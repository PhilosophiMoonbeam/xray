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
from xray.core.indexer import XRayIndexer
from xray.models import (
    dump_error_envelope,
    dump_explore_data,
    dump_explore_envelope,
    dump_find_envelope,
    dump_impact_envelope,
    dump_impact_result,
    dump_interface_envelope,
    dump_symbol_output,
    validate_symbol_input,
)

SCHEMA_VERSION = "xray.cli.v1"
MAX_SCORE = 100
MAX_SYMBOL_JSON_CHARS = 1024 * 1024
OUTPUT_FORMAT_HELP = "Output format. json is the default automation contract; text is a lossy scan mode."
PRETTY_HELP = "Pretty-print JSON output; ignored with --format text."

ROOT_HELP_EPILOG = """\
Progressive workflow:
  xray explore ROOT --max-depth 2
  xray find ROOT "target symbol" --min-score 60
  xray interface ROOT path/from/find.py
  symbol=$(xray find ROOT "target symbol" --limit 1 | jq -c '.symbols[0]')
  xray impact ROOT --symbol-json "$symbol"  # likely symbol-name references

Structural workflow:
  xray search ROOT -p 'old_api($ARG)' -l python
  xray imports ROOT src/package/module.py

Subcommands emit compact JSON by default. Use subcommand --pretty for indented
JSON or --format text for compact lossy scans. YAML output is unsupported.
Commands rewrite and scan --fix modify files in place.
Exit codes: 0 success, 1 command failure, 2 parse or validation error.
"""

EXPLORE_HELP = """\
Map repository structure before reading large files. Start shallow, then add
--focus and --include-symbols when you know where to zoom in.
"""

EXPLORE_EPILOG = """\
Examples:
  xray explore ROOT --max-depth 2
  xray explore ROOT --focus src --include-symbols --max-symbols-per-file 5
  xray map ROOT --format text

Default JSON includes schema_version, ok, root_path, tree_text, entries,
options, warnings, and invoked_as. The map alias reports command "explore".
"""

FIND_EPILOG = """\
Examples:
  xray find ROOT "AuthService.validate_user" --limit 5 --min-score 60
  xray find ROOT "target_function" --format text

Default JSON symbols are complete inputs for name-based impact analysis: path, abs_path,
start_line, end_line, type, and score.
Use --min-score 60 or higher to suppress weak fuzzy matches.
"""

INTERFACE_HELP = """\
Show signatures, class definitions, types, and docstrings for one file without
printing implementation bodies.
"""

INTERFACE_EPILOG = """\
Examples:
  xray interface ROOT src/package/module.py
  xray interface ROOT /absolute/path/inside/root.py --format text

FILE_PATH may be absolute or relative, but it must resolve inside ROOT. XRAY
rejects parent traversal and symlink escapes rather than reading outside files.
"""

IMPACT_HELP = """\
Find likely symbol-name code references for impact review. This is not a
type-aware caller or dependency graph. Provide exactly one symbol source:
--symbol-json, --symbol-file, or --name with --path and --start-line.
"""

IMPACT_EPILOG = """\
Examples:
  symbol=$(xray find ROOT "target_function" --limit 1 | jq -c '.symbols[0]')
  xray impact ROOT --symbol-json "$symbol"
  xray find ROOT "target_function" --limit 1 | jq -c '.symbols[0]' | xray impact ROOT --symbol-file -
  xray impact ROOT --name target_function --path src/app.py --start-line 42 --type function

Symbols returned by xray find are the safest input. Symbol paths must resolve
inside ROOT. Default JSON includes impact.strategy, counts, references, and note.
Review results for same-name symbols; impact analysis is name-based.
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
        description=(
            "Agent-centric code intelligence CLI: explore repositories, find and inspect symbols,\n"
            "review name-based impact, and structurally search, rewrite, scan, or outline code."
        ),
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
    explore.add_argument("--max-depth", type=int, default=None, help="Maximum directory depth to traverse.")
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
        help="Top-level directory to focus on. Repeat for multiple directories.",
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
        type=int,
        default=5000,
        help="Maximum files and directories returned (default: 5000); truncation is reported.",
    )
    explore.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help=OUTPUT_FORMAT_HELP,
    )
    explore.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    explore.set_defaults(handler=handle_explore)

    find = subparsers.add_parser(
        "find",
        help="Find functions, classes, methods, and types by fuzzy query.",
        description="Find definitions by fuzzy name, behavior phrase, or owner-qualified symbol path.",
        epilog=FIND_EPILOG,
    )
    find.add_argument("root_path", help="Repository root to inspect.")
    find.add_argument("query", help="Symbol query, such as 'auth service' or 'parse_json'.")
    find.add_argument("--limit", type=int, default=10, help="Maximum number of matches to return.")
    find.add_argument(
        "--min-score",
        type=int,
        default=0,
        help="Minimum fuzzy match score, from 0 to 100. Use 60+ to suppress weak matches.",
    )
    find.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help=OUTPUT_FORMAT_HELP,
    )
    find.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    find.set_defaults(handler=handle_find)

    interface = subparsers.add_parser(
        "interface",
        help="Show a file interface without implementation bodies.",
        description=INTERFACE_HELP,
        epilog=INTERFACE_EPILOG,
    )
    interface.add_argument("root_path", help="Repository root to inspect.")
    interface.add_argument("file_path", help="File path, absolute or relative; must resolve inside the root.")
    interface.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help=OUTPUT_FORMAT_HELP,
    )
    interface.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    interface.set_defaults(handler=handle_interface)

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
    impact.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help=OUTPUT_FORMAT_HELP,
    )
    impact.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    impact.set_defaults(handler=handle_impact)

    search = subparsers.add_parser("search", help="Search code with an ast-grep structural pattern.")
    search.add_argument("root_path", help="Repository root to search.")
    search.add_argument("-p", "--pattern", required=True, help="ast-grep structural pattern.")
    search.add_argument("-l", "--lang", help="Pattern language when it cannot be inferred.")
    search.add_argument("--format", choices=("json", "text"), default="json", help=OUTPUT_FORMAT_HELP)
    search.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    search.set_defaults(handler=handle_search)

    rewrite = subparsers.add_parser("rewrite", help="Apply an ast-grep structural rewrite in place.")
    rewrite.add_argument("root_path", help="Repository root to rewrite.")
    rewrite.add_argument("-p", "--pattern", required=True, help="ast-grep structural pattern.")
    rewrite.add_argument("-r", "--replacement", required=True, help="Replacement template.")
    rewrite.add_argument("-l", "--lang", help="Pattern language when it cannot be inferred.")
    rewrite.add_argument("--format", choices=("json", "text"), default="json", help=OUTPUT_FORMAT_HELP)
    rewrite.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    rewrite.set_defaults(handler=handle_rewrite)

    scan = subparsers.add_parser("scan", help="Scan code with ast-grep YAML rules.")
    scan.add_argument("root_path", help="Repository root to scan.")
    scan.add_argument("--rule", required=True, help="Rule configuration file or directory inside the root.")
    scan.add_argument("--fix", action="store_true", help="Apply every rule fix without prompting.")
    scan.add_argument("--format", choices=("json", "text"), default="json", help=OUTPUT_FORMAT_HELP)
    scan.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
    scan.set_defaults(handler=handle_scan)

    for command in ("imports", "exports"):
        outline = subparsers.add_parser(command, help=f"List file {command} using ast-grep outline.")
        outline.add_argument("root_path", help="Repository root containing the file.")
        outline.add_argument("file_path", help="File path, absolute or relative; must stay inside the root.")
        outline.add_argument("--format", choices=("json", "text"), default="json", help=OUTPUT_FORMAT_HELP)
        outline.add_argument("--pretty", action="store_true", help=PRETTY_HELP)
        outline.set_defaults(handler=handle_outline_items, outline_item=command)

    return parser


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
        max_symbols_per_file=args.max_symbols_per_file,
        symbol_types=symbol_types,
        max_entries=args.max_entries,
    )
    if args.format == "json":
        data = dump_explore_data(data)
        invoked_as = args.command
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
    results = indexer.find_symbol(
        args.query,
        limit=args.limit,
        min_score=args.min_score,
        include_scores=args.format == "json",
    )
    warnings = list(getattr(indexer, "last_warnings", []))
    search_failed = not getattr(indexer, "last_search_succeeded", False)
    if args.format == "text":
        for symbol in results:
            print(format_symbol(symbol))
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
    else:
        symbols = [format_symbol_for_json(symbol, indexer.root_path) for symbol in results]
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
                    "symbols": symbols,
                    "error": "Symbol search failed." if search_failed else None,
                    "warnings": warnings,
                }
            ),
            pretty=args.pretty,
        )
    return 1 if search_failed else 0


def handle_interface(args: argparse.Namespace) -> int:
    indexer = XRayIndexer(normalize_path(args.root_path))
    interface = indexer.read_interface(args.file_path)
    is_error = interface.startswith("Error")
    if args.format == "json":
        print_json(
            dump_interface_envelope(
                {
                    "schema_version": SCHEMA_VERSION,
                    "ok": not is_error,
                    "command": "interface",
                    "root_path": str(indexer.root_path),
                    "file_path": args.file_path,
                    "interface": None if is_error else interface,
                    "error": interface if is_error else None,
                    "warnings": [],
                }
            ),
            pretty=args.pretty,
        )
    else:
        print(interface)
    return 1 if is_error else 0


def handle_impact(args: argparse.Namespace) -> int:
    if args.context_lines < 0:
        raise ValueError("--context-lines must be 0 or greater.")
    if args.start_line is not None and args.start_line < 1:
        raise ValueError("--start-line must be 1 or greater.")
    if args.end_line is not None and args.end_line < 1:
        raise ValueError("--end-line must be 1 or greater.")

    indexer = XRayIndexer(normalize_path(args.root_path))
    symbol = load_symbol(args, indexer.root_path)
    result = indexer.what_breaks(symbol, context_lines=args.context_lines)
    result = dump_impact_result(result)
    is_error = isinstance(result, dict) and "error" in result
    if args.format == "text":
        print(format_impact(result))
    else:
        print_json(
            dump_impact_envelope(
                {
                    "schema_version": SCHEMA_VERSION,
                    "ok": not is_error,
                    "command": "impact",
                    "root_path": str(indexer.root_path),
                    "symbol": format_symbol_for_json(symbol, indexer.root_path),
                    "impact": result,
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


def handle_search(args: argparse.Namespace) -> int:
    indexer = XRayIndexer(normalize_path(args.root_path))
    matches = indexer.search_pattern(args.pattern, args.lang)
    if args.format == "text":
        print_structural_items(matches)
        return 0
    print_json(
        _command_envelope("search", indexer.root_path, pattern=args.pattern, language=args.lang, matches=matches),
        pretty=args.pretty,
    )
    return 0


def handle_rewrite(args: argparse.Namespace) -> int:
    indexer = XRayIndexer(normalize_path(args.root_path))
    summary = indexer.rewrite_pattern(args.pattern, args.replacement, args.lang)
    if args.format == "text":
        match_label = "match" if summary["match_count"] == 1 else "matches"
        file_label = "file" if summary["file_count"] == 1 else "files"
        print(f"{summary['match_count']} {match_label} rewritten in {summary['file_count']} {file_label}")
        for path in summary["files_modified"]:
            print(path)
        return 0
    print_json(
        _command_envelope(
            "rewrite",
            indexer.root_path,
            pattern=args.pattern,
            replacement=args.replacement,
            language=args.lang,
            **summary,
        ),
        pretty=args.pretty,
    )
    return 0


def handle_scan(args: argparse.Namespace) -> int:
    indexer = XRayIndexer(normalize_path(args.root_path))
    matches = indexer.scan_rules(args.rule, args.fix)
    if args.format == "text":
        print_structural_items(matches)
        return 0
    print_json(
        _command_envelope("scan", indexer.root_path, rule=args.rule, fixed=args.fix, matches=matches),
        pretty=args.pretty,
    )
    return 0


def handle_outline_items(args: argparse.Namespace) -> int:
    indexer = XRayIndexer(normalize_path(args.root_path))
    items = indexer.file_outline_items(args.file_path, args.outline_item)
    if args.format == "text":
        print_structural_items(items)
        return 0
    print_json(
        _command_envelope(args.outline_item, indexer.root_path, file_path=args.file_path, items=items),
        pretty=args.pretty,
    )
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
    location = str(path)
    if line is not None:
        location = f"{location}:{int(line) + 1}" if location else str(int(line) + 1)

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


def print_error(message: str, args: argparse.Namespace) -> None:
    if getattr(args, "format", None) == "json":
        print_json(
            dump_error_envelope(
                {
                    "schema_version": SCHEMA_VERSION,
                    "ok": False,
                    "command": getattr(args, "command", None),
                    "error": message,
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
    for value in args:
        if value.startswith("-"):
            continue
        if value == "map":
            return "explore"
        return value
    return None


def print_parse_error(message: str, argv: Sequence[str] | None) -> None:
    if wants_json_output(argv):
        print_json(
            dump_error_envelope(
                {
                    "schema_version": SCHEMA_VERSION,
                    "ok": False,
                    "command": parse_command_name(argv),
                    "error": message,
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
        print_error(f"invalid JSON: {exc}", args)
        return 2
    except ValueError as exc:
        print_error(str(exc), args)
        return 2
    except AstGrepError as exc:
        print_error(str(exc), args)
        return 1
    except BrokenPipeError:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
