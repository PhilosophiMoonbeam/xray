"""Finite xray operation metadata, callable schemas, discovery, and execution.

The application service owns the enabled-operation registry.  All eleven
repository operations are enabled by default, with change operations delegated
to one guarded service.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, TypeAlias, cast

from . import __version__ as XRAY_VERSION
from .core.indexer import XRayIndexer
from .core.replacement import GuardedChangeService
from .core.repository import OperationBudget, RepositoryError, RepositoryProvider, normalize_root
from .core.toolchain import ToolchainObservation, ToolchainProvider
from .models import (
    LANGUAGE_ORDER,
    MAX_REQUEST_JSON_BYTES,
    OPERATIONS,
    CallToolRequest,
    CapabilitiesArguments,
    CapabilitiesData,
    CatalogProvenance,
    ChangeApplyArguments,
    ChangeApplyData,
    ChangePlanArguments,
    ChangePlanData,
    ChangeRefineArguments,
    ChangeVerifyArguments,
    ChangeVerifyData,
    Coverage,
    Dependency,
    Error,
    ErrorDetails,
    ErrorValue,
    FindArguments,
    FindData,
    ImpactArguments,
    ImpactData,
    InterfaceArguments,
    InterfaceData,
    MapArguments,
    MapData,
    OperationContract,
    OperationSummary,
    PageFind,
    PageImpact,
    PageInterface,
    PageMap,
    PageRead,
    PageSearch,
    ReadArguments,
    ReadData,
    RepositoryProvenance,
    Request,
    Root,
    SearchArguments,
    SearchData,
    StrictModel,
    Success,
    default_limit_catalog,
    validate_request,
)
from .presentation import (
    SCHEMA_LIMIT,
    catalog_digest,
    fit_discovery,
    fit_error,
    fit_success,
    normalize_intent,
    repository_query_digest,
    request_json_size,
    sha256_bytes,
)
from .presentation import (
    plan_digest as canonical_plan_digest,
)

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
LOCAL_REF_PREFIX = "#/$defs/"
SCHEMA_INSTANCE_TYPES = {"object", "array", "string", "integer", "boolean"}
SCHEMA_NODE_KEYS = {
    "$ref",
    "type",
    "properties",
    "required",
    "additionalProperties",
    "const",
    "enum",
    "anyOf",
    "oneOf",
    "items",
    "prefixItems",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minLength",
    "maxLength",
    "pattern",
    "minimum",
    "maximum",
    "description",
    "default",
}
SCHEMA_DOCUMENT_KEYS = SCHEMA_NODE_KEYS | {"$schema", "$defs"}
_MAX_SCHEMA_DEFINITIONS = 64
_MAX_SCHEMA_NODES = 2048
_MAX_SCHEMA_DEPTH = 64
_MAX_ERROR_MESSAGE_BYTES = 512
_CAPABILITIES_DEFAULT_BYTES = 4096
_CAPABILITIES_DETAIL_BYTES = 65_536
_CAPABILITY_RESOURCES = (
    "skill://xray-progressive-discovery/SKILL.md",
    "skill://xray-progressive-discovery/{path*}",
    "xray://workflow",
)


class SchemaValidationError(ValueError):
    """A publication-schema error with a stable machine-readable category."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _schema_error(code: str, path: str, detail: str) -> None:
    raise SchemaValidationError(code, f"{path}: {detail}")


def _canonical_plain(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)


def canonicalize_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Canonicalize schema arrays while preserving prefixItems order."""

    def visit(value: Any) -> Any:
        if isinstance(value, dict):
            result = {key: visit(item) for key, item in value.items()}
            for key in ("required", "enum"):
                if key in result and isinstance(result[key], list):
                    result[key] = sorted(set(result[key]), key=_canonical_plain)
            for key in ("anyOf", "oneOf"):
                if key in result and isinstance(result[key], list):
                    unique: dict[str, Any] = {_canonical_plain(item): item for item in result[key]}
                    result[key] = [unique[item] for item in sorted(unique)]
            return result
        if isinstance(value, list):
            return [visit(item) for item in value]
        return value

    return cast(dict[str, Any], visit(copy.deepcopy(dict(schema))))


def _schema_ref_target(ref: Any, path: str) -> str:
    if not isinstance(ref, str) or not ref.startswith(LOCAL_REF_PREFIX):
        _schema_error("external_ref", f"{path}.$ref", repr(ref))
    target = ref[len(LOCAL_REF_PREFIX) :]
    if not target or "/" in target or target in {".", ".."}:
        _schema_error("invalid_ref", f"{path}.$ref", repr(ref))
    return target


def _project_reachable_definitions(root: Mapping[str, Any], definitions: Mapping[str, Any]) -> dict[str, Any]:
    """Project only definitions reachable from one operation root.

    References are followed as a graph rather than by recursively expanding
    schemas, so recursive ``$ref`` definitions remain intact.  A visited set
    terminates reference cycles, while active-container tracking still rejects
    malformed cyclic Python values.
    """
    available = dict(definitions)
    reachable: set[str] = set()
    active_containers: set[int] = set()

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            marker = id(value)
            if marker in active_containers:
                _schema_error("json_cycle", path, "cyclic Python container")
            active_containers.add(marker)
            try:
                if "$ref" in value:
                    target = _schema_ref_target(value["$ref"], path)
                    if target not in available:
                        _schema_error("unresolved_ref", f"{path}.$ref", target)
                    if target not in reachable:
                        reachable.add(target)
                        visit(available[target], f"{LOCAL_REF_PREFIX}{target}")
                for key, child in value.items():
                    if key != "$ref":
                        visit(child, f"{path}.{key}")
            finally:
                active_containers.remove(marker)
        elif isinstance(value, list):
            marker = id(value)
            if marker in active_containers:
                _schema_error("json_cycle", path, "cyclic Python container")
            active_containers.add(marker)
            try:
                for index, child in enumerate(value):
                    visit(child, f"{path}[{index}]")
            finally:
                active_containers.remove(marker)

    visit(root, "$")
    return {name: available[name] for name in sorted(reachable, key=lambda item: item.encode("utf-8"))}


def validate_schema_document(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the deliberately small closed Draft-2020-12 publication subset."""
    if not isinstance(schema, Mapping):
        _schema_error("invalid_document", "$", "document must be an object")
    schema = dict(schema)
    if schema.get("$schema") != SCHEMA_DIALECT:
        _schema_error("invalid_document", "$.$schema", f"expected {SCHEMA_DIALECT!r}")
    definitions = schema.get("$defs", {})
    if not isinstance(definitions, dict):
        _schema_error("invalid_definitions", "$.$defs", "definitions must be an object")
    if len(definitions) > _MAX_SCHEMA_DEFINITIONS:
        _schema_error("definition_limit", "$.$defs", str(len(definitions)))
    for name in definitions:
        if not isinstance(name, str) or not name or "/" in name or name in {".", ".."}:
            _schema_error("invalid_definition", "$.$defs", repr(name))

    references: dict[str | None, list[str]] = {None: []}
    references.update({name: [] for name in definitions})
    active: set[int] = set()
    stats = {"nodes": 0, "depth": 0}

    def count_json(value: Any, depth: int, path: str) -> None:
        stats["nodes"] += 1
        stats["depth"] = max(stats["depth"], depth)
        if stats["nodes"] > _MAX_SCHEMA_NODES:
            _schema_error("node_limit", path, str(stats["nodes"]))
        if depth > _MAX_SCHEMA_DEPTH:
            _schema_error("depth_limit", path, str(depth))
        if isinstance(value, (dict, list)):
            marker = id(value)
            if marker in active:
                _schema_error("json_cycle", path, "cyclic Python container")
            active.add(marker)
            try:
                if isinstance(value, dict):
                    for key, item in value.items():
                        count_json(item, depth + 1, f"{path}.{key}")
                else:
                    for index, item in enumerate(value):
                        count_json(item, depth + 1, f"{path}[{index}]")
            finally:
                active.remove(marker)

    count_json(schema, 1, "$")
    canonical_bytes_size = len(_canonical_plain(schema).encode("utf-8"))
    if canonical_bytes_size > SCHEMA_LIMIT:
        _schema_error("schema_size_limit", "$", str(canonical_bytes_size))

    def validate_node(node: Any, path: str, owner: str | None, *, document: bool = False) -> None:
        if not isinstance(node, dict):
            _schema_error("invalid_node", path, "schema node must be an object")
        unknown = sorted(set(node) - (SCHEMA_DOCUMENT_KEYS if document else SCHEMA_NODE_KEYS))
        if unknown:
            _schema_error("invalid_keyword", path, ",".join(unknown))
        if document and "$schema" not in node:
            _schema_error("invalid_document", path, "missing $schema")
        if "$ref" in node:
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith(LOCAL_REF_PREFIX):
                _schema_error("external_ref", f"{path}.$ref", repr(ref))
            target = ref[len(LOCAL_REF_PREFIX) :]
            if not target or "/" in target or target in {".", ".."}:
                _schema_error("invalid_ref", f"{path}.$ref", repr(ref))
            references[owner].append(target)
        if "type" in node:
            node_type = node["type"]
            if not isinstance(node_type, str) or node_type not in SCHEMA_INSTANCE_TYPES:
                _schema_error("invalid_type", f"{path}.type", repr(node_type))
            if node_type == "object" and node.get("additionalProperties") is not False:
                _schema_error("open_object", path, "modeled objects must set additionalProperties=false")
        if "properties" in node:
            properties = node["properties"]
            if not isinstance(properties, dict):
                _schema_error("invalid_properties", f"{path}.properties", "must be an object")
            for key in sorted(properties):
                if not isinstance(key, str):
                    _schema_error("invalid_properties", f"{path}.properties", repr(key))
                validate_node(properties[key], f"{path}.properties.{key}", owner)
        if "required" in node:
            required = node["required"]
            if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
                _schema_error("invalid_required", f"{path}.required", "must be a string array")
            if len(set(required)) != len(required):
                _schema_error("invalid_required", f"{path}.required", "duplicate names")
        if "additionalProperties" in node and not isinstance(node["additionalProperties"], (bool, dict)):
            _schema_error(
                "invalid_additional_properties", f"{path}.additionalProperties", repr(node["additionalProperties"])
            )
        for key in ("anyOf", "oneOf", "prefixItems"):
            if key in node:
                if not isinstance(node[key], list):
                    _schema_error("invalid_branches", f"{path}.{key}", "must be an array")
                for index, branch in enumerate(node[key]):
                    validate_node(branch, f"{path}.{key}[{index}]", owner)
        if "items" in node:
            validate_node(node["items"], f"{path}.items", owner)
        if "additionalProperties" in node and isinstance(node["additionalProperties"], dict):
            validate_node(node["additionalProperties"], f"{path}.additionalProperties", owner)
        if document and "$defs" in node:
            return
        if "$defs" in node:
            _schema_error("invalid_keyword", path, "$defs is only valid at the document root")

    validate_node(schema, "$", None, document=True)
    if schema.get("type") != "object":
        _schema_error("invalid_document", "$.type", "root must be object")
    for name in sorted(definitions):
        validate_node(definitions[name], f"{LOCAL_REF_PREFIX}{name}", name)
    for owner, refs in references.items():
        for target in refs:
            if target not in definitions:
                _schema_error("unresolved_ref", owner or "$", target)

    depth_cache: dict[str, int] = {}

    def ref_depth(name: str, stack: tuple[str, ...] = ()) -> int:
        if name in stack:
            _schema_error("cyclic_ref", f"{LOCAL_REF_PREFIX}{name}", " -> ".join((*stack, name)))
        if name in depth_cache:
            return depth_cache[name]
        values = [ref_depth(target, (*stack, name)) for target in references[name]]
        depth_cache[name] = 1 + max(values, default=0)
        return depth_cache[name]

    reference_depth = max((ref_depth(name) for name in definitions), default=0)
    if max(stats["depth"], reference_depth) > _MAX_SCHEMA_DEPTH:
        _schema_error("depth_limit", "$", str(max(stats["depth"], reference_depth)))
    return {
        "closure": "closed_acyclic",
        "definitions": len(definitions),
        "depth": max(stats["depth"], reference_depth),
        "nodes": stats["nodes"],
        "canonical_bytes": canonical_bytes_size,
    }


def _closed(properties: dict[str, Any], required: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        out["required"] = required
    out.update(extra)
    return out


def _schema_defs() -> dict[str, Any]:
    digest = {"type": "string", "pattern": "^[0-9a-f]{64}$", "description": "lowercase SHA-256 digest"}
    file_path = {
        "type": "string",
        "minLength": 1,
        "maxLength": 4096,
        "pattern": "^(?!/)(?!.*(^|/)\\.\\.?(/|$)).+$",
        "description": (
            "contained repository-relative file POSIX path; UTF-8 byte bound and "
            "symlink checks are typed-boundary constraints"
        ),
    }
    rel_path = {
        "anyOf": [{"const": "."}, {"$ref": "#/$defs/filePath"}],
        "description": "'.' is permitted for root or directory scope.",
    }

    defs: dict[str, Any] = {
        "digest": digest,
        "relPath": rel_path,
        "filePath": file_path,
        "language": {"type": "string", "enum": ["go", "javascript", "python", "typescript"]},
        "visibility": {"type": "string", "enum": ["private", "public", "unknown"]},
        "execution": _closed(
            {
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120, "default": 30},
                "cache": {"type": "string", "enum": ["auto", "off"], "default": "auto"},
            },
            [],
        ),
        "root": _closed(
            {
                "path": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 4096,
                    "description": "normalized absolute path; UTF-8 byte bound enforced outside JSON Schema",
                },
                "id": {"$ref": "#/$defs/digest"},
            },
            ["path", "id"],
        ),
        "selection": _closed(
            {
                "paths": {"type": "array", "items": {"$ref": "#/$defs/relPath"}, "maxItems": 100000},
                "globs": {"type": "array", "items": {"type": "string", "maxLength": 4096}},
                "languages": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/language"},
                    "uniqueItems": True,
                    "maxItems": 4,
                },
                "exclusions": {"type": "string", "enum": ["default", "none"], "default": "default"},
            },
            ["paths", "exclusions"],
        ),
        "symbolRef": _closed(
            {
                "kind": {"const": "symbol"},
                "root_id": {"$ref": "#/$defs/digest"},
                "path": {"$ref": "#/$defs/filePath"},
                "file_digest": {"$ref": "#/$defs/digest"},
                "start": {"type": "integer", "minimum": 0},
                "end": {"type": "integer", "minimum": 0, "description": "must be >= start at typed boundary"},
                "symbol_id": {"$ref": "#/$defs/digest"},
                "analyzer_id": {"$ref": "#/$defs/digest"},
            },
            ["kind", "root_id", "path", "file_digest", "start", "end", "symbol_id", "analyzer_id"],
        ),
        "sourceRef": _closed(
            {
                "kind": {"const": "source"},
                "root_id": {"$ref": "#/$defs/digest"},
                "path": {"$ref": "#/$defs/filePath"},
                "file_digest": {"$ref": "#/$defs/digest"},
                "start": {"type": "integer", "minimum": 0},
                "end": {"type": "integer", "minimum": 0, "description": "must be >= start at typed boundary"},
            },
            ["kind", "root_id", "path", "file_digest", "start", "end"],
        ),
        "occurrenceRef": _closed(
            {
                "kind": {"const": "occurrence"},
                "root_id": {"$ref": "#/$defs/digest"},
                "path": {"$ref": "#/$defs/filePath"},
                "file_digest": {"$ref": "#/$defs/digest"},
                "start": {"type": "integer", "minimum": 0},
                "end": {"type": "integer", "minimum": 0, "description": "must be >= start at typed boundary"},
                "occurrence_id": {"$ref": "#/$defs/digest"},
            },
            ["kind", "root_id", "path", "file_digest", "start", "end", "occurrence_id"],
        ),
        "locationTarget": _closed(
            {
                "kind": {"const": "location"},
                "path": {"$ref": "#/$defs/filePath"},
                "line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1, "description": "must be >= line at typed boundary"},
                "column": {"type": "integer", "minimum": 1, "description": "one-based UTF-8-byte column"},
            },
            ["kind", "path", "line"],
        ),
        "ruleInput": _closed(
            {"kind": {"type": "string", "enum": ["config", "rule"]}, "path": {"$ref": "#/$defs/filePath"}},
            ["kind", "path"],
        ),
        "fileTarget": _closed({"kind": {"const": "file"}, "path": {"$ref": "#/$defs/filePath"}}, ["kind", "path"]),
        "patternSource": _closed(
            {
                "kind": {"const": "pattern"},
                "pattern": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 8192,
                    "description": "UTF-8 byte bound enforced outside JSON Schema",
                },
                "replacement": {
                    "type": "string",
                    "maxLength": 8192,
                    "description": "UTF-8 byte bound enforced outside JSON Schema",
                },
                "language": {"$ref": "#/$defs/language"},
            },
            ["kind", "pattern", "replacement", "language"],
        ),
        "ruleSource": _closed({"kind": {"const": "rule"}, "input": {"$ref": "#/$defs/ruleInput"}}, ["kind", "input"]),
        "readTarget": {
            "anyOf": [
                {"$ref": "#/$defs/sourceRef"},
                {"$ref": "#/$defs/symbolRef"},
                {"$ref": "#/$defs/occurrenceRef"},
                {"$ref": "#/$defs/locationTarget"},
            ]
        },
        "interfaceTarget": {"anyOf": [{"$ref": "#/$defs/fileTarget"}, {"$ref": "#/$defs/symbolRef"}]},
        "planBounds": _closed(
            {
                "max_candidates": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 100},
                "max_files": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                "max_bytes": {"type": "integer", "minimum": 4096, "maximum": 262144, "default": 32768},
                "max_file_bytes": {"const": 10485760},
                "max_total_preimage_bytes": {"const": 52428800},
                "max_total_postimage_bytes": {"const": 52428800},
            },
            [
                "max_candidates",
                "max_files",
                "max_bytes",
                "max_file_bytes",
                "max_total_preimage_bytes",
                "max_total_postimage_bytes",
            ],
        ),
        "acknowledgements": _closed(
            {
                "dirty_affected": {"type": "boolean", "default": False},
                "new_parse_errors": {"type": "boolean", "default": False},
            },
            [],
        ),
        "range": _closed(
            {
                "start": _closed(
                    {
                        "byte": {"type": "integer", "minimum": 0},
                        "line": {"type": "integer", "minimum": 1},
                        "column": {"type": "integer", "minimum": 1},
                    },
                    ["byte", "line", "column"],
                ),
                "end": _closed(
                    {
                        "byte": {"type": "integer", "minimum": 0},
                        "line": {"type": "integer", "minimum": 1},
                        "column": {"type": "integer", "minimum": 1},
                    },
                    ["byte", "line", "column"],
                ),
            },
            ["start", "end"],
        ),
        "syntaxDiagnostic": _closed(
            {
                "range": {"$ref": "#/$defs/range"},
                "signature": {"$ref": "#/$defs/digest"},
                "text": {"type": "string", "maxLength": 200},
            },
            ["range", "signature", "text"],
        ),
        "syntaxEvidence": _closed(
            {
                "analyzer": {"$ref": "#/$defs/digest"},
                "language": {"$ref": "#/$defs/language"},
                "diagnostic_count": {"type": "integer", "minimum": 0},
                "fingerprint": {"$ref": "#/$defs/digest"},
                "diagnostics": {"type": "array", "items": {"$ref": "#/$defs/syntaxDiagnostic"}, "maxItems": 50},
            },
            ["analyzer", "language", "diagnostic_count", "fingerprint", "diagnostics"],
        ),
        "manifestItem": _closed(
            {
                "path": {"$ref": "#/$defs/filePath"},
                "bytes": {"type": "integer", "minimum": 0},
                "sha256": {"$ref": "#/$defs/digest"},
            },
            ["path", "bytes", "sha256"],
        ),
        "policyItem": _closed(
            {"name": {"type": "string", "minLength": 1, "maxLength": 128}, "sha256": {"$ref": "#/$defs/digest"}},
            ["name", "sha256"],
        ),
        "inputManifest": _closed(
            {
                "sources": {"type": "array", "items": {"$ref": "#/$defs/manifestItem"}, "maxItems": 20000},
                "configuration": {"type": "array", "items": {"$ref": "#/$defs/manifestItem"}, "maxItems": 1024},
                "policies": {"type": "array", "items": {"$ref": "#/$defs/policyItem"}},
                "toolchain": {"$ref": "#/$defs/digest"},
            },
            ["sources", "configuration", "policies", "toolchain"],
        ),
        "repositoryProvenance": _closed(
            {
                "kind": {"const": "repository"},
                "consistency": {"const": "captured_read_set"},
                "query": {"$ref": "#/$defs/digest"},
                "selection": {"$ref": "#/$defs/digest"},
                "snapshot": {"$ref": "#/$defs/digest"},
                "toolchain": {"$ref": "#/$defs/digest"},
            },
            ["kind", "consistency", "query", "selection", "snapshot", "toolchain"],
        ),
        "baseline": {
            "anyOf": [
                _closed(
                    {
                        "kind": {"const": "git"},
                        "dirty_affected": {"type": "array", "items": {"$ref": "#/$defs/filePath"}},
                    },
                    ["kind", "dirty_affected"],
                ),
                _closed({"kind": {"const": "unmanaged"}}, ["kind"]),
            ]
        },
        "eligibility": _closed(
            {
                "applicable": {"type": "boolean"},
                "reasons": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["dirty_affected", "new_parse_errors", "no_candidates", "no_changes"],
                    },
                    "uniqueItems": True,
                },
            },
            ["applicable", "reasons"],
        ),
        "planEdit": _closed(
            {
                "edit_id": {"$ref": "#/$defs/digest"},
                "path": {"$ref": "#/$defs/filePath"},
                "start": {"type": "integer", "minimum": 0},
                "end": {"type": "integer", "minimum": 0, "description": "must be >= start at typed boundary"},
                "before_sha256": {"$ref": "#/$defs/digest"},
                "after_sha256": {"$ref": "#/$defs/digest"},
                "changed": {"type": "boolean"},
            },
            ["edit_id", "path", "start", "end", "before_sha256", "after_sha256", "changed"],
        ),
        "planFile": _closed(
            {
                "path": {"$ref": "#/$defs/filePath"},
                "preimage_sha256": {"$ref": "#/$defs/digest"},
                "postimage_sha256": {"$ref": "#/$defs/digest"},
                "preimage_bytes": {"type": "integer", "minimum": 0},
                "postimage_bytes": {"type": "integer", "minimum": 0},
                "mode": {"type": "integer", "minimum": 0},
                "syntax_before": {"$ref": "#/$defs/syntaxEvidence"},
                "syntax_after": {"$ref": "#/$defs/syntaxEvidence"},
                "new_diagnostic_count": {"type": "integer", "minimum": 0},
                "diff": {"type": "string"},
            },
            [
                "path",
                "preimage_sha256",
                "postimage_sha256",
                "preimage_bytes",
                "postimage_bytes",
                "mode",
                "syntax_before",
                "syntax_after",
                "new_diagnostic_count",
                "diff",
            ],
        ),
        "changePlan": _closed(
            {
                "plan_schema": {"const": "xray.change.v1"},
                "root": {"$ref": "#/$defs/root"},
                "selection": {"$ref": "#/$defs/selection"},
                "source": {"anyOf": [{"$ref": "#/$defs/patternSource"}, {"$ref": "#/$defs/ruleSource"}]},
                "provenance": {"$ref": "#/$defs/repositoryProvenance"},
                "inputs": {"$ref": "#/$defs/inputManifest"},
                "bounds": {"$ref": "#/$defs/planBounds"},
                "chosen": {
                    "anyOf": [
                        _closed({"kind": {"const": "all"}}, ["kind"]),
                        _closed(
                            {
                                "kind": {"const": "edits"},
                                "ids": {"type": "array", "items": {"$ref": "#/$defs/digest"}, "maxItems": 1000},
                            },
                            ["kind", "ids"],
                        ),
                    ]
                },
                "files": {"type": "array", "items": {"$ref": "#/$defs/planFile"}, "maxItems": 100},
                "edits": {"type": "array", "items": {"$ref": "#/$defs/planEdit"}, "maxItems": 1000},
                "baseline": {"$ref": "#/$defs/baseline"},
                "acknowledgements": {"$ref": "#/$defs/acknowledgements"},
                "eligibility": {"$ref": "#/$defs/eligibility"},
                "plan_digest": {"$ref": "#/$defs/digest"},
            },
            [
                "plan_schema",
                "root",
                "selection",
                "source",
                "provenance",
                "inputs",
                "bounds",
                "chosen",
                "files",
                "edits",
                "baseline",
                "acknowledgements",
                "eligibility",
                "plan_digest",
            ],
        ),
    }
    return defs


def _page_schema(
    default_bytes: int,
    hard_bytes: int,
    default_items: int | None = None,
    hard_items: int | None = None,
    *,
    read: bool = False,
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "max_bytes": {"type": "integer", "minimum": 4096, "maximum": hard_bytes, "default": default_bytes},
        "cursor": {"type": "string", "maxLength": 4096},
    }
    if default_items is not None and hard_items is not None:
        properties["limit"] = {"type": "integer", "minimum": 1, "maximum": hard_items, "default": default_items}
    if read:
        properties["max_lines"] = {"type": "integer", "minimum": 1, "maximum": 256, "default": 64}
        properties["source_bytes"] = {"type": "integer", "minimum": 1, "maximum": 32768, "default": 8192}
    return _closed(properties, [])


def operation_query_schema(op: str) -> dict[str, Any]:
    if op == "map":
        return _closed(
            {
                "focus": {"type": "array", "items": {"$ref": "#/$defs/relPath"}, "default": ["."]},
                "depth": {"anyOf": [{"type": "integer", "minimum": 0, "maximum": 64}, {"const": "all"}], "default": 2},
                "context": {"type": "string", "enum": ["ancestors", "none"], "default": "none"},
                "exclusions": {"type": "string", "enum": ["default", "none"], "default": "default"},
            },
            [],
        )
    if op == "find":
        return _closed(
            {
                "text": {"type": "string", "minLength": 1, "maxLength": 8192},
                "selection": {"$ref": "#/$defs/selection"},
                "match": {"type": "string", "enum": ["exact", "fuzzy", "name"], "default": "name"},
                "kinds": {"type": "array", "items": {"type": "string", "minLength": 1}},
                "visibility": {"type": "array", "items": {"$ref": "#/$defs/visibility"}, "uniqueItems": True},
            },
            ["text"],
        )
    if op == "interface":
        file_common = {
            "sections": {
                "type": "array",
                "items": {"type": "string", "enum": ["exports", "imports", "symbols"]},
                "uniqueItems": True,
                "maxItems": 3,
                "default": ["symbols"],
            },
            "member_depth": {"type": "integer", "enum": [0, 1], "default": 1},
            "documentation": {"type": "boolean", "default": False},
        }
        symbol_common = {
            "sections": {
                "type": "array",
                "items": {"const": "symbols"},
                "minItems": 1,
                "maxItems": 1,
                "uniqueItems": True,
                "default": ["symbols"],
            },
            "member_depth": {"type": "integer", "enum": [0, 1], "default": 1},
            "documentation": {"type": "boolean", "default": False},
        }
        file_query = _closed(
            {
                "target": {"$ref": "#/$defs/fileTarget"},
                **file_common,
                "kinds": {"type": "array", "items": {"type": "string", "minLength": 1}},
                "visibility": {"type": "array", "items": {"$ref": "#/$defs/visibility"}, "uniqueItems": True},
            },
            ["target"],
        )
        symbol_query = _closed({"target": {"$ref": "#/$defs/symbolRef"}, **symbol_common}, ["target"])
        return {"anyOf": [file_query, symbol_query]}
    if op == "read":
        return _closed(
            {
                "targets": {"type": "array", "items": {"$ref": "#/$defs/readTarget"}, "minItems": 1, "maxItems": 8},
                "context_lines": {"type": "integer", "minimum": 0, "maximum": 10, "default": 0},
                "include_enclosing": {"type": "boolean", "default": True},
            },
            ["targets"],
        )
    if op == "impact":
        return _closed(
            {
                "target": {"$ref": "#/$defs/symbolRef"},
                "selection": {"$ref": "#/$defs/selection"},
                "mode": {"type": "string", "enum": ["lexical", "syntax"], "default": "syntax"},
            },
            ["target"],
        )
    if op == "search":
        pattern = {
            "type": "object",
            "properties": {
                "kind": {"const": "pattern"},
                "pattern": {"type": "string", "minLength": 1, "maxLength": 8192},
                "language": {"$ref": "#/$defs/language"},
            },
            "required": ["kind", "pattern", "language"],
            "additionalProperties": False,
        }
        literal = {
            "type": "object",
            "properties": {"kind": {"const": "literal"}, "text": {"type": "string", "minLength": 1, "maxLength": 8192}},
            "required": ["kind", "text"],
            "additionalProperties": False,
        }
        rule = {
            "type": "object",
            "properties": {"kind": {"const": "rule"}, "input": {"$ref": "#/$defs/ruleInput"}},
            "required": ["kind", "input"],
            "additionalProperties": False,
        }
        return _closed(
            {
                "selection": {"$ref": "#/$defs/selection"},
                "source": {"anyOf": [pattern, literal, rule]},
            },
            ["source"],
        )
    if op == "change_plan":
        return _closed(
            {
                "selection": {"$ref": "#/$defs/selection"},
                "source": {"anyOf": [{"$ref": "#/$defs/patternSource"}, {"$ref": "#/$defs/ruleSource"}]},
                "bounds": {"$ref": "#/$defs/planBounds"},
                "acknowledgements": {"$ref": "#/$defs/acknowledgements"},
            },
            ["source"],
        )
    if op == "change_refine":
        return _closed(
            {
                "plan": {"$ref": "#/$defs/changePlan"},
                "edit_ids": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/digest"},
                    "uniqueItems": True,
                    "maxItems": 1000,
                },
            },
            ["plan", "edit_ids"],
        )
    if op in {"change_verify", "change_apply"}:
        return _closed(
            {"plan": {"$ref": "#/$defs/changePlan"}, "expected_digest": {"$ref": "#/$defs/digest"}},
            ["plan", "expected_digest"],
        )
    if op == "capabilities":
        return _closed({"detail": {"type": "string", "enum": ["detail", "summary"], "default": "summary"}}, [])
    raise ValueError(op)


def schema_for_operation(op: str) -> dict[str, Any]:
    if op not in OPERATIONS:
        raise ValueError(f"unknown operation {op!r}")
    properties: dict[str, Any] = {
        "root": {
            "type": "string",
            "minLength": 1,
            "maxLength": 4096,
            "description": "normalized absolute root; containment and UTF-8 byte limits are typed-boundary constraints",
        },
        "query": operation_query_schema(op),
        "execution": {"$ref": "#/$defs/execution"},
    }
    required = ["query"]
    if op != "capabilities":
        required.insert(0, "root")
    if op in {"map", "find", "interface", "read", "impact", "search"}:
        if op == "read":
            properties["page"] = {"$ref": "#/$defs/page_read"}
        else:
            properties["page"] = {"$ref": f"#/$defs/page_{op}"}
    definitions = _schema_defs()
    definitions.update(
        {
            "page_map": _page_schema(8192, 65536, 100, 1000),
            "page_find": _page_schema(6144, 65536, 10, 100),
            "page_interface": _page_schema(8192, 65536, 20, 200),
            "page_search": _page_schema(8192, 65536, 20, 1000),
            "page_impact": _page_schema(8192, 65536, 20, 1000),
            "page_read": _page_schema(12288, 65536, read=True),
        }
    )
    root = _closed(properties, required)
    projected = _project_reachable_definitions(root, definitions)
    schema = {"$schema": SCHEMA_DIALECT, "$defs": projected}
    schema.update(root)
    return schema


DESCRIPTION_TEMPLATE = "Execute the {operation} operation with a complete closed argument schema."


class _FrozenDict(dict[Any, Any]):
    """A dict-shaped JSON container that rejects every in-place mutation."""

    def _blocked(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("cached operation contracts are immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = cast(Any, _blocked)

    def __ior__(self, other: Any) -> _FrozenDict:
        self._blocked(other)
        return self

    def __deepcopy__(self, _memo: dict[int, Any]) -> _FrozenDict:
        return self


class _FrozenList(list[Any]):
    """A list-shaped JSON container that rejects every in-place mutation."""

    def _blocked(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("cached operation contracts are immutable")

    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = cast(Any, _blocked)

    def __iadd__(self, other: Any) -> _FrozenList:
        self._blocked(other)
        return self

    def __imul__(self, other: Any) -> _FrozenList:
        self._blocked(other)
        return self

    def __deepcopy__(self, _memo: dict[int, Any]) -> _FrozenList:
        return self


def _freeze_json(value: Any) -> Any:
    if isinstance(value, (_FrozenDict, _FrozenList)):
        return value
    if isinstance(value, Mapping):
        return _FrozenDict({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return _FrozenList(_freeze_json(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


def _freeze_contract(contract: OperationContract) -> OperationContract:
    """Freeze mutable JSON containers beneath a cached public contract."""

    schema = contract.input_schema
    for field_name in type(schema).model_fields:
        value = getattr(schema, field_name)
        if isinstance(value, (Mapping, list, tuple)):
            object.__setattr__(schema, field_name, _freeze_json(value))
    return contract


def _build_contracts(specs: tuple[OperationSpec, ...]) -> tuple[OperationContract, ...]:
    return tuple(sorted((spec.contract() for spec in specs), key=lambda item: item.name.encode("utf-8")))


@dataclass(frozen=True, slots=True)
class OperationSpec:
    name: str
    description: str
    mutation: str
    cli: str
    arguments_type: type[StrictModel]
    result_type: type[StrictModel]
    handler: Callable[[Any], Success | Error] | None = field(default=None, compare=False, repr=False)

    def contract(self) -> OperationContract:
        schema = schema_for_operation(self.name)
        validate_schema_document(schema)
        return _freeze_contract(
            OperationContract.model_validate(
                {
                    "name": self.name,
                    "description": self.description,
                    "mutation": self.mutation,
                    "input_schema": schema,
                }
            )
        )


_ARGUMENT_TYPES: dict[str, type[StrictModel]] = {
    "map": MapArguments,
    "find": FindArguments,
    "interface": InterfaceArguments,
    "read": ReadArguments,
    "impact": ImpactArguments,
    "search": SearchArguments,
    "change_plan": ChangePlanArguments,
    "change_refine": ChangeRefineArguments,
    "change_verify": ChangeVerifyArguments,
    "change_apply": ChangeApplyArguments,
    "capabilities": CapabilitiesArguments,
}
_RESULT_TYPES: dict[str, type[StrictModel]] = {
    "map": MapData,
    "find": FindData,
    "interface": InterfaceData,
    "read": ReadData,
    "impact": ImpactData,
    "search": SearchData,
    "change_plan": ChangePlanData,
    "change_refine": ChangePlanData,
    "change_verify": ChangeVerifyData,
    "change_apply": ChangeApplyData,
    "capabilities": CapabilitiesData,
}


def _future_specs() -> tuple[OperationSpec, ...]:
    return tuple(
        OperationSpec(
            name=name,
            description=DESCRIPTION_TEMPLATE.format(operation=name),
            mutation="guarded_mutation" if name == "change_apply" else "read_only",
            cli=name,
            arguments_type=_ARGUMENT_TYPES[name],
            result_type=_RESULT_TYPES[name],
        )
        for name in OPERATIONS
    )


FUTURE_OPERATION_SPECS: tuple[OperationSpec, ...] = _future_specs()
FUTURE_OPERATION_BY_NAME: Mapping[str, OperationSpec] = MappingProxyType(
    {spec.name: spec for spec in FUTURE_OPERATION_SPECS}
)


@lru_cache(maxsize=1)
def _cached_default_contracts() -> tuple[OperationContract, ...]:
    """Build the enabled catalog once and retain only frozen contract values."""

    return _build_contracts(FUTURE_OPERATION_SPECS)


def future_operation_specs() -> tuple[OperationSpec, ...]:
    return FUTURE_OPERATION_SPECS


def enabled_operation_specs(
    handlers: Mapping[str, Callable[[Any], Success | Error]] | None = None,
) -> tuple[OperationSpec, ...]:
    selected = default_handlers() if handlers is None else handlers
    return tuple(
        replace(spec, handler=selected[spec.name])
        for spec in FUTURE_OPERATION_SPECS
        if spec.name in selected and callable(selected[spec.name])
    )


def operation_contracts(
    *, handlers: Mapping[str, Callable[[Any], Success | Error]] | None = None, include_disabled: bool = False
) -> tuple[OperationContract, ...]:
    if handlers is None:
        # The default catalog is immutable and independent of a handler
        # instance; disabled mode has the same complete finite spec set.
        return _cached_default_contracts()
    specs = FUTURE_OPERATION_SPECS if include_disabled else enabled_operation_specs(handlers)
    return _build_contracts(specs)


def schema_documents() -> Mapping[str, dict[str, Any]]:
    return MappingProxyType({name: schema_for_operation(name) for name in OPERATIONS})


def discovery_artifact_digest() -> str:
    return sha256_bytes(Path(__file__).read_bytes())


@lru_cache(maxsize=1)
def _cached_catalog_identity() -> str:
    contracts = [contract.to_payload() for contract in operation_contracts()]
    return catalog_digest(contracts, discovery_artifact_digest())


def catalog_identity(
    *, handlers: Mapping[str, Callable[[Any], Success | Error]] | None = None, include_disabled: bool = False
) -> str:
    if handlers is None and not include_disabled:
        return _cached_catalog_identity()
    contracts = [
        contract.to_payload() for contract in operation_contracts(handlers=handlers, include_disabled=include_disabled)
    ]
    return catalog_digest(contracts, discovery_artifact_digest())


RANKING_METADATA = MappingProxyType(
    {
        "version": "xray.discovery.ranking.v1",
        "ordinary_change": ("change_plan", "change_refine", "change_verify", "change_apply"),
        "explicit_apply": ("change_apply",),
        "lookup": ("find", "interface", "read", "map"),
        "blast_radius": ("impact", "search"),
        "workflow": ("capabilities",),
    }
)


_INTENT_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_CAPABILITY_TERMS = frozenset(
    {
        "ability",
        "abilities",
        "available",
        "catalog",
        "capabilities",
        "features",
        "health",
        "healthy",
        "limits",
        "readiness",
        "server",
        "support",
        "supported",
        "tools",
    }
)
_CHANGE_TERMS = frozenset(
    {
        "acknowledged",
        "approved",
        "applied",
        "applying",
        "apply",
        "artifact",
        "change",
        "changing",
        "commit",
        "digest",
        "edit",
        "edits",
        "execute",
        "guarded",
        "guards",
        "mutation",
        "mutate",
        "patch",
        "plan",
        "plans",
        "postimage",
        "postimages",
        "proposal",
        "propose",
        "refactor",
        "refine",
        "replace",
        "replacement",
        "replacing",
        "rename",
        "reviewed",
        "transform",
        "transformation",
        "write",
        "writes",
    }
)
_MAP_TERMS = frozenset(
    {
        "directory",
        "directories",
        "folder",
        "folders",
        "layout",
        "map",
        "namespace",
        "outline",
        "path",
        "paths",
        "project",
        "repo",
        "repository",
        "root",
        "shallow",
        "structure",
        "top",
        "tree",
    }
)
_INTERFACE_TERMS = frozenset(
    {
        "api",
        "class",
        "expose",
        "exposes",
        "exported",
        "exports",
        "imported",
        "imports",
        "interface",
        "member",
        "members",
        "module",
        "public",
        "section",
        "sections",
        "surface",
    }
)
_IMPACT_TERMS = frozenset(
    {
        "affected",
        "blast",
        "break",
        "breaks",
        "caller",
        "callers",
        "dependents",
        "impact",
        "radius",
        "reference",
        "references",
        "trace",
        "use",
        "used",
        "uses",
    }
)
_SEARCH_TERMS = frozenset(
    {
        "calls",
        "configured",
        "expression",
        "literal",
        "matching",
        "occurrence",
        "occurrences",
        "pattern",
        "rule",
        "rules",
        "scan",
        "search",
        "spelling",
        "syntax",
    }
)
_READ_TERMS = frozenset(
    {
        "body",
        "bodies",
        "bytes",
        "captured",
        "context",
        "display",
        "fetch",
        "implementation",
        "line",
        "lines",
        "location",
        "open",
        "range",
        "read",
        "retrieve",
        "unmodified",
    }
)
_FIND_TERMS = frozenset(
    {
        "called",
        "declare",
        "declared",
        "declares",
        "declaration",
        "declarations",
        "defined",
        "definition",
        "find",
        "function",
        "identify",
        "locate",
        "lookup",
        "name",
        "named",
        "owner",
        "qualified",
        "resolve",
        "signature",
        "symbol",
        "symbols",
        "where",
    }
)
_PLAN_TERMS = frozenset(
    {"build", "calculate", "complete", "draft", "generate", "prepare", "preview", "propose", "safe"}
)
_REFINE_TERMS = frozenset({"adjust", "narrow", "reduce", "refine", "revise", "smaller", "update"})
_VERIFY_TERMS = frozenset(
    {
        "applicable",
        "check",
        "confirm",
        "current",
        "digest",
        "ensure",
        "guard",
        "guards",
        "matches",
        "postimage",
        "postimages",
        "review",
        "safely",
        "validate",
        "verify",
    }
)
_APPLY_TERMS = frozenset(
    {
        "applied",
        "applying",
        "apply",
        "carry",
        "commit",
        "execute",
        "make",
        "mutate",
        "perform",
        "run",
        "write",
        "writes",
    }
)
_INSPECTION_TERMS = frozenset(
    {
        "checked",
        "configured",
        "inspect",
        "matching",
        "occurrence",
        "occurrences",
        "run",
        "scan",
        "search",
        "use",
    }
)
_RULE_LIKE_TERMS = frozenset({"expression", "literal", "pattern", "rule", "rules", "syntax"})
_TRANSFORM_TERMS = frozenset(
    {"change", "refactor", "rename", "replace", "replacement", "replacing", "transform", "transformation"}
)

_RANKING_CONCEPTS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "map": _MAP_TERMS,
        "find": _FIND_TERMS - frozenset({"lookup"}),
        "interface": _INTERFACE_TERMS | (_FIND_TERMS - frozenset({"lookup"})),
        "read": _READ_TERMS | frozenset({"lookup", "source"}),
        "impact": _IMPACT_TERMS | frozenset({"calls", "occurrences"}),
        "search": _SEARCH_TERMS | frozenset({"find", "source", "text"}),
        "change_plan": _CHANGE_TERMS | _PLAN_TERMS,
        "change_refine": _CHANGE_TERMS | _REFINE_TERMS,
        "change_verify": _CHANGE_TERMS | _VERIFY_TERMS,
        "change_apply": _CHANGE_TERMS | _APPLY_TERMS,
        "capabilities": _CAPABILITY_TERMS | frozenset({"operation", "operations"}),
    }
)


def _intent_tokens(normalized: str) -> tuple[str, ...]:
    return tuple(_INTENT_TOKEN_RE.findall(normalized))


def _has_any(words: set[str], terms: frozenset[str]) -> bool:
    return not words.isdisjoint(terms)


def _has_phrase(tokens: tuple[str, ...], *phrase: str) -> bool:
    width = len(phrase)
    return any(tokens[index : index + width] == phrase for index in range(len(tokens) - width + 1))


def _is_capability_intent(words: set[str]) -> bool:
    if not _has_any(words, _CAPABILITY_TERMS):
        return False
    blockers = _CHANGE_TERMS | _MAP_TERMS | _INTERFACE_TERMS | _IMPACT_TERMS | _SEARCH_TERMS | _READ_TERMS | _FIND_TERMS
    # Health/readiness/catalog wording is unambiguous unless the same intent
    # carries a concrete repository operation.
    return not _has_any(words, blockers - {"tools", "server", "operation", "operations"})


def _is_change_intent(words: set[str]) -> bool:
    return _has_any(words, _CHANGE_TERMS)


def _is_negative_execution(tokens: tuple[str, ...]) -> bool:
    return (
        _has_phrase(tokens, "without", "applying")
        or _has_phrase(tokens, "without", "apply")
        or _has_phrase(tokens, "without", "writing")
        or _has_phrase(tokens, "before", "apply")
        or _has_phrase(tokens, "before", "applying")
    )


def _is_refine_intent(words: set[str], tokens: tuple[str, ...]) -> bool:
    if _has_any(words, _REFINE_TERMS):
        return True
    if _has_phrase(tokens, "edit", "ids") or _has_phrase(tokens, "edit", "id"):
        return True
    if _has_phrase(tokens, "first", "two", "edits") or _has_phrase(tokens, "first", "edits"):
        return True
    if _has_phrase(tokens, "smaller", "set") or _has_phrase(tokens, "smaller", "scope"):
        return True
    if _has_phrase(tokens, "existing", "plan") or _has_phrase(tokens, "candidate", "artifact"):
        return True
    if _has_phrase(tokens, "reviewed", "selection") or _has_phrase(tokens, "plan", "scope"):
        return True
    return False


def _is_verify_intent(words: set[str]) -> bool:
    return _has_any(words, _VERIFY_TERMS) and not _has_any(words, _APPLY_TERMS)


def _is_apply_intent(words: set[str]) -> bool:
    if _has_any(words, _APPLY_TERMS):
        return True
    return "approved" in words and _has_any(words, _CHANGE_TERMS - {"approved", "reviewed"})


def _is_rule_inspection(words: set[str]) -> bool:
    return (
        _has_any(words, _RULE_LIKE_TERMS)
        and _has_any(words, _INSPECTION_TERMS)
        and not _has_any(words, _TRANSFORM_TERMS)
    )


def _preferred_change_operation(words: set[str], tokens: tuple[str, ...]) -> str:
    refine = _is_refine_intent(words, tokens)
    verify = _is_verify_intent(words)
    apply = _is_apply_intent(words)
    if refine:
        return "change_refine"
    if _is_negative_execution(tokens):
        preflight = _has_phrase(tokens, "before", "apply") and _has_any(words, _VERIFY_TERMS)
        return "change_verify" if verify or preflight else "change_plan"
    if _is_rule_inspection(words):
        return "search"
    if verify:
        return "change_verify"
    if apply:
        return "change_apply"
    return "change_plan"


def _is_map_intent(words: set[str]) -> bool:
    if not _has_any(words, _MAP_TERMS):
        return False
    source_terms = frozenset(
        {"body", "bytes", "declaration", "declarations", "implementation", "location", "read", "symbol", "symbols"}
    )
    return not _has_any(words, _SEARCH_TERMS | _CHANGE_TERMS | _INTERFACE_TERMS | source_terms)


def _is_interface_intent(words: set[str]) -> bool:
    return _has_any(words, _INTERFACE_TERMS) or ("without" in words and "bodies" in words)


def _is_impact_intent(words: set[str], tokens: tuple[str, ...]) -> bool:
    if _has_any(words, _IMPACT_TERMS - {"use", "used", "uses", "calls", "occurrences"}):
        return True
    if _has_phrase(tokens, "call", "sites") or _has_phrase(tokens, "affected", "files"):
        return True
    call_subject = frozenset({"caller", "callers", "declaration", "definition", "function", "symbol"})
    search_context = _SEARCH_TERMS - {"calls"}
    has_call_subject = _has_any(words, frozenset({"call", "calls"})) and _has_any(words, call_subject)
    if has_call_subject and not _has_any(words, search_context):
        return True
    return _has_any(words, frozenset({"use", "used", "uses"})) and _has_any(
        words, frozenset({"declaration", "definition", "function", "reference", "symbol"})
    )


def _is_explicit_read_intent(words: set[str]) -> bool:
    if _has_any(words, _READ_TERMS):
        return True
    source_retrieval_terms = frozenset({"exact", "fetch", "get", "open", "read", "retrieve", "show"})
    return "source" in words and _has_any(words, source_retrieval_terms)


def _is_named_lookup_intent(words: set[str], tokens: tuple[str, ...]) -> bool:
    if _has_phrase(tokens, "find", "calls") or _has_phrase(tokens, "calls", "matching"):
        return False
    search_terms = frozenset({"matching", "pattern", "literal", "rule", "rules", "expression", "syntax"})
    if _has_any(words, search_terms) and "find" in words:
        return False
    named_values = frozenset(
        {
            "declaration",
            "declarations",
            "declared",
            "declares",
            "defined",
            "definition",
            "function",
            "qualified",
            "symbol",
            "symbols",
        }
    )
    lookup_verbs = frozenset({"called", "identify", "locate", "name", "named", "owns", "resolve", "where", "which"})
    return _has_any(words, named_values) and _has_any(words, lookup_verbs)


def _is_search_intent(words: set[str], tokens: tuple[str, ...]) -> bool:
    return (
        _has_any(words, _SEARCH_TERMS)
        or _has_phrase(tokens, "find", "calls")
        or _has_phrase(tokens, "calls", "matching")
    )


def _preferred_operation(tokens: tuple[str, ...], words: set[str]) -> str | None:
    if _is_capability_intent(words):
        return "capabilities"
    if _is_change_intent(words):
        return _preferred_change_operation(words, tokens)
    if _is_map_intent(words):
        return "map"
    if _is_interface_intent(words):
        return "interface"
    if _is_impact_intent(words, tokens):
        return "impact"
    if _is_named_lookup_intent(words, tokens):
        return "find"
    if _is_explicit_read_intent(words):
        return "read"
    if _is_search_intent(words, tokens):
        return "search"
    if "lookup" in words or "source" in words:
        return "read"
    if _has_any(words, _FIND_TERMS):
        return "find"
    return None


def _operation_score(name: str, words: set[str], tokens: tuple[str, ...], preferred: str | None) -> int:
    concepts = _RANKING_CONCEPTS.get(name)
    if concepts is None:
        return 0
    score = len(words & concepts)
    if name == "change_apply" and _is_negative_execution(tokens):
        score -= 4
    if name == preferred:
        score += 10_000
    operation_words = set(name.split("_"))
    if operation_words <= words:
        score += 100
    return score


def rank_operations(intent: str, candidates: tuple[str, ...] = OPERATIONS) -> tuple[str, ...]:
    """Return the relevant enabled catalog names in deterministic rank order."""

    normalized = normalize_intent(intent)
    tokens = _intent_tokens(normalized)
    words = set(tokens)
    if not words:
        return ()
    preferred = _preferred_operation(tokens, words)
    selected = {name for name in candidates if name in OPERATIONS}
    scored = []
    for name in selected:
        score = _operation_score(name, words, tokens, preferred)
        if score > 0:
            scored.append((name, score))
    return tuple(name for name, _ in sorted(scored, key=lambda item: (-item[1], item[0].encode("utf-8"))))


@dataclass(frozen=True, slots=True)
class PreparedRequest:
    """One strictly validated request and its canonical repository identity."""

    request: Request
    root: Root | None = None


class RequestPreparationError(ValueError):
    """A bounded, recognition-aware failure before service execution."""

    def __init__(self, code: str, message: object, *, operation: str | None = None) -> None:
        self.code = code
        self.operation = operation if operation in OPERATIONS else None
        super().__init__(str(message))


def _request_operation(value: Any) -> str | None:
    if isinstance(value, CallToolRequest):
        return value.name
    if isinstance(value, Mapping):
        raw = value.get("op")
        if raw is None and "name" in value:
            raw = value.get("name")
        return raw if isinstance(raw, str) else None
    raw = getattr(value, "op", None)
    return raw if isinstance(raw, str) else None


def normalize_request(value: Any) -> Request:
    """Validate one request and apply only typed defaults; no coercion."""
    if isinstance(value, CallToolRequest):
        return normalize_call_tool(value)
    if isinstance(value, Mapping) and value.get("name") is not None and "arguments" in value and "op" not in value:
        return normalize_call_tool(CallToolRequest.model_validate(value))
    if isinstance(value, StrictModel) and getattr(value, "op", None) in OPERATIONS:
        return cast(Request, value)
    return validate_request(value)


def normalize_call_tool(value: CallToolRequest) -> Request:
    arguments = dict(value.arguments)
    if "op" in arguments:
        raise ValueError("call_tool.arguments must not contain op")
    arguments["op"] = value.name
    return validate_request(arguments)


def prepare_request(value: Any) -> PreparedRequest:
    """Validate once, account for request bytes, and normalize its root once."""

    raw_operation = _request_operation(value)
    operation = raw_operation if raw_operation in OPERATIONS else None
    try:
        if request_json_size(value, MAX_REQUEST_JSON_BYTES) > MAX_REQUEST_JSON_BYTES:
            raise RequestPreparationError(
                "execution_limit",
                f"request exceeds the {MAX_REQUEST_JSON_BYTES}-byte canonical JSON bound",
                operation=operation,
            )
    except RequestPreparationError:
        raise
    except (TypeError, ValueError):
        # The typed boundary remains authoritative for malformed values.  Do
        # not serialize or otherwise copy an invalid caller object here.
        pass

    try:
        normalized = normalize_request(value)
    except RequestPreparationError:
        raise
    except Exception as exc:
        code = "invalid_request" if operation is not None else "unknown_operation"
        raise RequestPreparationError(code, exc, operation=operation) from exc

    root_value = getattr(normalized, "root", None)
    if root_value is None:
        return PreparedRequest(normalized)
    try:
        root = normalize_root(root_value)
    except RepositoryError as exc:
        raise RequestPreparationError(exc.code, exc, operation=operation) from exc
    normalized = cast(Request, normalized.model_copy(update={"root": root.path}))
    return PreparedRequest(normalized, root)


def _bounded_message(message: object, fallback: str = "operation failed") -> str:
    text = str(message) or fallback
    raw = text.encode("utf-8")
    if len(raw) <= _MAX_ERROR_MESSAGE_BYTES:
        return text
    return raw[:_MAX_ERROR_MESSAGE_BYTES].decode("utf-8", errors="ignore") or fallback


def _failure(
    code: str,
    message: object,
    *,
    op: str | None = None,
    apply: bool = False,
    details: ErrorDetails | None = None,
    root: Root | None = None,
    provenance: RepositoryProvenance | CatalogProvenance | None = None,
    action: str | None = None,
    mutation: Any | None = None,
) -> Error:
    error_values: dict[str, Any] = {"code": code, "message": _bounded_message(message)}
    if details is not None:
        error_values["details"] = details
    if action is not None:
        error_values["action"] = action
    values: dict[str, Any] = {
        "schema": "xray.v1",
        "ok": False,
        "error": ErrorValue.model_validate(error_values),
    }
    if op is not None:
        values["op"] = op
    if root is not None:
        values["root"] = root
    if provenance is not None:
        values["provenance"] = provenance
    if apply:
        values["mutation"] = mutation or {"state": "not_applied", "rollback_status": "not_attempted"}
    return Error.model_validate(values)


_MUTATION_ROLLBACK_STATUS = {
    "not_applied": "not_attempted",
    "rolled_back": "succeeded",
    "partially_applied": "failed",
    "indeterminate": "failed",
}


def _validated_apply_plan_digest(request: Request) -> str | None:
    """Return the reviewed digest only after validating the complete artifact."""

    if request.op != "change_apply" or not isinstance(request, ChangeApplyArguments):
        return None
    plan = request.query.plan
    expected = request.query.expected_digest
    try:
        if expected != plan.plan_digest or canonical_plan_digest(plan) != expected:
            return None
    except Exception:
        return None
    return expected


def _apply_mutation_payload(request: Request, mutation: Any | None) -> dict[str, Any]:
    """Normalize an apply failure to one authoritative top-level mutation."""

    if mutation is None:
        values: dict[str, Any] = {}
    elif isinstance(mutation, Mapping):
        values = dict(mutation)
    else:
        try:
            candidate = mutation.to_payload()
            values = dict(candidate) if isinstance(candidate, Mapping) else {}
        except Exception:
            values = {}
    state = values.get("state")
    rollback_status = values.get("rollback_status")
    if state not in _MUTATION_ROLLBACK_STATUS or rollback_status != _MUTATION_ROLLBACK_STATUS[state]:
        values = {"state": "not_applied", "rollback_status": "not_attempted"}
    validated_digest = _validated_apply_plan_digest(request)
    if validated_digest is None:
        values.pop("plan_digest", None)
    else:
        values["plan_digest"] = validated_digest
    return values


def _ensure_apply_error(request: Request, result: Success | Error) -> Success | Error:
    """Ensure every recognized apply error has the canonical mutation field."""

    if request.op != "change_apply" or not isinstance(result, Error):
        return result
    values = result.to_payload()
    values["op"] = "change_apply"
    values["mutation"] = _apply_mutation_payload(request, result.mutation)
    try:
        return Error.model_validate(values)
    except Exception:
        return _failure(
            "internal_error",
            "change_apply handler returned an invalid error",
            op="change_apply",
            apply=True,
        )


@dataclass(frozen=True, slots=True)
class Result:
    """The one immutable executor result; adapters serialize ``value`` only."""

    value: Success | Error

    @property
    def ok(self) -> bool:
        return bool(getattr(self.value, "ok", False))

    def to_payload(self) -> dict[str, Any]:
        return self.value.to_payload()


class RepositoryService(Protocol):
    def execute_repository(self, request: Request, *, budget: OperationBudget | None = None) -> Success | Error: ...


class ExecutorService(Protocol):
    def execute(
        self,
        request: Request
        | MapArguments
        | FindArguments
        | InterfaceArguments
        | ReadArguments
        | ImpactArguments
        | SearchArguments,
        *,
        budget: OperationBudget | None = None,
    ) -> Success | Error: ...


class DeclarationService(Protocol):
    def execute(self, request: Request, *, budget: OperationBudget | None = None) -> Success | Error: ...


ChangeRequest: TypeAlias = ChangePlanArguments | ChangeRefineArguments | ChangeVerifyArguments | ChangeApplyArguments


Handler: TypeAlias = Callable[[Any], Success | Error]


class ChangeService(Protocol):
    def execute(self, request: ChangeRequest, *, budget: OperationBudget | None = None) -> Success | Error: ...


def _cancel_requested(cancel: object | None) -> bool:
    if cancel is None:
        return False
    if callable(cancel):
        try:
            return bool(cancel())
        except Exception:
            return True
    checker = getattr(cancel, "is_set", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return True
    return False


class ApplicationService:
    """Dispatch normalized requests through the enabled operation services."""

    def __init__(
        self,
        *,
        handlers: Mapping[str, Handler] | None = None,
        indexer_factory: Callable[[str], ExecutorService] | None = None,
        repository_factory: Callable[[str], Any] | None = None,
        change_service: ChangeService | None = None,
    ) -> None:
        self._indexer_factory = indexer_factory or XRayIndexer
        self._repository_factory = repository_factory or RepositoryProvider
        self._change_service = change_service if change_service is not None else GuardedChangeService()
        self._default_handlers = handlers is None
        selected = (
            {
                "map": self._execute_map,
                "find": self._execute_find,
                "interface": self._execute_interface,
                "read": self._execute_read,
                "impact": self._execute_impact,
                "search": self._execute_search,
                "change_plan": self._execute_change_plan,
                "change_refine": self._execute_change_refine,
                "change_verify": self._execute_change_verify,
                "change_apply": self._execute_change_apply,
                "capabilities": self._execute_capabilities,
            }
            if handlers is None
            else dict(handlers)
        )
        self._handlers = cast(Mapping[str, Handler], MappingProxyType(selected))

    @property
    def handlers(self) -> Mapping[str, Handler]:
        """Return the immutable registry used for this service."""
        return self._handlers

    def _budget(
        self,
        request: Request,
        *,
        budget: OperationBudget | None,
        cancel: object | None,
    ) -> OperationBudget:
        """Build one operation context and combine an internal cancellation signal."""

        if budget is None:
            return OperationBudget(timeout_seconds=request.execution.timeout_seconds, cancel=cancel)
        if cancel is None or budget.cancel is cancel:
            return budget
        if budget.cancel is None:
            budget.cancel = cancel
            return budget
        current = budget.cancel
        budget.cancel = lambda: _cancel_requested(current) or _cancel_requested(cancel)
        return budget

    def dispatch(
        self,
        request: Request,
        *,
        budget: OperationBudget | None = None,
        cancel: object | None = None,
    ) -> Success | Error:
        op = cast(str, request.op)
        operation_budget = self._budget(request, budget=budget, cancel=cancel)
        handler = self._handlers.get(op)
        if not callable(handler):
            result: Success | Error = _failure(
                "unknown_operation",
                f"operation {op!r} is not implemented",
                op=op,
                apply=op == "change_apply",
            )
        else:
            try:
                operation_budget.check_deadline()
                if self._default_handlers:
                    result = cast(Any, handler)(request, budget=operation_budget)
                else:
                    result = handler(request)
            except RepositoryError as exc:
                result = _failure(exc.code, exc, op=op, apply=op == "change_apply")
            except Exception as exc:  # the application boundary never leaks service failures
                result = _failure("internal_error", exc, op=op, apply=op == "change_apply")
            if not isinstance(result, (Success, Error)):
                result = _failure(
                    "internal_error",
                    "handler returned an invalid result",
                    op=op,
                    apply=op == "change_apply",
                )
            elif isinstance(result, Success) and result.op != op:
                result = _failure(
                    "internal_error",
                    "handler returned a result for another operation",
                    op=op,
                    apply=op == "change_apply",
                )
            elif isinstance(result, Error) and result.op not in {None, op}:
                result = _failure(
                    "internal_error",
                    "handler returned an error for another operation",
                    op=op,
                    apply=op == "change_apply",
                )
            elif isinstance(result, Error) and op == "change_apply" and result.mutation is None:
                result = _failure(
                    "internal_error",
                    "change_apply handler returned an error without mutation",
                    op=op,
                    apply=True,
                )
        return _ensure_apply_error(request, result)

    def execute(
        self,
        request: Request,
        *,
        budget: OperationBudget | None = None,
        cancel: object | None = None,
    ) -> Success | Error:
        """Dispatch an already-normalized request without normalizing again."""

        return self.dispatch(request, budget=budget, cancel=cancel)

    def _execute_map(self, request: Request, *, budget: OperationBudget) -> Success | Error:
        if not isinstance(request, MapArguments):
            return _failure("invalid_request", "map service accepts only typed map arguments", op="map")
        return self._indexer_factory(request.root).execute(request, budget=budget)

    def _execute_find(self, request: Request, *, budget: OperationBudget) -> Success | Error:
        if not isinstance(request, FindArguments):
            return _failure("invalid_request", "find service accepts only typed find arguments", op="find")
        return self._indexer_factory(request.root).execute(request, budget=budget)

    def _execute_interface(self, request: Request, *, budget: OperationBudget) -> Success | Error:
        if not isinstance(request, InterfaceArguments):
            return _failure(
                "invalid_request",
                "interface service accepts only typed interface arguments",
                op="interface",
            )
        return self._indexer_factory(request.root).execute(request, budget=budget)

    def _execute_read(self, request: Request, *, budget: OperationBudget) -> Success | Error:
        if not isinstance(request, ReadArguments):
            return _failure("invalid_request", "read service accepts only typed read arguments", op="read")
        # Construct exactly one indexer for this rooted request.  The indexer
        # owns capture, reference validation, cursor checks, and exact reads.
        return self._indexer_factory(request.root).execute(request, budget=budget)

    def _execute_impact(self, request: Request, *, budget: OperationBudget) -> Success | Error:
        if not isinstance(request, ImpactArguments):
            return _failure("invalid_request", "impact service accepts only typed impact arguments", op="impact")
        return self._indexer_factory(request.root).execute(request, budget=budget)

    def _execute_search(self, request: Request, *, budget: OperationBudget) -> Success | Error:
        if not isinstance(request, SearchArguments):
            return _failure("invalid_request", "search service accepts only typed search arguments", op="search")
        return self._indexer_factory(request.root).execute(request, budget=budget)

    def _execute_change_plan(self, request: Request, *, budget: OperationBudget) -> Success | Error:
        if not isinstance(request, ChangePlanArguments):
            return _failure("invalid_request", "change_plan service accepts only typed arguments", op="change_plan")
        return self._change_service.execute(request, budget=budget)

    def _execute_change_refine(self, request: Request, *, budget: OperationBudget) -> Success | Error:
        if not isinstance(request, ChangeRefineArguments):
            return _failure(
                "invalid_request",
                "change_refine service accepts only typed arguments",
                op="change_refine",
            )
        return self._change_service.execute(request, budget=budget)

    def _execute_change_verify(self, request: Request, *, budget: OperationBudget) -> Success | Error:
        if not isinstance(request, ChangeVerifyArguments):
            return _failure(
                "invalid_request",
                "change_verify service accepts only typed arguments",
                op="change_verify",
            )
        return self._change_service.execute(request, budget=budget)

    def _execute_change_apply(self, request: Request, *, budget: OperationBudget) -> Success | Error:
        if not isinstance(request, ChangeApplyArguments):
            return _failure(
                "invalid_request",
                "change_apply service accepts only typed arguments",
                op="change_apply",
                apply=True,
            )
        return self._change_service.execute(request, budget=budget)

    def _execute_capabilities(self, request: Request, *, budget: OperationBudget) -> Success | Error:
        if not isinstance(request, CapabilitiesArguments):
            return _failure("invalid_request", "capabilities service accepts only typed arguments", op="capabilities")

        catalog = catalog_identity() if self._default_handlers else catalog_identity(handlers=self._handlers)
        detail = request.query.detail == "detail"
        operation_values: list[OperationSummary] | None = None
        if detail:
            operation_values = [
                OperationSummary.model_validate(
                    {"name": spec.name, "description": spec.description, "mutation": spec.mutation}
                )
                for spec in sorted(enabled_operation_specs(self._handlers), key=lambda item: item.name.encode("utf-8"))
            ]

        observation: ToolchainObservation | None
        observation_error: Exception | None = None
        try:
            observation = ToolchainProvider().observe(budget=budget)
        except RepositoryError:
            raise
        except Exception as exc:
            observation = None
            observation_error = exc

        if observation is None:
            dependencies = [Dependency(name="xray", state="incompatible")]
            healthy = False
            toolchain_message = f"toolchain health could not be observed: {observation_error}"
        else:
            dependencies = [Dependency.model_validate(item.payload()) for item in observation.dependencies]
            healthy = observation.healthy
            toolchain_message = "; ".join(observation.errors) or "required toolchain identity is unavailable"

        if detail and (
            observation is None or not observation.healthy or observation.manifest is None or observation.digest is None
        ):
            return _failure(
                "dependency_unavailable",
                toolchain_message,
                op="capabilities",
                action="install_dependency",
            )

        data_values: dict[str, Any] = {
            "version": XRAY_VERSION,
            "schema": "xray.v1",
            "plan_schema": "xray.change.v1",
            "healthy": healthy,
            "languages": list(LANGUAGE_ORDER),
            "dependencies": dependencies,
        }
        if operation_values is not None:
            data_values.update(
                {
                    "operations": operation_values,
                    "limits": default_limit_catalog(),
                    "resources": list(_CAPABILITY_RESOURCES),
                    "toolchain": observation.manifest if observation is not None else None,
                }
            )

        if request.root is None:
            provenance: RepositoryProvenance | CatalogProvenance = CatalogProvenance(catalog=catalog)
            return Success(
                schema="xray.v1",
                ok=True,
                op="capabilities",
                provenance=provenance,
                data=CapabilitiesData(**data_values),
                coverage=Coverage(state="complete", basis="capabilities"),
            )

        root: Root | None = None
        try:
            capture = self._repository_factory(request.root).capture(include_namespace=False, budget=budget)
            root = capture.root
            if observation is None or observation.digest is None:
                return _failure(
                    "dependency_unavailable",
                    toolchain_message,
                    op="capabilities",
                    root=root,
                    action="install_dependency",
                )
            query_identity = repository_query_digest(
                "capabilities",
                request.query.to_payload(),
                {"operation": "capabilities", "detail": request.query.detail},
                capture.manifest.selection_digest,
                capture.manifest.snapshot_digest,
                observation.digest,
            )
            provenance = RepositoryProvenance(
                kind="repository",
                consistency="captured_read_set",
                query=query_identity,
                selection=capture.manifest.selection_digest,
                snapshot=capture.manifest.snapshot_digest,
                toolchain=observation.digest,
            )
            return Success(
                schema="xray.v1",
                ok=True,
                op="capabilities",
                root=root,
                scope=capture.selection,
                provenance=provenance,
                data=CapabilitiesData(**data_values),
                coverage=Coverage(state="complete", basis="capabilities"),
            )
        except RepositoryError as exc:
            details = ErrorDetails(kind=exc.kind) if exc.kind else None
            action = "correct_input" if exc.code == "path_outside_root" else None
            return _failure(
                exc.code,
                exc,
                op="capabilities",
                root=root,
                details=details,
                action=action,
            )


def default_handlers() -> Mapping[str, Handler]:
    """Return the immutable enabled-operation handler registry."""

    return ApplicationService().handlers


def _fit_result(
    request: Request,
    result: Success | Error,
    *,
    budget: OperationBudget | None = None,
) -> Success | Error:
    authoritative_apply = request.op == "change_apply"
    if budget is not None and not authoritative_apply:
        budget.check_deadline()
    if isinstance(result, Error):
        try:
            return fit_error(result)
        except Exception:
            return _failure(
                "internal_error",
                "typed operation error exceeded the error byte bound",
                op=result.op,
                apply=result.op == "change_apply",
                mutation=result.mutation,
            )

    page = getattr(request, "page", None)
    hard_bytes = 65_536
    if result.op in {"change_plan", "change_refine"}:
        plan = getattr(getattr(result, "data", None), "plan", None)
        max_bytes = getattr(getattr(plan, "bounds", None), "max_bytes", 65_536)
        hard_bytes = 262_144
    elif page is not None:
        max_bytes = page.max_bytes
    elif result.op == "map":
        max_bytes = PageMap().max_bytes
    elif result.op == "find":
        max_bytes = PageFind().max_bytes
    elif result.op == "interface":
        max_bytes = PageInterface().max_bytes
    elif result.op == "read":
        max_bytes = PageRead().max_bytes
    elif result.op == "impact":
        max_bytes = PageImpact().max_bytes
    elif result.op == "search":
        max_bytes = PageSearch().max_bytes
    elif result.op == "capabilities":
        detail = getattr(getattr(request, "query", None), "detail", "summary") == "detail"
        max_bytes = _CAPABILITIES_DETAIL_BYTES if detail else _CAPABILITIES_DEFAULT_BYTES
        hard_bytes = _CAPABILITIES_DETAIL_BYTES
    else:
        max_bytes = hard_bytes
    try:
        fitted = fit_success(result, max_bytes, hard_bytes=hard_bytes)
    except Exception as exc:
        if authoritative_apply:
            return result
        return _failure("internal_error", exc, op=result.op)
    if isinstance(fitted, Error):
        if authoritative_apply:
            return result
        try:
            return fit_error(fitted)
        except Exception:
            return _failure(
                "internal_error",
                "budget error exceeded the error byte bound",
                op=result.op,
            )
    if budget is not None and not authoritative_apply:
        budget.check_deadline()
    return fitted


def execute(
    request: Any,
    *,
    handlers: Mapping[str, Handler] | None = None,
    budget: OperationBudget | None = None,
    cancel: object | None = None,
) -> Result:
    """Prepare once, dispatch one enabled service, fit, and return one result."""

    if isinstance(request, PreparedRequest):
        prepared = request
    else:
        try:
            prepared = prepare_request(request)
        except RequestPreparationError as exc:
            operation = exc.operation
            if operation is None and isinstance(request, Mapping) and "name" in request and "op" not in request:
                operation = "call_tool"
            return Result(_failure(exc.code, exc, op=operation, apply=operation == "change_apply"))
        except Exception as exc:
            operation = _request_operation(request)
            operation = operation if operation in OPERATIONS else None
            return Result(_failure("internal_error", exc, op=operation, apply=operation == "change_apply"))

    normalized = prepared.request
    operation_budget = budget or OperationBudget(timeout_seconds=normalized.execution.timeout_seconds, cancel=cancel)
    service = ApplicationService(handlers=handlers)
    result = service.execute(normalized, budget=operation_budget, cancel=cancel)
    try:
        fitted = _fit_result(normalized, result, budget=operation_budget)
    except RepositoryError as exc:
        fitted = _failure(exc.code, exc, op=normalized.op, apply=normalized.op == "change_apply")
    except Exception as exc:
        fitted = _failure("internal_error", exc, op=normalized.op, apply=normalized.op == "change_apply")
    return Result(_ensure_apply_error(normalized, fitted))


def fit_contract(contract: OperationContract, max_bytes: int) -> OperationContract | Error:
    fitted = fit_discovery(contract, max_bytes)
    return fitted


__all__ = [
    "FUTURE_OPERATION_BY_NAME",
    "FUTURE_OPERATION_SPECS",
    "RANKING_METADATA",
    "SCHEMA_DIALECT",
    "ApplicationService",
    "ChangeRequest",
    "ChangeService",
    "DeclarationService",
    "ExecutorService",
    "Handler",
    "OperationBudget",
    "OperationSpec",
    "PreparedRequest",
    "RepositoryService",
    "RequestPreparationError",
    "Result",
    "SchemaValidationError",
    "canonicalize_schema",
    "catalog_identity",
    "default_handlers",
    "discovery_artifact_digest",
    "enabled_operation_specs",
    "execute",
    "fit_contract",
    "future_operation_specs",
    "normalize_call_tool",
    "normalize_request",
    "operation_contracts",
    "operation_query_schema",
    "prepare_request",
    "rank_operations",
    "schema_documents",
    "schema_for_operation",
    "validate_schema_document",
]
