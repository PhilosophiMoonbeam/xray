"""Core indexing engine for XRAY - ast-grep based implementation."""

import ast
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypedDict, cast

from thefuzz import fuzz

from xray.core.ast_grep import (
    AstGrepCommandError,
    AstGrepNotFoundError,
    parse_json_array,
    run_ast_grep,
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
MAX_SYMBOL_CACHE_ENTRIES = 2048
GIT_TIMEOUT_SECONDS = 5
RG_TIMEOUT_SECONDS = 30
MAX_RG_OUTPUT_CHARS = 10 * 1024 * 1024
MAX_SKELETON_FILE_BYTES = 1024 * 1024


class SymbolSkeleton(TypedDict):
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


class ExploreRepoData(TypedDict):
    root_path: str
    entries: list[ExploreEntry]
    options: ExploreOptions


class SymbolMatchBase(TypedDict):
    name: str
    type: str
    path: str
    start_line: int
    end_line: int


class SymbolMatch(SymbolMatchBase, total=False):
    score: int
    abs_path: str


class ImpactReferenceBase(TypedDict):
    file: str
    line: int
    text: str


class ImpactReference(ImpactReferenceBase, total=False):
    type: str


class ImpactResult(TypedDict):
    references: list[ImpactReference]
    total_count: int
    raw_count: int
    filtered_count: int
    strategy: str
    note: str


class XRayIndexer:
    """Main indexer for XRAY - provides file tree and symbol extraction using ast-grep."""

    def __init__(self, root_path: str):
        self.root_path = Path(root_path).resolve()
        self._cache: OrderedDict[str, list[SymbolSkeleton]] = OrderedDict()
        self.last_warnings: list[str] = []
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
                self.cache_dir = Path(f"/tmp/.xray_cache/{root_hash}-{self.commit_sha}")
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                self._load_cache()
            else:
                self.commit_sha = None
                self.cache_dir = None
        except Exception:
            self.commit_sha = None
            self.cache_dir = None

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
                    clean_symbols.append({"signature": signature, "doc": doc})

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

    def explore_repo(
        self,
        max_depth: int | None = None,
        include_symbols: bool = False,
        focus_dirs: list[str] | None = None,
        max_symbols_per_file: int = 5,
    ) -> str:
        """
        Build a visual file tree with optional symbol skeletons.

        Args:
            max_depth: Limit directory traversal depth
            include_symbols: Include symbol skeletons in output
            focus_dirs: Only include these top-level directories
            max_symbols_per_file: Max symbols to show per file

        Returns:
            Formatted tree string
        """
        # Get gitignore patterns if available
        gitignore_patterns = self._parse_gitignore()

        # Build the tree
        tree_lines = []
        self._build_tree_recursive_enhanced(
            self.root_path,
            tree_lines,
            "",
            gitignore_patterns,
            current_depth=0,
            max_depth=max_depth,
            include_symbols=include_symbols,
            focus_dirs=focus_dirs,
            max_symbols_per_file=max_symbols_per_file,
            is_last=True,
        )

        # Save cache after building tree
        if include_symbols:
            self._save_cache()

        return "\n".join(tree_lines)

    def explore_repo_data(
        self,
        max_depth: int | None = None,
        include_symbols: bool = False,
        focus_dirs: list[str] | None = None,
        max_symbols_per_file: int = 5,
    ) -> ExploreRepoData:
        """
        Build structured repository map data for CLI and automation.

        The text tree remains available through explore_repo and structured payloads include entries for automation.
        """
        gitignore_patterns = self._parse_gitignore()
        entries: list[ExploreEntry] = []
        self._collect_tree_entries(
            self.root_path,
            entries,
            gitignore_patterns,
            current_depth=0,
            max_depth=max_depth,
            include_symbols=include_symbols,
            focus_dirs=focus_dirs,
            max_symbols_per_file=max_symbols_per_file,
        )

        if include_symbols:
            self._save_cache()

        return {
            "root_path": str(self.root_path),
            "entries": entries,
            "options": {
                "max_depth": max_depth,
                "include_symbols": include_symbols,
                "focus_dirs": focus_dirs or [],
                "max_symbols_per_file": max_symbols_per_file,
            },
        }

    def _parse_gitignore(self) -> set[str]:
        """Parse .gitignore file if it exists."""
        patterns = set()
        gitignore_path = self.root_path / ".gitignore"

        if gitignore_path.exists():
            try:
                with open(gitignore_path, encoding="utf-8") as f:
                    for raw_line in f:
                        line = raw_line.strip()
                        if line and not line.startswith("#"):
                            patterns.add(line)
            except Exception:
                pass

        return patterns

    def _should_exclude(self, path: Path, gitignore_patterns: set[str]) -> bool:
        """Check if a path should be excluded."""
        name = path.name

        if path != self.root_path and not self._is_inside_root(path):
            return True

        # Avoid following symlinked directories, which can escape the root or cycle.
        if path.is_symlink() and path.is_dir():
            return True

        # Check default exclusions
        if name in DEFAULT_EXCLUSIONS:
            return True

        # Check file pattern exclusions
        for pattern in DEFAULT_EXCLUSIONS:
            if "*" in pattern and fnmatch.fnmatch(name, pattern):
                return True

        # Check gitignore patterns (simplified)
        for pattern in gitignore_patterns:
            if pattern in str(path.relative_to(self.root_path)):
                return True
            if fnmatch.fnmatch(name, pattern):
                return True

        return False

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
        gitignore_patterns: set[str],
        current_depth: int,
        max_depth: int | None,
        include_symbols: bool,
        focus_dirs: list[str] | None,
        max_symbols_per_file: int,
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
            entry["symbols"] = self._get_file_symbol_data(path, max_symbols_per_file)

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
                )
        except PermissionError:
            pass

    def _get_file_symbol_data(self, file_path: Path, max_symbols: int) -> list[ExploreSymbol]:
        """Return structured symbol skeleton data for a source file."""
        cache_key = self._get_cache_key(file_path)
        if self._get_cached_symbols(cache_key) is None:
            self._get_file_skeleton_enhanced(file_path, max_symbols)

        symbols = self._get_cached_symbols(cache_key) or []
        structured_symbols: list[ExploreSymbol] = []
        for symbol in symbols[:max_symbols]:
            signature = symbol.get("signature", "")
            structured_symbols.append(
                {
                    "name": self._extract_symbol_name(signature) or signature,
                    "type": self._infer_symbol_type(signature),
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
        gitignore_patterns: set[str],
        current_depth: int,
        max_depth: int | None,
        include_symbols: bool,
        focus_dirs: list[str] | None,
        max_symbols_per_file: int,
        is_last: bool = False,
    ):
        """Recursively build the tree representation with enhanced features."""
        if self._should_exclude(path, gitignore_patterns):
            return

        # Check depth limit
        if max_depth is not None and current_depth > max_depth:
            return

        # Check focus_dirs for directories
        if path.is_dir() and not self._should_include_dir(path, focus_dirs, current_depth):
            return

        # Add current item
        name = path.name if path != self.root_path else str(path)
        connector = "└── " if is_last else "├── "

        # For files, add skeleton if requested
        if path.is_file() and include_symbols and path.suffix.lower() in LANGUAGE_MAP:
            skeleton = self._get_file_skeleton_enhanced(path, max_symbols_per_file)
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

                    self._build_tree_recursive_enhanced(
                        child,
                        tree_lines,
                        new_prefix,
                        gitignore_patterns,
                        current_depth + 1,
                        max_depth,
                        include_symbols,
                        focus_dirs,
                        max_symbols_per_file,
                        is_last_child,
                    )
            except PermissionError:
                pass

    def read_interface(self, file_path: str) -> str:
        """
        Read the interface (skeleton) of a specific file.
        Returns function signatures, class definitions, and types, but hides implementation details.
        """
        try:
            target_path = self._resolve_file_inside_root(file_path)

            if not target_path.exists() or not target_path.is_file():
                return f"Error: File '{file_path}' not found or is not a file."

            # Use the existing skeleton logic, but with a high limit on symbols
            skeleton = self._get_file_skeleton_enhanced(target_path, max_symbols=1000)

            if not skeleton:
                # Fallback: if no symbols found or language not supported,
                # maybe just read the first few lines? or return message?
                language = LANGUAGE_MAP.get(target_path.suffix.lower())
                if not language:
                    return f"File type '{target_path.suffix}' not supported for interface extraction."
                return "No symbols found in file."

            return "\n".join(skeleton)

        except Exception as e:
            return f"Error reading interface: {e!s}"

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

    def _get_file_skeleton_enhanced(self, file_path: Path, max_symbols: int) -> list[str]:
        """Extract enhanced symbol info including signatures and docstrings."""
        # Check cache first
        cache_key = self._get_cache_key(file_path)
        cached_symbols = self._get_cached_symbols(cache_key)
        if cached_symbols is not None:
            return self._format_enhanced_skeleton(cached_symbols, max_symbols)

        language = LANGUAGE_MAP.get(file_path.suffix.lower())
        if not language:
            return []

        try:
            if file_path.stat().st_size > MAX_SKELETON_FILE_BYTES:
                return []

            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            if language == "python":
                symbols = self._extract_python_symbols_enhanced(content)
            else:
                symbols = self._extract_regex_symbols_enhanced(content, language)

            self._set_cached_symbols(cache_key, symbols)

            return self._format_enhanced_skeleton(symbols, max_symbols)

        except Exception:
            return []

    def _format_enhanced_skeleton(self, symbols: list[SymbolSkeleton], max_symbols: int) -> list[str]:
        """Format enhanced symbol info for display."""
        if not symbols:
            return []

        lines = []
        shown_count = min(len(symbols), max_symbols)

        for symbol in symbols[:shown_count]:
            line = symbol["signature"]
            if symbol.get("doc"):
                line += f" # {symbol['doc']}"
            lines.append(line)

        if len(symbols) > max_symbols:
            remaining = len(symbols) - max_symbols
            lines.append(f"... and {remaining} more")

        return lines

    def _extract_python_symbols_enhanced(self, content: str) -> list[SymbolSkeleton]:
        """Extract Python symbols with signatures and docstrings."""
        symbols: list[SymbolSkeleton] = []
        try:
            tree = ast.parse(content)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.ClassDef):
                    sig = f"class {node.name}"
                    if node.bases:
                        base_names = []
                        for base in node.bases:
                            if isinstance(base, ast.Name):
                                base_names.append(base.id)
                            elif isinstance(base, ast.Attribute):
                                base_names.append(ast.unparse(base))
                        if base_names:
                            sig += f"({', '.join(base_names)})"
                    sig += ":"

                    doc = ast.get_docstring(node)
                    if doc:
                        doc = doc.split("\n")[0].strip()[:50]

                    symbols.append({"signature": sig, "doc": doc or ""})

                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Build function signature
                    sig = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
                    sig += f"{node.name}("

                    # Add parameters
                    args = []
                    for arg in node.args.args:
                        args.append(arg.arg)
                    if args:
                        sig += ", ".join(args)
                    sig += "):"

                    doc = ast.get_docstring(node)
                    if doc:
                        doc = doc.split("\n")[0].strip()[:50]

                    symbols.append({"signature": sig, "doc": doc or ""})
        except Exception:
            pass
        return symbols

    def _extract_regex_symbols_enhanced(self, content: str, language: str) -> list[SymbolSkeleton]:
        """Extract symbols with signatures and comments for JS/TS/Go."""
        symbols: list[SymbolSkeleton] = []

        # Language-specific patterns
        if language in ["javascript", "typescript"]:
            patterns = [
                # Function with preceding comment
                (
                    r"(?://\s*(.+?)\n)?^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\((.*?)\)",
                    lambda m: {"signature": f"function {m.group(2)}({m.group(3)}):", "doc": (m.group(1) or "").strip()},
                ),
                # Class with preceding comment
                (
                    r"(?://\s*(.+?)\n)?^\s*(?:export\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?",
                    lambda m: {
                        "signature": f"class {m.group(2)}" + (f" extends {m.group(3)}" if m.group(3) else "") + ":",
                        "doc": (m.group(1) or "").strip(),
                    },
                ),
                # Arrow function with const
                (
                    r"(?://\s*(.+?)\n)?^\s*(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\((.*?)\)\s*=>",
                    lambda m: {
                        "signature": f"const {m.group(2)} = ({m.group(3)}) =>",
                        "doc": (m.group(1) or "").strip(),
                    },
                ),
            ]
        elif language == "go":
            patterns = [
                # Function with preceding comment
                (
                    r"(?://\s*(.+?)\n)?^func\s+(\w+)\s*\((.*?)\)",
                    lambda m: {"signature": f"func {m.group(2)}({m.group(3)})", "doc": (m.group(1) or "").strip()},
                ),
                # Method with preceding comment
                (
                    r"(?://\s*(.+?)\n)?^func\s*\((\w+\s+[*]?\w+)\)\s*(\w+)\s*\((.*?)\)",
                    lambda m: {
                        "signature": f"func ({m.group(2)}) {m.group(3)}({m.group(4)})",
                        "doc": (m.group(1) or "").strip(),
                    },
                ),
                # Type struct with preceding comment
                (
                    r"(?://\s*(.+?)\n)?^type\s+(\w+)\s+struct",
                    lambda m: {"signature": f"type {m.group(2)} struct", "doc": (m.group(1) or "").strip()},
                ),
            ]
        else:
            return symbols

        # Apply patterns
        for pattern, extractor in patterns:
            for match in re.finditer(pattern, content, re.MULTILINE):
                symbols.append(cast(SymbolSkeleton, extractor(match)))

        return symbols

    def find_symbol(
        self, query: str, limit: int = 10, min_score: int = 0, include_scores: bool = False
    ) -> list[SymbolMatch]:
        """
        Find symbols matching the query using fuzzy search.
        Uses ast-grep to find all symbols, then fuzzy matches against the query.

        Returns a list of the top matching "Exact Symbol" objects.
        """
        all_symbols: list[SymbolMatch] = []
        self.last_warnings = []
        self.last_search_succeeded = False

        # Define patterns for different symbol types
        patterns = [
            # Python functions and classes
            ("def $NAME($$$)", "function"),
            ("class $NAME: $$$", "class"),
            ("class $NAME($$$): $$$", "class"),
            # JavaScript/TypeScript functions and classes
            ("function $NAME($$$)", "function"),
            ("const $NAME = $$$ => $$$", "function"),
            ("let $NAME = $$$ => $$$", "function"),
            ("var $NAME = $$$ => $$$", "function"),
            ("const $NAME = function($$$) { $$$ }", "function"),
            ("let $NAME = function($$$) { $$$ }", "function"),
            ("var $NAME = function($$$) { $$$ }", "function"),
            ("class $NAME", "class"),
            ("interface $NAME", "interface"),
            ("type $NAME =", "type"),
            ("enum $NAME { $$$ }", "enum"),
            # Go functions and types
            ("func $NAME($$$)", "function"),
            ("func ($$$) $NAME($$$)", "method"),
            ("type $NAME struct", "struct"),
            ("type $NAME interface", "interface"),
            ("type $NAME $$$", "type"),
        ]

        # Run ast-grep for each fixed symbol pattern.
        for pattern, symbol_type in patterns:
            try:
                result = run_ast_grep(["run", "--pattern", pattern, "--json=compact", str(self.root_path)])
            except AstGrepNotFoundError as exc:
                self.last_warnings.append(str(exc))
                break
            except AstGrepCommandError as exc:
                self.last_warnings.append(f"ast-grep failed for pattern {pattern!r}: {exc}")
                continue

            self.last_search_succeeded = True
            try:
                matches = parse_json_array(result.stdout)
            except (json.JSONDecodeError, ValueError) as exc:
                self.last_warnings.append(f"ast-grep returned invalid JSON for pattern {pattern!r}: {exc}")
                continue

            for match in matches:
                # Extract details from match
                text = match.get("text", "")
                file_path = match.get("file", "")
                start = match.get("range", {}).get("start", {})
                end = match.get("range", {}).get("end", {})

                # Extract the name from metavariables
                metavars = match.get("metaVariables", {})
                name: str | None = None

                # Try to get NAME from metavariables
                name_var = self._get_metavariable(metavars, "NAME")
                if name_var:
                    name_text = name_var.get("text")
                    if isinstance(name_text, str):
                        name = name_text
                else:
                    # Fallback to regex extraction
                    name = self._extract_symbol_name(text)

                if name:
                    symbol: SymbolMatch = {
                        "name": name,
                        "type": symbol_type,
                        "path": file_path,
                        "start_line": self._normalize_ast_grep_line(start.get("line")),
                        "end_line": self._normalize_ast_grep_line(end.get("line", start.get("line"))),
                    }
                    all_symbols.append(symbol)

        # Deduplicate symbols (same name and location)
        seen = set()
        unique_symbols: list[SymbolMatch] = []
        for symbol in all_symbols:
            key = (symbol["name"], symbol["path"], symbol["start_line"])
            if key not in seen:
                seen.add(key)
                unique_symbols.append(symbol)

        # Now perform fuzzy matching against the query
        scored_symbols: list[tuple[int, SymbolMatch]] = []
        query_lower = query.lower()
        query_parts = [part for part in re.split(r"[\s.:/\\]+", query_lower) if part]
        terminal_query_part = query_parts[-1] if query_parts else query_lower
        qualified_query = "." in query_lower or "::" in query_lower
        class_symbols = [symbol for symbol in unique_symbols if symbol["type"] == "class"]
        for symbol in unique_symbols:
            owner_name = self._find_enclosing_class_name(symbol, class_symbols)
            score = self._score_symbol_match(query_lower, symbol, owner_name)
            symbol_name_lower = symbol["name"].lower()
            if qualified_query and terminal_query_part not in symbol_name_lower:
                score = min(score, fuzz.partial_ratio(terminal_query_part, symbol_name_lower))
            if qualified_query and owner_name:
                qualified_name = f"{owner_name.lower()}.{symbol_name_lower}"
                if query_lower.endswith(qualified_name) or query_lower == qualified_name:
                    score = max(score, 100)

            if score >= min_score:
                scored_symbols.append((score, symbol))

        # Sort by score and take top results
        scored_symbols.sort(
            key=lambda x: (
                x[0],
                self._is_qualified_symbol_match(query_lower, x[1], class_symbols),
                x[1]["name"].lower() == terminal_query_part,
                x[1]["name"].lower() == query_lower,
            ),
            reverse=True,
        )
        if include_scores:
            top_symbols: list[SymbolMatch] = []
            for score, symbol in scored_symbols[:limit]:
                scored_symbol: SymbolMatch = {**symbol, "score": score}
                top_symbols.append(scored_symbol)
        else:
            top_symbols = [s[1] for s in scored_symbols[:limit]]

        return top_symbols

    def _score_symbol_match(self, query_lower: str, symbol: SymbolMatch, owner_name: str | None) -> int:
        """Score a symbol against name, owner, and path context."""
        symbol_name_lower = symbol["name"].lower()
        path_lower = symbol["path"].lower()
        path_context = re.sub(r"[^a-z0-9_]+", ".", path_lower).strip(".")
        candidates = {
            symbol_name_lower,
            path_context,
            f"{path_context}.{symbol_name_lower}",
        }
        if owner_name:
            owner_lower = owner_name.lower()
            candidates.update(
                {
                    owner_lower,
                    f"{owner_lower}.{symbol_name_lower}",
                    f"{path_context}.{owner_lower}.{symbol_name_lower}",
                }
            )

        score = max(fuzz.partial_ratio(query_lower, candidate) for candidate in candidates)
        if query_lower in candidates or query_lower in symbol_name_lower:
            score = max(score, 80)
        return int(score)

    def _find_enclosing_class_name(self, symbol: SymbolMatch, class_symbols: list[SymbolMatch]) -> str | None:
        """Return the smallest class range enclosing a symbol in the same file."""
        if symbol["type"] == "class":
            return None

        enclosing: list[SymbolMatch] = [
            class_symbol
            for class_symbol in class_symbols
            if class_symbol["path"] == symbol["path"]
            and class_symbol["start_line"] <= symbol["start_line"] <= class_symbol["end_line"]
        ]
        if not enclosing:
            return None

        owner = min(enclosing, key=lambda item: item["end_line"] - item["start_line"])
        return owner["name"]

    def _is_qualified_symbol_match(
        self, query_lower: str, symbol: SymbolMatch, class_symbols: list[SymbolMatch]
    ) -> bool:
        """Return whether the query names a symbol with its owner context."""
        owner_name = self._find_enclosing_class_name(symbol, class_symbols)
        if not owner_name:
            return False
        qualified_name = f"{owner_name.lower()}.{symbol['name'].lower()}"
        return query_lower == qualified_name or query_lower.endswith(qualified_name)

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

    def what_breaks(self, exact_symbol: Mapping[str, Any], context_lines: int = 2) -> ImpactResult:
        """
        Find likely code references to a symbol name using structural search.
        Prioritizes ast-grep for code references, falls back to text search.
        """
        symbol_name = exact_symbol["name"]
        definition_path_value = exact_symbol.get("abs_path") or exact_symbol["path"]
        definition_path = str(Path(definition_path_value).resolve())
        definition_start = exact_symbol.get("start_line", -1)
        definition_end = exact_symbol.get("end_line", definition_start)

        strategy = "structural"

        # Try structural search first (ast-grep)
        struct_refs = self._ast_grep_search(symbol_name, context_lines)

        if struct_refs:
            references = struct_refs
        else:
            # Fallback to text search if ast-grep found nothing (or failed)
            # Note: This might happen if the symbol is not in a supported language file
            # or if it's only used in comments/strings (which we might want to know about as fallback?)
            # For now, if structural search returns empty list, we trust it for code.
            # But we might want to run text search as a backup for non-code files?
            # Let's stick to the previous behavior's fallback logic: if ast-grep *fails to run*, we use grep.
            # If ast-grep runs and finds nothing, we return nothing (for code).
            # BUT, to be safe and "improve" without breaking, let's run text search
            # if structural search is empty, but mark them as "text matches".

            # Actually, let's just use the text search if structural returned nothing.
            strategy = "text"
            references = self._text_search(symbol_name, context_lines)

        raw_count = len(references)
        references = self._filter_impact_references(
            references,
            symbol_name,
            definition_path,
            int(definition_start),
            int(definition_end),
        )

        return {
            "references": references,
            "total_count": len(references),
            "raw_count": raw_count,
            "filtered_count": raw_count - len(references),
            "strategy": strategy,
            "note": f"Found {len(references)} references using {strategy} search.",
        }

    def _ast_grep_search(self, symbol_name: str, context_lines: int) -> list[ImpactReference]:
        """Search for symbol-name code references using ast-grep."""
        references: list[ImpactReference] = []
        try:
            result = run_ast_grep(
                [
                    "run",
                    "--pattern",
                    symbol_name,
                    "--json=compact",
                    "-C",
                    str(context_lines),
                    str(self.root_path),
                ]
            )
            matches = parse_json_array(result.stdout)
        except (AstGrepCommandError, AstGrepNotFoundError, json.JSONDecodeError, ValueError):
            return references

        for match in matches:
            # ast-grep json with -C returns 'lines' containing the snippet.
            code_snippet = (match.get("lines") or match.get("text") or "").strip()
            line_num = self._normalize_ast_grep_line(match.get("range", {}).get("start", {}).get("line"))

            references.append({"file": match.get("file", ""), "line": line_num, "text": code_snippet, "type": "code"})

        return references

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
            key = (ref_path_str, ref_line, text, ref_type)
            if key in seen:
                continue

            seen.add(key)
            filtered_ref: ImpactReference = {
                "file": ref_path_str,
                "line": ref_line,
                "text": text,
                "type": ref_type,
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

    def _is_supported_impact_file(self, path: Path, gitignore_patterns: set[str]) -> bool:
        """Return whether impact analysis should report a file as code."""
        return path.suffix.lower() in LANGUAGE_MAP and not self._should_exclude(path, gitignore_patterns)

    def _text_search(self, symbol_name: str, context_lines: int) -> list[ImpactReference]:
        """Unified text search (ripgrep -> python fallback)."""
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
                                    }
                                )
                        except json.JSONDecodeError:
                            continue
                return references
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

    def _python_text_search(self, symbol_name: str) -> list[ImpactReference]:
        """Fallback text search using Python when ripgrep is not available."""
        references: list[ImpactReference] = []
        gitignore_patterns = self._parse_gitignore()

        # Create word boundary pattern
        pattern = re.compile(r"\b" + re.escape(symbol_name) + r"\b")

        for file_path in self.root_path.rglob("*"):
            if not file_path.is_file():
                continue

            # Skip excluded files
            if self._should_exclude(file_path, gitignore_patterns):
                continue

            # Only search in source files
            if file_path.suffix.lower() not in LANGUAGE_MAP:
                continue

            try:
                with open(file_path, encoding="utf-8") as f:
                    for line_num, line in enumerate(f, 1):
                        if pattern.search(line):
                            references.append({"file": str(file_path), "line": line_num, "text": line.strip()})
            except Exception:
                continue

        return references
