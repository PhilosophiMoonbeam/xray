"""Captured-byte declaration analysis and exact read service for XRAY I1.

The indexer deliberately owns only the analysis work that cannot live in the
repository capture layer: one canonical declaration artifact per captured
file, strict reference resolution against that artifact, and exact bounded
reads.  It never discovers files or rereads source after capture.
"""

from __future__ import annotations

import ast
import bisect
import json
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast, overload

from ast_grep_py import SgRoot

from xray.core.ast_grep import (
    AstGrepError,
    AstGrepResult,
    BoundedAstGrepExecutor,
    BoundedAstGrepResult,
    captured_ast_grep_session,
    collect_complete_file_candidates,
    parse_json_array,
)
from xray.core.cache import DerivedCache
from xray.core.repository import (
    REGULAR_TEXT_DOMAIN,
    SUPPORTED_SOURCE_DOMAIN,
    CapturedFile,
    CapturedNamespaceEntry,
    CaptureDomain,
    CapturedRuleSet,
    NamespaceHorizon,
    OperationBudget,
    RepositoryCapture,
    RepositoryError,
    RepositoryProvider,
    normalize_root,
)
from xray.core.toolchain import (
    ToolchainObservation,
    ToolchainProvider,
    ToolchainUnavailableError,
)
from xray.core.toolchain import (
    analyzer_id as toolchain_analyzer_id,
)
from xray.models import (
    Capture,
    Coverage,
    CoverageReason,
    Declaration,
    Disclosure,
    Enclosing,
    EnclosingFound,
    EnclosingNone,
    EnclosingResult,
    EnclosingUnavailable,
    EnclosingUnsupported,
    Error,
    ErrorDetails,
    ErrorValue,
    Export,
    FileCheckpoint,
    FindArguments,
    FindData,
    FindItem,
    FindRequest,
    ImpactArguments,
    ImpactData,
    ImpactImport,
    ImpactItem,
    ImpactRequest,
    Import,
    InterfaceArguments,
    InterfaceData,
    InterfaceFileQuery,
    InterfaceOwner,
    InterfaceRequest,
    InterfaceSymbolQuery,
    LiteralSearchSource,
    LocationTarget,
    MapArguments,
    MapData,
    MapItem,
    MapRequest,
    OccurrenceRef,
    PageFind,
    PageImpact,
    PageInterface,
    PageMap,
    PageRead,
    PageResult,
    PageSearch,
    PatternSearchSource,
    Position,
    Range,
    ReadArguments,
    ReadCheckpoint,
    ReadData,
    ReadItem,
    ReadRequest,
    ReadTarget,
    RepositoryCursor,
    RepositoryProvenance,
    Request,
    Root,
    RuleSearchSource,
    SearchArguments,
    SearchData,
    SearchItem,
    SearchRequest,
    Selection,
    SourceRef,
    Success,
    SymbolSourceRef,
)
from xray.presentation import (
    canonical_bytes,
    decode_cursor,
    digest,
    encode_cursor,
    find_row_digest,
    occurrence_digest,
    repository_query_digest,
    symbol_digest,
)

# The repository layer owns admission language values.  Keeping the extension
# table here is useful for parser dispatch, but this module never traverses a
# directory to discover one of them.
LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
}

# This is an output-affecting identity, not a process-generation or source
# cache key.  It remains stable for the supported I1 parser profile.
TOOLCHAIN_ID = digest(["xray.toolchain.v1", "declarations", "ast-grep-py", "python-ast"])
_LINE_FEED = 0x0A
_CARRIAGE_RETURN = 0x0D
_UTF8_CONTINUATION_MASK = 0xC0
_UTF8_CONTINUATION_PREFIX = 0x80
_MAX_CONTEXT_LINES = 10
_MIN_ERROR_DETAIL_BYTES = 4096
_MAX_READ_TARGETS = 8
_MAX_ERROR_MESSAGE_BYTES = 512
_CACHE_ARTIFACT_SCHEMA = "xray.declarations.v1"
_MAP_ROW_SCHEMA = "xray.map.row.v1"
_MAX_FIND_DECLARATIONS = 100_000
_MAX_FIND_CANDIDATES_PER_FILE = 10_000
_MAX_SEARCH_FILES = 1_000
_MAX_SEARCH_SOURCE_BYTES = 50 * 1024 * 1024
_MAX_SEARCH_RAW_CANDIDATES = 10_000
_MAX_CAPTURE_RECORDS = 16
_MAX_OCCURRENCE_TEXT_BYTES = 512
_MIN_QUOTED_STRING_LENGTH = 2
_MAX_TRANSFORMED_TEXT_BYTES = 512
_IMPACT_KIND_ORDER = {
    "definition": 0,
    "import": 1,
    "call": 2,
    "read": 3,
    "comment": 4,
    "string": 5,
    "text": 6,
    "unknown": 7,
}
_SECTION_ORDER = {"symbols": 0, "imports": 1, "exports": 2}
_KIND_ORDER = {"file": 0, "directory": 1, "symlink": 2}


class _IndexerFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: str | None = None,
        action: str | None = None,
        kind: str | None = None,
        minimum_bytes: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.action = action
        self.kind = kind
        self.minimum_bytes = minimum_bytes


@dataclass(frozen=True, slots=True)
class _SourceGeometry:
    """Byte and line geometry for one immutable decoded source value."""

    text: str
    data: bytes
    line_starts: tuple[int, ...]
    line_ends: tuple[int, ...]
    char_to_byte: tuple[int, ...] | None = None
    byte_to_char: tuple[int, ...] | None = None

    @classmethod
    def from_text(cls, text: str, *, data: bytes | None = None) -> _SourceGeometry:
        encoded = text.encode("utf-8") if data is None else data
        line_starts = [0]
        for index, value in enumerate(encoded):
            if value == _LINE_FEED:
                line_starts.append(index + 1)
        line_ends = [*line_starts[1:], len(encoded)]
        return cls(
            text=text,
            data=encoded,
            line_starts=tuple(line_starts),
            line_ends=tuple(line_ends),
        )

    def _character_maps(self) -> tuple[tuple[int, ...], tuple[int, ...]]:
        char_to_byte = self.char_to_byte
        byte_to_char = self.byte_to_char
        if char_to_byte is None or byte_to_char is None:
            char_values = [0]
            byte_values: list[int] = [0]
            byte_offset = 0
            for char_index, character in enumerate(self.text):
                width = len(character.encode("utf-8"))
                byte_offset += width
                char_values.append(byte_offset)
                byte_values.extend([char_index] * (width - 1))
                byte_values.append(char_index + 1)
            char_to_byte = tuple(char_values)
            byte_to_char = tuple(byte_values)
            object.__setattr__(self, "char_to_byte", char_to_byte)
            object.__setattr__(self, "byte_to_char", byte_to_char)
        return char_to_byte, byte_to_char

    @property
    def line_count(self) -> int:
        return len(self.line_starts)

    def char_index_to_byte(self, index: int) -> int:
        if index < 0 or index > len(self.text):
            raise _IndexerFailure("invalid_reference", "source character offset is outside the captured file")
        char_to_byte, _byte_to_char = self._character_maps()
        return char_to_byte[index]

    def byte_index_to_char(self, offset: int) -> int:
        if offset < 0 or offset > len(self.data):
            raise _IndexerFailure("invalid_reference", "source byte offset is outside the captured file")
        _char_to_byte, byte_to_char = self._character_maps()
        return byte_to_char[offset]

    def is_boundary(self, offset: int) -> bool:
        if offset < 0 or offset > len(self.data):
            return False
        return (
            offset == 0
            or offset == len(self.data)
            or (self.data[offset] & _UTF8_CONTINUATION_MASK) != _UTF8_CONTINUATION_PREFIX
        )

    def line_index(self, offset: int, *, end: bool = False) -> int:
        if offset < 0 or offset > len(self.data):
            raise _IndexerFailure("invalid_reference", "source byte offset is outside the captured file")
        if end and offset > 0:
            offset -= 1
        return max(0, bisect.bisect_right(self.line_starts, offset) - 1)

    def line_start(self, line: int) -> int:
        if line < 1 or line > self.line_count:
            raise _IndexerFailure("invalid_reference", f"line {line} is outside the captured file")
        return self.line_starts[line - 1]

    def line_end(self, line: int) -> int:
        if line < 1 or line > self.line_count:
            raise _IndexerFailure("invalid_reference", f"line {line} is outside the captured file")
        return self.line_ends[line - 1]

    def line_content_end(self, line: int) -> int:
        """Return the byte end of line content, excluding its terminator."""
        end = self.line_end(line)
        if end > self.line_start(line) and self.data[end - 1] == _LINE_FEED:
            end -= 1
            if end > self.line_start(line) and self.data[end - 1] == _CARRIAGE_RETURN:
                end -= 1
        return end

    def position(self, offset: int) -> Position:
        if not self.is_boundary(offset):
            raise _IndexerFailure("invalid_reference", "source range is not aligned to a UTF-8 boundary")
        line = self.line_index(offset)
        return Position(byte=offset, line=line + 1, column=offset - self.line_starts[line] + 1)

    def decode(self, start: int, end: int) -> str:
        if not (0 <= start <= end <= len(self.data)) or not self.is_boundary(start) or not self.is_boundary(end):
            raise _IndexerFailure("invalid_reference", "source range is outside the captured UTF-8 boundaries")
        try:
            return self.data[start:end].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _IndexerFailure("invalid_encoding", "captured source range is not valid UTF-8") from exc


@dataclass(frozen=True, slots=True)
class DeclarationRecord:
    """One canonical declaration owned by a captured file artifact."""

    root_id: str
    path: str
    file_digest: str
    language: str
    analyzer_id: str
    kind: str
    name: str
    owner_chain: tuple[str, ...]
    qualified_name: str
    start: int
    end: int
    defining_start: int
    defining_end: int
    signature: str
    visibility: Literal["public", "private", "unknown"]
    documentation: str | None
    parent_id: str | None
    expandable: bool
    symbol_id: str

    @property
    def full_owner_chain(self) -> tuple[str, ...]:
        return self.owner_chain

    @property
    def name_start(self) -> int:
        return self.defining_start

    @property
    def name_end(self) -> int:
        return self.defining_end

    @property
    def ref(self) -> SymbolSourceRef:
        return SymbolSourceRef(
            kind="symbol",
            root_id=self.root_id,
            path=self.path,
            file_digest=self.file_digest,
            start=self.start,
            end=self.end,
            symbol_id=self.symbol_id,
            analyzer_id=self.analyzer_id,
        )


@dataclass(frozen=True, slots=True)
class DeclarationArtifact:
    """Complete, deterministic declaration population for one captured file."""

    root_id: str
    path: str
    file_digest: str
    language: str
    analyzer_id: str
    declarations: tuple[DeclarationRecord, ...]
    coverage: Coverage
    source_size: int

    def by_symbol_id(self, symbol_id: str) -> tuple[DeclarationRecord, ...]:
        return tuple(item for item in self.declarations if item.symbol_id == symbol_id)

    def resolve(self, ref: SymbolSourceRef) -> DeclarationRecord:
        if ref.root_id != self.root_id or ref.path != self.path or ref.file_digest != self.file_digest:
            raise _IndexerFailure("stale_reference", "symbol reference is not bound to this declaration artifact")
        matches = tuple(
            item
            for item in self.declarations
            if item.symbol_id == ref.symbol_id
            and item.start == ref.start
            and item.end == ref.end
            and item.analyzer_id == ref.analyzer_id
        )
        if len(matches) != 1:
            raise _IndexerFailure("stale_reference", "symbol reference does not match the current declaration artifact")
        return matches[0]

    def enclosing(self, start: int, end: int) -> DeclarationRecord | None:
        matches = [item for item in self.declarations if item.start <= start and end <= item.end]
        if not matches:
            return None
        return min(
            matches,
            key=lambda item: (
                item.end - item.start,
                -item.start,
                item.defining_start,
                item.symbol_id,
            ),
        )


@dataclass(frozen=True, slots=True)
class _RawDeclaration:
    language: str
    kind: str
    name: str
    owner_chain: tuple[str, ...]
    start: int
    end: int
    defining_start: int
    defining_end: int
    signature: str
    visibility: Literal["public", "private", "unknown"]
    documentation: str | None
    expandable: bool


@dataclass(frozen=True, slots=True)
class _SyntaxObservation:
    section: Literal["imports", "exports"]
    start: int
    end: int
    module_text: str | None = None
    imported_name: str | None = None
    local_name: str | None = None
    name: str | None = None
    kind: Literal["named", "default", "star", "reexport", "unknown"] = "unknown"


@dataclass(frozen=True, slots=True)
class _FindCandidate:
    declaration: DeclarationRecord
    match_kind: Literal[
        "exact_qualified_name",
        "exact_name",
        "exact_path_context",
        "normalized_name",
        "prefix",
        "token",
        "fuzzy",
    ]
    rank: int
    row_id: str


@dataclass(slots=True)
class _TargetState:
    index: int
    target: ReadTarget
    captured: CapturedFile
    geometry: _SourceGeometry
    start: int
    end: int
    artifact: DeclarationArtifact | None = None
    declaration: DeclarationRecord | None = None
    enclosing: Enclosing | None = None


@dataclass(slots=True)
class _Segment:
    path: str
    captured: CapturedFile
    geometry: _SourceGeometry
    start: int
    end: int
    targets: list[int]


@dataclass(frozen=True, slots=True)
class _MapRow:
    entry: CapturedNamespaceEntry
    frontier: bool
    row_id: str


class _MapProjection(Sequence[MapItem]):
    """Sorted namespace rows with public models materialized on demand."""

    __slots__ = ("_rows",)

    def __init__(self, rows: Sequence[_MapRow]) -> None:
        self._rows = tuple(rows)

    @property
    def row_ids(self) -> tuple[str, ...]:
        return tuple(item.row_id for item in self._rows)

    def __len__(self) -> int:
        return len(self._rows)

    @overload
    def __getitem__(self, index: int) -> MapItem: ...

    @overload
    def __getitem__(self, index: slice) -> list[MapItem]: ...

    def __getitem__(self, index: int | slice) -> MapItem | list[MapItem]:
        if isinstance(index, slice):
            return [self._item(value) for value in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)
        return self._item(index)

    def _item(self, index: int) -> MapItem:
        row = self._rows[index]
        values: dict[str, Any] = {"path": row.entry.path, "kind": row.entry.kind}
        if row.entry.language is not None:
            values["language"] = row.entry.language
        if row.frontier:
            values["frontier"] = True
        return MapItem(**values)


class _FindProjection(Sequence[FindItem]):
    """Ranked find rows with public models materialized on demand."""

    __slots__ = ("_candidates", "_geometries")

    def __init__(
        self,
        candidates: Sequence[_FindCandidate],
        geometries: Mapping[str, _SourceGeometry],
    ) -> None:
        self._candidates = tuple(candidates)
        self._geometries = geometries

    @property
    def row_ids(self) -> tuple[str, ...]:
        return tuple(candidate.row_id for candidate in self._candidates)

    def __len__(self) -> int:
        return len(self._candidates)

    @overload
    def __getitem__(self, index: int) -> FindItem: ...

    @overload
    def __getitem__(self, index: slice) -> list[FindItem]: ...

    def __getitem__(self, index: int | slice) -> FindItem | list[FindItem]:
        if isinstance(index, slice):
            return [self._item(value) for value in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)
        return self._item(index)

    def _item(self, index: int) -> FindItem:
        candidate = self._candidates[index]
        declaration = candidate.declaration
        geometry = self._geometries[declaration.path]
        return FindItem(
            ref=declaration.ref,
            row_id=candidate.row_id,
            name=declaration.name,
            kind=declaration.kind,
            qualified_name=declaration.qualified_name,
            location=Range(
                start=geometry.position(declaration.defining_start),
                end=geometry.position(declaration.defining_end),
            ),
            match_kind=candidate.match_kind,
        )


@dataclass(frozen=True, slots=True)
class _SearchRecord:
    captured: CapturedFile
    geometry: _SourceGeometry
    start: int
    end: int
    text: str
    rule_id: str | None
    captures: tuple[Capture, ...]
    row_id: str


@dataclass(frozen=True, slots=True)
class _ImpactOccurrence:
    captured: CapturedFile
    geometry: _SourceGeometry
    start: int
    end: int
    kind: Literal["definition", "import", "call", "read", "comment", "string", "text", "unknown"]
    evidence: Literal["ast_syntax", "lexical"]
    text: str
    enclosing: Enclosing | None = None
    import_value: ImpactImport | None = None


class XRayIndexer:
    """One captured-byte declaration/read service for a normalized root."""

    def __init__(
        self,
        root_path: str | Path | Root,
        *,
        cache: DerivedCache | None = None,
        toolchain_provider: ToolchainProvider | Callable[[], ToolchainObservation] | None = None,
    ) -> None:
        self.root = normalize_root(root_path)
        self.root_path = Path(self.root.path)
        self._cache = cache
        self._toolchain_provider = toolchain_provider or ToolchainProvider()
        self._active_toolchain: ToolchainObservation | None = None

    @staticmethod
    def _path_sort_key(path: str) -> tuple[bytes, ...]:
        return tuple(part.encode("utf-8") for part in PurePosixPath(path).parts)

    def _observe_toolchain(self, *, budget: OperationBudget | None = None) -> ToolchainObservation:
        try:
            provider = self._toolchain_provider
            observe = getattr(provider, "observe", None)
            if callable(observe):
                if budget is not None and isinstance(provider, ToolchainProvider):
                    observation = observe(budget=budget)
                else:
                    observation = observe()
            else:
                observation = cast(Callable[[], ToolchainObservation], provider)()
        except RepositoryError:
            raise
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise _IndexerFailure(
                "dependency_unavailable",
                f"analysis toolchain could not be observed: {exc}",
                action="install_dependency",
            ) from exc
        if not isinstance(observation, ToolchainObservation) or not observation.healthy or observation.digest is None:
            detail = "; ".join(observation.errors) if isinstance(observation, ToolchainObservation) else ""
            if not detail:
                detail = "analysis toolchain is unavailable"
            raise _IndexerFailure("dependency_unavailable", detail, action="install_dependency")
        return observation

    def _toolchain_observation(self, *, budget: OperationBudget | None = None) -> ToolchainObservation:
        return self._active_toolchain or self._observe_toolchain(budget=budget)

    def _toolchain_id(self) -> str:
        observation = self._toolchain_observation()
        if observation.digest is None:
            raise _IndexerFailure("dependency_unavailable", "analysis toolchain has no complete identity")
        return observation.digest

    def _analyzer_id(self, language: str) -> str:
        observation = self._toolchain_observation()
        try:
            return toolchain_analyzer_id(language, observation=observation)
        except ToolchainUnavailableError as exc:
            raise _IndexerFailure(
                "dependency_unavailable",
                f"analyzer identity is unavailable for {language}",
                action="install_dependency",
            ) from exc

    @staticmethod
    def _record_payload(record: DeclarationRecord) -> dict[str, Any]:
        return {
            "root_id": record.root_id,
            "path": record.path,
            "file_digest": record.file_digest,
            "language": record.language,
            "analyzer_id": record.analyzer_id,
            "kind": record.kind,
            "name": record.name,
            "owner_chain": list(record.owner_chain),
            "qualified_name": record.qualified_name,
            "start": record.start,
            "end": record.end,
            "defining_start": record.defining_start,
            "defining_end": record.defining_end,
            "signature": record.signature,
            "visibility": record.visibility,
            "documentation": record.documentation,
            "parent_id": record.parent_id,
            "expandable": record.expandable,
            "symbol_id": record.symbol_id,
        }

    @classmethod
    def _artifact_payload(
        cls,
        artifact: DeclarationArtifact,
        *,
        toolchain_id: str | None = None,
    ) -> dict[str, Any]:
        values: dict[str, Any] = {
            "schema": _CACHE_ARTIFACT_SCHEMA,
            "root_id": artifact.root_id,
            "path": artifact.path,
            "file_digest": artifact.file_digest,
            "language": artifact.language,
            "analyzer_id": artifact.analyzer_id,
            "source_size": artifact.source_size,
            "declarations": [cls._record_payload(item) for item in artifact.declarations],
            "coverage": artifact.coverage.to_payload(),
        }
        if toolchain_id is not None:
            values["toolchain"] = toolchain_id
        return values

    def _rebind_artifact(self, artifact: DeclarationArtifact, path: str) -> DeclarationArtifact:
        if artifact.path == path:
            return artifact
        declarations = tuple(
            DeclarationRecord(
                root_id=self.root.id,
                path=path,
                file_digest=item.file_digest,
                language=item.language,
                analyzer_id=item.analyzer_id,
                kind=item.kind,
                name=item.name,
                owner_chain=item.owner_chain,
                qualified_name=item.qualified_name,
                start=item.start,
                end=item.end,
                defining_start=item.defining_start,
                defining_end=item.defining_end,
                signature=item.signature,
                visibility=item.visibility,
                documentation=item.documentation,
                parent_id=item.parent_id,
                expandable=item.expandable,
                symbol_id=item.symbol_id,
            )
            for item in artifact.declarations
        )
        coverage = artifact.coverage
        if coverage.reasons:
            coverage = coverage.model_copy(
                update={
                    "reasons": [
                        reason.model_copy(update={"path": path}) if reason.path == artifact.path else reason
                        for reason in coverage.reasons
                    ]
                }
            )
        return DeclarationArtifact(
            root_id=self.root.id,
            path=path,
            file_digest=artifact.file_digest,
            language=artifact.language,
            analyzer_id=artifact.analyzer_id,
            declarations=declarations,
            coverage=coverage,
            source_size=artifact.source_size,
        )

    def _decode_cached_artifact(
        self,
        payload: bytes,
        captured_file: CapturedFile,
        *,
        analyzer_id: str,
        toolchain_id: str,
    ) -> DeclarationArtifact | None:
        language = captured_file.language
        if language not in {"python", "javascript", "typescript", "go"}:
            return None
        try:
            value = json.loads(payload.decode("utf-8"))
            if not isinstance(value, dict):
                return None
            required = {
                "schema",
                "root_id",
                "path",
                "file_digest",
                "language",
                "analyzer_id",
                "toolchain",
                "source_size",
                "declarations",
                "coverage",
            }
            if set(value) != required or value["schema"] != _CACHE_ARTIFACT_SCHEMA:
                return None
            if (
                value["root_id"] != self.root.id
                or value["file_digest"] != captured_file.digest
                or value["language"] != captured_file.language
                or value["analyzer_id"] != analyzer_id
                or value["toolchain"] != toolchain_id
                or value["source_size"] != captured_file.size
                or not isinstance(value["path"], str)
                or not isinstance(value["declarations"], list)
            ):
                return None
            raw_declarations = value["declarations"]
            declarations: list[DeclarationRecord] = []
            fields = set(DeclarationRecord.__dataclass_fields__)
            for raw in raw_declarations:
                if not isinstance(raw, dict) or set(raw) != fields:
                    return None
                owner_chain = raw["owner_chain"]
                if not isinstance(owner_chain, list) or any(not isinstance(item, str) for item in owner_chain):
                    return None
                if raw["root_id"] != self.root.id or raw["file_digest"] != captured_file.digest:
                    return None
                if raw["path"] != value["path"] or raw["language"] != captured_file.language:
                    return None
                if raw["analyzer_id"] != analyzer_id:
                    return None
                if not all(
                    isinstance(raw[field], int) and not isinstance(raw[field], bool)
                    for field in ("start", "end", "defining_start", "defining_end")
                ):
                    return None
                if any(raw[field] < 0 for field in ("start", "end", "defining_start", "defining_end")):
                    return None
                declarations.append(
                    DeclarationRecord(
                        root_id=raw["root_id"],
                        path=raw["path"],
                        file_digest=raw["file_digest"],
                        language=raw["language"],
                        analyzer_id=raw["analyzer_id"],
                        kind=raw["kind"],
                        name=raw["name"],
                        owner_chain=tuple(owner_chain),
                        qualified_name=raw["qualified_name"],
                        start=raw["start"],
                        end=raw["end"],
                        defining_start=raw["defining_start"],
                        defining_end=raw["defining_end"],
                        signature=raw["signature"],
                        visibility=raw["visibility"],
                        documentation=raw["documentation"],
                        parent_id=raw["parent_id"],
                        expandable=raw["expandable"],
                        symbol_id=raw["symbol_id"],
                    )
                )
            coverage = Coverage.model_validate(value["coverage"])
            artifact = DeclarationArtifact(
                root_id=self.root.id,
                path=value["path"],
                file_digest=captured_file.digest,
                language=language,
                analyzer_id=analyzer_id,
                declarations=tuple(declarations),
                coverage=coverage,
                source_size=captured_file.size,
            )
            expected_order = sorted(
                artifact.declarations,
                key=lambda item: (
                    item.start,
                    item.end,
                    item.defining_start,
                    item.owner_chain,
                    item.name,
                    item.kind,
                ),
            )
            if tuple(expected_order) != artifact.declarations:
                return None
            symbols = {item.symbol_id for item in declarations}
            for item in declarations:
                if item.end < item.start or item.defining_end < item.defining_start:
                    return None
                if item.parent_id is not None and item.parent_id not in symbols:
                    return None
                expected_id = symbol_digest(
                    captured_file.digest,
                    analyzer_id,
                    item.language,
                    item.kind,
                    list(item.owner_chain),
                    item.name,
                    item.start,
                    item.end,
                )
                if item.symbol_id != expected_id:
                    return None
            return self._rebind_artifact(artifact, captured_file.path)
        except Exception:
            return None

    def _cache_for(self, enabled: bool) -> DerivedCache | None:
        if not enabled:
            return None
        return self._cache if self._cache is not None else DerivedCache(self.root.id, enabled=True)

    def _declarations_for(
        self,
        captured_file: CapturedFile,
        *,
        cache: DerivedCache | None = None,
        geometry: _SourceGeometry | None = None,
        budget: OperationBudget | None = None,
    ) -> DeclarationArtifact:
        if budget is not None:
            budget.check_deadline()
        owned_toolchain = self._active_toolchain is None
        if owned_toolchain:
            self._active_toolchain = self._observe_toolchain(budget=budget)
        try:
            if cache is None or captured_file.language not in {"python", "javascript", "typescript", "go"}:
                return self.declarations_for(captured_file, geometry=geometry, budget=budget)
            analyzer = self._analyzer_id(captured_file.language)
            toolchain = self._toolchain_id()
            key = cache.key(
                _CACHE_ARTIFACT_SCHEMA,
                "declarations",
                captured_file.digest,
                captured_file.language,
                analyzer,
                toolchain,
            )
            try:
                encoded = cache.get(key, budget=budget)
            except RepositoryError:
                raise
            except Exception:
                encoded = None
            if encoded is not None:
                artifact = self._decode_cached_artifact(
                    encoded,
                    captured_file,
                    analyzer_id=analyzer,
                    toolchain_id=toolchain,
                )
                if artifact is not None:
                    if budget is not None:
                        budget.check_deadline()
                    return artifact
            artifact = self.declarations_for(captured_file, geometry=geometry, budget=budget)
            try:
                cache.put(
                    key,
                    canonical_bytes(self._artifact_payload(artifact, toolchain_id=toolchain)),
                    budget=budget,
                )
            except RepositoryError:
                raise
            except Exception:
                pass
            return artifact
        finally:
            if owned_toolchain:
                self._active_toolchain = None

    # ------------------------------------------------------------------
    # Capture and declaration artifacts

    def _provider_for(self, paths: Iterable[str]) -> RepositoryProvider:
        normalized = sorted(set(paths), key=lambda value: value.encode("utf-8"))
        if not normalized:
            raise _IndexerFailure("invalid_request", "read requires at least one target")
        return RepositoryProvider(self.root, Selection(paths=normalized, exclusions="default"))

    @staticmethod
    def _target_path(target: ReadTarget) -> str:
        return target.path

    def _validate_target_roots(self, targets: Sequence[ReadTarget]) -> None:
        for target in targets:
            root_id = getattr(target, "root_id", None)
            if root_id is not None and root_id != self.root.id:
                raise _IndexerFailure(
                    "invalid_reference",
                    "reference root does not match the requested root",
                    path=target.path,
                    action="refresh_reference",
                )

    def _capture_targets(
        self,
        targets: Sequence[ReadTarget],
        *,
        budget: OperationBudget | None = None,
    ) -> RepositoryCapture:
        self._validate_target_roots(targets)
        provider = self._provider_for(self._target_path(target) for target in targets)
        local_budget = budget or OperationBudget()
        local_budget.check_deadline()
        try:
            capture = provider.capture(
                include_namespace=False,
                budget=local_budget,
                capture_domain=REGULAR_TEXT_DOMAIN,
            )
        except RepositoryError:
            raise
        if len(capture.files) != len({self._target_path(target) for target in targets}):
            raise _IndexerFailure("source_changed", "captured target set does not contain every requested file")
        return capture

    @staticmethod
    def _captured_text(captured: CapturedFile) -> str:
        if not captured.is_text:
            raise _IndexerFailure(
                "invalid_encoding",
                "exact reads require valid UTF-8 text without NUL bytes",
                path=captured.path,
                action="correct_input",
            )
        try:
            return captured.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _IndexerFailure("invalid_encoding", "captured source is not valid UTF-8", path=captured.path) from exc

    def declarations_for(
        self,
        captured_file: CapturedFile,
        *,
        geometry: _SourceGeometry | None = None,
        budget: OperationBudget | None = None,
    ) -> DeclarationArtifact:
        """Extract declarations from exactly ``captured_file.content``.

        This method intentionally accepts a captured value rather than a path;
        parsing it cannot observe or capture another source file.
        """

        if budget is not None:
            budget.check_deadline()
        relative = Path(captured_file.path).as_posix()
        parts = Path(relative).parts
        if (
            not relative
            or relative == "."
            or Path(relative).is_absolute()
            or "\\" in relative
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise _IndexerFailure(
                "path_outside_root",
                "captured declaration path is not a contained relative file",
                path=captured_file.path,
            )
        if captured_file.language not in {"python", "javascript", "typescript", "go"}:
            raise _IndexerFailure(
                "unsupported_file", "captured file has no supported declaration language", path=captured_file.path
            )
        text = self._captured_text(captured_file)
        geometry = geometry or _SourceGeometry.from_text(text, data=captured_file.content)
        language = cast(str, captured_file.language)
        analyzer_id = self._analyzer_id(language)
        if language == "python":
            raw, parse_diagnostic = self._python_declarations(text, geometry, budget=budget)
        else:
            raw, parse_diagnostic = self._tree_declarations(text, geometry, language, budget=budget)
        declarations = self._materialize_declarations(captured_file, analyzer_id, raw, budget=budget)
        if parse_diagnostic:
            reason = CoverageReason(code="parse_diagnostics", path=captured_file.path)
            coverage = Coverage(state="partial", basis="supported_declarations", reasons=[reason])
        else:
            coverage = Coverage(state="complete", basis="supported_declarations")
        if budget is not None:
            budget.check_deadline()
        return DeclarationArtifact(
            root_id=self.root.id,
            path=captured_file.path,
            file_digest=captured_file.digest,
            language=language,
            analyzer_id=analyzer_id,
            declarations=declarations,
            coverage=coverage,
            source_size=captured_file.size,
        )

    def _materialize_declarations(
        self,
        captured_file: CapturedFile,
        analyzer_id: str,
        raw: Sequence[_RawDeclaration],
        *,
        budget: OperationBudget | None = None,
    ) -> tuple[DeclarationRecord, ...]:
        ordered = sorted(
            raw,
            key=lambda item: (
                item.start,
                item.end,
                item.defining_start,
                item.owner_chain,
                item.name,
                item.kind,
            ),
        )
        records: list[DeclarationRecord] = []
        by_qualified: dict[str, list[DeclarationRecord]] = {}
        for item in ordered:
            if budget is not None:
                budget.check_deadline()
            symbol_id = symbol_digest(
                captured_file.digest,
                analyzer_id,
                item.language,
                item.kind,
                list(item.owner_chain),
                item.name,
                item.start,
                item.end,
            )
            qualified = ".".join((*item.owner_chain, item.name))
            parent_id: str | None = None
            if item.owner_chain:
                owner_name = ".".join(item.owner_chain)
                parent_candidates = [
                    record
                    for record in by_qualified.get(owner_name, ())
                    if record.start <= item.start and record.end >= item.end
                ]
                if parent_candidates:
                    parent_id = min(
                        parent_candidates,
                        key=lambda record: (record.end - record.start, record.start, record.symbol_id),
                    ).symbol_id
            record = DeclarationRecord(
                root_id=self.root.id,
                path=captured_file.path,
                file_digest=captured_file.digest,
                language=item.language,
                analyzer_id=analyzer_id,
                kind=item.kind,
                name=item.name,
                owner_chain=item.owner_chain,
                qualified_name=qualified,
                start=item.start,
                end=item.end,
                defining_start=item.defining_start,
                defining_end=item.defining_end,
                signature=item.signature,
                visibility=item.visibility,
                documentation=item.documentation,
                parent_id=parent_id,
                expandable=item.expandable,
                symbol_id=symbol_id,
            )
            records.append(record)
            by_qualified.setdefault(qualified, []).append(record)
        return tuple(records)

    # ------------------------------------------------------------------
    # Python declaration extraction

    @staticmethod
    def _python_visibility(name: str) -> Literal["public", "private"]:
        return "private" if name.startswith("_") and not (name.startswith("__") and name.endswith("__")) else "public"

    @staticmethod
    def _python_node_bytes(node: ast.AST, geometry: _SourceGeometry) -> tuple[int, int]:
        start_line = int(getattr(node, "lineno", 1))
        start_col = int(getattr(node, "col_offset", 0))
        end_line = int(getattr(node, "end_lineno", start_line))
        end_col = int(getattr(node, "end_col_offset", start_col))
        if (
            start_line < 1
            or end_line < start_line
            or start_line > geometry.line_count
            or end_line > geometry.line_count
        ):
            raise _IndexerFailure("unsupported_syntax", "Python declaration range is outside the captured source")
        start = geometry.line_starts[start_line - 1] + start_col
        end = geometry.line_starts[end_line - 1] + end_col
        return start, end

    @staticmethod
    def _python_name_bytes(node: ast.AST, geometry: _SourceGeometry, start: int, end: int) -> tuple[int, int]:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.target if isinstance(node, ast.AnnAssign) else (node.targets[0] if node.targets else None)
            if isinstance(target, ast.Name):
                return XRayIndexer._python_node_bytes(target, geometry)
        snippet = geometry.decode(start, end)
        match = re.search(r"(?:async\s+def|def|class)\s+([\w]+)", snippet)
        if match is None:
            return start, min(end, start + len(node.__class__.__name__.encode("utf-8")))
        name_start = start + len(snippet[: match.start(1)].encode("utf-8"))
        name_end = name_start + len(match.group(1).encode("utf-8"))
        return name_start, name_end

    @staticmethod
    def _python_signature(node: ast.AST, name: str, geometry: _SourceGeometry, start: int, end: int) -> str:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            try:
                value = f"{prefix} {name}({ast.unparse(node.args)})"
                if node.returns is not None:
                    value += f" -> {ast.unparse(node.returns)}"
                return value + ":"
            except Exception:
                return geometry.decode(start, end).splitlines()[0].strip()
        if isinstance(node, ast.ClassDef):
            try:
                bases = [ast.unparse(base) for base in node.bases]
                bases.extend(ast.unparse(keyword) for keyword in node.keywords)
                suffix = f"({', '.join(bases)})" if bases else ""
                return f"class {name}{suffix}:"
            except Exception:
                return geometry.decode(start, end).splitlines()[0].strip()
        return geometry.decode(start, end).splitlines()[0].strip()

    def _python_declarations(
        self,
        text: str,
        geometry: _SourceGeometry,
        *,
        budget: OperationBudget | None = None,
    ) -> tuple[list[_RawDeclaration], bool]:
        if budget is not None:
            budget.check_deadline()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return [], True
        raw: list[_RawDeclaration] = []

        def add(node: ast.AST, owners: tuple[str, ...], role: str) -> None:
            if budget is not None:
                budget.check_deadline()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                kind = "method" if owners and role == "member" else "function"
                expandable = True
                documentation = ast.get_docstring(node, clean=False)
            elif isinstance(node, ast.ClassDef):
                name = node.name
                kind = "class"
                expandable = True
                documentation = ast.get_docstring(node, clean=False)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name = node.target.id
                kind = "field" if owners else "variable"
                expandable = False
                documentation = None
            elif isinstance(node, ast.Assign):
                targets = [target for target in node.targets if isinstance(target, ast.Name)]
                if not targets:
                    return
                start, end = self._python_node_bytes(node, geometry)
                for target in targets:
                    name_value = target.id
                    defining_start, defining_end = self._python_node_bytes(target, geometry)
                    raw.append(
                        _RawDeclaration(
                            language="python",
                            kind="field" if owners else "variable",
                            name=name_value,
                            owner_chain=owners,
                            start=start,
                            end=end,
                            defining_start=defining_start,
                            defining_end=defining_end,
                            signature=geometry.decode(start, end).splitlines()[0].strip(),
                            visibility=self._python_visibility(name_value),
                            documentation=None,
                            expandable=False,
                        )
                    )
                return
            else:
                return
            start, end = self._python_node_bytes(node, geometry)
            defining_start, defining_end = self._python_name_bytes(node, geometry, start, end)
            raw.append(
                _RawDeclaration(
                    language="python",
                    kind=kind,
                    name=name,
                    owner_chain=owners,
                    start=start,
                    end=end,
                    defining_start=defining_start,
                    defining_end=defining_end,
                    signature=self._python_signature(node, name, geometry, start, end),
                    visibility=self._python_visibility(name),
                    documentation=documentation,
                    expandable=expandable,
                )
            )

        def visit_statement(node: ast.stmt, owners: tuple[str, ...], in_function: bool) -> None:
            if budget is not None:
                budget.check_deadline()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                role = "member" if owners and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "item"
                add(node, owners, role)
                child_owners = (*owners, node.name)
                child_in_function = in_function or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                for child in node.body:
                    visit_statement(child, child_owners, child_in_function)
                return
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and not in_function:
                add(node, owners, "member" if owners else "item")
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.stmt):
                    visit_statement(child, owners, in_function)

        for statement in tree.body:
            visit_statement(statement, (), False)
        if budget is not None:
            budget.check_deadline()
        return raw, False

    # ------------------------------------------------------------------
    # ast-grep declaration extraction for JavaScript, TypeScript and Go

    @staticmethod
    def _node_kind(node: Any) -> str:
        try:
            return str(node.kind())
        except Exception:
            return ""

    @staticmethod
    def _node_parent(node: Any) -> Any | None:
        try:
            return node.parent()
        except Exception:
            return None

    @staticmethod
    def _node_field(node: Any, field: str) -> Any | None:
        try:
            return node.field(field)
        except Exception:
            return None

    @staticmethod
    def _node_text(node: Any) -> str:
        try:
            return str(node.text())
        except Exception:
            return ""

    @staticmethod
    def _node_range(node: Any, geometry: _SourceGeometry) -> tuple[int, int]:
        try:
            value = node.range()
            return geometry.char_index_to_byte(int(value.start.index)), geometry.char_index_to_byte(
                int(value.end.index)
            )
        except Exception as exc:
            raise _IndexerFailure("unsupported_syntax", "parser returned an invalid declaration range") from exc

    @staticmethod
    def _tree_declaration_kinds(language: str) -> set[str]:
        if language == "javascript":
            return {
                "class_declaration",
                "function_declaration",
                "method_definition",
                "variable_declarator",
                "property_definition",
            }
        if language == "typescript":
            return {
                "abstract_class_declaration",
                "class_declaration",
                "function_declaration",
                "method_definition",
                "method_signature",
                "variable_declarator",
                "property_definition",
                "public_field_definition",
                "interface_declaration",
                "property_signature",
                "type_alias_declaration",
                "enum_declaration",
                "enum_member",
                "internal_module",
            }
        return {
            "type_spec",
            "field_declaration",
            "function_declaration",
            "method_declaration",
            "const_spec",
            "var_spec",
        }

    @staticmethod
    def _tree_is_owner(node: Any, language: str) -> bool:
        kind = XRayIndexer._node_kind(node)
        if language in {"javascript", "typescript"}:
            return (
                kind
                in {
                    "abstract_class_declaration",
                    "class_declaration",
                    "function_declaration",
                    "method_definition",
                    "interface_declaration",
                    "internal_module",
                    "enum_declaration",
                    "variable_declarator",
                }
                and XRayIndexer._node_name(node, language) is not None
            )
        return kind in {"type_spec", "function_declaration", "method_declaration"}

    @staticmethod
    def _node_name(node: Any, language: str) -> tuple[str, Any] | None:
        value = XRayIndexer._node_field(node, "name")
        if value is not None:
            text = XRayIndexer._node_text(value)
            if text and re.fullmatch(r"[\w$#]+", text, flags=re.UNICODE):
                return text, value
        kind = XRayIndexer._node_kind(node)
        if language == "go" and kind == "field_declaration":
            for child in getattr(node, "children", lambda: [])():
                if XRayIndexer._node_kind(child) == "field_identifier":
                    text = XRayIndexer._node_text(child)
                    if text:
                        return text, child
        return None

    @staticmethod
    def _tree_kind(node: Any, language: str) -> str:
        kind = XRayIndexer._node_kind(node)
        if kind in {"class_declaration", "abstract_class_declaration"}:
            return "class"
        if kind in {"function_declaration"}:
            return "function"
        if kind in {"method_definition", "method_signature", "method_declaration"}:
            return "method"
        if kind in {"interface_declaration"}:
            return "interface"
        if kind in {"type_alias_declaration", "type_spec"}:
            type_node = XRayIndexer._node_field(node, "type")
            type_kind = XRayIndexer._node_kind(type_node) if type_node is not None else ""
            if language == "go" and type_kind in {"struct_type", "interface_type"}:
                return "struct" if type_kind == "struct_type" else "interface"
            return "type"
        if kind in {"enum_declaration"}:
            return "enum"
        if kind in {"enum_member"}:
            return "enum_member"
        if kind in {"property_signature", "property_definition", "public_field_definition", "field_declaration"}:
            return "field"
        if kind in {"const_spec"}:
            return "constant"
        if kind in {"var_spec", "variable_declarator"}:
            value = XRayIndexer._node_field(node, "value")
            value_kind = XRayIndexer._node_kind(value) if value is not None else ""
            return "function" if value_kind in {"arrow_function", "function", "function_expression"} else "variable"
        return "symbol"

    @staticmethod
    def _tree_expandable(kind: str) -> bool:
        return kind in {"class", "function", "method", "interface", "struct", "enum", "type"}

    @staticmethod
    def _tree_visibility(node: Any, name: str, language: str) -> Literal["public", "private", "unknown"]:
        if language == "go":
            return "public" if name[:1].isupper() else "private"
        if name.startswith("#"):
            return "private"
        parent = XRayIndexer._node_parent(node)
        for _ in range(8):
            if parent is None:
                break
            if XRayIndexer._node_kind(parent) == "export_statement":
                return "public"
            parent = XRayIndexer._node_parent(parent)
        return "unknown"

    @staticmethod
    def _tree_owner_chain(node: Any, language: str) -> tuple[str, ...]:
        owners: list[str] = []
        parent = XRayIndexer._node_parent(node)
        while parent is not None:
            if XRayIndexer._tree_is_owner(parent, language):
                info = XRayIndexer._node_name(parent, language)
                if info is not None:
                    owners.append(info[0])
            parent = XRayIndexer._node_parent(parent)
        if language == "go" and XRayIndexer._node_kind(node) == "method_declaration":
            receiver = None
            try:
                children = node.children()
            except Exception:
                children = []
            for child in children:
                if XRayIndexer._node_kind(child) != "parameter_list":
                    continue
                for parameter in getattr(child, "children", lambda: [])():
                    type_node = XRayIndexer._node_field(parameter, "type")
                    if type_node is not None:
                        receiver = XRayIndexer._node_text(type_node).lstrip("*")
                        break
                if receiver:
                    break
            if receiver:
                owners.insert(0, receiver)
        owners.reverse()
        return tuple(owners)

    @staticmethod
    def _tree_exported(node: Any) -> bool:
        parent = XRayIndexer._node_parent(node)
        for _ in range(8):
            if parent is None:
                return False
            if XRayIndexer._node_kind(parent) == "export_statement":
                return True
            parent = XRayIndexer._node_parent(parent)
        return False

    @staticmethod
    def _tree_signature(node: Any, geometry: _SourceGeometry, start: int, end: int) -> str:
        text = geometry.decode(start, end).strip()
        if "{" in text:
            return text[: text.find("{")].rstrip()
        return text.splitlines()[0].strip() if text.splitlines() else text

    def _tree_declarations(
        self,
        text: str,
        geometry: _SourceGeometry,
        language: str,
        *,
        budget: OperationBudget | None = None,
    ) -> tuple[list[_RawDeclaration], bool]:
        if budget is not None:
            budget.check_deadline()
        try:
            root = SgRoot(text, language).root()
            nodes = [
                node
                for node in root.find_all(pattern="$A")
                if self._node_kind(node) in self._tree_declaration_kinds(language)
            ]
            all_nodes = list(root.find_all(pattern="$A"))
            parse_diagnostic = any(self._node_kind(node) == "ERROR" for node in all_nodes)
        except Exception:
            return [], True
        raw: list[_RawDeclaration] = []
        seen: set[tuple[str, str, int, int, int, int]] = set()
        for node in nodes:
            if budget is not None:
                budget.check_deadline()
            info = self._node_name(node, language)
            if info is None:
                continue
            name, name_node = info
            kind = self._tree_kind(node, language)
            start, end = self._node_range(node, geometry)
            parent = self._node_parent(node)
            if self._node_kind(node) == "variable_declarator" and self._node_kind(parent) in {
                "lexical_declaration",
                "variable_declaration",
            }:
                start, end = self._node_range(parent, geometry)
            elif self._node_kind(node) in {"type_spec", "const_spec", "var_spec"} and self._node_kind(parent) in {
                "type_declaration",
                "const_declaration",
                "var_declaration",
            }:
                start, end = self._node_range(parent, geometry)
            defining_start, defining_end = self._node_range(name_node, geometry)
            key = (kind, name, start, end, defining_start, defining_end)
            if key in seen:
                continue
            seen.add(key)
            owners = self._tree_owner_chain(node, language)
            visibility = self._tree_visibility(node, name, language)
            if language in {"javascript", "typescript"} and self._tree_exported(node):
                visibility = "public"
            raw.append(
                _RawDeclaration(
                    language=language,
                    kind=kind,
                    name=name,
                    owner_chain=owners,
                    start=start,
                    end=end,
                    defining_start=defining_start,
                    defining_end=defining_end,
                    signature=self._tree_signature(node, geometry, start, end),
                    visibility=visibility,
                    documentation=None,
                    expandable=self._tree_expandable(kind),
                )
            )
        if budget is not None:
            budget.check_deadline()
        return raw, parse_diagnostic

    def _capture_namespace(
        self,
        selection: Selection,
        *,
        budget: OperationBudget | None = None,
        horizon: NamespaceHorizon | Mapping[str, Any] | None = None,
    ) -> RepositoryCapture:
        """Capture namespace metadata without reading selected source bodies."""
        provider = RepositoryProvider(self.root, selection)
        local_budget = budget or OperationBudget()
        local_budget.check_deadline()
        rules_cache: dict[str, Any] = {}
        namespace, _files, _directories, config = provider._collect_namespace(
            budget=local_budget,
            rules_cache=rules_cache,
            horizon=horizon,
        )
        manifest = provider._manifest(namespace=namespace, config=config, sources=(), budget=local_budget)
        return RepositoryCapture(namespace, manifest)

    @staticmethod
    def _path_is_descendant(path: str, parent: str) -> bool:
        return path == parent or (parent == "." and path != ".") or path.startswith(f"{parent}/")

    @staticmethod
    def _namespace_parts(path: str) -> tuple[str, ...]:
        return () if path == "." else tuple(path.split("/"))

    @classmethod
    def _ancestor_paths(cls, path: str) -> tuple[str, ...]:
        parts = cls._namespace_parts(path)
        return tuple("/".join(parts[:index]) or "." for index in range(1, len(parts) + 1))

    def _map_projection(
        self,
        capture: RepositoryCapture,
        query: Any,
        *,
        budget: OperationBudget | None = None,
    ) -> _MapProjection:
        if capture.namespace is None:
            raise _IndexerFailure("internal_error", "map capture did not include namespace metadata")
        local_budget = budget or OperationBudget()
        local_budget.check_deadline()
        focus_specs = tuple(
            (parts, len(parts)) for scope in tuple(query.focus) for parts in (self._namespace_parts(scope),)
        )
        ancestor_membership = frozenset(
            ancestor for scope in tuple(query.focus) for ancestor in self._ancestor_paths(scope)
        )
        finite_depth = query.depth != "all"
        depth = int(query.depth) if finite_depth else None
        projected: list[_MapRow] = []
        for entry in capture.namespace.entries:
            local_budget.check_deadline()
            if entry.path == ".":
                continue
            entry_parts = self._namespace_parts(entry.path)
            best_distance: int | None = None
            for scope_parts, scope_depth in focus_specs:
                if entry_parts[:scope_depth] != scope_parts:
                    continue
                distance = len(entry_parts) - scope_depth
                if best_distance is None or distance < best_distance:
                    best_distance = distance
            if best_distance is None:
                if query.context != "ancestors" or entry.path not in ancestor_membership:
                    continue
                frontier = False
            elif depth is not None and best_distance > depth:
                continue
            else:
                frontier = bool(depth is not None and entry.kind == "directory" and best_distance == depth)
            row_id = digest(
                [
                    _MAP_ROW_SCHEMA,
                    entry.path,
                    entry.kind,
                    entry.language,
                    frontier,
                ]
            )
            projected.append(_MapRow(entry=entry, frontier=frontier, row_id=row_id))
        return _MapProjection(projected)

    def _map_items(
        self,
        capture: RepositoryCapture,
        query: Any,
        *,
        budget: OperationBudget | None = None,
    ) -> list[MapItem]:
        projection = self._map_projection(capture, query, budget=budget)
        return list(projection)

    @staticmethod
    def _map_row_id(item: MapItem) -> str:
        return digest(
            [
                _MAP_ROW_SCHEMA,
                item.path,
                item.kind,
                item.language,
                bool(item.frontier),
            ]
        )

    def _capture_sources(
        self,
        selection: Selection | None,
        *,
        capture_domain: CaptureDomain = SUPPORTED_SOURCE_DOMAIN,
        budget: OperationBudget | None = None,
    ) -> RepositoryCapture:
        provider = RepositoryProvider(self.root, selection)
        local_budget = budget or OperationBudget()
        local_budget.check_deadline()
        return provider.capture(
            include_namespace=False,
            budget=local_budget,
            capture_domain=capture_domain,
        )

    @staticmethod
    def _coverage_for_artifacts(
        artifacts: Iterable[DeclarationArtifact],
        *,
        non_text: Iterable[str] = (),
    ) -> Coverage:
        reasons: list[CoverageReason] = []
        for artifact in artifacts:
            if artifact.coverage.state == "partial":
                reasons.extend(artifact.coverage.reasons or [])
        reasons.extend(CoverageReason(code="non_text_input", path=path) for path in non_text)
        unique = {(reason.code, reason.path or "", reason.count or 0): reason for reason in reasons}
        if not unique:
            return Coverage(state="complete", basis="supported_declarations")
        ordered = sorted(
            unique.values(),
            key=lambda reason: (reason.code.encode("utf-8"), (reason.path or "").encode("utf-8"), reason.count or 0),
        )
        return Coverage(state="partial", basis="supported_declarations", reasons=ordered)

    def _validate_cursor_identity(
        self,
        page_cursor: str,
        *,
        op: Literal["map", "find", "interface", "search", "impact", "read"],
        query_digest: str,
        selection: str,
        snapshot: str,
        toolchain: str,
    ) -> RepositoryCursor:
        """Decode a cursor and apply the shared identity precedence.

        Cursor shape is validated before semantic identity. Operation/root
        differences are query mismatches, while a changed captured/toolchain
        identity is stale. The checkpoint is intentionally left to each
        projection because membership is the final validation step.
        """

        try:
            cursor = decode_cursor(page_cursor)
        except Exception as exc:
            raise _IndexerFailure("invalid_cursor", "cursor is malformed", action="restart_query") from exc
        if cursor is None:
            raise _IndexerFailure("invalid_cursor", "cursor is malformed", action="restart_query")
        if cursor.op != op or cursor.root != self.root.id:
            raise _IndexerFailure("cursor_query_mismatch", "cursor does not match this request", action="restart_query")
        if cursor.selection != selection or cursor.snapshot != snapshot or cursor.toolchain != toolchain:
            raise _IndexerFailure(
                "stale_cursor",
                "cursor does not match the captured source set",
                action="restart_query",
            )
        if cursor.query != query_digest:
            raise _IndexerFailure("cursor_query_mismatch", "cursor does not match this request", action="restart_query")
        return cursor

    def _seek_collection(
        self,
        page_cursor: str | None,
        *,
        op: Literal["map", "find", "interface"],
        query_digest: str,
        capture: RepositoryCapture,
        row_ids: Sequence[str],
        budget: OperationBudget | None = None,
    ) -> int:
        if budget is not None:
            budget.check_deadline()
        if page_cursor is None:
            return 0
        cursor = self._validate_cursor_identity(
            page_cursor,
            op=op,
            query_digest=query_digest,
            selection=capture.manifest.selection_digest,
            snapshot=capture.manifest.snapshot_digest,
            toolchain=self._toolchain_id(),
        )
        checkpoint = cursor.checkpoint
        expected_kind = {"map": "namespace", "find": "rank", "interface": "interface"}[op]
        if checkpoint.kind != expected_kind:
            raise _IndexerFailure("invalid_cursor", "cursor has the wrong checkpoint kind", action="restart_query")
        after = getattr(checkpoint, "after", None)
        if after is None:
            raise _IndexerFailure(
                "invalid_cursor",
                "cursor checkpoint does not identify a result row",
                action="restart_query",
            )
        for index, row_id in enumerate(row_ids):
            if budget is not None:
                budget.check_deadline()
            if row_id == after:
                return index + 1
        raise _IndexerFailure(
            "invalid_cursor",
            "cursor checkpoint does not identify a result row",
            action="restart_query",
        )

    def _collection_result(
        self,
        *,
        op: Literal["map", "find", "interface"],
        capture: RepositoryCapture,
        provenance: RepositoryProvenance,
        coverage: Coverage,
        page: Any,
        rows: Sequence[Any],
        start: int,
        row_ids: Sequence[str],
        data_factory: Any,
        owners: Sequence[InterfaceOwner] | None = None,
        budget: OperationBudget | None = None,
    ) -> Success:
        local_budget = budget or OperationBudget()
        local_budget.check_deadline()
        remaining = max(len(rows) - start, 0)
        requested = min(page.limit, remaining)
        checkpoint_kind = {"map": "namespace", "find": "rank", "interface": "interface"}[op]

        def cursor_for(after: str) -> str:
            return encode_cursor(
                RepositoryCursor(
                    version=1,
                    op=op,
                    root=self.root.id,
                    query=provenance.query,
                    selection=provenance.selection,
                    snapshot=provenance.snapshot,
                    toolchain=self._toolchain_id(),
                    checkpoint=cast(Any, {"kind": checkpoint_kind, "after": after}),
                )
            )

        def build(values: Sequence[Any], next_cursor: str | None) -> Success:
            local_budget.check_deadline()
            data = data_factory(list(values), owners)
            page_result = (
                PageResult(total=len(rows))
                if next_cursor is None
                else PageResult(next_cursor=next_cursor, total=len(rows))
            )
            return Success(
                schema="xray.v1",
                ok=True,
                op=op,
                root=capture.root,
                scope=capture.selection,
                provenance=provenance,
                data=data,
                page=page_result,
                coverage=coverage,
            )

        if requested == 0:
            result = build([], None)
            minimum = len(canonical_bytes(result))
            if minimum <= page.max_bytes:
                return result
            raise _IndexerFailure(
                "budget_too_small",
                f"{op} result cannot fit the requested byte budget (minimum {minimum} bytes)",
                action="narrow_query",
            )

        values: list[Any] = []
        row_sizes: list[int] = []
        for offset in range(requested):
            local_budget.check_deadline()
            value = rows[start + offset]
            values.append(value)
            row_sizes.append(len(canonical_bytes(value)))

        terminal_base = len(canonical_bytes(build([], None)))
        placeholder_cursor = cursor_for("0" * 64)
        continuation_base = len(canonical_bytes(build([], placeholder_cursor)))
        best = 0
        accumulated = 0
        for count, row_size in enumerate(row_sizes, start=1):
            local_budget.check_deadline()
            accumulated += row_size
            base = terminal_base if start + count == len(rows) else continuation_base
            candidate_size = base + accumulated + count - 1
            if candidate_size <= page.max_bytes:
                best = count

        if best == 0:
            minimum = len(canonical_bytes(build([values[0]], cursor_for(row_ids[start]))))
            raise _IndexerFailure(
                "budget_too_small",
                f"{op} result cannot fit the requested byte budget (minimum {minimum} bytes)",
                action="narrow_query",
            )

        while best > 0:
            local_budget.check_deadline()
            next_cursor = None if start + best >= len(rows) else cursor_for(row_ids[start + best - 1])
            result = build(values[:best], next_cursor)
            if len(canonical_bytes(result)) <= page.max_bytes:
                return result
            best -= 1
        raise _IndexerFailure(
            "budget_too_small",
            f"{op} result cannot fit the requested byte budget",
            action="narrow_query",
        )

    @staticmethod
    def _find_match(
        text: str,
        declaration: DeclarationRecord,
        *,
        match: str,
    ) -> tuple[str, int] | None:
        query = text
        folded = query.casefold()
        qualified = declaration.qualified_name
        name = declaration.name
        path_contexts = {
            f"{declaration.path}:{qualified}",
            f"{declaration.path}::{qualified}",
            f"{declaration.path}/{qualified}",
        }
        if query == qualified:
            return "exact_qualified_name", 700
        if query == name:
            return "exact_name", 680
        if query in path_contexts:
            return "exact_path_context", 670
        if match == "exact":
            return None
        if folded == qualified.casefold() or folded == name.casefold():
            return "normalized_name", 560
        if qualified.startswith(query) or name.startswith(query):
            return "prefix", 460
        name_tokens = set(re.findall(r"[A-Za-z0-9_$]+", qualified))
        if query in name_tokens or folded in {token.casefold() for token in name_tokens}:
            return "token", 360
        if match != "fuzzy":
            return None
        if folded and all(character in qualified.casefold() for character in folded):
            return "fuzzy", 260
        return None

    @staticmethod
    def _find_sort_key(candidate: _FindCandidate) -> tuple[Any, ...]:
        precedence = {
            "exact_qualified_name": 0,
            "exact_name": 1,
            "exact_path_context": 2,
            "normalized_name": 3,
            "prefix": 4,
            "token": 5,
            "fuzzy": 6,
        }
        declaration = candidate.declaration
        return (
            -candidate.rank,
            precedence[candidate.match_kind],
            declaration.qualified_name.encode("utf-8"),
            declaration.qualified_name,
            declaration.path.encode("utf-8"),
            declaration.start,
            declaration.end,
            declaration.symbol_id,
            candidate.row_id,
        )

    def _find_items(
        self,
        capture: RepositoryCapture,
        query: Any,
        *,
        cache: DerivedCache | None,
        budget: OperationBudget | None = None,
    ) -> tuple[Sequence[FindItem], Coverage]:
        local_budget = budget or OperationBudget()
        candidates: list[_FindCandidate] = []
        artifacts: list[DeclarationArtifact] = []
        non_text: list[str] = []
        geometries: dict[str, _SourceGeometry] = {}
        total_declarations = 0
        for captured in capture.files:
            local_budget.check_deadline()
            if captured.language not in {"python", "javascript", "typescript", "go"}:
                continue
            if not captured.is_text:
                non_text.append(captured.path)
                continue
            geometry = _SourceGeometry.from_text(self._captured_text(captured), data=captured.content)
            geometries[captured.path] = geometry
            artifact = self._declarations_for(captured, cache=cache, geometry=geometry, budget=local_budget)
            artifacts.append(artifact)
            total_declarations += len(artifact.declarations)
            if total_declarations > _MAX_FIND_DECLARATIONS:
                raise _IndexerFailure(
                    "analysis_limit",
                    "find declaration population exceeds the bounded limit",
                    action="narrow_query",
                )
            if len(artifact.declarations) > _MAX_FIND_CANDIDATES_PER_FILE:
                raise _IndexerFailure(
                    "analysis_limit",
                    "find candidates per file exceed the bounded limit",
                    path=captured.path,
                )
            for declaration in artifact.declarations:
                local_budget.check_deadline()
                if query.kinds is not None and declaration.kind not in query.kinds:
                    continue
                if query.visibility is not None and declaration.visibility not in query.visibility:
                    continue
                match = self._find_match(query.text, declaration, match=query.match)
                if match is None:
                    continue
                match_kind, rank = match
                row_id = find_row_digest(
                    declaration.path,
                    declaration.start,
                    declaration.end,
                    declaration.symbol_id,
                )
                candidates.append(_FindCandidate(declaration, cast(Any, match_kind), rank, row_id))
        candidates.sort(key=self._find_sort_key)
        row_ids = [candidate.row_id for candidate in candidates]
        if len(row_ids) != len(set(row_ids)):
            raise _IndexerFailure("internal_error", "find row identities are not unique")
        local_budget.check_deadline()
        return _FindProjection(candidates, geometries), self._coverage_for_artifacts(artifacts, non_text=non_text)

    @staticmethod
    def _python_tokens(
        text: str,
        geometry: _SourceGeometry,
        node: ast.AST,
    ) -> tuple[tuple[Any, int, int], ...]:
        import io
        import tokenize

        start, end = XRayIndexer._python_node_bytes(node, geometry)
        start_char = geometry.byte_index_to_char(start)
        end_char = geometry.byte_index_to_char(end)

        def absolute(line: int, column: int) -> int:
            if line < 1 or line > geometry.line_count:
                return -1
            line_char = geometry.byte_index_to_char(geometry.line_starts[line - 1])
            return line_char + column

        try:
            tokens = tokenize.generate_tokens(io.StringIO(text).readline)
            values: list[tuple[Any, int, int]] = []
            for token in tokens:
                token_start = absolute(*token.start)
                token_end = absolute(*token.end)
                if token_start < start_char or token_end > end_char or token_end < token_start:
                    continue
                if token.type in {
                    tokenize.ENCODING,
                    tokenize.ENDMARKER,
                    tokenize.INDENT,
                    tokenize.DEDENT,
                    tokenize.NL,
                    tokenize.NEWLINE,
                    tokenize.COMMENT,
                }:
                    continue
                values.append((token, token_start, token_end))
            return tuple(values)
        except (tokenize.TokenError, IndentationError, SyntaxError):
            return ()

    @staticmethod
    def _python_alias_spans(
        text: str,
        geometry: _SourceGeometry,
        node: ast.Import | ast.ImportFrom,
    ) -> tuple[tuple[ast.alias, int, int], ...]:
        tokens = XRayIndexer._python_tokens(text, geometry, node)
        if not tokens:
            return ()
        import_index = next(
            (index for index, (token, _start, _end) in enumerate(tokens) if token.string == "import"), None
        )
        if import_index is None:
            return ()
        cursor = import_index + 1
        values: list[tuple[ast.alias, int, int]] = []
        for alias in node.names:
            parts = ["*"] if alias.name == "*" else alias.name.split(".")
            match_start: int | None = None
            match_end: int | None = None
            position = cursor
            for part_index, part in enumerate(parts):
                while position < len(tokens) and tokens[position][0].string in {"(", ")", ","}:
                    position += 1
                if position >= len(tokens) or tokens[position][0].string != part:
                    match_start = None
                    break
                if match_start is None:
                    match_start = tokens[position][1]
                match_end = tokens[position][2]
                position += 1
                if part_index + 1 < len(parts):
                    if position >= len(tokens) or tokens[position][0].string != ".":
                        match_start = None
                        break
                    position += 1
            if match_start is None or match_end is None:
                return ()
            if alias.asname is not None:
                while position < len(tokens) and tokens[position][0].string == "as":
                    position += 1
                    break
                if position >= len(tokens) or tokens[position][0].string != alias.asname:
                    return ()
                match_end = tokens[position][2]
                position += 1
            values.append((alias, match_start, match_end))
            cursor = position
        return tuple(values)

    @staticmethod
    def _observation_span(
        geometry: _SourceGeometry,
        start_char: int,
        end_char: int,
    ) -> tuple[int, int]:
        return geometry.char_index_to_byte(start_char), geometry.char_index_to_byte(end_char)

    @staticmethod
    def _contained_span(
        span: tuple[int, int],
        containers: Iterable[tuple[int, int]],
    ) -> bool:
        start, end = span
        return any(container_start <= start and end <= container_end for container_start, container_end in containers)

    @staticmethod
    def _python_observations(text: str, geometry: _SourceGeometry) -> list[_SyntaxObservation]:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
        observations: list[_SyntaxObservation] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            aliases = XRayIndexer._python_alias_spans(text, geometry, node)
            if not aliases:
                continue
            module = None if isinstance(node, ast.Import) else "." * node.level + (node.module or "")
            for alias, start_char, end_char in aliases:
                start, end = XRayIndexer._observation_span(geometry, start_char, end_char)
                observations.append(
                    _SyntaxObservation(
                        section="imports",
                        start=start,
                        end=end,
                        module_text=module or alias.name,
                        imported_name=alias.name,
                        local_name=alias.asname,
                    )
                )
        return observations

    @staticmethod
    def _tree_string_value(node: Any) -> str | None:
        if node is None:
            return None
        for child in getattr(node, "children", lambda: [])():
            if XRayIndexer._node_kind(child) in {"string_fragment", "interpreted_string_literal_content"}:
                return XRayIndexer._node_text(child)
        value = XRayIndexer._node_text(node)
        if len(value) >= _MIN_QUOTED_STRING_LENGTH and value[0] in {"'", '"', "`"} and value[-1] == value[0]:
            return value[1:-1]
        return value or None

    @staticmethod
    def _tree_descendants(node: Any) -> Iterable[Any]:
        for child in getattr(node, "children", lambda: [])():
            yield child
            yield from XRayIndexer._tree_descendants(child)

    def _tree_observations(self, text: str, geometry: _SourceGeometry, language: str) -> list[_SyntaxObservation]:
        try:
            root = SgRoot(text, language).root()
            statements = [
                node
                for node in root.find_all(pattern="$A")
                if self._node_kind(node) in {"import_statement", "import_declaration", "export_statement"}
            ]
        except Exception:
            return []
        observations: list[_SyntaxObservation] = []

        def span(node: Any) -> tuple[int, int]:
            return self._node_range(node, geometry)

        def add_import(statement: Any) -> None:
            module = self._tree_string_value(self._node_field(statement, "source"))
            clause = next(
                (
                    child
                    for child in getattr(statement, "children", lambda: [])()
                    if self._node_kind(child) == "import_clause"
                ),
                None,
            )
            if clause is None:
                start, end = span(statement)
                observations.append(_SyntaxObservation("imports", start, end, module_text=module))
                return
            emitted = False
            for child in getattr(clause, "children", lambda: [])():
                kind = self._node_kind(child)
                if kind == "identifier":
                    start, end = span(child)
                    observations.append(
                        _SyntaxObservation(
                            "imports",
                            start,
                            end,
                            module_text=module,
                            imported_name="default",
                            local_name=self._node_text(child),
                        )
                    )
                    emitted = True
                elif kind == "namespace_import":
                    local = next(
                        (
                            grandchild
                            for grandchild in getattr(child, "children", lambda: [])()
                            if self._node_kind(grandchild) == "identifier"
                        ),
                        None,
                    )
                    start, end = span(child)
                    observations.append(
                        _SyntaxObservation(
                            "imports",
                            start,
                            end,
                            module_text=module,
                            imported_name="*",
                            local_name=self._node_text(local) if local is not None else None,
                        )
                    )
                    emitted = True
                elif kind == "named_imports":
                    for specifier in getattr(child, "children", lambda: [])():
                        if self._node_kind(specifier) != "import_specifier":
                            continue
                        imported = self._node_field(specifier, "name")
                        alias = self._node_field(specifier, "alias")
                        start, end = span(specifier)
                        observations.append(
                            _SyntaxObservation(
                                "imports",
                                start,
                                end,
                                module_text=module,
                                imported_name=self._node_text(imported) if imported is not None else None,
                                local_name=self._node_text(alias) if alias is not None else None,
                            )
                        )
                        emitted = True
            if not emitted:
                start, end = span(statement)
                observations.append(_SyntaxObservation("imports", start, end, module_text=module))

        def add_export(statement: Any) -> None:
            module = self._tree_string_value(self._node_field(statement, "source"))
            children = list(getattr(statement, "children", lambda: [])())
            descendants = [*children, *self._tree_descendants(statement)]
            if any(
                self._node_kind(node) in {"namespace_export", "namespace_export_clause", "wildcard_export"}
                or (
                    self._node_text(node) == "*"
                    and self._node_kind(node) not in {"comment", "line_comment", "block_comment"}
                )
                for node in descendants
            ):
                start, end = span(statement)
                observations.append(_SyntaxObservation("exports", start, end, module_text=module, kind="star"))
                return
            for child in children:
                kind = self._node_kind(child)
                if kind == "export_clause":
                    for specifier in getattr(child, "children", lambda: [])():
                        if self._node_kind(specifier) != "export_specifier":
                            continue
                        name_node = self._node_field(specifier, "name")
                        alias_node = self._node_field(specifier, "alias")
                        start, end = span(specifier)
                        observations.append(
                            _SyntaxObservation(
                                "exports",
                                start,
                                end,
                                module_text=module,
                                name=(
                                    self._node_text(alias_node)
                                    if alias_node is not None
                                    else self._node_text(name_node) or None
                                ),
                                kind="reexport" if module is not None else "named",
                            )
                        )
                    return
                if kind == "namespace_export":
                    start, end = span(child)
                    observations.append(_SyntaxObservation("exports", start, end, module_text=module, kind="star"))
                    return
                if kind in {"function_declaration", "class_declaration", "lexical_declaration", "variable_declaration"}:
                    name = None
                    for descendant in (child, *self._tree_descendants(child)):
                        info = self._node_name(descendant, language)
                        if info is not None:
                            name = info[0]
                            break
                    start, end = span(statement)
                    observations.append(
                        _SyntaxObservation(
                            "exports",
                            start,
                            end,
                            module_text=module,
                            name=name,
                            kind="default" if any(self._node_kind(item) == "default" for item in children) else "named",
                        )
                    )
                    return
            start, end = span(statement)
            observations.append(
                _SyntaxObservation(
                    "exports",
                    start,
                    end,
                    module_text=module,
                    kind="default" if any(self._node_kind(item) == "default" for item in children) else "unknown",
                )
            )

        for statement in statements:
            if self._node_kind(statement) in {"import_statement", "import_declaration"}:
                if language in {"javascript", "typescript"}:
                    add_import(statement)
                else:
                    for specifier in self._tree_descendants(statement):
                        if self._node_kind(specifier) != "import_spec":
                            continue
                        path_node = self._node_field(specifier, "path")
                        alias_node = self._node_field(specifier, "name")
                        start, end = span(specifier)
                        observations.append(
                            _SyntaxObservation(
                                "imports",
                                start,
                                end,
                                module_text=self._tree_string_value(path_node) or "",
                                local_name=self._node_text(alias_node) if alias_node is not None else None,
                            )
                        )
            elif language in {"javascript", "typescript"}:
                add_export(statement)
        observations.sort(key=lambda item: (_SECTION_ORDER[item.section], item.start, item.end, item.name or ""))
        return observations

    def _observations(
        self,
        captured_file: CapturedFile,
        geometry: _SourceGeometry,
    ) -> list[_SyntaxObservation]:
        text = self._captured_text(captured_file)
        if captured_file.language == "python":
            return self._python_observations(text, geometry)
        if captured_file.language in {"javascript", "typescript", "go"}:
            return self._tree_observations(text, geometry, captured_file.language)
        return []

    def _interface_observation_items(
        self,
        captured_file: CapturedFile,
        geometry: _SourceGeometry,
        sections: Sequence[str],
    ) -> list[Import | Export]:
        selected = set(sections)
        values: list[Import | Export] = []
        for observation in self._observations(captured_file, geometry):
            if observation.section not in selected:
                continue
            occurrence = OccurrenceRef(
                kind="occurrence",
                root_id=self.root.id,
                path=captured_file.path,
                file_digest=captured_file.digest,
                start=observation.start,
                end=observation.end,
                occurrence_id=occurrence_digest(
                    captured_file.path,
                    captured_file.digest,
                    observation.start,
                    observation.end,
                ),
            )
            if observation.section == "imports":
                import_values: dict[str, Any] = {
                    "section": "imports",
                    "ref": occurrence,
                    "module_text": observation.module_text or "",
                }
                if observation.imported_name is not None:
                    import_values["imported_name"] = observation.imported_name
                if observation.local_name is not None:
                    import_values["local_name"] = observation.local_name
                values.append(Import(**import_values))
            else:
                export_values: dict[str, Any] = {
                    "section": "exports",
                    "ref": occurrence,
                    "kind": observation.kind,
                }
                if observation.name is not None:
                    export_values["name"] = observation.name
                if observation.module_text is not None:
                    export_values["module_text"] = observation.module_text
                values.append(Export(**export_values))
        values.sort(
            key=lambda item: (
                _SECTION_ORDER[item.section],
                item.ref.start,
                item.ref.end,
                item.ref.occurrence_id,
            )
        )
        return values

    @staticmethod
    def _interface_row_id(item: Any) -> str:
        if isinstance(item, Declaration):
            return digest(
                [
                    "xray.interface.row.v1",
                    "symbols",
                    item.ref.path,
                    item.ref.start,
                    item.ref.end,
                    item.ref.symbol_id,
                ]
            )
        return digest(
            [
                "xray.interface.row.v1",
                item.section,
                item.ref.path,
                item.ref.start,
                item.ref.end,
                item.ref.occurrence_id,
            ]
        )

    @staticmethod
    def _declaration_value(record: DeclarationRecord, *, documentation: bool) -> Declaration:
        signature, signature_clipped = XRayIndexer._clip_text(record.signature, 2048)
        documentation_value: str | None = None
        documentation_clipped = False
        if documentation and record.documentation is not None:
            documentation_value, documentation_clipped = XRayIndexer._clip_text(record.documentation, 512)
        values: dict[str, Any] = {
            "section": "symbols",
            "ref": record.ref,
            "name": record.name,
            "kind": record.kind,
            "qualified_name": record.qualified_name,
            "signature": signature,
            "visibility": record.visibility,
        }
        if record.parent_id is not None:
            values["parent_id"] = record.parent_id
        if record.expandable:
            values["expandable"] = True
        if documentation_value is not None:
            values["documentation"] = documentation_value
        clipped: list[Literal["signature", "documentation", "text", "captures"]] = []
        if signature_clipped:
            clipped.append("signature")
        if documentation_clipped:
            clipped.append("documentation")
        if clipped:
            values["disclosure"] = Disclosure(clipped=clipped)
        return Declaration(**values)

    def _owner_values(self, artifact: DeclarationArtifact, record: DeclarationRecord) -> list[InterfaceOwner]:
        by_id = {item.symbol_id: item for item in artifact.declarations}
        chain: list[DeclarationRecord] = []
        parent_id = record.parent_id
        while parent_id is not None and parent_id in by_id:
            parent = by_id[parent_id]
            chain.append(parent)
            parent_id = parent.parent_id
        chain.reverse()
        return [InterfaceOwner(ref=item.ref, name=item.name, kind=item.kind) for item in chain]

    def _interface_file_rows(
        self,
        captured_file: CapturedFile,
        query: InterfaceFileQuery,
        *,
        cache: DerivedCache | None,
        budget: OperationBudget | None = None,
    ) -> tuple[list[Any], Coverage]:
        local_budget = budget or OperationBudget()
        local_budget.check_deadline()
        if not captured_file.is_text:
            return [], Coverage(
                state="partial",
                basis="supported_declarations",
                reasons=[CoverageReason(code="non_text_input", path=captured_file.path)],
            )
        geometry = _SourceGeometry.from_text(self._captured_text(captured_file), data=captured_file.content)
        artifact = self._declarations_for(captured_file, cache=cache, geometry=geometry, budget=local_budget)
        declarations = list(artifact.declarations)
        seeds = declarations
        if query.kinds is not None:
            seeds = [item for item in seeds if item.kind in query.kinds]
        if query.visibility is not None:
            seeds = [item for item in seeds if item.visibility in query.visibility]
        seed_ids = {item.symbol_id for item in seeds}
        selected_ids = set(seed_ids)
        if query.member_depth == 1:
            selected_ids.update(item.symbol_id for item in declarations if item.parent_id in seed_ids)
        declaration_items = [
            self._declaration_value(item, documentation=query.documentation)
            for item in declarations
            if item.symbol_id in selected_ids
        ]
        observations = self._interface_observation_items(captured_file, geometry, query.sections)
        values: list[Any] = []
        if "symbols" in query.sections:
            values.extend(declaration_items)
        values.extend(item for item in observations if item.section in query.sections)
        values.sort(
            key=lambda item: (
                _SECTION_ORDER[item.section],
                item.ref.start,
                item.ref.end,
                item.ref.symbol_id if isinstance(item, Declaration) else item.ref.occurrence_id,
            )
        )
        local_budget.check_deadline()
        coverage = self._coverage_for_artifacts([artifact])
        return values, coverage

    def _interface_symbol_rows(
        self,
        capture: RepositoryCapture,
        query: InterfaceSymbolQuery,
        *,
        cache: DerivedCache | None,
        budget: OperationBudget | None = None,
    ) -> tuple[list[Any], list[InterfaceOwner] | None, Coverage]:
        local_budget = budget or OperationBudget()
        local_budget.check_deadline()
        if query.sections != ["symbols"]:
            raise _IndexerFailure("invalid_request", "exact symbol interfaces permit only the symbols section")
        ref = query.target
        if ref.root_id != self.root.id:
            raise _IndexerFailure("invalid_reference", "symbol reference is outside the captured root", path=ref.path)
        captured = self._captured_map(capture).get(ref.path)
        if captured is None:
            raise _IndexerFailure("invalid_reference", "symbol reference file was not captured", path=ref.path)
        geometry = _SourceGeometry.from_text(self._captured_text(captured), data=captured.content)
        artifact = self._declarations_for(captured, cache=cache, geometry=geometry, budget=local_budget)
        record = self.resolve_symbol(capture, ref, artifact=artifact, geometry=geometry, budget=local_budget)
        values = [self._declaration_value(record, documentation=query.documentation)]
        owners: list[InterfaceOwner] | None = None
        if record.expandable and query.member_depth == 1:
            values.extend(
                self._declaration_value(item, documentation=query.documentation)
                for item in artifact.declarations
                if item.parent_id == record.symbol_id
            )
        elif not record.expandable:
            owners = self._owner_values(artifact, record)
        values.sort(key=lambda item: (item.ref.start, item.ref.end, item.ref.symbol_id))
        local_budget.check_deadline()
        return values, owners, self._coverage_for_artifacts([artifact])

    @staticmethod
    def _coverage_for_reasons(
        basis: Literal["pattern_matches", "rule_diagnostics", "literal_occurrences", "name_occurrences"],
        reasons: Iterable[CoverageReason],
    ) -> Coverage:
        unique = {(item.code, item.path or "", item.count or 0): item for item in reasons}
        if not unique:
            return Coverage(state="complete", basis=basis)
        ordered = sorted(
            unique.values(),
            key=lambda item: (
                item.code.encode("utf-8"),
                (item.path or "").encode("utf-8"),
                item.count or 0,
            ),
        )
        return Coverage(state="partial", basis=basis, reasons=ordered)

    @staticmethod
    def _source_ref_for(
        root_id: str,
        captured: CapturedFile,
        start: int,
        end: int,
    ) -> SourceRef:
        return SourceRef(
            kind="source",
            root_id=root_id,
            path=captured.path,
            file_digest=captured.digest,
            start=start,
            end=end,
        )

    def _occurrence_ref_for(self, captured: CapturedFile, start: int, end: int) -> OccurrenceRef:
        return OccurrenceRef(
            kind="occurrence",
            root_id=self.root.id,
            path=captured.path,
            file_digest=captured.digest,
            start=start,
            end=end,
            occurrence_id=occurrence_digest(captured.path, captured.digest, start, end),
        )

    @staticmethod
    def _search_row_digest(item: SearchItem) -> str:
        return digest(
            [
                "xray.search.row.v1",
                item.ref.path,
                item.ref.start,
                item.ref.end,
                item.ref.occurrence_id,
                item.rule_id,
                [capture.to_payload() for capture in item.captures or ()],
            ]
        )

    @staticmethod
    def _impact_row_digest(item: ImpactItem) -> str:
        return digest(
            [
                "xray.impact.row.v1",
                item.ref.path,
                item.ref.start,
                item.ref.end,
                item.kind,
                item.evidence,
                item.ref.occurrence_id,
            ]
        )

    @staticmethod
    def _captured_result_path(value: Any, files: Mapping[str, CapturedFile]) -> str:
        if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
            raise _IndexerFailure("internal_error", "ast-grep returned an invalid captured path")
        try:
            path = PurePosixPath(value)
        except Exception as exc:
            raise _IndexerFailure("internal_error", "ast-grep returned an invalid captured path") from exc
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise _IndexerFailure("internal_error", "ast-grep returned a non-contained captured path")
        normalized = path.as_posix()
        if normalized not in files:
            raise _IndexerFailure("internal_error", "ast-grep returned a path outside the captured source set")
        return normalized

    @staticmethod
    def _ast_grep_records(result: Any) -> tuple[list[dict[str, Any]], bool]:
        if isinstance(result, AstGrepResult):
            try:
                return parse_json_array(result.stdout), True
            except Exception as exc:
                raise _IndexerFailure("internal_error", "ast-grep returned malformed JSON") from exc
        if isinstance(result, BoundedAstGrepResult):
            if not result.complete:
                raise _IndexerFailure("execution_limit", "ast-grep did not complete its bounded result")
            if not result.total_exact:
                return [dict(item) for item in result.matches], False
            return [dict(item) for item in result.matches], True
        raise _IndexerFailure("internal_error", "ast-grep returned an unsupported result value")

    @staticmethod
    def _ast_grep_failure(error: AstGrepError) -> _IndexerFailure:
        status = getattr(error, "status", "")
        if status == "validation_failed":
            code = "invalid_pattern"
            action = "correct_input"
        elif status == "not_found":
            code = "dependency_unavailable"
            action = "install_dependency"
        elif status == "timeout":
            code = "timeout"
            action = "narrow_query"
        elif status == "cancelled":
            code = "execution_limit"
            action = "narrow_query"
        elif status in {"stdout_overflow", "stderr_overflow", "huge_line", "temporary_overflow"}:
            code = "execution_limit"
            action = "narrow_query"
        else:
            code = "internal_error"
            action = "report_bug"
        return _IndexerFailure(code, str(error), action=action)

    @staticmethod
    def _record_range(
        record: Mapping[str, Any],
        captured: CapturedFile,
        geometry: _SourceGeometry,
    ) -> tuple[int, int, str]:
        value = record.get("range")
        if not isinstance(value, Mapping):
            raise _IndexerFailure("internal_error", "ast-grep match has no byte range", path=captured.path)
        byte_range = value.get("byteOffset")
        if not isinstance(byte_range, Mapping):
            raise _IndexerFailure("internal_error", "ast-grep match has no byte offsets", path=captured.path)
        start = byte_range.get("start")
        end = byte_range.get("end")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end < start
        ):
            raise _IndexerFailure("internal_error", "ast-grep match has an invalid byte range", path=captured.path)
        XRayIndexer._validate_interval(start, end, geometry, path=captured.path)
        text = record.get("text")
        if not isinstance(text, str) or geometry.decode(start, end) != text:
            raise _IndexerFailure(
                "internal_error",
                "ast-grep match text does not verify against captured bytes",
                path=captured.path,
            )
        return start, end, text

    @staticmethod
    def _range_value(
        value: Any,
        captured: CapturedFile,
        geometry: _SourceGeometry,
    ) -> tuple[int, int, str] | None:
        if not isinstance(value, Mapping):
            return None
        byte_range = value.get("range")
        if not isinstance(byte_range, Mapping):
            return None
        offsets = byte_range.get("byteOffset")
        text = value.get("text")
        if not isinstance(offsets, Mapping) or not isinstance(text, str):
            return None
        start, end = offsets.get("start"), offsets.get("end")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end < start
            or end > len(geometry.data)
            or not geometry.is_boundary(start)
            or not geometry.is_boundary(end)
        ):
            return None
        if geometry.decode(start, end) != text:
            return None
        return start, end, text

    def _capture_values(
        self,
        raw: Mapping[str, Any],
        captured: CapturedFile,
        geometry: _SourceGeometry,
    ) -> tuple[tuple[Capture, ...], bool]:
        values = raw.get("metaVariables")
        if not isinstance(values, Mapping):
            return (), True
        output: list[Capture] = []
        verified = True
        for kind_key, kind in (("single", "single"), ("multi", "multi"), ("transformed", "transformed")):
            entries = values.get(kind_key, {})
            if not isinstance(entries, Mapping):
                verified = False
                continue
            for name in sorted(entries, key=lambda item: str(item).encode("utf-8")):
                if not isinstance(name, str) or not name:
                    verified = False
                    continue
                item = entries[name]
                if kind == "multi":
                    if not isinstance(item, Sequence) or isinstance(item, (str, bytes, bytearray)):
                        verified = False
                        continue
                    refs: list[SourceRef] = []
                    for candidate in item:
                        value = self._range_value(candidate, captured, geometry)
                        if value is None:
                            verified = False
                            continue
                        start, end, _text = value
                        refs.append(self._source_ref_for(self.root.id, captured, start, end))
                    output.append(Capture(name=name, kind="multi", refs=refs))
                    continue
                if kind == "single":
                    value = self._range_value(item, captured, geometry)
                    if value is None:
                        verified = False
                        continue
                    start, end, text = value
                    output.append(
                        Capture(
                            name=name,
                            kind="single",
                            refs=[self._source_ref_for(self.root.id, captured, start, end)],
                            text=text,
                        )
                    )
                    continue
                transformed_text: str | None = None
                if isinstance(item, Mapping):
                    candidate = item.get("text")
                    if isinstance(candidate, str):
                        transformed_text = candidate
                elif isinstance(item, str):
                    transformed_text = item
                if transformed_text is None:
                    verified = False
                    continue
                output.append(Capture(name=name, kind="transformed", text=transformed_text))
        return tuple(output), verified

    @staticmethod
    def _selected_files(
        capture: RepositoryCapture,
        *,
        language: str | None = None,
        budget: OperationBudget | None = None,
    ) -> tuple[list[CapturedFile], list[CoverageReason]]:
        files: list[CapturedFile] = []
        reasons: list[CoverageReason] = []
        for captured in capture.files:
            if budget is not None:
                budget.check_deadline()
            if language is not None and captured.language != language:
                continue
            files.append(captured)
            if not captured.is_text or captured.has_nul:
                reasons.append(CoverageReason(code="non_text_input", path=captured.path))
        return files, reasons

    def _file_cursor_start(
        self,
        cursor_value: str | None,
        *,
        op: Literal["search", "impact"],
        query_digest: str,
        capture: RepositoryCapture,
        eligible: Sequence[CapturedFile],
        snapshot: str,
        budget: OperationBudget | None = None,
    ) -> tuple[int, str | None]:
        if budget is not None:
            budget.check_deadline()
        if cursor_value is None:
            return (0, None)
        cursor = self._validate_cursor_identity(
            cursor_value,
            op=op,
            query_digest=query_digest,
            selection=capture.manifest.selection_digest,
            snapshot=snapshot,
            toolchain=self._toolchain_id(),
        )
        checkpoint = cursor.checkpoint
        if not isinstance(checkpoint, FileCheckpoint):
            raise _IndexerFailure("invalid_cursor", "cursor has the wrong checkpoint kind", action="restart_query")
        if checkpoint.index < 0 or checkpoint.index >= len(capture.files):
            raise _IndexerFailure(
                "invalid_cursor",
                "cursor file index is outside the captured source set",
                action="restart_query",
            )
        current = capture.files[checkpoint.index]
        eligible_indexes = {id(item): index for index, item in enumerate(eligible)}
        if id(current) not in eligible_indexes:
            raise _IndexerFailure(
                "invalid_cursor",
                "cursor points to a file outside the requested profile",
                action="restart_query",
            )
        if budget is not None:
            budget.check_deadline()
        return eligible_indexes[id(current)], checkpoint.after

    @staticmethod
    def _window_files(
        eligible: Sequence[CapturedFile],
        start: int,
        *,
        budget: OperationBudget | None = None,
    ) -> tuple[list[CapturedFile], int | None]:
        if budget is not None:
            budget.check_deadline()
        if start >= len(eligible):
            return [], None
        values: list[CapturedFile] = []
        total_bytes = 0
        index = start
        while index < len(eligible):
            if budget is not None:
                budget.check_deadline()
            captured = eligible[index]
            if len(values) >= _MAX_SEARCH_FILES or (values and total_bytes + captured.size > _MAX_SEARCH_SOURCE_BYTES):
                return values, index
            if captured.size > _MAX_SEARCH_SOURCE_BYTES:
                raise _IndexerFailure(
                    "analysis_limit",
                    "one search unit exceeds the source-byte window",
                    path=captured.path,
                    action="narrow_query",
                )
            values.append(captured)
            total_bytes += captured.size
            index += 1
        return values, None

    @staticmethod
    def _file_indexes(capture: RepositoryCapture) -> dict[str, int]:
        return {item.path: index for index, item in enumerate(capture.files)}

    def _encode_file_cursor(
        self,
        *,
        op: Literal["search", "impact"],
        query_digest: str,
        capture: RepositoryCapture,
        snapshot: str,
        index: int,
        after: str | None,
    ) -> str:
        checkpoint_values: dict[str, Any] = {"kind": "file", "index": index}
        if after is not None:
            checkpoint_values["after"] = after
        return encode_cursor(
            RepositoryCursor(
                version=1,
                op=op,
                root=self.root.id,
                query=query_digest,
                selection=capture.manifest.selection_digest,
                snapshot=snapshot,
                toolchain=self._toolchain_id(),
                checkpoint=FileCheckpoint(**checkpoint_values),
            )
        )

    @staticmethod
    def _clip_text(value: str, maximum: int) -> tuple[str, bool]:
        encoded = value.encode("utf-8")
        if len(encoded) <= maximum:
            return value, False
        clipped = encoded[:maximum].decode("utf-8", errors="ignore")
        return clipped, True

    def _literal_records(
        self,
        files: Sequence[CapturedFile],
        text: str,
        *,
        budget: OperationBudget | None = None,
    ) -> tuple[dict[str, list[SearchItem]], str | None]:
        local_budget = budget or OperationBudget()
        local_budget.check_deadline()
        if not text:
            raise _IndexerFailure("invalid_request", "literal search text must not be empty", action="correct_input")
        needle = text.encode("utf-8")
        result: dict[str, list[SearchItem]] = {item.path: [] for item in files}
        remaining = _MAX_SEARCH_RAW_CANDIDATES
        for captured in files:
            local_budget.check_deadline()
            if not captured.is_text or captured.has_nul:
                continue
            geometry = _SourceGeometry.from_text(self._captured_text(captured), data=captured.content)

            def spans() -> Iterable[tuple[int, int]]:
                offset = 0
                while True:
                    local_budget.check_deadline()
                    start = captured.content.find(needle, offset)
                    if start < 0:
                        return
                    end = start + len(needle)
                    self._validate_interval(start, end, geometry, path=captured.path)
                    yield start, end
                    offset = end

            def make_item(span: tuple[int, int]) -> SearchItem:
                start, end = span
                display_text, clipped = self._clip_text(geometry.decode(start, end), _MAX_OCCURRENCE_TEXT_BYTES)
                values: dict[str, Any] = {
                    "ref": self._occurrence_ref_for(captured, start, end),
                    "location": Range(start=geometry.position(start), end=geometry.position(end)),
                    "text": display_text,
                }
                if clipped:
                    values["disclosure"] = Disclosure(clipped=["text"])
                return SearchItem(**values)

            admitted = collect_complete_file_candidates(
                spans(),
                remaining,
                transform=make_item,
                budget=local_budget,
            )
            result[captured.path] = list(admitted.candidates)
            if admitted.overflowed:
                return result, captured.path
            remaining -= admitted.raw_count
        local_budget.check_deadline()
        return result, None

    def _ast_records_by_file(
        self,
        files: Sequence[CapturedFile],
        source: PatternSearchSource | RuleSearchSource,
        *,
        rule_set: CapturedRuleSet | None,
        detail: Literal["summary", "detail"],
        budget: OperationBudget | None = None,
    ) -> tuple[dict[str, list[SearchItem]], list[CoverageReason], bool, str | None]:
        local_budget = budget or OperationBudget()
        local_budget.check_deadline()
        source_files = {item.path: item for item in files}
        inputs = {
            item.path: item.content for item in files if item.is_text and not item.has_nul and item.language is not None
        }
        reasons: list[CoverageReason] = [
            CoverageReason(code="non_text_input", path=item.path) for item in files if not item.is_text or item.has_nul
        ]
        by_file: dict[str, list[SearchItem]] = {item.path: [] for item in files}
        if not inputs:
            return by_file, reasons, True, None
        if isinstance(source, PatternSearchSource):
            args = [
                "run",
                "--pattern",
                source.pattern,
                "--lang",
                source.language,
                "--json=compact",
                "--color",
                "never",
            ]
        else:
            if rule_set is None:
                raise _IndexerFailure("internal_error", "rule search has no captured rule set")
            args = [
                "scan",
                "--config",
                source.input.path,
                "--json=compact",
                "--color",
                "never",
            ]
        try:
            observation = self._toolchain_observation()
            executable = observation.executable
            if not isinstance(executable, str) or not executable:
                raise _IndexerFailure(
                    "dependency_unavailable",
                    "the observed ast-grep executable is unavailable",
                    action="install_dependency",
                )
            executor = BoundedAstGrepExecutor(executable=executable)
            remaining = _MAX_SEARCH_RAW_CANDIDATES
            with captured_ast_grep_session(inputs, rule_set, budget=local_budget) as session:
                for captured in files:
                    local_budget.check_deadline()
                    if captured.path not in inputs:
                        continue
                    result = session.execute(
                        args,
                        source_paths=(captured.path,),
                        max_results=remaining,
                        timeout=local_budget.remaining_seconds,
                        cancel=local_budget.cancel,
                        executor=executor,
                    )
                    records, exact = self._ast_grep_records(result)
                    raw_count = result.raw_count if isinstance(result, BoundedAstGrepResult) else len(records)
                    if not exact:
                        return by_file, reasons, False, captured.path
                    if raw_count > remaining:
                        raise _IndexerFailure(
                            "internal_error",
                            "ast-grep exceeded its admitted raw candidate budget",
                            path=captured.path,
                        )
                    remaining -= raw_count
                    single_file = {captured.path: captured}
                    geometries: dict[str, _SourceGeometry] = {}
                    for raw in records:
                        local_budget.check_deadline()
                        if not isinstance(raw, Mapping):
                            raise _IndexerFailure("internal_error", "ast-grep returned a non-object match")
                        path = self._captured_result_path(raw.get("file"), single_file)
                        current = source_files[path]
                        geometry = geometries.get(path)
                        if geometry is None:
                            geometry = _SourceGeometry.from_text(self._captured_text(current), data=current.content)
                            geometries[path] = geometry
                        start, end, match_text = self._record_range(raw, current, geometry)
                        display_text, text_clipped = self._clip_text(match_text, _MAX_OCCURRENCE_TEXT_BYTES)
                        captures: tuple[Capture, ...] = ()
                        if detail == "detail":
                            captures, verified = self._capture_values(raw, current, geometry)
                            if not verified:
                                reasons.append(CoverageReason(code="capture_unverified", path=path))
                        rule_id: str | None = None
                        if isinstance(source, RuleSearchSource):
                            raw_rule = raw.get("ruleId")
                            if not isinstance(raw_rule, str) or not raw_rule:
                                raise _IndexerFailure("internal_error", "rule match has no ruleId", path=path)
                            rule_id = raw_rule
                        item_values: dict[str, Any] = {
                            "ref": self._occurrence_ref_for(current, start, end),
                            "location": Range(start=geometry.position(start), end=geometry.position(end)),
                            "text": display_text,
                        }
                        if text_clipped:
                            item_values["disclosure"] = Disclosure(clipped=["text"])
                        if rule_id is not None:
                            item_values["rule_id"] = rule_id
                        if detail == "detail":
                            item_values["captures"] = list(captures)
                        by_file[path].append(SearchItem(**item_values))
                    by_file[captured.path].sort(
                        key=lambda item: (
                            item.ref.start,
                            item.ref.end,
                            (item.rule_id or "").encode("utf-8"),
                            self._search_row_digest(item),
                        )
                    )
        except AstGrepError as exc:
            raise self._ast_grep_failure(exc) from exc
        local_budget.check_deadline()
        return by_file, reasons, True, None

    @staticmethod
    def _limit_search_captures(item: SearchItem) -> SearchItem:
        if not item.captures:
            return item
        clipped = len(item.captures) > _MAX_CAPTURE_RECORDS
        captures = list(item.captures[:_MAX_CAPTURE_RECORDS])
        clipped_text = False
        normalized: list[Capture] = []
        for capture in captures:
            if capture.text is None:
                normalized.append(capture)
                continue
            text, was_clipped = XRayIndexer._clip_text(capture.text, _MAX_TRANSFORMED_TEXT_BYTES)
            clipped_text = clipped_text or was_clipped
            normalized.append(capture.model_copy(update={"text": text}))
        clipped_fields = set(item.disclosure.clipped) if item.disclosure is not None else set()
        if clipped or clipped_text:
            clipped_fields.add("captures")
        disclosure = (
            Disclosure(clipped=sorted(clipped_fields, key=("signature", "documentation", "text", "captures").index))
            if clipped_fields
            else None
        )
        return item.model_copy(update={"captures": normalized, "disclosure": disclosure})

    def _search_window_rows(
        self,
        capture: RepositoryCapture,
        query: Any,
        *,
        source: Any = None,
        rule_set: CapturedRuleSet | None = None,
        start: int,
        after: str | None,
        cache: DerivedCache | None = None,
        budget: OperationBudget | None = None,
    ) -> tuple[list[SearchItem], list[CoverageReason], int | None]:
        local_budget = budget or OperationBudget()
        local_budget.check_deadline()
        if source is None:
            source = query.source
        language = source.language if isinstance(source, PatternSearchSource) else None
        eligible, reasons = self._selected_files(capture, language=language, budget=local_budget)
        window, pending_position = self._window_files(eligible, start, budget=local_budget)
        if isinstance(source, LiteralSearchSource):
            by_file, ast_overflow_path = self._literal_records(window, source.text, budget=local_budget)
            exact = True
        else:
            by_file, ast_reasons, exact, ast_overflow_path = self._ast_records_by_file(
                window,
                source,
                rule_set=rule_set,
                detail=query.detail,
                budget=local_budget,
            )
            reasons.extend(ast_reasons)
            if not exact and ast_overflow_path is None and window:
                raise _IndexerFailure("internal_error", "ast-grep overflow has no owning file")
            if isinstance(source, PatternSearchSource):
                for captured in window:
                    if ast_overflow_path == captured.path:
                        break
                    local_budget.check_deadline()
                    if not captured.is_text or captured.has_nul:
                        continue
                    geometry = _SourceGeometry.from_text(self._captured_text(captured), data=captured.content)
                    artifact = self._declarations_for(
                        captured,
                        cache=cache,
                        geometry=geometry,
                        budget=local_budget,
                    )
                    if artifact.coverage.state == "partial":
                        reasons.extend(artifact.coverage.reasons or ())
        overflow_position: int | None = None
        complete_end = len(window)
        if ast_overflow_path is not None:
            try:
                overflow_offset = next(index for index, item in enumerate(window) if item.path == ast_overflow_path)
            except StopIteration as exc:
                raise _IndexerFailure(
                    "internal_error",
                    "search overflow path is outside the captured window",
                    path=ast_overflow_path,
                ) from exc
            overflow_position = start + overflow_offset
            if overflow_position == start:
                raise _IndexerFailure(
                    "analysis_limit",
                    "search result unit exceeds the raw candidate window",
                    path=ast_overflow_path,
                    action="narrow_query",
                )
            complete_end = overflow_offset
        display_by_file: dict[str, list[SearchItem]] = {}
        for captured in window[:complete_end]:
            local_budget.check_deadline()
            file_rows = by_file.get(captured.path, [])
            if query.detail == "detail":
                file_rows = [self._limit_search_captures(item) for item in file_rows]
            display_by_file[captured.path] = file_rows
        after_offset: int | None = None
        if after is not None:
            if not window or complete_end == 0:
                raise _IndexerFailure(
                    "invalid_cursor",
                    "cursor checkpoint does not identify a search result row",
                    action="restart_query",
                )
            first_rows = display_by_file.get(window[0].path, [])
            row_ids = [self._search_row_digest(item) for item in first_rows]
            try:
                after_offset = row_ids.index(after)
            except ValueError as exc:
                raise _IndexerFailure(
                    "invalid_cursor",
                    "cursor checkpoint does not identify a search result row",
                    action="restart_query",
                ) from exc
        file_indexes = self._file_indexes(capture)
        rows: list[SearchItem] = []
        for position, captured in enumerate(window[:complete_end]):
            local_budget.check_deadline()
            admitted = display_by_file.get(captured.path, [])
            if position == 0 and after_offset is not None:
                admitted = admitted[after_offset + 1 :]
            rows.extend(admitted)
        if overflow_position is not None:
            pending_position = overflow_position
            reasons.append(CoverageReason(code="scan_pending", path=eligible[overflow_position].path))
        elif pending_position is not None:
            reasons.append(CoverageReason(code="scan_pending", path=eligible[pending_position].path))
        if pending_position is None and overflow_position is None:
            pending_cursor = None
        else:
            pending_index = overflow_position if overflow_position is not None else pending_position
            pending_cursor = file_indexes[eligible[pending_index].path] if pending_index is not None else None
        local_budget.check_deadline()
        return rows, reasons, pending_cursor

    def _execute_search(
        self,
        arguments: SearchArguments,
        *,
        budget: OperationBudget | None = None,
        cache: DerivedCache | None = None,
    ) -> Success:
        local_budget = budget or OperationBudget()
        local_budget.check_deadline()
        query = arguments.query
        source = query.source
        capture_domain = REGULAR_TEXT_DOMAIN if isinstance(source, LiteralSearchSource) else SUPPORTED_SOURCE_DOMAIN
        capture = self._capture_sources(
            query.selection,
            capture_domain=capture_domain,
            budget=local_budget,
        )
        rule_set: CapturedRuleSet | None = None
        snapshot = capture.manifest.snapshot_digest
        if isinstance(source, RuleSearchSource):
            try:
                rule_set = RepositoryProvider(self.root).capture_rule_input(source.input, budget=local_budget)
            except RepositoryError:
                raise
            snapshot = digest(["xray.search.rule-snapshot.v1", snapshot, rule_set.digest])
        provenance = self._repository_provenance(
            op="search",
            query=query,
            capture=capture,
            snapshot=snapshot,
        )
        page = arguments.page or PageSearch()
        source_language = source.language if isinstance(source, PatternSearchSource) else None
        eligible, _profile_reasons = self._selected_files(
            capture,
            language=source_language,
            budget=local_budget,
        )
        start, after = self._file_cursor_start(
            page.cursor,
            op="search",
            query_digest=provenance.query,
            capture=capture,
            eligible=eligible,
            snapshot=snapshot,
            budget=local_budget,
        )
        rows, reasons, pending_index = self._search_window_rows(
            capture,
            query,
            source=source,
            rule_set=rule_set,
            start=start,
            after=after,
            cache=cache,
            budget=local_budget,
        )
        file_indexes = self._file_indexes(capture)
        coverage = self._coverage_for_reasons(
            "pattern_matches"
            if isinstance(source, PatternSearchSource)
            else "rule_diagnostics"
            if isinstance(source, RuleSearchSource)
            else "literal_occurrences",
            reasons,
        )
        if not rows:
            next_cursor = (
                self._encode_file_cursor(
                    op="search",
                    query_digest=provenance.query,
                    capture=capture,
                    snapshot=snapshot,
                    index=pending_index,
                    after=None,
                )
                if pending_index is not None
                else None
            )
            page_values: dict[str, Any] = {}
            if next_cursor is not None:
                page_values["next_cursor"] = next_cursor
            result = Success(
                schema="xray.v1",
                ok=True,
                op="search",
                root=capture.root,
                scope=capture.selection,
                provenance=provenance,
                data=SearchData(items=[]),
                page=PageResult(**page_values),
                coverage=coverage,
            )
            local_budget.check_deadline()
            if len(canonical_bytes(result)) > page.max_bytes:
                raise _IndexerFailure(
                    "budget_too_small",
                    "search result cannot fit the requested byte budget",
                    action="narrow_query",
                )
            return result
        count = min(page.limit, len(rows))
        while count > 0:
            local_budget.check_deadline()
            selected = rows[:count]
            last = selected[-1]
            remaining = rows[count:]
            if remaining:
                next_cursor = self._encode_file_cursor(
                    op="search",
                    query_digest=provenance.query,
                    capture=capture,
                    snapshot=snapshot,
                    index=file_indexes[last.ref.path],
                    after=self._search_row_digest(last),
                )
            elif pending_index is not None:
                next_cursor = self._encode_file_cursor(
                    op="search",
                    query_digest=provenance.query,
                    capture=capture,
                    snapshot=snapshot,
                    index=pending_index,
                    after=None,
                )
            else:
                next_cursor = None
            page_values = {}
            if next_cursor is not None:
                page_values["next_cursor"] = next_cursor
            result = Success(
                schema="xray.v1",
                ok=True,
                op="search",
                root=capture.root,
                scope=capture.selection,
                provenance=provenance,
                data=SearchData(items=selected),
                page=PageResult(**page_values),
                coverage=coverage,
            )
            if len(canonical_bytes(result)) <= page.max_bytes:
                return result
            count -= 1
        raise _IndexerFailure(
            "budget_too_small",
            "one search result cannot fit the requested byte budget",
            action="narrow_query",
        )

    @staticmethod
    def _identifier_char(value: str, language: str | None) -> bool:
        if not value:
            return False
        if value == "$":
            return language in {"javascript", "typescript"}
        if value == "_":
            return True
        if value.isalnum():
            return True
        category = unicodedata.category(value)
        return category in {"Lm", "Mc", "Mn", "Nl"}

    @classmethod
    def _identifier_spans(
        cls,
        text: str,
        name: str,
        language: str | None,
        *,
        budget: OperationBudget | None = None,
    ) -> Iterable[tuple[int, int]]:
        if not name:
            return
        offset = 0
        while True:
            if budget is not None:
                budget.check_deadline()
            start = text.find(name, offset)
            if start < 0:
                return
            end = start + len(name)
            before = text[start - 1] if start else ""
            after = text[end] if end < len(text) else ""
            if not cls._identifier_char(before, language) and not cls._identifier_char(after, language):
                if budget is not None:
                    budget.check_deadline()
                yield start, end
            offset = end

    @staticmethod
    def _python_token_name_span(
        text: str,
        geometry: _SourceGeometry,
        node: ast.AST,
        name: str,
    ) -> tuple[int, int] | None:
        import io
        import tokenize

        node_start, node_end = XRayIndexer._python_node_bytes(node, geometry)
        snippet = geometry.decode(node_start, node_end)
        line_starts = [0]
        for index, value in enumerate(snippet):
            if value == "\n":
                line_starts.append(index + 1)
        try:
            tokens = tokenize.generate_tokens(io.StringIO(snippet).readline)
            match: tuple[int, int] | None = None
            base_char = geometry.byte_index_to_char(node_start)
            for token in tokens:
                if token.type != tokenize.NAME or token.string != name:
                    continue
                line, column = token.start
                end_line, end_column = token.end
                if line < 1 or end_line < line or line > len(line_starts) or end_line > len(line_starts):
                    continue
                start_char = base_char + line_starts[line - 1] + column
                end_char = base_char + line_starts[end_line - 1] + end_column
                match = (
                    geometry.char_index_to_byte(start_char),
                    geometry.char_index_to_byte(end_char),
                )
            return match
        except (tokenize.TokenError, IndentationError, SyntaxError):
            return None

    @staticmethod
    def _python_context(
        text: str,
        geometry: _SourceGeometry,
        name: str,
    ) -> tuple[set[tuple[int, int]], list[tuple[int, int]], list[tuple[int, int]], bool]:
        import io
        import tokenize

        call_spans: set[tuple[int, int]] = set()
        comment_spans: list[tuple[int, int]] = []
        string_spans: list[tuple[int, int]] = []
        parsed = True
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
            parsed = False
        if tree is not None:
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                candidate: tuple[int, int] | None = None
                if isinstance(function, ast.Name) and function.id == name:
                    candidate = XRayIndexer._python_node_bytes(function, geometry)
                elif isinstance(function, ast.Attribute) and function.attr == name:
                    candidate = XRayIndexer._python_token_name_span(text, geometry, function, name)
                if candidate is not None:
                    call_spans.add(candidate)
        try:
            tokens = tokenize.generate_tokens(io.StringIO(text).readline)
            for token in tokens:
                if token.type not in {tokenize.COMMENT, tokenize.STRING}:
                    continue
                start_line, start_column = token.start
                end_line, end_column = token.end
                if start_line < 1 or end_line < start_line or end_line > geometry.line_count:
                    continue
                line_start_char = geometry.byte_index_to_char(geometry.line_starts[start_line - 1])
                end_line_start_char = geometry.byte_index_to_char(geometry.line_starts[end_line - 1])
                start_char = line_start_char + start_column
                end_char = end_line_start_char + end_column
                if start_char < 0 or end_char < start_char or end_char > len(text):
                    continue
                if token.type == tokenize.COMMENT:
                    comment_spans.append(
                        (geometry.char_index_to_byte(start_char), geometry.char_index_to_byte(end_char))
                    )
                else:
                    string_spans.append(
                        (geometry.char_index_to_byte(start_char), geometry.char_index_to_byte(end_char))
                    )
        except (tokenize.TokenError, IndentationError, SyntaxError):
            parsed = False
        return call_spans, comment_spans, string_spans, parsed

    def _tree_context(
        self,
        text: str,
        geometry: _SourceGeometry,
        language: str,
        name: str,
    ) -> tuple[set[tuple[int, int]], list[tuple[int, int]], list[tuple[int, int]], bool]:
        call_spans: set[tuple[int, int]] = set()
        comment_spans: list[tuple[int, int]] = []
        string_spans: list[tuple[int, int]] = []
        try:
            root = SgRoot(text, language).root()
            nodes = list(root.find_all(pattern="$A"))
        except Exception:
            return call_spans, comment_spans, string_spans, False
        parse_ok = not any(self._node_kind(node) == "ERROR" for node in nodes)
        identifier_kinds = {
            "identifier",
            "field_identifier",
            "property_identifier",
            "type_identifier",
            "shorthand_property_identifier_pattern",
            "namespace_identifier",
        }
        call_kinds = {"call_expression", "call", "invocation_expression", "function_call_expression"}
        for node in nodes:
            try:
                start, end = self._node_range(node, geometry)
            except _IndexerFailure:
                continue
            kind = self._node_kind(node)
            if kind in {"comment", "line_comment", "block_comment"}:
                comment_spans.append((start, end))
            if kind in {"string", "string_fragment", "template_string", "interpreted_string_literal_content"}:
                string_spans.append((start, end))
            if self._node_text(node) != name or kind not in identifier_kinds:
                continue
            parent = self._node_parent(node)
            while parent is not None:
                parent_kind = self._node_kind(parent)
                if parent_kind in call_kinds:
                    function = self._node_field(parent, "function")
                    if function is not None:
                        try:
                            function_start, function_end = self._node_range(function, geometry)
                        except _IndexerFailure:
                            break
                        if function_start <= start and end <= function_end:
                            call_spans.add((start, end))
                    break
                parent = self._node_parent(parent)
        return call_spans, comment_spans, string_spans, parse_ok

    def _impact_import(
        self,
        captured: CapturedFile,
        geometry: _SourceGeometry,
        span: tuple[int, int],
        *,
        observations: Sequence[_SyntaxObservation] | None = None,
    ) -> ImpactImport | None:
        for observation in observations if observations is not None else self._observations(captured, geometry):
            if observation.section != "imports" or not (observation.start <= span[0] and span[1] <= observation.end):
                continue
            values: dict[str, Any] = {"module_text": observation.module_text or ""}
            if observation.imported_name is not None:
                values["imported_name"] = observation.imported_name
            if observation.local_name is not None:
                values["local_name"] = observation.local_name
            return ImpactImport(**values)
        return None

    def _impact_file_rows(
        self,
        captured: CapturedFile,
        name: str,
        *,
        target: DeclarationRecord,
        mode: Literal["syntax", "lexical"],
        cache: DerivedCache | None,
        remaining: int,
        budget: OperationBudget | None = None,
    ) -> tuple[list[ImpactItem], list[CoverageReason], int, bool]:
        local_budget = budget or OperationBudget()
        local_budget.check_deadline()
        if not captured.is_text or captured.has_nul:
            return [], [CoverageReason(code="non_text_input", path=captured.path)], 0, False
        text = self._captured_text(captured)
        admitted = collect_complete_file_candidates(
            self._identifier_spans(text, name, captured.language, budget=local_budget),
            remaining,
            budget=local_budget,
        )
        if admitted.overflowed:
            return [], [], admitted.raw_count, True
        geometry = _SourceGeometry.from_text(text, data=captured.content)
        artifact: DeclarationArtifact | None = None
        observations: list[_SyntaxObservation] = []
        reasons: list[CoverageReason] = []
        call_spans: set[tuple[int, int]] = set()
        comment_spans: list[tuple[int, int]] = []
        string_spans: list[tuple[int, int]] = []
        parser_ok = False
        if mode == "syntax":
            if captured.language == "python":
                call_spans, comment_spans, string_spans, parser_ok = self._python_context(text, geometry, name)
            elif captured.language in {"javascript", "typescript", "go"}:
                call_spans, comment_spans, string_spans, parser_ok = self._tree_context(
                    text,
                    geometry,
                    captured.language,
                    name,
                )
            else:
                reasons.append(CoverageReason(code="unsupported_syntax", path=captured.path))
            if captured.language in {"python", "javascript", "typescript", "go"}:
                observations = self._observations(captured, geometry)
                artifact = self._declarations_for(captured, cache=cache, geometry=geometry, budget=local_budget)
                if artifact.coverage.state == "partial":
                    reasons.extend(artifact.coverage.reasons or ())
                parser_ok = parser_ok and artifact.coverage.state == "complete"
                if not parser_ok and not artifact.coverage.reasons:
                    reasons.append(CoverageReason(code="unsupported_syntax", path=captured.path))
        rows: list[ImpactItem] = []
        definition_spans: set[tuple[int, int]] = set()
        if artifact is not None:
            definition_spans = {
                (item.defining_start, item.defining_end) for item in artifact.declarations if item.name == name
            }
        target_span = (target.defining_start, target.defining_end)
        for start_char, end_char in admitted.candidates:
            local_budget.check_deadline()
            start = geometry.char_index_to_byte(start_char)
            end = geometry.char_index_to_byte(end_char)
            span = (start, end)
            if span == target_span and captured.path == target.path:
                continue
            if mode == "lexical":
                kind: Literal["definition", "import", "call", "read", "comment", "string", "text", "unknown"] = "text"
                evidence: Literal["ast_syntax", "lexical"] = "lexical"
                enclosing = None
                import_value = None
            else:
                import_value = self._impact_import(captured, geometry, span, observations=observations)
                if span in definition_spans:
                    kind = "definition"
                elif import_value is not None:
                    kind = "import"
                elif self._contained_span(span, comment_spans):
                    kind = "comment"
                elif self._contained_span(span, string_spans):
                    kind = "string"
                elif span in call_spans:
                    kind = "call"
                elif parser_ok:
                    kind = "read"
                else:
                    kind = "unknown"
                evidence = "ast_syntax" if parser_ok else "lexical"
                enclosing = None
                if artifact is not None:
                    declaration = artifact.enclosing(start, end)
                    if declaration is not None:
                        enclosing = EnclosingFound(state="found", ref=declaration.ref)
                    elif artifact.coverage.state == "partial":
                        enclosing = EnclosingUnavailable(state="unavailable", reason="parse_diagnostics")
                    else:
                        enclosing = EnclosingNone(state="none")
            display_text, clipped = self._clip_text(geometry.decode(start, end), _MAX_OCCURRENCE_TEXT_BYTES)
            disclosure = Disclosure(clipped=["text"]) if clipped else None
            values: dict[str, Any] = {
                "ref": self._occurrence_ref_for(captured, start, end),
                "location": Range(start=geometry.position(start), end=geometry.position(end)),
                "kind": kind,
                "evidence": evidence,
                "text": display_text,
            }
            if enclosing is not None:
                values["enclosing"] = enclosing
            if import_value is not None:
                values["import_"] = import_value
            if disclosure is not None:
                values["disclosure"] = disclosure
            rows.append(ImpactItem(**values))
        rows.sort(
            key=lambda item: (
                item.ref.start,
                item.ref.end,
                _IMPACT_KIND_ORDER[item.kind],
                self._impact_row_digest(item),
            )
        )
        local_budget.check_deadline()
        return rows, reasons, admitted.raw_count, False

    def _execute_impact(
        self,
        arguments: ImpactArguments,
        *,
        budget: OperationBudget | None = None,
        cache: DerivedCache | None = None,
    ) -> Success:
        local_budget = budget or OperationBudget()
        local_budget.check_deadline()
        query = arguments.query
        capture_domain = REGULAR_TEXT_DOMAIN if query.mode == "lexical" else SUPPORTED_SOURCE_DOMAIN
        capture = self._capture_sources(
            query.selection,
            capture_domain=capture_domain,
            budget=local_budget,
        )
        provenance = self._repository_provenance(op="impact", query=query, capture=capture)
        page = arguments.page or PageImpact()
        target_file = self._captured_map(capture).get(query.target.path)
        if target_file is None:
            raise _IndexerFailure("invalid_reference", "impact target file was not captured", path=query.target.path)
        target_geometry = _SourceGeometry.from_text(
            self._captured_text(target_file),
            data=target_file.content,
        )
        artifact = self._declarations_for(
            target_file,
            cache=cache,
            geometry=target_geometry,
            budget=local_budget,
        )
        target = self.resolve_symbol(
            capture,
            query.target,
            artifact=artifact,
            geometry=target_geometry,
            budget=local_budget,
        )
        eligible, initial_reasons = self._selected_files(capture, budget=local_budget)
        start, after = self._file_cursor_start(
            page.cursor,
            op="impact",
            query_digest=provenance.query,
            capture=capture,
            eligible=eligible,
            snapshot=provenance.snapshot,
            budget=local_budget,
        )
        window, pending_position = self._window_files(eligible, start, budget=local_budget)
        reasons = list(initial_reasons)
        rows: list[ImpactItem] = []
        remaining = _MAX_SEARCH_RAW_CANDIDATES
        after_offset: int | None = None
        overflow_position: int | None = None
        for position, captured in enumerate(window):
            local_budget.check_deadline()
            rows_for_file, file_reasons, raw_count, overflowed = self._impact_file_rows(
                captured,
                target.name,
                target=target,
                mode=query.mode,
                cache=cache,
                remaining=remaining,
                budget=local_budget,
            )
            reasons.extend(file_reasons)
            if overflowed:
                overflow_position = start + position
                if overflow_position == start:
                    raise _IndexerFailure(
                        "analysis_limit",
                        "impact result unit exceeds the raw candidate window",
                        path=captured.path,
                        action="narrow_query",
                    )
                break
            remaining -= raw_count
            if position == 0 and after is not None:
                row_ids = [self._impact_row_digest(item) for item in rows_for_file]
                try:
                    after_offset = row_ids.index(after)
                except ValueError as exc:
                    raise _IndexerFailure(
                        "invalid_cursor",
                        "cursor checkpoint does not identify an impact result row",
                        action="restart_query",
                    ) from exc
                rows_for_file = rows_for_file[after_offset + 1 :]
            rows.extend(rows_for_file)
        if after is not None and not window:
            raise _IndexerFailure(
                "invalid_cursor",
                "cursor checkpoint does not identify an impact result row",
                action="restart_query",
            )
        if overflow_position is not None:
            pending_position = overflow_position
            reasons.append(CoverageReason(code="scan_pending", path=eligible[overflow_position].path))
        elif pending_position is not None:
            reasons.append(CoverageReason(code="scan_pending", path=eligible[pending_position].path))
        file_indexes = self._file_indexes(capture)
        pending_position_value = overflow_position if overflow_position is not None else pending_position
        pending_index = (
            file_indexes[eligible[pending_position_value].path] if pending_position_value is not None else None
        )
        coverage = self._coverage_for_reasons("name_occurrences", reasons)
        if not rows:
            next_cursor = (
                self._encode_file_cursor(
                    op="impact",
                    query_digest=provenance.query,
                    capture=capture,
                    snapshot=provenance.snapshot,
                    index=pending_index,
                    after=None,
                )
                if pending_index is not None
                else None
            )
            page_values: dict[str, Any] = {}
            if next_cursor is not None:
                page_values["next_cursor"] = next_cursor
            result = Success(
                schema="xray.v1",
                ok=True,
                op="impact",
                root=capture.root,
                scope=capture.selection,
                provenance=provenance,
                data=ImpactData(target=query.target, basis="name_occurrences", resolution="unresolved", items=[]),
                page=PageResult(**page_values),
                coverage=coverage,
            )
            if len(canonical_bytes(result)) > page.max_bytes:
                raise _IndexerFailure("budget_too_small", "impact result cannot fit the requested byte budget")
            return result
        count = min(page.limit, len(rows))
        while count > 0:
            local_budget.check_deadline()
            selected = rows[:count]
            last = selected[-1]
            if count < len(rows):
                next_cursor = self._encode_file_cursor(
                    op="impact",
                    query_digest=provenance.query,
                    capture=capture,
                    snapshot=provenance.snapshot,
                    index=file_indexes[last.ref.path],
                    after=self._impact_row_digest(last),
                )
            elif pending_index is not None:
                next_cursor = self._encode_file_cursor(
                    op="impact",
                    query_digest=provenance.query,
                    capture=capture,
                    snapshot=provenance.snapshot,
                    index=pending_index,
                    after=None,
                )
            else:
                next_cursor = None
            page_values: dict[str, Any] = {}
            if next_cursor is not None:
                page_values["next_cursor"] = next_cursor
            result = Success(
                schema="xray.v1",
                ok=True,
                op="impact",
                root=capture.root,
                scope=capture.selection,
                provenance=provenance,
                data=ImpactData(target=query.target, basis="name_occurrences", resolution="unresolved", items=selected),
                page=PageResult(**page_values),
                coverage=coverage,
            )
            if len(canonical_bytes(result)) <= page.max_bytes:
                return result
            count -= 1
        raise _IndexerFailure("budget_too_small", "one impact result cannot fit the requested byte budget")

    @staticmethod
    def _captured_map(capture: RepositoryCapture) -> dict[str, CapturedFile]:
        return {item.path: item for item in capture.files}

    @staticmethod
    def _validate_digest(ref_digest: str, captured: CapturedFile, path: str) -> None:
        if ref_digest != captured.digest:
            raise _IndexerFailure(
                "stale_reference",
                "reference file digest does not match the captured source",
                path=path,
                action="refresh_reference",
            )

    @staticmethod
    def _validate_interval(start: int, end: int, geometry: _SourceGeometry, *, path: str) -> None:
        if start < 0 or end < start or end > len(geometry.data):
            raise _IndexerFailure("invalid_reference", "reference byte range is outside the captured file", path=path)
        if not geometry.is_boundary(start) or not geometry.is_boundary(end):
            raise _IndexerFailure(
                "invalid_reference",
                "reference byte range is not aligned to UTF-8 boundaries",
                path=path,
                action="correct_input",
            )

    def resolve_symbol(
        self,
        capture: RepositoryCapture,
        ref: SymbolSourceRef,
        *,
        artifact: DeclarationArtifact | None = None,
        geometry: _SourceGeometry | None = None,
        budget: OperationBudget | None = None,
    ) -> DeclarationRecord:
        local_budget = budget or OperationBudget()
        local_budget.check_deadline()
        if ref.root_id != capture.root.id or ref.path not in {item.path for item in capture.files}:
            raise _IndexerFailure("invalid_reference", "symbol reference is outside the captured root", path=ref.path)
        captured = self._captured_map(capture).get(ref.path)
        if captured is None:
            raise _IndexerFailure("invalid_reference", "symbol reference file was not captured", path=ref.path)
        self._validate_digest(ref.file_digest, captured, ref.path)
        geometry = geometry or _SourceGeometry.from_text(self._captured_text(captured), data=captured.content)
        self._validate_interval(ref.start, ref.end, geometry, path=ref.path)
        item = artifact or self.declarations_for(captured, geometry=geometry, budget=local_budget)
        if item.root_id != capture.root.id or item.file_digest != captured.digest:
            raise _IndexerFailure(
                "stale_reference", "declaration artifact is not bound to the captured source", path=ref.path
            )
        try:
            resolved = item.resolve(ref)
        except _IndexerFailure:
            raise
        except Exception as exc:
            raise _IndexerFailure("stale_reference", "symbol reference does not resolve", path=ref.path) from exc
        local_budget.check_deadline()
        return resolved

    def _normalize_location(
        self,
        target: LocationTarget,
        geometry: _SourceGeometry,
    ) -> tuple[int, int]:
        start = geometry.line_start(target.line)
        if target.column is not None:
            column_offset = target.column - 1
            line_content_end = geometry.line_content_end(target.line)
            if column_offset > line_content_end - start:
                raise _IndexerFailure(
                    "invalid_reference", "location column is outside the selected line", path=target.path
                )
            start += column_offset
            if not geometry.is_boundary(start):
                raise _IndexerFailure("invalid_reference", "location column is not a UTF-8 boundary", path=target.path)
        if target.end_line is None:
            end = len(geometry.data)
        else:
            end = geometry.line_end(target.end_line)
        self._validate_interval(start, end, geometry, path=target.path)
        return start, end

    def _normalize_targets(
        self,
        capture: RepositoryCapture,
        targets: Sequence[ReadTarget],
        *,
        cache: DerivedCache | None = None,
        budget: OperationBudget | None = None,
        include_enclosing: bool = True,
    ) -> tuple[list[_TargetState], dict[str, DeclarationArtifact]]:
        local_budget = budget or OperationBudget()
        files = self._captured_map(capture)
        if len(files) != len(capture.files):
            raise _IndexerFailure("internal_error", "captured source paths are not unique")
        artifacts: dict[str, DeclarationArtifact] = {}
        geometries: dict[str, _SourceGeometry] = {}
        states: list[_TargetState] = []
        for index, target in enumerate(targets):
            local_budget.check_deadline()
            captured = files.get(target.path)
            if captured is None:
                raise _IndexerFailure("invalid_reference", "target file was not captured", path=target.path)
            if isinstance(target, (SourceRef, SymbolSourceRef, OccurrenceRef)):
                self._validate_digest(target.file_digest, captured, target.path)
                if isinstance(target, OccurrenceRef):
                    expected = occurrence_digest(target.path, target.file_digest, target.start, target.end)
                    if target.occurrence_id != expected:
                        raise _IndexerFailure(
                            "invalid_reference",
                            "occurrence identity does not match its path, digest, and range",
                            path=target.path,
                            action="refresh_reference",
                        )
            geometry = geometries.get(target.path)
            if geometry is None:
                geometry = _SourceGeometry.from_text(self._captured_text(captured), data=captured.content)
                geometries[target.path] = geometry
            artifact = artifacts.get(target.path)
            needs_artifact = include_enclosing or isinstance(target, SymbolSourceRef)
            if (
                needs_artifact
                and artifact is None
                and captured.language
                in (
                    "python",
                    "javascript",
                    "typescript",
                    "go",
                )
            ):
                artifact = self._declarations_for(captured, cache=cache, geometry=geometry, budget=local_budget)
                artifacts[target.path] = artifact
            if isinstance(target, LocationTarget):
                start, end = self._normalize_location(target, geometry)
                declaration = None
            elif isinstance(target, (SourceRef, SymbolSourceRef)):
                self._validate_interval(target.start, target.end, geometry, path=target.path)
                start, end = target.start, target.end
                declaration = None
                if isinstance(target, SymbolSourceRef):
                    if artifact is None:
                        artifact = self._declarations_for(
                            captured,
                            cache=cache,
                            geometry=geometry,
                            budget=local_budget,
                        )
                        artifacts[target.path] = artifact
                    declaration = self.resolve_symbol(
                        capture,
                        target,
                        artifact=artifact,
                        geometry=geometry,
                        budget=local_budget,
                    )
            elif isinstance(target, OccurrenceRef):
                self._validate_interval(target.start, target.end, geometry, path=target.path)
                start, end = target.start, target.end
                declaration = None
            else:
                raise _IndexerFailure("invalid_reference", "unsupported read target")
            states.append(
                _TargetState(
                    index=index,
                    target=target,
                    captured=captured,
                    geometry=geometry,
                    start=start,
                    end=end,
                    artifact=artifact,
                    declaration=declaration,
                )
            )
        local_budget.check_deadline()
        return states, artifacts

    @staticmethod
    def _enclosing_for(state: _TargetState, include_enclosing: bool) -> Enclosing | None:
        if not include_enclosing:
            return None
        if isinstance(state.target, SymbolSourceRef):
            if state.declaration is None:
                return EnclosingUnavailable(state="unavailable", reason="parse_diagnostics")
            return EnclosingFound(state="found", ref=state.declaration.ref)
        artifact = state.artifact
        if artifact is None:
            return EnclosingUnsupported(state="unsupported")
        enclosing_end = state.end
        if isinstance(state.target, LocationTarget) and state.target.end_line is not None:
            enclosing_end = state.geometry.line_content_end(state.target.end_line)
        declaration = artifact.enclosing(state.start, enclosing_end)
        if declaration is not None:
            return EnclosingFound(state="found", ref=declaration.ref)
        if artifact.coverage.state == "partial":
            return EnclosingUnavailable(state="unavailable", reason="parse_diagnostics")
        return EnclosingNone(state="none")

    @staticmethod
    def _context_interval(state: _TargetState, context_lines: int) -> tuple[int, int]:
        if context_lines < 0 or context_lines > _MAX_CONTEXT_LINES:
            raise _IndexerFailure("invalid_request", "context_lines must be between 0 and 10")
        if context_lines == 0:
            return state.start, state.end
        geometry = state.geometry
        start_line = geometry.line_index(state.start)
        end_line = geometry.line_index(state.end, end=True)
        expanded_start = geometry.line_starts[max(0, start_line - context_lines)]
        expanded_end = geometry.line_ends[min(geometry.line_count - 1, end_line + context_lines)]
        return expanded_start, expanded_end

    def _merge_segments(
        self,
        states: Sequence[_TargetState],
        context_lines: int,
        *,
        budget: OperationBudget | None = None,
    ) -> tuple[_Segment, ...]:
        local_budget = budget or OperationBudget()
        by_path: dict[str, list[tuple[int, int, int, _TargetState]]] = {}
        for state in states:
            local_budget.check_deadline()
            start, end = self._context_interval(state, context_lines)
            by_path.setdefault(state.captured.path, []).append((start, end, state.index, state))
        merged: list[_Segment] = []
        for path, intervals in by_path.items():
            local_budget.check_deadline()
            intervals.sort(key=lambda item: (item[0], item[1], item[2]))
            current: _Segment | None = None
            for start, end, target_index, state in intervals:
                local_budget.check_deadline()
                if current is None:
                    current = _Segment(path, state.captured, state.geometry, start, end, [target_index])
                    continue
                if start <= current.end:
                    current.end = max(current.end, end)
                    if target_index not in current.targets:
                        current.targets.append(target_index)
                        current.targets.sort()
                    continue
                merged.append(current)
                current = _Segment(path, state.captured, state.geometry, start, end, [target_index])
            if current is not None:
                merged.append(current)
        merged.sort(key=lambda item: (min(item.targets), item.path.encode("utf-8"), item.start, item.end))
        local_budget.check_deadline()
        return tuple(merged)

    @staticmethod
    def _safe_page_end(data: bytes, start: int, proposed: int, segment_end: int) -> int:
        end = min(segment_end, max(start, proposed))
        while end > start and end < len(data) and (data[end] & _UTF8_CONTINUATION_MASK) == _UTF8_CONTINUATION_PREFIX:
            end -= 1
        # A CRLF terminator is indivisible. Never extend past the byte ceiling
        # to include its LF; backtrack instead.
        if end > start and end < segment_end and data[end - 1 : end + 1] == b"\r\n":
            end -= 1
        return end

    def _page_slice(self, segment: _Segment, start: int, page: PageRead) -> tuple[int, int]:
        if start >= segment.end:
            return start, start
        proposed = min(segment.end, start + page.source_bytes)

        end = self._safe_page_end(segment.geometry.data, start, proposed, segment.end)
        if page.max_lines > 0:
            newline_count = 0
            for index in range(start, end):
                if segment.geometry.data[index] == _LINE_FEED:
                    newline_count += 1
                    if newline_count >= page.max_lines:
                        end = index + 1
                        break
            end = self._safe_page_end(segment.geometry.data, start, end, segment.end)
        return start, end

    @staticmethod
    def _represented_line_count(data: bytes, start: int, end: int) -> int:
        """Count every source line represented by a nonempty byte slice."""

        if end <= start:
            return 0
        newlines = data[start:end].count(bytes((_LINE_FEED,)))
        return newlines + (1 if data[end - 1] != _LINE_FEED else 0)

    def _read_items(
        self,
        segments: Sequence[_Segment],
        states: Sequence[_TargetState],
        *,
        start_segment: int = 0,
        start_byte: int | None = None,
        page: PageRead | None = None,
        end_limit: int | None = None,
        budget: OperationBudget | None = None,
    ) -> tuple[ReadData, tuple[_Segment, ...], int | None, int | None]:
        local_budget = budget or OperationBudget()
        local_budget.check_deadline()
        state_by_index = {state.index: state for state in states}
        output: list[ReadItem] = []
        next_segment = len(segments)
        next_byte: int | None = None
        source_used = 0
        line_used = 0
        for segment_index, segment in enumerate(segments):
            local_budget.check_deadline()
            if segment_index < start_segment:
                continue
            offset = segment.start
            if segment_index == start_segment and start_byte is not None:
                offset = start_byte
                if offset < segment.start or offset > segment.end:
                    raise _IndexerFailure("stale_cursor", "read cursor byte is outside its segment", path=segment.path)
            empty_segment = segment.start == segment.end
            while offset < segment.end or empty_segment:
                local_budget.check_deadline()
                if empty_segment:
                    end = offset
                elif page is None:
                    end = segment.end
                else:
                    remaining_source = page.source_bytes - source_used
                    remaining_lines = page.max_lines - line_used
                    if remaining_source <= 0 or remaining_lines <= 0:
                        next_segment = segment_index
                        next_byte = offset
                        return ReadData(items=output), tuple(segments), next_segment, next_byte
                    window = page.model_copy(update={"source_bytes": remaining_source, "max_lines": remaining_lines})
                    _start, end = self._page_slice(segment, offset, window)
                    if end_limit is not None and segment_index == start_segment:
                        end = self._safe_page_end(
                            segment.geometry.data,
                            offset,
                            min(end, end_limit),
                            segment.end,
                        )
                if not empty_segment and end <= offset:
                    if output:
                        next_segment = segment_index
                        next_byte = offset
                        return ReadData(items=output), tuple(segments), next_segment, next_byte
                    raise _IndexerFailure(
                        "budget_too_small",
                        "read source byte budget cannot contain one UTF-8 code point or CRLF terminator",
                        action="narrow_query",
                        minimum_bytes=2,
                    )
                source = segment.geometry.decode(offset, end)
                enclosing: list[EnclosingResult] | None = None
                if any(state_by_index[index].enclosing is not None for index in segment.targets):
                    enclosing = [
                        EnclosingResult(target=index, result=cast(Enclosing, state_by_index[index].enclosing))
                        for index in sorted(segment.targets)
                        if state_by_index[index].enclosing is not None
                    ]
                item_values: dict[str, Any] = {
                    "targets": sorted(segment.targets),
                    "ref": SourceRef(
                        kind="source",
                        root_id=self.root.id,
                        path=segment.path,
                        file_digest=segment.captured.digest,
                        start=offset,
                        end=end,
                    ),
                    "location": Range(start=segment.geometry.position(offset), end=segment.geometry.position(end)),
                    "source": source,
                }
                if enclosing is not None:
                    item_values["enclosing"] = enclosing
                output.append(ReadItem(**item_values))
                if page is None:
                    break
                consumed = end - offset
                source_used += consumed
                if consumed:
                    line_used += self._represented_line_count(segment.geometry.data, offset, end)
                if end == segment.end:
                    next_segment = segment_index + 1
                    next_byte = None
                    offset = end
                    empty_segment = False
                    break
                next_segment = segment_index
                next_byte = end
                offset = end
                empty_segment = False
                if source_used >= page.source_bytes or line_used >= page.max_lines:
                    return ReadData(items=output), tuple(segments), next_segment, next_byte
        return ReadData(items=output), tuple(segments), next_segment, next_byte

    def _read_data(
        self,
        capture: RepositoryCapture,
        targets: Sequence[ReadTarget],
        *,
        context_lines: int = 0,
        include_enclosing: bool = True,
        page: PageRead | None = None,
        query_digest: str | None = None,
        cache: DerivedCache | None = None,
        result_builder: Callable[[ReadData, str | None], Success] | None = None,
        budget: OperationBudget | None = None,
    ) -> tuple[ReadData, str | None]:
        local_budget = budget or OperationBudget()
        local_budget.check_deadline()
        if capture.root.id != self.root.id:
            raise _IndexerFailure("invalid_reference", "capture root does not match this indexer")
        if not targets or len(targets) > _MAX_READ_TARGETS:
            raise _IndexerFailure("invalid_request", "read accepts one to eight targets")
        states, _artifacts = self._normalize_targets(
            capture,
            targets,
            cache=cache,
            budget=local_budget,
            include_enclosing=include_enclosing,
        )
        for state in states:
            local_budget.check_deadline()
            state.enclosing = self._enclosing_for(state, include_enclosing)
        segments = self._merge_segments(states, context_lines, budget=local_budget)
        start_segment = 0
        start_byte: int | None = None
        if page is not None and page.cursor is not None:
            cursor = self._validate_cursor_identity(
                page.cursor,
                op="read",
                query_digest=query_digest or "",
                selection=capture.manifest.selection_digest,
                snapshot=capture.manifest.snapshot_digest,
                toolchain=self._toolchain_id(),
            )
            checkpoint = cursor.checkpoint
            if not isinstance(checkpoint, ReadCheckpoint):
                raise _IndexerFailure(
                    "invalid_cursor", "read cursor has the wrong checkpoint kind", action="restart_query"
                )
            start_segment = checkpoint.segment
            start_byte = checkpoint.byte
            if start_segment < 0 or start_segment >= len(segments):
                raise _IndexerFailure(
                    "invalid_cursor", "read cursor segment is outside the current result", action="restart_query"
                )
            segment = segments[start_segment]
            if start_byte is None or not segment.geometry.is_boundary(start_byte):
                raise _IndexerFailure(
                    "invalid_cursor", "read cursor byte is not a UTF-8 boundary", action="restart_query"
                )
            if start_byte == segment.start:
                if start_segment == 0:
                    raise _IndexerFailure(
                        "invalid_cursor", "read cursor does not advance within its segment", action="restart_query"
                    )
            elif start_byte <= segment.start or start_byte >= segment.end:
                raise _IndexerFailure(
                    "invalid_cursor", "read cursor byte is outside its segment", action="restart_query"
                )

        def make_cursor(next_segment: int | None, next_byte: int | None) -> str | None:
            if page is None or next_segment is None or next_segment >= len(segments):
                return None
            if query_digest is None:
                raise _IndexerFailure("internal_error", "paged read is missing its query identity")
            local_budget.check_deadline()
            return encode_cursor(
                RepositoryCursor(
                    version=1,
                    op="read",
                    root=self.root.id,
                    query=query_digest,
                    selection=capture.manifest.selection_digest,
                    snapshot=capture.manifest.snapshot_digest,
                    toolchain=self._toolchain_id(),
                    checkpoint=ReadCheckpoint(
                        kind="read",
                        segment=next_segment,
                        byte=next_byte if next_byte is not None else segments[next_segment].start,
                    ),
                )
            )

        def read_once(end_limit: int | None = None) -> tuple[ReadData, str | None]:
            data, _segments, next_segment, next_byte = self._read_items(
                segments,
                states,
                start_segment=start_segment,
                start_byte=start_byte,
                page=page,
                end_limit=end_limit,
                budget=local_budget,
            )
            return data, make_cursor(next_segment, next_byte)

        data, next_cursor = read_once()
        if page is None or result_builder is None:
            local_budget.check_deadline()
            return data, next_cursor

        def sized_result(data_value: ReadData, cursor_value: str | None) -> tuple[Success, int]:
            local_budget.check_deadline()
            built = result_builder(data_value, cursor_value)
            encoded = canonical_bytes(built)
            local_budget.check_deadline()
            return built, len(encoded)

        def continuation_for_items(items: Sequence[ReadItem]) -> str | None:
            if not items:
                return next_cursor
            last = items[-1]
            for index, segment in enumerate(segments):
                if segment.path != last.ref.path:
                    continue
                if segment.start <= last.ref.start <= segment.end:
                    if last.ref.end < segment.end:
                        return make_cursor(index, last.ref.end)
                    return make_cursor(index + 1, None)
            raise _IndexerFailure("internal_error", "read result item has no source segment")

        _result, result_size = sized_result(data, next_cursor)
        if result_size <= page.max_bytes:
            return data, next_cursor
        if not data.items:
            raise _IndexerFailure(
                "budget_too_small",
                "one read result cannot fit the requested byte budget",
                action="narrow_query",
                minimum_bytes=result_size,
            )

        # Drop complete trailing disjoint items before splitting a source
        # interval. This preserves every fitting target under the shared page
        # budgets rather than returning only the first segment.
        for count in range(len(data.items) - 1, 0, -1):
            local_budget.check_deadline()
            selected = ReadData(items=list(data.items[:count]))
            selected_cursor = continuation_for_items(selected.items)
            _candidate_result, candidate_size = sized_result(selected, selected_cursor)
            if candidate_size <= page.max_bytes:
                return selected, selected_cursor

        first = data.items[0]
        first_start = first.ref.start
        first_end = first.ref.end
        if first_end <= first_start:
            raise _IndexerFailure(
                "budget_too_small",
                "one read result cannot fit the requested byte budget",
                action="narrow_query",
                minimum_bytes=result_size,
            )
        first_index = next(
            (
                index
                for index, segment in enumerate(segments)
                if segment.path == first.ref.path and segment.start <= first_start and first_end <= segment.end
            ),
            None,
        )
        if first_index is None:
            raise _IndexerFailure("internal_error", "first read result item has no source segment")
        first_segment = segments[first_index]
        boundaries = [
            offset
            for offset in range(first_start + 1, first_end + 1)
            if first_segment.geometry.is_boundary(offset)
            and not (offset < first_segment.end and first_segment.geometry.data[offset - 1 : offset + 1] == b"\r\n")
        ]

        def prefix(boundary: int) -> tuple[ReadData, str | None]:
            prefix_ref = first.ref.model_copy(update={"end": boundary})
            prefix_item = first.model_copy(
                update={
                    "ref": prefix_ref,
                    "location": Range(
                        start=first_segment.geometry.position(first_start),
                        end=first_segment.geometry.position(boundary),
                    ),
                    "source": first_segment.geometry.decode(first_start, boundary),
                }
            )
            prefix_data = ReadData(items=[prefix_item])
            prefix_cursor = (
                make_cursor(
                    first_index,
                    boundary,
                )
                if boundary < first_segment.end
                else make_cursor(first_index + 1, None)
            )
            return prefix_data, prefix_cursor

        best: tuple[ReadData, str | None] | None = None
        low = 0
        high = len(boundaries) - 1
        while low <= high:
            local_budget.check_deadline()
            middle = (low + high) // 2
            candidate = prefix(boundaries[middle])
            _candidate_result, candidate_size = sized_result(*candidate)
            if candidate_size <= page.max_bytes:
                best = candidate
                low = middle + 1
            else:
                high = middle - 1
        if best is None:
            minimum_candidate = prefix(boundaries[0]) if boundaries else (data, next_cursor)
            _minimum_result, minimum = sized_result(*minimum_candidate)
            raise _IndexerFailure(
                "budget_too_small",
                "one read result cannot fit the requested byte budget",
                action="narrow_query",
                minimum_bytes=minimum,
            )
        local_budget.check_deadline()
        return best

    def read(
        self,
        capture: RepositoryCapture,
        targets: Sequence[ReadTarget],
        *,
        context_lines: int = 0,
        include_enclosing: bool = True,
        budget: OperationBudget | None = None,
    ) -> ReadData:
        """Resolve and read a validated target batch from one capture."""

        local_budget = budget or OperationBudget()
        data, _cursor = self._read_data(
            capture,
            targets,
            context_lines=context_lines,
            include_enclosing=include_enclosing,
            budget=local_budget,
        )
        return data

    # ------------------------------------------------------------------
    # Typed operation service boundary

    @staticmethod
    def _normalized_query_payload(query: Any) -> Any:
        payload = query.to_payload() if hasattr(query, "to_payload") else query
        if isinstance(payload, Mapping):
            normalized = dict(payload)
            # Selection is represented by the final provider digest below.
            # Omitting it here makes implicit and explicit equivalent
            # selections share one semantic query identity.
            normalized.pop("selection", None)
            normalized.pop("focus", None)
            return normalized
        return payload

    @staticmethod
    def _query_projection(query: Any, *, op: str) -> dict[str, Any]:
        payload = query.to_payload() if hasattr(query, "to_payload") else {}
        values: dict[str, Any] = {"operation": op}
        if isinstance(payload, Mapping):
            for name in ("detail", "sections", "member_depth", "documentation", "include_enclosing"):
                if name in payload:
                    values[name] = payload[name]
        return values

    def _query_digest(
        self,
        query: Any,
        *,
        op: str,
        capture: RepositoryCapture,
        snapshot: str | None = None,
        projection: Any | None = None,
    ) -> str:
        final_snapshot = snapshot or capture.manifest.snapshot_digest
        return repository_query_digest(
            op,
            self._normalized_query_payload(query),
            projection if projection is not None else self._query_projection(query, op=op),
            capture.manifest.selection_digest,
            final_snapshot,
            self._toolchain_id(),
        )

    def _repository_provenance(
        self,
        *,
        op: Literal["map", "find", "interface", "read", "impact", "search"],
        query: Any,
        capture: RepositoryCapture,
        snapshot: str | None = None,
        projection: Any | None = None,
    ) -> RepositoryProvenance:
        final_snapshot = snapshot or capture.manifest.snapshot_digest
        return RepositoryProvenance(
            kind="repository",
            consistency="captured_read_set",
            query=self._query_digest(
                query,
                op=op,
                capture=capture,
                snapshot=final_snapshot,
                projection=projection,
            ),
            selection=capture.manifest.selection_digest,
            snapshot=final_snapshot,
            toolchain=self._toolchain_id(),
        )

    def _execute_map(
        self,
        arguments: MapArguments,
        *,
        budget: OperationBudget | None = None,
    ) -> Success:
        local_budget = budget or OperationBudget()
        local_budget.check_deadline()
        query = arguments.query.model_copy(
            update={"focus": sorted(arguments.query.focus, key=lambda value: value.encode("utf-8"))}
        )
        selection = Selection(paths=list(query.focus), exclusions=query.exclusions)
        capture = self._capture_namespace(
            selection,
            budget=local_budget,
            horizon={"focus": tuple(query.focus), "depth": query.depth},
        )
        provenance = self._repository_provenance(op="map", query=query, capture=capture)
        page = arguments.page or PageMap()
        rows = self._map_projection(capture, query, budget=local_budget)
        row_ids = rows.row_ids
        if len(row_ids) != len(set(row_ids)):
            raise _IndexerFailure("internal_error", "map row identities are not unique")
        start = self._seek_collection(
            page.cursor,
            op="map",
            query_digest=provenance.query,
            capture=capture,
            row_ids=row_ids,
            budget=local_budget,
        )
        if start > len(rows):
            raise _IndexerFailure("invalid_cursor", "map cursor is beyond the result", action="restart_query")
        return self._collection_result(
            op="map",
            capture=capture,
            provenance=provenance,
            coverage=Coverage(state="complete", basis="namespace"),
            page=page,
            rows=rows,
            start=start,
            row_ids=row_ids,
            data_factory=lambda selected, _owners: MapData(items=selected),
            budget=local_budget,
        )

    def _execute_find(
        self,
        arguments: FindArguments,
        *,
        budget: OperationBudget | None = None,
        cache: DerivedCache | None = None,
    ) -> Success:
        local_budget = budget or OperationBudget()
        local_budget.check_deadline()
        query = arguments.query
        capture = self._capture_sources(query.selection, budget=local_budget)
        provenance = self._repository_provenance(op="find", query=query, capture=capture)
        page = arguments.page or PageFind()
        rows, coverage = self._find_items(capture, query, cache=cache, budget=local_budget)
        row_ids = rows.row_ids if isinstance(rows, _FindProjection) else [item.row_id for item in rows]
        start = self._seek_collection(
            page.cursor,
            op="find",
            query_digest=provenance.query,
            capture=capture,
            row_ids=row_ids,
            budget=local_budget,
        )
        if start > len(rows):
            raise _IndexerFailure("invalid_cursor", "find cursor is beyond the result", action="restart_query")
        return self._collection_result(
            op="find",
            capture=capture,
            provenance=provenance,
            coverage=coverage,
            page=page,
            rows=rows,
            start=start,
            row_ids=row_ids,
            data_factory=lambda selected, _owners: FindData(items=selected),
            budget=local_budget,
        )

    def _execute_interface(
        self,
        arguments: InterfaceArguments,
        *,
        budget: OperationBudget | None = None,
        cache: DerivedCache | None = None,
    ) -> Success:
        local_budget = budget or OperationBudget()
        local_budget.check_deadline()
        query = arguments.query
        if isinstance(query, InterfaceFileQuery):
            selection = Selection(paths=[query.target.path], exclusions="default")
            capture = self._capture_sources(selection, budget=local_budget)
        elif isinstance(query, InterfaceSymbolQuery):
            selection = Selection(paths=[query.target.path], exclusions="default")
            capture = self._capture_sources(selection, budget=local_budget)
        else:
            raise _IndexerFailure("invalid_request", "interface target is unsupported")
        provenance = self._repository_provenance(op="interface", query=query, capture=capture)
        page = arguments.page or PageInterface()
        owners: list[InterfaceOwner] | None = None
        if isinstance(query, InterfaceFileQuery):
            captured = capture.files[0] if capture.files else None
            if captured is None:
                raise _IndexerFailure(
                    "invalid_reference",
                    "interface target file was not captured",
                    path=query.target.path,
                )
            rows, coverage = self._interface_file_rows(captured, query, cache=cache, budget=local_budget)
        else:
            rows, owners, coverage = self._interface_symbol_rows(capture, query, cache=cache, budget=local_budget)
        row_ids = [self._interface_row_id(item) for item in rows]
        if len(row_ids) != len(set(row_ids)):
            raise _IndexerFailure("internal_error", "interface row identities are not unique")
        start = self._seek_collection(
            page.cursor,
            op="interface",
            query_digest=provenance.query,
            capture=capture,
            row_ids=row_ids,
            budget=local_budget,
        )
        if start > len(rows):
            raise _IndexerFailure("invalid_cursor", "interface cursor is beyond the result", action="restart_query")
        return self._collection_result(
            op="interface",
            capture=capture,
            provenance=provenance,
            coverage=coverage,
            page=page,
            rows=rows,
            start=start,
            row_ids=row_ids,
            owners=owners,
            data_factory=lambda selected, owner_values: InterfaceData(
                **({"owners": owner_values} if owner_values else {}),
                items=selected,
            ),
            budget=local_budget,
        )

    @staticmethod
    def _failure_error(
        failure: _IndexerFailure | RepositoryError,
        *,
        op: str = "read",
        root: Root | None = None,
        provenance: RepositoryProvenance | None = None,
    ) -> Error:
        code = getattr(failure, "code", "internal_error")
        message = str(failure)
        if len(message.encode("utf-8")) > _MAX_ERROR_MESSAGE_BYTES:
            encoded = message.encode("utf-8")[:_MAX_ERROR_MESSAGE_BYTES]
            message = encoded.decode("utf-8", errors="ignore") or "analysis failed"
        path = getattr(failure, "path", None)
        detail_values: dict[str, Any] = {}
        kind = getattr(failure, "kind", None)
        if isinstance(kind, str) and kind:
            detail_values["kind"] = kind
        if isinstance(path, str) and path not in {".", ""}:
            detail_values["path"] = path
        minimum_bytes = getattr(failure, "minimum_bytes", None)
        if (
            isinstance(minimum_bytes, int)
            and not isinstance(minimum_bytes, bool)
            and minimum_bytes >= _MIN_ERROR_DETAIL_BYTES
        ):
            detail_values["minimum_bytes"] = minimum_bytes
        details = ErrorDetails(**detail_values) if detail_values else None
        action = getattr(failure, "action", None)
        allowed_actions = {
            "correct_input",
            "refresh_reference",
            "restart_query",
            "narrow_query",
            "install_dependency",
            "inspect_worktree",
            "report_bug",
        }
        error_values: dict[str, Any] = {
            "code": cast(Any, code),
            "message": message,
            "at": "query.targets",
        }
        if action in allowed_actions:
            error_values["action"] = action
        if details is not None:
            error_values["details"] = details
        result_values: dict[str, Any] = {
            "schema": "xray.v1",
            "ok": False,
            "op": op,
            "error": ErrorValue(**error_values),
        }
        if root is not None:
            result_values["root"] = root
        if provenance is not None:
            result_values["provenance"] = provenance
        return Error(**result_values)

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
    ) -> Success | Error:
        """Execute one typed repository analysis request."""

        operation: str | None = None
        arguments: Any
        if isinstance(request, (MapRequest, MapArguments)):
            operation = "map"
            arguments = request
        elif isinstance(request, (FindRequest, FindArguments)):
            operation = "find"
            arguments = request
        elif isinstance(request, (InterfaceRequest, InterfaceArguments)):
            operation = "interface"
            arguments = request
        elif isinstance(request, (ImpactRequest, ImpactArguments)):
            operation = "impact"
            arguments = request
        elif isinstance(request, (SearchRequest, SearchArguments)):
            operation = "search"
            arguments = request
        elif isinstance(request, (ReadRequest, ReadArguments)):
            operation = "read"
            arguments = request
        else:
            return Error(
                schema="xray.v1",
                ok=False,
                error=ErrorValue(code="invalid_request", message="indexer accepts only typed analysis arguments"),
            )
        local_budget = budget or OperationBudget(timeout_seconds=arguments.execution.timeout_seconds)
        cache = self._cache_for(arguments.execution.cache == "auto")
        root: Root | None = None
        provenance: RepositoryProvenance | None = None
        previous_toolchain = self._active_toolchain
        try:
            local_budget.check_deadline()
            if cache is not None:
                cache.evict(budget=local_budget)
            self._active_toolchain = self._observe_toolchain(budget=local_budget)
            root = normalize_root(arguments.root)
            if root.id != self.root.id:
                raise _IndexerFailure("invalid_reference", "request root does not match this indexer root")
            if operation == "map":
                return self._execute_map(arguments, budget=local_budget)
            if operation == "find":
                return self._execute_find(arguments, budget=local_budget, cache=cache)
            if operation == "interface":
                return self._execute_interface(arguments, budget=local_budget, cache=cache)
            if operation == "impact":
                return self._execute_impact(arguments, budget=local_budget, cache=cache)
            if operation == "search":
                return self._execute_search(arguments, budget=local_budget, cache=cache)
            capture = self._capture_targets(tuple(arguments.query.targets), budget=local_budget)
            provenance = self._repository_provenance(op="read", query=arguments.query, capture=capture)
            page = arguments.page or PageRead()
            coverage = Coverage(state="complete", basis="source_bytes")

            def build_read_result(data: ReadData, next_cursor: str | None) -> Success:
                page_result = PageResult() if next_cursor is None else PageResult(next_cursor=next_cursor)
                return Success(
                    schema="xray.v1",
                    ok=True,
                    op="read",
                    root=capture.root,
                    scope=capture.selection,
                    provenance=provenance,
                    data=data,
                    page=page_result,
                    coverage=coverage,
                )

            data, next_cursor = self._read_data(
                capture,
                tuple(arguments.query.targets),
                context_lines=arguments.query.context_lines,
                page=page,
                query_digest=provenance.query,
                cache=cache,
                result_builder=build_read_result,
                budget=local_budget,
            )
            return build_read_result(data, next_cursor)
        except (RepositoryError, _IndexerFailure) as exc:
            return self._failure_error(exc, op=operation or "read", root=root, provenance=provenance)
        except Exception as exc:
            failure = _IndexerFailure(
                "internal_error",
                f"{operation or 'analysis'} analysis failed: {exc}",
                action="report_bug",
            )
            return self._failure_error(failure, op=operation or "read", root=root, provenance=provenance)
        finally:
            self._active_toolchain = previous_toolchain


__all__ = [
    "LANGUAGE_MAP",
    "TOOLCHAIN_ID",
    "DeclarationArtifact",
    "DeclarationRecord",
    "XRayIndexer",
]
