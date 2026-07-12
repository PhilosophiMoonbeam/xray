"""XRAY MCP Server - Progressive code discovery in 4 steps: Map, Find, Interface, Impact.

🚀 THE XRAY WORKFLOW (Progressive Discovery):
1. explore_repo() - Start with directory structure, then zoom in with symbols
2. find_symbol() - Find specific functions/classes you need to analyze
3. read_interface() - Peek at a file's structure (signatures/docs) without reading implementation
4. what_breaks() - Find likely code references to that symbol name

PROGRESSIVE DISCOVERY EXAMPLE:
```python
# Step 1: Get the lay of the land
repo_map = explore_repo("/Users/john/myproject")

# Step 2: Find the specific function
symbols = find_symbol("/Users/john/myproject", "validate user")

# Step 3: Check the file interface if unsure
interface = read_interface("/Users/john/myproject", symbols[0]['path'])

# Step 4: Review likely symbol-name references
impact = what_breaks(symbols[0])
```

KEY FEATURES:
- Structural Analysis: Uses ast-grep to find likely symbol-name code references.
- Progressive Discovery: Start simple, then add detail.
- Smart Caching: Instant re-runs.
- Stateless: No database to manage.
"""

import asyncio
import os
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from fastmcp import Context, FastMCP
from fastmcp.server.providers.skills import SkillsDirectoryProvider
from fastmcp.server.transforms import ToolTransform
from fastmcp.server.transforms.search import RegexSearchTransform
from fastmcp.tools.tool_transform import ArgTransformConfig, ToolTransformConfig

from xray.core.indexer import XRayIndexer
from xray.models import dump_explore_data, dump_impact_result, dump_symbol_output, validate_symbol_input

# Initialize FastMCP server
mcp = FastMCP("XRAY Code Intelligence")

# Cache for indexer instances per repository path
INDEXER_CACHE_LIMIT_ENV = "XRAY_MCP_INDEXER_CACHE_LIMIT"
DEFAULT_INDEXER_CACHE_LIMIT = 32
_indexer_cache: OrderedDict[str, XRayIndexer] = OrderedDict()
_indexer_locks: dict[str, threading.RLock] = {}
_indexer_active_operations: dict[str, int] = {}
_indexer_cache_lock = threading.RLock()
T = TypeVar("T")

XRAY_WORKFLOW_GUIDE = """# XRAY Progressive Discovery

Use XRAY as map -> find -> interface -> impact:

1. Map the repository with `explore_repo`.
   It returns `entries` for file selection and `tree_text` for visual scanning.
   Start shallow; add `focus_dirs` or `include_symbols=True` only when zooming in.
2. Locate code with `find_symbol`.
   Keep the returned symbol object, including path and line data.
3. Inspect contracts with `read_interface`.
   It returns text signatures/classes/docstrings without implementation bodies.
4. Check likely symbol-name code references with `what_breaks`.
   Pass the entire symbol object from `find_symbol`.
   This is not a type-aware caller, dependent, or dependency graph.

Use `search_tools` to discover operations, then execute one through `call_tool`.
"""

READ_ONLY_TOOL_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
DESTRUCTIVE_TOOL_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": False,
}


@mcp.resource(
    "xray://workflow",
    name="xray_workflow",
    description="Detailed XRAY map -> find -> interface -> impact guidance.",
    mime_type="text/markdown",
    annotations={"readOnlyHint": True, "idempotentHint": True},
)
def xray_workflow() -> str:
    """Return detailed XRAY workflow guidance."""
    return XRAY_WORKFLOW_GUIDE


@mcp.prompt(
    name="xray_discovery_plan",
    description="Plan a compact XRAY discovery sequence for a code task.",
)
def xray_discovery_plan(goal: str = "understand a code change") -> str:
    """Create a short XRAY discovery plan for a client task."""
    return (
        f"Goal: {goal}\n\n"
        "Use XRAY progressively:\n"
        "1. Call explore_repo; use entries for file selection and tree_text for scanning.\n"
        "2. Call find_symbol with the most relevant symbol or behavior phrase.\n"
        "3. Call read_interface for text contracts when needed.\n"
        "4. Call what_breaks with the full symbol object before changing public code; "
        "treat results as name-based references, not a type-aware dependency graph.\n\n"
        "Fetch xray://workflow only if more detailed XRAY usage guidance is needed."
    )


mcp.add_provider(
    SkillsDirectoryProvider(
        roots=Path(__file__).parent / "skills",
        supporting_files="template",
    )
)


def normalize_path(path: str) -> str:
    """Normalize a path to absolute form."""
    path = os.path.expanduser(path)
    path = os.path.abspath(path)
    path = str(Path(path).resolve())
    if not os.path.exists(path):
        raise ValueError(f"Path '{path}' does not exist")
    if not os.path.isdir(path):
        raise ValueError(f"Path '{path}' is not a directory")
    return path


def get_indexer_cache_limit() -> int:
    """Return the configured MCP indexer cache entry limit."""
    raw_limit = os.environ.get(INDEXER_CACHE_LIMIT_ENV)
    if raw_limit is None:
        return DEFAULT_INDEXER_CACHE_LIMIT
    try:
        return max(0, int(raw_limit))
    except ValueError:
        return DEFAULT_INDEXER_CACHE_LIMIT


def _trim_indexer_cache_locked() -> None:
    """Evict least-recently-used inactive indexers until the cache is within its limit."""
    limit = get_indexer_cache_limit()
    while len(_indexer_cache) > limit:
        evicted_path = next(iter(_indexer_cache))
        if _indexer_active_operations.get(evicted_path, 0) > 0:
            return

        _indexer_cache.pop(evicted_path, None)
        _indexer_locks.pop(evicted_path, None)
        _indexer_active_operations.pop(evicted_path, None)


def _get_or_create_indexer_locked(path: str) -> tuple[XRayIndexer, threading.RLock]:
    """Return the cached indexer and lock for an already-normalized path."""
    if path not in _indexer_cache:
        _indexer_cache[path] = XRayIndexer(path)
        _indexer_locks[path] = threading.RLock()
    else:
        _indexer_cache.move_to_end(path)

    lock = _indexer_locks.setdefault(path, threading.RLock())
    return _indexer_cache[path], lock


def get_indexer(path: str) -> XRayIndexer:
    """Get or create indexer instance for the given path."""
    path = normalize_path(path)
    with _indexer_cache_lock:
        indexer, _lock = _get_or_create_indexer_locked(path)
        _trim_indexer_cache_locked()
        return indexer


def run_indexer_operation(path: str, operation: Callable[[XRayIndexer], T]) -> T:
    """Run blocking indexer work with per-repository serialization."""
    path = normalize_path(path)
    with _indexer_cache_lock:
        indexer, lock = _get_or_create_indexer_locked(path)
        _indexer_active_operations[path] = _indexer_active_operations.get(path, 0) + 1
        _trim_indexer_cache_locked()
    try:
        with lock:
            return operation(indexer)
    finally:
        with _indexer_cache_lock:
            active_count = _indexer_active_operations.get(path, 0) - 1
            if active_count > 0:
                _indexer_active_operations[path] = active_count
            else:
                _indexer_active_operations.pop(path, None)
            _trim_indexer_cache_locked()


def infer_symbol_root_path(exact_symbol: dict[str, Any], symbol_path: Path) -> Path:
    """Infer a repository root for MCP impact without falling back to filesystem root."""
    declared_path = Path(str(exact_symbol["path"]))
    if not declared_path.is_absolute():
        try:
            root_path = symbol_path.parents[len(declared_path.parts) - 1]
        except IndexError as exc:
            raise ValueError("what_breaks could not infer a repository root from the symbol path.") from exc
        if (root_path / declared_path).resolve() != symbol_path:
            raise ValueError("what_breaks symbol path and abs_path do not describe the same file.")
        return root_path

    for candidate in [symbol_path.parent, *symbol_path.parents]:
        if candidate == Path(candidate.anchor):
            break
        if (candidate / ".git").exists():
            return candidate

    raise ValueError(
        "what_breaks requires a CLI find symbol with relative path and abs_path, "
        "or an absolute symbol inside a git repo."
    )


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
async def explore_repo(
    root_path: str,
    ctx: Context,
    max_depth: int | str | None = None,
    include_symbols: bool | str = False,
    focus_dirs: list[str] | None = None,
    max_symbols_per_file: int | str = 5,
    symbol_types: list[str] | str | None = None,
    max_entries: int | str = 5000,
) -> dict[str, Any]:
    """Map repository structure, optionally including symbol skeletons."""
    try:
        await ctx.info(f"Exploring repository: {root_path}")
        await ctx.report_progress(0, 2, "normalizing repository path")
        # Convert string inputs to proper types (for LLMs that pass strings)
        if max_depth is not None and isinstance(max_depth, str):
            max_depth = int(max_depth)
        if isinstance(max_symbols_per_file, str):
            max_symbols_per_file = int(max_symbols_per_file)
        if isinstance(max_entries, str):
            max_entries = int(max_entries)
        if isinstance(include_symbols, str):
            include_symbols = include_symbols.lower() in ("true", "1", "yes")
        if isinstance(symbol_types, str):
            symbol_types = [value.strip() for value in symbol_types.split(",") if value.strip()]
        if max_entries < 1:
            raise ValueError("max_entries must be 1 or greater.")

        await ctx.report_progress(1, 2, "building repository map")
        result = await asyncio.to_thread(
            run_indexer_operation,
            root_path,
            lambda indexer: build_explore_result(
                indexer,
                max_depth,
                include_symbols,
                focus_dirs,
                max_symbols_per_file,
                symbol_types,
                max_entries,
            ),
        )
        await ctx.report_progress(2, 2, "repository map ready")
        return result
    except Exception as e:
        await ctx.error(f"Error exploring repository: {e}")
        return {"error": f"Error exploring repository: {e!s}"}


def build_explore_result(
    indexer: XRayIndexer,
    max_depth: int | None,
    include_symbols: bool,
    focus_dirs: list[str] | None,
    max_symbols_per_file: int,
    symbol_types: list[str] | None = None,
    max_entries: int = 5000,
) -> dict[str, Any]:
    """Return structured MCP explore data with the compact text tree included."""
    data = dump_explore_data(
        indexer.explore_repo_data(
            max_depth=max_depth,
            include_symbols=include_symbols,
            focus_dirs=focus_dirs,
            max_symbols_per_file=max_symbols_per_file,
            symbol_types=symbol_types,
            max_entries=max_entries,
        )
    )
    data["warnings"] = (
        [f"Explore output truncated at {max_entries} entries; narrow with focus_dirs/max_depth or raise max_entries."]
        if data["truncated"]
        else []
    )
    return data


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
async def find_symbol(root_path: str, query: str, ctx: Context) -> list[dict[str, Any]]:
    """Find functions, classes, methods, or types by fuzzy query."""
    try:
        await ctx.info(f"Finding symbols for query: {query}")
        await ctx.report_progress(0, 2, "normalizing repository path")
        await ctx.report_progress(1, 2, "searching symbols")
        results = await asyncio.to_thread(
            run_indexer_operation,
            root_path,
            lambda indexer: indexer.find_symbol(query),
        )
        results = [dump_symbol_output(result) for result in results]
        await ctx.report_progress(2, 2, f"found {len(results)} symbol matches")
        return results
    except Exception as e:
        await ctx.error(f"Error finding symbol: {e}")
        return [{"error": f"Error finding symbol: {e!s}"}]


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def read_interface(root_path: str, file_path: str) -> str:
    """Read signatures, class definitions, and docstrings for one file."""
    try:
        return run_indexer_operation(
            root_path,
            lambda indexer: indexer.read_interface(file_path),
        )
    except Exception as e:
        return f"Error reading interface: {e!s}"


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def what_breaks(exact_symbol: dict[str, Any]) -> dict[str, Any]:
    """Find likely symbol-name code references for impact review."""
    try:
        exact_symbol = validate_symbol_input(exact_symbol)
        symbol_path_value = exact_symbol.get("abs_path") or exact_symbol["path"]
        symbol_path = Path(symbol_path_value)
        if not symbol_path.is_absolute():
            return {"error": "what_breaks requires an absolute symbol path or abs_path when called via MCP."}
        symbol_path = symbol_path.resolve()
        root_path = infer_symbol_root_path(exact_symbol, symbol_path)
        symbol_for_indexer = dict(exact_symbol)
        symbol_for_indexer["path"] = str(symbol_path)

        result = run_indexer_operation(
            str(root_path),
            lambda indexer: indexer.what_breaks(symbol_for_indexer),
        )
        return dump_impact_result(result)
    except Exception as e:
        return {"error": f"Error finding references: {e!s}"}


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def search_pattern(root_path: str, pattern: str, lang: str | None = None) -> dict[str, Any]:
    """Search a repository with an ast-grep structural pattern."""
    try:
        matches = run_indexer_operation(root_path, lambda indexer: indexer.search_pattern(pattern, lang))
        return {"matches": matches, "match_count": len(matches), "pattern": pattern, "language": lang}
    except Exception as e:
        return {"error": f"Error searching pattern: {e!s}"}


@mcp.tool(annotations=DESTRUCTIVE_TOOL_ANNOTATIONS)
def rewrite_pattern(root_path: str, pattern: str, replacement: str, lang: str | None = None) -> dict[str, Any]:
    """Apply an ast-grep structural rewrite to repository files in place."""
    try:
        return run_indexer_operation(root_path, lambda indexer: indexer.rewrite_pattern(pattern, replacement, lang))
    except Exception as e:
        return {"error": f"Error rewriting pattern: {e!s}"}


@mcp.tool(annotations=DESTRUCTIVE_TOOL_ANNOTATIONS)
def scan_rules(root_path: str, rule_path: str, fix: bool = False) -> dict[str, Any]:
    """Scan a repository with ast-grep YAML rules, optionally applying fixes."""
    try:
        matches = run_indexer_operation(root_path, lambda indexer: indexer.scan_rules(rule_path, fix))
        return {"matches": matches, "match_count": len(matches), "fixed": fix}
    except Exception as e:
        return {"error": f"Error scanning rules: {e!s}"}


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def file_imports(root_path: str, file_path: str) -> dict[str, Any]:
    """List imports from one repository file using ast-grep outline."""
    try:
        items = run_indexer_operation(root_path, lambda indexer: indexer.file_outline_items(file_path, "imports"))
        return {"file_path": file_path, "items": items}
    except Exception as e:
        return {"error": f"Error listing imports: {e!s}"}


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def file_exports(root_path: str, file_path: str) -> dict[str, Any]:
    """List exports from one repository file using ast-grep outline."""
    try:
        items = run_indexer_operation(root_path, lambda indexer: indexer.file_outline_items(file_path, "exports"))
        return {"file_path": file_path, "items": items}
    except Exception as e:
        return {"error": f"Error listing exports: {e!s}"}


mcp.add_transform(
    ToolTransform(
        {
            "explore_repo": ToolTransformConfig(
                description=(
                    "Map repository overview, layout, and file tree as entries plus tree_text; "
                    "optionally include symbols."
                ),
                tags={"map", "tree", "discovery", "repository"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path to inspect."),
                    "max_depth": ArgTransformConfig(description="Optional directory depth limit."),
                    "include_symbols": ArgTransformConfig(description="Include function/class skeletons when true."),
                    "focus_dirs": ArgTransformConfig(description="Top-level directories to focus on."),
                    "max_symbols_per_file": ArgTransformConfig(description="Symbol skeleton limit per file."),
                    "symbol_types": ArgTransformConfig(
                        description="Optional symbol types to include, as a list or comma-separated string."
                    ),
                    "max_entries": ArgTransformConfig(description="Maximum map entries; truncation is reported."),
                },
            ),
            "find_symbol": ToolTransformConfig(
                description="Find definitions: functions, methods, classes, types, enums, and code symbols.",
                tags={"find", "symbol", "search", "function", "class", "type", "method", "enum", "definitions"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path to search."),
                    "query": ArgTransformConfig(description="Symbol name or behavior phrase to find."),
                },
            ),
            "read_interface": ToolTransformConfig(
                description="Read text API summary: signatures, contracts, classes, and docstrings without body text.",
                tags={"interface", "signature", "contract", "docstring", "summary"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path."),
                    "file_path": ArgTransformConfig(description="File path, absolute or relative to root_path."),
                },
            ),
            "what_breaks": ToolTransformConfig(
                description=(
                    "Find likely symbol-name code references for change impact review. "
                    "Use before breaking changes to inspect name-based usage and code that uses the same symbol name. "
                    "For 'used by' questions, this is an approximation. "
                    "This is not a type-aware caller, dependent, or dependency graph."
                ),
                tags={"impact", "usage", "references", "symbol-name", "approximate"},
                arguments={
                    "exact_symbol": ArgTransformConfig(
                        description="Full symbol object from find_symbol, including absolute path and line data."
                    ),
                },
            ),
            "search_pattern": ToolTransformConfig(
                description=(
                    "Search arbitrary AST structure with an ast-grep pattern and return captured metavariables."
                ),
                tags={"search", "structural", "pattern", "ast-grep"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path to search."),
                    "pattern": ArgTransformConfig(
                        description="ast-grep structural pattern with optional metavariables."
                    ),
                    "lang": ArgTransformConfig(description="Optional ast-grep pattern language."),
                },
            ),
            "rewrite_pattern": ToolTransformConfig(
                description="Rewrite matching AST structure in place across a repository; this modifies files.",
                tags={"rewrite", "replace", "structural", "ast-grep"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path to modify."),
                    "pattern": ArgTransformConfig(description="ast-grep structural pattern to replace."),
                    "replacement": ArgTransformConfig(description="ast-grep replacement template."),
                    "lang": ArgTransformConfig(description="Optional ast-grep pattern language."),
                },
            ),
            "scan_rules": ToolTransformConfig(
                description="Lint a repository with ast-grep YAML rules and optionally apply configured fixes.",
                tags={"scan", "lint", "rules", "ast-grep"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path to scan."),
                    "rule_path": ArgTransformConfig(description="Rule file or config directory inside root_path."),
                    "fix": ArgTransformConfig(description="Apply configured rule fixes in place when true."),
                },
            ),
            "file_imports": ToolTransformConfig(
                description="List a file's imports for immediate dependency inspection.",
                tags={"imports", "dependencies", "outline"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path."),
                    "file_path": ArgTransformConfig(description="File path inside root_path."),
                },
            ),
            "file_exports": ToolTransformConfig(
                description="List a file's exported public API declarations.",
                tags={"exports", "api", "outline"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path."),
                    "file_path": ArgTransformConfig(description="File path inside root_path."),
                },
            ),
        }
    )
)

mcp.add_transform(RegexSearchTransform(max_results=10))


def main():
    """Main entry point for the XRAY MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
