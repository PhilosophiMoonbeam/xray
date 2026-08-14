"""Core indexing engine for XRAY - ast-grep based implementation."""

import ast
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict, cast

from pathspec import GitIgnoreSpec
from thefuzz import fuzz

from xray.core.ast_grep import (
    AstGrepCommandError,
    AstGrepNotFoundError,
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
RG_TIMEOUT_SECONDS = 30
MAX_RG_OUTPUT_CHARS = 10 * 1024 * 1024
MAX_SKELETON_FILE_BYTES = 1024 * 1024
MAX_INVENTORY_FILES = 20_000
MAX_INVENTORY_SOURCE_BYTES = 256 * 1024 * 1024
MAX_INVENTORY_SYMBOLS = 100_000
MAX_SOURCE_ARGUMENT_CHARS = 128 * 1024
INVENTORY_CACHE_FILENAME = "inventory.json"
REPLACEMENT_PLAN_VERSION = "xray.replace.v1"
DEFAULT_REPLACEMENT_MAX_MATCHES = 1000
DEFAULT_REPLACEMENT_MAX_FILES = 100
DEFAULT_REPLACEMENT_PREVIEW_LIMIT = 50
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

    def _git_state(self) -> tuple[str | None, bool]:
        """Return current Git commit and whether tracked or untracked state is dirty."""
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
        except (OSError, subprocess.TimeoutExpired):
            return None, False
        commit = commit_result.stdout.strip() if commit_result.returncode == 0 else None
        dirty = status_result.returncode == 0 and bool(status_result.stdout.strip())
        return commit, dirty

    @staticmethod
    def _plan_digest_payload(plan: Mapping[str, Any]) -> dict[str, Any]:
        """Select every semantic field covered by a replacement plan digest."""
        keys = (
            "plan_version",
            "root_path",
            "root_fingerprint",
            "query",
            "bounds",
            "allow_noop",
            "candidate_count",
            "changed_candidate_count",
            "no_op_count",
            "affected_file_count",
            "changed_file_count",
            "files",
        )
        return {key: plan[key] for key in keys}

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
        preview_limit: int = DEFAULT_REPLACEMENT_PREVIEW_LIMIT,
    ) -> PreparedReplacement:
        """Build one exact non-mutating replacement plan and its in-memory postimages."""
        if max_matches is not None and max_matches < 1:
            raise ValueError("max_matches must be 1 or greater.")
        if max_files is not None and max_files < 1:
            raise ValueError("max_files must be 1 or greater.")
        if preview_limit < 0:
            raise ValueError("preview_limit must be 0 or greater.")
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
        if max_files is not None and len(files) > max_files:
            raise ValueError(f"Replacement affects more than the allowed {max_files} files.")

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
            }
            for item in files
        ]
        commit, dirty = self._git_state()
        fingerprint_payload = {
            "root_path": str(self.root_path),
            "git_commit": commit,
            "query": query,
            "files": [{"path": item["path"], "sha256": item["preimage_sha256"]} for item in file_payloads],
        }
        root_fingerprint = self._sha256(self._canonical_json(fingerprint_payload))
        changed_candidate_count = sum(1 for item in files for edit in item.edits if bool(edit["changed"]))
        warnings: list[str] = []
        if query["change"]["kind"] == "pattern" and not query["change"].get("language"):
            warnings.append("Language was inferred; review configuration and documentation matches before apply.")
        if dirty:
            warnings.append("Repository worktree is dirty; the plan digest still binds every affected preimage.")
        if matches and changed_candidate_count == 0:
            warnings.append("Every candidate is a no-op; apply requires explicit no-op allowance.")
        plan: dict[str, Any] = {
            "plan_version": REPLACEMENT_PLAN_VERSION,
            "root_path": str(self.root_path),
            "root_fingerprint": root_fingerprint,
            "query": query,
            "bounds": {"max_matches": max_matches, "max_files": max_files},
            "allow_noop": allow_noop,
            "candidate_count": len(matches),
            "changed_candidate_count": changed_candidate_count,
            "no_op_count": len(matches) - changed_candidate_count,
            "affected_file_count": len(files),
            "changed_file_count": sum(item.original != item.postimage for item in files),
            "files": file_payloads,
            "preview": preview[:preview_limit],
            "preview_returned": min(len(preview), preview_limit),
            "preview_total": len(preview),
            "preview_truncated": len(preview) > preview_limit,
            "warnings": warnings,
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
        preview_limit: int = DEFAULT_REPLACEMENT_PREVIEW_LIMIT,
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
            preview_limit=preview_limit,
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
        staged: dict[Path, Path] = {}
        try:
            for item in changed_files:
                current = item.path.read_bytes()
                if self._sha256(current) != self._sha256(item.original):
                    raise ReplacementApplyError(f"Source drift detected before writing '{item.relative_path}'.")
                staged[item.path] = self._write_staged_file(item, item.postimage)
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

    def apply_replacement(self, plan: Mapping[str, Any], *, expected_digest: str) -> dict[str, Any]:
        """Recompute and apply a serialized plan only when every guard still matches."""
        if plan.get("plan_version") != REPLACEMENT_PLAN_VERSION:
            raise ValueError(f"Unsupported replacement plan version: {plan.get('plan_version')!r}.")
        stored_digest = plan.get("plan_digest")
        if not isinstance(stored_digest, str):
            raise ValueError("Replacement plan is missing plan_digest.")
        try:
            calculated_digest = self._sha256(self._canonical_json(self._plan_digest_payload(plan)))
        except KeyError as exc:
            raise ValueError(f"Replacement plan is missing semantic field {exc.args[0]!r}.") from exc
        if calculated_digest != stored_digest:
            raise ValueError("Replacement plan digest does not match its semantic fields.")
        if expected_digest != stored_digest:
            raise ValueError("expected_digest does not confirm this replacement plan.")
        if Path(str(plan.get("root_path", ""))).resolve() != self.root_path:
            raise ValueError("Replacement plan root does not match the requested repository root.")

        query = plan.get("query")
        bounds = plan.get("bounds")
        if not isinstance(query, Mapping) or not isinstance(query.get("change"), Mapping):
            raise ValueError("Replacement plan query is invalid.")
        if not isinstance(bounds, Mapping):
            raise ValueError("Replacement plan bounds are invalid.")
        change = query["change"]
        kind = change.get("kind")
        kwargs: dict[str, Any]
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
        prepared = self._build_replacement_plan(
            **kwargs,
            paths=query.get("paths"),
            globs=query.get("globs"),
            max_matches=bounds.get("max_matches"),
            max_files=bounds.get("max_files"),
            allow_noop=bool(plan.get("allow_noop", False)),
            preview_limit=int(plan.get("preview_returned", DEFAULT_REPLACEMENT_PREVIEW_LIMIT)),
        )
        if prepared.plan["plan_digest"] != stored_digest or prepared.plan["root_fingerprint"] != plan.get(
            "root_fingerprint"
        ):
            raise ReplacementApplyError("Replacement plan no longer matches the repository source snapshot.")
        if prepared.plan["changed_candidate_count"] == 0 and not prepared.plan["allow_noop"]:
            raise ValueError("Replacement plan contains no byte-changing edits; allow_noop was not recorded.")
        return self._apply_prepared_replacement(prepared)

    def rewrite_pattern(self, pattern: str, replacement: str, lang: str | None = None) -> dict[str, Any]:
        """Apply the legacy all-match rewrite through the staged writer."""
        prepared = self._build_replacement_plan(
            pattern=pattern,
            replacement=replacement,
            lang=lang,
            max_matches=None,
            max_files=None,
            allow_noop=True,
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
    ) -> ExploreRepoData:
        """
        Build structured repository map data for CLI and automation.

        The text tree remains available through explore_repo and structured payloads include entries for automation.
        """
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
            focus_dirs=focus_dirs,
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
                "focus_dirs": focus_dirs or [],
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

    def _should_include_dir(self, path: Path, focus_dirs: list[str] | None, current_depth: int) -> bool:
        """Check if a directory should be included based on focus_dirs."""
        if not focus_dirs or current_depth > 0:
            return True
        if path == self.root_path:
            return True

        # At depth 0 (top-level), only include if in focus_dirs
        return path.name in focus_dirs

    def _collect_tree_entries(
        self,
        path: Path,
        entries: list[ExploreEntry],
        gitignore_patterns: IgnorePolicy,
        current_depth: int,
        max_depth: int | None,
        include_symbols: bool,
        focus_dirs: list[str] | None,
        max_symbols_per_file: int,
        symbol_types: list[str] | None,
    ):
        """Collect a flat, structured repository map."""
        if self._should_exclude(path, gitignore_patterns):
            return

        if max_depth is not None and current_depth > max_depth:
            return

        if path.is_dir() and not self._should_include_dir(path, focus_dirs, current_depth):
            return

        try:
            relative_path = "." if path == self.root_path else path.relative_to(self.root_path).as_posix()
        except ValueError:
            relative_path = str(path)

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

        if not path.is_dir():
            return

        try:
            children = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            children = [c for c in children if not self._should_exclude(c, gitignore_patterns)]

            if current_depth == 0 and focus_dirs:
                children = [c for c in children if c.is_file() or c.name in focus_dirs]

            for child in children:
                self._collect_tree_entries(
                    child,
                    entries,
                    gitignore_patterns,
                    current_depth + 1,
                    max_depth,
                    include_symbols,
                    focus_dirs,
                    max_symbols_per_file,
                    symbol_types,
                )
        except PermissionError:
            pass

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

        # Check depth limit
        if max_depth is not None and current_depth > max_depth:
            return False

        # Check focus_dirs for directories
        if path.is_dir() and not self._should_include_dir(path, focus_dirs, current_depth):
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

                # Apply focus_dirs filter at top level
                if current_depth == 0 and focus_dirs:
                    children = [c for c in children if c.is_file() or c.name in focus_dirs]

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

    def read_interface_structured(self, file_path: str) -> dict[str, Any]:
        """Return a typed, hierarchical interface contract or raise InterfaceReadError."""
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
        return {
            "path": target_path.relative_to(self.root_path).as_posix(),
            "language": language,
            "symbols": symbols,
            "complete": not warnings,
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
            return self.render_interface(self.read_interface_structured(file_path))
        except InterfaceReadError as exc:
            return f"Error reading interface: {exc}"

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
        fingerprint = self._sha256(self._canonical_json(sorted(manifest)))
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
            visibility = "public" if is_public is True else "private" if is_public is False else "unknown"
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
        self, query: str, limit: int = 10, min_score: int = 0, include_scores: bool = False
    ) -> list[SymbolMatch]:
        """Find symbols from one snapshot-cached expanded outline inventory."""
        if not query.strip():
            raise ValueError("Symbol query must not be empty.")
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
        return [cast(SymbolMatch, value[2]) for value in scored[:limit]]

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

        references, total_exact, structural_error = self._ast_grep_search(symbol_name, context_lines, max_results)
        if not references:
            strategy = "text"
            references, total_exact = self._text_search(symbol_name, context_lines, max_results)
            degradation_reason = structural_error or "Structural search returned no candidates; used text fallback."

        raw_count = len(references)
        references = self._filter_impact_references(
            references,
            symbol_name,
            definition_path,
            int(definition_start),
            int(definition_end),
        )
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
            line_num = self._normalize_ast_grep_line(match.get("range", {}).get("start", {}).get("line"))
            reference_type, confidence = self._classify_impact_reference(symbol_name, code_snippet, structural=True)
            references.append(
                {
                    "file": match.get("file", ""),
                    "line": line_num,
                    "text": code_snippet,
                    "type": reference_type,
                    "confidence": confidence,
                }
            )

        return references, total_exact, None

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
            if not word_pattern.search(text):
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
