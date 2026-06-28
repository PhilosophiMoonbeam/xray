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


class ParserExit(Exception):
    """Internal replacement for argparse's process-level exits."""

    def __init__(self, status: int = 0, message: str = ""):
        self.status = status
        self.message = message
        super().__init__(message)


class XRayArgumentParser(argparse.ArgumentParser):
    """ArgumentParser variant that lets cli.main return exit codes."""

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
        description="Agent-centric code intelligence CLI: map, find, inspect, and assess impact.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {get_version()}")

    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=XRayArgumentParser)

    explore = subparsers.add_parser(
        "explore",
        aliases=["map"],
        help="Map repository structure, optionally with symbols.",
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
    explore.add_argument("--format", choices=("text", "json"), default="text")
    explore.set_defaults(handler=handle_explore)

    find = subparsers.add_parser("find", help="Find functions, classes, methods, and types by fuzzy query.")
    find.add_argument("root_path", help="Repository root to inspect.")
    find.add_argument("query", help="Symbol query, such as 'auth service' or 'parse_json'.")
    find.add_argument("--limit", type=int, default=10, help="Maximum number of matches to return.")
    find.add_argument(
        "--min-score",
        type=int,
        default=0,
        help="Minimum fuzzy match score, from 0 to 100. Use 60+ to suppress weak matches.",
    )
    find.add_argument("--format", choices=("json", "text"), default="json")
    find.set_defaults(handler=handle_find)

    interface = subparsers.add_parser("interface", help="Show a file interface without implementation bodies.")
    interface.add_argument("root_path", help="Repository root to inspect.")
    interface.add_argument("file_path", help="File path, absolute or relative; must resolve inside the root.")
    interface.add_argument("--format", choices=("text", "json"), default="text")
    interface.set_defaults(handler=handle_interface)

    impact = subparsers.add_parser(
        "impact",
        help="Find references that may break if a symbol changes.",
        description=(
            "Find references that may break if a symbol changes. Provide exactly one symbol source: "
            "--symbol-json, --symbol-file, or --name with --path and --start-line."
        ),
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
    impact.add_argument("--format", choices=("json", "text"), default="json")
    impact.set_defaults(handler=handle_impact)

    return parser


def handle_explore(args: argparse.Namespace) -> int:
    if args.max_depth is not None and args.max_depth < 0:
        raise ValueError("--max-depth must be 0 or greater.")
    if args.max_symbols_per_file < 0:
        raise ValueError("--max-symbols-per-file must be 0 or greater.")

    indexer = XRayIndexer(normalize_path(args.root_path))
    tree = indexer.explore_repo(
        max_depth=args.max_depth,
        include_symbols=args.include_symbols,
        focus_dirs=args.focus_dirs,
        max_symbols_per_file=args.max_symbols_per_file,
    )
    if args.format == "json":
        data = indexer.explore_repo_data(
            max_depth=args.max_depth,
            include_symbols=args.include_symbols,
            focus_dirs=args.focus_dirs,
            max_symbols_per_file=args.max_symbols_per_file,
        )
        data = dump_explore_data(data)
        invoked_as = args.command
        data.update(
            {
                "schema_version": SCHEMA_VERSION,
                "ok": True,
                "command": "explore",
                "invoked_as": invoked_as,
                "tree_text": tree,
                "warnings": [],
            }
        )
        print_json(dump_explore_envelope(data))
    else:
        print(tree)
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
            )
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
            )
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
            )
        )
    return 1 if is_error else 0


def load_symbol(args: argparse.Namespace, root_path: Path | None = None) -> dict[str, Any]:
    sources = [bool(args.symbol_json), bool(args.symbol_file), bool(args.name or args.path)]
    if sum(sources) != 1:
        raise ValueError("Provide exactly one symbol source: --symbol-json, --symbol-file, or --name with --path.")

    if args.symbol_json:
        symbol = json.loads(args.symbol_json)
    elif args.symbol_file:
        if args.symbol_file == "-":
            raw = sys.stdin.read()
        else:
            raw = Path(args.symbol_file).read_text(encoding="utf-8")
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


def print_json(value: Any, stream: Any = None) -> None:
    if stream is None:
        stream = sys.stdout
    print(json.dumps(value, indent=2, sort_keys=True), file=stream)


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
        )
    else:
        print(f"xray: {message}", file=sys.stderr)


def wants_json_output(argv: Sequence[str] | None) -> bool:
    args = list(sys.argv[1:] if argv is None else argv)
    for index, value in enumerate(args):
        if value == "--format" and index + 1 < len(args) and args[index + 1] == "json":
            return True
        if value == "--format=json":
            return True
    return False


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
    except BrokenPipeError:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
