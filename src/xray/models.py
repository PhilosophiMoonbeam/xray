"""Strict, closed xray.v1 and xray.change.v1 value contracts.

The models in this module are transport-neutral.  Adapters construct these
values at their boundary and never add projection-specific fields.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from typing import Annotated, Any, Literal, TypeAlias, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic.types import StringConstraints

# ---------------------------------------------------------------------------
# Shared constrained values

DIGEST_PATTERN = r"^[0-9a-f]{64}$"
_FILE_PATH_COMPONENT = r"(?:[^/.][^/]*|\.[^/.][^/]*|\.\.[^/.][^/]*|\.{3,}[^/]*)"
_FILE_PATH_BODY = rf"{_FILE_PATH_COMPONENT}(?:/+{_FILE_PATH_COMPONENT})*/*"
FILE_PATH_PATTERN = rf"^{_FILE_PATH_BODY}$"
SCOPE_PATH_PATTERN = rf"^(?:\.|{_FILE_PATH_BODY})$"
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
MAX_PATH_BYTES = 4096
MAX_REQUEST_JSON_BYTES = 1_048_576
MAX_SELECTION_PATHS = 100_000
MAX_LANGUAGES = 4
MAX_INTERFACE_SECTIONS = 3
MAX_SCHEMA_DEFINITIONS = 64
MAX_SCHEMA_NODES = 2048
MAX_SCHEMA_DEPTH = 64

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject: TypeAlias = dict[str, JSONValue]


def _validate_path(value: Any, *, allow_dot: bool) -> Any:
    if isinstance(value, str):
        if "\x00" in value or len(value.encode("utf-8")) > MAX_PATH_BYTES:
            raise ValueError("path exceeds the 4096-byte UTF-8 bound")
        if (
            value.startswith("/")
            or (not allow_dot and value == ".")
            or (value != "." and any(part in {".", ".."} for part in value.split("/")))
        ):
            raise ValueError("path must be a contained repository-relative POSIX path")
    return value


def _validate_file_path(value: Any) -> Any:
    return _validate_path(value, allow_dot=False)


def _validate_scope_path(value: Any) -> Any:
    return _validate_path(value, allow_dot=True)


LANGUAGE_ORDER: tuple[str, ...] = ("python", "javascript", "typescript", "go")
OPERATIONS: tuple[str, ...] = (
    "map",
    "find",
    "interface",
    "read",
    "impact",
    "search",
    "change_plan",
    "change_refine",
    "change_verify",
    "change_apply",
    "capabilities",
)
CATALOG_OPERATIONS: tuple[str, ...] = (
    "search_tools",
    "capabilities",
    "map",
    "find",
    "interface",
    "read",
    "impact",
    "search",
    "change_plan",
    "change_refine",
    "change_verify",
    "change_apply",
)
Digest = Annotated[StrictStr, StringConstraints(min_length=64, max_length=64, pattern=DIGEST_PATTERN)]
RelPath = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=4096, pattern=FILE_PATH_PATTERN),
    AfterValidator(_validate_file_path),
]
ScopePath = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=4096, pattern=SCOPE_PATH_PATTERN),
    AfterValidator(_validate_scope_path),
]
Language = Literal["python", "javascript", "typescript", "go"]
Visibility = Literal["public", "private", "unknown"]
Operation = Literal[
    "map",
    "find",
    "interface",
    "read",
    "impact",
    "search",
    "change_plan",
    "change_refine",
    "change_verify",
    "change_apply",
    "capabilities",
]
CatalogOperation = Literal[
    "search_tools",
    "capabilities",
    "map",
    "find",
    "interface",
    "read",
    "impact",
    "search",
    "change_plan",
    "change_refine",
    "change_verify",
    "change_apply",
]
ErrorOperation = Operation | Literal["search_tools", "call_tool", "skill_install"]


def _reject_non_list(value: Any) -> Any:
    if not isinstance(value, list):
        raise TypeError("expected a JSON array")
    return cast(list[object], value)


StrictList = Annotated[list[Any], BeforeValidator(_reject_non_list)]


class StrictModel(BaseModel):
    """Closed, immutable model base with strict JSON-like input semantics."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_assignment=True,
        populate_by_name=True,
    )

    @model_validator(mode="before")
    @classmethod
    def _reject_nulls(cls, value: Any) -> Any:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            return value
        if "schema_" in value:
            raise ValueError("schema_ is not a public field")

        def walk(item: Any) -> None:
            if item is None:
                raise ValueError("null is not an omission")
            if isinstance(item, (tuple, set, frozenset)):
                raise TypeError("tuples and sets are not JSON arrays")
            if isinstance(item, Mapping):
                mapping = cast(Mapping[object, object], item)
                for nested in mapping.values():
                    walk(nested)
            elif isinstance(item, list):
                items = cast(list[object], item)
                for nested in items:
                    walk(nested)

        walk(value)
        return dict(cast(Mapping[object, object], value))

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)

    def canonical_payload(self) -> dict[str, Any]:
        return self.to_payload()


class _PathModel(StrictModel):
    @field_validator("path", check_fields=False)
    @classmethod
    def _path_bytes(cls, value: str) -> str:
        if "\x00" in value or len(value.encode("utf-8")) > MAX_PATH_BYTES:
            raise ValueError("path exceeds the 4096-byte UTF-8 bound")
        return value


def _check_digest(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("digest must be 64 lowercase hexadecimal characters")
    return value


def _domain_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _check_range(start: int, end: int) -> None:
    if end < start:
        raise ValueError("end must be greater than or equal to start")


def _utf8_bounded(value: str, maximum: int, *, minimum: int = 0, label: str = "value") -> str:
    size = len(value.encode("utf-8"))
    if size < minimum or size > maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum} UTF-8 bytes")
    return value


def _unique(values: list[Any], label: str) -> None:
    try:
        if len(set(values)) != len(values):
            raise ValueError(f"{label} must not contain duplicates")
    except TypeError as exc:
        raise ValueError(f"{label} must contain hashable values") from exc


def _utf8_sorted(values: list[str], label: str) -> None:
    expected = sorted(values, key=lambda item: item.encode("utf-8"))
    if values != expected:
        raise ValueError(f"{label} must be sorted by UTF-8 byte order")


def _strict_string_list(value: Any) -> Any:
    if not isinstance(value, list):
        raise TypeError("expected an array of strings")
    items = cast(list[object], value)
    if any(not isinstance(item, str) for item in items):
        raise TypeError("expected an array of strings")
    return cast(list[str], items)


StringList = Annotated[list[StrictStr], BeforeValidator(_strict_string_list)]


def _resource_address(value: str) -> str:
    return _utf8_bounded(value, MAX_PATH_BYTES, minimum=1, label="resource address")


ResourceAddress = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=MAX_PATH_BYTES),
    AfterValidator(_resource_address),
]
ResourceAddressList = Annotated[list[ResourceAddress], BeforeValidator(_strict_string_list)]


def canonical_resource_addresses(values: list[str]) -> list[str]:
    """Validate and return deterministic, duplicate-free resource addresses."""

    validated = cast(list[str], TypeAdapter(ResourceAddressList).validate_python(values))
    _unique(validated, "capabilities.resources")
    return sorted(validated, key=lambda item: item.encode("utf-8"))


# ---------------------------------------------------------------------------
# Identity, source and paging values


class Root(_PathModel):
    path: StrictStr = Field(min_length=1, max_length=4096)
    id: Digest

    @field_validator("path")
    @classmethod
    def _absolute_normalized_root(cls, value: str) -> str:
        if not os.path.isabs(value):
            raise ValueError("root path must be absolute")
        if "\\" in value or "/./" in value or "/../" in value or value.endswith("/..") or value.endswith("/."):
            raise ValueError("root path must be normalized")
        return value

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        return _check_digest(value)

    @model_validator(mode="after")
    def _identity(self) -> Root:
        if self.id != _domain_digest(["xray.root.v1", self.path]):
            raise ValueError("root.id does not match the normalized root path")
        return self


class Position(StrictModel):
    byte: StrictInt = Field(ge=0)
    line: StrictInt = Field(ge=1)
    column: StrictInt = Field(ge=1)


class Range(StrictModel):
    start: Position
    end: Position

    @model_validator(mode="after")
    def _ordered(self) -> Range:
        _check_range(self.start.byte, self.end.byte)
        return self


class _SourceRefBase(_PathModel):
    root_id: Digest
    path: RelPath
    file_digest: Digest
    start: StrictInt = Field(ge=0)
    end: StrictInt = Field(ge=0)

    @field_validator("root_id", "file_digest")
    @classmethod
    def _digests(cls, value: str) -> str:
        return _check_digest(value)

    @model_validator(mode="after")
    def _ordered(self) -> _SourceRefBase:
        _check_range(self.start, self.end)
        return self


class SourceRef(_SourceRefBase):
    kind: Literal["source"]


class SymbolSourceRef(_SourceRefBase):
    kind: Literal["symbol"]
    symbol_id: Digest
    analyzer_id: Digest

    @field_validator("symbol_id", "analyzer_id")
    @classmethod
    def _ids(cls, value: str) -> str:
        return _check_digest(value)


SourceRefUnion: TypeAlias = Annotated[SourceRef | SymbolSourceRef, Field(discriminator="kind")]


class OccurrenceRef(_PathModel):
    kind: Literal["occurrence"]
    root_id: Digest
    path: RelPath
    file_digest: Digest
    start: StrictInt = Field(ge=0)
    end: StrictInt = Field(ge=0)
    occurrence_id: Digest

    @field_validator("root_id", "file_digest", "occurrence_id")
    @classmethod
    def _digests(cls, value: str) -> str:
        return _check_digest(value)

    @model_validator(mode="after")
    def _ordered(self) -> OccurrenceRef:
        _check_range(self.start, self.end)
        expected = _domain_digest(["xray.occurrence.v1", self.path, self.file_digest, self.start, self.end])
        if self.occurrence_id != expected:
            raise ValueError("occurrence_id does not match the occurrence identity")
        return self


class LocationTarget(_PathModel):
    kind: Literal["location"]
    path: RelPath
    line: StrictInt = Field(ge=1)
    end_line: StrictInt | None = Field(default=None, ge=1)
    column: StrictInt | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _ordered(self) -> LocationTarget:
        if self.end_line is not None and self.end_line < self.line:
            raise ValueError("end_line must be greater than or equal to line")
        return self


ReadTarget: TypeAlias = SourceRefUnion | OccurrenceRef | LocationTarget


class FileTarget(_PathModel):
    kind: Literal["file"]
    path: RelPath


class Selection(StrictModel):
    paths: list[ScopePath] = Field(
        default_factory=lambda: [
            ".",
        ]
    )
    globs: StringList | None = None
    languages: list[Language] | None = None
    exclusions: Literal["default", "none"] = "default"

    @field_validator("paths")
    @classmethod
    def _paths(cls, value: list[str]) -> list[str]:
        _unique(value, "selection.paths")
        _utf8_sorted(value, "selection.paths")
        if len(value) > MAX_SELECTION_PATHS:
            raise ValueError("selection.paths exceeds 100000 entries")
        return value

    @field_validator("globs")
    @classmethod
    def _globs(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if any(len(item.encode("utf-8")) > MAX_PATH_BYTES for item in value):
            raise ValueError("selection.globs contains an oversized pattern")
        _unique(value, "selection.globs")
        return value

    @field_validator("languages")
    @classmethod
    def _languages(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        _unique(value, "selection.languages")
        if len(value) > MAX_LANGUAGES or value != sorted(value, key=LANGUAGE_ORDER.index):
            raise ValueError("selection.languages must use the fixed language order")
        return value


class Disclosure(StrictModel):
    clipped: list[Literal["signature", "documentation", "text", "captures"]]

    @field_validator("clipped")
    @classmethod
    def _clipped(cls, value: list[str]) -> list[str]:
        _unique(value, "disclosure.clipped")
        order = ("signature", "documentation", "text", "captures")
        if value != sorted(value, key=order.index):
            raise ValueError("disclosure.clipped must use canonical order")
        return value


class Execution(StrictModel):
    timeout_seconds: StrictInt = Field(default=30, ge=1, le=120)
    cache: Literal["auto", "off"] = "auto"


class PageMap(StrictModel):
    max_bytes: StrictInt = Field(default=8192, ge=4096, le=65536)
    cursor: StrictStr | None = Field(default=None, max_length=4096)
    limit: StrictInt = Field(default=100, ge=1, le=1000)


class PageFind(StrictModel):
    max_bytes: StrictInt = Field(default=6144, ge=4096, le=65536)
    cursor: StrictStr | None = Field(default=None, max_length=4096)
    limit: StrictInt = Field(default=10, ge=1, le=100)


class PageInterface(StrictModel):
    max_bytes: StrictInt = Field(default=8192, ge=4096, le=65536)
    cursor: StrictStr | None = Field(default=None, max_length=4096)
    limit: StrictInt = Field(default=20, ge=1, le=200)


class PageRead(StrictModel):
    max_bytes: StrictInt = Field(default=12288, ge=4096, le=65536)
    cursor: StrictStr | None = Field(default=None, max_length=4096)
    max_lines: StrictInt = Field(default=64, ge=1, le=256)
    source_bytes: StrictInt = Field(default=8192, ge=1, le=32768)


class PageSearch(StrictModel):
    max_bytes: StrictInt = Field(default=8192, ge=4096, le=65536)
    cursor: StrictStr | None = Field(default=None, max_length=4096)
    limit: StrictInt = Field(default=20, ge=1, le=1000)


class PageImpact(PageSearch):
    pass


PageRequest: TypeAlias = PageMap | PageFind | PageInterface | PageRead | PageSearch | PageImpact


# ---------------------------------------------------------------------------
# Operation query values


class MapQuery(StrictModel):
    focus: list[ScopePath] = Field(default_factory=lambda: ["."])
    depth: StrictInt | Literal["all"] = Field(default=2)
    context: Literal["none", "ancestors"] = "none"
    exclusions: Literal["default", "none"] = "default"

    @field_validator("focus")
    @classmethod
    def _focus(cls, value: list[str]) -> list[str]:
        _unique(value, "map.focus")
        return value

    @field_validator("depth")
    @classmethod
    def _depth(cls, value: int | str) -> int | str:
        if value == "all":
            return value
        if not isinstance(value, int) or not 0 <= value <= MAX_SCHEMA_DEPTH:
            raise ValueError("map.depth must be 0..64 or 'all'")
        return value


class FindQuery(StrictModel):
    text: StrictStr = Field(min_length=1, max_length=8192)
    selection: Selection | None = None
    match: Literal["name", "exact", "fuzzy"] = "name"
    kinds: StringList | None = None
    visibility: list[Visibility] | None = None

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        return _utf8_bounded(value, 8192, minimum=1, label="find.text")

    @field_validator("kinds")
    @classmethod
    def _kinds(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        _unique(value, "find.kinds")
        return value

    @field_validator("visibility")
    @classmethod
    def _visibility(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        _unique(value, "find.visibility")
        order = ("public", "private", "unknown")
        if value != sorted(value, key=order.index):
            raise ValueError("find.visibility must use canonical order")
        return value


class InterfaceFileQuery(StrictModel):
    target: FileTarget
    sections: list[Literal["symbols", "imports", "exports"]] = Field(default_factory=lambda: ["symbols"])
    member_depth: Literal[0, 1] = 1
    documentation: StrictBool = False
    kinds: StringList | None = None
    visibility: list[Visibility] | None = None

    @field_validator("sections")
    @classmethod
    def _sections(cls, value: list[str]) -> list[str]:
        _unique(value, "interface.sections")
        order = ("symbols", "imports", "exports")
        if len(value) > MAX_INTERFACE_SECTIONS or value != sorted(value, key=order.index):
            raise ValueError("interface.sections must use canonical order")
        return value

    @field_validator("kinds")
    @classmethod
    def _kinds(cls, value: list[str] | None) -> list[str] | None:
        if value is not None:
            _unique(value, "interface.kinds")
        return value

    @field_validator("visibility")
    @classmethod
    def _visibility(cls, value: list[str] | None) -> list[str] | None:
        if value is not None:
            _unique(value, "interface.visibility")
            order = ("public", "private", "unknown")
            if value != sorted(value, key=order.index):
                raise ValueError("interface.visibility must use canonical order")
        return value


class InterfaceSymbolQuery(StrictModel):
    target: SymbolSourceRef
    sections: list[Literal["symbols"]] = Field(default_factory=lambda: ["symbols"], min_length=1, max_length=1)
    member_depth: Literal[0, 1] = 1
    documentation: StrictBool = False

    @field_validator("sections")
    @classmethod
    def _sections(cls, value: list[str]) -> list[str]:
        if value != ["symbols"]:
            raise ValueError("exact-symbol interface queries require sections=['symbols']")
        return value


InterfaceQuery: TypeAlias = InterfaceFileQuery | InterfaceSymbolQuery


class ReadQuery(StrictModel):
    targets: list[ReadTarget] = Field(min_length=1, max_length=8)
    context_lines: StrictInt = Field(default=0, ge=0, le=10)
    include_enclosing: StrictBool = True


class ImpactQuery(StrictModel):
    target: SymbolSourceRef
    selection: Selection | None = None
    mode: Literal["syntax", "lexical"] = "syntax"


class PatternSearchSource(StrictModel):
    kind: Literal["pattern"]
    pattern: StrictStr = Field(min_length=1, max_length=8192)
    language: Language

    @field_validator("pattern")
    @classmethod
    def _pattern(cls, value: str) -> str:
        return _utf8_bounded(value, 8192, minimum=1, label="search.pattern")


class LiteralSearchSource(StrictModel):
    kind: Literal["literal"]
    text: StrictStr = Field(min_length=1, max_length=8192)

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        return _utf8_bounded(value, 8192, minimum=1, label="search.literal")


class RuleInput(_PathModel):
    kind: Literal["rule", "config"]
    path: RelPath


class RuleSearchSource(StrictModel):
    kind: Literal["rule"]
    input: RuleInput


SearchSource: TypeAlias = PatternSearchSource | LiteralSearchSource | RuleSearchSource


class SearchQuery(StrictModel):
    source: SearchSource
    selection: Selection | None = None
    detail: Literal["summary", "detail"] = "summary"


class PatternChangeSource(StrictModel):
    kind: Literal["pattern"]
    pattern: StrictStr = Field(min_length=1, max_length=8192)
    replacement: StrictStr = Field(max_length=8192)
    language: Language

    @field_validator("pattern")
    @classmethod
    def _pattern(cls, value: str) -> str:
        return _utf8_bounded(value, 8192, minimum=1, label="change.pattern")

    @field_validator("replacement")
    @classmethod
    def _replacement(cls, value: str) -> str:
        return _utf8_bounded(value, 8192, label="change.replacement")


class RuleChangeSource(StrictModel):
    kind: Literal["rule"]
    input: RuleInput


ChangeSource: TypeAlias = PatternChangeSource | RuleChangeSource


class Acknowledgements(StrictModel):
    dirty_affected: StrictBool = False
    new_parse_errors: StrictBool = False


class PlanBounds(StrictModel):
    max_candidates: StrictInt = Field(default=100, ge=1, le=1000)
    max_files: StrictInt = Field(default=20, ge=1, le=100)
    max_bytes: StrictInt = Field(default=32768, ge=4096, le=262144)
    max_file_bytes: Literal[10_485_760] = 10_485_760
    max_total_preimage_bytes: Literal[52_428_800] = 52_428_800
    max_total_postimage_bytes: Literal[52_428_800] = 52_428_800


class ChangePlanQuery(StrictModel):
    source: ChangeSource
    selection: Selection | None = None
    bounds: PlanBounds | None = None
    acknowledgements: Acknowledgements | None = None


class ChangeRefineQuery(StrictModel):
    plan: ChangePlan  # type: ignore[name-defined]
    edit_ids: list[Digest] = Field(max_length=1000)

    @field_validator("edit_ids")
    @classmethod
    def _ids(cls, value: list[str]) -> list[str]:
        _unique(value, "change_refine.edit_ids")
        _utf8_sorted(value, "change_refine.edit_ids")
        return value


class ChangeVerifyQuery(StrictModel):
    plan: ChangePlan  # type: ignore[name-defined]
    expected_digest: Digest

    @field_validator("expected_digest")
    @classmethod
    def _digest(cls, value: str) -> str:
        return _check_digest(value)


class ChangeApplyQuery(ChangeVerifyQuery):
    pass


class CapabilitiesQuery(StrictModel):
    detail: Literal["summary", "detail"] = "summary"


# ---------------------------------------------------------------------------
# Provenance and operation requests


class RepositoryProvenance(StrictModel):
    kind: Literal["repository"]
    consistency: Literal["captured_read_set"]
    query: Digest
    selection: Digest
    snapshot: Digest
    toolchain: Digest

    @field_validator("query", "selection", "snapshot", "toolchain")
    @classmethod
    def _digests(cls, value: str) -> str:
        return _check_digest(value)


class CatalogProvenance(StrictModel):
    catalog: Digest
    query: Digest | None = None

    @field_validator("catalog", "query")
    @classmethod
    def _digests(cls, value: str | None) -> str | None:
        return None if value is None else _check_digest(value)


EstablishedProvenance: TypeAlias = RepositoryProvenance | CatalogProvenance
Provenance: TypeAlias = EstablishedProvenance


class _RootArguments(StrictModel):
    root: StrictStr = Field(min_length=1, max_length=4096)

    @field_validator("root")
    @classmethod
    def _root(cls, value: str) -> str:
        if not os.path.isabs(value) or "\x00" in value or len(value.encode("utf-8")) > MAX_PATH_BYTES:
            raise ValueError("root must be a normalized absolute path within 4096 UTF-8 bytes")
        return value


class MapArguments(_RootArguments):
    query: MapQuery
    page: PageMap | None = None
    execution: Execution = Field(default_factory=Execution)


class FindArguments(_RootArguments):
    query: FindQuery
    page: PageFind | None = None
    execution: Execution = Field(default_factory=Execution)


class InterfaceArguments(_RootArguments):
    query: InterfaceQuery
    page: PageInterface | None = None
    execution: Execution = Field(default_factory=Execution)


class ReadArguments(_RootArguments):
    query: ReadQuery
    page: PageRead | None = None
    execution: Execution = Field(default_factory=Execution)


class ImpactArguments(_RootArguments):
    query: ImpactQuery
    page: PageImpact | None = None
    execution: Execution = Field(default_factory=Execution)


class SearchArguments(_RootArguments):
    query: SearchQuery
    page: PageSearch | None = None
    execution: Execution = Field(default_factory=Execution)


class ChangePlanArguments(_RootArguments):
    query: ChangePlanQuery
    execution: Execution = Field(default_factory=Execution)


class ChangeRefineArguments(_RootArguments):
    query: ChangeRefineQuery
    execution: Execution = Field(default_factory=Execution)


class ChangeVerifyArguments(_RootArguments):
    query: ChangeVerifyQuery
    execution: Execution = Field(default_factory=Execution)


class ChangeApplyArguments(_RootArguments):
    query: ChangeApplyQuery
    execution: Execution = Field(default_factory=Execution)


class CapabilitiesArguments(StrictModel):
    root: StrictStr | None = Field(default=None, min_length=1, max_length=4096)
    query: CapabilitiesQuery
    execution: Execution = Field(default_factory=Execution)

    @field_validator("root")
    @classmethod
    def _root(cls, value: str | None) -> str | None:
        if value is not None and (
            not os.path.isabs(value) or "\x00" in value or len(value.encode("utf-8")) > MAX_PATH_BYTES
        ):
            raise ValueError("root must be a normalized absolute path within 4096 UTF-8 bytes")
        return value


OperationArguments: TypeAlias = (
    MapArguments
    | FindArguments
    | InterfaceArguments
    | ReadArguments
    | ImpactArguments
    | SearchArguments
    | ChangePlanArguments
    | ChangeRefineArguments
    | ChangeVerifyArguments
    | ChangeApplyArguments
    | CapabilitiesArguments
)


class MapRequest(MapArguments):
    op: Literal["map"] = "map"


class FindRequest(FindArguments):
    op: Literal["find"] = "find"


class InterfaceRequest(InterfaceArguments):
    op: Literal["interface"] = "interface"


class ReadRequest(ReadArguments):
    op: Literal["read"] = "read"


class ImpactRequest(ImpactArguments):
    op: Literal["impact"] = "impact"


class SearchRequest(SearchArguments):
    op: Literal["search"] = "search"


class ChangePlanRequest(ChangePlanArguments):
    op: Literal["change_plan"] = "change_plan"


class ChangeRefineRequest(ChangeRefineArguments):
    op: Literal["change_refine"] = "change_refine"


class ChangeVerifyRequest(ChangeVerifyArguments):
    op: Literal["change_verify"] = "change_verify"


class ChangeApplyRequest(ChangeApplyArguments):
    op: Literal["change_apply"] = "change_apply"


class CapabilitiesRequest(CapabilitiesArguments):
    op: Literal["capabilities"] = "capabilities"


Request: TypeAlias = (
    MapRequest
    | FindRequest
    | InterfaceRequest
    | ReadRequest
    | ImpactRequest
    | SearchRequest
    | ChangePlanRequest
    | ChangeRefineRequest
    | ChangeVerifyRequest
    | ChangeApplyRequest
    | CapabilitiesRequest
)


def validate_request(value: Any) -> Request:
    return REQUEST_ADAPTER.validate_python(value)


def validate_arguments(value: Any) -> OperationArguments:
    return ARGUMENT_ADAPTER.validate_python(value)


# ---------------------------------------------------------------------------
# Operation result values


class CoverageReason(StrictModel):
    code: Literal[
        "scan_pending",
        "unsupported_syntax",
        "parse_diagnostics",
        "non_text_input",
        "enclosing_unavailable",
        "capture_unverified",
    ]
    path: RelPath | None = None
    count: StrictInt | None = Field(default=None, ge=1)


class Coverage(StrictModel):
    state: Literal["complete", "partial"]
    basis: Literal[
        "namespace",
        "supported_declarations",
        "source_bytes",
        "pattern_matches",
        "rule_diagnostics",
        "literal_occurrences",
        "name_occurrences",
        "change_guards",
        "capabilities",
    ]
    reasons: list[CoverageReason] | None = None

    @model_validator(mode="after")
    def _complete_or_partial(self) -> Coverage:
        if self.state == "complete" and self.reasons is not None:
            raise ValueError("complete coverage cannot contain reasons")
        if self.state == "partial" and not self.reasons:
            raise ValueError("partial coverage requires reasons")
        if self.reasons:
            keys = [(reason.code, reason.path or "", reason.count or 0) for reason in self.reasons]
            if len(set(keys)) != len(keys) or keys != sorted(
                keys, key=lambda item: tuple(part.encode("utf-8") if isinstance(part, str) else part for part in item)
            ):
                raise ValueError("coverage reasons must be unique and canonically sorted")
        return self


class PageResult(StrictModel):
    next_cursor: StrictStr | None = Field(default=None, max_length=4096)
    total: StrictInt | None = Field(default=None, ge=0)


class MapItem(_PathModel):
    path: RelPath
    kind: Literal["file", "directory", "symlink"]
    language: Language | None = None
    frontier: Literal[True] | None = None


class MapData(StrictModel):
    items: list[MapItem]


class FindItem(_PathModel):
    ref: SymbolSourceRef
    row_id: Digest
    name: StrictStr = Field(min_length=1)
    kind: StrictStr = Field(min_length=1)
    qualified_name: StrictStr = Field(min_length=1)
    location: Range
    match_kind: Literal[
        "exact_qualified_name",
        "exact_name",
        "exact_path_context",
        "normalized_name",
        "prefix",
        "token",
        "fuzzy",
    ]

    @field_validator("row_id")
    @classmethod
    def _row_id(cls, value: str) -> str:
        return _check_digest(value)


class FindData(StrictModel):
    items: list[FindItem]


class InterfaceOwner(StrictModel):
    ref: SymbolSourceRef
    name: StrictStr = Field(min_length=1)
    kind: StrictStr = Field(min_length=1)


class Declaration(StrictModel):
    section: Literal["symbols"]
    ref: SymbolSourceRef
    name: StrictStr = Field(min_length=1)
    kind: StrictStr = Field(min_length=1)
    qualified_name: StrictStr = Field(min_length=1)
    signature: StrictStr
    visibility: Visibility
    parent_id: Digest | None = None
    expandable: Literal[True] | None = None
    documentation: StrictStr | None = None
    disclosure: Disclosure | None = None


class Import(StrictModel):
    section: Literal["imports"]
    ref: OccurrenceRef
    module_text: StrictStr
    imported_name: StrictStr | None = None
    local_name: StrictStr | None = None


class Export(StrictModel):
    section: Literal["exports"]
    ref: OccurrenceRef
    name: StrictStr | None = None
    module_text: StrictStr | None = None
    kind: Literal["named", "default", "star", "reexport", "unknown"]


InterfaceItem: TypeAlias = Declaration | Import | Export


class InterfaceData(StrictModel):
    owners: list[InterfaceOwner] | None = None
    items: list[InterfaceItem]


class EnclosingFound(StrictModel):
    state: Literal["found"]
    ref: SymbolSourceRef


class EnclosingNone(StrictModel):
    state: Literal["none"]


class EnclosingUnsupported(StrictModel):
    state: Literal["unsupported"]


class EnclosingUnavailable(StrictModel):
    state: Literal["unavailable"]
    reason: Literal["dependency_unavailable", "unsupported_syntax", "parse_diagnostics"]


Enclosing: TypeAlias = EnclosingFound | EnclosingNone | EnclosingUnsupported | EnclosingUnavailable


class EnclosingResult(StrictModel):
    target: StrictInt = Field(ge=0)
    result: Enclosing


class ReadItem(StrictModel):
    targets: list[StrictInt] = Field(min_length=1)
    ref: SourceRefUnion
    location: Range
    source: StrictStr
    enclosing: list[EnclosingResult] | None = None

    @field_validator("targets")
    @classmethod
    def _targets(cls, value: list[int]) -> list[int]:
        _unique(value, "read.targets")
        if value != sorted(value):
            raise ValueError("read.targets must be ascending")
        return value


class ReadData(StrictModel):
    items: list[ReadItem]


class Capture(StrictModel):
    name: StrictStr = Field(min_length=1)
    kind: Literal["single", "multi", "transformed"]
    refs: list[SourceRef] | None = None
    text: StrictStr | None = None


class SearchItem(StrictModel):
    ref: OccurrenceRef
    location: Range
    text: StrictStr
    rule_id: StrictStr | None = None
    captures: list[Capture] | None = None
    disclosure: Disclosure | None = None


class SearchData(StrictModel):
    items: list[SearchItem]


class ImpactImport(StrictModel):
    module_text: StrictStr
    imported_name: StrictStr | None = None
    local_name: StrictStr | None = None


class ImpactItem(StrictModel):
    ref: OccurrenceRef
    location: Range
    kind: Literal["definition", "import", "call", "read", "comment", "string", "text", "unknown"]
    evidence: Literal["ast_syntax", "lexical"]
    text: StrictStr
    enclosing: Enclosing | None = None
    import_: ImpactImport | None = Field(default=None, alias="import")
    disclosure: Disclosure | None = None


class ImpactData(StrictModel):
    target: SymbolSourceRef
    basis: Literal["name_occurrences"]
    resolution: Literal["unresolved"]
    items: list[ImpactItem]


class ChangePlanData(StrictModel):
    plan: ChangePlan  # type: ignore[name-defined]


class ChangeVerifyData(StrictModel):
    plan_digest: Digest
    ready: Literal[True]


class ChangeApplyData(StrictModel):
    plan_digest: Digest
    state: Literal["applied"]
    rollback_status: Literal["not_attempted"]


class Dependency(StrictModel):
    name: StrictStr = Field(min_length=1)
    state: Literal["available", "missing", "incompatible"]
    version: StrictStr | None = None


class CapabilitiesData(StrictModel):
    version: StrictStr = Field(min_length=1, max_length=128)
    schema_: Literal["xray.v1"] = Field(alias="schema", serialization_alias="schema")
    plan_schema: Literal["xray.change.v1"]
    healthy: StrictBool
    languages: list[Language]
    dependencies: list[Dependency]
    operations: list[OperationSummary] | None = None
    limits: LimitCatalog | None = None
    resources: ResourceAddressList | None = None
    toolchain: ToolchainManifest | None = None

    @field_validator("version")
    @classmethod
    def _version(cls, value: str) -> str:
        return _utf8_bounded(value, 128, minimum=1, label="capability version")

    @field_validator("languages")
    @classmethod
    def _languages(cls, value: list[str]) -> list[str]:
        _unique(value, "capabilities.languages")
        if value != sorted(value, key=LANGUAGE_ORDER.index):
            raise ValueError("capabilities.languages must use canonical language order")
        return value

    @field_validator("dependencies")
    @classmethod
    def _dependencies(cls, value: list[Dependency]) -> list[Dependency]:
        names = [item.name for item in value]
        if len(names) != len(set(names)) or names != sorted(names, key=lambda item: item.encode("utf-8")):
            raise ValueError("capabilities dependencies must be unique and UTF-8 sorted")
        return value

    @model_validator(mode="after")
    def _operations_order(self) -> CapabilitiesData:
        if self.operations is not None:
            names = [item.name for item in self.operations]
            if len(names) != len(set(names)) or names != sorted(names, key=lambda item: item.encode("utf-8")):
                raise ValueError("capabilities operations must be unique and UTF-8 sorted")
        if self.resources is not None:
            canonical = canonical_resource_addresses(list(self.resources))
            if list(self.resources) != canonical:
                raise ValueError("capabilities resources must be unique and UTF-8 sorted")
        return self


OperationData: TypeAlias = (
    MapData
    | FindData
    | InterfaceData
    | ReadData
    | SearchData
    | ImpactData
    | ChangePlanData
    | ChangeVerifyData
    | ChangeApplyData
    | CapabilitiesData
)

_DATA_TYPES: dict[str, type[StrictModel]] = {
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


class Success(StrictModel):
    schema_: Literal["xray.v1"] = Field(alias="schema", serialization_alias="schema")
    ok: Literal[True]
    op: Operation
    root: Root | None = None
    scope: Selection | None = None
    provenance: EstablishedProvenance | None = None
    data: Any
    page: PageResult | None = None
    coverage: Coverage

    @model_validator(mode="after")
    def _typed_result(self) -> Success:
        data_type = _DATA_TYPES[self.op]
        data = TypeAdapter(data_type).validate_python(self.data)
        object.__setattr__(self, "data", data)
        if self.op in {"change_plan", "change_refine"}:
            if self.root is not None or self.scope is not None or self.provenance is not None:
                raise ValueError("plan responses carry identity only inside the complete plan")
            if self.page is not None:
                raise ValueError("plan responses do not carry a page")
        elif self.op == "capabilities":
            if self.root is None:
                if not isinstance(self.provenance, CatalogProvenance):
                    raise ValueError("rootless capabilities requires catalog provenance")
            elif not isinstance(self.provenance, RepositoryProvenance) or self.scope is None:
                raise ValueError("rooted capabilities requires repository provenance and scope")
        elif self.root is None or self.scope is None or not isinstance(self.provenance, RepositoryProvenance):
            raise ValueError("repository success requires root, scope, and repository provenance")
        return self


ErrorCode = Literal[
    "invalid_request",
    "unknown_operation",
    "path_outside_root",
    "not_found",
    "excluded_input",
    "unsupported_file",
    "unsupported_configuration",
    "invalid_pattern",
    "invalid_rule",
    "invalid_encoding",
    "invalid_reference",
    "stale_reference",
    "invalid_cursor",
    "cursor_query_mismatch",
    "stale_cursor",
    "source_changed",
    "dependency_unavailable",
    "io_error",
    "timeout",
    "execution_limit",
    "analysis_limit",
    "budget_too_small",
    "invalid_plan",
    "plan_drift",
    "plan_inapplicable",
    "mutation_conflict",
    "apply_failed",
    "internal_error",
]
RecoveryAction = Literal[
    "correct_input",
    "refresh_reference",
    "restart_query",
    "narrow_query",
    "install_dependency",
    "inspect_worktree",
    "report_bug",
]
RollbackStatus = Literal["not_attempted", "succeeded", "failed"]
MutationFailureState = Literal["not_applied", "rolled_back", "partially_applied", "indeterminate"]


class ErrorDetails(StrictModel):
    kind: StrictStr | None = None
    minimum_bytes: StrictInt | None = Field(default=None, ge=4096)
    conflict_edit_ids: list[Digest] | None = None
    additional_conflicts: StrictInt | None = Field(default=None, ge=0)
    operation: Operation | None = None
    path: RelPath | None = None
    reason: StrictStr | None = None

    @field_validator("conflict_edit_ids")
    @classmethod
    def _conflicts(cls, value: list[str] | None) -> list[str] | None:
        if value is not None:
            _unique(value, "conflict_edit_ids")
            _utf8_sorted(value, "conflict_edit_ids")
        return value


class ErrorValue(StrictModel):
    code: ErrorCode
    message: StrictStr = Field(min_length=1, max_length=512)
    at: StrictStr | None = None
    action: RecoveryAction | None = None
    details: ErrorDetails | None = None

    @field_validator("message")
    @classmethod
    def _message_bytes(cls, value: str) -> str:
        return _utf8_bounded(value, 512, minimum=1, label="error.message")


class ChangeApplyMutation(StrictModel):
    state: MutationFailureState
    rollback_status: RollbackStatus
    plan_digest: Digest | None = None

    @model_validator(mode="after")
    def _pair(self) -> ChangeApplyMutation:
        expected = {
            "not_applied": "not_attempted",
            "rolled_back": "succeeded",
            "partially_applied": "failed",
            "indeterminate": "failed",
        }[self.state]
        if self.rollback_status != expected:
            raise ValueError("mutation state and rollback status disagree")
        return self


class Error(StrictModel):
    schema_: Literal["xray.v1"] = Field(alias="schema", serialization_alias="schema")
    ok: Literal[False]
    op: ErrorOperation | None = None
    root: Root | None = None
    error: ErrorValue
    mutation: ChangeApplyMutation | None = None
    provenance: EstablishedProvenance | None = None

    @model_validator(mode="after")
    def _mutation_contract(self) -> Error:
        if self.op == "change_apply":
            if self.mutation is None:
                raise ValueError("recognized change_apply errors require mutation")
        elif self.mutation is not None:
            raise ValueError("mutation is only valid for recognized change_apply errors")
        if self.op == "skill_install" and (self.root is not None or isinstance(self.provenance, RepositoryProvenance)):
            raise ValueError("administrative errors cannot carry repository identity")
        return self


class AdministrativeData(StrictModel):
    scope: Literal["user", "project"]
    target: StrictStr = Field(min_length=1, max_length=4096)
    changed: StrictBool
    replaced: StrictBool
    files: list[Literal["SKILL.md", "agents/openai.yaml"]]

    @field_validator("target")
    @classmethod
    def _target(cls, value: str) -> str:
        if not os.path.isabs(value) or "\x00" in value or len(value.encode("utf-8")) > MAX_PATH_BYTES:
            raise ValueError("administrative target must be an absolute path within 4096 UTF-8 bytes")
        return value

    @field_validator("files")
    @classmethod
    def _files(cls, value: list[str]) -> list[str]:
        if value != ["SKILL.md", "agents/openai.yaml"]:
            raise ValueError("administrative files must use the fixed bundle order")
        return value

    @model_validator(mode="after")
    def _replacement(self) -> AdministrativeData:
        if self.replaced and not self.changed:
            raise ValueError("replaced implies changed")
        return self


class AdministrativeSuccess(StrictModel):
    schema_: Literal["xray.v1"] = Field(alias="schema", serialization_alias="schema")
    ok: Literal[True]
    op: Literal["skill_install"]
    data: AdministrativeData


# ---------------------------------------------------------------------------
# xray.change.v1 plan artifact


class ManifestItem(_PathModel):
    path: RelPath
    bytes: StrictInt = Field(ge=0)
    sha256: Digest

    @field_validator("sha256")
    @classmethod
    def _digest(cls, value: str) -> str:
        return _check_digest(value)


class PolicyItem(StrictModel):
    name: StrictStr = Field(min_length=1, max_length=128)
    sha256: Digest

    @field_validator("sha256")
    @classmethod
    def _digest(cls, value: str) -> str:
        return _check_digest(value)


class InputManifest(StrictModel):
    sources: list[ManifestItem] = Field(max_length=20_000)
    configuration: list[ManifestItem] = Field(max_length=1024)
    policies: list[PolicyItem]
    toolchain: Digest

    @field_validator("toolchain")
    @classmethod
    def _toolchain(cls, value: str) -> str:
        return _check_digest(value)

    @model_validator(mode="after")
    def _canonical(self) -> InputManifest:
        for label, items in (("sources", self.sources), ("configuration", self.configuration)):
            paths = [item.path for item in items]
            if len(set(paths)) != len(paths) or paths != sorted(paths, key=lambda item: item.encode("utf-8")):
                raise ValueError(f"inputs.{label} must be unique and UTF-8 path sorted")
        names = [item.name for item in self.policies]
        keys = [(item.name, item.sha256) for item in self.policies]
        if len(set(names)) != len(names) or keys != sorted(
            keys, key=lambda item: (item[0].encode("utf-8"), item[1].encode("ascii"))
        ):
            raise ValueError("inputs.policies must be unique and canonically sorted")
        return self


class SyntaxDiagnostic(StrictModel):
    range: Range
    signature: Digest
    text: StrictStr = Field(max_length=200)

    @field_validator("signature")
    @classmethod
    def _signature(cls, value: str) -> str:
        return _check_digest(value)

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        return _utf8_bounded(value, 200, label="syntax diagnostic text")


class SyntaxEvidence(StrictModel):
    analyzer: Digest
    language: Language
    diagnostic_count: StrictInt = Field(ge=0)
    fingerprint: Digest
    diagnostics: list[SyntaxDiagnostic] = Field(max_length=50)

    @field_validator("analyzer", "fingerprint")
    @classmethod
    def _digests(cls, value: str) -> str:
        return _check_digest(value)

    @model_validator(mode="after")
    def _canonical(self) -> SyntaxEvidence:
        keys = [(item.range.start.byte, item.range.end.byte, item.signature, item.text) for item in self.diagnostics]
        if keys != sorted(keys, key=lambda item: (item[0], item[1], item[2].encode("ascii"), item[3].encode("utf-8"))):
            raise ValueError("syntax diagnostics must be canonically sorted")
        return self


class BaselineGit(StrictModel):
    kind: Literal["git"]
    dirty_affected: list[RelPath]

    @field_validator("dirty_affected")
    @classmethod
    def _paths(cls, value: list[str]) -> list[str]:
        _unique(value, "baseline.dirty_affected")
        _utf8_sorted(value, "baseline.dirty_affected")
        return value


class BaselineUnmanaged(StrictModel):
    kind: Literal["unmanaged"]


Baseline: TypeAlias = BaselineGit | BaselineUnmanaged


class Eligibility(StrictModel):
    applicable: StrictBool
    reasons: list[Literal["no_candidates", "no_changes", "dirty_affected", "new_parse_errors"]]

    @field_validator("reasons")
    @classmethod
    def _reasons(cls, value: list[str]) -> list[str]:
        _unique(value, "eligibility.reasons")
        order = ("no_candidates", "no_changes", "dirty_affected", "new_parse_errors")
        if value != sorted(value, key=order.index):
            raise ValueError("eligibility.reasons must use canonical order")
        return value

    @model_validator(mode="after")
    def _applicable(self) -> Eligibility:
        if self.applicable != (not self.reasons):
            raise ValueError("eligibility.applicable must agree with reasons")
        return self


class PlanEdit(StrictModel):
    edit_id: Digest
    path: RelPath
    start: StrictInt = Field(ge=0)
    end: StrictInt = Field(ge=0)
    before_sha256: Digest
    after_sha256: Digest
    changed: StrictBool

    @field_validator("edit_id", "before_sha256", "after_sha256")
    @classmethod
    def _digests(cls, value: str) -> str:
        return _check_digest(value)

    @model_validator(mode="after")
    def _valid(self) -> PlanEdit:
        _check_range(self.start, self.end)
        if self.changed != (self.before_sha256 != self.after_sha256):
            raise ValueError("edit.changed must agree with before and after digests")
        return self


class PlanFile(_PathModel):
    path: RelPath
    preimage_sha256: Digest
    postimage_sha256: Digest
    preimage_bytes: StrictInt = Field(ge=0)
    postimage_bytes: StrictInt = Field(ge=0)
    mode: StrictInt = Field(ge=0)
    syntax_before: SyntaxEvidence
    syntax_after: SyntaxEvidence
    new_diagnostic_count: StrictInt = Field(ge=0)
    diff: StrictStr

    @field_validator("preimage_sha256", "postimage_sha256")
    @classmethod
    def _digests(cls, value: str) -> str:
        return _check_digest(value)


class ChosenAll(StrictModel):
    kind: Literal["all"]


class ChosenEdits(StrictModel):
    kind: Literal["edits"]
    ids: list[Digest] = Field(max_length=1000)

    @field_validator("ids")
    @classmethod
    def _ids(cls, value: list[str]) -> list[str]:
        _unique(value, "chosen.ids")
        _utf8_sorted(value, "chosen.ids")
        return value


Chosen: TypeAlias = ChosenAll | ChosenEdits


class ChangePlan(StrictModel):
    plan_schema: Literal["xray.change.v1"]
    root: Root
    selection: Selection
    source: ChangeSource
    provenance: RepositoryProvenance
    inputs: InputManifest
    bounds: PlanBounds
    chosen: Chosen
    files: list[PlanFile] = Field(max_length=100)
    edits: list[PlanEdit] = Field(max_length=1000)
    baseline: Baseline
    acknowledgements: Acknowledgements
    eligibility: Eligibility
    plan_digest: Digest

    @field_validator("plan_digest")
    @classmethod
    def _digest(cls, value: str) -> str:
        return _check_digest(value)

    @model_validator(mode="after")
    def _canonical(self) -> ChangePlan:
        file_paths = [item.path for item in self.files]
        if len(set(file_paths)) != len(file_paths) or file_paths != sorted(
            file_paths, key=lambda item: item.encode("utf-8")
        ):
            raise ValueError("plan.files must be unique and path sorted")
        edit_keys = [(item.path, item.start, item.end, item.edit_id) for item in self.edits]
        if len(set(edit_keys)) != len(edit_keys) or edit_keys != sorted(
            edit_keys, key=lambda item: (item[0].encode("utf-8"), item[1], item[2], item[3].encode("ascii"))
        ):
            raise ValueError("plan.edits must use canonical order and no duplicates")
        for index, left in enumerate(self.edits):
            for right in self.edits[index + 1 :]:
                if left.path != right.path:
                    continue
                if left.start < right.end and right.start < left.end:
                    raise ValueError("overlapping plan edits are forbidden")
        if len(self.files) > self.bounds.max_files or len(self.edits) > self.bounds.max_candidates:
            raise ValueError("plan exceeds selected bounds")
        preimage = sum(item.preimage_bytes for item in self.files)
        postimage = sum(item.postimage_bytes for item in self.files)
        if preimage > self.bounds.max_total_preimage_bytes or postimage > self.bounds.max_total_postimage_bytes:
            raise ValueError("plan exceeds total image bounds")
        payload = self.to_payload()
        payload.pop("plan_digest", None)
        if self.plan_digest != _domain_digest(payload):
            raise ValueError("plan_digest does not match the complete canonical plan")
        return self


# Resolve forward references in query, argument, request, and result models now that ChangePlan exists.
ChangeRefineQuery.model_rebuild()
ChangeVerifyQuery.model_rebuild()
ChangeApplyQuery.model_rebuild()
ChangePlanData.model_rebuild()
ChangeRefineArguments.model_rebuild()
ChangeVerifyArguments.model_rebuild()
ChangeApplyArguments.model_rebuild()
ChangeRefineRequest.model_rebuild()
ChangeVerifyRequest.model_rebuild()
ChangeApplyRequest.model_rebuild()
REQUEST_ADAPTER: TypeAdapter[Request] = TypeAdapter[Request](Request)
ARGUMENT_ADAPTER: TypeAdapter[OperationArguments] = TypeAdapter[OperationArguments](OperationArguments)


# ---------------------------------------------------------------------------
# Limits and toolchain identity


class ResponseLimit(StrictModel):
    operation: CatalogOperation
    default_bytes: StrictInt = Field(ge=4096)
    hard_bytes: StrictInt = Field(ge=4096)
    default_items: StrictInt | None = Field(default=None, ge=1)
    hard_items: StrictInt | None = Field(default=None, ge=1)
    item_mode: Literal["count", "targets", "none"]

    @model_validator(mode="after")
    def _bounds(self) -> ResponseLimit:
        if self.hard_bytes < self.default_bytes:
            raise ValueError("hard_bytes must be >= default_bytes")
        if (self.default_items is None) != (self.hard_items is None):
            raise ValueError("item bounds must be supplied together")
        if self.default_items is not None and self.hard_items is not None and self.hard_items < self.default_items:
            raise ValueError("hard_items must be >= default_items")
        if self.item_mode == "count" and self.default_items is None:
            raise ValueError("count requires item bounds")
        if self.item_mode in {"targets", "none"} and self.default_items is not None:
            raise ValueError("target or no-item modes cannot carry item bounds")
        return self


class CaptureLimits(StrictModel):
    source_files: Literal[20_000] = 20_000
    source_bytes: Literal[268_435_456] = 268_435_456
    file_bytes: Literal[10_485_760] = 10_485_760


class NamespaceLimits(StrictModel):
    entries: Literal[100_000] = 100_000
    path_bytes: Literal[16_777_216] = 16_777_216


class AnalysisLimits(StrictModel):
    find_declarations: Literal[100_000] = 100_000
    find_candidates_per_file: Literal[10_000] = 10_000
    window_files: Literal[1000] = 1000
    window_source_bytes: Literal[52_428_800] = 52_428_800
    window_raw_candidates: Literal[10_000] = 10_000
    overflow_sentinel: Literal[1] = 1


class ConfigurationLimits(StrictModel):
    files: Literal[1024] = 1024
    file_bytes: Literal[1_048_576] = 1_048_576
    total_bytes: Literal[8_388_608] = 8_388_608
    yaml_depth: Literal[64] = 64
    nodes: Literal[100_000] = 100_000


class ExecutorLimits(StrictModel):
    stdout_bytes: Literal[16_777_216] = 16_777_216
    stderr_bytes: Literal[65_536] = 65_536
    queued_bytes: Literal[262_144] = 262_144
    default_timeout_seconds: Literal[30] = 30
    hard_timeout_seconds: Literal[120] = 120
    git_timeout_seconds: Literal[5] = 5
    children_per_operation: Literal[1] = 1


class ConcurrencyLimits(StrictModel):
    mcp_operations: Literal[4] = 4
    mcp_per_root: Literal[1] = 1


class StorageLimits(StrictModel):
    temporary_bytes: Literal[335_544_320] = 335_544_320
    mutation_bytes: Literal[209_715_200] = 209_715_200
    cache_disk_bytes: Literal[536_870_912] = 536_870_912
    cache_artifact_bytes: Literal[16_777_216] = 16_777_216
    cache_payload_bytes: Literal[67_108_864] = 67_108_864
    root_handles: Literal[32] = 32


class MutationLimits(StrictModel):
    affected_file_bytes: Literal[10_485_760] = 10_485_760
    total_preimage_bytes: Literal[52_428_800] = 52_428_800
    total_postimage_bytes: Literal[52_428_800] = 52_428_800


class RequestLimits(StrictModel):
    json_bytes: Literal[1_048_576] = MAX_REQUEST_JSON_BYTES
    cursor_bytes: Literal[4096] = 4096
    discovery_intent_bytes: Literal[1024] = 1024


class DisplayLimits(StrictModel):
    read_lines_default: Literal[64] = 64
    read_lines_hard: Literal[256] = 256
    read_source_bytes_default: Literal[8192] = 8192
    read_source_bytes_hard: Literal[32768] = 32768
    context_lines: Literal[10] = 10
    signature_bytes: Literal[2048] = 2048
    documentation_bytes: Literal[512] = 512
    occurrence_text_bytes: Literal[512] = 512
    capture_records: Literal[16] = 16
    transformed_text_bytes: Literal[512] = 512


class LimitCatalog(StrictModel):
    schema_: Literal["xray.limits.v1"] = Field(alias="schema", serialization_alias="schema")
    responses: list[ResponseLimit] = Field(min_length=12, max_length=12)
    capture: CaptureLimits
    namespace: NamespaceLimits
    analysis: AnalysisLimits
    configuration: ConfigurationLimits
    executor: ExecutorLimits
    concurrency: ConcurrencyLimits
    storage: StorageLimits
    mutation: MutationLimits
    request: RequestLimits
    display: DisplayLimits

    @model_validator(mode="after")
    def _responses(self) -> LimitCatalog:
        names = [item.operation for item in self.responses]
        if names != list(CATALOG_OPERATIONS):
            raise ValueError("limit responses must use canonical catalog order")
        return self


def default_limit_catalog() -> LimitCatalog:
    """Build the canonical frozen-threshold catalog for capability detail."""

    response_values = (
        ("search_tools", 4096, 16384, 3, 10, "count"),
        ("capabilities", 4096, 65536, None, None, "none"),
        ("map", 8192, 65536, 100, 1000, "count"),
        ("find", 6144, 65536, 10, 100, "count"),
        ("interface", 8192, 65536, 20, 200, "count"),
        ("read", 12288, 65536, None, None, "targets"),
        ("impact", 8192, 65536, 20, 1000, "count"),
        ("search", 8192, 65536, 20, 1000, "count"),
        ("change_plan", 32768, 262144, 100, 1000, "count"),
        ("change_refine", 32768, 262144, 100, 1000, "count"),
        ("change_verify", 8192, 65536, None, None, "none"),
        ("change_apply", 8192, 65536, None, None, "none"),
    )
    responses: list[ResponseLimit] = []
    for operation, default_bytes, hard_bytes, default_items, hard_items, item_mode in response_values:
        response: dict[str, Any] = {
            "operation": operation,
            "default_bytes": default_bytes,
            "hard_bytes": hard_bytes,
            "item_mode": item_mode,
        }
        if default_items is not None and hard_items is not None:
            response["default_items"] = default_items
            response["hard_items"] = hard_items
        responses.append(ResponseLimit.model_validate(response))
    return LimitCatalog(
        schema="xray.limits.v1",
        responses=responses,
        capture=CaptureLimits(),
        namespace=NamespaceLimits(),
        analysis=AnalysisLimits(),
        configuration=ConfigurationLimits(),
        executor=ExecutorLimits(),
        concurrency=ConcurrencyLimits(),
        storage=StorageLimits(),
        mutation=MutationLimits(),
        request=RequestLimits(),
        display=DisplayLimits(),
    )


class GrammarManifest(StrictModel):
    language: Language
    version: StrictStr = Field(min_length=1, max_length=128)
    artifact: Digest

    @field_validator("version")
    @classmethod
    def _version(cls, value: str) -> str:
        return _utf8_bounded(value, 128, minimum=1, label="grammar version")

    @field_validator("artifact")
    @classmethod
    def _artifact(cls, value: str) -> str:
        return _check_digest(value)


class ToolchainComponent(StrictModel):
    version: StrictStr = Field(min_length=1, max_length=128)
    artifact: Digest

    @field_validator("version")
    @classmethod
    def _version(cls, value: str) -> str:
        return _utf8_bounded(value, 128, minimum=1, label="toolchain version")

    @field_validator("artifact")
    @classmethod
    def _artifact(cls, value: str) -> str:
        return _check_digest(value)


class ToolchainManifest(StrictModel):
    schema_: Literal["xray.toolchain.v1"] = Field(alias="schema", serialization_alias="schema")
    xray_revision: StrictStr = Field(min_length=1, max_length=128)
    xray_artifact: Digest
    ast_grep: ToolchainComponent
    ast_grep_py: ToolchainComponent
    python_ast: ToolchainComponent
    grammars: list[GrammarManifest] = Field(max_length=4)
    ranking: Digest
    selection: Digest
    parser: Digest

    @field_validator("xray_revision")
    @classmethod
    def _revision(cls, value: str) -> str:
        return _utf8_bounded(value, 128, minimum=1, label="xray revision")

    @field_validator("xray_artifact", "ranking", "selection", "parser")
    @classmethod
    def _digests(cls, value: str) -> str:
        return _check_digest(value)

    @model_validator(mode="after")
    def _grammar_order(self) -> ToolchainManifest:
        names = [item.language for item in self.grammars]
        if len(set(names)) != len(names) or names != sorted(names, key=LANGUAGE_ORDER.index):
            raise ValueError("toolchain grammars must be unique and language sorted")
        return self


# ---------------------------------------------------------------------------
# Catalog and discovery values


class SchemaNode(StrictModel):
    ref: StrictStr | None = Field(default=None, alias="$ref")
    type: Literal["object", "array", "string", "integer", "boolean"] | None = None
    properties: dict[str, Any] | None = None
    required: list[StrictStr] | None = None
    additional_properties: StrictBool | dict[str, Any] | None = Field(default=None, alias="additionalProperties")
    const: Any | None = None
    enum: list[Any] | None = None
    any_of: list[dict[str, Any]] | None = Field(default=None, alias="anyOf")
    one_of: list[dict[str, Any]] | None = Field(default=None, alias="oneOf")
    items: dict[str, Any] | None = None
    prefix_items: list[dict[str, Any]] | None = Field(default=None, alias="prefixItems")
    min_items: StrictInt | None = Field(default=None, alias="minItems", ge=0)
    max_items: StrictInt | None = Field(default=None, alias="maxItems", ge=0)
    unique_items: StrictBool | None = Field(default=None, alias="uniqueItems")
    min_length: StrictInt | None = Field(default=None, alias="minLength", ge=0)
    max_length: StrictInt | None = Field(default=None, alias="maxLength", ge=0)
    pattern: StrictStr | None = None
    minimum: StrictInt | None = None
    maximum: StrictInt | None = None
    description: StrictStr | None = None
    default: Any | None = None


def _validate_schema_document_payload(value: Mapping[str, JSONValue]) -> None:
    allowed = {
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
    definitions_value = value.get("$defs", {})
    if not isinstance(definitions_value, dict):
        raise ValueError("schema definitions must be a closed object with at most 64 entries")
    raw_definitions = cast(dict[object, JSONValue], definitions_value)
    if len(raw_definitions) > MAX_SCHEMA_DEFINITIONS:
        raise ValueError("schema definitions must be a closed object with at most 64 entries")
    definitions: dict[str, JSONValue] = {}
    for name, definition in raw_definitions.items():
        if not isinstance(name, str) or not name or "/" in name or name in {".", ".."}:
            raise ValueError("definition names must be simple nonempty names")
        definitions[name] = definition
    if value.get("$schema") != SCHEMA_DIALECT or value.get("type") != "object":
        raise ValueError("schema document must use Draft 2020-12 and have an object root")
    references: dict[str | None, list[str]] = {None: []}
    references.update({name: [] for name in definitions})
    active: set[int] = set()
    nodes = 0

    def visit(node: JSONValue, owner: str | None, depth: int) -> None:
        nonlocal nodes
        if not isinstance(node, dict):
            raise ValueError("schema nodes must be objects")
        marker = id(node)
        if marker in active:
            raise ValueError("schema contains a cyclic JSON container")
        active.add(marker)
        try:
            nodes += 1
            if nodes > MAX_SCHEMA_NODES or depth > MAX_SCHEMA_DEPTH:
                raise ValueError("schema exceeds node or depth bound")
            unknown = set(node) - allowed - ({"$schema", "$defs"} if owner is None else set())
            if unknown:
                raise ValueError(f"schema contains unknown keywords: {sorted(unknown)}")
            node_type = node.get("type")
            if node_type is not None and (
                not isinstance(node_type, str) or node_type not in {"object", "array", "string", "integer", "boolean"}
            ):
                raise ValueError("schema contains an unsupported instance type")
            if node_type == "object" and node.get("additionalProperties") is not False:
                raise ValueError("modeled object schemas must be closed")
            ref = node.get("$ref")
            if ref is not None:
                if not isinstance(ref, str) or not ref.startswith("#/$defs/") or "/" in ref[len("#/$defs/") :]:
                    raise ValueError("schema references must be local definition references")
                references[owner].append(ref[len("#/$defs/") :])
            properties_value = node.get("properties")
            if properties_value is not None:
                if not isinstance(properties_value, dict):
                    raise ValueError("schema properties must be an object")
                properties = cast(JSONObject, properties_value)
                for child in properties.values():
                    visit(child, owner, depth + 1)
            for key in ("anyOf", "oneOf", "prefixItems"):
                branches_value = node.get(key)
                if branches_value is not None:
                    if not isinstance(branches_value, list):
                        raise ValueError(f"schema {key} must be an array")
                    branches = cast(list[JSONValue], branches_value)
                    for child in branches:
                        visit(child, owner, depth + 1)
            if "items" in node:
                visit(node["items"], owner, depth + 1)
            additional = node.get("additionalProperties")
            if isinstance(additional, dict):
                visit(cast(JSONObject, additional), owner, depth + 1)
            nested_defs = node.get("$defs")
            if nested_defs is not None:
                if owner is not None or not isinstance(nested_defs, dict):
                    raise ValueError("$defs is only permitted at the document root")
        finally:
            active.remove(marker)

    visit(cast(JSONObject, value), None, 1)
    for name, definition in definitions.items():
        visit(definition, name, 1)
    for refs in references.values():
        for target in refs:
            if target not in definitions:
                raise ValueError(f"unresolved local schema reference: {target}")
    visiting: set[str] = set()
    complete: set[str] = set()

    def walk(name: str) -> None:
        if name in visiting:
            raise ValueError("schema definitions must be acyclic")
        if name in complete:
            return
        visiting.add(name)
        for target in references[name]:
            walk(target)
        visiting.remove(name)
        complete.add(name)

    for name in definitions:
        walk(name)


class SchemaDocument(SchemaNode):
    schema_uri: Literal["https://json-schema.org/draft/2020-12/schema"] = Field(alias="$schema")
    defs: dict[str, dict[str, Any]] = Field(default_factory=dict, alias="$defs")

    @model_validator(mode="after")
    def _schema_constraints(self) -> SchemaDocument:
        _validate_schema_document_payload(cast(Mapping[str, JSONValue], self.to_payload()))
        return self


class OperationSummary(StrictModel):
    name: Operation
    description: StrictStr = Field(min_length=1, max_length=256)
    mutation: Literal["read_only", "guarded_mutation"]

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        if "\n" in value or "\r" in value or not value.rstrip().endswith("."):
            raise ValueError("description must be one nonempty sentence without newlines")
        return _utf8_bounded(value, 256, minimum=1, label="description")

    @model_validator(mode="after")
    def _mutation_class(self) -> OperationSummary:
        expected = "guarded_mutation" if self.name == "change_apply" else "read_only"
        if self.mutation != expected:
            raise ValueError("only change_apply is guarded_mutation")
        return self


class OperationContract(OperationSummary):
    input_schema: SchemaDocument

    @model_validator(mode="after")
    def _mutation(self) -> OperationContract:
        expected = "guarded_mutation" if self.name == "change_apply" else "read_only"
        if self.mutation != expected:
            raise ValueError("only change_apply is guarded_mutation")
        return self


# CapabilitiesData is declared before the catalog models so operation result
# unions can refer to it without introducing a second capability shape.
CapabilitiesData.model_rebuild()


class CatalogProvenanceQuery(StrictModel):
    catalog: Digest
    query: Digest


class SearchToolsIntentRequest(StrictModel):
    mode: Literal["intent"] = "intent"
    query: StrictStr = Field(min_length=1, max_length=1024)
    limit: StrictInt = Field(default=3, ge=1, le=10)
    max_bytes: StrictInt = Field(default=4096, ge=4096, le=16384)
    cursor: StrictStr | None = Field(default=None, max_length=4096)

    @field_validator("query")
    @classmethod
    def _query(cls, value: str) -> str:
        return _utf8_bounded(value, 1024, minimum=1, label="discovery intent")


class SearchToolsExactRequest(StrictModel):
    mode: Literal["exact"]
    query: Operation
    max_bytes: StrictInt = Field(default=4096, ge=4096, le=16384)


class SearchToolsCatalogRequest(StrictModel):
    mode: Literal["catalog"]
    limit: StrictInt = Field(default=3, ge=1, le=10)
    max_bytes: StrictInt = Field(default=4096, ge=4096, le=16384)
    cursor: StrictStr | None = Field(default=None, max_length=4096)


SearchToolsRequest: TypeAlias = SearchToolsIntentRequest | SearchToolsExactRequest | SearchToolsCatalogRequest


class SearchToolsData(StrictModel):
    best: OperationContract | None = None
    alternatives: list[OperationSummary]


class SearchToolsSuccess(StrictModel):
    schema_: Literal["xray.v1"] = Field(alias="schema", serialization_alias="schema")
    ok: Literal[True]
    op: Literal["search_tools"]
    provenance: CatalogProvenanceQuery
    data: SearchToolsData
    page: PageResult
    coverage: Coverage

    @model_validator(mode="after")
    def _coverage(self) -> SearchToolsSuccess:
        if self.coverage != Coverage(state="complete", basis="capabilities"):
            raise ValueError("discovery success requires complete capabilities coverage")
        if self.data.best is None and self.data.alternatives:
            raise ValueError("alternatives require a best contract")
        return self


class CallToolRequest(StrictModel):
    name: Operation
    arguments: dict[str, Any]

    @field_validator("arguments")
    @classmethod
    def _arguments(cls, value: dict[str, Any]) -> dict[str, Any]:
        if "op" in value:
            raise ValueError("call_tool.arguments must not contain op")
        if any(item is None for item in value.values()):
            raise ValueError("null is not an omission")
        return value


class CatalogCursor(StrictModel):
    version: Literal[1]
    op: Literal["search_tools"]
    catalog: Digest
    query: Digest
    after: Operation

    @field_validator("catalog", "query")
    @classmethod
    def _digests(cls, value: str) -> str:
        return _check_digest(value)


class FileCheckpoint(StrictModel):
    kind: Literal["file"]
    index: StrictInt = Field(ge=0)
    after: Digest | None = None


class RankCheckpoint(StrictModel):
    kind: Literal["rank"]
    after: Digest


class NamespaceCheckpoint(StrictModel):
    kind: Literal["namespace"]
    after: Digest | None = None


class ReadCheckpoint(StrictModel):
    kind: Literal["read"]
    segment: StrictInt = Field(ge=0)
    byte: StrictInt = Field(ge=0)


class InterfaceCheckpoint(StrictModel):
    kind: Literal["interface"]
    after: Digest | None = None


Checkpoint: TypeAlias = FileCheckpoint | RankCheckpoint | NamespaceCheckpoint | ReadCheckpoint | InterfaceCheckpoint


class RepositoryCursor(StrictModel):
    version: Literal[1]
    op: Operation
    root: Digest
    query: Digest
    selection: Digest
    snapshot: Digest
    toolchain: Digest
    checkpoint: Checkpoint

    @field_validator("root", "query", "selection", "snapshot", "toolchain")
    @classmethod
    def _digests(cls, value: str) -> str:
        return _check_digest(value)


__all__ = [
    "MAX_REQUEST_JSON_BYTES",
    "Acknowledgements",
    "AdministrativeData",
    "AdministrativeSuccess",
    "Baseline",
    "BaselineGit",
    "BaselineUnmanaged",
    "CallToolRequest",
    "CapabilitiesArguments",
    "CapabilitiesData",
    "CapabilitiesQuery",
    "Capture",
    "CatalogCursor",
    "CatalogOperation",
    "CatalogProvenance",
    "CatalogProvenanceQuery",
    "ChangeApplyArguments",
    "ChangeApplyData",
    "ChangeApplyMutation",
    "ChangeApplyQuery",
    "ChangeApplyRequest",
    "ChangePlan",
    "ChangePlanArguments",
    "ChangePlanData",
    "ChangePlanQuery",
    "ChangeRefineArguments",
    "ChangeRefineQuery",
    "ChangeRefineRequest",
    "ChangeSource",
    "ChangeVerifyArguments",
    "ChangeVerifyData",
    "ChangeVerifyQuery",
    "ChangeVerifyRequest",
    "Checkpoint",
    "Chosen",
    "Coverage",
    "CoverageReason",
    "Declaration",
    "Dependency",
    "Digest",
    "Disclosure",
    "Enclosing",
    "EnclosingFound",
    "EnclosingNone",
    "EnclosingUnsupported",
    "Error",
    "ErrorCode",
    "ErrorDetails",
    "ErrorOperation",
    "ErrorValue",
    "Execution",
    "Export",
    "FileCheckpoint",
    "FileTarget",
    "FindArguments",
    "FindData",
    "FindItem",
    "FindQuery",
    "FindRequest",
    "GrammarManifest",
    "ImpactArguments",
    "ImpactData",
    "ImpactImport",
    "ImpactItem",
    "ImpactQuery",
    "ImpactRequest",
    "Import",
    "InputManifest",
    "InterfaceArguments",
    "InterfaceCheckpoint",
    "InterfaceData",
    "InterfaceFileQuery",
    "InterfaceItem",
    "InterfaceOwner",
    "InterfaceQuery",
    "InterfaceRequest",
    "InterfaceSymbolQuery",
    "Language",
    "LimitCatalog",
    "LiteralSearchSource",
    "LocationTarget",
    "ManifestItem",
    "MapArguments",
    "MapData",
    "MapItem",
    "MapQuery",
    "MapRequest",
    "MutationFailureState",
    "NamespaceCheckpoint",
    "OccurrenceRef",
    "Operation",
    "OperationArguments",
    "OperationContract",
    "OperationData",
    "OperationSummary",
    "PageFind",
    "PageImpact",
    "PageInterface",
    "PageMap",
    "PageRead",
    "PageRequest",
    "PageResult",
    "PageSearch",
    "PatternChangeSource",
    "PatternSearchSource",
    "PlanBounds",
    "PlanEdit",
    "PlanFile",
    "PolicyItem",
    "Provenance",
    "Range",
    "RankCheckpoint",
    "ReadArguments",
    "ReadCheckpoint",
    "ReadData",
    "ReadItem",
    "ReadQuery",
    "ReadRequest",
    "ReadTarget",
    "RecoveryAction",
    "RelPath",
    "RepositoryCursor",
    "RepositoryProvenance",
    "Request",
    "ResourceAddress",
    "ResourceAddressList",
    "ResponseLimit",
    "RollbackStatus",
    "RuleChangeSource",
    "RuleInput",
    "RuleSearchSource",
    "SchemaDocument",
    "SchemaNode",
    "SearchArguments",
    "SearchData",
    "SearchItem",
    "SearchQuery",
    "SearchRequest",
    "SearchSource",
    "SearchToolsCatalogRequest",
    "SearchToolsExactRequest",
    "SearchToolsIntentRequest",
    "SearchToolsRequest",
    "SearchToolsSuccess",
    "Selection",
    "SourceRef",
    "SourceRefUnion",
    "StrictModel",
    "Success",
    "SymbolSourceRef",
    "SyntaxDiagnostic",
    "SyntaxEvidence",
    "ToolchainComponent",
    "ToolchainManifest",
    "TypeAdapter",
    "ValidationError",
    "Visibility",
    "canonical_resource_addresses",
    "default_limit_catalog",
    "validate_arguments",
    "validate_request",
]
