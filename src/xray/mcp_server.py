"""XRAY MCP Server - Progressive code discovery in 4 steps: Map, Find, Interface, Impact.

🚀 THE XRAY WORKFLOW (Progressive Discovery):
1. explore_repo() - Start with directory structure, then zoom in with symbols
2. find_symbol() - Find specific functions/classes you need to analyze
3. read_interface() - Peek at a file's structure (signatures/docs) without reading implementation
4. what_breaks() - See where that symbol is used (impact analysis)

PROGRESSIVE DISCOVERY EXAMPLE:
```python
# Step 1: Get the lay of the land
repo_map = explore_repo("/Users/john/myproject")

# Step 2: Find the specific function
symbols = find_symbol("/Users/john/myproject", "validate user")

# Step 3: Check the file interface if unsure
interface = read_interface("/Users/john/myproject", symbols[0]['path'])

# Step 4: See impact
impact = what_breaks(symbols[0])
```

KEY FEATURES:
- Structural Analysis: Uses ast-grep to find ACTUAL code references, ignoring comments/strings.
- Progressive Discovery: Start simple, then add detail.
- Smart Caching: Instant re-runs.
- Stateless: No database to manage.
"""

import asyncio
import os
import threading
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
_indexer_cache: dict[str, XRayIndexer] = {}
_indexer_locks: dict[str, threading.RLock] = {}
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
4. Check change impact with `what_breaks`.
   Pass the entire symbol object from `find_symbol`.

Use `search_tools` to discover operations, then execute one through `call_tool`.
"""

READ_ONLY_TOOL_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
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
        "4. Call what_breaks with the full symbol object before changing public code.\n\n"
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


def get_indexer(path: str) -> XRayIndexer:
    """Get or create indexer instance for the given path."""
    path = normalize_path(path)
    with _indexer_cache_lock:
        if path not in _indexer_cache:
            _indexer_cache[path] = XRayIndexer(path)
            _indexer_locks[path] = threading.RLock()
        return _indexer_cache[path]


def run_indexer_operation(path: str, operation: Callable[[XRayIndexer], T]) -> T:
    """Run blocking indexer work with per-repository serialization."""
    path = normalize_path(path)
    indexer = get_indexer(path)
    with _indexer_cache_lock:
        lock = _indexer_locks.setdefault(path, threading.RLock())
    with lock:
        return operation(indexer)


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
async def explore_repo(
    root_path: str,
    ctx: Context,
    max_depth: int | str | None = None,
    include_symbols: bool | str = False,
    focus_dirs: list[str] | None = None,
    max_symbols_per_file: int | str = 5,
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
        if isinstance(include_symbols, str):
            include_symbols = include_symbols.lower() in ("true", "1", "yes")

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
) -> dict[str, Any]:
    """Return structured MCP explore data with the compact text tree included."""
    tree = indexer.explore_repo(
        max_depth=max_depth,
        include_symbols=include_symbols,
        focus_dirs=focus_dirs,
        max_symbols_per_file=max_symbols_per_file,
    )
    data = dump_explore_data(
        indexer.explore_repo_data(
            max_depth=max_depth,
            include_symbols=include_symbols,
            focus_dirs=focus_dirs,
            max_symbols_per_file=max_symbols_per_file,
        )
    )
    data["tree_text"] = tree
    data["warnings"] = []
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
    """Find structural code references that may break if a symbol changes."""
    try:
        exact_symbol = validate_symbol_input(exact_symbol)
        symbol_path_value = exact_symbol.get("abs_path") or exact_symbol["path"]
        symbol_path = Path(symbol_path_value)
        if not symbol_path.is_absolute():
            return {"error": "what_breaks requires an absolute symbol path or abs_path when called via MCP."}
        symbol_path = symbol_path.resolve()
        root_path = str(symbol_path.parent)
        symbol_for_indexer = dict(exact_symbol)
        symbol_for_indexer["path"] = str(symbol_path)

        # Find a suitable root (go up until we find a git repo or reach root)
        while root_path != "/":
            if (Path(root_path) / ".git").exists():
                break
            parent = Path(root_path).parent
            if parent == Path(root_path):
                break
            root_path = str(parent)

        result = run_indexer_operation(
            root_path,
            lambda indexer: indexer.what_breaks(symbol_for_indexer),
        )
        return dump_impact_result(result)
    except Exception as e:
        return {"error": f"Error finding references: {e!s}"}


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
                },
            ),
            "find_symbol": ToolTransformConfig(
                description="Find definitions: functions, methods, classes, types, enums, and code symbols.",
                tags={"find", "symbol", "search", "function", "class"},
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
                    "Find breaking change impact, usage, and dependency impact: where a symbol is used by code; "
                    "uses, callers, references, dependencies, dependents, and blast radius."
                ),
                tags={"impact", "usage", "references", "callers", "dependencies"},
                arguments={
                    "exact_symbol": ArgTransformConfig(
                        description="Full symbol object from find_symbol, including absolute path and line data."
                    ),
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
