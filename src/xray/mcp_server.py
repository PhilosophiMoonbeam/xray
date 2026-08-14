"""XRAY's search-first stdio MCP server."""

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

from xray.core.indexer import InterfaceReadError, XRayIndexer
from xray.models import (
    dump_explore_data,
    dump_impact_result,
    dump_interface_data,
    dump_symbol_output,
    validate_symbol_input,
)
from xray.presentation import (
    DEFAULT_RESULT_LIMIT,
    compact_explore,
    compact_impact_references,
    compact_structural_items,
    cursor_fingerprint,
    decode_cursor,
    page_items,
)

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

Discover tools with `search_tools`, which accepts a regular expression and returns at most 10 matches.
Use a focused literal or alternation such as `interface|signature`; do not use `.` to inventory the surface.
Execute one discovered operation through `call_tool` with its exact name and arguments.

Use XRAY as map -> find -> interface -> impact:

1. Map the repository with `explore_repo`.
   Compact output returns relative-path `entries`; request `detail="full"` only when `tree_text` is needed.
   Start shallow; add `focus_dirs` or `include_symbols=True` only when zooming in.
2. Locate code with `find_symbol`.
   Keep the returned symbol object, including path and line data.
3. Inspect source contracts with `read_interface_structured` when typed hierarchy,
   documentation, and completeness matter. `read_interface` preserves the legacy text projection.
   Python uses enriched standard-library AST data; other supported languages expose ast-grep completeness warnings.
4. Check likely symbol-name code references with `what_breaks`.
   Pass the entire symbol object from `find_symbol`.
   This is not a type-aware caller, dependent, or dependency graph.

For structural discovery, `search_pattern`, read-only `scan_rules`, `file_imports`, and `file_exports`
return at most 50 compact items by default. Check `returned`, `total`, `total_exact`, and `truncated`; pass
`next_cursor` back as `cursor` only with the identical root, arguments, and unchanged source snapshot.
Request `detail="full"` only for raw ast-grep metadata. `rewrite_pattern` and `scan_rules(fix=True)` modify every match
regardless of the reporting limit and never support continuation after mutation.
For replacement, call read-only `plan_replacement`, review every count, path, warning, hash, preview,
and `plan_digest`, then pass the complete plan plus an independently copied digest to destructive
`apply_replacement`. It rejects query or source drift before writing and rolls back partial application.
Pass `lang` whenever known for pattern plans and rewrites. Keep `rewrite_pattern` only for explicit
legacy all-match mutation.
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
        "Use a focused search_tools regular expression, then call the discovered tool through call_tool.\n"
        "Use XRAY progressively:\n"
        "1. Call explore_repo; use compact entries for file selection and request detail='full' only for tree_text.\n"
        "2. Call find_symbol with the most relevant symbol or behavior phrase.\n"
        "3. Call read_interface_structured for typed hierarchy/completeness, or read_interface for legacy text.\n"
        "4. Call what_breaks with the full symbol object before changing public code; "
        "treat results as name-based references, not a type-aware dependency graph.\n\n"
        "For structural reads, inspect returned/total/total_exact/truncated and continue next_cursor only with "
        "identical arguments and an unchanged source snapshot. For mutation, call plan_replacement, review the "
        "complete plan and digest, then call apply_replacement with that plan and an independently copied digest. "
        "For pattern plans or rewrites, pass lang whenever the target language is known. "
        "Legacy rewrite and scan fixes still apply every match and cannot be continued.\n\n"
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
    detail: str = "compact",
    use_default_exclusions: bool | str = True,
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
        if isinstance(use_default_exclusions, str):
            use_default_exclusions = use_default_exclusions.lower() in ("true", "1", "yes")
        if isinstance(symbol_types, str):
            symbol_types = [value.strip() for value in symbol_types.split(",") if value.strip()]
        if max_entries < 1:
            raise ValueError("max_entries must be 1 or greater.")
        _validate_detail(detail)

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
                detail,
                use_default_exclusions,
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
    detail: str = "compact",
    use_default_exclusions: bool = True,
) -> dict[str, Any]:
    """Return compact repository entries or the full legacy map payload."""
    _validate_detail(detail)
    data = dump_explore_data(
        indexer.explore_repo_data(
            max_depth=max_depth,
            include_symbols=include_symbols,
            focus_dirs=focus_dirs,
            max_symbols_per_file=max_symbols_per_file,
            symbol_types=symbol_types,
            max_entries=max_entries,
            use_default_exclusions=use_default_exclusions,
        )
    )
    result = data if detail == "full" else compact_explore(data)
    warnings = (
        [f"Explore output truncated at {max_entries} entries; narrow with focus_dirs/max_depth or raise max_entries."]
        if data["truncated"]
        else []
    )
    if warnings:
        result["warnings"] = warnings
    elif detail == "full":
        result["warnings"] = []
    return result


def _validate_detail(detail: str) -> None:
    if detail not in {"compact", "full"}:
        raise ValueError("detail must be 'compact' or 'full'.")


def _prepare_page(
    root_path: str,
    command: str,
    identity: dict[str, Any],
    limit: int | str,
    cursor: str | None,
) -> tuple[str, int, dict[str, Any], int]:
    """Bind paging to repository content before running read or mutation work."""
    normalized = normalize_path(root_path)
    try:
        parsed_limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer.") from exc
    if parsed_limit < 0:
        raise ValueError("limit must be 0 or greater.")
    snapshot = run_indexer_operation(normalized, lambda indexer: indexer.repository_snapshot_fingerprint())
    bound_identity = {**identity, "source_snapshot": snapshot}
    offset = decode_cursor(cursor, cursor_fingerprint(command, Path(normalized), bound_identity))
    return normalized, parsed_limit, bound_identity, offset


def _present_items(
    raw_items: list[dict[str, Any]],
    *,
    root_path: str,
    command: str,
    identity: dict[str, Any],
    detail: str,
    limit: int,
    cursor: str | None,
    continuable: bool = True,
    total_exact: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _validate_detail(detail)
    items = raw_items if detail == "full" else compact_structural_items(raw_items, Path(root_path))
    page, metadata = page_items(
        items,
        command=command,
        root_path=Path(root_path),
        identity=identity,
        limit=limit,
        cursor=cursor,
        continuable=continuable,
        total_exact=total_exact,
    )
    return [dict(item) for item in page], metadata


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
async def find_symbol(root_path: str, query: str, ctx: Context) -> list[dict[str, Any]]:
    """Find functions, classes, methods, or types by fuzzy query."""
    try:
        await ctx.info(f"Finding symbols for query: {query}")
        await ctx.report_progress(0, 2, "normalizing repository path")
        normalized_root = normalize_path(root_path)
        await ctx.report_progress(1, 2, "searching symbols")
        results = await asyncio.to_thread(
            run_indexer_operation,
            normalized_root,
            lambda indexer: indexer.find_symbol(query),
        )
        normalized_results: list[dict[str, Any]] = []
        for result in results:
            value = dict(result)
            path = Path(str(value.get("path", "")))
            value["abs_path"] = str(path.resolve() if path.is_absolute() else (Path(normalized_root) / path).resolve())
            normalized_results.append(dump_symbol_output(value))
        results = normalized_results
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
def read_interface_structured(root_path: str, file_path: str) -> dict[str, Any]:
    """Return a hierarchical typed interface with completeness and warnings."""
    try:
        return run_indexer_operation(
            root_path,
            lambda indexer: dump_interface_data(indexer.read_interface_structured(file_path)),
        )
    except InterfaceReadError as exc:
        return {"error": {"code": exc.code, "message": str(exc)}}
    except Exception as exc:
        return {"error": {"code": "internal_error", "message": str(exc)}}


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def what_breaks(
    exact_symbol: dict[str, Any],
    limit: int | str = DEFAULT_RESULT_LIMIT,
    cursor: str | None = None,
    detail: str = "compact",
) -> dict[str, Any]:
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
        _validate_detail(detail)
        identity = {
            "symbol": {
                key: exact_symbol.get(key) for key in ("name", "path", "abs_path", "start_line", "end_line", "type")
            },
            "detail": detail,
        }
        normalized, parsed_limit, identity, offset = _prepare_page(str(root_path), "impact", identity, limit, cursor)
        result = run_indexer_operation(
            normalized,
            lambda indexer: indexer.what_breaks(
                symbol_for_indexer,
                max_results=offset + parsed_limit + 1,
            ),
        )
        references = (
            result["references"]
            if detail == "full"
            else compact_impact_references(result["references"], Path(normalized), str(exact_symbol["name"]))
        )
        page, metadata = page_items(
            references,
            command="impact",
            root_path=Path(normalized),
            identity=identity,
            limit=parsed_limit,
            cursor=cursor,
            total_exact=bool(result.get("total_exact", True)),
        )
        return dump_impact_result({**result, "references": page, **metadata})
    except Exception as e:
        return {"error": f"Error finding references: {e!s}"}


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def search_pattern(
    root_path: str,
    pattern: str,
    lang: str | None = None,
    limit: int | str = DEFAULT_RESULT_LIMIT,
    cursor: str | None = None,
    detail: str = "compact",
    paths: list[str] | None = None,
    globs: list[str] | None = None,
) -> dict[str, Any]:
    """Return bounded compact structural matches, with full detail available on request."""
    try:
        _validate_detail(detail)
        identity = {"pattern": pattern, "lang": lang, "paths": paths or [], "globs": globs or []}
        normalized, parsed_limit, identity, offset = _prepare_page(root_path, "search", identity, limit, cursor)
        matches, total_exact = run_indexer_operation(
            normalized,
            lambda indexer: (
                indexer.search_pattern(
                    pattern,
                    lang,
                    paths=paths,
                    globs=globs,
                    max_results=offset + parsed_limit + 1,
                ),
                indexer.last_result_total_exact,
            ),
        )
        page, metadata = _present_items(
            matches,
            root_path=normalized,
            command="search",
            identity=identity,
            detail=detail,
            limit=parsed_limit,
            cursor=cursor,
            total_exact=total_exact,
        )
        result = {"matches": page, **metadata}
        if detail == "full":
            result.update({"match_count": len(matches), "pattern": pattern, "language": lang})
        return result
    except Exception as e:
        return {"error": f"Error searching pattern: {e!s}"}


@mcp.tool(annotations=DESTRUCTIVE_TOOL_ANNOTATIONS)
def rewrite_pattern(
    root_path: str,
    pattern: str,
    replacement: str,
    lang: str | None = None,
    limit: int | str = DEFAULT_RESULT_LIMIT,
    detail: str = "compact",
) -> dict[str, Any]:
    """Rewrite every match in place and return a compact summary or bounded full diagnostics."""
    try:
        _validate_detail(detail)
        identity = {"pattern": pattern, "replacement": replacement, "lang": lang}
        normalized, parsed_limit, identity, _offset = _prepare_page(root_path, "rewrite", identity, limit, None)
        summary = run_indexer_operation(normalized, lambda indexer: indexer.rewrite_pattern(pattern, replacement, lang))
        matches = summary.pop("matches", [])
        if detail == "full":
            page, metadata = _present_items(
                matches,
                root_path=normalized,
                command="rewrite",
                identity=identity,
                detail="full",
                limit=parsed_limit,
                cursor=None,
                continuable=False,
                total_exact=True,
            )
            summary.update({"matches": page, **metadata})
        return summary
    except Exception as e:
        return {"error": f"Error rewriting pattern: {e!s}"}


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def plan_replacement(
    root_path: str,
    pattern: str | None = None,
    replacement: str | None = None,
    rule_path: str | None = None,
    lang: str | None = None,
    paths: list[str] | None = None,
    globs: list[str] | None = None,
    max_matches: int = 1000,
    max_files: int = 100,
    allow_noop: bool = False,
    preview_limit: int = 50,
) -> dict[str, Any]:
    """Create an exact non-mutating replacement plan for independent review."""
    try:
        return run_indexer_operation(
            root_path,
            lambda indexer: indexer.plan_replacement(
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
            ),
        )
    except Exception as exc:
        return {"error": f"Error planning replacement: {exc}"}


@mcp.tool(annotations=DESTRUCTIVE_TOOL_ANNOTATIONS)
def apply_replacement(root_path: str, plan: dict[str, Any], expected_digest: str) -> dict[str, Any]:
    """Apply a complete reviewed plan only if digest, root, query, and source guards still match."""
    try:
        return run_indexer_operation(
            root_path,
            lambda indexer: indexer.apply_replacement(plan, expected_digest=expected_digest),
        )
    except Exception as exc:
        return {"error": f"Error applying replacement: {exc}"}


@mcp.tool(annotations=DESTRUCTIVE_TOOL_ANNOTATIONS)
def scan_rules(
    root_path: str,
    rule_path: str,
    fix: bool = False,
    limit: int | str = DEFAULT_RESULT_LIMIT,
    cursor: str | None = None,
    detail: str = "compact",
    paths: list[str] | None = None,
    globs: list[str] | None = None,
) -> dict[str, Any]:
    """Return bounded rule diagnostics or apply every configured fix without continuation."""
    try:
        _validate_detail(detail)
        if fix and cursor:
            raise ValueError("cursor cannot be used when fix is true because fixes mutate the result set.")
        identity = {"rule_path": rule_path, "fix": fix, "paths": paths or [], "globs": globs or []}
        normalized, parsed_limit, identity, offset = _prepare_page(root_path, "scan", identity, limit, cursor)
        matches, total_exact, mutation_summary = run_indexer_operation(
            normalized,
            lambda indexer: (
                indexer.scan_rules(
                    rule_path,
                    fix,
                    paths=paths,
                    globs=globs,
                    max_results=None if fix else offset + parsed_limit + 1,
                ),
                indexer.last_result_total_exact,
                indexer.last_mutation_summary if fix else None,
            ),
        )
        page, metadata = _present_items(
            matches,
            root_path=normalized,
            command="scan",
            identity=identity,
            detail=detail,
            limit=parsed_limit,
            cursor=cursor,
            continuable=not fix,
            total_exact=total_exact,
        )
        result = {"matches": page, "fixed": fix, **metadata}
        if mutation_summary is not None:
            result["mutation"] = mutation_summary
        if detail == "full":
            result["match_count"] = len(matches)
        return result
    except Exception as e:
        return {"error": f"Error scanning rules: {e!s}"}


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def file_imports(
    root_path: str,
    file_path: str,
    limit: int | str = DEFAULT_RESULT_LIMIT,
    cursor: str | None = None,
    detail: str = "compact",
) -> dict[str, Any]:
    """Return bounded compact imports, flattening ast-grep outline wrappers."""
    try:
        _validate_detail(detail)
        identity = {"file_path": file_path}
        normalized, parsed_limit, identity, _offset = _prepare_page(root_path, "imports", identity, limit, cursor)
        items = run_indexer_operation(normalized, lambda indexer: indexer.file_outline_items(file_path, "imports"))
        page, metadata = _present_items(
            items,
            root_path=normalized,
            command="imports",
            identity=identity,
            detail=detail,
            limit=parsed_limit,
            cursor=cursor,
        )
        result = {"items": page, **metadata}
        if detail == "full":
            result["file_path"] = file_path
        return result
    except Exception as e:
        return {"error": f"Error listing imports: {e!s}"}


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def file_exports(
    root_path: str,
    file_path: str,
    limit: int | str = DEFAULT_RESULT_LIMIT,
    cursor: str | None = None,
    detail: str = "compact",
) -> dict[str, Any]:
    """Return bounded compact exports, flattening ast-grep outline wrappers."""
    try:
        _validate_detail(detail)
        identity = {"file_path": file_path}
        normalized, parsed_limit, identity, _offset = _prepare_page(root_path, "exports", identity, limit, cursor)
        items = run_indexer_operation(normalized, lambda indexer: indexer.file_outline_items(file_path, "exports"))
        page, metadata = _present_items(
            items,
            root_path=normalized,
            command="exports",
            identity=identity,
            detail=detail,
            limit=parsed_limit,
            cursor=cursor,
        )
        result = {"items": page, **metadata}
        if detail == "full":
            result["file_path"] = file_path
        return result
    except Exception as e:
        return {"error": f"Error listing exports: {e!s}"}


mcp.add_transform(
    ToolTransform(
        {
            "explore_repo": ToolTransformConfig(
                description=(
                    "Map repository overview, layout, and file tree as compact relative-path entries; optionally "
                    "include symbols or request full detail for tree_text and absolute paths."
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
                    "detail": ArgTransformConfig(description="compact (default) or full repository-map detail."),
                    "use_default_exclusions": ArgTransformConfig(
                        description="Apply named built-in generated-state exclusions; repository ignores remain active."
                    ),
                },
            ),
            "find_symbol": ToolTransformConfig(
                description="Find symbols and definitions: functions, methods, classes, types, and enums.",
                tags={"find", "symbol", "search", "function", "class", "type", "method", "enum", "definitions"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path to search."),
                    "query": ArgTransformConfig(description="Symbol name or behavior phrase to find."),
                },
            ),
            "read_interface": ToolTransformConfig(
                description=(
                    "Read a source API interface summary with signatures, contracts, classes, documentation, and "
                    "docstrings, without implementation body text."
                ),
                tags={"interface", "signature", "contract", "docstring", "summary"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path."),
                    "file_path": ArgTransformConfig(description="File path, absolute or relative to root_path."),
                },
            ),
            "read_interface_structured": ToolTransformConfig(
                description=(
                    "Read a structured source API interface with signatures, ranges, visibility, documentation, "
                    "completeness, and warnings without implementation bodies."
                ),
                tags={"interface", "structured", "signature", "contract", "docstring", "hierarchy"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path."),
                    "file_path": ArgTransformConfig(description="File path inside root_path."),
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
                    "limit": ArgTransformConfig(description="Maximum returned references; defaults to 50."),
                    "cursor": ArgTransformConfig(description="Snapshot-bound continuation cursor."),
                    "detail": ArgTransformConfig(description="compact (default) or full reference context."),
                },
            ),
            "search_pattern": ToolTransformConfig(
                description=(
                    "Run structural search with an ast-grep pattern and return at most 50 compact matches, including "
                    "useful captured metavariables. Continue truncated read-only results with next_cursor and "
                    "request full detail only for raw ast-grep metadata."
                ),
                tags={"search", "structural", "pattern", "ast-grep"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path to search."),
                    "pattern": ArgTransformConfig(
                        description="ast-grep structural pattern with optional metavariables."
                    ),
                    "lang": ArgTransformConfig(description="Optional ast-grep pattern language."),
                    "limit": ArgTransformConfig(description="Maximum returned matches; defaults to 50."),
                    "cursor": ArgTransformConfig(
                        description=(
                            "Opaque next_cursor from the identical root, pattern, language, scopes, and unchanged "
                            "source snapshot."
                        )
                    ),
                    "detail": ArgTransformConfig(description="compact (default) or full ast-grep match detail."),
                    "paths": ArgTransformConfig(description="Optional contained file/directory scopes."),
                    "globs": ArgTransformConfig(description="Optional ordered ast-grep glob filters."),
                },
            ),
            "rewrite_pattern": ToolTransformConfig(
                description=(
                    "Rewrite pattern matches in place across every matching AST structure. Compact output is a "
                    "count/path summary; "
                    "full diagnostics are bounded and never support continuation after mutation. Pass lang "
                    "whenever the target language is known to avoid matching pattern-like non-code text."
                ),
                tags={"rewrite", "replace", "structural", "ast-grep"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path to modify."),
                    "pattern": ArgTransformConfig(description="ast-grep structural pattern to replace."),
                    "replacement": ArgTransformConfig(description="ast-grep replacement template."),
                    "lang": ArgTransformConfig(
                        description="Target language; supply it when known to constrain destructive rewrite scope."
                    ),
                    "limit": ArgTransformConfig(
                        description="Maximum full-detail diagnostics returned; every match is still rewritten."
                    ),
                    "detail": ArgTransformConfig(description="compact summary (default) or full match detail."),
                },
            ),
            "plan_replacement": ToolTransformConfig(
                description=(
                    "Create a bounded replacement plan without mutation. It returns exact source hashes, "
                    "counts, warnings, edits, and a digest required by apply_replacement."
                ),
                tags={"replace", "plan", "preview", "rewrite", "safe", "ast-grep"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path to inspect."),
                    "pattern": ArgTransformConfig(description="Pattern source; pair with replacement."),
                    "replacement": ArgTransformConfig(description="Replacement template paired with pattern."),
                    "rule_path": ArgTransformConfig(description="Alternative fix-bearing rule/config inside root."),
                    "lang": ArgTransformConfig(
                        description="Target language; supply it when known to constrain pattern-plan scope."
                    ),
                    "paths": ArgTransformConfig(description="Optional contained file/directory scopes."),
                    "globs": ArgTransformConfig(description="Optional ordered ast-grep glob filters."),
                    "max_matches": ArgTransformConfig(description="Maximum exact candidate count."),
                    "max_files": ArgTransformConfig(description="Maximum affected file count."),
                    "allow_noop": ArgTransformConfig(description="Record permission for an all-no-op apply."),
                    "preview_limit": ArgTransformConfig(description="Maximum preview edits returned."),
                },
            ),
            "apply_replacement": ToolTransformConfig(
                description=(
                    "Apply replacement from a complete reviewed plan only when its independently supplied digest and "
                    "every "
                    "root, query, candidate, count, and source-hash guard still match."
                ),
                tags={"replace", "apply", "guarded", "rewrite", "destructive"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute root exactly matching the plan."),
                    "plan": ArgTransformConfig(description="Complete plan object returned by plan_replacement."),
                    "expected_digest": ArgTransformConfig(description="Independently copied reviewed plan digest."),
                },
            ),
            "scan_rules": ToolTransformConfig(
                description=(
                    "Scan rules read-only by default for bounded compact ast-grep diagnostics and continuation. "
                    "When fix is true, apply every configured fix and do not continue against the changed worktree."
                ),
                tags={"scan", "lint", "rules", "ast-grep"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path to scan."),
                    "rule_path": ArgTransformConfig(description="Rule file or config directory inside root_path."),
                    "fix": ArgTransformConfig(description="Apply every configured rule fix in place when true."),
                    "limit": ArgTransformConfig(
                        description="Maximum returned diagnostics; does not limit fixes and defaults to 50."
                    ),
                    "cursor": ArgTransformConfig(description="Opaque next_cursor; invalid when fix is true."),
                    "detail": ArgTransformConfig(description="compact (default) or full ast-grep diagnostic detail."),
                    "paths": ArgTransformConfig(description="Optional contained file/directory scopes."),
                    "globs": ArgTransformConfig(description="Optional ordered ast-grep glob filters."),
                },
            ),
            "file_imports": ToolTransformConfig(
                description=(
                    "List file imports as at most 50 compact flattened items for dependency inspection; continue "
                    "truncated results with next_cursor or request full outline wrappers."
                ),
                tags={"imports", "dependencies", "outline"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path."),
                    "file_path": ArgTransformConfig(description="File path inside root_path."),
                    "limit": ArgTransformConfig(description="Maximum returned imports; defaults to 50."),
                    "cursor": ArgTransformConfig(
                        description="Opaque next_cursor from the identical root and file query."
                    ),
                    "detail": ArgTransformConfig(description="compact (default) or full ast-grep outline detail."),
                },
            ),
            "file_exports": ToolTransformConfig(
                description=(
                    "List file exports as at most 50 compact flattened items for public-API inspection; continue "
                    "truncated results with next_cursor or request full outline wrappers."
                ),
                tags={"exports", "api", "outline"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path."),
                    "file_path": ArgTransformConfig(description="File path inside root_path."),
                    "limit": ArgTransformConfig(description="Maximum returned exports; defaults to 50."),
                    "cursor": ArgTransformConfig(
                        description="Opaque next_cursor from the identical root and file query."
                    ),
                    "detail": ArgTransformConfig(description="compact (default) or full ast-grep outline detail."),
                },
            ),
        }
    )
)

mcp.add_transform(RegexSearchTransform(max_results=10))


def main():
    """Run the installed XRAY MCP command over its supported stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
