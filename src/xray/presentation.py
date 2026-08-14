"""Compact, stable projections for verbose ast-grep output."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

DEFAULT_RESULT_LIMIT = 50


def _relative_path(value: Any, root_path: Path) -> str:
    path = Path(str(value or ""))
    if path.is_absolute():
        try:
            return path.resolve().relative_to(root_path.resolve()).as_posix()
        except ValueError:
            return str(path)
    return path.as_posix()


def _location(item: Mapping[str, Any]) -> tuple[int | None, int | None]:
    range_data = item.get("range")
    start = range_data.get("start", {}) if isinstance(range_data, Mapping) else {}
    if not isinstance(start, Mapping):
        return None, None
    line = start.get("line")
    column = start.get("column")
    return (int(line) + 1 if line is not None else None, int(column) + 1 if column is not None else None)


def _captures(item: Mapping[str, Any]) -> dict[str, Any]:
    meta = item.get("metaVariables")
    if not isinstance(meta, Mapping):
        return {}
    captures: dict[str, Any] = {}
    for group in ("single", "transformed"):
        values = meta.get(group)
        if isinstance(values, Mapping):
            for name, value in values.items():
                if isinstance(value, Mapping) and "text" in value:
                    captures[str(name)] = value["text"]
    multi = meta.get("multi")
    if isinstance(multi, Mapping):
        for name, values in multi.items():
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                texts = [value["text"] for value in values if isinstance(value, Mapping) and "text" in value]
                if texts:
                    captures[str(name)] = texts
    return captures


def compact_structural_item(item: Mapping[str, Any], root_path: Path, *, default_path: str = "") -> dict[str, Any]:
    """Project one ast-grep match or outline item to XRAY-owned fields."""
    path = item.get("file") or item.get("path") or default_path
    line, column = _location(item)
    result: dict[str, Any] = {}
    if path:
        result["path"] = _relative_path(path, root_path)
    if line is not None:
        result["line"] = line
    if column is not None:
        result["column"] = column
    for source, target in (
        ("text", "text"),
        ("lines", "text"),
        ("name", "name"),
        ("kind", "kind"),
        ("signature", "signature"),
        ("ruleId", "rule_id"),
        ("id", "id"),
    ):
        if source in item and item[source] not in (None, "") and target not in result:
            result[target] = item[source]
    captures = _captures(item)
    if captures:
        result["captures"] = captures
    return result


def compact_structural_items(items: Sequence[Mapping[str, Any]], root_path: Path) -> list[dict[str, Any]]:
    """Flatten outline groups and compact all structural items."""
    results: list[dict[str, Any]] = []
    for item in items:
        nested = item.get("items")
        if isinstance(nested, list):
            default_path = str(item.get("path") or item.get("file") or "")
            results.extend(
                compact_structural_item(value, root_path, default_path=default_path)
                for value in nested
                if isinstance(value, Mapping)
            )
        else:
            results.append(compact_structural_item(item, root_path))
    return results


def compact_explore(data: Mapping[str, Any]) -> dict[str, Any]:
    """Remove duplicated tree and derivable absolute/name fields from explore JSON."""
    entries = []
    for entry in data.get("entries", []):
        compact = {key: entry[key] for key in ("path", "kind", "depth", "language", "symbols") if key in entry}
        entries.append(compact)
    return {
        "root_path": data["root_path"],
        "entries": entries,
        "options": data["options"],
        "truncated": data.get("truncated", False),
    }


def compact_impact_references(
    items: Sequence[Mapping[str, Any]], root_path: Path, symbol_name: str
) -> list[dict[str, Any]]:
    """Project impact references to relative paths and one matched source line."""
    word = re.compile(r"\b" + re.escape(symbol_name) + r"\b")
    compact: list[dict[str, Any]] = []
    for item in items:
        text = str(item.get("text") or "")
        matched_line = next((line.strip() for line in text.splitlines() if word.search(line)), text.strip())
        compact.append(
            {
                "path": _relative_path(item.get("file"), root_path),
                "line": int(item.get("line", 1)),
                "type": str(item.get("type") or "text"),
                "confidence": str(item.get("confidence") or "low"),
                "text": matched_line,
            }
        )
    return compact


def compact_v3_interface(data: Mapping[str, Any]) -> dict[str, Any]:
    """Project interface data to one paging vocabulary and typed completeness."""
    result = dict(data)
    result.pop("returned_symbols", None)
    result.pop("total_symbols", None)
    reasons: list[str] = []
    warnings = [str(value) for value in result.get("warnings", [])]
    if any("Members for" in warning for warning in warnings):
        reasons.append("member_truncated")
    if bool(result.get("truncated")):
        reasons.append("page_truncated")
    if not bool(result.get("complete", True)) and not reasons:
        reasons.append("source_incomplete")
    result["completeness"] = {"complete": not reasons, "reasons": reasons}
    result.pop("complete", None)
    return result


def compact_v3_impact(data: Mapping[str, Any]) -> dict[str, Any]:
    """Remove overlapping impact counters while retaining named diagnostics."""
    result = dict(data)
    diagnostics = {
        key: result.pop(key)
        for key in ("raw_count", "filtered_count", "execution_cap", "execution_limited")
        if key in result
    }
    result.pop("total_count", None)
    if diagnostics:
        result["diagnostics"] = diagnostics
    return result


def cursor_fingerprint(command: str, root_path: Path, identity: Mapping[str, Any]) -> str:
    """Return a stable query binding for an opaque result cursor."""
    value = json.dumps([command, str(root_path.resolve()), identity], separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def encode_cursor(offset: int, fingerprint: str) -> str:
    """Encode an offset and query fingerprint as an opaque cursor."""
    raw = json.dumps({"o": offset, "q": fingerprint}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None, fingerprint: str) -> int:
    """Decode and validate a query- and snapshot-bound cursor."""
    if not cursor:
        return 0
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        value = json.loads(raw)
        offset = value["o"]
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, binascii.Error) as exc:
        raise ValueError("cursor is invalid.") from exc
    if not isinstance(offset, int) or offset < 0 or value.get("q") != fingerprint:
        raise ValueError("cursor does not match this command or query.")
    return offset


def page_items(
    items: Sequence[Mapping[str, Any]],
    *,
    command: str,
    root_path: Path,
    identity: Mapping[str, Any],
    limit: int = DEFAULT_RESULT_LIMIT,
    cursor: str | None = None,
    continuable: bool = True,
    total_exact: bool = True,
) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    """Page items and return truthful compact result metadata."""
    if limit < 0:
        raise ValueError("limit must be 0 or greater.")
    fingerprint = cursor_fingerprint(command, root_path, identity)
    offset = decode_cursor(cursor, fingerprint)
    total = len(items)
    if offset > total:
        raise ValueError("cursor is past the available results.")
    end = min(offset + limit, total)
    page = list(items[offset:end])
    truncated = end < total or (not total_exact and len(page) == limit and limit > 0)
    metadata: dict[str, Any] = {
        "returned": len(page),
        "total": total,
        "total_exact": total_exact,
        "truncated": truncated,
    }
    if continuable and truncated and limit > 0:
        metadata["next_cursor"] = encode_cursor(end, fingerprint)
    return page, metadata
