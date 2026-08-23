"""XRAY's search-first stdio MCP server."""

import asyncio
import hashlib
import json
import os
import re
import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar

from fastmcp import Context, FastMCP
from fastmcp.server.providers.skills import SkillsDirectoryProvider
from fastmcp.server.transforms import ToolTransform
from fastmcp.server.transforms.search.base import BaseSearchTransform
from fastmcp.tools import Tool, ToolResult
from fastmcp.tools.tool_transform import ArgTransformConfig, ToolTransformConfig

from xray.core.ast_grep import AstGrepError, AstGrepValidationError
from xray.core.indexer import InterfaceReadError, ReplacementApplyError, ReplacementDriftError, XRayIndexer
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
    compact_v3_impact,
    compact_v3_interface,
    cursor_fingerprint,
    decode_cursor,
    encode_cursor,
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


def mcp_error(code: str, message: str, *, details: dict[str, Any] | None = None) -> ToolResult:
    """Return one protocol-level typed MCP error with matching text and structured content."""
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    payload = {"error": error}
    return ToolResult(
        content=json.dumps(payload, separators=(",", ":"), sort_keys=True),
        structured_content=payload,
        is_error=True,
    )


XRAY_WORKFLOW_GUIDE = """# XRAY Progressive Discovery

Discover tools with ranked `search_tools`. Intent mode is the default; regex mode is explicit.
Use phrases such as `find usages` or `change function safely`. Results page with a cursor and summary detail.
Execute one discovered operation through `call_tool` with its exact name and arguments.

Use XRAY as map -> find -> interface -> impact:

1. Map the repository with `explore_repo`.
   Compact output returns relative-path `entries`; request `detail="full"` only when `tree_text` is needed.
   Start shallow; add `focus_dirs` or `include_symbols=True` only when zooming in.
2. Locate code with `find_symbol`.
   Keep the returned symbol object, including path and line data.
3. Inspect source contracts with `read_interface_structured` when typed hierarchy,
   documentation, and completeness matter. `read_interface` preserves the legacy text projection.
   Pass the complete find symbol as `exact_symbol`. Containers expand bounded
   members; members return only their owner path without siblings.
   Python uses enriched standard-library AST data; other supported languages expose ast-grep completeness warnings.
4. Check likely symbol-name code references with `what_breaks`.
   Pass the entire symbol object from `find_symbol`.
   This is not a type-aware caller, dependent, or dependency graph.

For structural discovery, `search_pattern`, read-only `scan_rules`, `file_imports`, and `file_exports`
return at most 50 compact items by default. Check `returned`, `total`, `total_exact`, and `truncated`; pass
`next_cursor` back as `cursor` with the same query/scopes, projection, and unchanged source snapshot;
the later page may use a different positive page size.
Request `detail="full"` only for raw ast-grep metadata. `scan_rules` is read-only. Build a reviewed rule plan with
`plan_replacement`, then use `apply_rule_fixes` for guarded rule mutation. `rewrite_pattern` remains a legacy
all-match mutation regardless of the reporting limit and never supports continuation after mutation.
For replacement, call read-only `plan_replacement`, review every edit in `edit_manifest`, syntax result,
dirty-file acknowledgement, warning, hash, diff, and `plan_digest`, then call `verify_replacement`.
Only then pass the complete plan plus an independently copied digest to destructive `apply_replacement`.
Apply revalidates syntax and source state before writing and rolls back partial application.
On results, use `rollback_status`: `not_attempted`, `succeeded`, or `failed`.
The plan `root_fingerprint` binds query/selection and affected preimages, so refinement may change it without drift.
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

DEFAULT_TOOL_SEARCH_LIMIT = 10
MAX_TOOL_SEARCH_LIMIT = 50
READ_ONLY_SEARCH_BASE_SCORE = 5
LEGACY_DISCOVERY_TERMS = {"legacy", "unsafe", "all-match", "all match", "destructive"}
MUTATION_INTENT_TERMS = {"change", "fix", "rename", "replace", "rewrite"}
TOOL_WORKFLOW_STAGES = {
    "explore_repo": "discover",
    "find_symbol": "discover",
    "search_pattern": "discover",
    "scan_rules": "discover",
    "file_imports": "discover",
    "file_exports": "discover",
    "read_interface": "inspect",
    "read_interface_structured": "inspect",
    "read_symbol": "inspect",
    "symbol_at": "inspect",
    "what_breaks": "analyze",
    "check_rules": "analyze",
    "explain_rules": "analyze",
    "test_rules": "analyze",
    "xray_capabilities": "inspect",
    "plan_replacement": "plan",
    "refine_replacement": "plan",
    "verify_replacement": "verify",
    "apply_replacement": "apply",
    "apply_rule_fixes": "apply",
    "rewrite_pattern": "legacy_mutate",
}
TOOL_INTENT_ALIASES = {
    "explore_repo": {"map", "tree", "repository overview", "layout", "file tree", "project structure"},
    "find_symbol": {"find", "find symbol", "lookup", "definition", "definitions", "function", "method", "class"},
    "read_interface": {"interface", "signature", "contract", "docstring", "api", "summary", "body"},
    "read_interface_structured": {"structured interface", "typed interface", "api hierarchy"},
    "read_symbol": {"read symbol", "source body", "implementation"},
    "symbol_at": {"symbol at line", "line data", "enclosing symbol"},
    "what_breaks": {
        "blast radius",
        "breaking change",
        "callers",
        "change impact",
        "find usages",
        "references",
        "used by",
        "usages",
        "who calls",
    },
    "search_pattern": {"structural search", "ast search", "code pattern"},
    "plan_replacement": {
        "change function safely",
        "fix",
        "rename",
        "rename symbol",
        "replace",
        "replace expression",
        "replacement plan",
        "safe change",
        "safe code replacement",
    },
    "refine_replacement": {"select edits", "refine replacement", "edit ids"},
    "verify_replacement": {"verify replacement", "validate replacement", "check replacement plan"},
    "apply_replacement": {"apply replacement", "approved replacement"},
    "scan_rules": {"scan rules", "rule diagnostics", "lint rules"},
    "check_rules": {"validate rule", "rule validation", "check rule"},
    "explain_rules": {"explain rule", "inspect rule"},
    "test_rules": {"test rule", "rule tests"},
    "apply_rule_fixes": {"apply rule fixes", "fix rule matches"},
    "file_imports": {"file imports", "imports", "dependencies"},
    "file_exports": {"file exports", "exports", "public api"},
    "xray_capabilities": {"help", "workflow", "capabilities", "doctor", "limits"},
    "rewrite_pattern": {"legacy rewrite", "unsafe rewrite", "all-match rewrite", "destructive rewrite"},
}
INTENT_SYNONYMS = {
    "calls": {"caller", "callers", "references", "usage"},
    "caller": {"callers", "references", "usage"},
    "callers": {"caller", "references", "usage"},
    "usage": {"references", "usages", "used"},
    "usages": {"references", "usage", "used"},
    "rename": {"change", "replace"},
    "validate": {"check", "verification"},
    "validation": {"check", "verification"},
}
WORKFLOW_STAGE_ORDER = {
    "discover": 0,
    "inspect": 1,
    "analyze": 2,
    "plan": 3,
    "verify": 4,
    "apply": 5,
    "legacy_mutate": 6,
}


class XRayToolSearchTransform(BaseSearchTransform):
    """Expose deterministic intent and explicit-regex discovery with bounded metadata."""

    @staticmethod
    def _tokens(value: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", value.casefold()))

    @staticmethod
    def _tool_dump(tool: Tool) -> dict[str, Any]:
        annotations: dict[str, Any] = {}
        if tool.annotations is not None:
            annotations = tool.annotations.model_dump(mode="json", by_alias=True, exclude_none=True)
        return {
            "name": tool.name,
            "description": tool.description or "",
            "tags": sorted(str(value) for value in tool.tags),
            "parameters": tool.parameters,
            "annotations": annotations,
        }

    @classmethod
    def _mutation_class(cls, tool: Tool) -> str:
        if tool.name == "rewrite_pattern":
            return "legacy_mutation"
        annotations = cls._tool_dump(tool).get("annotations", {})
        if annotations.get("destructiveHint"):
            return "guarded_mutation"
        return "read_only"

    @staticmethod
    def _legacy_intent(query: str) -> bool:
        normalized = " ".join(query.casefold().replace("_", " ").split())
        return any(term in normalized for term in LEGACY_DISCOVERY_TERMS)

    @classmethod
    def _catalog_digest(cls, tools: Sequence[Tool]) -> str:
        payload = [cls._tool_dump(tool) for tool in tools]
        return hashlib.sha256(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).hexdigest()[:24]

    @classmethod
    def _rank_intent(cls, tool: Tool, query: str) -> tuple[int, list[str]]:
        normalized = " ".join(query.casefold().replace("_", " ").split())
        query_tokens = cls._tokens(normalized)
        aliases = TOOL_INTENT_ALIASES.get(tool.name, set())
        dump = cls._tool_dump(tool)
        name_tokens = cls._tokens(tool.name)
        tag_tokens = cls._tokens(" ".join(str(value) for value in dump.get("tags", [])))
        description_tokens = cls._tokens(tool.description or "")
        parameter_tokens = cls._tokens(
            " ".join(str(value) for value in dump.get("parameters", {}).get("properties", {}))
        )
        alias_tokens = cls._tokens(" ".join(sorted(aliases)))
        score = 0
        reasons: list[str] = []
        if normalized == tool.name.casefold().replace("_", " "):
            score += 160
            reasons.append("exact_name")
        if normalized in aliases:
            score += 140
            reasons.append("exact_alias")
        for token in query_tokens:
            variants = {token, *INTENT_SYNONYMS.get(token, set())}
            if variants & name_tokens:
                score += 32
                reasons.append(f"name:{token}")
            if variants & tag_tokens:
                score += 24
                reasons.append(f"tag:{token}")
            if variants & alias_tokens:
                score += 20
                reasons.append(f"alias:{token}")
            if variants & description_tokens:
                score += 8
                reasons.append(f"description:{token}")
            if variants & parameter_tokens:
                score += 4
                reasons.append(f"parameter:{token}")
        stage = TOOL_WORKFLOW_STAGES.get(tool.name, "inspect")
        mutation_intent = bool(query_tokens & MUTATION_INTENT_TERMS)
        if mutation_intent and stage == "plan":
            score += 45
            reasons.append("safe_plan_first")
        if "verify" in query_tokens and stage == "verify":
            score += 70
            reasons.append("requested_verify_stage")
        if "apply" in query_tokens and stage == "apply":
            score += 70
            reasons.append("requested_apply_stage")
        if cls._mutation_class(tool) == "read_only":
            score += READ_ONLY_SEARCH_BASE_SCORE
        return score, list(dict.fromkeys(reasons))

    @classmethod
    def _rank_tools(
        cls, tools: Sequence[Tool], query: str, mode: Literal["intent", "regex"]
    ) -> list[tuple[Tool, int, list[str]]]:
        legacy_intent = cls._legacy_intent(query)
        broad = mode == "intent" and query.strip().casefold() in {".", "*", "all", "inventory", "tools"}
        compiled: re.Pattern[str] | None = None
        if mode == "regex":
            compiled = re.compile(query, re.IGNORECASE)
        ranked: list[tuple[Tool, int, list[str]]] = []
        for tool in tools:
            if tool.name == "rewrite_pattern" and not legacy_intent:
                continue
            score, reasons = cls._rank_intent(tool, query)
            if compiled is not None:
                searchable = json.dumps(cls._tool_dump(tool), separators=(",", ":"), sort_keys=True)
                match = compiled.search(searchable)
                if match is None:
                    continue
                score += 100 if compiled.fullmatch(tool.name) else 40
                reasons.append("regex_match")
            elif not broad and score <= READ_ONLY_SEARCH_BASE_SCORE:
                continue
            if legacy_intent and tool.name == "rewrite_pattern":
                score += 100
                reasons.append("explicit_legacy_intent")
            ranked.append((tool, score, list(dict.fromkeys(reasons))))
        ranked.sort(
            key=lambda item: (
                -item[1],
                WORKFLOW_STAGE_ORDER.get(TOOL_WORKFLOW_STAGES.get(item[0].name, "inspect"), 99),
                item[0].name,
            )
        )
        return ranked

    async def _search(self, tools: Sequence[Tool], query: str) -> Sequence[Tool]:
        return [item[0] for item in self._rank_tools(tools, query, "intent")[: self._max_results]]

    @classmethod
    def _summary(cls, tool: Tool, score: int, reasons: list[str]) -> dict[str, Any]:
        dump = cls._tool_dump(tool)
        return {
            "name": tool.name,
            "description": tool.description or "",
            "annotations": dump.get("annotations", {}),
            "tags": sorted(str(value) for value in dump.get("tags", [])),
            "parameters": sorted(str(value) for value in dump.get("parameters", {}).get("properties", {})),
            "mutation_class": cls._mutation_class(tool),
            "workflow_stage": TOOL_WORKFLOW_STAGES.get(tool.name, "inspect"),
            "score": score,
            "match_reasons": reasons,
        }

    def _make_search_tool(self) -> Tool:
        transform = self

        async def search_tools(
            pattern: Annotated[str, "Natural-language intent, or a regex when mode='regex'"],
            mode: Annotated[Literal["intent", "regex"], "intent (default) or explicit regex compatibility"] = "intent",
            limit: Annotated[int, "Page size from 1 to 50"] = DEFAULT_TOOL_SEARCH_LIMIT,
            cursor: Annotated[
                str | None, "next_cursor for the same catalog/query/detail; positive page size may change"
            ] = None,
            detail: Annotated[
                Literal["summary", "full"], "summary metadata (default) or complete tool schemas"
            ] = "summary",
            ctx: Context = None,  # type: ignore[assignment]
        ) -> dict[str, Any] | ToolResult:
            """Find tools by ranked intent or explicit regex with bounded, exact paging."""
            if limit < 1 or limit > MAX_TOOL_SEARCH_LIMIT:
                return mcp_error("invalid_request", f"limit must be between 1 and {MAX_TOOL_SEARCH_LIMIT}.")
            if not pattern:
                return mcp_error("invalid_request", "pattern must not be empty.")
            hidden = await transform._get_visible_tools(ctx)
            try:
                ranked = transform._rank_tools(hidden, pattern, mode)
            except re.error as exc:
                return mcp_error("invalid_regex", f"Invalid tool-search regex: {exc}.")
            identity = {
                "catalog": transform._catalog_digest(hidden),
                "pattern": pattern,
                "mode": mode,
                "detail": detail,
                "legacy_intent": transform._legacy_intent(pattern),
            }
            fingerprint = cursor_fingerprint("search_tools", Path("/"), identity)
            try:
                offset = decode_cursor(cursor, fingerprint)
            except ValueError as exc:
                return mcp_error("invalid_cursor", str(exc))
            page = ranked[offset : offset + limit]
            if detail == "full":
                rendered = await transform._render_results([item[0] for item in page])
                if not isinstance(rendered, list):
                    return mcp_error("search_failed", "FastMCP returned a non-list tool catalog projection.")
                matches = []
                for serialized, (_tool, score, reasons) in zip(rendered, page, strict=True):
                    match = dict(serialized)
                    match["discovery"] = transform._summary(_tool, score, reasons)
                    matches.append(match)
            else:
                matches = [transform._summary(tool, score, reasons) for tool, score, reasons in page]
            next_offset = offset + len(page)
            result: dict[str, Any] = {
                "query": pattern,
                "mode": mode,
                "detail": detail,
                "matches": matches,
                "returned": len(matches),
                "total": len(ranked),
                "total_exact": True,
                "truncated": next_offset < len(ranked),
                "catalog_total": len(hidden),
                "legacy_tools_included": transform._legacy_intent(pattern),
            }
            if result["truncated"]:
                result["next_cursor"] = encode_cursor(next_offset, fingerprint)
            return result

        return Tool.from_function(fn=search_tools, name=self._search_tool_name)


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
        "Use ranked search_tools intent search, then call the discovered tool through call_tool.\n"
        "Use XRAY progressively:\n"
        "1. Call explore_repo; use compact entries for file selection and request detail='full' only for tree_text.\n"
        "2. Call find_symbol with the most relevant symbol name or owner-qualified identity.\n"
        "3. Call read_interface_structured with exact_symbol to expand a container or isolate a member path, "
        "or read_interface for legacy text.\n"
        "4. Call what_breaks with the full symbol object before changing public code; "
        "treat results as name-based references, not a type-aware dependency graph.\n\n"
        "For structural reads, use a positive limit, inspect returned/total/total_exact/truncated, and continue "
        "next_cursor with the same query/projection and unchanged source; page size may change. For mutation, "
        "call plan_replacement, review the "
        "edit_manifest, syntax/dirty evidence, and digest; call verify_replacement; then call apply_replacement "
        "with that plan and an independently copied digest. "
        "For pattern plans or rewrites, pass lang whenever the target language is known. "
        "Legacy rewrite still applies every match and cannot be continued. Rule fixes require a reviewed plan.\n\n"
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
    max_depth: int | str | None = 2,
    all_depths: bool | str = False,
    include_symbols: bool | str = False,
    focus_dirs: list[str] | None = None,
    include_root_context: bool | str = True,
    max_symbols_per_file: int | str = 5,
    symbol_types: list[str] | str | None = None,
    max_entries: int | str = 5000,
    detail: str = "compact",
    use_default_exclusions: bool | str = True,
) -> dict[str, Any] | ToolResult:
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
        if isinstance(include_root_context, str):
            include_root_context = include_root_context.lower() in ("true", "1", "yes")
        if isinstance(all_depths, str):
            all_depths = all_depths.lower() in ("true", "1", "yes")
        if all_depths:
            max_depth = None
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
                indexer=indexer,
                max_depth=max_depth,
                include_symbols=include_symbols,
                focus_dirs=focus_dirs,
                max_symbols_per_file=max_symbols_per_file,
                symbol_types=symbol_types,
                max_entries=max_entries,
                detail=detail,
                use_default_exclusions=use_default_exclusions,
                include_root_context=include_root_context,
            ),
        )
        await ctx.report_progress(2, 2, "repository map ready")
        return result
    except Exception as e:
        await ctx.error(f"Error exploring repository: {e}")
        return mcp_error("invalid_request", str(e))


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
    include_root_context: bool = True,
) -> dict[str, Any] | ToolResult:
    """Return compact repository entries or the full legacy map payload."""
    _validate_detail(detail)
    data = dump_explore_data(
        indexer.explore_repo_data(
            max_depth=max_depth,
            include_symbols=include_symbols,
            focus_dirs=focus_dirs,
            include_root_context=include_root_context,
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


def _validate_schema(schema: str) -> None:
    if schema not in {"v2", "v3"}:
        raise ValueError("schema must be 'v2' or 'v3'.")


def _prepare_page(
    root_path: str,
    command: str,
    identity: dict[str, Any],
    limit: int | str,
    cursor: str | None,
    *,
    continuable: bool = True,
) -> tuple[str, int, dict[str, Any], int]:
    """Bind paging to repository content before running read or mutation work."""
    normalized = normalize_path(root_path)
    try:
        parsed_limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer.") from exc
    if continuable and parsed_limit < 1:
        raise ValueError("limit must be 1 or greater for a continuable read.")
    if not continuable and parsed_limit < 0:
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
    has_multi = any(
        isinstance(meta := item.get("metaVariables"), Mapping) and bool(meta.get("multi")) for item in raw_items
    )
    if detail == "compact" and has_multi:
        page, metadata = page_items(
            raw_items,
            command=command,
            root_path=Path(root_path),
            identity=identity,
            limit=limit,
            cursor=cursor,
            continuable=continuable,
            total_exact=total_exact,
        )
        projected, warnings = run_indexer_operation(root_path, lambda indexer: indexer.project_semantic_captures(page))
        if warnings:
            metadata["warnings"] = warnings
        return compact_structural_items(projected, Path(root_path)), metadata
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
async def find_symbol(
    root_path: str,
    query: str,
    ctx: Context,
    limit: int | str = 10,
    cursor: str | None = None,
    min_score: int | str = 60,
    paths: list[str] | None = None,
    languages: list[str] | None = None,
    symbol_types: list[str] | None = None,
    visibility: list[str] | None = None,
) -> dict[str, Any] | ToolResult:
    """Find definitions by calibrated name or owner-qualified identity."""
    try:
        await ctx.info(f"Finding symbols for query: {query}")
        await ctx.report_progress(0, 2, "normalizing repository path")
        parsed_score = int(min_score)
        identity = {
            "query": query,
            "min_score": parsed_score,
            "paths": paths or [],
            "languages": languages or [],
            "symbol_types": symbol_types or [],
            "visibility": visibility or [],
        }
        normalized_root, parsed_limit, identity, _offset = await asyncio.to_thread(
            _prepare_page, root_path, "find", identity, limit, cursor
        )
        await ctx.report_progress(1, 2, "searching symbols")
        results, succeeded, warnings = await asyncio.to_thread(
            run_indexer_operation,
            normalized_root,
            lambda indexer: (
                indexer.find_symbol(
                    query,
                    limit=None,
                    min_score=parsed_score,
                    include_scores=True,
                    paths=paths,
                    languages=languages,
                    symbol_types=symbol_types,
                    visibility=visibility,
                ),
                indexer.last_search_succeeded,
                list(indexer.last_warnings),
            ),
        )
        if not succeeded:
            return mcp_error("ast_grep_error", warnings[0] if warnings else "Symbol search failed.")
        normalized_results: list[dict[str, Any]] = []
        for result in results:
            value = dict(result)
            path = Path(str(value.get("path", "")))
            value["abs_path"] = str(path.resolve() if path.is_absolute() else (Path(normalized_root) / path).resolve())
            normalized_results.append(dump_symbol_output(value))
        page, metadata = page_items(
            normalized_results,
            command="find",
            root_path=Path(normalized_root),
            identity=identity,
            limit=parsed_limit,
            cursor=cursor,
        )
        await ctx.report_progress(2, 2, f"found {len(normalized_results)} symbol matches")
        return {
            "query": query,
            "min_score": parsed_score,
            "symbols": [dict(item) for item in page],
            **metadata,
            "warnings": warnings,
        }
    except Exception as e:
        await ctx.error(f"Error finding symbol: {e}")
        return mcp_error("invalid_request", str(e))


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def read_interface(root_path: str, file_path: str) -> str | ToolResult:
    """Read signatures, class definitions, and docstrings for one file."""
    try:
        return run_indexer_operation(
            root_path,
            lambda indexer: indexer.render_interface(
                indexer.read_interface_structured(file_path, member_depth=None, max_symbols=None, max_members=None)
            ),
        )
    except InterfaceReadError as exc:
        return mcp_error(exc.code, str(exc))
    except Exception as e:
        return mcp_error("internal_error", str(e))


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def read_interface_structured(
    root_path: str,
    file_path: Annotated[str | None, "Contained source file; omit when exact_symbol supplies its path"] = None,
    exact_symbol: Annotated[
        dict[str, Any] | None, "Exact find_symbol object; expands containers or selects only one member path"
    ] = None,
    symbol_names: list[str] | None = None,
    visibility: list[str] | None = None,
    symbol_types: list[str] | None = None,
    member_depth: int = 1,
    max_members: int = 20,
    limit: int | str = 50,
    cursor: str | None = None,
    schema: Annotated[str, "Response projection: compact v3 default or explicit legacy v2"] = "v3",
) -> dict[str, Any] | ToolResult:
    """Return a typed interface; v3 expands exact containers and isolates exact members."""
    try:
        _validate_schema(schema)
        selected_symbol = validate_symbol_input(exact_symbol) if exact_symbol is not None else None
        if selected_symbol is not None:
            if file_path is not None:
                raise ValueError("Do not combine file_path with exact_symbol.")
            file_path = str(selected_symbol.get("abs_path") or selected_symbol["path"])
        if file_path is None:
            raise ValueError("Provide file_path or exact_symbol.")
        if selected_symbol is not None and schema != "v3":
            raise ValueError("exact_symbol requires schema='v3'.")
        identity = {
            "file_path": file_path,
            **({"exact_symbol": selected_symbol} if selected_symbol is not None else {}),
            "symbol_names": symbol_names or [],
            "visibility": visibility or [],
            "symbol_types": symbol_types or [],
            "member_depth": member_depth,
            "max_members": max_members,
            "projection": "compact" if schema == "v3" else "full",
            **({"schema": "v3"} if schema == "v3" else {}),
        }
        normalized, parsed_limit, identity, _offset = _prepare_page(root_path, "interface", identity, limit, cursor)
        result = run_indexer_operation(
            normalized,
            lambda indexer: dump_interface_data(
                indexer.read_interface_structured(
                    file_path,
                    symbol_names=symbol_names,
                    visibility=visibility,
                    symbol_types=symbol_types,
                    member_depth=member_depth,
                    max_symbols=None,
                    max_members=max_members,
                    exact_symbol=selected_symbol,
                )
            ),
        )
        page, metadata = page_items(
            result["symbols"],
            command="interface",
            root_path=Path(normalized),
            identity=identity,
            limit=parsed_limit,
            cursor=cursor,
        )
        result["symbols"] = page
        result.update(metadata)
        if metadata["truncated"]:
            result["complete"] = False
            result["warnings"].append("Top-level interface symbols are paged; continue with next_cursor.")
        if schema == "v3":
            return compact_v3_interface(result)
        result.pop("warning_details", None)
        return result
    except InterfaceReadError as exc:
        return mcp_error(exc.code, str(exc))
    except Exception as exc:
        return mcp_error("invalid_request", str(exc))


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def read_symbol(
    root_path: str,
    exact_symbol: dict[str, Any],
    context_lines: int = 0,
    max_lines: int = 200,
    max_bytes: int = 64 * 1024,
) -> dict[str, Any] | ToolResult:
    """Read one exact contained symbol source slice with explicit bounds."""
    try:
        symbol = validate_symbol_input(exact_symbol)
        return run_indexer_operation(
            root_path,
            lambda indexer: indexer.read_symbol(
                symbol, context_lines=context_lines, max_lines=max_lines, max_bytes=max_bytes
            ),
        )
    except InterfaceReadError as exc:
        return mcp_error(exc.code, str(exc))
    except Exception as exc:
        return mcp_error("invalid_request", str(exc))


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def symbol_at(root_path: str, file_path: str, line: int) -> dict[str, Any] | ToolResult:
    """Return the narrowest inventory symbol enclosing a one-based line."""
    try:
        normalized = normalize_path(root_path)
        symbol = run_indexer_operation(normalized, lambda indexer: indexer.symbol_at(file_path, line))
        if symbol is not None:
            path = Path(str(symbol.get("path", "")))
            symbol["abs_path"] = str(path if path.is_absolute() else (Path(normalized) / path).resolve())
            symbol = dump_symbol_output(symbol)
        return {"file_path": file_path, "line": line, "found": symbol is not None, "symbol": symbol}
    except Exception as exc:
        return mcp_error("invalid_request", str(exc))


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def what_breaks(
    exact_symbol: dict[str, Any],
    limit: int | str = DEFAULT_RESULT_LIMIT,
    cursor: str | None = None,
    detail: str = "compact",
    schema: Annotated[str, "Response projection: compact v3 default or explicit legacy v2"] = "v3",
) -> dict[str, Any] | ToolResult:
    """Find likely symbol-name code references for impact review."""
    try:
        exact_symbol = validate_symbol_input(exact_symbol)
        symbol_path_value = exact_symbol.get("abs_path") or exact_symbol["path"]
        symbol_path = Path(symbol_path_value)
        if not symbol_path.is_absolute():
            return mcp_error(
                "invalid_symbol_path",
                "what_breaks requires an absolute symbol path or abs_path when called via MCP.",
            )
        symbol_path = symbol_path.resolve()
        root_path = infer_symbol_root_path(exact_symbol, symbol_path)
        symbol_for_indexer = dict(exact_symbol)
        symbol_for_indexer["path"] = str(symbol_path)
        _validate_detail(detail)
        _validate_schema(schema)
        identity = {
            "symbol": {
                key: exact_symbol.get(key) for key in ("name", "path", "abs_path", "start_line", "end_line", "type")
            },
            "detail": detail,
            **({"schema": "v3"} if schema == "v3" else {}),
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
        presented = dump_impact_result({**result, "references": page, **metadata})
        return compact_v3_impact(presented) if schema == "v3" and detail == "compact" else presented
    except AstGrepValidationError as exc:
        return mcp_error("invalid_request", str(exc))
    except AstGrepError as exc:
        return mcp_error("ast_grep_error", str(exc))
    except Exception as e:
        return mcp_error("invalid_request", str(e))


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
) -> dict[str, Any] | ToolResult:
    """Return bounded compact structural matches, with full detail available on request."""
    try:
        _validate_detail(detail)
        identity = {
            "pattern": pattern,
            "lang": lang,
            "paths": paths or [],
            "globs": globs or [],
            "projection": detail,
        }
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
    except AstGrepValidationError as exc:
        return mcp_error("invalid_request", str(exc))
    except AstGrepError as exc:
        return mcp_error("ast_grep_error", str(exc))
    except Exception as e:
        return mcp_error("invalid_request", str(e))


@mcp.tool(annotations=DESTRUCTIVE_TOOL_ANNOTATIONS)
def rewrite_pattern(
    root_path: str,
    pattern: str,
    replacement: str,
    lang: str | None = None,
    limit: int | str = DEFAULT_RESULT_LIMIT,
    detail: str = "compact",
) -> dict[str, Any] | ToolResult:
    """Rewrite every match in place and return a compact summary or bounded full diagnostics."""
    try:
        _validate_detail(detail)
        identity = {"pattern": pattern, "replacement": replacement, "lang": lang}
        normalized, parsed_limit, identity, _offset = _prepare_page(
            root_path, "rewrite", identity, limit, None, continuable=False
        )
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
    except AstGrepValidationError as exc:
        return mcp_error("invalid_request", str(exc))
    except AstGrepError as exc:
        return mcp_error("ast_grep_error", str(exc))
    except Exception as e:
        return mcp_error("rewrite_failed", str(e))


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
    allow_truncated_review: bool = False,
    allow_dirty_affected: bool = False,
    allow_new_parse_errors: bool = False,
    preview_limit: int = 50,
    diff_limit: int = 100_000,
) -> dict[str, Any] | ToolResult:
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
                allow_truncated_review=allow_truncated_review,
                allow_dirty_affected=allow_dirty_affected,
                allow_new_parse_errors=allow_new_parse_errors,
                preview_limit=preview_limit,
                diff_limit=diff_limit,
            ),
        )
    except AstGrepValidationError as exc:
        return mcp_error("invalid_request", str(exc))
    except AstGrepError as exc:
        return mcp_error("ast_grep_error", str(exc))
    except Exception as exc:
        return mcp_error("invalid_request", str(exc))


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def refine_replacement(root_path: str, plan: dict[str, Any], edit_ids: list[str]) -> dict[str, Any] | ToolResult:
    """Recompute a reviewed v2 replacement plan for selected stable edit IDs."""
    try:
        return run_indexer_operation(
            root_path,
            lambda indexer: indexer.refine_replacement(plan, edit_ids=edit_ids),
        )
    except Exception as exc:
        return mcp_error("invalid_request", str(exc))


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def verify_replacement(root_path: str, plan: dict[str, Any], expected_digest: str) -> dict[str, Any] | ToolResult:
    """Recompute every replacement apply guard without writing files."""
    try:
        return run_indexer_operation(
            root_path,
            lambda indexer: indexer.verify_replacement(plan, expected_digest=expected_digest),
        )
    except ReplacementDriftError as exc:
        return mcp_error("replacement_source_drift", str(exc), details=exc.details)
    except Exception as exc:
        return mcp_error("replacement_verification_failed", str(exc))


@mcp.tool(annotations=DESTRUCTIVE_TOOL_ANNOTATIONS)
def apply_replacement(root_path: str, plan: dict[str, Any], expected_digest: str) -> dict[str, Any] | ToolResult:
    """Apply a complete reviewed plan only if digest, root, query, and source guards still match."""
    try:
        return run_indexer_operation(
            root_path,
            lambda indexer: indexer.apply_replacement(plan, expected_digest=expected_digest),
        )
    except ReplacementDriftError as exc:
        return mcp_error("replacement_source_drift", str(exc), details=exc.details)
    except ReplacementApplyError as exc:
        return mcp_error(
            "replacement_apply_failed",
            str(exc),
            details={
                "rollback_attempted": exc.rollback_attempted,
                "rollback_count": exc.rollback_count,
                "rollback_succeeded": exc.rollback_succeeded,
                "rollback_status": exc.rollback_status,
            },
        )
    except Exception as exc:
        return mcp_error("replacement_apply_failed", str(exc))


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def scan_rules(
    root_path: str,
    rule_path: str,
    limit: int | str = DEFAULT_RESULT_LIMIT,
    cursor: str | None = None,
    detail: str = "compact",
    paths: list[str] | None = None,
    globs: list[str] | None = None,
) -> dict[str, Any] | ToolResult:
    """Return bounded read-only ast-grep rule diagnostics."""
    try:
        _validate_detail(detail)
        identity = {"rule_path": rule_path, "paths": paths or [], "globs": globs or [], "projection": detail}
        normalized, parsed_limit, identity, offset = _prepare_page(root_path, "scan", identity, limit, cursor)
        matches, total_exact, selection = run_indexer_operation(
            normalized,
            lambda indexer: (
                indexer.scan_rules(
                    rule_path,
                    False,
                    paths=paths,
                    globs=globs,
                    max_results=offset + parsed_limit + 1,
                ),
                indexer.last_result_total_exact,
                indexer.last_rule_selection,
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
            continuable=True,
            total_exact=total_exact,
        )
        result = {"matches": page, "selection": selection, **metadata}
        if detail == "full":
            result["match_count"] = len(matches)
        return result
    except AstGrepValidationError as exc:
        return mcp_error("invalid_request", str(exc))
    except AstGrepError as exc:
        return mcp_error("ast_grep_error", str(exc))
    except Exception as e:
        return mcp_error("invalid_request", str(e))


@mcp.tool(annotations=DESTRUCTIVE_TOOL_ANNOTATIONS)
def apply_rule_fixes(root_path: str, plan: dict[str, Any], expected_digest: str) -> dict[str, Any] | ToolResult:
    """Apply only a reviewed v2 rule replacement plan with an independent digest."""
    try:
        change = plan.get("query", {}).get("change", {})
        if not isinstance(change, dict) or change.get("kind") != "rule":
            raise ValueError("apply_rule_fixes requires a replacement plan whose change kind is rule.")
        return run_indexer_operation(
            root_path,
            lambda indexer: indexer.apply_replacement(plan, expected_digest=expected_digest),
        )
    except ReplacementDriftError as exc:
        return mcp_error("replacement_source_drift", str(exc), details=exc.details)
    except ReplacementApplyError as exc:
        return mcp_error(
            "rule_apply_failed",
            str(exc),
            details={
                "rollback_attempted": exc.rollback_attempted,
                "rollback_count": exc.rollback_count,
                "rollback_succeeded": exc.rollback_succeeded,
                "rollback_status": exc.rollback_status,
            },
        )
    except Exception as exc:
        return mcp_error("rule_apply_failed", str(exc))


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def check_rules(
    root_path: str,
    rule_path: str,
    limit: int | str = 100,
    cursor: str | None = None,
    detail: str = "compact",
    paths: list[str] | None = None,
    globs: list[str] | None = None,
) -> dict[str, Any] | ToolResult:
    """Validate and scan a contained ast-grep rule without mutation."""
    try:
        _validate_detail(detail)
        identity = {"rule_path": rule_path, "paths": paths or [], "globs": globs or [], "projection": detail}
        normalized, parsed_limit, identity, offset = _prepare_page(root_path, "rules.check", identity, limit, cursor)
        result = run_indexer_operation(
            normalized,
            lambda indexer: indexer.check_rules(
                rule_path, paths=paths, globs=globs, max_results=offset + parsed_limit + 1
            ),
        )
        matches, metadata = _present_items(
            result.pop("matches"),
            root_path=normalized,
            command="rules.check",
            identity=identity,
            detail=detail,
            limit=parsed_limit,
            cursor=cursor,
            total_exact=bool(result.pop("total_exact")),
        )
        result.update({"matches": matches, **metadata})
        return result
    except AstGrepValidationError as exc:
        return mcp_error("invalid_request", str(exc))
    except AstGrepError as exc:
        return mcp_error("ast_grep_error", str(exc))
    except Exception as exc:
        return mcp_error("invalid_rule", str(exc))


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def explain_rules(
    root_path: str,
    rule_path: str,
    source_limit: int = 32_000,
    paths: list[str] | None = None,
    globs: list[str] | None = None,
) -> dict[str, Any] | ToolResult:
    """Return bounded rule source plus upstream validation and inspection evidence."""
    try:
        return run_indexer_operation(
            root_path,
            lambda indexer: indexer.explain_rules(rule_path, source_limit=source_limit, paths=paths, globs=globs),
        )
    except AstGrepValidationError as exc:
        return mcp_error("invalid_request", str(exc))
    except AstGrepError as exc:
        return mcp_error("ast_grep_error", str(exc))
    except Exception as exc:
        return mcp_error("invalid_rule", str(exc))


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def test_rules(root_path: str, test_dir: str = ".", config_path: str | None = None) -> dict[str, Any] | ToolResult:
    """Run contained ast-grep tests without interactivity or snapshot updates."""
    try:
        return run_indexer_operation(
            root_path,
            lambda indexer: indexer.test_rules(test_dir=test_dir, config_path=config_path),
        )
    except AstGrepValidationError as exc:
        return mcp_error("invalid_request", str(exc))
    except AstGrepError as exc:
        return mcp_error("ast_grep_error", str(exc))
    except Exception as exc:
        return mcp_error("rule_test_failed", str(exc))


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def xray_capabilities(root_path: str | None = None) -> dict[str, Any] | ToolResult:
    """Report XRAY help, schemas, operations, bounds, dependencies, and workflow resources."""
    try:
        root = normalize_path(root_path) if root_path is not None else str(Path.cwd().resolve())
        return run_indexer_operation(
            root,
            lambda indexer: indexer.capabilities(include_repository=root_path is not None),
        )
    except Exception as exc:
        return mcp_error("capabilities_failed", str(exc))


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def file_imports(
    root_path: str,
    file_path: str,
    limit: int | str = DEFAULT_RESULT_LIMIT,
    cursor: str | None = None,
    detail: str = "compact",
) -> dict[str, Any] | ToolResult:
    """Return bounded compact imports, flattening ast-grep outline wrappers."""
    try:
        _validate_detail(detail)
        identity = {"file_path": file_path, "projection": detail}
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
        return mcp_error("invalid_request", str(e))


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
def file_exports(
    root_path: str,
    file_path: str,
    limit: int | str = DEFAULT_RESULT_LIMIT,
    cursor: str | None = None,
    detail: str = "compact",
) -> dict[str, Any] | ToolResult:
    """Return bounded compact exports, flattening ast-grep outline wrappers."""
    try:
        _validate_detail(detail)
        identity = {"file_path": file_path, "projection": detail}
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
        return mcp_error("invalid_request", str(e))


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
                    "max_depth": ArgTransformConfig(description="Directory depth limit; defaults to 2."),
                    "all_depths": ArgTransformConfig(description="Explicitly disable the depth limit when true."),
                    "include_symbols": ArgTransformConfig(description="Include function/class skeletons when true."),
                    "focus_dirs": ArgTransformConfig(description="Contained nested file/directory focuses."),
                    "include_root_context": ArgTransformConfig(
                        description="Keep unrelated root files as named context; false selects strict focus."
                    ),
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
                description=(
                    "Find symbol definitions and lookup function, method, class, type, or enum by calibrated name or "
                    "owner-qualified identity, with scores, scopes, filters, and snapshot-bound paging. "
                    "This is not semantic behavior search."
                ),
                tags={"find", "lookup", "symbol", "search", "function", "class", "type", "definitions"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path to search."),
                    "query": ArgTransformConfig(description="Symbol name or owner-qualified identity to find."),
                    "limit": ArgTransformConfig(description="Page size; defaults to 10."),
                    "cursor": ArgTransformConfig(
                        description="Query/projection/snapshot-bound continuation; positive page size may change."
                    ),
                    "min_score": ArgTransformConfig(description="Minimum calibrated score; defaults to 60."),
                    "paths": ArgTransformConfig(description="Optional contained file/directory scopes."),
                    "languages": ArgTransformConfig(description="Optional language filters."),
                    "symbol_types": ArgTransformConfig(description="Optional symbol-type filters."),
                    "visibility": ArgTransformConfig(description="Optional public/private/unknown filters."),
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
                    "symbol_names": ArgTransformConfig(description="Optional top-level symbol-name filters."),
                    "visibility": ArgTransformConfig(description="Optional visibility filters."),
                    "symbol_types": ArgTransformConfig(description="Optional symbol-type filters."),
                    "member_depth": ArgTransformConfig(description="Nested member depth; defaults to 1."),
                    "max_members": ArgTransformConfig(description="Member cap per symbol; defaults to 20."),
                    "limit": ArgTransformConfig(description="Top-level symbol page size; defaults to 50."),
                    "cursor": ArgTransformConfig(
                        description="Query/projection/snapshot-bound continuation; positive page size may change."
                    ),
                },
            ),
            "read_symbol": ToolTransformConfig(
                description="Read exact source for a contained symbol with explicit context, line, and byte bounds.",
                tags={"read", "source", "symbol", "definition", "implementation"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path."),
                    "exact_symbol": ArgTransformConfig(description="Full symbol object returned by find_symbol."),
                    "context_lines": ArgTransformConfig(description="Context lines around the symbol."),
                    "max_lines": ArgTransformConfig(description="Maximum returned source lines."),
                    "max_bytes": ArgTransformConfig(description="Maximum returned UTF-8 bytes."),
                },
            ),
            "symbol_at": ToolTransformConfig(
                description="Lookup the narrowest symbol enclosing a one-based file line.",
                tags={"lookup", "symbol", "line", "location", "source"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path."),
                    "file_path": ArgTransformConfig(description="Contained supported source file."),
                    "line": ArgTransformConfig(description="One-based source line."),
                },
            ),
            "what_breaks": ToolTransformConfig(
                description=(
                    "Estimate blast radius and likely callers with symbol-name code references for change impact. "
                    "Use before breaking changes to inspect name-based usage and code that uses the same symbol name. "
                    "For 'used by' questions, this is an approximation. "
                    "This is not a type-aware caller, dependent, or dependency graph."
                ),
                tags={"impact", "blast radius", "callers", "usage", "references", "symbol-name", "approximate"},
                arguments={
                    "exact_symbol": ArgTransformConfig(
                        description="Full symbol object from find_symbol, including absolute path and line data."
                    ),
                    "limit": ArgTransformConfig(description="Maximum returned references; defaults to 50."),
                    "cursor": ArgTransformConfig(
                        description="Query/projection/snapshot-bound continuation; positive page size may change."
                    ),
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
                            "Opaque next_cursor for the same root, query/scopes, projection, and source snapshot; "
                            "positive page size may change."
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
                    "Plan a safe code replacement or rename without mutation. It returns exact source hashes, "
                    "counts, warnings, edits, and a digest required by apply_replacement."
                ),
                tags={"replace", "plan", "preview", "rewrite", "safe code replacement", "rename", "ast-grep"},
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
                    "allow_truncated_review": ArgTransformConfig(
                        description="Record explicit acknowledgement of bounded preview or diff content."
                    ),
                    "allow_dirty_affected": ArgTransformConfig(
                        description="Record acknowledgement that affected files already contain Git changes."
                    ),
                    "allow_new_parse_errors": ArgTransformConfig(
                        description="Explicitly record permission for newly introduced parse errors."
                    ),
                    "preview_limit": ArgTransformConfig(description="Maximum preview edits returned."),
                    "diff_limit": ArgTransformConfig(description="Maximum unified-diff characters returned."),
                },
            ),
            "refine_replacement": ToolTransformConfig(
                description="Re-plan a reviewed safe code replacement subset using stable edit IDs without writing.",
                tags={"replace", "refine", "select", "edit id", "safe code replacement"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute root exactly matching the plan."),
                    "plan": ArgTransformConfig(description="Complete reviewed xray.replace.v2 plan."),
                    "edit_ids": ArgTransformConfig(description="Stable edit IDs selected from the plan manifest."),
                },
            ),
            "verify_replacement": ToolTransformConfig(
                description=(
                    "Verify a safe code replacement plan without mutation by recomputing its digest, source, "
                    "selection, syntax, dirty-file, completeness, and applicability guards."
                ),
                tags={"replace", "verify", "validate", "guarded", "safe code replacement"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute root exactly matching the plan."),
                    "plan": ArgTransformConfig(description="Complete reviewed xray.replace.v2 plan."),
                    "expected_digest": ArgTransformConfig(description="Independently copied reviewed plan digest."),
                },
            ),
            "apply_replacement": ToolTransformConfig(
                description=(
                    "Apply replacement safely from a complete reviewed safe code replacement plan only when its "
                    "independent digest and "
                    "every "
                    "root, query, candidate, count, and source-hash guard still match. Interpret results by "
                    "using rollback_status as the authoritative restoration state."
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
                    "Scan rules read-only with ast-grep for bounded compact diagnostics and "
                    "snapshot-bound continuation."
                ),
                tags={"scan", "lint", "rules", "ast-grep"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path to scan."),
                    "rule_path": ArgTransformConfig(description="Rule file or config directory inside root_path."),
                    "limit": ArgTransformConfig(description="Maximum returned diagnostics; defaults to 50."),
                    "cursor": ArgTransformConfig(
                        description="Query/projection/snapshot-bound continuation; positive page size may change."
                    ),
                    "detail": ArgTransformConfig(description="compact (default) or full ast-grep diagnostic detail."),
                    "paths": ArgTransformConfig(description="Optional contained file/directory scopes."),
                    "globs": ArgTransformConfig(description="Optional ordered ast-grep glob filters."),
                },
            ),
            "apply_rule_fixes": ToolTransformConfig(
                description="Apply fixes only from a reviewed xray.replace.v2 rule plan and independent digest.",
                tags={"rules", "fix", "apply", "guarded", "destructive", "safe code replacement"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute root exactly matching the plan."),
                    "plan": ArgTransformConfig(description="Complete reviewed v2 plan whose change kind is rule."),
                    "expected_digest": ArgTransformConfig(description="Independently copied reviewed plan digest."),
                },
            ),
            "check_rules": ToolTransformConfig(
                description="Validate and scan a contained ast-grep rule without applying fixes.",
                tags={"rules", "check", "validate", "scan", "read-only"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path."),
                    "rule_path": ArgTransformConfig(description="Contained rule or configuration path."),
                    "limit": ArgTransformConfig(description="Positive diagnostic page size; defaults to 100."),
                    "cursor": ArgTransformConfig(
                        description="Query/projection/snapshot-bound continuation; positive page size may change."
                    ),
                    "detail": ArgTransformConfig(description="compact (default) or full ast-grep diagnostic detail."),
                    "paths": ArgTransformConfig(description="Optional contained scan scopes."),
                    "globs": ArgTransformConfig(description="Optional ast-grep glob filters."),
                },
            ),
            "explain_rules": ToolTransformConfig(
                description="Explain a rule with bounded source, validation evidence, and ast-grep inspect summary.",
                tags={"rules", "explain", "validate", "inspect", "help"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path."),
                    "rule_path": ArgTransformConfig(description="Contained rule or configuration path."),
                    "source_limit": ArgTransformConfig(description="Maximum returned rule-source characters."),
                    "paths": ArgTransformConfig(description="Optional contained inspection scopes."),
                    "globs": ArgTransformConfig(description="Optional ordered ast-grep glob filters."),
                },
            ),
            "test_rules": ToolTransformConfig(
                description="Run contained ast-grep rule tests without interactivity or snapshot changes.",
                tags={"rules", "test", "validate", "read-only"},
                arguments={
                    "root_path": ArgTransformConfig(description="Absolute repository root path."),
                    "test_dir": ArgTransformConfig(description="Contained rule-test directory."),
                    "config_path": ArgTransformConfig(description="Optional contained sgconfig path."),
                },
            ),
            "xray_capabilities": ToolTransformConfig(
                description="Get XRAY help, workflow, schemas, operations, limits, dependencies, and health.",
                tags={"help", "workflow", "capabilities", "doctor", "diagnostics"},
                arguments={
                    "root_path": ArgTransformConfig(description="Optional absolute root for repository checks."),
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
                        description="Same file/projection/snapshot continuation; positive page size may change."
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
                        description="Same file/projection/snapshot continuation; positive page size may change."
                    ),
                    "detail": ArgTransformConfig(description="compact (default) or full ast-grep outline detail."),
                },
            ),
        }
    )
)

mcp.add_transform(XRayToolSearchTransform(max_results=DEFAULT_TOOL_SEARCH_LIMIT))


def main():
    """Run the installed XRAY MCP command over its supported stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
