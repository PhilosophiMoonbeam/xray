"""Command line interface for XRAY code intelligence."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from importlib import metadata
from pathlib import Path
from typing import Any, NoReturn

from xray import __version__
from xray.core.ast_grep import AstGrepError
from xray.core.indexer import InterfaceReadError, ReplacementApplyError, XRayIndexer
from xray.models import (
    dump_error_envelope,
    dump_explore_data,
    dump_explore_envelope,
    dump_find_envelope,
    dump_impact_envelope,
    dump_impact_result,
    dump_interface_data,
    dump_interface_envelope,
    dump_symbol_output,
    validate_symbol_input,
)
from xray.presentation import (
    compact_explore,
    compact_impact_references,
    compact_structural_items,
    compact_v3_impact,
    compact_v3_interface,
    cursor_fingerprint,
    decode_cursor,
    page_items,
)
from xray.skill_installer import SkillInstallError, install_cli_skill

SCHEMA_VERSION = "xray.cli.v1"
COMPACT_SCHEMA_VERSION = "xray.cli.v2"
V3_SCHEMA_VERSION = "xray.cli.v3"
DEFAULT_STRUCTURAL_LIMIT = 50
MAX_SCORE = 100
MAX_SYMBOL_JSON_CHARS = 1024 * 1024
MAX_PLAN_JSON_CHARS = 10 * 1024 * 1024
OUTPUT_FORMAT_HELP = "Output: compact JSON (default) or lossy text."
PRETTY_HELP = "Indent JSON output."

ROOT_HELP_EPILOG = """\
Agent flow:
  xray explore ROOT --max-depth 2
  symbol=$(xray find ROOT "target symbol" --limit 1 | jq -c '.symbols[0]')
  xray interface ROOT --symbol-json "$symbol" --schema v3
  xray impact ROOT --symbol-json "$symbol"

Guarded change:
  xray replace plan ROOT -p 'old_api($ARG)' -r 'new_api($ARG)' -l python > plan.json
  jq -r '(.plan // .).edit_manifest[].edit_id' plan.json
  xray replace verify ROOT --plan-file plan.json --expected-digest REVIEWED_DIGEST
  xray replace apply ROOT --plan-file plan.json --expected-digest REVIEWED_DIGEST

Compact JSON is default; where offered, use --detail full for legacy fields or
--format text for lossy scans. Use --schema v3 for consistent success/paging
and exact-symbol interfaces. Pages report total_exact; next_cursor requires the
same query and snapshot. YAML output is unsupported. replace apply, rewrite, and
scan --fix mutate files; --limit never bounds legacy edits. Exit codes: 0 success,
1 command failure, 2 parse or validation error.
"""

EXPLORE_HELP = """\
Map a repository. Start shallow; add --focus or --include-symbols as needed.
"""

EXPLORE_EPILOG = """\
Examples:
  xray explore ROOT --max-depth 2
  xray explore ROOT --focus src --include-symbols --max-symbols-per-file 5

Compact JSON contains relative-path entries. --detail full adds the v1 tree and
absolute paths. map aliases explore and sets invoked_as to "map".
"""

FIND_EPILOG = """\
Example: xray find ROOT "AuthService.validate_user" --limit 5 --min-score 60

JSON symbols are complete impact inputs, including qualified identity, match
reason, confidence, paths, lines, type, and score.
"""

INTERFACE_HELP = """\
Show one file's typed hierarchy without implementation bodies.
"""

INTERFACE_EPILOG = """\
Example: xray interface ROOT src/package/module.py
Exact handoff: xray interface ROOT --symbol-json "$symbol" --schema v3

FILE_PATH must resolve inside ROOT; parent traversal and symlink escapes fail.
Compact v3 accepts an exact find symbol and reports typed completeness reasons.
--detail full returns the legacy v1 string envelope.
"""

IMPACT_HELP = """\
Find bounded symbol-name references; this is not a type-aware dependency graph.
Provide exactly one symbol source:
--symbol-json, --symbol-file, or --name with --path and --start-line.
"""

IMPACT_EPILOG = """\
Pipeline:
  xray find ROOT "target_function" --limit 1 | jq -c '.symbols[0]' | xray impact ROOT --symbol-file -

Symbol paths must resolve inside ROOT. Compact references classify
definition/import/call/read/text with confidence and snapshot-bound paging.
total_exact=false means a lower bound; review same-name definitions separately.
"""


class ParserExit(Exception):
    """Internal replacement for argparse's process-level exits."""

    def __init__(self, status: int = 0, message: str = ""):
        self.status = status
        self.message = message
        super().__init__(message)


class XRayArgumentParser(argparse.ArgumentParser):
    """ArgumentParser variant that lets cli.main return exit codes."""

    def __init__(self, *args: Any, **kwargs: Any):
        kwargs.setdefault("formatter_class", argparse.RawDescriptionHelpFormatter)
        super().__init__(*args, **kwargs)

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        raise ParserExit(status, message or "")

    def error(self, message: str) -> NoReturn:
        raise ParserExit(2, f"{self.prog}: error: {message}")


def normalize_path(path: str) -> str:
    """Normalize a repository path to an existing absolute directory."""
    expanded = os.path.expanduser(path)
    resolved = str(Path(expanded).resolve())
    if not os.path.exists(resolved):
        raise ValueError(f"Path '{path}' does not exist")
    if not os.path.isdir(resolved):
        raise ValueError(f"Path '{path}' is not a directory")
    return resolved


def get_version() -> str:
    try:
        return metadata.version("xray")
    except metadata.PackageNotFoundError:
        return __version__


def build_parser() -> argparse.ArgumentParser:
    parser = XRayArgumentParser(
        prog="xray",
        description="Code intelligence for LLM agents: inspect, assess impact, and make structural changes.",
        epilog=ROOT_HELP_EPILOG,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {get_version()}")

    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=XRayArgumentParser)

    explore = subparsers.add_parser(
        "explore",
        aliases=["map"],
        help="Map repository structure, optionally with symbols.",
        description=EXPLORE_HELP,
        epilog=EXPLORE_EPILOG,
    )
    explore.add_argument("root_path", help="Repository root to inspect.")
    depth = explore.add_mutually_exclusive_group()
    depth.add_argument("--max-depth", type=int, default=2, help="Maximum directory depth to traverse (default: 2).")
    depth.add_argument(
        "--all-depths",
        action="store_const",
        const=None,
        default=argparse.SUPPRESS,
        dest="max_depth",
        help="Traverse without a depth limit.",
    )
    explore.add_argument(
        "--include-symbols",
        "--symbols",
        action="store_true",
        help="Include function/class/type skeletons for supported source files.",
    )
    explore.add_argument(
        "--focus",
        dest="focus_dirs",
        action="append",
        default=None,
        help="Contained file or directory focus. Repeat for multiple nested scopes.",
    )
    explore.add_argument(
        "--strict-focus",
        action="store_false",
        dest="include_root_context",
        help="Return only each focus, its ancestors, and focus-relative descendants; omit unrelated root files.",
    )
    explore.add_argument(
        "--max-symbols-per-file",
        type=int,
        default=5,
        help="Maximum skeleton symbols shown per file when symbols are included.",
    )
    explore.add_argument(
        "--type",
        dest="symbol_types",
        help="Comma-separated ast-grep outline symbol types, such as class,interface.",
    )
    explore.add_argument(
        "--max-entries",
        "--limit",
        type=int,
        default=5000,
        help="Maximum files and directories returned (default: 5000); truncation is reported.",
    )
    explore.add_argument(
        "--no-default-exclusions",
        action="store_false",
        dest="use_default_exclusions",
        help="Include generated/agent-state paths while still honoring repository .gitignore rules.",
    )
    explore.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help=OUTPUT_FORMAT_HELP,
    )
    explore.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    add_schema_arg(explore)
    explore.add_argument(
        "--detail",
        choices=("compact", "full"),
        default="compact",
        help="JSON detail level; full preserves the v1 payload.",
    )
    explore.set_defaults(handler=handle_explore)

    find = subparsers.add_parser(
        "find",
        help="Find symbols by calibrated name match.",
        description="Find definitions by name or owner-qualified identity.",
        epilog=FIND_EPILOG,
    )
    find.add_argument("root_path", help="Repository root to inspect.")
    find.add_argument("query", help="Symbol query, such as 'auth service' or 'parse_json'.")
    find.add_argument("--limit", type=int, default=10, help="Maximum number of matches to return.")
    find.add_argument("--cursor", help="Opaque continuation cursor from an identical unchanged query.")
    find.add_argument(
        "--min-score",
        type=int,
        default=60,
        help="Minimum calibrated name-match score, from 0 to 100 (default: 60).",
    )
    find.add_argument("--path", dest="paths", action="append", help="Contained file/directory scope; repeatable.")
    find.add_argument("--language", dest="languages", action="append", help="Language filter; repeatable.")
    find.add_argument("--type", dest="symbol_types", action="append", help="Symbol-type filter; repeatable.")
    find.add_argument(
        "--visibility", action="append", choices=("public", "private", "unknown"), help="Visibility filter; repeatable."
    )
    find.add_argument(
        "--detail", choices=("compact", "full"), default="compact", help="Compact v2 (default) or v1 envelope."
    )
    find.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help=OUTPUT_FORMAT_HELP,
    )
    find.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    add_schema_arg(find)
    find.set_defaults(handler=handle_find)

    interface = subparsers.add_parser(
        "interface",
        help="Show a file interface without implementation bodies.",
        description=INTERFACE_HELP,
        epilog=INTERFACE_EPILOG,
    )
    interface.add_argument("root_path", help="Repository root to inspect.")
    interface.add_argument(
        "file_path", nargs="?", help="File path that must resolve inside the root; optional with exact-symbol input."
    )
    interface.add_argument(
        "--symbol-json", help="Exact symbol JSON from find; v3 returns its owner and selected member."
    )
    interface.add_argument("--symbol-file", help="Exact symbol JSON file, or '-' for stdin.")
    interface.add_argument("--name", dest="symbol_names", action="append", help="Top-level symbol name; repeatable.")
    interface.add_argument("--type", dest="symbol_types", action="append", help="Top-level symbol type; repeatable.")
    interface.add_argument(
        "--visibility", action="append", choices=("public", "private", "unknown"), help="Visibility; repeatable."
    )
    interface.add_argument("--member-depth", type=int, default=1, help="Nested member depth (default: 1).")
    interface.add_argument("--max-members", type=int, default=20, help="Members per symbol (default: 20).")
    interface.add_argument("--limit", type=int, default=50, help="Top-level symbols per page (default: 50).")
    interface.add_argument("--cursor", help="Opaque continuation cursor from an identical unchanged query.")
    interface.add_argument(
        "--detail",
        choices=("compact", "full"),
        default="compact",
        help="Structured compact v2 contract (default) or legacy v1 string envelope.",
    )
    interface.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help=OUTPUT_FORMAT_HELP,
    )
    interface.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    add_schema_arg(interface)
    interface.set_defaults(handler=handle_interface)

    read_symbol = subparsers.add_parser(
        "read-symbol",
        help="Read one exact symbol source slice with bounds.",
        description="Read one exact contained symbol source slice with explicit line and byte bounds.",
    )
    read_symbol.add_argument("root_path", help="Repository root containing the symbol.")
    add_symbol_input_args(read_symbol)
    read_symbol.add_argument("--context-lines", type=int, default=0, help="Context lines around the symbol.")
    read_symbol.add_argument("--max-lines", type=int, default=200, help="Maximum returned lines (default: 200).")
    read_symbol.add_argument("--max-bytes", type=int, default=64 * 1024, help="Maximum returned UTF-8 bytes.")
    read_symbol.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    add_schema_arg(read_symbol)
    read_symbol.set_defaults(handler=handle_read_symbol, format="json")

    symbol_at = subparsers.add_parser(
        "symbol-at",
        help="Find the narrowest symbol enclosing a source line.",
        description="Find the narrowest symbol enclosing one contained source line.",
    )
    symbol_at.add_argument("root_path", help="Repository root containing the file.")
    symbol_at.add_argument("file_path", help="Contained source file.")
    symbol_at.add_argument("line", type=int, help="One-based source line.")
    symbol_at.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    add_schema_arg(symbol_at)
    symbol_at.set_defaults(handler=handle_symbol_at, format="json")

    impact = subparsers.add_parser(
        "impact",
        help="Find likely symbol-name code references for impact review.",
        description=IMPACT_HELP,
        epilog=IMPACT_EPILOG,
    )
    impact.add_argument("root_path", help="Repository root to inspect.")
    impact.add_argument("--symbol-json", help="Exact symbol object as JSON, usually from `xray find`.")
    impact.add_argument(
        "--symbol-file",
        help="Path to a JSON file containing the exact symbol object. Use '-' to read stdin.",
    )
    impact.add_argument("--name", help="Symbol name when not passing a full symbol JSON object.")
    impact.add_argument("--path", help="Symbol definition path when not passing a full symbol JSON object.")
    impact.add_argument("--type", default="symbol", help="Symbol type for manually specified symbols.")
    impact.add_argument(
        "--start-line",
        type=int,
        default=None,
        help="Definition start line for manual symbols; required with --name and --path.",
    )
    impact.add_argument("--end-line", type=int, default=None, help="Definition end line for manual symbols.")
    impact.add_argument("--context-lines", type=int, default=2, help="Context lines around each reference.")
    impact.add_argument("--limit", type=int, default=DEFAULT_STRUCTURAL_LIMIT, help="Maximum returned references.")
    impact.add_argument("--cursor", help="Opaque continuation cursor from an identical unchanged query.")
    impact.add_argument(
        "--detail",
        choices=("compact", "full"),
        default="compact",
        help="Compact relative-path v2 results (default) or full v1-compatible context.",
    )
    impact.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help=OUTPUT_FORMAT_HELP,
    )
    impact.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    add_schema_arg(impact)
    impact.set_defaults(handler=handle_impact)

    search = subparsers.add_parser("search", help="Search with an ast-grep pattern.")
    search.add_argument("root_path", help="Repository root to search.")
    search.add_argument("-p", "--pattern", required=True, help="ast-grep structural pattern.")
    search.add_argument("-l", "--lang", help="Pattern language when it cannot be inferred.")
    add_scope_args(search)
    add_structural_output_args(
        search,
        limit_help=f"Result cap (default: {DEFAULT_STRUCTURAL_LIMIT}); also bounds upstream search.",
    )
    search.set_defaults(handler=handle_search)

    rewrite = subparsers.add_parser("rewrite", help="Apply an ast-grep structural rewrite in place.")
    rewrite.add_argument("root_path", help="Repository root to rewrite.")
    rewrite.add_argument("-p", "--pattern", required=True, help="ast-grep structural pattern.")
    rewrite.add_argument("-r", "--replacement", required=True, help="Replacement template.")
    rewrite.add_argument(
        "-l",
        "--lang",
        help="Target language; specify it when known to keep mutations from matching pattern-like non-code text.",
    )
    add_structural_output_args(
        rewrite,
        supports_cursor=False,
        limit_help=f"Reported-match cap (default: {DEFAULT_STRUCTURAL_LIMIT}); edits still cover every match.",
    )
    rewrite.set_defaults(handler=handle_rewrite)

    scan = subparsers.add_parser("scan", help="Scan code with ast-grep YAML rules.")
    scan.add_argument("root_path", help="Repository root to scan.")
    scan.add_argument("--rule", required=True, help="Rule configuration file or directory inside the root.")
    scan.add_argument("--fix", action="store_true", help="Apply every rule fix without prompting.")
    add_scope_args(scan)
    add_structural_output_args(
        scan,
        limit_help=f"Diagnostic cap (default: {DEFAULT_STRUCTURAL_LIMIT}); --fix still applies every fix.",
    )
    scan.set_defaults(handler=handle_scan)

    rules = subparsers.add_parser("rules", help="Validate, explain, or test ast-grep rules without mutation.")
    rules_subparsers = rules.add_subparsers(dest="rules_command", required=True, parser_class=XRayArgumentParser)
    rules_check = rules_subparsers.add_parser(
        "check", help="Validate and scan one contained rule source.", description="Validate and scan without fixes."
    )
    rules_check.add_argument("root_path")
    rules_check.add_argument("--rule", required=True)
    add_scope_args(rules_check)
    rules_check.add_argument("--limit", type=int, default=DEFAULT_STRUCTURAL_LIMIT)
    rules_check.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    rules_check.set_defaults(handler=handle_rules_check, format="json")
    rules_explain = rules_subparsers.add_parser(
        "explain", help="Show bounded source and upstream inspection.", description="Inspect one rule without mutation."
    )
    rules_explain.add_argument("root_path")
    rules_explain.add_argument("--rule", required=True)
    rules_explain.add_argument("--source-limit", type=int, default=32_000)
    rules_explain.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    rules_explain.set_defaults(handler=handle_rules_explain, format="json")
    rules_test = rules_subparsers.add_parser(
        "test",
        help="Run contained rule tests without snapshot updates.",
        description="Run contained tests non-interactively without updating snapshots.",
    )
    rules_test.add_argument("root_path")
    rules_test.add_argument("--test-dir", default=".")
    rules_test.add_argument("--config")
    rules_test.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    rules_test.set_defaults(handler=handle_rules_test, format="json")

    replace = subparsers.add_parser(
        "replace",
        help="Plan or guardedly apply a bounded structural replacement.",
        description="Plan without writes; apply only a reviewed unchanged plan.",
    )
    replace_subparsers = replace.add_subparsers(dest="replace_command", required=True, parser_class=XRayArgumentParser)
    replace_plan = replace_subparsers.add_parser(
        "plan",
        help="Create a non-mutating exact replacement plan.",
        description="Emit an exact JSON plan without writing files.",
    )
    replace_plan.add_argument("root_path", help="Repository root to inspect without mutation.")
    replace_plan.add_argument("-p", "--pattern", help="ast-grep structural pattern.")
    replace_plan.add_argument("-r", "--replacement", help="Replacement template paired with --pattern.")
    replace_plan.add_argument("--rule", help="Fix-bearing ast-grep rule/config path inside the root.")
    replace_plan.add_argument("-l", "--lang", help="Pattern language when using --pattern.")
    add_scope_args(replace_plan)
    replace_plan.add_argument("--max-matches", type=int, default=1000, help="Candidate cap (default: 1000).")
    replace_plan.add_argument("--max-files", type=int, default=100, help="Affected-file cap (default: 100).")
    replace_plan.add_argument("--preview-limit", type=int, default=50, help="Preview cap (default: 50).")
    replace_plan.add_argument("--diff-limit", type=int, default=100_000, help="Unified-diff character cap.")
    replace_plan.add_argument("--allow-noop", action="store_true", help="Record permission to apply an all-no-op plan.")
    replace_plan.add_argument(
        "--allow-truncated-review", action="store_true", help="Acknowledge applying from bounded review content."
    )
    replace_plan.add_argument(
        "--allow-dirty-affected",
        action="store_true",
        help="Acknowledge that affected files already contain Git worktree changes.",
    )
    replace_plan.add_argument(
        "--allow-new-parse-errors",
        action="store_true",
        help="Explicitly record permission for newly introduced ast-grep parse errors.",
    )
    replace_plan.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    replace_plan.set_defaults(handler=handle_replace_plan, format="json")

    replace_refine = replace_subparsers.add_parser(
        "refine",
        help="Re-plan a reviewed subset by stable edit ID.",
        description="Re-plan repeated stable edit IDs without writing files.",
    )
    replace_refine.add_argument("root_path", help="Repository root bound by the plan.")
    replace_refine.add_argument("--plan-file", required=True, help="Full v2 plan JSON file, or '-' for stdin.")
    replace_refine.add_argument("--edit-id", dest="edit_ids", action="append", required=True)
    replace_refine.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    replace_refine.set_defaults(handler=handle_replace_refine, format="json")

    replace_verify = replace_subparsers.add_parser(
        "verify",
        help="Recompute every apply guard without writing.",
        description=(
            "Verify digest, source, selection, syntax, dirtiness, completeness, and applicability without writes."
        ),
    )
    replace_verify.add_argument("root_path", help="Repository root bound by the plan.")
    replace_verify.add_argument(
        "--plan-file", required=True, help="Full v2 plan JSON file, or '-' for standard input (bounded to 10 MiB)."
    )
    replace_verify.add_argument("--expected-digest", required=True, help="Independently copied reviewed plan digest.")
    replace_verify.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    replace_verify.set_defaults(handler=handle_replace_verify, format="json")

    replace_apply = replace_subparsers.add_parser(
        "apply",
        help="Apply a reviewed plan after all guards pass.",
        description="Validate plan, digest, and source; then stage, replace, and verify.",
    )
    replace_apply.add_argument("root_path", help="Repository root bound by the plan.")
    replace_apply.add_argument(
        "--plan-file", required=True, help="Full plan JSON file, or '-' for standard input (bounded to 10 MiB)."
    )
    replace_apply.add_argument("--expected-digest", required=True, help="Independently copied reviewed plan digest.")
    replace_apply.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    replace_apply.set_defaults(handler=handle_replace_apply, format="json")

    skill = subparsers.add_parser(
        "skill",
        help="Install the bundled xray-cli agent skill.",
        description="Install for this user or one project.",
    )
    skill_subparsers = skill.add_subparsers(dest="skill_command", required=True, parser_class=XRayArgumentParser)
    skill_install = skill_subparsers.add_parser(
        "install",
        help="Install; divergent content requires --force.",
    )
    scope = skill_install.add_mutually_exclusive_group()
    scope.add_argument("--user", action="store_true", help="Use ~/.agents/skills (default).")
    scope.add_argument("--project", metavar="ROOT", help="Use ROOT/.agents/skills.")
    skill_install.add_argument("--force", action="store_true", help="Replace divergent content.")
    skill_install.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    skill_install.set_defaults(handler=handle_skill_install, format="json")

    capabilities = subparsers.add_parser(
        "capabilities",
        aliases=["doctor"],
        help="Report schemas, operations, bounds, and dependency health.",
        description="Report schemas, operations, bounds, caches, dependencies, and health.",
    )
    capabilities.add_argument("root_path", nargs="?", help="Optional repository root for repository checks.")
    capabilities.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    add_schema_arg(capabilities)
    capabilities.set_defaults(handler=handle_capabilities, format="json")

    for command in ("imports", "exports"):
        outline = subparsers.add_parser(command, help=f"List file {command} using ast-grep outline.")
        outline.add_argument("root_path", help="Repository root containing the file.")
        outline.add_argument("file_path", help="File path, absolute or relative; must stay inside the root.")
        add_structural_output_args(outline, limit_help=f"Page size (default: {DEFAULT_STRUCTURAL_LIMIT}).")
        outline.set_defaults(handler=handle_outline_items, outline_item=command)

    return parser


def add_scope_args(parser: argparse.ArgumentParser) -> None:
    """Add repeatable contained paths and ast-grep glob filters."""
    parser.add_argument("--path", dest="paths", action="append", help="Contained file/directory scope; repeatable.")
    parser.add_argument("--glob", dest="globs", action="append", help="Ordered ast-grep glob filter; repeatable.")


def add_symbol_input_args(parser: argparse.ArgumentParser) -> None:
    """Add the established exact-symbol input alternatives."""
    parser.add_argument("--symbol-json", help="Exact symbol object as JSON, usually from `xray find`.")
    parser.add_argument("--symbol-file", help="JSON file containing the exact symbol, or '-' for stdin.")
    parser.add_argument("--name", help="Symbol name for a manually specified symbol.")
    parser.add_argument("--path", help="Contained definition path for a manually specified symbol.")
    parser.add_argument("--type", default="symbol", help="Symbol type for a manually specified symbol.")
    parser.add_argument("--start-line", type=int, default=None, help="One-based symbol start line.")
    parser.add_argument("--end-line", type=int, default=None, help="One-based symbol end line.")


def add_schema_arg(parser: argparse.ArgumentParser, *, visible: bool = True) -> None:
    """Add the opt-in compact response projection selector."""
    parser.add_argument(
        "--schema",
        choices=("v2", "v3"),
        default="v2",
        help="Compact schema." if visible else argparse.SUPPRESS,
    )


def add_structural_output_args(
    parser: argparse.ArgumentParser,
    *,
    limit_help: str,
    supports_cursor: bool = True,
) -> None:
    parser.add_argument(
        "--detail",
        choices=("compact", "full"),
        default="compact",
        help="Compact stable fields (default) or lossless upstream JSON.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_STRUCTURAL_LIMIT,
        help=limit_help,
    )
    if supports_cursor:
        parser.add_argument("--cursor", help="next_cursor from the identical unchanged read.")
    else:
        parser.set_defaults(cursor=None)
    parser.add_argument("--format", choices=("json", "text"), default="json", help=OUTPUT_FORMAT_HELP)
    parser.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    add_schema_arg(parser, visible=False)


def handle_explore(args: argparse.Namespace) -> int:
    if args.max_depth is not None and args.max_depth < 0:
        raise ValueError("--max-depth must be 0 or greater.")
    if args.max_symbols_per_file < 0:
        raise ValueError("--max-symbols-per-file must be 0 or greater.")
    if args.max_entries < 1:
        raise ValueError("--max-entries must be 1 or greater.")
    symbol_types = [value.strip() for value in (args.symbol_types or "").split(",") if value.strip()]

    indexer = XRayIndexer(normalize_path(args.root_path))
    data = indexer.explore_repo_data(
        max_depth=args.max_depth,
        include_symbols=args.include_symbols,
        focus_dirs=args.focus_dirs,
        include_root_context=args.include_root_context,
        max_symbols_per_file=args.max_symbols_per_file,
        symbol_types=symbol_types,
        max_entries=args.max_entries,
        use_default_exclusions=args.use_default_exclusions,
    )
    if args.format == "json":
        data = dump_explore_data(data)
        invoked_as = args.command
        if args.detail == "compact":
            compact = compact_explore(data)
            compact.update(
                {
                    "schema_version": compact_schema_version(args),
                    **({"ok": True} if args.schema == "v3" else {}),
                    "command": "explore",
                    "invoked_as": invoked_as,
                }
            )
            if data["truncated"]:
                compact["warnings"] = [
                    f"Explore output truncated at {args.max_entries} entries; "
                    "narrow with --focus/--max-depth or raise --max-entries."
                ]
            print_json(compact, pretty=args.pretty)
            return 0
        data.update(
            {
                "schema_version": SCHEMA_VERSION,
                "ok": True,
                "command": "explore",
                "invoked_as": invoked_as,
                "warnings": (
                    [
                        f"Explore output truncated at {args.max_entries} entries; "
                        "narrow with --focus/--max-depth or raise --max-entries."
                    ]
                    if data["truncated"]
                    else []
                ),
            }
        )
        print_json(dump_explore_envelope(data), pretty=args.pretty)
    else:
        print(data["tree_text"])
        if data["truncated"]:
            print(
                f"... output truncated at {args.max_entries} entries; "
                "narrow with --focus/--max-depth or raise --max-entries."
            )
    return 0


def handle_find(args: argparse.Namespace) -> int:
    if args.limit < 0:
        raise ValueError("--limit must be 0 or greater.")
    if args.min_score < 0 or args.min_score > MAX_SCORE:
        raise ValueError("--min-score must be between 0 and 100.")

    indexer = XRayIndexer(normalize_path(args.root_path))
    identity, _offset = _validate_page_args(
        args,
        "find",
        indexer.root_path,
        {
            "query": args.query,
            "min_score": args.min_score,
            "paths": args.paths or [],
            "languages": args.languages or [],
            "symbol_types": args.symbol_types or [],
            "visibility": args.visibility or [],
            "detail": args.detail,
        },
        indexer.repository_snapshot_fingerprint(),
    )
    results = indexer.find_symbol(
        args.query,
        limit=None,
        min_score=args.min_score,
        include_scores=True,
        paths=args.paths,
        languages=args.languages,
        symbol_types=args.symbol_types,
        visibility=args.visibility,
    )
    warnings = list(getattr(indexer, "last_warnings", []))
    search_failed = not getattr(indexer, "last_search_succeeded", False)
    if search_failed:
        raise AstGrepError(warnings[0] if warnings else "Symbol search failed.")
    formatted_results = [format_symbol_for_json(symbol, indexer.root_path) for symbol in results]
    page, page_metadata = page_items(
        formatted_results,
        command="find",
        root_path=indexer.root_path,
        identity=identity,
        limit=args.limit,
        cursor=args.cursor,
    )
    if args.format == "text":
        for symbol in page:
            print(format_symbol(symbol))
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
    elif args.detail == "compact":
        print_json(
            {
                "schema_version": compact_schema_version(args),
                "ok": not search_failed,
                "command": "find",
                "root_path": str(indexer.root_path),
                "query": args.query,
                "limit": args.limit,
                "min_score": args.min_score,
                "symbols": page,
                **page_metadata,
                "warnings": warnings,
            },
            pretty=args.pretty,
        )
    else:
        print_json(
            dump_find_envelope(
                {
                    "schema_version": SCHEMA_VERSION,
                    "ok": not search_failed,
                    "command": "find",
                    "root_path": str(indexer.root_path),
                    "query": args.query,
                    "limit": args.limit,
                    "min_score": args.min_score,
                    "symbols": page,
                    "error": "Symbol search failed." if search_failed else None,
                    **page_metadata,
                    "warnings": warnings,
                }
            ),
            pretty=args.pretty,
        )
    return 1 if search_failed else 0


def handle_interface(args: argparse.Namespace) -> int:
    indexer = XRayIndexer(normalize_path(args.root_path))
    exact_symbol = load_interface_symbol(args, indexer.root_path)
    if exact_symbol is not None:
        if args.detail == "full" or args.schema != "v3":
            raise ValueError("Exact-symbol interface selection requires --schema v3 compact JSON.")
        file_path = str(exact_symbol["path"])
    elif args.file_path:
        file_path = args.file_path
    else:
        raise ValueError("Provide FILE_PATH or exactly one of --symbol-json/--symbol-file.")
    if args.detail == "full":
        rendered = indexer.read_interface(file_path)
        failed = rendered.startswith("Error reading interface:")
        if args.format == "text":
            print(rendered)
        else:
            print_json(
                dump_interface_envelope(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "ok": not failed,
                        "command": "interface",
                        "root_path": str(indexer.root_path),
                        "file_path": file_path,
                        "interface": None if failed else rendered,
                        "error": rendered if failed else None,
                        "warnings": [],
                    }
                ),
                pretty=args.pretty,
            )
        return 1 if failed else 0
    try:
        structured = dump_interface_data(
            indexer.read_interface_structured(
                file_path,
                symbol_names=args.symbol_names,
                visibility=args.visibility,
                symbol_types=args.symbol_types,
                member_depth=args.member_depth,
                max_symbols=None,
                max_members=args.max_members,
                exact_symbol=exact_symbol,
            )
        )
    except InterfaceReadError as exc:
        raise exc

    identity, _offset = _validate_page_args(
        args,
        "interface",
        indexer.root_path,
        {
            "file_path": file_path,
            **({"exact_symbol": exact_symbol} if exact_symbol is not None else {}),
            "symbol_names": args.symbol_names or [],
            "visibility": args.visibility or [],
            "symbol_types": args.symbol_types or [],
            "member_depth": args.member_depth,
            "max_members": args.max_members,
        },
        indexer.repository_snapshot_fingerprint(),
    )
    symbols, metadata = page_items(
        structured["symbols"],
        command="interface",
        root_path=indexer.root_path,
        identity=identity,
        limit=args.limit,
        cursor=args.cursor,
    )
    structured["symbols"] = symbols
    structured.update(metadata)
    if metadata["truncated"]:
        structured["complete"] = False
        structured["warnings"].append("Top-level interface symbols are paged; continue with next_cursor.")

    rendered = indexer.render_interface(structured)
    if args.schema == "v3":
        structured = compact_v3_interface(structured)
    if args.format == "text":
        print(rendered)
    else:
        print_json(
            {
                "schema_version": compact_schema_version(args),
                "ok": True,
                "command": "interface",
                "root_path": str(indexer.root_path),
                "interface": structured,
            },
            pretty=args.pretty,
        )
    return 0


def handle_read_symbol(args: argparse.Namespace) -> int:
    """Read one exact symbol source range through the shared bounded core."""
    indexer = XRayIndexer(normalize_path(args.root_path))
    symbol = load_symbol(args, indexer.root_path)
    result = indexer.read_symbol(
        symbol,
        context_lines=args.context_lines,
        max_lines=args.max_lines,
        max_bytes=args.max_bytes,
    )
    print_json(
        _compact_envelope("read-symbol", args=args, root_path=str(indexer.root_path), result=result), pretty=args.pretty
    )
    return 0


def handle_symbol_at(args: argparse.Namespace) -> int:
    """Resolve one source location to the narrowest enclosing symbol."""
    indexer = XRayIndexer(normalize_path(args.root_path))
    symbol = indexer.symbol_at(args.file_path, args.line)
    if symbol is not None:
        symbol = format_symbol_for_json(symbol, indexer.root_path)
    print_json(
        _compact_envelope(
            "symbol-at",
            args=args,
            root_path=str(indexer.root_path),
            file_path=args.file_path,
            line=args.line,
            symbol=symbol,
            found=symbol is not None,
        ),
        pretty=args.pretty,
    )
    return 0


def handle_impact(args: argparse.Namespace) -> int:
    if args.context_lines < 0:
        raise ValueError("--context-lines must be 0 or greater.")
    if args.start_line is not None and args.start_line < 1:
        raise ValueError("--start-line must be 1 or greater.")
    if args.end_line is not None and args.end_line < 1:
        raise ValueError("--end-line must be 1 or greater.")
    if args.limit < 0:
        raise ValueError("--limit must be 0 or greater.")

    indexer = XRayIndexer(normalize_path(args.root_path))
    symbol = load_symbol(args, indexer.root_path)
    identity, offset = _validate_page_args(
        args,
        "impact",
        indexer.root_path,
        {
            "symbol": {key: symbol.get(key) for key in ("name", "path", "abs_path", "start_line", "end_line", "type")},
            "context_lines": args.context_lines,
            "detail": args.detail,
        },
        indexer.repository_snapshot_fingerprint(),
    )
    result = dump_impact_result(
        indexer.what_breaks(
            symbol,
            context_lines=args.context_lines,
            max_results=offset + args.limit + 1,
        )
    )
    is_error = isinstance(result, dict) and "error" in result
    raw_references = result.get("references", []) if isinstance(result, dict) else []
    references: Sequence[Mapping[str, Any]] = (
        raw_references
        if args.detail == "full"
        else compact_impact_references(raw_references, indexer.root_path, str(symbol["name"]))
    )
    page, metadata = page_items(
        references,
        command="impact",
        root_path=indexer.root_path,
        identity=identity,
        limit=args.limit,
        cursor=args.cursor,
        total_exact=bool(result.get("total_exact", True)),
    )
    presented = {**result, "references": [dict(reference) for reference in page], **metadata}
    if args.schema == "v3" and args.detail == "compact":
        presented = compact_v3_impact(presented)
    if args.format == "text":
        print(format_impact(presented))
    elif args.detail == "compact":
        print_json(
            {
                "schema_version": compact_schema_version(args),
                **({"ok": not is_error} if args.schema == "v3" else {}),
                "command": "impact",
                "root_path": str(indexer.root_path),
                "symbol": format_symbol_for_json(symbol, indexer.root_path),
                "impact": presented,
            },
            pretty=args.pretty,
        )
    else:
        print_json(
            dump_impact_envelope(
                {
                    "schema_version": SCHEMA_VERSION,
                    "ok": not is_error,
                    "command": "impact",
                    "root_path": str(indexer.root_path),
                    "symbol": format_symbol_for_json(symbol, indexer.root_path),
                    "impact": presented,
                    "error": result.get("error") if is_error else None,
                    "warnings": [],
                }
            ),
            pretty=args.pretty,
        )
    return 1 if is_error else 0


def _command_envelope(command: str, root_path: Path, **payload: Any) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "command": command,
        "root_path": str(root_path),
        **payload,
        "warnings": [],
    }


def _validate_page_args(
    args: argparse.Namespace,
    command: str,
    root_path: Path,
    identity: Mapping[str, Any],
    source_snapshot: str,
) -> tuple[dict[str, Any], int]:
    """Bind paging to a content snapshot and validate it before repository work."""
    if args.limit < 0:
        raise ValueError("--limit must be 0 or greater.")
    bound_identity = {
        **identity,
        **({"schema": "v3"} if getattr(args, "schema", "v2") == "v3" else {}),
        "source_snapshot": source_snapshot,
    }
    fingerprint = cursor_fingerprint(command, root_path, bound_identity)
    try:
        offset = decode_cursor(args.cursor, fingerprint)
    except ValueError as exc:
        raise ValueError(f"--{exc}") from exc
    return bound_identity, offset


def _structural_payload(
    raw_items: Sequence[Mapping[str, Any]],
    args: argparse.Namespace,
    command: str,
    root_path: Path,
    identity: Mapping[str, Any],
    *,
    total_exact: bool = True,
    continuable: bool = True,
) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    projected: Sequence[Mapping[str, Any]] = (
        raw_items if args.detail == "full" else compact_structural_items(raw_items, root_path)
    )
    return page_items(
        projected,
        command=command,
        root_path=root_path,
        identity=identity,
        limit=args.limit,
        cursor=args.cursor,
        continuable=continuable,
        total_exact=total_exact,
    )


def compact_schema_version(args: argparse.Namespace) -> str:
    """Return the selected compact schema without changing the v2 default."""
    return V3_SCHEMA_VERSION if getattr(args, "schema", "v2") == "v3" else COMPACT_SCHEMA_VERSION


def _compact_envelope(command: str, *, args: argparse.Namespace | None = None, **payload: Any) -> dict[str, Any]:
    schema_version = V3_SCHEMA_VERSION if getattr(args, "schema", "v2") == "v3" else COMPACT_SCHEMA_VERSION
    return {"schema_version": schema_version, "ok": True, "command": command, **payload}


def handle_search(args: argparse.Namespace) -> int:
    indexer = XRayIndexer(normalize_path(args.root_path))
    identity, offset = _validate_page_args(
        args,
        "search",
        indexer.root_path,
        {"pattern": args.pattern, "lang": args.lang, "paths": args.paths or [], "globs": args.globs or []},
        indexer.repository_snapshot_fingerprint(),
    )
    matches = indexer.search_pattern(
        args.pattern,
        args.lang,
        paths=args.paths,
        globs=args.globs,
        max_results=offset + args.limit + 1,
    )
    page, metadata = _structural_payload(
        matches,
        args,
        "search",
        indexer.root_path,
        identity,
        total_exact=indexer.last_result_total_exact,
    )
    if args.format == "text":
        print_structural_items(page)
        if metadata["truncated"] and "next_cursor" in metadata:
            print(f"... {metadata['returned']} of {metadata['total']} results; next_cursor={metadata['next_cursor']}")
        return 0
    if args.detail == "compact":
        print_json(_compact_envelope("search", args=args, matches=page, **metadata), pretty=args.pretty)
        return 0
    print_json(
        _command_envelope(
            "search", indexer.root_path, pattern=args.pattern, language=args.lang, matches=page, **metadata
        ),
        pretty=args.pretty,
    )
    return 0


def handle_rewrite(args: argparse.Namespace) -> int:
    indexer = XRayIndexer(normalize_path(args.root_path))
    identity = {"pattern": args.pattern, "replacement": args.replacement, "lang": args.lang}
    identity, _offset = _validate_page_args(
        args, "rewrite", indexer.root_path, identity, indexer.repository_snapshot_fingerprint()
    )
    summary = indexer.rewrite_pattern(args.pattern, args.replacement, args.lang)
    if args.format == "text":
        changed = summary.get("changed_match_count", summary["match_count"])
        match_label = "match" if changed == 1 else "matches"
        file_label = "file" if summary["file_count"] == 1 else "files"
        print(
            f"{changed} {match_label} changed in {summary['file_count']} {file_label}; "
            f"{summary.get('no_op_count', 0)} no-op matches"
        )
        for path in summary["files_modified"]:
            print(path)
        return 0
    matches = summary.pop("matches", [])
    page, metadata = _structural_payload(matches, args, "rewrite", indexer.root_path, identity, continuable=False)
    metadata.pop("next_cursor", None)
    if args.detail == "compact":
        print_json(_compact_envelope("rewrite", args=args, **summary), pretty=args.pretty)
        return 0
    print_json(
        _command_envelope(
            "rewrite",
            indexer.root_path,
            pattern=args.pattern,
            replacement=args.replacement,
            language=args.lang,
            **summary,
            matches=page,
            **metadata,
        ),
        pretty=args.pretty,
    )
    return 0


def handle_scan(args: argparse.Namespace) -> int:
    indexer = XRayIndexer(normalize_path(args.root_path))
    identity = {
        "rule": args.rule,
        "fix": args.fix,
        "paths": args.paths or [],
        "globs": args.globs or [],
    }
    if args.fix and args.cursor:
        raise ValueError("--cursor cannot be used with scan --fix because fixes mutate the result set.")
    identity, offset = _validate_page_args(
        args, "scan", indexer.root_path, identity, indexer.repository_snapshot_fingerprint()
    )
    matches = indexer.scan_rules(
        args.rule,
        args.fix,
        paths=args.paths,
        globs=args.globs,
        max_results=None if args.fix else offset + args.limit + 1,
    )
    mutation_summary = indexer.last_mutation_summary if args.fix else None
    page, metadata = _structural_payload(
        matches,
        args,
        "scan",
        indexer.root_path,
        identity,
        total_exact=indexer.last_result_total_exact,
        continuable=not args.fix,
    )
    if args.fix:
        metadata.pop("next_cursor", None)
    if args.format == "text":
        print_structural_items(page)
        if mutation_summary is not None:
            print(
                f"changed={mutation_summary['changed_count']} files={mutation_summary['file_count']} "
                f"no_ops={mutation_summary['no_op_count']}"
            )
        if metadata["truncated"] and "next_cursor" in metadata:
            print(f"... {metadata['returned']} of {metadata['total']} results; next_cursor={metadata['next_cursor']}")
        return 0
    if args.detail == "compact":
        payload = _compact_envelope("scan", args=args, matches=page, fixed=args.fix, **metadata)
        if mutation_summary is not None:
            payload["mutation"] = mutation_summary
        print_json(payload, pretty=args.pretty)
        return 0
    print_json(
        _command_envelope(
            "scan",
            indexer.root_path,
            rule=args.rule,
            fixed=args.fix,
            matches=page,
            mutation=mutation_summary,
            **metadata,
        ),
        pretty=args.pretty,
    )
    return 0


def handle_rules_check(args: argparse.Namespace) -> int:
    indexer = XRayIndexer(normalize_path(args.root_path))
    result = indexer.check_rules(
        args.rule,
        paths=args.paths,
        globs=args.globs,
        max_results=args.limit,
    )
    print_json(_compact_envelope("rules.check", root_path=str(indexer.root_path), result=result), pretty=args.pretty)
    return 0


def handle_rules_explain(args: argparse.Namespace) -> int:
    indexer = XRayIndexer(normalize_path(args.root_path))
    result = indexer.explain_rules(args.rule, source_limit=args.source_limit)
    print_json(_compact_envelope("rules.explain", root_path=str(indexer.root_path), result=result), pretty=args.pretty)
    return 0


def handle_rules_test(args: argparse.Namespace) -> int:
    indexer = XRayIndexer(normalize_path(args.root_path))
    result = indexer.test_rules(test_dir=args.test_dir, config_path=args.config)
    print_json(_compact_envelope("rules.test", root_path=str(indexer.root_path), result=result), pretty=args.pretty)
    return 0


def handle_capabilities(args: argparse.Namespace) -> int:
    supplied_root = args.root_path is not None
    root = normalize_path(args.root_path) if supplied_root else str(Path.cwd().resolve())
    result = XRayIndexer(root).capabilities(include_repository=supplied_root)
    print_json(
        _compact_envelope("capabilities", args=args, invoked_as=args.command, capabilities=result),
        pretty=args.pretty,
    )
    return 0 if result["healthy"] else 1


def handle_outline_items(args: argparse.Namespace) -> int:
    indexer = XRayIndexer(normalize_path(args.root_path))
    identity = {"file_path": args.file_path}
    identity, _offset = _validate_page_args(
        args,
        args.outline_item,
        indexer.root_path,
        identity,
        indexer.repository_snapshot_fingerprint(),
    )
    items = indexer.file_outline_items(args.file_path, args.outline_item)
    page, metadata = _structural_payload(items, args, args.outline_item, indexer.root_path, identity)
    if args.format == "text":
        print_structural_items(page)
        if metadata["truncated"] and "next_cursor" in metadata:
            print(f"... {metadata['returned']} of {metadata['total']} results; next_cursor={metadata['next_cursor']}")
        return 0
    if args.detail == "compact":
        print_json(_compact_envelope(args.outline_item, args=args, items=page, **metadata), pretty=args.pretty)
        return 0
    print_json(
        _command_envelope(args.outline_item, indexer.root_path, file_path=args.file_path, items=page, **metadata),
        pretty=args.pretty,
    )
    return 0


def handle_skill_install(args: argparse.Namespace) -> int:
    try:
        result = install_cli_skill(project_root=args.project, force=args.force)
    except OSError as exc:
        raise SkillInstallError(f"skill installation failed: {exc}") from exc
    print_json(
        {
            "schema_version": SCHEMA_VERSION,
            "ok": True,
            "command": "skill",
            "action": "install",
            **result.as_dict(),
            "warnings": [],
        },
        pretty=args.pretty,
    )
    return 0


def handle_replace_plan(args: argparse.Namespace) -> int:
    """Create and emit a complete, bounded, non-mutating replacement plan."""
    pattern_source = args.pattern is not None or args.replacement is not None
    rule_source = args.rule is not None
    if pattern_source == rule_source:
        raise ValueError("Provide exactly one replacement source: --pattern/--replacement or --rule.")
    if pattern_source and (not args.pattern or args.replacement is None):
        raise ValueError("--pattern and --replacement must be provided together.")
    indexer = XRayIndexer(normalize_path(args.root_path))
    plan = indexer.plan_replacement(
        pattern=args.pattern,
        replacement=args.replacement,
        rule_path=args.rule,
        lang=args.lang,
        paths=args.paths,
        globs=args.globs,
        max_matches=args.max_matches,
        max_files=args.max_files,
        allow_noop=args.allow_noop,
        allow_truncated_review=args.allow_truncated_review,
        allow_dirty_affected=args.allow_dirty_affected,
        allow_new_parse_errors=args.allow_new_parse_errors,
        preview_limit=args.preview_limit,
        diff_limit=args.diff_limit,
    )
    print_json(_compact_envelope("replace.plan", plan=plan), pretty=args.pretty)
    return 0


def handle_replace_refine(args: argparse.Namespace) -> int:
    """Recompute a reviewed v2 plan for a selected stable edit subset."""
    indexer = XRayIndexer(normalize_path(args.root_path))
    plan = _read_plan_json(args.plan_file)
    refined = indexer.refine_replacement(plan, edit_ids=args.edit_ids)
    print_json(_compact_envelope("replace.refine", plan=refined), pretty=args.pretty)
    return 0


def _read_plan_json(path_value: str) -> dict[str, Any]:
    """Read a bounded replacement plan from a file or standard input."""
    if path_value == "-":
        raw = sys.stdin.read(MAX_PLAN_JSON_CHARS + 1)
        source = "stdin"
    else:
        path = Path(path_value).expanduser()
        try:
            if path.stat().st_size > MAX_PLAN_JSON_CHARS:
                raise ValueError(f"Replacement plan exceeds {MAX_PLAN_JSON_CHARS} characters.")
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"Could not read replacement plan file '{path_value}': {exc}") from exc
        source = str(path)
    if len(raw) > MAX_PLAN_JSON_CHARS:
        raise ValueError(f"Replacement plan from {source} exceeds {MAX_PLAN_JSON_CHARS} characters.")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Replacement plan from {source} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Replacement plan JSON must be an object.")
    plan = value.get("plan", value)
    if not isinstance(plan, dict):
        raise ValueError("Replacement plan envelope must contain an object field named 'plan'.")
    return plan


def handle_replace_apply(args: argparse.Namespace) -> int:
    """Apply one reviewed plan only after independent digest and source guards pass."""
    indexer = XRayIndexer(normalize_path(args.root_path))
    plan = _read_plan_json(args.plan_file)
    result = indexer.apply_replacement(plan, expected_digest=args.expected_digest)
    print_json(_compact_envelope("replace.apply", result=result), pretty=args.pretty)
    return 0


def handle_replace_verify(args: argparse.Namespace) -> int:
    """Recompute every replacement apply guard without writing files."""
    indexer = XRayIndexer(normalize_path(args.root_path))
    plan = _read_plan_json(args.plan_file)
    result = indexer.verify_replacement(plan, expected_digest=args.expected_digest)
    print_json(_compact_envelope("replace.verify", result=result), pretty=args.pretty)
    return 0


def print_structural_items(items: Sequence[Mapping[str, Any]]) -> None:
    """Print concise, lossy ast-grep results for human scanning."""
    for item in items:
        nested_items = item.get("items")
        if isinstance(nested_items, list):
            group_path = item.get("path") or item.get("file") or ""
            for nested_item in nested_items:
                if isinstance(nested_item, Mapping):
                    print_structural_item(nested_item, default_path=str(group_path))
            continue
        print_structural_item(item)


def print_structural_item(item: Mapping[str, Any], *, default_path: str = "") -> None:
    """Print one ast-grep match or outline item as a tab-separated scan line."""
    path = item.get("file") or item.get("path") or default_path
    range_data = item.get("range")
    start = range_data.get("start", {}) if isinstance(range_data, Mapping) else {}
    line = start.get("line") if isinstance(start, Mapping) else None
    if line is None:
        line = item.get("line")
    location = str(path)
    if line is not None:
        display_line = int(line) if "line" in item and not range_data else int(line) + 1
        location = f"{location}:{display_line}" if location else str(display_line)

    label = (
        item.get("text")
        or item.get("lines")
        or item.get("signature")
        or item.get("name")
        or item.get("kind")
        or item.get("ruleId")
        or item.get("id")
    )
    if label is None:
        label = json.dumps(item, separators=(",", ":"), sort_keys=True)
    label = " ".join(str(label).split())
    print(f"{location}\t{label}" if location else label)


def load_symbol(args: argparse.Namespace, root_path: Path | None = None) -> dict[str, Any]:
    sources = [bool(args.symbol_json), bool(args.symbol_file), bool(args.name or args.path)]
    if sum(sources) != 1:
        raise ValueError("Provide exactly one symbol source: --symbol-json, --symbol-file, or --name with --path.")

    if args.symbol_json:
        symbol = json.loads(args.symbol_json)
    elif args.symbol_file:
        if args.symbol_file == "-":
            raw = read_bounded_symbol_json(sys.stdin, "stdin")
        else:
            symbol_file = Path(args.symbol_file)
            try:
                raw = read_bounded_symbol_json_file(symbol_file)
            except OSError as exc:
                raise ValueError(f"Could not read symbol file '{args.symbol_file}': {exc.strerror or exc}") from exc
        symbol = json.loads(raw)
    else:
        if not args.name or not args.path:
            raise ValueError("Manual symbols require both --name and --path.")
        if args.start_line is None:
            raise ValueError(
                "Manual symbols require --start-line so the definition can be excluded from impact results."
            )
        symbol = {
            "name": args.name,
            "type": args.type,
            "path": args.path,
            "start_line": args.start_line,
            "end_line": args.end_line if args.end_line is not None else args.start_line,
        }

    symbol = validate_symbol_input(symbol)

    if root_path is not None:
        symbol = dict(symbol)
        if "abs_path" in symbol:
            resolve_inside_root(str(symbol["abs_path"]), root_path, "abs_path")
        symbol["path"] = str(resolve_inside_root(str(symbol["path"]), root_path, "path"))
    return symbol


def load_interface_symbol(args: argparse.Namespace, root_path: Path) -> dict[str, Any] | None:
    """Load the JSON-only exact-symbol alternatives accepted by interface."""
    if args.symbol_json and args.symbol_file:
        raise ValueError("Provide only one of --symbol-json or --symbol-file.")
    if not args.symbol_json and not args.symbol_file:
        return None
    if args.file_path:
        raise ValueError("Do not combine FILE_PATH with --symbol-json or --symbol-file.")
    if args.symbol_json:
        raw = args.symbol_json
    elif args.symbol_file == "-":
        raw = read_bounded_symbol_json(sys.stdin, "stdin")
    else:
        try:
            raw = read_bounded_symbol_json_file(Path(str(args.symbol_file)))
        except OSError as exc:
            raise ValueError(f"Could not read symbol file '{args.symbol_file}': {exc.strerror or exc}") from exc
    symbol = validate_symbol_input(json.loads(raw))
    symbol = dict(symbol)
    if "abs_path" in symbol:
        resolve_inside_root(str(symbol["abs_path"]), root_path, "abs_path")
    symbol["path"] = str(resolve_inside_root(str(symbol["path"]), root_path, "path"))
    return symbol


def read_bounded_symbol_json_file(path: Path) -> str:
    """Read a symbol JSON file with the same size cap as stdin."""
    try:
        if path.stat().st_size > MAX_SYMBOL_JSON_CHARS:
            raise ValueError(f"Symbol JSON exceeds {MAX_SYMBOL_JSON_CHARS} characters.")
    except FileNotFoundError:
        raise
    except OSError:
        pass

    with open(path, encoding="utf-8") as stream:
        return read_bounded_symbol_json(stream, str(path))


def read_bounded_symbol_json(stream: Any, source: str) -> str:
    """Read symbol JSON input while preventing accidental unbounded reads."""
    chunks: list[str] = []
    total = 0
    while True:
        chunk = stream.read(min(65536, MAX_SYMBOL_JSON_CHARS + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_SYMBOL_JSON_CHARS:
            raise ValueError(f"Symbol JSON from {source} exceeds {MAX_SYMBOL_JSON_CHARS} characters.")

    raw = "".join(chunks)
    if not raw.strip():
        raise ValueError(f"Symbol JSON from {source} is empty.")
    return raw


def resolve_inside_root(path: str, root_path: Path, field_name: str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root_path / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError:
        raise ValueError(f"Symbol {field_name} '{path}' is outside repository root '{root_path}'.")
    return candidate


def format_symbol_for_json(symbol: Mapping[str, Any], root_path: Path) -> dict[str, Any]:
    formatted = dict(symbol)
    symbol_path = Path(str(formatted.get("path", "")))
    abs_path = symbol_path if symbol_path.is_absolute() else (root_path / symbol_path).resolve()
    try:
        relative_path = abs_path.resolve().relative_to(root_path).as_posix()
    except ValueError:
        relative_path = str(formatted.get("path", ""))

    formatted["path"] = relative_path
    formatted["abs_path"] = str(abs_path.resolve())
    return dump_symbol_output(formatted)


def format_symbol(symbol: Mapping[str, Any]) -> str:
    location = f"{symbol.get('path', '')}:{symbol.get('start_line', '')}"
    symbol_type = symbol.get("type", "symbol")
    return f"{symbol.get('name', '')}\t{symbol_type}\t{location}"


def format_impact(result: Mapping[str, Any]) -> str:
    lines = [result.get("note", "")]
    for reference in result.get("references", []):
        location = f"{reference.get('file', '')}:{reference.get('line', '')}"
        lines.append(f"{location}\t{reference.get('type', 'reference')}")
        text = reference.get("text")
        if text:
            lines.append(text)
    return "\n".join(line for line in lines if line)


def print_json(value: Any, stream: Any = None, *, pretty: bool = False) -> None:
    if stream is None:
        stream = sys.stdout
    if pretty:
        output = json.dumps(value, indent=2, sort_keys=True)
    else:
        output = json.dumps(value, separators=(",", ":"), sort_keys=True)
    print(output, file=stream)


def leaf_command(args: argparse.Namespace) -> str | None:
    """Return the exact public leaf operation selected by parsed arguments."""
    command = getattr(args, "command", None)
    if command == "map":
        command = "explore"
    if not isinstance(command, str):
        return None
    nested = {
        "replace": getattr(args, "replace_command", None),
        "rules": getattr(args, "rules_command", None),
        "skill": getattr(args, "skill_command", None),
    }.get(command)
    return f"{command}.{nested}" if nested else command


def print_error(message: str, args: argparse.Namespace, *, code: str = "command_failed") -> None:
    if getattr(args, "format", None) == "json":
        compact = getattr(args, "detail", "compact") != "full"
        print_json(
            dump_error_envelope(
                {
                    "schema_version": compact_schema_version(args) if compact else SCHEMA_VERSION,
                    "ok": False,
                    "command": leaf_command(args),
                    "error": {"code": code, "message": message} if compact else message,
                    "warnings": [],
                }
            ),
            stream=sys.stderr,
            pretty=getattr(args, "pretty", False),
        )
    else:
        print(f"xray: {message}", file=sys.stderr)


def wants_json_output(argv: Sequence[str] | None) -> bool:
    args = list(sys.argv[1:] if argv is None else argv)
    for index, value in enumerate(args):
        if value == "--format" and index + 1 < len(args) and args[index + 1] == "text":
            return False
        if value == "--format=text":
            return False
    return True


def wants_pretty_output(argv: Sequence[str] | None) -> bool:
    args = list(sys.argv[1:] if argv is None else argv)
    return "--pretty" in args


def parse_command_name(argv: Sequence[str] | None) -> str | None:
    args = list(sys.argv[1:] if argv is None else argv)
    commands = {
        "explore",
        "map",
        "find",
        "interface",
        "read-symbol",
        "symbol-at",
        "impact",
        "search",
        "rewrite",
        "scan",
        "rules",
        "replace",
        "skill",
        "imports",
        "exports",
        "capabilities",
        "doctor",
    }
    for index, value in enumerate(args):
        if value not in commands:
            continue
        command = "explore" if value == "map" else "capabilities" if value == "doctor" else value
        if command in {"replace", "rules", "skill"} and index + 1 < len(args) and not args[index + 1].startswith("-"):
            return f"{command}.{args[index + 1]}"
        return command
    return None


def wants_full_output(argv: Sequence[str] | None) -> bool:
    args = list(sys.argv[1:] if argv is None else argv)
    return any(
        (value == "--detail" and index + 1 < len(args) and args[index + 1] == "full") or value == "--detail=full"
        for index, value in enumerate(args)
    )


def wants_v3_output(argv: Sequence[str] | None) -> bool:
    args = list(sys.argv[1:] if argv is None else argv)
    return any(
        (value == "--schema" and index + 1 < len(args) and args[index + 1] == "v3") or value == "--schema=v3"
        for index, value in enumerate(args)
    )


def print_parse_error(message: str, argv: Sequence[str] | None) -> None:
    if wants_json_output(argv):
        compact = not wants_full_output(argv)
        print_json(
            dump_error_envelope(
                {
                    "schema_version": (
                        V3_SCHEMA_VERSION
                        if compact and wants_v3_output(argv)
                        else COMPACT_SCHEMA_VERSION
                        if compact
                        else SCHEMA_VERSION
                    ),
                    "ok": False,
                    "command": parse_command_name(argv),
                    "error": {"code": "invalid_arguments", "message": message} if compact else message,
                    "warnings": [],
                }
            ),
            stream=sys.stderr,
            pretty=wants_pretty_output(argv),
        )
    else:
        print(message, file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except ParserExit as exc:
        if exc.status == 0:
            if exc.message:
                print(exc.message, end="")
            return 0
        print_parse_error(exc.message, argv)
        return exc.status

    handler: Callable[[argparse.Namespace], int] = args.handler
    try:
        return handler(args)
    except json.JSONDecodeError as exc:
        print_error(f"invalid JSON: {exc}", args, code="invalid_json")
        return 2
    except ValueError as exc:
        print_error(str(exc), args, code="invalid_request")
        return 2
    except InterfaceReadError as exc:
        print_error(str(exc), args, code=exc.code)
        return 1
    except AstGrepError as exc:
        print_error(str(exc), args, code="ast_grep_error")
        return 1
    except ReplacementApplyError as exc:
        print_error(str(exc), args, code="replacement_apply_failed")
        return 1
    except SkillInstallError as exc:
        print_error(str(exc), args, code="skill_install_failed")
        return 1
    except BrokenPipeError:
        return 1
    except Exception as exc:
        print_error(str(exc), args, code="internal_error")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
