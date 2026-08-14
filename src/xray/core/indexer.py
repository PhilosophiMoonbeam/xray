"""Core indexing engine for XRAY - ast-grep based implementation."""

import ast
import difflib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from collections import Counter, OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict, cast

from pathspec import GitIgnoreSpec
from thefuzz import fuzz

from xray import __version__
from xray.core.ast_grep import (
    AstGrepCommandError,
    AstGrepNotFoundError,
    get_ast_grep_output_limit,
    get_ast_grep_timeout,
    parse_json_array,
    run_ast_grep,
    run_ast_grep_bounded,
)

# Default exclusions
DEFAULT_EXCLUSIONS = {
    # Directories
    "node_modules",
    "vendor",
    "__pycache__",
    "venv",
    ".venv",
    "env",
    "target",
    "build",
    "dist",
    ".git",
    ".svn",
    ".hg",
    ".agents",
    ".beads",
    ".claude",
    ".codex",
    ".idea",
    ".vscode",
    ".reference_projects",
    ".ruff_cache",
    ".xray",
    "site-packages",
    ".tox",
    ".pytest_cache",
    ".mypy_cache",
    # File patterns
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.so",
    "*.dll",
    "*.egg-info",
    "*.log",
    ".DS_Store",
    "Thumbs.db",
    "*.swp",
    "*.swo",
    "*~",
}
DEFAULT_EXCLUSION_SPEC = GitIgnoreSpec.from_lines(sorted(DEFAULT_EXCLUSIONS))

# Language extensions
LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
}

CACHE_FILENAME = "symbols.json"
CACHE_ROOT = Path("/tmp/.xray_cache")
CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
CACHE_MAX_BYTES = 512 * 1024 * 1024
CACHE_ACTIVE_TEMP_SECONDS = 5 * 60
MAX_SYMBOL_CACHE_ENTRIES = 2048
GIT_TIMEOUT_SECONDS = 5
GIT_PORCELAIN_MIN_RECORD_BYTES = 4
RG_TIMEOUT_SECONDS = 30
MAX_RG_OUTPUT_CHARS = 10 * 1024 * 1024
MAX_SKELETON_FILE_BYTES = 1024 * 1024
MAX_INVENTORY_FILES = 20_000
MAX_INVENTORY_SOURCE_BYTES = 256 * 1024 * 1024
MAX_INVENTORY_SYMBOLS = 100_000
MAX_SOURCE_ARGUMENT_CHARS = 128 * 1024
MAX_IMPACT_RAW_RESULTS = 10_000
INVENTORY_CACHE_FILENAME = "inventory.json"
INVENTORY_SCHEMA_VERSION = 2
REPLACEMENT_PLAN_VERSION = "xray.replace.v2"
DEFAULT_REPLACEMENT_MAX_MATCHES = 1000
DEFAULT_REPLACEMENT_MAX_FILES = 100
DEFAULT_REPLACEMENT_PREVIEW_LIMIT = 50
DEFAULT_REPLACEMENT_DIFF_LIMIT = 100_000
MAX_REPLACEMENT_SYNTAX_DIAGNOSTICS = 50
MAX_REPLACEMENT_FILE_BYTES = 10 * 1024 * 1024
MAX_REPLACEMENT_TOTAL_BYTES = 50 * 1024 * 1024


class ReplacementApplyError(RuntimeError):
    """Raised when guarded replacement fails, with rollback evidence."""

    def __init__(self, message: str, *, rollback_count: int = 0, rollback_succeeded: bool = True):
        super().__init__(message)
        self.rollback_count = rollback_count
        self.rollback_succeeded = rollback_succeeded


class InterfaceReadError(RuntimeError):
    """Typed interface-extraction failure for structured adapters."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PreparedReplacementFile:
    """One affected file and its fully prepared postimage."""

    path: Path
    relative_path: str
    original: bytes
    postimage: bytes
    edits: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class PreparedReplacement:
    """Internal complete plan plus staged-in-memory file postimages."""

    plan: dict[str, Any]
    files: tuple[PreparedReplacementFile, ...]
    matches: tuple[dict[str, Any], ...]


class SymbolSkeleton(TypedDict, total=False):
    name: str
    type: str
    signature: str
    doc: str


class ExploreSymbol(TypedDict):
    name: str
    type: str
    signature: str
    doc: str


class ExploreEntryBase(TypedDict):
    path: str
    abs_path: str
    name: str
    kind: str
    depth: int


class ExploreEntry(ExploreEntryBase, total=False):
    language: str
    symbols: list[ExploreSymbol]


class ExploreOptions(TypedDict):
    max_depth: int | None
    include_symbols: bool
    focus_dirs: list[str]
    include_root_context: bool
    focus_mode: str
    max_symbols_per_file: int
    symbol_types: list[str]
    max_entries: int
    use_default_exclusions: bool


class ExploreRepoData(TypedDict):
    root_path: str
    tree_text: str
    entries: list[ExploreEntry]
    options: ExploreOptions
    truncated: bool


class SymbolMatchBase(TypedDict):
    name: str
    type: str
    path: str
    start_line: int
    end_line: int


class SymbolMatch(SymbolMatchBase, total=False):
    score: int
    abs_path: str
    qualified_name: str
    owner: str | None
    language: str
    match_reason: str
    confidence: str
    signature: str
    role: str
    visibility: str
    doc: str


class ImpactReferenceBase(TypedDict):
    file: str
    line: int
    text: str


class ImpactReference(ImpactReferenceBase, total=False):
    matched_text: str
    type: str
    confidence: str


class ImpactResult(TypedDict):
    references: list[ImpactReference]
    total_count: int
    raw_count: int
    filtered_count: int
    strategy: str
    note: str
    total_exact: bool
    degradation_reason: str | None
    execution_limited: bool
    execution_cap: int | None


@dataclass(frozen=True)
class IgnoreRuleSet:
    """One directory-relative Git ignore specification."""

    base: Path
    spec: GitIgnoreSpec


@dataclass(frozen=True)
class IgnorePolicy:
    """Ordered repository ignore rules plus independent built-in exclusions."""

    rules: tuple[IgnoreRuleSet, ...]
    use_default_exclusions: bool = True


class XRayIndexer:
    """Main indexer for XRAY - provides file tree and symbol extraction using ast-grep."""

    def __init__(self, root_path: str):
        self.root_path = Path(root_path).resolve()
        self._cache: OrderedDict[str, list[SymbolSkeleton]] = OrderedDict()
        self.last_warnings: list[str] = []
        self.last_result_total_exact = True
        self.last_result_cap: int | None = None
        self.last_find_total = 0
        self.last_mutation_summary: dict[str, Any] | None = None
        self._inventory_fingerprint: str | None = None
        self._inventory: list[dict[str, Any]] | None = None
        self._init_cache()

    def _init_cache(self):
        """Initialize cache based on git commit SHA."""
        try:
            # Get current git commit SHA
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.root_path,
                capture_output=True,
                check=False,
                text=True,
                timeout=GIT_TIMEOUT_SECONDS,
            )
            if result.returncode == 0:
                self.commit_sha = result.stdout.strip()
                root_hash = hashlib.sha256(str(self.root_path).encode("utf-8")).hexdigest()[:16]
                self.cache_dir = CACHE_ROOT / f"{root_hash}-{self.commit_sha}"
                self._prune_disk_cache(self.cache_dir)
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                self._load_cache()
            else:
                self.commit_sha = None
                self.cache_dir = None
        except Exception:
            self.commit_sha = None
            self.cache_dir = None

    @staticmethod
    def _prune_disk_cache(current_dir: Path) -> None:
        """Remove expired and excess cache entries without disturbing active writes."""
        cache_root = current_dir.parent
        try:
            entries = [entry for entry in cache_root.iterdir() if entry.is_dir() and entry != current_dir]
        except OSError:
            return

        now = time.time()
        candidates: list[tuple[float, int, Path]] = []
        for entry in entries:
            try:
                # NamedTemporaryFile uses a ``tmp`` prefix. Its presence means another
                # indexer may be between writing and atomically replacing symbols.json.
                if XRayIndexer._has_active_cache_temp(entry, now):
                    continue
                modified = entry.stat().st_mtime
                size = sum(
                    child.stat().st_size for child in entry.rglob("*") if child.is_file() and not child.is_symlink()
                )
            except OSError:
                # Concurrent creation/removal and partially readable entries are benign.
                continue
            candidates.append((modified, size, entry))

        retained: list[tuple[float, int, Path]] = []
        for modified, size, entry in candidates:
            if now - modified > CACHE_MAX_AGE_SECONDS:
                if not XRayIndexer._remove_cache_entry(entry, now):
                    retained.append((modified, size, entry))
            else:
                retained.append((modified, size, entry))

        total_size = sum(size for _, size, _ in retained)
        for _, size, entry in sorted(retained):
            if total_size <= CACHE_MAX_BYTES:
                break
            if not XRayIndexer._remove_cache_entry(entry, now):
                continue
            total_size -= size

    @staticmethod
    def _has_active_cache_temp(cache_dir: Path, now: float) -> bool:
        """Return whether a recently touched atomic-write temp file exists."""
        return any(
            child.name.startswith("tmp") and now - child.stat().st_mtime <= CACHE_ACTIVE_TEMP_SECONDS
            for child in cache_dir.iterdir()
        )

    @staticmethod
    def _remove_cache_entry(cache_dir: Path, now: float) -> bool:
        """Remove one entry after rechecking for a concurrent atomic write."""
        try:
            if XRayIndexer._has_active_cache_temp(cache_dir, now):
                return False
            shutil.rmtree(cache_dir)
        except OSError:
            return False
        return True

    def _load_cache(self):
        """Load cache from disk if available."""
        if not self.cache_dir:
            return

        cache_file = self.cache_dir / CACHE_FILENAME
        if cache_file.exists():
            try:
                with open(cache_file, encoding="utf-8") as f:
                    self._cache = self._coerce_symbol_cache(json.load(f))
            except Exception:
                self._cache = OrderedDict()

    def _save_cache(self):
        """Save cache to disk."""
        if not self.cache_dir:
            return

        self._prune_symbol_cache()
        cache_file = self.cache_dir / CACHE_FILENAME
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile("w", dir=self.cache_dir, delete=False, encoding="utf-8") as f:
                json.dump(self._cache, f, separators=(",", ":"), sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
                temp_path = Path(f.name)
            os.replace(temp_path, cache_file)
        except Exception:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            pass

    def _coerce_symbol_cache(self, value: Any) -> OrderedDict[str, list[SymbolSkeleton]]:
        """Return a bounded cache containing only the symbol skeleton shape XRAY writes."""
        cache: OrderedDict[str, list[SymbolSkeleton]] = OrderedDict()
        if not isinstance(value, dict):
            return cache

        for key, symbols in value.items():
            if not isinstance(key, str) or not isinstance(symbols, list):
                continue

            clean_symbols: list[SymbolSkeleton] = []
            for symbol in symbols:
                if not isinstance(symbol, dict):
                    continue
                signature = symbol.get("signature", "")
                doc = symbol.get("doc", "")
                if isinstance(signature, str) and isinstance(doc, str):
                    clean_symbol: SymbolSkeleton = {"signature": signature, "doc": doc}
                    name = symbol.get("name")
                    symbol_type = symbol.get("type")
                    if isinstance(name, str) and isinstance(symbol_type, str):
                        clean_symbol.update({"name": name, "type": symbol_type})
                    clean_symbols.append(clean_symbol)

            if clean_symbols:
                cache[key] = clean_symbols

        while len(cache) > MAX_SYMBOL_CACHE_ENTRIES:
            cache.popitem(last=False)
        return cache

    def _get_cached_symbols(self, cache_key: str) -> list[SymbolSkeleton] | None:
        """Return cached symbols and mark the entry as recently used."""
        symbols = self._cache.get(cache_key)
        if symbols is not None:
            self._cache.move_to_end(cache_key)
        return symbols

    def _set_cached_symbols(self, cache_key: str, symbols: list[SymbolSkeleton]) -> None:
        """Store symbols while bounding long-running MCP memory use."""
        self._cache[cache_key] = symbols
        self._cache.move_to_end(cache_key)
        self._prune_symbol_cache()

    def _prune_symbol_cache(self) -> None:
        """Drop least-recently-used symbol entries past the configured cap."""
        while len(self._cache) > MAX_SYMBOL_CACHE_ENTRIES:
            self._cache.popitem(last=False)

    def _get_cache_key(self, file_path: Path) -> str:
        """Generate cache key for a file."""
        try:
            stat = file_path.stat()
            return f"{file_path}:{stat.st_mtime_ns}:{stat.st_size}"
        except OSError:
            return str(file_path)

    def _resolve_repo_path(self, path: str, *, require_file: bool = False) -> Path:
        """Resolve a user path inside the repository and optionally require a file."""
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.root_path / candidate
        candidate = candidate.resolve()
        try:
            candidate.relative_to(self.root_path)
        except ValueError as exc:
            raise ValueError(f"Path '{path}' is outside repository root '{self.root_path}'.") from exc
        if not candidate.exists():
            raise ValueError(f"Path '{path}' does not exist.")
        if require_file and not candidate.is_file():
            raise ValueError(f"Path '{path}' is not a file.")
        return candidate

    def _operation_scopes(self, paths: Sequence[str] | None) -> tuple[list[Path], list[str]]:
        """Return contained absolute operation paths and stable relative identities."""
        resolved: list[Path] = []
        relative: list[str] = []
        for value in paths or ():
            candidate = self._resolve_repo_path(value)
            if candidate in resolved:
                continue
            resolved.append(candidate)
            relative.append("." if candidate == self.root_path else candidate.relative_to(self.root_path).as_posix())
        return resolved, relative

    @staticmethod
    def _validate_globs(globs: Sequence[str] | None) -> list[str]:
        """Validate ast-grep glob filters without changing their ordered meaning."""
        result: list[str] = []
        for value in globs or ():
            if not value or "\x00" in value:
                raise ValueError("Glob filters must be non-empty and must not contain NUL bytes.")
            result.append(value)
        return result

    def _append_operation_scope(
        self,
        args: list[str],
        paths: Sequence[str] | None,
        globs: Sequence[str] | None,
    ) -> tuple[list[str], list[str]]:
        """Append filters and contained positional paths, returning stable identities."""
        resolved_paths, relative_paths = self._operation_scopes(paths)
        normalized_globs = self._validate_globs(globs)
        for glob in normalized_globs:
            args.extend(["--globs", glob])
        args.extend(str(path) for path in (resolved_paths or [self.root_path]))
        return relative_paths, normalized_globs

    def search_pattern(
        self,
        pattern: str,
        lang: str | None = None,
        *,
        paths: Sequence[str] | None = None,
        globs: Sequence[str] | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return structurally matched candidates within explicit execution bounds."""
        if not pattern:
            raise ValueError("Pattern must not be empty.")
        if max_results is not None and max_results < 1:
            raise ValueError("max_results must be 1 or greater.")
        args = ["run", "--pattern", pattern]
        if lang:
            args.extend(["--lang", lang])
        self._append_operation_scope(args, paths, globs)
        if max_results is None:
            args.insert(3, "--json=compact")
            matches = parse_json_array(run_ast_grep(args).stdout)
            total_exact = True
        else:
            bounded = run_ast_grep_bounded(args, max_results)
            matches = bounded.matches
            total_exact = bounded.total_exact
        self.last_result_total_exact = total_exact
        self.last_result_cap = max_results
        return matches

    def _rule_arguments(self, rule_path: str) -> tuple[list[str], str]:
        """Resolve one contained rule or configuration path to ast-grep arguments."""
        resolved_rule = self._resolve_repo_path(rule_path)
        if resolved_rule.is_dir():
            configs = [resolved_rule / "sgconfig.yml", resolved_rule / "sgconfig.yaml"]
            config = next((candidate for candidate in configs if candidate.is_file()), None)
            if config is None:
                raise ValueError(f"Rule directory '{rule_path}' does not contain sgconfig.yml or sgconfig.yaml.")
            resolved_rule = config
            rule_args = ["--config", str(config)]
        elif resolved_rule.name in {"sgconfig.yml", "sgconfig.yaml"}:
            rule_args = ["--config", str(resolved_rule)]
        else:
            rule_args = ["--rule", str(resolved_rule)]
        return rule_args, resolved_rule.relative_to(self.root_path).as_posix()

    def _scan_rule_matches(
        self,
        rule_path: str,
        *,
        paths: Sequence[str] | None = None,
        globs: Sequence[str] | None = None,
        max_results: int | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        """Return rule matches and the normalized contained rule identity."""
        if max_results is not None and max_results < 1:
            raise ValueError("max_results must be 1 or greater.")
        rule_args, relative_rule = self._rule_arguments(rule_path)
        args = ["scan", *rule_args, "--json=compact"]
        if max_results is not None:
            args.extend(["--max-results", str(max_results)])
        self._append_operation_scope(args, paths, globs)
        matches = parse_json_array(run_ast_grep(args).stdout)
        self.last_result_total_exact = max_results is None or len(matches) < max_results
        self.last_result_cap = max_results
        return matches, relative_rule

    @staticmethod
    def _sha256(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    @staticmethod
    def _canonical_json(value: Any) -> bytes:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()

    @staticmethod
    def _capture_values(match: Mapping[str, Any]) -> dict[str, Any]:
        meta = match.get("metaVariables")
        if not isinstance(meta, Mapping):
            return {}
        captures: dict[str, Any] = {}
        for group in ("single", "transformed"):
            values = meta.get(group)
            if isinstance(values, Mapping):
                for name, value in values.items():
                    if isinstance(value, Mapping) and isinstance(value.get("text"), str):
                        captures[str(name)] = value["text"]
        multi = meta.get("multi")
        if isinstance(multi, Mapping):
            for name, values in multi.items():
                if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                    texts = [value["text"] for value in values if isinstance(value, Mapping) and "text" in value]
                    if texts:
                        captures[str(name)] = texts
        return captures

    def _replacement_candidates(
        self,
        *,
        pattern: str | None,
        replacement: str | None,
        rule_path: str | None,
        lang: str | None,
        paths: Sequence[str] | None,
        globs: Sequence[str] | None,
        max_results: int | None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Return replacement-bearing ast-grep candidates and normalized query identity."""
        pattern_change = pattern is not None or replacement is not None
        rule_change = rule_path is not None
        if pattern_change == rule_change:
            raise ValueError("Provide exactly one replacement source: pattern/replacement or rule_path.")
        if rule_change and lang is not None:
            raise ValueError("Language applies only to pattern/replacement plans, not rule_path plans.")
        resolved_paths, relative_paths = self._operation_scopes(paths)
        normalized_globs = self._validate_globs(globs)

        if pattern_change:
            if not pattern:
                raise ValueError("Pattern must not be empty.")
            if replacement is None:
                raise ValueError("Replacement must be provided with a pattern.")
            args = ["run", "--pattern", pattern, "--rewrite", replacement]
            if lang:
                args.extend(["--lang", lang])
            for glob in normalized_globs:
                args.extend(["--globs", glob])
            args.extend(str(path) for path in (resolved_paths or [self.root_path]))
            if max_results is None:
                args.insert(5, "--json=compact")
                matches = parse_json_array(run_ast_grep(args).stdout)
            else:
                matches = run_ast_grep_bounded(args, max_results).matches
            change = {"kind": "pattern", "pattern": pattern, "replacement": replacement, "language": lang}
        else:
            rule_args, relative_rule = self._rule_arguments(str(rule_path))
            args = ["scan", *rule_args, "--json=compact"]
            if max_results is not None:
                args.extend(["--max-results", str(max_results)])
            for glob in normalized_globs:
                args.extend(["--globs", glob])
            args.extend(str(path) for path in (resolved_paths or [self.root_path]))
            matches = parse_json_array(run_ast_grep(args).stdout)
            change = {"kind": "rule", "rule_path": relative_rule}

        for match in matches:
            if not isinstance(match.get("replacement"), str):
                raise ValueError("Every replacement candidate must include ast-grep replacement text.")
        return matches, {"change": change, "paths": relative_paths, "globs": normalized_globs}

    @staticmethod
    def _replacement_offsets(match: Mapping[str, Any]) -> tuple[int, int]:
        replacement_offsets = match.get("replacementOffsets")
        if isinstance(replacement_offsets, Mapping):
            start = replacement_offsets.get("start")
            end = replacement_offsets.get("end")
        else:
            range_data = match.get("range")
            byte_offset = range_data.get("byteOffset") if isinstance(range_data, Mapping) else None
            start = byte_offset.get("start") if isinstance(byte_offset, Mapping) else None
            end = byte_offset.get("end") if isinstance(byte_offset, Mapping) else None
        if not isinstance(start, int) or not isinstance(end, int):
            raise ValueError("Replacement candidate is missing integer byte offsets.")
        return start, end

    def _prepare_replacement_files(
        self, matches: Sequence[dict[str, Any]]
    ) -> tuple[tuple[PreparedReplacementFile, ...], list[dict[str, Any]]]:
        """Validate candidates and build every postimage without writing files."""
        grouped: dict[Path, list[dict[str, Any]]] = {}
        for match in matches:
            file_value = match.get("file")
            if not isinstance(file_value, str) or not file_value:
                raise ValueError("Replacement candidate is missing a file path.")
            path = self._resolve_repo_path(file_value, require_file=True)
            grouped.setdefault(path, []).append(match)

        input_bytes = 0
        output_bytes = 0
        files: list[PreparedReplacementFile] = []
        preview: list[dict[str, Any]] = []
        for path in sorted(grouped, key=lambda item: item.as_posix()):
            original = path.read_bytes()
            if len(original) > MAX_REPLACEMENT_FILE_BYTES:
                raise ValueError(f"Replacement file '{path}' exceeds {MAX_REPLACEMENT_FILE_BYTES} bytes.")
            input_bytes += len(original)
            if input_bytes > MAX_REPLACEMENT_TOTAL_BYTES:
                raise ValueError(f"Replacement inputs exceed {MAX_REPLACEMENT_TOTAL_BYTES} total bytes.")

            edits: list[dict[str, Any]] = []
            for match in grouped[path]:
                start, end = self._replacement_offsets(match)
                if start < 0 or end < start or end > len(original):
                    raise ValueError(f"Replacement candidate has invalid byte offsets for '{path}'.")
                replacement_text = str(match["replacement"])
                replacement_bytes = replacement_text.encode("utf-8")
                before_bytes = original[start:end]
                try:
                    before_text = before_bytes.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError(f"Replacement candidate splits a UTF-8 sequence in '{path}'.") from exc
                matched_text = match.get("text")
                if isinstance(matched_text, str) and before_text != matched_text:
                    raise ValueError(f"Replacement candidate no longer matches source bytes in '{path}'.")
                range_data = match.get("range")
                start_data = range_data.get("start", {}) if isinstance(range_data, Mapping) else {}
                edit = {
                    "start": start,
                    "end": end,
                    "before": before_text,
                    "after": replacement_text,
                    "changed": before_bytes != replacement_bytes,
                    "line": int(start_data.get("line", 0)) + 1 if isinstance(start_data, Mapping) else 1,
                    "column": int(start_data.get("column", 0)) + 1 if isinstance(start_data, Mapping) else 1,
                    "captures": self._capture_values(match),
                    "_match": match,
                }
                edits.append(edit)

            edits.sort(key=lambda item: (item["start"], item["end"]))
            previous_end = -1
            seen_ranges: set[tuple[int, int]] = set()
            for edit in edits:
                edit_range = (edit["start"], edit["end"])
                if edit["start"] < previous_end or edit_range in seen_ranges:
                    raise ValueError(f"Replacement candidates overlap in '{path}'.")
                seen_ranges.add(edit_range)
                previous_end = edit["end"]

            postimage = original
            for edit in reversed(edits):
                postimage = postimage[: edit["start"]] + edit["after"].encode("utf-8") + postimage[edit["end"] :]
            if len(postimage) > MAX_REPLACEMENT_FILE_BYTES:
                raise ValueError(f"Replacement postimage '{path}' exceeds {MAX_REPLACEMENT_FILE_BYTES} bytes.")
            output_bytes += len(postimage)
            if output_bytes > MAX_REPLACEMENT_TOTAL_BYTES:
                raise ValueError(f"Replacement outputs exceed {MAX_REPLACEMENT_TOTAL_BYTES} total bytes.")

            relative_path = path.relative_to(self.root_path).as_posix()
            for edit in edits:
                source_match = edit.pop("_match")
                edit["edit_id"] = self._sha256(
                    self._canonical_json(
                        {
                            "path": relative_path,
                            "preimage_sha256": self._sha256(original),
                            "start": edit["start"],
                            "end": edit["end"],
                            "before_sha256": self._sha256(edit["before"].encode("utf-8")),
                            "after_sha256": self._sha256(edit["after"].encode("utf-8")),
                        }
                    )
                )
                source_match["_xray_edit_id"] = edit["edit_id"]
                preview.append({"path": relative_path, **edit})
            files.append(
                PreparedReplacementFile(
                    path=path,
                    relative_path=relative_path,
                    original=original,
                    postimage=postimage,
                    edits=tuple(edits),
                )
            )
        return tuple(files), preview

    def _git_state(self, affected_paths: Sequence[str] = ()) -> tuple[str | None, bool, list[str]]:
        """Return the Git commit, repository dirtiness, and dirty affected paths."""
        try:
            commit_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.root_path,
                capture_output=True,
                check=False,
                text=True,
                timeout=GIT_TIMEOUT_SECONDS,
            )
            status_result = subprocess.run(
                ["git", "status", "--porcelain=v1", "--untracked-files=normal"],
                cwd=self.root_path,
                capture_output=True,
                check=False,
                text=True,
                timeout=GIT_TIMEOUT_SECONDS,
            )
            affected_result = subprocess.run(
                [
                    "git",
                    "status",
                    "--porcelain=v1",
                    "-z",
                    "--untracked-files=all",
                    "--",
                    *affected_paths,
                ],
                cwd=self.root_path,
                capture_output=True,
                check=False,
                timeout=GIT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Timed out while determining Git dirty state for replacement safety.") from exc
        except OSError:
            return None, False, []
        if commit_result.returncode != 0:
            return None, False, []
        if status_result.returncode != 0 or affected_result.returncode != 0:
            raise ValueError("Could not determine Git dirty state for replacement safety.")
        commit = commit_result.stdout.strip()
        dirty = bool(status_result.stdout.strip())
        dirty_affected: list[str] = []
        if affected_paths and affected_result.returncode == 0 and affected_result.stdout:
            records = affected_result.stdout.split(b"\0")
            reported: set[str] = set()
            index = 0
            while index < len(records):
                record = records[index]
                index += 1
                if not record:
                    continue
                if len(record) < GIT_PORCELAIN_MIN_RECORD_BYTES:
                    reported.clear()
                    break
                status = record[:2]
                reported.add(record[3:].decode("utf-8", errors="surrogateescape"))
                if b"R" in status or b"C" in status:
                    if index < len(records) and records[index]:
                        reported.add(records[index].decode("utf-8", errors="surrogateescape"))
                    index += 1
            normalized = set(affected_paths)
            dirty_affected = sorted(normalized & reported)
            if not dirty_affected:
                # An unparsed status entry must fail safe rather than overwrite user work.
                dirty_affected = sorted(normalized)
        return commit, dirty, dirty_affected

    @staticmethod
    def _replacement_language(relative_path: str, requested_language: str | None) -> str | None:
        """Return the ast-grep language used to parse one affected source file."""
        aliases = {
            "js": "javascript",
            "jsx": "javascript",
            "py": "python",
            "ts": "typescript",
            "tsx": "typescript",
        }
        if requested_language:
            normalized = requested_language.casefold()
            return aliases.get(normalized, normalized)
        return LANGUAGE_MAP.get(Path(relative_path).suffix.casefold())

    def _syntax_snapshot(self, content: bytes, language: str | None) -> tuple[dict[str, Any], Counter[str]]:
        """Return bounded, digestible ast-grep ERROR-node evidence for source bytes."""
        if language is None:
            return {"checked": False, "reason": "unsupported_language"}, Counter()
        try:
            source = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Replacement syntax validation requires UTF-8 source for {language}.") from exc
        diagnostics = parse_json_array(
            run_ast_grep(
                ["run", "--kind", "ERROR", "--stdin", "-l", language, "--json=compact"],
                input_text=source,
            ).stdout
        )
        signatures: Counter[str] = Counter()
        samples: list[dict[str, Any]] = []
        for diagnostic in diagnostics:
            text = str(diagnostic.get("text", ""))
            signature = self._sha256(self._canonical_json({"language": language, "text": text}))
            signatures[signature] += 1
            if len(samples) < MAX_REPLACEMENT_SYNTAX_DIAGNOSTICS:
                range_data = diagnostic.get("range")
                start = range_data.get("start", {}) if isinstance(range_data, Mapping) else {}
                samples.append(
                    {
                        "line": int(start.get("line", 0)) + 1 if isinstance(start, Mapping) else 1,
                        "column": int(start.get("column", 0)) + 1 if isinstance(start, Mapping) else 1,
                        "text": text[:200],
                        "signature": signature,
                    }
                )
        expanded_signatures = sorted(signature for signature, count in signatures.items() for _ in range(count))
        return (
            {
                "checked": True,
                "parser": "ast-grep",
                "language": language,
                "diagnostic_count": len(diagnostics),
                "diagnostics_returned": len(samples),
                "diagnostics_truncated": len(samples) < len(diagnostics),
                "diagnostic_fingerprint": self._sha256(self._canonical_json(expanded_signatures)),
                "diagnostics": samples,
            },
            signatures,
        )

    def _replacement_syntax_evidence(
        self, item: PreparedReplacementFile, requested_language: str | None
    ) -> dict[str, Any]:
        """Compare preimage and postimage parse errors without mutating the file."""
        language = self._replacement_language(item.relative_path, requested_language)
        preimage, before = self._syntax_snapshot(item.original, language)
        postimage, after = self._syntax_snapshot(item.postimage, language)
        new_counts = after - before
        new_signatures = set(new_counts)
        new_diagnostics = [
            diagnostic
            for diagnostic in postimage.get("diagnostics", [])
            if isinstance(diagnostic, Mapping) and diagnostic.get("signature") in new_signatures
        ][:MAX_REPLACEMENT_SYNTAX_DIAGNOSTICS]
        return {
            "checked": language is not None,
            "language": language,
            "parser": "ast-grep" if language is not None else None,
            "preimage": preimage,
            "postimage": postimage,
            "new_diagnostic_count": sum(new_counts.values()),
            "new_diagnostics": new_diagnostics,
        }

    @staticmethod
    def _plan_digest_payload(plan: Mapping[str, Any]) -> dict[str, Any]:
        """Return the complete review artifact except for its self-referential digest."""
        return {str(key): value for key, value in plan.items() if key != "plan_digest"}

    @staticmethod
    def _replacement_diff(files: Sequence[PreparedReplacementFile]) -> str:
        """Return a deterministic unified diff for every changed file."""
        chunks: list[str] = []
        for item in files:
            if item.original == item.postimage:
                continue
            before = item.original.decode("utf-8").splitlines(keepends=True)
            after = item.postimage.decode("utf-8").splitlines(keepends=True)
            chunks.extend(
                difflib.unified_diff(
                    before,
                    after,
                    fromfile=f"a/{item.relative_path}",
                    tofile=f"b/{item.relative_path}",
                    lineterm="\n",
                )
            )
        return "".join(chunks)

    def _build_replacement_plan(
        self,
        *,
        pattern: str | None = None,
        replacement: str | None = None,
        rule_path: str | None = None,
        lang: str | None = None,
        paths: Sequence[str] | None = None,
        globs: Sequence[str] | None = None,
        max_matches: int | None = DEFAULT_REPLACEMENT_MAX_MATCHES,
        max_files: int | None = DEFAULT_REPLACEMENT_MAX_FILES,
        allow_noop: bool = False,
        allow_truncated_review: bool = False,
        allow_dirty_affected: bool = False,
        allow_new_parse_errors: bool = False,
        preview_limit: int = DEFAULT_REPLACEMENT_PREVIEW_LIMIT,
        diff_limit: int = DEFAULT_REPLACEMENT_DIFF_LIMIT,
        selected_edit_ids: Sequence[str] | None = None,
    ) -> PreparedReplacement:
        """Build one exact non-mutating replacement plan and its in-memory postimages."""
        if max_matches is not None and max_matches < 1:
            raise ValueError("max_matches must be 1 or greater.")
        if max_files is not None and max_files < 1:
            raise ValueError("max_files must be 1 or greater.")
        if preview_limit < 0:
            raise ValueError("preview_limit must be 0 or greater.")
        if diff_limit < 0:
            raise ValueError("diff_limit must be 0 or greater.")
        execution_cap = max_matches + 1 if max_matches is not None else None
        matches, query = self._replacement_candidates(
            pattern=pattern,
            replacement=replacement,
            rule_path=rule_path,
            lang=lang,
            paths=paths,
            globs=globs,
            max_results=execution_cap,
        )
        if max_matches is not None and len(matches) > max_matches:
            raise ValueError(f"Replacement has more than the allowed {max_matches} candidates.")
        files, preview = self._prepare_replacement_files(matches)
        available_edit_ids = {str(edit["edit_id"]) for edit in preview}
        normalized_selection = sorted(set(selected_edit_ids or ()))
        if selected_edit_ids is not None:
            unknown = sorted(set(normalized_selection) - available_edit_ids)
            if unknown:
                raise ValueError(f"Unknown replacement edit_id: {unknown[0]}.")
            selected = set(normalized_selection)
            matches = [match for match in matches if str(match.get("_xray_edit_id", "")) in selected]
            if matches:
                files, preview = self._prepare_replacement_files(matches)
            else:
                files, preview = (), []
        if max_files is not None and len(files) > max_files:
            raise ValueError(f"Replacement affects more than the allowed {max_files} files.")

        requested_language = query["change"].get("language") if query["change"]["kind"] == "pattern" else None
        syntax_evidence = [self._replacement_syntax_evidence(item, requested_language) for item in files]
        file_payloads = [
            {
                "path": item.relative_path,
                "preimage_sha256": self._sha256(item.original),
                "postimage_sha256": self._sha256(item.postimage),
                "byte_size": len(item.original),
                "postimage_byte_size": len(item.postimage),
                "edit_count": len(item.edits),
                "changed_edit_count": sum(bool(edit["changed"]) for edit in item.edits),
                "changed": item.original != item.postimage,
                "syntax": syntax,
                "edits": [
                    {
                        "edit_id": edit["edit_id"],
                        "start": edit["start"],
                        "end": edit["end"],
                        "before_sha256": self._sha256(edit["before"].encode("utf-8")),
                        "after_sha256": self._sha256(edit["after"].encode("utf-8")),
                        "changed": edit["changed"],
                    }
                    for edit in item.edits
                ],
            }
            for item, syntax in zip(files, syntax_evidence, strict=True)
        ]
        if selected_edit_ids is not None:
            query["selected_edit_ids"] = normalized_selection
        affected_paths = [item.relative_path for item in files]
        commit, dirty, dirty_affected_paths = self._git_state(affected_paths)
        fingerprint_payload = {
            "root_path": str(self.root_path),
            "git_commit": commit,
            "query": query,
            "files": [{"path": item["path"], "sha256": item["preimage_sha256"]} for item in file_payloads],
        }
        root_fingerprint = self._sha256(self._canonical_json(fingerprint_payload))
        changed_candidate_count = sum(1 for item in files for edit in item.edits if bool(edit["changed"]))
        new_parse_error_count = sum(int(item["new_diagnostic_count"]) for item in syntax_evidence)
        edit_manifest = [
            {
                "edit_id": edit["edit_id"],
                "path": edit["path"],
                "line": edit["line"],
                "column": edit["column"],
                "before_sha256": self._sha256(edit["before"].encode("utf-8")),
                "after_sha256": self._sha256(edit["after"].encode("utf-8")),
                "changed": edit["changed"],
                "selected": True,
            }
            for edit in preview
        ]
        warnings: list[str] = []
        if query["change"]["kind"] == "pattern" and not query["change"].get("language"):
            warnings.append("Language was inferred; review configuration and documentation matches before apply.")
        if dirty:
            warnings.append("Repository worktree is dirty; the plan digest still binds every affected preimage.")
        if dirty_affected_paths and not allow_dirty_affected:
            warnings.append("Affected files already contain Git worktree changes; acknowledge them before apply.")
        if new_parse_error_count and not allow_new_parse_errors:
            warnings.append("Replacement postimages introduce new parse errors; revise the replacement before apply.")
        if matches and changed_candidate_count == 0:
            warnings.append("Every candidate is a no-op; apply requires explicit no-op allowance.")
        full_diff = self._replacement_diff(files)
        preview_truncated = len(preview) > preview_limit
        diff_truncated = len(full_diff) > diff_limit
        review_truncated = preview_truncated or diff_truncated
        review_complete = not review_truncated or allow_truncated_review
        applicable = (
            bool(matches)
            and review_complete
            and (changed_candidate_count > 0 or allow_noop)
            and (not dirty_affected_paths or allow_dirty_affected)
            and (new_parse_error_count == 0 or allow_new_parse_errors)
        )
        applicability_reason: str | None = None
        if not matches:
            applicability_reason = "no_candidates"
        elif review_truncated and not allow_truncated_review:
            applicability_reason = "truncated_review_not_acknowledged"
            warnings.append("Preview or diff is truncated; acknowledge truncated review before apply.")
        elif changed_candidate_count == 0 and not allow_noop:
            applicability_reason = "noop_not_allowed"
        elif new_parse_error_count and not allow_new_parse_errors:
            applicability_reason = "new_parse_errors"
        elif dirty_affected_paths and not allow_dirty_affected:
            applicability_reason = "dirty_affected_files_not_acknowledged"
        plan: dict[str, Any] = {
            "plan_version": REPLACEMENT_PLAN_VERSION,
            "root_path": str(self.root_path),
            "root_fingerprint": root_fingerprint,
            "query": query,
            "bounds": {
                "max_matches": max_matches,
                "max_files": max_files,
                "preview_limit": preview_limit,
                "diff_limit": diff_limit,
            },
            "allow_noop": allow_noop,
            "allow_truncated_review": allow_truncated_review,
            "allow_dirty_affected": allow_dirty_affected,
            "allow_new_parse_errors": allow_new_parse_errors,
            "candidate_count": len(matches),
            "changed_candidate_count": changed_candidate_count,
            "no_op_count": len(matches) - changed_candidate_count,
            "affected_file_count": len(files),
            "changed_file_count": sum(item.original != item.postimage for item in files),
            "files": file_payloads,
            "edit_manifest": edit_manifest,
            "dirty_affected_paths": dirty_affected_paths,
            "syntax_validation": {
                "parser": "ast-grep",
                "checked_file_count": sum(bool(item["checked"]) for item in syntax_evidence),
                "unchecked_file_count": sum(not bool(item["checked"]) for item in syntax_evidence),
                "new_diagnostic_count": new_parse_error_count,
                "valid": new_parse_error_count == 0,
            },
            "preview": preview[:preview_limit],
            "preview_returned": min(len(preview), preview_limit),
            "preview_total": len(preview),
            "preview_truncated": preview_truncated,
            "diff": full_diff[:diff_limit],
            "diff_returned_chars": min(len(full_diff), diff_limit),
            "diff_total_chars": len(full_diff),
            "diff_truncated": diff_truncated,
            "review_complete": review_complete,
            "applicable": applicable,
            "applicability_reason": applicability_reason,
            "warnings": warnings,
            "next_actions": {
                "list_edit_ids": "jq -r '(.plan // .).edit_manifest[].edit_id' PLAN.json",
                "refine": "Repeat --edit-id EDIT_ID for every selected edit.",
                "verify": "Run xray replace verify with this complete plan and an independently copied digest.",
                "apply": "Apply only after verify reports ready_to_apply=true and external approval is satisfied.",
            },
        }
        plan["plan_digest"] = self._sha256(self._canonical_json(self._plan_digest_payload(plan)))
        return PreparedReplacement(plan=plan, files=files, matches=tuple(matches))

    def plan_replacement(
        self,
        *,
        pattern: str | None = None,
        replacement: str | None = None,
        rule_path: str | None = None,
        lang: str | None = None,
        paths: Sequence[str] | None = None,
        globs: Sequence[str] | None = None,
        max_matches: int = DEFAULT_REPLACEMENT_MAX_MATCHES,
        max_files: int = DEFAULT_REPLACEMENT_MAX_FILES,
        allow_noop: bool = False,
        allow_truncated_review: bool = False,
        allow_dirty_affected: bool = False,
        allow_new_parse_errors: bool = False,
        preview_limit: int = DEFAULT_REPLACEMENT_PREVIEW_LIMIT,
        diff_limit: int = DEFAULT_REPLACEMENT_DIFF_LIMIT,
    ) -> dict[str, Any]:
        """Return an exact, bounded, non-mutating replacement plan."""
        return self._build_replacement_plan(
            pattern=pattern,
            replacement=replacement,
            rule_path=rule_path,
            lang=lang,
            paths=paths,
            globs=globs,
            max_matches=max_matches,
            max_files=max_files,
            allow_noop=allow_noop,
            allow_truncated_review=allow_truncated_review,
            allow_dirty_affected=allow_dirty_affected,
            allow_new_parse_errors=allow_new_parse_errors,
            preview_limit=preview_limit,
            diff_limit=diff_limit,
        ).plan

    def refine_replacement(self, plan: Mapping[str, Any], *, edit_ids: Sequence[str]) -> dict[str, Any]:
        """Recompute a reviewed plan and select stable edit identifiers without writing."""
        self._validate_replacement_plan_digest(plan)
        query, bounds, kwargs = self._replacement_plan_inputs(plan)
        return self._build_replacement_plan(
            **kwargs,
            paths=query.get("paths"),
            globs=query.get("globs"),
            max_matches=bounds.get("max_matches"),
            max_files=bounds.get("max_files"),
            allow_noop=bool(plan.get("allow_noop", False)),
            allow_truncated_review=bool(plan.get("allow_truncated_review", False)),
            allow_dirty_affected=bool(plan.get("allow_dirty_affected", False)),
            allow_new_parse_errors=bool(plan.get("allow_new_parse_errors", False)),
            preview_limit=int(bounds.get("preview_limit", DEFAULT_REPLACEMENT_PREVIEW_LIMIT)),
            diff_limit=int(bounds.get("diff_limit", DEFAULT_REPLACEMENT_DIFF_LIMIT)),
            selected_edit_ids=edit_ids,
        ).plan

    @staticmethod
    def _write_staged_file(item: PreparedReplacementFile, content: bytes) -> Path:
        """Write and fsync a same-directory temporary file with the target mode."""
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("wb", dir=item.path.parent, prefix=".xray-stage-", delete=False) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
                temporary_path = Path(stream.name)
            os.chmod(temporary_path, stat.S_IMODE(item.path.stat().st_mode))
            return temporary_path
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise

    def _apply_prepared_replacement(self, prepared: PreparedReplacement) -> dict[str, Any]:
        """Stage, verify, apply, and if necessary roll back one complete plan."""
        changed_files = [item for item in prepared.files if item.original != item.postimage]
        planned_files = {
            str(item["path"]): item for item in prepared.plan["files"] if isinstance(item, Mapping) and "path" in item
        }
        requested_language = (
            prepared.plan["query"]["change"].get("language")
            if prepared.plan["query"]["change"]["kind"] == "pattern"
            else None
        )
        staged: dict[Path, Path] = {}
        try:
            for item in changed_files:
                current = item.path.read_bytes()
                if self._sha256(current) != self._sha256(item.original):
                    raise ReplacementApplyError(f"Source drift detected before writing '{item.relative_path}'.")
                staged[item.path] = self._write_staged_file(item, item.postimage)
                staged_bytes = staged[item.path].read_bytes()
                if self._sha256(staged_bytes) != self._sha256(item.postimage):
                    raise ReplacementApplyError(f"Staged postimage hash mismatch for '{item.relative_path}'.")
                planned_syntax = planned_files[item.relative_path]["syntax"]
                language = self._replacement_language(item.relative_path, requested_language)
                staged_syntax, _signatures = self._syntax_snapshot(staged_bytes, language)
                if staged_syntax != planned_syntax["postimage"]:
                    raise ReplacementApplyError(f"Staged syntax evidence drifted for '{item.relative_path}'.")
        except Exception:
            for temporary in staged.values():
                temporary.unlink(missing_ok=True)
            raise

        replaced: list[PreparedReplacementFile] = []
        try:
            for item in changed_files:
                if self._sha256(item.path.read_bytes()) != self._sha256(item.original):
                    raise ReplacementApplyError(f"Source drift detected after staging '{item.relative_path}'.")
            for item in changed_files:
                os.replace(staged[item.path], item.path)
                replaced.append(item)
            for item in changed_files:
                if self._sha256(item.path.read_bytes()) != self._sha256(item.postimage):
                    raise OSError(f"Postimage verification failed for '{item.relative_path}'.")
                planned_syntax = planned_files[item.relative_path]["syntax"]
                language = self._replacement_language(item.relative_path, requested_language)
                final_syntax, _signatures = self._syntax_snapshot(item.path.read_bytes(), language)
                if final_syntax != planned_syntax["postimage"]:
                    raise OSError(f"Final syntax evidence drifted for '{item.relative_path}'.")
        except Exception as exc:
            rollback_count = 0
            rollback_succeeded = True
            for item in reversed(replaced):
                rollback_stage: Path | None = None
                try:
                    rollback_stage = self._write_staged_file(item, item.original)
                    os.replace(rollback_stage, item.path)
                    rollback_count += 1
                except Exception:
                    if rollback_stage is not None:
                        rollback_stage.unlink(missing_ok=True)
                    rollback_succeeded = False
            for temporary in staged.values():
                temporary.unlink(missing_ok=True)
            raise ReplacementApplyError(
                f"Replacement apply failed: {exc}",
                rollback_count=rollback_count,
                rollback_succeeded=rollback_succeeded,
            ) from exc

        return {
            "plan_digest": prepared.plan["plan_digest"],
            "candidate_count": prepared.plan["candidate_count"],
            "applied_count": prepared.plan["changed_candidate_count"],
            "changed_count": prepared.plan["changed_candidate_count"],
            "no_op_count": prepared.plan["no_op_count"],
            "matched_file_count": prepared.plan["affected_file_count"],
            "file_count": len(changed_files),
            "files_modified": [item.relative_path for item in changed_files],
            "rollback_count": 0,
            "rollback_succeeded": True,
            "files": [
                {
                    "path": item.relative_path,
                    "preimage_sha256": self._sha256(item.original),
                    "postimage_sha256": self._sha256(item.postimage),
                }
                for item in changed_files
            ],
        }

    def _validate_replacement_plan_digest(self, plan: Mapping[str, Any]) -> str:
        """Validate the version and complete-artifact digest of a replacement plan."""
        version = plan.get("plan_version")
        if version == "xray.replace.v1":
            raise ValueError("Replacement plan xray.replace.v1 cannot attest review fields; create a new v2 plan.")
        if version != REPLACEMENT_PLAN_VERSION:
            raise ValueError(f"Unsupported replacement plan version: {version!r}.")
        stored_digest = plan.get("plan_digest")
        if not isinstance(stored_digest, str):
            raise ValueError("Replacement plan is missing plan_digest.")
        calculated_digest = self._sha256(self._canonical_json(self._plan_digest_payload(plan)))
        if calculated_digest != stored_digest:
            raise ValueError("Replacement plan digest does not match its complete review artifact.")
        return stored_digest

    @staticmethod
    def _is_legacy_v2_replacement_plan(plan: Mapping[str, Any]) -> bool:
        """Return whether a valid v2 artifact predates additive safety evidence."""
        return "syntax_validation" not in plan

    def _legacy_v2_projection(self, current_plan: Mapping[str, Any]) -> dict[str, Any]:
        """Project a current plan to the exact pre-0.11 v2 review artifact."""
        projected = json.loads(json.dumps(current_plan))
        for field in (
            "allow_dirty_affected",
            "allow_new_parse_errors",
            "dirty_affected_paths",
            "edit_manifest",
            "syntax_validation",
            "next_actions",
        ):
            projected.pop(field, None)
        for file_data in projected.get("files", []):
            if isinstance(file_data, dict):
                file_data.pop("syntax", None)
        projected["warnings"] = [
            warning
            for warning in projected.get("warnings", [])
            if not warning.startswith("Affected files already contain")
            and not warning.startswith("Replacement postimages introduce")
        ]
        projected["applicable"] = (
            bool(projected.get("candidate_count"))
            and bool(projected.get("review_complete"))
            and (int(projected.get("changed_candidate_count", 0)) > 0 or bool(projected.get("allow_noop")))
        )
        projected["applicability_reason"] = None
        if not projected.get("candidate_count"):
            projected["applicability_reason"] = "no_candidates"
        elif not projected.get("review_complete"):
            projected["applicability_reason"] = "truncated_review_not_acknowledged"
        elif not projected.get("changed_candidate_count") and not projected.get("allow_noop"):
            projected["applicability_reason"] = "noop_not_allowed"
        projected["plan_digest"] = self._sha256(self._canonical_json(self._plan_digest_payload(projected)))
        return projected

    @staticmethod
    def _replacement_plan_inputs(
        plan: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], Mapping[str, Any], dict[str, Any]]:
        """Extract validated plan inputs used for canonical recomputation."""
        query = plan.get("query")
        bounds = plan.get("bounds")
        if not isinstance(query, Mapping) or not isinstance(query.get("change"), Mapping):
            raise ValueError("Replacement plan query is invalid.")
        if not isinstance(bounds, Mapping):
            raise ValueError("Replacement plan bounds are invalid.")
        change = query["change"]
        kind = change.get("kind")
        if kind == "pattern":
            kwargs = {
                "pattern": change.get("pattern"),
                "replacement": change.get("replacement"),
                "lang": change.get("language"),
            }
        elif kind == "rule":
            kwargs = {"rule_path": change.get("rule_path")}
        else:
            raise ValueError("Replacement plan change kind is invalid.")
        return query, bounds, kwargs

    def _verify_replacement_plan(
        self, plan: Mapping[str, Any], *, expected_digest: str
    ) -> tuple[PreparedReplacement, bool]:
        """Recompute every non-mutating apply guard for a serialized plan."""
        stored_digest = self._validate_replacement_plan_digest(plan)
        if expected_digest != stored_digest:
            raise ValueError("expected_digest does not confirm this replacement plan.")
        if Path(str(plan.get("root_path", ""))).resolve() != self.root_path:
            raise ValueError("Replacement plan root does not match the requested repository root.")
        query, bounds, kwargs = self._replacement_plan_inputs(plan)
        prepared = self._build_replacement_plan(
            **kwargs,
            paths=query.get("paths"),
            globs=query.get("globs"),
            max_matches=bounds.get("max_matches"),
            max_files=bounds.get("max_files"),
            allow_noop=bool(plan.get("allow_noop", False)),
            allow_truncated_review=bool(plan.get("allow_truncated_review", False)),
            allow_dirty_affected=bool(plan.get("allow_dirty_affected", False)),
            allow_new_parse_errors=bool(plan.get("allow_new_parse_errors", False)),
            preview_limit=int(bounds.get("preview_limit", DEFAULT_REPLACEMENT_PREVIEW_LIMIT)),
            diff_limit=int(bounds.get("diff_limit", DEFAULT_REPLACEMENT_DIFF_LIMIT)),
            selected_edit_ids=query.get("selected_edit_ids"),
        )
        legacy_v2 = self._is_legacy_v2_replacement_plan(plan)
        comparable_plan = self._legacy_v2_projection(prepared.plan) if legacy_v2 else prepared.plan
        if comparable_plan != dict(plan):
            raise ReplacementApplyError("Replacement plan no longer matches the repository source snapshot.")
        if not prepared.plan["applicable"]:
            if prepared.plan["applicability_reason"] == "noop_not_allowed":
                raise ValueError("Replacement plan contains no byte-changing edits; allow_noop was not recorded.")
            raise ValueError(f"Replacement plan is not applicable: {prepared.plan['applicability_reason']}.")
        return prepared, legacy_v2

    def verify_replacement(self, plan: Mapping[str, Any], *, expected_digest: str) -> dict[str, Any]:
        """Perform every non-mutating apply guard and summarize readiness."""
        prepared, legacy_v2 = self._verify_replacement_plan(plan, expected_digest=expected_digest)
        return {
            "verified": True,
            "ready_to_apply": True,
            "plan_digest": expected_digest,
            "plan_version": plan["plan_version"],
            "legacy_v2": legacy_v2,
            "candidate_count": prepared.plan["candidate_count"],
            "affected_file_count": prepared.plan["affected_file_count"],
            "selected_edit_ids": [item["edit_id"] for item in prepared.plan["edit_manifest"]],
            "syntax_validation": prepared.plan["syntax_validation"],
            "dirty_affected_paths": prepared.plan["dirty_affected_paths"],
        }

    def apply_replacement(self, plan: Mapping[str, Any], *, expected_digest: str) -> dict[str, Any]:
        """Recompute and apply a serialized plan only when every guard still matches."""
        prepared, legacy_v2 = self._verify_replacement_plan(plan, expected_digest=expected_digest)
        result = self._apply_prepared_replacement(prepared)
        result["plan_digest"] = expected_digest
        result["legacy_v2"] = legacy_v2
        result["syntax_validation"] = prepared.plan["syntax_validation"]
        return result

    def rewrite_pattern(self, pattern: str, replacement: str, lang: str | None = None) -> dict[str, Any]:
        """Apply the legacy all-match rewrite through the staged writer."""
        prepared = self._build_replacement_plan(
            pattern=pattern,
            replacement=replacement,
            lang=lang,
            max_matches=None,
            max_files=None,
            allow_noop=True,
            allow_dirty_affected=True,
            allow_new_parse_errors=True,
            preview_limit=0,
        )
        applied = self._apply_prepared_replacement(prepared)
        return {
            "matches": list(prepared.matches),
            "match_count": applied["candidate_count"],
            "changed_match_count": applied["changed_count"],
            "no_op_count": applied["no_op_count"],
            "matched_file_count": applied["matched_file_count"],
            "matched_files": [str(item.path) for item in prepared.files],
            "files_modified": [str(self.root_path / path) for path in applied["files_modified"]],
            "file_count": applied["file_count"],
            "rollback_count": applied["rollback_count"],
            "rollback_succeeded": applied["rollback_succeeded"],
        }

    def scan_rules(
        self,
        rule_path: str,
        fix: bool = False,
        *,
        paths: Sequence[str] | None = None,
        globs: Sequence[str] | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        """Run bounded rule diagnostics or legacy all-match staged fixes."""
        if not fix:
            matches, _relative_rule = self._scan_rule_matches(
                rule_path,
                paths=paths,
                globs=globs,
                max_results=max_results,
            )
            return matches
        prepared = self._build_replacement_plan(
            rule_path=rule_path,
            paths=paths,
            globs=globs,
            max_matches=None,
            max_files=None,
            allow_noop=True,
            preview_limit=0,
        )
        self.last_mutation_summary = self._apply_prepared_replacement(prepared)
        return list(prepared.matches)

    def check_rules(
        self,
        rule_path: str,
        *,
        paths: Sequence[str] | None = None,
        globs: Sequence[str] | None = None,
        max_results: int = 100,
    ) -> dict[str, Any]:
        """Validate and scan one contained ast-grep rule source without mutation."""
        matches, relative_rule = self._scan_rule_matches(rule_path, paths=paths, globs=globs, max_results=max_results)
        return {
            "rule_path": relative_rule,
            "valid": True,
            "matches": matches,
            "returned": len(matches),
            "total_exact": self.last_result_total_exact,
            "truncated": not self.last_result_total_exact,
        }

    def explain_rules(self, rule_path: str, *, source_limit: int = 32_000) -> dict[str, Any]:
        """Return bounded source plus upstream validation and inspection evidence."""
        if source_limit < 1:
            raise ValueError("source_limit must be 1 or greater.")
        rule_args, relative_rule = self._rule_arguments(rule_path)
        resolved = self._resolve_repo_path(relative_rule)
        source_path = resolved
        if resolved.is_dir():
            source_path = next(
                path for path in (resolved / "sgconfig.yml", resolved / "sgconfig.yaml") if path.is_file()
            )
        source = source_path.read_text(encoding="utf-8")
        result = run_ast_grep(
            ["scan", *rule_args, "--inspect=summary", "--json=compact", "--max-results", "1", str(self.root_path)],
            cwd=self.root_path,
        )
        return {
            "rule_path": relative_rule,
            "valid": True,
            "source": source[:source_limit],
            "source_chars": min(len(source), source_limit),
            "source_total_chars": len(source),
            "source_truncated": len(source) > source_limit,
            "inspection": result.stderr.strip(),
        }

    def test_rules(
        self,
        *,
        test_dir: str = ".",
        config_path: str | None = None,
    ) -> dict[str, Any]:
        """Run contained ast-grep rule tests without snapshots or interactive behavior."""
        resolved_test_dir = self._resolve_repo_path(test_dir)
        if not resolved_test_dir.is_dir():
            raise ValueError("test_dir must be a directory.")
        args = [
            "test",
            "--test-dir",
            str(resolved_test_dir),
            "--skip-snapshot-tests",
            "--color",
            "never",
        ]
        relative_config: str | None = None
        if config_path is not None:
            resolved_config = self._resolve_repo_path(config_path, require_file=True)
            relative_config = resolved_config.relative_to(self.root_path).as_posix()
            args.extend(["--config", str(resolved_config)])
        result = run_ast_grep(args, cwd=self.root_path)
        return {
            "ok": True,
            "test_dir": (
                "." if resolved_test_dir == self.root_path else resolved_test_dir.relative_to(self.root_path).as_posix()
            ),
            "config_path": relative_config,
            "output": result.stdout.strip(),
            "diagnostics": result.stderr.strip(),
        }

    def capabilities(self, *, include_repository: bool = True) -> dict[str, Any]:
        """Report stable product contracts and effective local dependency health."""

        def version(command: str) -> str | None:
            executable = shutil.which(command)
            if executable is None:
                return None
            try:
                completed = subprocess.run(
                    [executable, "--version"], capture_output=True, check=False, text=True, timeout=GIT_TIMEOUT_SECONDS
                )
            except (OSError, subprocess.TimeoutExpired):
                return None
            output = (completed.stdout or completed.stderr).strip().splitlines()
            return output[0] if completed.returncode == 0 and output else None

        ast_grep_version = version("ast-grep")
        try:
            mcp_cache_limit = max(1, int(os.environ.get("XRAY_MCP_INDEXER_CACHE_LIMIT", "32")))
        except ValueError:
            mcp_cache_limit = 32
        cli_read_only = [
            "explore",
            "find",
            "interface",
            "read-symbol",
            "symbol-at",
            "impact",
            "search",
            "scan",
            "imports",
            "exports",
            "rules-check",
            "rules-explain",
            "rules-test",
            "replace-plan",
            "replace-refine",
            "replace-verify",
            "capabilities",
        ]
        cli_mutating = ["rewrite", "scan-fix", "replace-apply"]
        mcp_read_only = [
            "explore_repo",
            "find_symbol",
            "read_interface",
            "read_interface_structured",
            "read_symbol",
            "symbol_at",
            "what_breaks",
            "search_pattern",
            "plan_replacement",
            "refine_replacement",
            "verify_replacement",
            "scan_rules",
            "check_rules",
            "explain_rules",
            "test_rules",
            "xray_capabilities",
            "file_imports",
            "file_exports",
        ]
        mcp_mutating = ["apply_replacement", "apply_rule_fixes", "rewrite_pattern"]
        payload: dict[str, Any] = {
            "product": {"name": "xray-cli", "version": __version__},
            "schemas": ["xray.cli.v1", "xray.cli.v2", "xray.cli.v3"],
            "schema_contracts": {
                "cli_default": "xray.cli.v3",
                "cli_legacy": ["xray.cli.v2"],
                "cli_full": "xray.cli.v1",
                "replacement_plan": REPLACEMENT_PLAN_VERSION,
                "mcp_default": "v3",
                "mcp_legacy": ["v2"],
            },
            "replacement_plan_versions": [REPLACEMENT_PLAN_VERSION],
            "languages": sorted(set(LANGUAGE_MAP.values())),
            "extensions": dict(sorted(LANGUAGE_MAP.items())),
            "operations": {
                "read_only": cli_read_only,
                "destructive": cli_mutating,
            },
            "bounds": {
                "inventory_files": MAX_INVENTORY_FILES,
                "inventory_symbols": MAX_INVENTORY_SYMBOLS,
                "impact_raw_results": MAX_IMPACT_RAW_RESULTS,
                "replacement_matches": DEFAULT_REPLACEMENT_MAX_MATCHES,
                "replacement_files": DEFAULT_REPLACEMENT_MAX_FILES,
                "ast_grep_timeout_seconds": get_ast_grep_timeout(),
                "ast_grep_output_chars": get_ast_grep_output_limit(),
                "ripgrep_output_chars": MAX_RG_OUTPUT_CHARS,
                "interface_file_bytes": MAX_SKELETON_FILE_BYTES,
                "inventory_source_bytes": MAX_INVENTORY_SOURCE_BYTES,
                "source_argument_chars": MAX_SOURCE_ARGUMENT_CHARS,
                "replacement_file_bytes": MAX_REPLACEMENT_FILE_BYTES,
                "replacement_total_bytes": MAX_REPLACEMENT_TOTAL_BYTES,
            },
            "surfaces": {
                "cli": {
                    "operations": {"read_only": cli_read_only, "mutating": cli_mutating},
                    "aliases": {"map": "explore", "doctor": "capabilities"},
                    "administrative": ["skill-install"],
                    "defaults": {
                        "explore": {"max_depth": 2, "max_entries": 5000, "max_symbols_per_file": 5},
                        "find": {"limit": 10, "min_score": 60},
                        "interface": {"limit": 50, "member_depth": 1, "max_members": 20},
                        "read_symbol": {"context_lines": 0, "max_lines": 200, "max_bytes": 65536},
                        "impact": {"limit": 50, "context_lines": 2},
                        "structural_page": {"limit": 50},
                    },
                    "maximums": {
                        "explore": {"max_entries": None},
                        "find": {"indexed_symbols": MAX_INVENTORY_SYMBOLS, "limit": None},
                        "interface": {"file_bytes": MAX_SKELETON_FILE_BYTES, "limit": None},
                        "read_symbol": {"max_lines": None, "max_bytes": None, "symbol_json_chars": 1024 * 1024},
                        "impact": {"raw_results": MAX_IMPACT_RAW_RESULTS, "limit": None},
                        "structural_page": {"limit": None, "subprocess_output_chars": get_ast_grep_output_limit()},
                    },
                },
                "mcp": {
                    "operations": {"read_only": mcp_read_only, "mutating": mcp_mutating},
                    "defaults": {
                        "explore_repo": {"max_depth": 2, "max_entries": 5000, "max_symbols_per_file": 5},
                        "find_symbol": {"limit": 10, "min_score": 60},
                        "read_interface_structured": {
                            "limit": 50,
                            "member_depth": 1,
                            "max_members": 20,
                            "schema": "v3",
                        },
                        "read_symbol": {"context_lines": 0, "max_lines": 200, "max_bytes": 65536},
                        "what_breaks": {"limit": 50, "detail": "compact", "schema": "v3"},
                        "structural_page": {"limit": 50},
                        "tool_search": {"limit": 10, "maximum": 50},
                    },
                    "maximums": {
                        "explore_repo": {"max_entries": None},
                        "find_symbol": {"indexed_symbols": MAX_INVENTORY_SYMBOLS, "limit": None},
                        "read_interface_structured": {"file_bytes": MAX_SKELETON_FILE_BYTES, "limit": None},
                        "read_symbol": {"max_lines": None, "max_bytes": None},
                        "what_breaks": {"raw_results": MAX_IMPACT_RAW_RESULTS, "limit": None},
                        "structural_page": {"limit": None, "subprocess_output_chars": get_ast_grep_output_limit()},
                        "tool_search": {"limit": 50},
                    },
                    "cache": {
                        "indexers": {"effective_limit": mcp_cache_limit, "environment": "XRAY_MCP_INDEXER_CACHE_LIMIT"}
                    },
                    "discovery_tools": ["search_tools", "call_tool"],
                    "resources": ["xray://workflow", "skill://xray-progressive-discovery/SKILL.md"],
                    "resource_templates": ["skill://xray-progressive-discovery/{path*}"],
                    "prompts": ["xray_discovery_plan"],
                },
            },
            "mutation_classes": {
                "guarded": {
                    "cli": ["replace-apply"],
                    "mcp": ["apply_replacement", "apply_rule_fixes"],
                },
                "direct_legacy": {
                    "cli": ["rewrite", "scan-fix"],
                    "mcp": ["rewrite_pattern"],
                },
                "administrative": {"cli": ["skill-install"], "mcp": []},
            },
            "cache": {
                "directory": str(self.cache_dir) if self.cache_dir is not None else None,
                "files": [CACHE_FILENAME, INVENTORY_CACHE_FILENAME],
                "snapshot_bound": True,
                "disk_max_age_seconds": CACHE_MAX_AGE_SECONDS,
                "disk_max_bytes": CACHE_MAX_BYTES,
                "memory_symbol_entries": MAX_SYMBOL_CACHE_ENTRIES,
            },
            "workflow_resources": [
                "xray://workflow",
                "xray_discovery_plan",
                "skill://xray-progressive-discovery/SKILL.md",
            ],
            "dependencies": {
                "ast_grep": {"required": True, "available": ast_grep_version is not None, "version": ast_grep_version},
                "git": {"required": False, "available": shutil.which("git") is not None, "version": version("git")},
                "ripgrep": {"required": False, "available": shutil.which("rg") is not None, "version": version("rg")},
            },
            "healthy": ast_grep_version is not None,
        }
        if include_repository:
            payload["repository"] = {
                "root_path": str(self.root_path),
                "snapshot": self.repository_snapshot_fingerprint(),
            }
        return payload

    def file_outline_items(self, file_path: str, item: str) -> list[dict[str, Any]]:
        """Return imports or exports reported by ast-grep outline for one repository file."""
        if item not in {"imports", "exports"}:
            raise ValueError("Outline item must be 'imports' or 'exports'.")
        resolved_file = self._resolve_repo_path(file_path, require_file=True)
        result = run_ast_grep(["outline", f"--items={item}", "--json=compact", str(resolved_file)])
        return parse_json_array(result.stdout)

    def explore_repo(
        self,
        max_depth: int | None = None,
        include_symbols: bool = False,
        focus_dirs: list[str] | None = None,
        max_symbols_per_file: int = 5,
        symbol_types: list[str] | None = None,
        max_entries: int = 5000,
        use_default_exclusions: bool = True,
        include_root_context: bool = True,
    ) -> str:
        """
        Build a visual file tree with optional symbol skeletons.

        Args:
            max_depth: Limit directory traversal depth
            include_symbols: Include symbol skeletons in output
            focus_dirs: Only include these top-level directories
            max_symbols_per_file: Max symbols to show per file
            symbol_types: Optional ast-grep outline symbol types to include

        Returns:
            Formatted tree string
        """
        return self.explore_repo_data(
            max_depth=max_depth,
            include_symbols=include_symbols,
            focus_dirs=focus_dirs,
            include_root_context=include_root_context,
            max_symbols_per_file=max_symbols_per_file,
            symbol_types=symbol_types,
            max_entries=max_entries,
            use_default_exclusions=use_default_exclusions,
        )["tree_text"]

    def explore_repo_data(
        self,
        max_depth: int | None = None,
        include_symbols: bool = False,
        focus_dirs: list[str] | None = None,
        max_symbols_per_file: int = 5,
        symbol_types: list[str] | None = None,
        max_entries: int = 5000,
        use_default_exclusions: bool = True,
        include_root_context: bool = True,
    ) -> ExploreRepoData:
        """
        Build structured repository map data for CLI and automation.

        The text tree remains available through explore_repo and structured payloads include entries for automation.
        """
        normalized_focus: list[str] = []
        for value in focus_dirs or ():
            candidate = self._resolve_repo_path(value)
            relative = "." if candidate == self.root_path else candidate.relative_to(self.root_path).as_posix()
            if relative not in normalized_focus:
                normalized_focus.append(relative)
        gitignore_patterns = self._parse_gitignore(use_default_exclusions=use_default_exclusions)
        tree_lines: list[str] = []
        entries: list[ExploreEntry] = []
        truncated = self._build_tree_recursive_enhanced(
            self.root_path,
            tree_lines,
            "",
            gitignore_patterns,
            current_depth=0,
            max_depth=max_depth,
            include_symbols=include_symbols,
            focus_dirs=normalized_focus,
            include_root_context=include_root_context,
            max_symbols_per_file=max_symbols_per_file,
            symbol_types=symbol_types,
            is_last=True,
            entries=entries,
            max_entries=max_entries,
        )

        if include_symbols:
            self._save_cache()

        return {
            "root_path": str(self.root_path),
            "tree_text": "\n".join(tree_lines),
            "entries": entries,
            "truncated": truncated,
            "options": {
                "max_depth": max_depth,
                "include_symbols": include_symbols,
                "focus_dirs": normalized_focus,
                "include_root_context": include_root_context,
                "focus_mode": "root_context" if include_root_context else "strict",
                "max_symbols_per_file": max_symbols_per_file,
                "symbol_types": symbol_types or [],
                "max_entries": max_entries,
                "use_default_exclusions": use_default_exclusions,
            },
        }

    def _parse_gitignore(self, *, use_default_exclusions: bool = True) -> IgnorePolicy:
        """Compile root and nested .gitignore files with directory-relative semantics."""
        rule_sets: list[IgnoreRuleSet] = []
        try:
            ignore_files = sorted(
                (path for path in self.root_path.rglob(".gitignore") if path.is_file() and not path.is_symlink()),
                key=lambda path: (len(path.relative_to(self.root_path).parts), path.as_posix()),
            )
        except OSError:
            ignore_files = []
        for ignore_file in ignore_files:
            try:
                lines = ignore_file.read_text(encoding="utf-8").splitlines()
                rule_sets.append(IgnoreRuleSet(ignore_file.parent, GitIgnoreSpec.from_lines(lines)))
            except (OSError, UnicodeError, ValueError) as exc:
                self.last_warnings.append(f"Could not parse {ignore_file.relative_to(self.root_path)}: {exc}")
        return IgnorePolicy(tuple(rule_sets), use_default_exclusions=use_default_exclusions)

    def _should_exclude(self, path: Path, gitignore_patterns: IgnorePolicy) -> bool:
        """Return whether built-in policy or ordered Git-ignore rules exclude a path."""

        if path != self.root_path and not self._is_inside_root(path):
            return True

        # Avoid following symlinked directories, which can escape the root or cycle.
        if path.is_symlink() and path.is_dir():
            return True
        if path == self.root_path:
            return False

        relative = path.relative_to(self.root_path).as_posix()
        match_path = f"{relative}/" if path.is_dir() else relative
        if gitignore_patterns.use_default_exclusions:
            default_result = DEFAULT_EXCLUSION_SPEC.check_file(match_path)
            if default_result.include is True:
                return True

        ignored = False
        for rule_set in gitignore_patterns.rules:
            try:
                rule_relative = path.relative_to(rule_set.base).as_posix()
            except ValueError:
                continue
            rule_match_path = f"{rule_relative}/" if path.is_dir() else rule_relative
            result = rule_set.spec.check_file(rule_match_path)
            if result.include is not None:
                ignored = result.include
        return ignored

    def _is_inside_root(self, path: Path) -> bool:
        """Return whether a path resolves inside the repository root."""
        try:
            path.resolve().relative_to(self.root_path)
            return True
        except ValueError:
            return False

    def _focus_relationship(self, path: Path, focus_dirs: list[str] | None) -> tuple[bool, int | None]:
        """Return whether a path is a focus ancestor and its nearest descendant depth."""
        if not focus_dirs:
            return False, None
        relative = "." if path == self.root_path else path.relative_to(self.root_path).as_posix()
        relative_parts = () if relative == "." else tuple(relative.split("/"))
        ancestor = False
        descendant_depths: list[int] = []
        for focus in focus_dirs:
            focus_parts = () if focus == "." else tuple(focus.split("/"))
            if relative_parts[: len(focus_parts)] == focus_parts:
                descendant_depths.append(len(relative_parts) - len(focus_parts))
            elif focus_parts[: len(relative_parts)] == relative_parts:
                ancestor = True
        return ancestor, min(descendant_depths) if descendant_depths else None

    def _should_include_dir(self, path: Path, focus_dirs: list[str] | None) -> bool:
        """Retain focused descendants and their complete repository ancestor chain."""
        if not focus_dirs:
            return True
        ancestor, descendant_depth = self._focus_relationship(path, focus_dirs)
        return ancestor or descendant_depth is not None

    def _should_include_focused_path(
        self, path: Path, focus_dirs: list[str] | None, include_root_context: bool
    ) -> bool:
        """Include root context files plus selected files and descendant subtrees."""
        if not focus_dirs or path == self.root_path:
            return True
        if path.is_dir():
            return self._should_include_dir(path, focus_dirs)
        relative = path.relative_to(self.root_path).as_posix()
        _ancestor, descendant_depth = self._focus_relationship(path, focus_dirs)
        if descendant_depth is not None:
            return True
        return include_root_context and "/" not in relative

    def _within_explore_depth(
        self,
        path: Path,
        *,
        current_depth: int,
        max_depth: int | None,
        focus_dirs: list[str] | None,
        include_root_context: bool,
    ) -> bool:
        """Apply absolute depth normally and focus-relative depth for focused maps."""
        if max_depth is None:
            return True
        if not focus_dirs:
            return current_depth <= max_depth
        ancestor, descendant_depth = self._focus_relationship(path, focus_dirs)
        if ancestor:
            return True
        if descendant_depth is not None:
            return descendant_depth <= max_depth
        if include_root_context and path.is_file() and path.parent == self.root_path:
            return True
        return False

    def _get_file_symbol_data(
        self, file_path: Path, max_symbols: int, symbol_types: list[str] | None = None
    ) -> list[ExploreSymbol]:
        """Return structured symbol skeleton data for a source file."""
        cache_key = self._get_skeleton_cache_key(file_path, symbol_types)
        if self._get_cached_symbols(cache_key) is None:
            self._get_file_skeleton_enhanced(file_path, max_symbols, symbol_types)

        symbols = self._get_cached_symbols(cache_key) or []
        structured_symbols: list[ExploreSymbol] = []
        for symbol in symbols[:max_symbols]:
            signature = symbol.get("signature", "")
            structured_symbols.append(
                {
                    "name": symbol.get("name") or self._extract_symbol_name(signature) or signature,
                    "type": symbol.get("type") or self._infer_symbol_type(signature),
                    "signature": signature,
                    "doc": symbol.get("doc", ""),
                }
            )

        if len(symbols) > max_symbols:
            structured_symbols.append(
                {
                    "name": "...",
                    "type": "truncated",
                    "signature": f"... and {len(symbols) - max_symbols} more",
                    "doc": "",
                }
            )

        return structured_symbols

    def _infer_symbol_type(self, signature: str) -> str:
        """Infer a symbol type from a skeleton signature."""
        if signature.startswith("class "):
            return "class"
        if signature.startswith(("def ", "async def ", "function ", "const ", "let ", "var ")):
            return "function"
        if signature.startswith("func "):
            return "function"
        if signature.startswith("type ") and " struct" in signature:
            return "struct"
        if signature.startswith("type ") and " interface" in signature:
            return "interface"
        return "symbol"

    def _build_tree_recursive_enhanced(
        self,
        path: Path,
        tree_lines: list[str],
        prefix: str,
        gitignore_patterns: IgnorePolicy,
        current_depth: int,
        max_depth: int | None,
        include_symbols: bool,
        focus_dirs: list[str] | None,
        include_root_context: bool,
        max_symbols_per_file: int,
        symbol_types: list[str] | None,
        is_last: bool = False,
        entries: list[ExploreEntry] | None = None,
        max_entries: int = 5000,
    ) -> bool:
        """Recursively build the tree representation with enhanced features."""
        if entries is not None and len(entries) >= max_entries:
            return True
        if self._should_exclude(path, gitignore_patterns):
            return False

        if not self._should_include_focused_path(path, focus_dirs, include_root_context):
            return False

        if not self._within_explore_depth(
            path,
            current_depth=current_depth,
            max_depth=max_depth,
            focus_dirs=focus_dirs,
            include_root_context=include_root_context,
        ):
            return False

        if path.is_dir() and not self._should_include_dir(path, focus_dirs):
            return False

        if entries is not None:
            relative_path = "." if path == self.root_path else path.relative_to(self.root_path).as_posix()
            entry: ExploreEntry = {
                "path": relative_path,
                "abs_path": str(path),
                "name": path.name if path != self.root_path else self.root_path.name,
                "kind": "directory" if path.is_dir() else "file",
                "depth": current_depth,
            }
            language = LANGUAGE_MAP.get(path.suffix.lower()) if path.is_file() else None
            if language:
                entry["language"] = language
            if path.is_file() and include_symbols and language:
                entry["symbols"] = self._get_file_symbol_data(path, max_symbols_per_file, symbol_types)
            entries.append(entry)

        # Add current item
        name = path.name if path != self.root_path else str(path)
        connector = "└── " if is_last else "├── "

        # For files, add skeleton if requested
        if path.is_file() and include_symbols and path.suffix.lower() in LANGUAGE_MAP:
            skeleton = self._get_file_skeleton_enhanced(path, max_symbols_per_file, symbol_types)
            if skeleton:
                # Format with indented skeleton
                if path == self.root_path:
                    tree_lines.append(name)
                else:
                    tree_lines.append(prefix + connector + name)

                # Add skeleton lines
                for i, skel_line in enumerate(skeleton):
                    is_last_skel = i == len(skeleton) - 1
                    skel_prefix = prefix + ("    " if is_last else "│   ")
                    skel_connector = "└── " if is_last_skel else "├── "
                    tree_lines.append(skel_prefix + skel_connector + skel_line)
            # No skeleton, just show filename
            elif path == self.root_path:
                tree_lines.append(name)
            else:
                tree_lines.append(prefix + connector + name)
        # Directory or file without symbols
        elif path == self.root_path:
            tree_lines.append(name)
        else:
            tree_lines.append(prefix + connector + name)

        # Only recurse into directories
        if path.is_dir():
            # Get children and sort them
            try:
                children = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
                # Filter out excluded items
                children = [c for c in children if not self._should_exclude(c, gitignore_patterns)]

                for i, child in enumerate(children):
                    is_last_child = i == len(children) - 1
                    extension = "    " if is_last else "│   "
                    new_prefix = prefix + extension if path != self.root_path else ""

                    truncated = self._build_tree_recursive_enhanced(
                        child,
                        tree_lines,
                        new_prefix,
                        gitignore_patterns,
                        current_depth + 1,
                        max_depth,
                        include_symbols,
                        focus_dirs,
                        include_root_context,
                        max_symbols_per_file,
                        symbol_types,
                        is_last_child,
                        entries,
                        max_entries,
                    )
                    if truncated:
                        return True
            except PermissionError:
                pass
        return False

    @staticmethod
    def _python_visibility(name: str) -> str:
        """Return conventional Python public/private visibility."""
        return "private" if name.startswith("_") and not (name.startswith("__") and name.endswith("__")) else "public"

    @classmethod
    def _inventory_visibility(cls, name: str, language: str, is_public: Any, is_exported: Any) -> str:
        """Normalize language-specific visibility when ast-grep does not supply it."""
        if language == "python":
            return cls._python_visibility(name)
        if language == "go":
            return "public" if name[:1].isupper() else "private"
        if language in {"javascript", "typescript"} and name.startswith("#"):
            return "private"
        if is_public is True:
            return "public"
        if is_public is False:
            return "private"
        if language in {"javascript", "typescript"} and is_exported is True:
            return "public"
        return "unknown"

    @staticmethod
    def _python_function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        signature = f"{prefix} {node.name}({ast.unparse(node.args)})"
        if node.returns is not None:
            signature += f" -> {ast.unparse(node.returns)}"
        return f"{signature}:"

    @staticmethod
    def _python_class_signature(node: ast.ClassDef) -> str:
        arguments = [ast.unparse(base) for base in node.bases]
        arguments.extend(ast.unparse(keyword) for keyword in node.keywords)
        suffix = f"({', '.join(arguments)})" if arguments else ""
        return f"class {node.name}{suffix}:"

    def _python_interface_symbol(self, node: ast.AST, *, role: str) -> dict[str, Any] | None:
        """Project one Python definition without retaining implementation bodies."""
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
            signature = self._python_function_signature(node)
            symbol_type = "method" if role == "member" else "function"
            members: list[dict[str, Any]] = []
        elif isinstance(node, ast.ClassDef):
            name = node.name
            signature = self._python_class_signature(node)
            symbol_type = "class"
            members = [
                symbol
                for child in node.body
                if (symbol := self._python_interface_symbol(child, role="member")) is not None
            ]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            signature = f"{name}: {ast.unparse(node.annotation)}"
            symbol_type = "field"
            members = []
        else:
            return None
        return {
            "name": name,
            "type": symbol_type,
            "signature": signature,
            "start_line": int(getattr(node, "lineno", 1)),
            "end_line": int(getattr(node, "end_lineno", getattr(node, "lineno", 1))),
            "visibility": self._python_visibility(name),
            "role": role,
            "documentation": ast.get_docstring(node, clean=False)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            else None,
            "members": members,
        }

    def _python_interface(self, target_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
        """Parse a Python file into ordered top-level contracts and direct class members."""
        try:
            source = target_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(target_path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise InterfaceReadError("parse_error", f"Could not parse Python interface: {exc}") from exc
        symbols = [
            symbol for node in tree.body if (symbol := self._python_interface_symbol(node, role="item")) is not None
        ]
        return symbols, []

    def _outline_interface_symbol(self, item: Mapping[str, Any], warnings: list[str]) -> dict[str, Any] | None:
        """Preserve upstream outline hierarchy for non-Python languages."""
        name = item.get("name")
        if not isinstance(name, str) or not name:
            warnings.append("An upstream outline item had no name and was omitted.")
            return None
        range_data = item.get("range")
        start = range_data.get("start", {}) if isinstance(range_data, Mapping) else {}
        end = range_data.get("end", {}) if isinstance(range_data, Mapping) else {}
        signature = item.get("signature")
        if not isinstance(signature, str) or not signature:
            signature = name
            warnings.append(f"Signature for '{name}' was incomplete in ast-grep outline output.")
        members = item.get("members")
        structured_members = (
            [
                structured
                for member in members
                if isinstance(members, list) and isinstance(member, Mapping)
                if (structured := self._outline_interface_symbol(member, warnings)) is not None
            ]
            if isinstance(members, list)
            else []
        )
        is_public = item.get("isPublic")
        return {
            "name": name,
            "type": str(item.get("symbolType") or "symbol"),
            "signature": signature,
            "start_line": self._normalize_ast_grep_line(start.get("line") if isinstance(start, Mapping) else None),
            "end_line": self._normalize_ast_grep_line(end.get("line") if isinstance(end, Mapping) else None),
            "visibility": "public" if is_public is True else "private" if is_public is False else "unknown",
            "role": str(item.get("role") or "item"),
            "documentation": None,
            "members": structured_members,
        }

    def _outline_interface(self, target_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
        warnings: list[str] = []
        try:
            result = run_ast_grep(["outline", "--json=compact", "--view=expanded", str(target_path)])
            outlines = parse_json_array(result.stdout)
        except (AstGrepCommandError, AstGrepNotFoundError, json.JSONDecodeError, ValueError) as exc:
            raise InterfaceReadError("upstream_error", f"ast-grep interface extraction failed: {exc}") from exc
        symbols: list[dict[str, Any]] = []
        for outline in outlines:
            items = outline.get("items")
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, Mapping):
                    structured = self._outline_interface_symbol(item, warnings)
                    if structured is not None:
                        symbols.append(structured)
        if not symbols:
            warnings.append("No interface symbols were reported for this supported file.")
        return symbols, warnings

    def read_interface_structured(
        self,
        file_path: str,
        *,
        symbol_names: Sequence[str] | None = None,
        visibility: Sequence[str] | None = None,
        symbol_types: Sequence[str] | None = None,
        member_depth: int | None = 1,
        max_symbols: int | None = 50,
        max_members: int | None = 20,
        exact_symbol: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a bounded, filterable hierarchical interface contract."""
        bounds = (("member_depth", member_depth), ("max_symbols", max_symbols), ("max_members", max_members))
        for label, value in bounds:
            if value is not None and value < 0:
                raise InterfaceReadError("invalid_bound", f"{label} must be 0 or greater.")
        try:
            target_path = self._resolve_file_inside_root(file_path)
        except (OSError, RuntimeError, ValueError) as exc:
            raise InterfaceReadError("path_outside_root", str(exc)) from exc
        if not target_path.exists() or not target_path.is_file():
            raise InterfaceReadError("not_found", f"File '{file_path}' was not found or is not a file.")
        language = LANGUAGE_MAP.get(target_path.suffix.lower())
        if language is None:
            raise InterfaceReadError("unsupported_file", f"File type '{target_path.suffix}' is not supported.")
        try:
            size = target_path.stat().st_size
        except OSError as exc:
            raise InterfaceReadError("read_error", f"Could not inspect '{file_path}': {exc}") from exc
        if size > MAX_SKELETON_FILE_BYTES:
            raise InterfaceReadError("file_too_large", f"File '{file_path}' exceeds {MAX_SKELETON_FILE_BYTES} bytes.")
        if language == "python":
            symbols, warnings = self._python_interface(target_path)
        else:
            symbols, warnings = self._outline_interface(target_path)
        if exact_symbol is not None:
            target_name = str(exact_symbol.get("name") or "")
            owner_name = str(exact_symbol.get("owner") or "").split(".")[-1]
            target_line = exact_symbol.get("start_line")
            if not target_name:
                raise InterfaceReadError("invalid_symbol", "exact_symbol.name must be non-empty.")

            def select_member(items: list[dict[str, Any]]) -> dict[str, Any] | None:
                for item in items:
                    if str(item.get("name")) == target_name and (
                        not isinstance(target_line, int) or target_line < 1 or item.get("start_line") == target_line
                    ):
                        return {**item, "members": []}
                    members = item.get("members")
                    if isinstance(members, list):
                        selected = select_member(members)
                        if selected is not None:
                            return {**item, "members": [selected]}
                return None

            candidate_items = symbols
            if owner_name:
                candidate_items = [item for item in symbols if str(item.get("name")) == owner_name]
            selected = select_member(candidate_items)
            if selected is None:
                raise InterfaceReadError(
                    "symbol_not_found", f"Exact symbol '{target_name}' was not found in interface '{file_path}'."
                )
            symbols = [selected]
        names = {value for value in symbol_names or ()}
        visibilities = {value.lower() for value in visibility or ()}
        types = {value.lower() for value in symbol_types or ()}
        if visibilities - {"public", "private", "unknown"}:
            raise InterfaceReadError("invalid_filter", "visibility filters must be public, private, or unknown.")
        symbols = [
            symbol
            for symbol in symbols
            if (not names or str(symbol.get("name")) in names)
            and (not visibilities or str(symbol.get("visibility", "unknown")).lower() in visibilities)
            and (not types or str(symbol.get("type", "symbol")).lower() in types)
        ]
        complete = not warnings
        total_symbols = len(symbols)
        if max_symbols is not None and len(symbols) > max_symbols:
            symbols = symbols[:max_symbols]
            complete = False
            warnings.append(f"Interface symbols truncated at {max_symbols} of {total_symbols} top-level symbols.")

        def bound_members(items: list[dict[str, Any]], depth: int) -> None:
            nonlocal complete
            for symbol in items:
                members = symbol.get("members")
                if not isinstance(members, list):
                    symbol["members"] = []
                    continue
                if member_depth is not None and depth >= member_depth:
                    if members:
                        complete = False
                        warnings.append(f"Members for '{symbol.get('name', '')}' truncated at depth {member_depth}.")
                    symbol["members"] = []
                    continue
                if max_members is not None and len(members) > max_members:
                    complete = False
                    warnings.append(
                        f"Members for '{symbol.get('name', '')}' truncated at {max_members} of {len(members)}."
                    )
                    members = members[:max_members]
                    symbol["members"] = members
                bound_members(members, depth + 1)

        bound_members(symbols, 0)
        return {
            "path": target_path.relative_to(self.root_path).as_posix(),
            "language": language,
            "symbols": symbols,
            "complete": complete,
            "total_symbols": total_symbols,
            "returned_symbols": len(symbols),
            "exact_symbol_selected": exact_symbol is not None,
            "warnings": warnings,
        }

    @staticmethod
    def render_interface(interface: Mapping[str, Any]) -> str:
        """Render a structured interface hierarchy without implementation bodies."""
        lines: list[str] = []

        def append_symbols(symbols: Any, depth: int) -> None:
            if not isinstance(symbols, list):
                return
            for symbol in symbols:
                if not isinstance(symbol, Mapping):
                    continue
                lines.append(f"{'    ' * depth}{symbol.get('signature', symbol.get('name', ''))}")
                documentation = symbol.get("documentation")
                if isinstance(documentation, str) and documentation:
                    for line in documentation.splitlines():
                        lines.append(f"{'    ' * (depth + 1)}# {line}")
                append_symbols(symbol.get("members"), depth + 1)

        append_symbols(interface.get("symbols"), 0)
        return "\n".join(lines) if lines else "No symbols found in file."

    def read_interface(self, file_path: str) -> str:
        """Preserve the legacy string interface projection and string errors."""
        try:
            return self.render_interface(
                self.read_interface_structured(
                    file_path,
                    member_depth=None,
                    max_symbols=None,
                    max_members=None,
                )
            )
        except InterfaceReadError as exc:
            return f"Error reading interface: {exc}"

    def read_symbol(
        self,
        symbol: Mapping[str, Any],
        *,
        context_lines: int = 0,
        max_lines: int = 200,
        max_bytes: int = 64 * 1024,
    ) -> dict[str, Any]:
        """Read one contained symbol source slice with explicit line and byte bounds."""
        if context_lines < 0 or max_lines < 1 or max_bytes < 1:
            raise ValueError("context_lines must be non-negative and max_lines/max_bytes must be positive.")
        path_value = symbol.get("path") or symbol.get("abs_path")
        if not isinstance(path_value, str):
            raise ValueError("Symbol path is required.")
        target = self._resolve_repo_path(path_value, require_file=True)
        start = int(symbol.get("start_line", 0))
        end = int(symbol.get("end_line", start))
        if start < 1 or end < start:
            raise ValueError("Symbol start_line/end_line are invalid.")
        lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
        slice_start = max(1, start - context_lines)
        slice_end = min(len(lines), end + context_lines)
        requested_lines = lines[slice_start - 1 : slice_end]
        line_truncated = len(requested_lines) > max_lines
        requested_lines = requested_lines[:max_lines]
        source = "".join(requested_lines)
        encoded = source.encode("utf-8")
        byte_truncated = len(encoded) > max_bytes
        if byte_truncated:
            source = encoded[:max_bytes].decode("utf-8", errors="ignore")
        returned_lines = source.count("\n") + (1 if source and not source.endswith("\n") else 0)
        return {
            "path": target.relative_to(self.root_path).as_posix(),
            "symbol": {
                key: symbol.get(key) for key in ("name", "type", "qualified_name") if symbol.get(key) is not None
            },
            "start_line": slice_start,
            "end_line": slice_start + max(0, returned_lines - 1),
            "source": source,
            "returned_lines": returned_lines,
            "returned_bytes": len(source.encode("utf-8")),
            "truncated": line_truncated or byte_truncated,
            "line_truncated": line_truncated,
            "byte_truncated": byte_truncated,
        }

    def symbol_at(self, file_path: str, line: int) -> dict[str, Any] | None:
        """Return the narrowest inventory symbol containing a one-based source line."""
        if line < 1:
            raise ValueError("line must be 1 or greater.")
        target = self._resolve_repo_path(file_path, require_file=True)
        relative = target.relative_to(self.root_path).as_posix()
        matches = [
            symbol
            for symbol in self._get_symbol_inventory()
            if symbol.get("path") == relative
            and int(symbol.get("start_line", 0)) <= line <= int(symbol.get("end_line", 0))
        ]
        if not matches:
            return None
        selected = min(
            matches,
            key=lambda symbol: (
                int(symbol.get("end_line", 0)) - int(symbol.get("start_line", 0)),
                -int(symbol.get("start_line", 0)),
            ),
        )
        return cast(dict[str, Any], dict(selected))

    def _resolve_file_inside_root(self, file_path: str) -> Path:
        """Resolve a file path and require it to remain inside the repository root."""
        target_path = Path(file_path).expanduser()
        if not target_path.is_absolute():
            target_path = self.root_path / target_path

        target_path = target_path.resolve()
        try:
            target_path.relative_to(self.root_path)
        except ValueError:
            raise ValueError(f"File '{file_path}' is outside repository root '{self.root_path}'.")

        return target_path

    def _get_skeleton_cache_key(self, file_path: Path, symbol_types: list[str] | None) -> str:
        """Include outline filters in the skeleton cache identity."""
        types_key = ",".join(symbol_types or [])
        return f"{self._get_cache_key(file_path)}:outline-types={types_key}"

    def _get_file_skeleton_enhanced(
        self, file_path: Path, max_symbols: int, symbol_types: list[str] | None = None
    ) -> list[str]:
        """Extract symbol signatures using ast-grep outline."""
        # Check cache first
        cache_key = self._get_skeleton_cache_key(file_path, symbol_types)
        cached_symbols = self._get_cached_symbols(cache_key)
        if cached_symbols is not None:
            return self._format_enhanced_skeleton(cached_symbols, max_symbols)

        language = LANGUAGE_MAP.get(file_path.suffix.lower())
        if not language:
            return []

        try:
            if file_path.stat().st_size > MAX_SKELETON_FILE_BYTES:
                return []

            args = ["outline", "--json=compact", "--view=expanded"]
            if symbol_types:
                args.extend(["--type", ",".join(symbol_types)])
            args.append(str(file_path))
            result = run_ast_grep(args)
            outlines = parse_json_array(result.stdout)
            symbols: list[SymbolSkeleton] = []
            for outline in outlines:
                if not isinstance(outline, Mapping):
                    continue
                items = outline.get("items", [])
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, Mapping):
                        continue
                    self._append_outline_symbol(symbols, item)

            self._set_cached_symbols(cache_key, symbols)

            return self._format_enhanced_skeleton(symbols, max_symbols)

        except Exception:
            return []

    def _append_outline_symbol(self, symbols: list[SymbolSkeleton], item: Mapping[str, Any]) -> None:
        """Append an outline item and its expanded direct members."""
        name = item.get("name")
        symbol_type = item.get("symbolType")
        signature = item.get("signature")
        if isinstance(name, str) and isinstance(symbol_type, str) and isinstance(signature, str):
            symbols.append({"name": name, "type": symbol_type, "signature": signature, "doc": ""})

        members = item.get("members", [])
        if isinstance(members, list):
            for member in members:
                if isinstance(member, Mapping):
                    self._append_outline_symbol(symbols, member)

    def _format_enhanced_skeleton(self, symbols: list[SymbolSkeleton], max_symbols: int) -> list[str]:
        """Format enhanced symbol info for display."""
        if not symbols:
            return []

        lines = []
        shown_count = min(len(symbols), max_symbols)

        for symbol in symbols[:shown_count]:
            line = symbol.get("signature", "")
            doc = symbol.get("doc", "")
            if doc:
                line += f" # {doc}"
            lines.append(line)

        if len(symbols) > max_symbols:
            remaining = len(symbols) - max_symbols
            lines.append(f"... and {remaining} more")

        return lines

    def _supported_source_snapshot(self) -> tuple[str, list[Path]]:
        """Return a bounded supported-source manifest and its content-sensitive identity."""
        policy = self._parse_gitignore()
        files: list[Path] = []
        manifest: list[tuple[str, int, str]] = []
        total_bytes = 0
        argument_chars = 0
        stack = [self.root_path]
        while stack:
            directory = stack.pop()
            try:
                children = sorted(directory.iterdir(), key=lambda path: path.as_posix(), reverse=True)
            except OSError:
                continue
            for path in children:
                if self._should_exclude(path, policy):
                    continue
                if path.is_dir():
                    stack.append(path)
                    continue
                if not path.is_file() or path.suffix.lower() not in LANGUAGE_MAP:
                    continue
                try:
                    content = path.read_bytes()
                except OSError:
                    continue
                total_bytes += len(content)
                if len(files) >= MAX_INVENTORY_FILES or total_bytes > MAX_INVENTORY_SOURCE_BYTES:
                    raise ValueError("Supported-source inventory exceeds XRAY's repository bounds.")
                files.append(path)
                argument_chars += len(str(path)) + 1
                if argument_chars > MAX_SOURCE_ARGUMENT_CHARS:
                    raise ValueError("Supported-source paths exceed XRAY's subprocess argument bound.")
                manifest.append((path.relative_to(self.root_path).as_posix(), len(content), self._sha256(content)))
        fingerprint = self._sha256(
            self._canonical_json({"inventory_schema": INVENTORY_SCHEMA_VERSION, "files": sorted(manifest)})
        )
        return fingerprint, files

    def repository_snapshot_fingerprint(self) -> str:
        """Return a bounded content identity for adapter continuation cursors."""
        policy = self._parse_gitignore()
        manifest: list[tuple[str, int, str]] = []
        total_bytes = 0
        stack = [self.root_path]
        while stack:
            directory = stack.pop()
            try:
                children = sorted(directory.iterdir(), key=lambda path: path.as_posix(), reverse=True)
            except OSError:
                continue
            for path in children:
                if self._should_exclude(path, policy):
                    continue
                if path.is_dir():
                    stack.append(path)
                    continue
                if not path.is_file():
                    continue
                try:
                    content = path.read_bytes()
                except OSError:
                    continue
                total_bytes += len(content)
                if len(manifest) >= MAX_INVENTORY_FILES or total_bytes > MAX_INVENTORY_SOURCE_BYTES:
                    raise ValueError("Repository snapshot exceeds XRAY's cursor fingerprint bounds.")
                manifest.append((path.relative_to(self.root_path).as_posix(), len(content), self._sha256(content)))
        return self._sha256(self._canonical_json(sorted(manifest)))[:24]

    def _load_inventory_cache(self, fingerprint: str) -> list[dict[str, Any]] | None:
        """Load a validated snapshot-bound inventory from the optional disk cache."""
        if self.cache_dir is None:
            return None
        cache_file = self.cache_dir / INVENTORY_CACHE_FILENAME
        try:
            value = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(value, Mapping) or value.get("fingerprint") != fingerprint:
            return None
        symbols = value.get("symbols")
        if not isinstance(symbols, list) or len(symbols) > MAX_INVENTORY_SYMBOLS:
            return None
        if not all(isinstance(symbol, dict) for symbol in symbols):
            return None
        return [dict(symbol) for symbol in symbols]

    def _save_inventory_cache(self, fingerprint: str, symbols: list[dict[str, Any]]) -> None:
        """Atomically persist a bounded symbol inventory when disk caching is available."""
        if self.cache_dir is None:
            return
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("w", dir=self.cache_dir, delete=False, encoding="utf-8") as stream:
                json.dump({"fingerprint": fingerprint, "symbols": symbols}, stream, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
                temporary_path = Path(stream.name)
            os.replace(temporary_path, self.cache_dir / INVENTORY_CACHE_FILENAME)
        except (OSError, TypeError, ValueError):
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _append_inventory_symbol(
        self,
        symbols: list[dict[str, Any]],
        item: Mapping[str, Any],
        *,
        path: str,
        language: str,
        owner: str | None = None,
    ) -> None:
        """Flatten one outline item while retaining owner and qualified identity."""
        name = item.get("name")
        if isinstance(name, str) and name:
            range_data = item.get("range")
            start = range_data.get("start", {}) if isinstance(range_data, Mapping) else {}
            end = range_data.get("end", {}) if isinstance(range_data, Mapping) else {}
            start_line = self._normalize_ast_grep_line(start.get("line") if isinstance(start, Mapping) else None)
            end_line = self._normalize_ast_grep_line(
                end.get("line", start_line - 1) if isinstance(end, Mapping) else start_line - 1
            )
            qualified_name = f"{owner}.{name}" if owner else name
            is_public = item.get("isPublic")
            visibility = self._inventory_visibility(name, language, is_public, item.get("isExported"))
            symbol_type = str(item.get("symbolType") or "symbol")
            ast_kind = str(item.get("astKind") or "")
            signature = str(item.get("signature") or name)
            if symbol_type == "typeParameter" and ast_kind == "type_declaration":
                symbol_type = "type"
            if ast_kind == "variable_declarator" and ("=>" in signature or "function" in signature):
                symbol_type = "function"
            symbols.append(
                {
                    "name": name,
                    "type": symbol_type,
                    "path": path,
                    "start_line": start_line,
                    "end_line": end_line,
                    "language": language,
                    "owner": owner,
                    "qualified_name": qualified_name,
                    "signature": signature,
                    "role": str(item.get("role") or ("member" if owner else "item")),
                    "visibility": visibility,
                    "doc": "",
                }
            )
            owner = qualified_name
        members = item.get("members")
        if isinstance(members, list):
            for member in members:
                if isinstance(member, Mapping):
                    self._append_inventory_symbol(symbols, member, path=path, language=language, owner=owner)

    def _get_symbol_inventory(self) -> list[dict[str, Any]]:
        """Build one expanded outline per dirty-source snapshot and cache the result."""
        fingerprint, source_files = self._supported_source_snapshot()
        if fingerprint == self._inventory_fingerprint and self._inventory is not None:
            self.last_search_succeeded = True
            return self._inventory
        cached = self._load_inventory_cache(fingerprint)
        if cached is not None:
            self._inventory_fingerprint = fingerprint
            self._inventory = cached
            self.last_search_succeeded = True
            return cached
        if not source_files:
            self._inventory_fingerprint = fingerprint
            self._inventory = []
            self.last_search_succeeded = True
            return []
        try:
            result = run_ast_grep(
                ["outline", "--json=compact", "--view=expanded", *(str(path) for path in source_files)]
            )
            outlines = parse_json_array(result.stdout)
        except (AstGrepCommandError, AstGrepNotFoundError, json.JSONDecodeError, ValueError) as exc:
            self.last_warnings.append(str(exc))
            self.last_search_succeeded = False
            return []

        source_paths = {path.relative_to(self.root_path).as_posix(): path for path in source_files}
        symbols: list[dict[str, Any]] = []
        for outline in outlines:
            outline_path = outline.get("path") or outline.get("file")
            if not isinstance(outline_path, str):
                continue
            candidate = Path(outline_path)
            if candidate.is_absolute():
                try:
                    relative_path = candidate.resolve().relative_to(self.root_path).as_posix()
                except ValueError:
                    continue
            else:
                relative_path = candidate.as_posix()
            source_path = source_paths.get(relative_path)
            if source_path is None:
                continue
            items = outline.get("items")
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, Mapping):
                    self._append_inventory_symbol(
                        symbols,
                        item,
                        path=relative_path,
                        language=LANGUAGE_MAP[source_path.suffix.lower()],
                    )
                    if len(symbols) > MAX_INVENTORY_SYMBOLS:
                        raise ValueError("Symbol inventory exceeds XRAY's result bound.")
        self._inventory_fingerprint = fingerprint
        self._inventory = symbols
        self.last_search_succeeded = True
        self._save_inventory_cache(fingerprint, symbols)
        return symbols

    @staticmethod
    def _normalized_symbol_text(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    def _score_inventory_symbol(self, query: str, symbol: Mapping[str, Any]) -> tuple[int, str, str]:
        """Return calibrated score, reason, and confidence without owner pollution."""
        query_lower = query.strip().lower()
        name = str(symbol["name"]).lower()
        qualified_name = str(symbol.get("qualified_name") or name).lower().replace("::", ".")
        path = str(symbol.get("path") or "").lower()
        qualified_query = "." in query_lower or "::" in query_lower
        path_query = "/" in query_lower or "\\" in query_lower
        normalized_query = self._normalized_symbol_text(query_lower)

        if qualified_query:
            candidate = qualified_name
            normalized_candidate = self._normalized_symbol_text(candidate)
            if query_lower.replace("::", ".") == candidate:
                return 100, "exact_qualified_name", "high"
        elif path_query:
            candidate = f"{path}:{qualified_name}"
            normalized_candidate = self._normalized_symbol_text(candidate)
            if query_lower.replace("\\", "/") in {path, f"{path}:{qualified_name}"}:
                return 100, "exact_path_context", "high"
        else:
            candidate = name
            normalized_candidate = self._normalized_symbol_text(name)
            if query_lower == name:
                return 100, "exact_name", "high"

        if normalized_query and normalized_query == normalized_candidate:
            return 95, "normalized_name", "high"
        if query_lower and candidate.startswith(query_lower):
            return 85, "prefix", "medium"
        query_tokens = {part for part in re.split(r"[^a-z0-9]+", query_lower) if part}
        candidate_tokens = {part for part in re.split(r"[^a-z0-9]+", candidate) if part}
        if query_tokens and query_tokens <= candidate_tokens:
            return 75, "token", "medium"
        return min(int(fuzz.ratio(query_lower, candidate)), 59), "fuzzy", "low"

    def find_symbol(
        self,
        query: str,
        limit: int | None = 10,
        min_score: int = 60,
        include_scores: bool = True,
        *,
        paths: Sequence[str] | None = None,
        languages: Sequence[str] | None = None,
        symbol_types: Sequence[str] | None = None,
        visibility: Sequence[str] | None = None,
    ) -> list[SymbolMatch]:
        """Find symbols by calibrated name identity after contained scope filtering."""
        if not query.strip():
            raise ValueError("Symbol query must not be empty.")
        if limit is not None and limit < 0:
            raise ValueError("limit must be 0 or greater.")
        if not 0 <= min_score <= 100:  # noqa: PLR2004 - public score scale is defined as 0..100
            raise ValueError("min_score must be between 0 and 100.")
        _resolved, relative_paths = self._operation_scopes(paths)
        normalized_languages = {value.lower() for value in languages or ()}
        unknown_languages = normalized_languages - set(LANGUAGE_MAP.values())
        if unknown_languages:
            raise ValueError(f"Unsupported language filter: {sorted(unknown_languages)[0]}.")
        normalized_types = {value.lower() for value in symbol_types or ()}
        normalized_visibility = {value.lower() for value in visibility or ()}
        if normalized_visibility - {"public", "private", "unknown"}:
            raise ValueError("visibility filters must be public, private, or unknown.")
        self.last_warnings = []
        self.last_search_succeeded = False
        scored: list[tuple[int, int, dict[str, Any]]] = []
        reason_priority = {
            "exact_qualified_name": 6,
            "exact_path_context": 6,
            "exact_name": 5,
            "normalized_name": 4,
            "prefix": 3,
            "token": 2,
            "fuzzy": 1,
        }
        for symbol in self._get_symbol_inventory():
            symbol_path = str(symbol.get("path") or "")
            if relative_paths and not any(
                scope in {".", symbol_path} or symbol_path.startswith(f"{scope}/") for scope in relative_paths
            ):
                continue
            if normalized_languages and str(symbol.get("language", "")).lower() not in normalized_languages:
                continue
            if normalized_types and str(symbol.get("type", "")).lower() not in normalized_types:
                continue
            if normalized_visibility and str(symbol.get("visibility", "unknown")).lower() not in normalized_visibility:
                continue
            score, reason, confidence = self._score_inventory_symbol(query, symbol)
            if score < min_score:
                continue
            result = dict(symbol)
            result.update({"match_reason": reason, "confidence": confidence})
            if include_scores:
                result["score"] = score
            scored.append((score, reason_priority[reason], result))
        scored.sort(
            key=lambda value: (
                -value[0],
                -value[1],
                str(value[2].get("qualified_name", "")).lower(),
                str(value[2].get("path", "")),
                int(value[2].get("start_line", 0)),
            )
        )
        self.last_find_total = len(scored)
        selected = scored if limit is None else scored[:limit]
        return [cast(SymbolMatch, value[2]) for value in selected]

    def _get_metavariable(self, metavars: dict[str, Any], name: str) -> dict[str, Any] | None:
        """Return a metavariable from old or current ast-grep JSON shapes."""
        if name in metavars:
            value = metavars[name]
            if isinstance(value, dict):
                return value

        single_vars = metavars.get("single", {})
        if isinstance(single_vars, dict):
            value = single_vars.get(name)
            if isinstance(value, dict):
                return value

        return None

    def _normalize_ast_grep_line(self, line: int | None) -> int:
        """Convert ast-grep zero-based line values to one-based line numbers."""
        if line is None:
            return 1
        return int(line) + 1

    def _extract_symbol_name(self, text: str) -> str | None:
        """Extract the symbol name from matched text."""
        # Patterns to extract names from different definition types
        patterns = [
            r"(?:def|class|function|interface|type)\s+(\w+)",
            r"(?:const|let|var)\s+(\w+)\s*=",
            r"func\s+(?:\([^)]+\)\s+)?(\w+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)

        return None

    def what_breaks(
        self,
        exact_symbol: Mapping[str, Any],
        context_lines: int = 2,
        max_results: int | None = None,
    ) -> ImpactResult:
        """
        Find likely code references to a symbol name using structural search.
        Prioritizes ast-grep for code references, falls back to text search.
        """
        symbol_name = exact_symbol["name"]
        definition_path_value = exact_symbol.get("abs_path") or exact_symbol["path"]
        definition_path = str(Path(definition_path_value).resolve())
        definition_start = exact_symbol.get("start_line", -1)
        definition_end = exact_symbol.get("end_line", definition_start)

        if max_results is not None and max_results < 1:
            raise ValueError("max_results must be 1 or greater.")
        strategy = "structural"
        degradation_reason: str | None = None

        raw_cap = max_results
        execution_limited = False
        structural_error: str | None = None
        while True:
            references, total_exact, structural_error = self._ast_grep_search(symbol_name, context_lines, raw_cap)
            filtered_references = self._filter_impact_references(
                references,
                symbol_name,
                definition_path,
                int(definition_start),
                int(definition_end),
            )
            enough = max_results is None or len(filtered_references) >= max_results
            if enough or total_exact or raw_cap is None:
                break
            if raw_cap >= MAX_IMPACT_RAW_RESULTS:
                execution_limited = True
                break
            raw_cap = min(MAX_IMPACT_RAW_RESULTS, max(raw_cap + 1, raw_cap * 2))

        if not filtered_references:
            strategy = "text"
            references, total_exact = self._text_search(symbol_name, context_lines, max_results)
            filtered_references = self._filter_impact_references(
                references,
                symbol_name,
                definition_path,
                int(definition_start),
                int(definition_end),
            )
            degradation_reason = (
                structural_error or "Structural search returned no usable candidates; used text fallback."
            )

        raw_count = len(references)
        references = filtered_references
        definition_count = sum(reference.get("type") == "definition" for reference in references)
        lower_bound = "at least " if not total_exact else ""

        return {
            "references": references,
            "total_count": len(references),
            "raw_count": raw_count,
            "filtered_count": raw_count - len(references),
            "strategy": strategy,
            "note": (
                f"Found {lower_bound}{len(references)} name-based references using {strategy} search; "
                f"{definition_count} same-name definitions are classified separately and are not dependents."
            ),
            "total_exact": total_exact,
            "degradation_reason": degradation_reason,
            "execution_limited": execution_limited,
            "execution_cap": raw_cap,
        }

    def _ast_grep_search(
        self, symbol_name: str, context_lines: int, max_results: int | None
    ) -> tuple[list[ImpactReference], bool, str | None]:
        """Search for symbol-name code references using ast-grep."""
        references: list[ImpactReference] = []
        try:
            _fingerprint, source_files = self._supported_source_snapshot()
            if not source_files:
                return [], True, None
            args = ["run", "--pattern", symbol_name, "-C", str(context_lines), *(str(path) for path in source_files)]
            if max_results is None:
                args.insert(3, "--json=compact")
                matches = parse_json_array(run_ast_grep(args).stdout)
                total_exact = True
            else:
                bounded = run_ast_grep_bounded(args, max_results)
                matches = bounded.matches
                total_exact = bounded.total_exact
        except (AstGrepCommandError, AstGrepNotFoundError, json.JSONDecodeError, ValueError) as exc:
            return references, True, f"Structural search failed: {exc}"

        for match in matches:
            code_snippet = (match.get("lines") or match.get("text") or "").strip()
            matched_text = self._matched_ast_grep_line(match, symbol_name)
            line_num = self._normalize_ast_grep_line(match.get("range", {}).get("start", {}).get("line"))
            reference_type, confidence = self._classify_impact_reference(symbol_name, matched_text, structural=True)
            references.append(
                {
                    "file": match.get("file", ""),
                    "line": line_num,
                    "text": code_snippet,
                    "matched_text": matched_text,
                    "type": reference_type,
                    "confidence": confidence,
                }
            )

        return references, total_exact, None

    @staticmethod
    def _matched_ast_grep_line(match: Mapping[str, Any], symbol_name: str) -> str:
        """Return the exact matched source line from an ast-grep context block."""
        context = str(match.get("lines") or match.get("text") or "")
        char_count = match.get("charCount")
        leading = char_count.get("leading") if isinstance(char_count, Mapping) else None
        if isinstance(leading, int) and 0 <= leading <= len(context):
            line_start = context.rfind("\n", 0, leading) + 1
            line_end = context.find("\n", leading)
            if line_end < 0:
                line_end = len(context)
            return context[line_start:line_end].strip()
        word = re.compile(r"\b" + re.escape(symbol_name) + r"\b")
        return next((line.strip() for line in context.splitlines() if word.search(line)), context.strip())

    @staticmethod
    def _classify_impact_reference(symbol_name: str, text: str, *, structural: bool) -> tuple[str, str]:
        """Classify one name match without claiming type-aware dependency analysis."""
        escaped = re.escape(symbol_name)
        if re.search(rf"\b(?:def|class|function|interface|type|enum)\s+{escaped}\b", text) or re.search(
            rf"\b(?:const|let|var)\s+{escaped}\s*=", text
        ):
            return "definition", "high"
        if re.search(rf"\b(?:import|from)\b[^\n]*\b{escaped}\b", text) or re.search(
            rf"\b{escaped}\b[^\n]*\b(?:from|require)\b", text
        ):
            return "import", "high"
        if re.search(rf"\b{escaped}\s*\(", text):
            return "call", "high" if structural else "medium"
        return ("read", "medium") if structural else ("text", "low")

    def _filter_impact_references(
        self,
        references: list[ImpactReference],
        symbol_name: str,
        definition_path: str,
        definition_start: int,
        definition_end: int,
    ) -> list[ImpactReference]:
        """Keep only exact, source-file references outside the symbol definition."""
        filtered: list[ImpactReference] = []
        seen: set[tuple[str, int, str, str]] = set()
        word_pattern = re.compile(r"\b" + re.escape(symbol_name) + r"\b")
        gitignore_patterns = self._parse_gitignore()

        for ref in references:
            ref_file = str(ref.get("file", ""))
            if not ref_file:
                continue

            ref_path = self._resolve_impact_reference_path(ref_file)
            if ref_path is None or not self._is_supported_impact_file(ref_path, gitignore_patterns):
                continue

            text = str(ref.get("text", ""))
            matched_text = str(ref.get("matched_text") or text)
            if not word_pattern.search(matched_text):
                continue

            ref_line = int(ref.get("line", 0))
            ref_path_str = str(ref_path)
            if ref_path_str == definition_path and definition_start <= ref_line <= definition_end:
                continue

            ref_type = str(ref.get("type", "text"))
            confidence = str(ref.get("confidence", "low"))
            key = (ref_path_str, ref_line, text, ref_type)
            if key in seen:
                continue

            seen.add(key)
            filtered_ref: ImpactReference = {
                "file": ref_path_str,
                "line": ref_line,
                "text": text,
                "type": ref_type,
                "confidence": confidence,
            }
            if "matched_text" in ref:
                filtered_ref["matched_text"] = matched_text
            filtered.append(filtered_ref)

        return filtered

    def _resolve_impact_reference_path(self, file_path: str) -> Path | None:
        """Resolve ast-grep/rg result paths relative to the repository root."""
        path = Path(file_path).expanduser()
        if not path.is_absolute():
            path = self.root_path / path
        try:
            return path.resolve()
        except OSError:
            return None

    def _is_supported_impact_file(self, path: Path, gitignore_patterns: IgnorePolicy) -> bool:
        """Return whether impact analysis should report a file as code."""
        return path.suffix.lower() in LANGUAGE_MAP and not self._should_exclude(path, gitignore_patterns)

    def _text_search(
        self, symbol_name: str, context_lines: int, max_results: int | None
    ) -> tuple[list[ImpactReference], bool]:
        """Unified text search (ripgrep -> python fallback)."""
        if max_results is not None:
            return self._python_text_search(symbol_name, max_results=max_results)
        references: list[ImpactReference] = []
        gitignore_patterns = self._parse_gitignore()

        # Try ripgrep
        try:
            cmd = ["rg", "-w", "--json", "-C", str(context_lines), symbol_name, str(self.root_path)]
            with tempfile.TemporaryFile("w+", encoding="utf-8") as stdout_file:
                result = subprocess.run(
                    cmd,
                    stdout=stdout_file,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    text=True,
                    timeout=RG_TIMEOUT_SECONDS,
                )
                stdout = self._read_limited_process_output(stdout_file, MAX_RG_OUTPUT_CHARS)
            if result.returncode == 0:
                for line in stdout.strip().split("\n"):
                    if line:
                        try:
                            data = json.loads(line)
                            if data.get("type") == "match":
                                match_data = data.get("data", {})
                                file_path = match_data.get("path", {}).get("text", "")
                                resolved = self._resolve_impact_reference_path(file_path)
                                if resolved is None or not self._is_supported_impact_file(resolved, gitignore_patterns):
                                    continue
                                references.append(
                                    {
                                        "file": str(resolved),
                                        "line": match_data.get("line_number", 0),
                                        "text": match_data.get("lines", {}).get("text", "").strip(),
                                        "type": "text",
                                        "confidence": "low",
                                    }
                                )
                        except json.JSONDecodeError:
                            continue
                return references, True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Python fallback (simplified, no context for now to save complexity)
        return self._python_text_search(symbol_name)

    def _read_limited_process_output(self, stream: Any, limit: int) -> str:
        """Read a temp-backed subprocess stream only when it is within the configured cap."""
        stream.seek(0, os.SEEK_END)
        length = stream.tell()
        if length > limit:
            return ""

        stream.seek(0)
        output = stream.read()
        if len(output) > limit:
            return ""
        return output

    def _python_text_search(
        self, symbol_name: str, max_results: int | None = None
    ) -> tuple[list[ImpactReference], bool]:
        """Fallback text search using Python when ripgrep is not available."""
        references: list[ImpactReference] = []
        _fingerprint, source_files = self._supported_source_snapshot()

        # Create word boundary pattern
        pattern = re.compile(r"\b" + re.escape(symbol_name) + r"\b")

        for file_path in source_files:
            try:
                with open(file_path, encoding="utf-8") as f:
                    for line_num, line in enumerate(f, 1):
                        if pattern.search(line):
                            reference_type, confidence = self._classify_impact_reference(
                                symbol_name, line, structural=False
                            )
                            references.append(
                                {
                                    "file": str(file_path),
                                    "line": line_num,
                                    "text": line.strip(),
                                    "type": reference_type,
                                    "confidence": confidence,
                                }
                            )
                            if max_results is not None and len(references) >= max_results:
                                return references, False
            except Exception:
                continue

        return references, True
