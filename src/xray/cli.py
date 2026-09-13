"""Handwritten shell adapter for the enabled XRAY I2 operations.

The CLI deliberately stays thin: it parses the natural shell grammar, normalizes
only explicitly supplied shell paths, builds the canonical typed request, and
serializes the result returned by :func:`xray.operations.execute`.  Repository
capture, reference validation, paging, fitting, and all operation defaults live
behind that shared application boundary.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from xray import __version__
from xray.models import AdministrativeData, AdministrativeSuccess, Error
from xray.operations import Result, execute
from xray.presentation import canonical_json
from xray.skill_installer import install_cli_skill

CLI_COMMANDS = frozenset(
    {
        "map",
        "find",
        "interface",
        "read",
        "impact",
        "search",
        "change",
        "capabilities",
        "skill",
    }
)
MAX_REQUEST_JSON_BYTES = 1_048_576
MAX_ERROR_MESSAGE_BYTES = 512
MAX_READ_TARGETS = 8
_CLI_ERROR_RESPONSE_BYTES = 4_096

_CLI_HARD_RESPONSE_BYTES = {
    "capabilities": 65_536,
    "map": 65_536,
    "find": 65_536,
    "interface": 65_536,
    "read": 65_536,
    "impact": 65_536,
    "search": 65_536,
    "change_plan": 262_144,
    "change_refine": 262_144,
    "change_verify": 65_536,
    "change_apply": 65_536,
}


class CliInputError(ValueError):
    """A shell grammar or explicitly supplied shell-input failure."""

    def __init__(self, message: str, *, code: str = "invalid_request") -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class OutputOptions:
    format: str = "json"
    pretty: bool = False


@dataclass(frozen=True)
class ParsedCommand:
    operation: str
    request: dict[str, Any] | None = None
    output: OutputOptions = OutputOptions()
    admin: bool = False
    project_root: str | None = None
    force: bool = False


MAP_HELP = """Usage: xray map ROOT [options]

Map the explicitly rooted repository namespace without reading source bodies.
The default focus is ROOT and the default depth is two.

Options:
  --focus PATH            Include a contained focus path (repeatable).
  --depth N|all           Descendant depth (0..64 or all).
  --context none|ancestors
                          Include focus ancestors when requested.
  --exclusions default|none
                          Apply or disable generated exclusions.
  --cursor TOKEN          Continue a previous bounded map page.
  --limit N               Maximum namespace entries (1..1000).
  --max-bytes N           Maximum response bytes for the page.
  --timeout-seconds N     Operation deadline in seconds.
  --cache auto|off        Operation cache policy.
  --format json|text      JSON (default) or lossy text.
  --pretty                Indent JSON output.
"""

FIND_HELP = """Usage: xray find ROOT QUERY [options]

Find declarations by their canonical name or qualified identity.

Options:
  --match name|exact|fuzzy
                          Name matching policy (name is the default).
  --path PATH             Restrict the selected repository path (repeatable).
  --glob PATTERN          Restrict selection with an ordered glob (repeatable).
  --language LANGUAGE     Restrict selection to python, javascript, typescript,
                          or go (repeatable).
  --exclusions default|none
                          Apply or disable generated exclusions.
  --kinds KIND            Restrict declaration kinds (repeatable).
  --visibility VALUE      Restrict visibility: public, private, or unknown
                          (repeatable).
  --cursor TOKEN          Continue a previous bounded find page.
  --limit N               Maximum matches (1..100).
  --max-bytes N           Maximum response bytes for the page.
  --timeout-seconds N     Operation deadline in seconds.
  --cache auto|off        Operation cache policy.
  --format json|text      JSON (default) or lossy text.
  --pretty                Indent JSON output.
"""

INTERFACE_HELP = """Usage: xray interface ROOT FILE [options]
       xray interface ROOT --ref-json JSON [options]
       xray interface ROOT --ref-file FILE [options]

Read a bounded interface from one contained file or one exact symbol
reference. Use '-' as FILE for JSON on standard input.

Options:
  --sections SECTION      Include symbols, imports, or exports (repeatable).
  --member-depth N        Direct member depth, zero or one.
  --documentation         Include declaration documentation.
  --kinds KIND            Filter file declarations by kind (repeatable).
  --visibility VALUE      Filter file declarations by visibility (repeatable).
  --cursor TOKEN          Continue a previous bounded interface page.
  --limit N               Maximum interface items (1..200).
  --max-bytes N           Maximum response bytes for the page.
  --timeout-seconds N     Operation deadline in seconds.
  --cache auto|off        Operation cache policy.
  --format json|text      JSON (default) or lossy text.
  --pretty                Indent JSON output.
"""

READ_HELP = """Usage: xray read ROOT TARGET [options]
       xray read ROOT --ref-json JSON [options]
       xray read ROOT --ref-file FILE [options]
       xray read ROOT --targets-file FILE [options]

Read one exact location or reference, or a JSON batch of one to eight targets.
ROOT is required and is normalized by the shell before the typed request.

Location form:
  TARGET is a contained file path; --line is required, with optional
  --end-line and --column. Reference forms are --ref-json, --ref-file, or
  --targets-file (use '-' for stdin).

Options:
  --context-lines N       Include N surrounding lines (0..10).
  --include-enclosing     Include enclosing-symbol results (default).
  --no-enclosing          Omit enclosing-symbol results.
  --cursor TOKEN          Continue a previous bounded read page.
  --max-bytes N           Maximum response bytes for the page.
  --max-lines N           Maximum source lines for the page.
  --source-bytes N        Maximum source bytes for the page.
  --timeout-seconds N     Operation deadline in seconds.
  --cache auto|off        Operation cache policy.
  --format json|text      JSON (default) or lossy text.
  --pretty                Indent JSON output.
"""

SEARCH_HELP = """Usage: xray search ROOT [source] [options]

Search captured repository text, syntax patterns, or one explicit rule/config
input. Exactly one source is required: --literal, --pattern, --rule, or
--config. Pattern searches require an explicit --lang.

Sources:
  --literal TEXT           Exact case-sensitive UTF-8 text.
  --pattern PATTERN        Structural ast-grep pattern.
  --lang LANGUAGE          Pattern language: python, javascript, typescript, go.
  --rule FILE              One contained standalone rule file.
  --config FILE            One contained ruleDirs-only configuration file.

Selection and result options:
  --path PATH              Restrict selection (repeatable).
  --glob PATTERN           Restrict selection with an ordered glob (repeatable).
  --language LANGUAGE      Restrict selection language (repeatable).
  --exclusions default|none
                           Apply or disable generated exclusions.
  --detail summary|detail  Include verified captures in detail mode.
  --cursor TOKEN           Continue a previous bounded search page.
  --limit N                Maximum matches (1..1000).
  --max-bytes N            Maximum response bytes for the page.
  --timeout-seconds N      Operation deadline in seconds.
  --cache auto|off         Operation cache policy.
  --format json|text       JSON (default) or lossy text.
  --pretty                 Indent JSON output.
"""

IMPACT_HELP = """Usage: xray impact ROOT --ref-json JSON [options]
       xray impact ROOT --ref-file FILE [options]

Report unresolved occurrences for one exact captured symbol reference. Use
--ref-file - to read the reference JSON from standard input.

Options:
  --mode syntax|lexical     Choose syntax evidence or explicit lexical evidence.
  --path PATH               Restrict selection (repeatable).
  --glob PATTERN            Restrict selection with an ordered glob (repeatable).
  --language LANGUAGE       Restrict selection language (repeatable).
  --exclusions default|none
                            Apply or disable generated exclusions.
  --cursor TOKEN            Continue a previous bounded impact page.
  --limit N                 Maximum matches (1..1000).
  --max-bytes N             Maximum response bytes for the page.
  --timeout-seconds N       Operation deadline in seconds.
  --cache auto|off          Operation cache policy.
  --format json|text        JSON (default) or lossy text.
  --pretty                  Indent JSON output.
"""

CHANGE_HELP = """Usage: xray change plan|refine|verify|apply ROOT [options]

Plan, refine, verify, or apply one complete guarded structural change.
Only the apply leaf can write repository source files.

Leaves:
  plan                  Build a complete non-mutating change plan.
  refine                Select reviewed edit IDs and emit a new plan.
  verify                Recheck a complete plan without writing.
  apply                 Recheck and apply a complete reviewed plan.
"""

CHANGE_PLAN_HELP = """Usage: xray change plan ROOT [options]

Build a complete non-mutating pattern or rule/config change plan.

Sources (exactly one):
  --pattern PATTERN        Structural ast-grep pattern.
  --replacement TEXT       Replacement template paired with --pattern.
  --lang LANGUAGE          Pattern language: python, javascript, typescript, go.
  --rule FILE               One contained standalone rule file.
  --config FILE             One contained ruleDirs-only configuration file.

Selection:
  --path PATH               Restrict selection (repeatable).
  --glob PATTERN            Restrict selection with an ordered glob (repeatable).
  --language LANGUAGE       Restrict selection language (repeatable).
  --exclusions default|none
                            Apply or disable generated exclusions.

Plan bounds and acknowledgements:
  --max-candidates N        Candidate cap (1..1000).
  --max-files N             Affected-file cap (1..100).
  --max-bytes N             Complete-plan response cap (4096..262144).
  --allow-dirty-affected    Acknowledge affected files dirty in Git.
  --allow-new-parse-errors  Acknowledge newly introduced parse errors.

  --timeout-seconds N       Operation deadline in seconds.
  --cache auto|off          Operation cache policy.
  --format json|text        JSON (default) or lossy text.
  --pretty                  Indent JSON output.
"""

CHANGE_REFINE_HELP = """Usage: xray change refine ROOT --plan-file FILE [options]

Select sorted edit IDs from a complete plan and emit a new complete plan.
FILE is a complete xray.change.v1 plan or '-' for standard input. Repeating
--edit-id selects the corresponding edits; omitting it selects none.

Options:
  --edit-id DIGEST          Reviewed edit ID (repeatable, sorted).
  --timeout-seconds N       Operation deadline in seconds.
  --cache auto|off          Operation cache policy.
  --format json|text        JSON (default) or lossy text.
  --pretty                  Indent JSON output.
"""

CHANGE_VERIFY_HELP = """Usage: xray change verify ROOT --plan-file FILE --expected-digest DIGEST [options]

Verify a complete reviewed plan without writing repository source files.
FILE is a complete xray.change.v1 plan or '-' for standard input.

Options:
  --timeout-seconds N       Operation deadline in seconds.
  --cache auto|off          Operation cache policy.
  --format json|text        JSON (default) or lossy text.
  --pretty                  Indent JSON output.
"""

CHANGE_APPLY_HELP = """Usage: xray change apply ROOT --plan-file FILE --expected-digest DIGEST [options]

Verify and apply a complete reviewed plan. Apply is the only change leaf that
can write repository source files. FILE is a complete xray.change.v1 plan or
'-' for standard input.

Options:
  --timeout-seconds N       Operation deadline in seconds.
  --cache auto|off          Operation cache policy.
  --format json|text        JSON (default) or lossy text.
  --pretty                  Indent JSON output.
"""

CAPABILITIES_HELP = """Usage: xray capabilities [ROOT] [options]

Report enabled-operation capabilities. Without ROOT this is a rootless catalog
check; ROOT is never inferred from the current directory.

Options:
  --detail summary|detail  Include enabled operation summaries in detail mode.
  --timeout-seconds N      Operation deadline in seconds.
  --format json|text       JSON (default) or lossy text.
  --pretty                 Indent JSON output.
"""

SKILL_HELP = """Usage: xray skill install [--user | --project ROOT] [--force] [--pretty]

Install the bundled xray-cli skill. The default scope is the current user's
home. A divergent existing target is refused unless --force is supplied.
"""

ROOT_HELP = """Usage: xray COMMAND [options]

Enabled commands:
  map              Map the explicitly rooted repository namespace.
  find             Find declarations by name or qualified identity.
  interface        Read one bounded file or symbol interface.
  read             Read exact captured source targets.
  impact           Report unresolved syntax or lexical symbol occurrences.
  search           Search literal text, syntax patterns, or selected rules.
  change             Plan, refine, verify, or apply a guarded structural change.
  capabilities     Report the enabled operation catalog and health.
  skill install    Install the bundled shell-agent skill.
Global options:
  --version        Print the XRAY version.
  --help           Show this help.
"""


def get_version() -> str:
    """Return the installed distribution version, with source fallback."""
    try:
        return metadata.version("xray")
    except metadata.PackageNotFoundError:
        return __version__


def normalize_shell_root(value: str) -> str:
    """Resolve an explicitly supplied shell root to an existing directory."""
    if not isinstance(value, str) or not value:
        raise CliInputError("ROOT must be a non-empty path")
    if "\x00" in value:
        raise CliInputError("ROOT must not contain NUL bytes")
    try:
        candidate = Path(value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise CliInputError(f"ROOT cannot be resolved: {value}") from exc
    if not candidate.is_dir():
        raise CliInputError(f"ROOT is not a directory: {value}")
    return candidate.as_posix()


def _bounded_message(value: object) -> str:
    text = str(value) or "request failed"
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_ERROR_MESSAGE_BYTES:
        text = encoded[:MAX_ERROR_MESSAGE_BYTES].decode("utf-8", errors="ignore")
    return text or "request failed"


def _error_payload(operation: str | None, code: str, message: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "schema": "xray.v1",
        "ok": False,
        "error": {"code": code, "message": _bounded_message(message)},
    }
    if operation is not None:
        values["op"] = operation
        if operation == "change_apply":
            values["mutation"] = {"state": "not_applied", "rollback_status": "not_attempted"}
    return Error.model_validate(values).to_payload()


def _strict_json_constant(value: str) -> Any:
    raise ValueError(f"invalid JSON constant {value!r}")


def _parse_json(raw: bytes, source: str) -> Any:
    if len(raw) > MAX_REQUEST_JSON_BYTES:
        raise CliInputError(f"JSON input from {source} exceeds {MAX_REQUEST_JSON_BYTES} bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CliInputError(f"JSON input from {source} is not valid UTF-8") from exc
    if not text.strip():
        raise CliInputError(f"JSON input from {source} is empty")
    try:
        return json.loads(text, parse_constant=_strict_json_constant)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CliInputError(f"JSON input from {source} is not valid JSON: {exc}") from exc


def _read_json_source(value: str) -> Any:
    if value == "-":
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        try:
            raw = stream.read(MAX_REQUEST_JSON_BYTES + 1)
        except OSError as exc:
            raise CliInputError(f"could not read JSON input from stdin: {exc}") from exc
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        if not isinstance(raw, bytes):
            raise CliInputError("could not read JSON input from stdin")
        return _parse_json(raw, "stdin")

    path = Path(value).expanduser()
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_REQUEST_JSON_BYTES + 1)
    except OSError as exc:
        raise CliInputError(f"could not read JSON file '{value}': {exc}") from exc
    return _parse_json(raw, str(path))


def _as_int(name: str, value: str) -> int:
    try:
        return int(value, 10)
    except (TypeError, ValueError) as exc:
        raise CliInputError(f"{name} requires an integer") from exc


def _split_option(token: str) -> tuple[str, str | None]:
    if not token.startswith("--") or token == "--":
        return token, None
    if "=" in token:
        name, value = token.split("=", 1)
        return name, value
    return token, None


def _option_value(tokens: list[str], index: int, name: str, inline: str | None) -> tuple[str, int]:
    if inline is not None:
        return inline, index
    next_index = index + 1
    if next_index >= len(tokens):
        raise CliInputError(f"{name} requires a value")
    return tokens[next_index], next_index


def _ensure_unique(seen: set[str], name: str) -> None:
    if name in seen:
        raise CliInputError(f"{name} may be supplied only once")
    seen.add(name)


def _normalize_location_path(value: str, root: str) -> str:
    """Normalize a natural location path without dereferencing its target."""
    if not value or "\x00" in value:
        raise CliInputError("TARGET must be a non-empty path")
    root_path = Path(root)
    expanded = Path(value).expanduser()
    if expanded.is_absolute():
        candidate = Path(os.path.normpath(expanded.as_posix()))
        try:
            relative = candidate.relative_to(root_path)
        except ValueError as exc:
            raise CliInputError(f"TARGET '{value}' is outside ROOT '{root}'", code="path_outside_root") from exc
    else:
        relative = Path(os.path.normpath(value))
        if relative.is_absolute() or relative == Path(".") or relative.parts[:1] == ("..",):
            raise CliInputError(f"TARGET '{value}' is outside ROOT '{root}'", code="path_outside_root")
    normalized = relative.as_posix()
    if not normalized or normalized == ".":
        raise CliInputError("TARGET must identify a file")
    return normalized


def _output_options(values: dict[str, Any]) -> OutputOptions:
    output_format = values.get("format", "json")
    if output_format not in {"json", "text"}:
        raise CliInputError("--format must be json or text")
    return OutputOptions(format=output_format, pretty=bool(values.get("pretty", False)))


def _parse_output_option(
    tokens: list[str], index: int, name: str, inline: str | None, values: dict[str, Any], seen: set[str]
) -> int:
    if name == "--pretty":
        _ensure_unique(seen, name)
        if inline is not None:
            raise CliInputError("--pretty does not take a value")
        values["pretty"] = True
        return index
    if name == "--format":
        _ensure_unique(seen, name)
        value, index = _option_value(tokens, index, name, inline)
        values["format"] = value
        return index
    raise CliInputError(f"unknown option {name}")


def _parse_execution_option(
    tokens: list[str], index: int, name: str, inline: str | None, values: dict[str, Any], seen: set[str]
) -> int:
    if name in {"--timeout-seconds", "--cache"}:
        _ensure_unique(seen, name)
        value, index = _option_value(tokens, index, name, inline)
        values[name[2:].replace("-", "_")] = _as_int(name, value) if name == "--timeout-seconds" else value
        return index
    raise CliInputError(f"unknown option {name}")


def _parse_collection_common_option(
    tokens: list[str],
    index: int,
    name: str,
    inline: str | None,
    values: dict[str, Any],
    seen: set[str],
) -> tuple[bool, int]:
    """Parse options shared by the bounded collection operations."""
    if name in {"--pretty", "--format"}:
        return True, _parse_output_option(tokens, index, name, inline, values, seen)
    if name in {"--timeout-seconds", "--cache"}:
        return True, _parse_execution_option(tokens, index, name, inline, values, seen)
    if name in {"--cursor", "--limit", "--max-bytes"}:
        _ensure_unique(seen, name)
        value, index = _option_value(tokens, index, name, inline)
        key = name[2:].replace("-", "_")
        values[key] = _as_int(name, value) if name != "--cursor" else value
        return True, index
    return False, index


def _append_option_value(
    tokens: list[str],
    index: int,
    name: str,
    inline: str | None,
    values: dict[str, Any],
    key: str,
) -> int:
    value, index = _option_value(tokens, index, name, inline)
    values.setdefault(key, []).append(value)
    return index


def _selection_from_values(values: dict[str, Any]) -> dict[str, Any] | None:
    selection: dict[str, Any] = {}
    for field in ("paths", "globs", "languages", "exclusions"):
        if field in values:
            selection[field] = values.pop(field)
    return selection or None


def _parse_json_reference(value: Any, option: str) -> dict[str, Any]:
    parsed = _parse_json(value.encode("utf-8"), option) if isinstance(value, str) else value
    if not isinstance(parsed, dict):
        raise CliInputError(f"{option} JSON must contain one symbol reference object")
    if parsed.get("kind") != "symbol":
        raise CliInputError(f"{option} JSON must contain one symbol reference object")
    return parsed


def _parse_map(argv: list[str]) -> ParsedCommand:
    if argv and argv[0] in {"--help", "-h"}:
        raise CliInputError("help", code="__help_map__")
    if not argv:
        raise CliInputError("map requires ROOT")
    root = normalize_shell_root(argv[0])
    tokens = argv[1:]
    positionals: list[str] = []
    values: dict[str, Any] = {}
    seen: set[str] = set()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in {"--help", "-h"}:
            raise CliInputError("help", code="__help_map__")
        if not token.startswith("-"):
            positionals.append(token)
            i += 1
            continue
        name, inline = _split_option(token)
        handled, i = _parse_collection_common_option(tokens, i, name, inline, values, seen)
        if handled:
            i += 1
            continue
        if name == "--focus":
            i = _append_option_value(tokens, i, name, inline, values, "focus")
        elif name in {"--depth", "--context", "--exclusions"}:
            _ensure_unique(seen, name)
            value, i = _option_value(tokens, i, name, inline)
            values[name[2:].replace("-", "_")] = _as_int(name, value) if name == "--depth" and value != "all" else value
        else:
            raise CliInputError(f"unknown option {name}")
        i += 1

    if positionals:
        raise CliInputError("map accepts ROOT followed by options only")
    query: dict[str, Any] = {}
    for field in ("focus", "depth", "context", "exclusions"):
        if field in values:
            query[field] = values.pop(field)
    request: dict[str, Any] = {"op": "map", "root": root, "query": query}
    page = {field: values.pop(field) for field in ("cursor", "limit", "max_bytes") if field in values}
    if page:
        request["page"] = page
    execution = {field: values.pop(field) for field in ("timeout_seconds", "cache") if field in values}
    if execution:
        request["execution"] = execution
    output = _output_options({"format": values.pop("format", "json"), "pretty": values.pop("pretty", False)})
    if values:
        raise CliInputError(f"unrecognized map arguments: {', '.join(sorted(values))}")
    return ParsedCommand(operation="map", request=request, output=output)


def _parse_find(argv: list[str]) -> ParsedCommand:
    if argv and argv[0] in {"--help", "-h"}:
        raise CliInputError("help", code="__help_find__")
    if not argv:
        raise CliInputError("find requires ROOT")
    root = normalize_shell_root(argv[0])
    tokens = argv[1:]
    positionals: list[str] = []
    values: dict[str, Any] = {}
    seen: set[str] = set()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in {"--help", "-h"}:
            raise CliInputError("help", code="__help_find__")
        if not token.startswith("-"):
            positionals.append(token)
            i += 1
            continue
        name, inline = _split_option(token)
        handled, i = _parse_collection_common_option(tokens, i, name, inline, values, seen)
        if handled:
            i += 1
            continue
        if name in {"--path", "--glob", "--language", "--kinds", "--visibility"}:
            key = {"--path": "paths", "--glob": "globs", "--language": "languages"}.get(name, name[2:])
            i = _append_option_value(tokens, i, name, inline, values, key)
        elif name in {"--match", "--exclusions"}:
            _ensure_unique(seen, name)
            value, i = _option_value(tokens, i, name, inline)
            values[name[2:].replace("-", "_")] = value
        else:
            raise CliInputError(f"unknown option {name}")
        i += 1

    if len(positionals) != 1:
        raise CliInputError("find requires exactly one QUERY")
    query: dict[str, Any] = {"text": positionals[0]}
    selection = _selection_from_values(values)
    if selection is not None:
        query["selection"] = selection
    for field in ("match", "kinds", "visibility"):
        if field in values:
            query[field] = values.pop(field)
    request: dict[str, Any] = {"op": "find", "root": root, "query": query}
    page = {field: values.pop(field) for field in ("cursor", "limit", "max_bytes") if field in values}
    if page:
        request["page"] = page
    execution = {field: values.pop(field) for field in ("timeout_seconds", "cache") if field in values}
    if execution:
        request["execution"] = execution
    output = _output_options({"format": values.pop("format", "json"), "pretty": values.pop("pretty", False)})
    if values:
        raise CliInputError(f"unrecognized find arguments: {', '.join(sorted(values))}")
    return ParsedCommand(operation="find", request=request, output=output)


def _parse_interface(argv: list[str]) -> ParsedCommand:
    if argv and argv[0] in {"--help", "-h"}:
        raise CliInputError("help", code="__help_interface__")
    if not argv:
        raise CliInputError("interface requires ROOT")
    root = normalize_shell_root(argv[0])
    tokens = argv[1:]
    positionals: list[str] = []
    values: dict[str, Any] = {}
    seen: set[str] = set()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in {"--help", "-h"}:
            raise CliInputError("help", code="__help_interface__")
        if not token.startswith("-"):
            positionals.append(token)
            i += 1
            continue
        name, inline = _split_option(token)
        handled, i = _parse_collection_common_option(tokens, i, name, inline, values, seen)
        if handled:
            i += 1
            continue
        if name in {"--ref-json", "--ref-file"}:
            _ensure_unique(seen, name)
            value, i = _option_value(tokens, i, name, inline)
            values[name[2:].replace("-", "_")] = value
        elif name in {"--sections", "--kinds", "--visibility"}:
            i = _append_option_value(tokens, i, name, inline, values, name[2:])
        elif name == "--member-depth":
            _ensure_unique(seen, name)
            value, i = _option_value(tokens, i, name, inline)
            values["member_depth"] = _as_int(name, value)
        elif name == "--documentation":
            _ensure_unique(seen, name)
            if inline is not None:
                raise CliInputError(f"{name} does not take a value")
            values["documentation"] = True
        else:
            raise CliInputError(f"unknown option {name}")
        i += 1

    target_forms = [name for name in ("ref_json", "ref_file") if name in values]
    if positionals and target_forms:
        raise CliInputError("FILE cannot be combined with --ref-json or --ref-file")
    if len(positionals) > 1:
        raise CliInputError("interface accepts exactly one FILE")
    if len(target_forms) > 1:
        raise CliInputError("interface accepts exactly one JSON reference form")
    if not positionals and not target_forms:
        raise CliInputError("interface requires FILE, --ref-json, or --ref-file")

    if positionals:
        query: dict[str, Any] = {"target": {"kind": "file", "path": _normalize_location_path(positionals[0], root)}}
    else:
        form = target_forms[0]
        source = values.pop(form)
        parsed = (
            _parse_json_reference(source, "--ref-json")
            if form == "ref_json"
            else _parse_json_reference(_read_json_source(source), "--ref-file")
        )
        query = {"target": parsed}
    for field in ("sections", "member_depth", "documentation", "kinds", "visibility"):
        if field in values:
            query[field] = values.pop(field)

    request: dict[str, Any] = {"op": "interface", "root": root, "query": query}
    page = {field: values.pop(field) for field in ("cursor", "limit", "max_bytes") if field in values}
    if page:
        request["page"] = page
    execution = {field: values.pop(field) for field in ("timeout_seconds", "cache") if field in values}
    if execution:
        request["execution"] = execution
    output = _output_options({"format": values.pop("format", "json"), "pretty": values.pop("pretty", False)})
    if values:
        raise CliInputError(f"unrecognized interface arguments: {', '.join(sorted(values))}")
    return ParsedCommand(operation="interface", request=request, output=output)


def _parse_read(argv: list[str]) -> ParsedCommand:
    if argv and argv[0] in {"--help", "-h"}:
        raise CliInputError("help", code="__help_read__")
    if not argv:
        raise CliInputError("read requires ROOT")
    root = normalize_shell_root(argv[0])
    tokens = argv[1:]

    positionals: list[str] = []
    values: dict[str, Any] = {}
    seen: set[str] = set()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in {"--help", "-h"}:
            raise CliInputError("help", code="__help_read__")
        if not token.startswith("-"):
            positionals.append(token)
            i += 1
            continue
        name, inline = _split_option(token)
        if name in {"--pretty", "--format"}:
            i = _parse_output_option(tokens, i, name, inline, values, seen)
        elif name in {"--timeout-seconds", "--cache"}:
            i = _parse_execution_option(tokens, i, name, inline, values, seen)
        elif name in {"--ref-json", "--ref-file", "--targets-file"}:
            _ensure_unique(seen, name)
            value, i = _option_value(tokens, i, name, inline)
            values[name[2:].replace("-", "_")] = value
        elif name in {
            "--line",
            "--end-line",
            "--column",
            "--context-lines",
            "--max-bytes",
            "--max-lines",
            "--source-bytes",
        }:
            _ensure_unique(seen, name)
            value, i = _option_value(tokens, i, name, inline)
            values[name[2:].replace("-", "_")] = _as_int(name, value)
        elif name == "--cursor":
            _ensure_unique(seen, name)
            value, i = _option_value(tokens, i, name, inline)
            values["cursor"] = value
        elif name in {"--include-enclosing", "--no-enclosing"}:
            _ensure_unique(seen, name)
            if inline is not None:
                raise CliInputError(f"{name} does not take a value")
            values["include_enclosing"] = name == "--include-enclosing"
        else:
            raise CliInputError(f"unknown option {name}")
        i += 1

    target_forms = [name for name in ("ref_json", "ref_file", "targets_file") if name in values]
    if positionals and target_forms:
        raise CliInputError("TARGET cannot be combined with --ref-json, --ref-file, or --targets-file")
    if len(target_forms) > 1:
        raise CliInputError("read accepts exactly one JSON target-input form")

    if positionals:
        if len(positionals) != 1:
            raise CliInputError("read accepts exactly one natural TARGET")
        if "line" not in values:
            raise CliInputError("natural TARGET requires --line")
        if "ref_json" in values or "ref_file" in values or "targets_file" in values:
            raise CliInputError("natural TARGET cannot be combined with a JSON target-input form")
        location: dict[str, Any] = {
            "kind": "location",
            "path": _normalize_location_path(positionals[0], root),
            "line": values.pop("line"),
        }
        for field in ("end_line", "column"):
            if field in values:
                location[field] = values.pop(field)
        targets: Any = [location]
    elif target_forms:
        if any(field in values for field in ("line", "end_line", "column")):
            raise CliInputError("line options apply only to a natural TARGET")
        form = target_forms[0]
        source_value = values.pop(form)
        parsed = (
            _parse_json(source_value.encode("utf-8"), "--ref-json")
            if form == "ref_json"
            else _read_json_source(source_value)
        )
        if form == "targets_file":
            if not isinstance(parsed, list):
                raise CliInputError("--targets-file JSON must contain an array of targets")
            targets = parsed
        else:
            if not isinstance(parsed, dict):
                raise CliInputError(f"--{form.replace('_', '-')} JSON must contain one target object")
            targets = [parsed]
    else:
        raise CliInputError("read requires TARGET, --ref-json, --ref-file, or --targets-file")
    if not isinstance(targets, list) or not 1 <= len(targets) <= MAX_READ_TARGETS:
        raise CliInputError("read accepts one to eight targets")

    query: dict[str, Any] = {"targets": targets}
    for field in ("context_lines", "include_enclosing"):
        if field in values:
            query[field] = values.pop(field)

    page_fields = ("cursor", "max_bytes", "max_lines", "source_bytes")
    page = {field: values.pop(field) for field in page_fields if field in values}
    execution: dict[str, Any] = {}
    for field in ("timeout_seconds", "cache"):
        if field in values:
            execution[field] = values.pop(field)
    output = _output_options({"format": values.pop("format", "json"), "pretty": values.pop("pretty", False)})
    if values:
        raise CliInputError(f"unrecognized read arguments: {', '.join(sorted(values))}")

    request: dict[str, Any] = {"op": "read", "root": root, "query": query}
    if page:
        request["page"] = page
    if execution:
        request["execution"] = execution
    return ParsedCommand(operation="read", request=request, output=output)


def _parse_capabilities(argv: list[str]) -> ParsedCommand:
    if argv and argv[0] in {"--help", "-h"}:
        raise CliInputError("help", code="__help_capabilities__")
    positionals: list[str] = []
    values: dict[str, Any] = {}
    seen: set[str] = set()
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in {"--help", "-h"}:
            raise CliInputError("help", code="__help_capabilities__")
        if not token.startswith("-"):
            positionals.append(token)
            i += 1
            continue
        name, inline = _split_option(token)
        if name in {"--pretty", "--format"}:
            i = _parse_output_option(argv, i, name, inline, values, seen)
        elif name in {"--timeout-seconds", "--cache"}:
            i = _parse_execution_option(argv, i, name, inline, values, seen)
        elif name == "--detail":
            _ensure_unique(seen, name)
            if inline is None and (i + 1 >= len(argv) or argv[i + 1].startswith("-")):
                values["detail"] = "detail"
            else:
                value, i = _option_value(argv, i, name, inline)
                values["detail"] = value

        else:
            raise CliInputError(f"unknown option {name}")
        i += 1
    if len(positionals) > 1:
        raise CliInputError("capabilities accepts at most one ROOT")

    request: dict[str, Any] = {
        "op": "capabilities",
        "query": {"detail": values.pop("detail", "summary")},
    }
    if positionals:
        request["root"] = normalize_shell_root(positionals[0])
    execution: dict[str, Any] = {}
    for field in ("timeout_seconds", "cache"):
        if field in values:
            execution[field] = values.pop(field)
    output = _output_options({"format": values.pop("format", "json"), "pretty": values.pop("pretty", False)})
    if values:
        raise CliInputError(f"unrecognized capabilities arguments: {', '.join(sorted(values))}")
    if execution:
        request["execution"] = execution
    return ParsedCommand(operation="capabilities", request=request, output=output)


def _parse_search(argv: list[str]) -> ParsedCommand:
    if argv and argv[0] in {"--help", "-h"}:
        raise CliInputError("help", code="__help_search__")
    if not argv:
        raise CliInputError("search requires ROOT")
    root = normalize_shell_root(argv[0])
    tokens = argv[1:]
    positionals: list[str] = []
    values: dict[str, Any] = {}
    seen: set[str] = set()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in {"--help", "-h"}:
            raise CliInputError("help", code="__help_search__")
        if not token.startswith("-"):
            positionals.append(token)
            i += 1
            continue
        name, inline = _split_option(token)
        handled, i = _parse_collection_common_option(tokens, i, name, inline, values, seen)
        if handled:
            i += 1
            continue
        if name in {"--literal", "--pattern", "--rule", "--config"}:
            _ensure_unique(seen, name)
            value, i = _option_value(tokens, i, name, inline)
            values[name[2:]] = value
        elif name == "--lang":
            _ensure_unique(seen, name)
            value, i = _option_value(tokens, i, name, inline)
            values["lang"] = value
        elif name in {"--path", "--glob", "--language"}:
            key = {"--path": "paths", "--glob": "globs", "--language": "languages"}[name]
            i = _append_option_value(tokens, i, name, inline, values, key)
        elif name == "--exclusions":
            _ensure_unique(seen, name)
            value, i = _option_value(tokens, i, name, inline)
            values["exclusions"] = value
        elif name == "--detail":
            _ensure_unique(seen, name)
            if inline is None and (i + 1 >= len(tokens) or tokens[i + 1].startswith("-")):
                values["detail"] = "detail"
            else:
                value, i = _option_value(tokens, i, name, inline)
                values["detail"] = value
        else:
            raise CliInputError(f"unknown option {name}")
        i += 1

    if positionals:
        raise CliInputError("search accepts ROOT followed by options only")
    source_forms = [name for name in ("literal", "pattern", "rule", "config") if name in values]
    if len(source_forms) != 1:
        raise CliInputError("search requires exactly one of --literal, --pattern, --rule, or --config")
    source_name = source_forms[0]
    if source_name == "literal":
        if "lang" in values:
            raise CliInputError("--lang applies only to --pattern")
        source: dict[str, Any] = {"kind": "literal", "text": values.pop("literal")}
    elif source_name == "pattern":
        if "lang" not in values:
            raise CliInputError("--pattern requires --lang")
        source = {
            "kind": "pattern",
            "pattern": values.pop("pattern"),
            "language": values.pop("lang"),
        }
    else:
        if "lang" in values:
            raise CliInputError("--lang applies only to --pattern")
        source = {
            "kind": "rule",
            "input": {
                "kind": "rule" if source_name == "rule" else "config",
                "path": _normalize_location_path(values.pop(source_name), root),
            },
        }

    query: dict[str, Any] = {"source": source}
    selection = _selection_from_values(values)
    if selection is not None:
        query["selection"] = selection
    if "detail" in values:
        query["detail"] = values.pop("detail")

    request: dict[str, Any] = {"op": "search", "root": root, "query": query}
    page = {field: values.pop(field) for field in ("cursor", "limit", "max_bytes") if field in values}
    if page:
        request["page"] = page
    execution = {field: values.pop(field) for field in ("timeout_seconds", "cache") if field in values}
    if execution:
        request["execution"] = execution
    output = _output_options({"format": values.pop("format", "json"), "pretty": values.pop("pretty", False)})
    if values:
        raise CliInputError(f"unrecognized search arguments: {', '.join(sorted(values))}")
    return ParsedCommand(operation="search", request=request, output=output)


def _parse_impact(argv: list[str]) -> ParsedCommand:
    if argv and argv[0] in {"--help", "-h"}:
        raise CliInputError("help", code="__help_impact__")
    if not argv:
        raise CliInputError("impact requires ROOT")
    root = normalize_shell_root(argv[0])
    tokens = argv[1:]
    positionals: list[str] = []
    values: dict[str, Any] = {}
    seen: set[str] = set()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in {"--help", "-h"}:
            raise CliInputError("help", code="__help_impact__")
        if not token.startswith("-"):
            positionals.append(token)
            i += 1
            continue
        name, inline = _split_option(token)
        handled, i = _parse_collection_common_option(tokens, i, name, inline, values, seen)
        if handled:
            i += 1
            continue
        if name in {"--ref-json", "--ref-file"}:
            _ensure_unique(seen, name)
            value, i = _option_value(tokens, i, name, inline)
            values[name[2:].replace("-", "_")] = value
        elif name in {"--path", "--glob", "--language"}:
            key = {"--path": "paths", "--glob": "globs", "--language": "languages"}[name]
            i = _append_option_value(tokens, i, name, inline, values, key)
        elif name == "--exclusions":
            _ensure_unique(seen, name)
            value, i = _option_value(tokens, i, name, inline)
            values["exclusions"] = value
        elif name == "--mode":
            _ensure_unique(seen, name)
            value, i = _option_value(tokens, i, name, inline)
            values["mode"] = value
        else:
            raise CliInputError(f"unknown option {name}")
        i += 1

    if positionals:
        raise CliInputError("impact accepts ROOT followed by options only")
    target_forms = [name for name in ("ref_json", "ref_file") if name in values]
    if len(target_forms) != 1:
        raise CliInputError("impact requires exactly one of --ref-json or --ref-file")
    form = target_forms[0]
    source = values.pop(form)
    target = (
        _parse_json_reference(source, "--ref-json")
        if form == "ref_json"
        else _parse_json_reference(_read_json_source(source), "--ref-file")
    )

    query: dict[str, Any] = {"target": target}
    selection = _selection_from_values(values)
    if selection is not None:
        query["selection"] = selection
    if "mode" in values:
        query["mode"] = values.pop("mode")

    request: dict[str, Any] = {"op": "impact", "root": root, "query": query}
    page = {field: values.pop(field) for field in ("cursor", "limit", "max_bytes") if field in values}
    if page:
        request["page"] = page
    execution = {field: values.pop(field) for field in ("timeout_seconds", "cache") if field in values}
    if execution:
        request["execution"] = execution
    output = _output_options({"format": values.pop("format", "json"), "pretty": values.pop("pretty", False)})
    if values:
        raise CliInputError(f"unrecognized impact arguments: {', '.join(sorted(values))}")
    return ParsedCommand(operation="impact", request=request, output=output)


def _read_change_plan(value: str) -> dict[str, Any]:
    """Read one complete ``xray.change.v1`` plan from a file or stdin.

    The plan artifact is intentionally passed through to ``execute`` for the
    authoritative closed-model and digest checks.  A current CLI plan response
    is accepted as a transport convenience, but no legacy plan envelope or
    field reconstruction is performed.
    """
    parsed = _read_json_source(value)
    if not isinstance(parsed, dict):
        raise CliInputError("--plan-file JSON must contain one complete plan object")
    if "plan_schema" in parsed:
        return parsed
    data = parsed.get("data")
    if (
        parsed.get("schema") == "xray.v1"
        and parsed.get("ok") is True
        and parsed.get("op") in {"change_plan", "change_refine"}
        and isinstance(data, dict)
        and isinstance(data.get("plan"), dict)
    ):
        return data["plan"]
    return parsed


def _parse_change_plan(argv: list[str]) -> ParsedCommand:
    if argv and argv[0] in {"--help", "-h"}:
        raise CliInputError("help", code="__help_change_plan__")
    if not argv:
        raise CliInputError("change plan requires ROOT")
    root = normalize_shell_root(argv[0])
    tokens = argv[1:]
    positionals: list[str] = []
    values: dict[str, Any] = {}
    seen: set[str] = set()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in {"--help", "-h"}:
            raise CliInputError("help", code="__help_change_plan__")
        if not token.startswith("-"):
            positionals.append(token)
            i += 1
            continue
        name, inline = _split_option(token)
        if name in {"--pretty", "--format"}:
            i = _parse_output_option(tokens, i, name, inline, values, seen)
        elif name in {"--timeout-seconds", "--cache"}:
            i = _parse_execution_option(tokens, i, name, inline, values, seen)
        elif name in {"--pattern", "--replacement", "--lang", "--rule", "--config"}:
            _ensure_unique(seen, name)
            value, i = _option_value(tokens, i, name, inline)
            values[name[2:]] = value
        elif name in {"--path", "--glob", "--language"}:
            key = {"--path": "paths", "--glob": "globs", "--language": "languages"}[name]
            i = _append_option_value(tokens, i, name, inline, values, key)
        elif name == "--exclusions":
            _ensure_unique(seen, name)
            value, i = _option_value(tokens, i, name, inline)
            values["exclusions"] = value
        elif name in {"--max-candidates", "--max-files", "--max-bytes"}:
            _ensure_unique(seen, name)
            value, i = _option_value(tokens, i, name, inline)
            values[name[2:].replace("-", "_")] = _as_int(name, value)
        elif name in {"--allow-dirty-affected", "--allow-new-parse-errors"}:
            _ensure_unique(seen, name)
            if inline is not None:
                raise CliInputError(f"{name} does not take a value")
            values[name[2:].replace("-", "_")] = True
        else:
            raise CliInputError(f"unknown option {name}")
        i += 1

    if positionals:
        raise CliInputError("change plan accepts ROOT followed by options only")

    source_forms = [name for name in ("pattern", "rule", "config") if name in values]
    if len(source_forms) != 1:
        raise CliInputError("change plan requires exactly one of --pattern, --rule, or --config")
    source_name = source_forms[0]
    if source_name == "pattern":
        if "replacement" not in values:
            raise CliInputError("--pattern requires --replacement")
        if "lang" not in values:
            raise CliInputError("--pattern requires --lang")
        source: dict[str, Any] = {
            "kind": "pattern",
            "pattern": values.pop("pattern"),
            "replacement": values.pop("replacement"),
            "language": values.pop("lang"),
        }
    else:
        if "replacement" in values or "lang" in values:
            raise CliInputError("--replacement and --lang apply only to --pattern")
        source = {
            "kind": "rule",
            "input": {
                "kind": source_name,
                "path": _normalize_location_path(values.pop(source_name), root),
            },
        }

    query: dict[str, Any] = {"source": source}
    selection = _selection_from_values(values)
    if selection is not None:
        query["selection"] = selection
    bounds = {field: values.pop(field) for field in ("max_candidates", "max_files", "max_bytes") if field in values}
    if bounds:
        query["bounds"] = bounds
    acknowledgements: dict[str, Any] = {}
    if values.pop("allow_dirty_affected", False):
        acknowledgements["dirty_affected"] = True
    if values.pop("allow_new_parse_errors", False):
        acknowledgements["new_parse_errors"] = True
    if acknowledgements:
        query["acknowledgements"] = acknowledgements

    execution = {field: values.pop(field) for field in ("timeout_seconds", "cache") if field in values}
    output = _output_options({"format": values.pop("format", "json"), "pretty": values.pop("pretty", False)})
    if values:
        raise CliInputError(f"unrecognized change plan arguments: {', '.join(sorted(values))}")
    request: dict[str, Any] = {"op": "change_plan", "root": root, "query": query}
    if execution:
        request["execution"] = execution
    return ParsedCommand(operation="change_plan", request=request, output=output)


def _parse_change_refine(argv: list[str]) -> ParsedCommand:
    if argv and argv[0] in {"--help", "-h"}:
        raise CliInputError("help", code="__help_change_refine__")
    if not argv:
        raise CliInputError("change refine requires ROOT")
    root = normalize_shell_root(argv[0])
    tokens = argv[1:]
    positionals: list[str] = []
    values: dict[str, Any] = {}
    seen: set[str] = set()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in {"--help", "-h"}:
            raise CliInputError("help", code="__help_change_refine__")
        if not token.startswith("-"):
            positionals.append(token)
            i += 1
            continue
        name, inline = _split_option(token)
        if name in {"--pretty", "--format"}:
            i = _parse_output_option(tokens, i, name, inline, values, seen)
        elif name in {"--timeout-seconds", "--cache"}:
            i = _parse_execution_option(tokens, i, name, inline, values, seen)
        elif name == "--plan-file":
            _ensure_unique(seen, name)
            values["plan_file"], i = _option_value(tokens, i, name, inline)
        elif name == "--edit-id":
            i = _append_option_value(tokens, i, name, inline, values, "edit_ids")
        else:
            raise CliInputError(f"unknown option {name}")
        i += 1

    if positionals:
        raise CliInputError("change refine accepts ROOT followed by options only")
    if "plan_file" not in values:
        raise CliInputError("change refine requires --plan-file")
    plan = _read_change_plan(values.pop("plan_file"))
    edit_ids = values.pop("edit_ids", [])
    if len(set(edit_ids)) != len(edit_ids):
        raise CliInputError("--edit-id values must be unique")
    edit_ids = sorted(edit_ids, key=lambda item: item.encode("utf-8"))
    query: dict[str, Any] = {"plan": plan, "edit_ids": edit_ids}
    execution = {field: values.pop(field) for field in ("timeout_seconds", "cache") if field in values}
    output = _output_options({"format": values.pop("format", "json"), "pretty": values.pop("pretty", False)})
    if values:
        raise CliInputError(f"unrecognized change refine arguments: {', '.join(sorted(values))}")
    request: dict[str, Any] = {"op": "change_refine", "root": root, "query": query}
    if execution:
        request["execution"] = execution
    return ParsedCommand(operation="change_refine", request=request, output=output)


def _parse_change_review(argv: list[str], operation: str) -> ParsedCommand:
    help_code = f"__help_{operation}__"
    if argv and argv[0] in {"--help", "-h"}:
        raise CliInputError("help", code=help_code)
    if not argv:
        raise CliInputError(f"{operation.removeprefix('change_')} requires ROOT")
    root = normalize_shell_root(argv[0])
    tokens = argv[1:]
    positionals: list[str] = []
    values: dict[str, Any] = {}
    seen: set[str] = set()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in {"--help", "-h"}:
            raise CliInputError("help", code=help_code)
        if not token.startswith("-"):
            positionals.append(token)
            i += 1
            continue
        name, inline = _split_option(token)
        if name in {"--pretty", "--format"}:
            i = _parse_output_option(tokens, i, name, inline, values, seen)
        elif name in {"--timeout-seconds", "--cache"}:
            i = _parse_execution_option(tokens, i, name, inline, values, seen)
        elif name == "--plan-file":
            _ensure_unique(seen, name)
            values["plan_file"], i = _option_value(tokens, i, name, inline)
        elif name == "--expected-digest":
            _ensure_unique(seen, name)
            values["expected_digest"], i = _option_value(tokens, i, name, inline)
        else:
            raise CliInputError(f"unknown option {name}")
        i += 1

    leaf = operation.removeprefix("change_")
    if positionals:
        raise CliInputError(f"change {leaf} accepts ROOT followed by options only")
    if "plan_file" not in values:
        raise CliInputError(f"change {leaf} requires --plan-file")
    if "expected_digest" not in values:
        raise CliInputError(f"change {leaf} requires --expected-digest")
    plan = _read_change_plan(values.pop("plan_file"))
    expected_digest = values.pop("expected_digest")
    query: dict[str, Any] = {"plan": plan, "expected_digest": expected_digest}
    execution = {field: values.pop(field) for field in ("timeout_seconds", "cache") if field in values}
    output = _output_options({"format": values.pop("format", "json"), "pretty": values.pop("pretty", False)})
    if values:
        raise CliInputError(f"unrecognized change {leaf} arguments: {', '.join(sorted(values))}")
    request: dict[str, Any] = {"op": operation, "root": root, "query": query}
    if execution:
        request["execution"] = execution
    return ParsedCommand(operation=operation, request=request, output=output)


def _parse_change(argv: list[str]) -> ParsedCommand:
    if not argv or argv[0] in {"--help", "-h"}:
        raise CliInputError("help", code="__help_change__")
    command = argv[0]
    if command == "plan":
        return _parse_change_plan(argv[1:])
    if command == "refine":
        return _parse_change_refine(argv[1:])
    if command == "verify":
        return _parse_change_review(argv[1:], "change_verify")
    if command == "apply":
        return _parse_change_review(argv[1:], "change_apply")
    raise CliInputError(f"unknown change command {command!r}", code="unknown_operation")


def _parse_skill(argv: list[str]) -> ParsedCommand:
    if not argv or argv[0] in {"--help", "-h"}:
        raise CliInputError("help", code="__help_skill__")
    if argv[0] != "install":
        raise CliInputError(f"unknown skill command {argv[0]!r}")
    values: dict[str, Any] = {}
    seen: set[str] = set()
    i = 1
    while i < len(argv):
        token = argv[i]
        if token in {"--help", "-h"}:
            raise CliInputError("help", code="__help_skill__")
        if not token.startswith("-"):
            raise CliInputError(f"unexpected skill argument {token!r}")
        name, inline = _split_option(token)
        if name in {"--user", "--force", "--pretty"}:
            _ensure_unique(seen, name)
            if inline is not None:
                raise CliInputError(f"{name} does not take a value")
            values[name[2:].replace("-", "_")] = True
        elif name == "--project":
            _ensure_unique(seen, name)
            values["project"], i = _option_value(argv, i, name, inline)

        else:
            raise CliInputError(f"unknown option {name}")
        i += 1
    if values.get("user") and "project" in values:
        raise CliInputError("--user and --project are mutually exclusive")
    return ParsedCommand(
        operation="skill_install",
        output=OutputOptions(pretty=bool(values.get("pretty", False))),
        admin=True,
        project_root=values.get("project"),
        force=bool(values.get("force", False)),
    )


def _parse_command(argv: list[str]) -> ParsedCommand:
    if not argv:
        raise CliInputError("a command is required")
    command = argv[0]
    if command not in CLI_COMMANDS:
        if command in {"--help", "-h"}:
            raise CliInputError("help", code="__help_root__")
        raise CliInputError(f"unknown command {command!r}", code="unknown_operation")
    if command == "map":
        return _parse_map(argv[1:])
    if command == "find":
        return _parse_find(argv[1:])
    if command == "interface":
        return _parse_interface(argv[1:])
    if command == "read":
        return _parse_read(argv[1:])
    if command == "impact":
        return _parse_impact(argv[1:])
    if command == "search":
        return _parse_search(argv[1:])
    if command == "change":
        return _parse_change(argv[1:])
    if command == "capabilities":
        return _parse_capabilities(argv[1:])
    return _parse_skill(argv[1:])


def _scan_output_options(argv: list[str]) -> OutputOptions:
    output_format = "json"
    pretty = False
    for index, token in enumerate(argv):
        if token == "--pretty":
            pretty = True
        elif token.startswith("--format="):
            candidate = token.split("=", 1)[1]
            if candidate in {"json", "text"}:
                output_format = candidate
        elif token == "--format" and index + 1 < len(argv):
            candidate = argv[index + 1]
            if candidate in {"json", "text"}:
                output_format = candidate
    return OutputOptions(format=output_format, pretty=pretty)


def _render_read_text(payload: dict[str, Any]) -> str:
    data = payload.get("data", {})
    items = data.get("items", []) if isinstance(data, dict) else []
    rendered: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ref = item.get("ref", {})
        location = item.get("location", {})
        start = location.get("start", {}) if isinstance(location, dict) else {}
        end = location.get("end", {}) if isinstance(location, dict) else {}
        path = ref.get("path", "") if isinstance(ref, dict) else ""
        start_line = start.get("line", "") if isinstance(start, dict) else ""
        end_line = end.get("line", "") if isinstance(end, dict) else ""
        rendered.append(f"{path}:{start_line}-{end_line}")
        source = item.get("source", "")
        rendered.append(str(source).rstrip("\n"))
    return "\n".join(rendered)


def _ref_location(ref: Any, location: Any = None) -> str:
    if not isinstance(ref, dict):
        return ""
    path = str(ref.get("path", ""))
    if isinstance(location, dict):
        start = location.get("start", {})
        end = location.get("end", {})
        if isinstance(start, dict) and isinstance(end, dict):
            return f"{path}:{start.get('line', '')}-{end.get('line', '')}"
    return f"{path}:{ref.get('start', '')}-{ref.get('end', '')}"


def _render_map_text(payload: dict[str, Any]) -> str:
    data = payload.get("data", {})
    items = data.get("items", []) if isinstance(data, dict) else []
    rendered: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        fields = [str(item.get("path", "")), str(item.get("kind", ""))]
        if item.get("language") is not None:
            fields.append(str(item["language"]))
        if item.get("frontier") is True:
            fields.append("frontier")
        rendered.append("\t".join(fields))
    return "\n".join(rendered)


def _render_find_text(payload: dict[str, Any]) -> str:
    data = payload.get("data", {})
    items = data.get("items", []) if isinstance(data, dict) else []
    rendered: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rendered.append(
            "\t".join(
                [
                    str(item.get("name", "")),
                    str(item.get("kind", "")),
                    str(item.get("qualified_name", "")),
                    _ref_location(item.get("ref"), item.get("location")),
                ]
            )
        )
    return "\n".join(rendered)


def _render_search_text(payload: dict[str, Any]) -> str:
    data = payload.get("data", {})
    items = data.get("items", []) if isinstance(data, dict) else []
    rendered: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rendered.append("\t".join([_ref_location(item.get("ref"), item.get("location")), str(item.get("text", ""))]))
    return "\n".join(rendered)


def _render_impact_text(payload: dict[str, Any]) -> str:
    data = payload.get("data", {})
    items = data.get("items", []) if isinstance(data, dict) else []
    rendered: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rendered.append(
            "\t".join(
                [
                    _ref_location(item.get("ref"), item.get("location")),
                    str(item.get("kind", "")),
                    str(item.get("evidence", "")),
                    str(item.get("text", "")),
                ]
            )
        )
    return "\n".join(rendered)


def _render_change_text(payload: dict[str, Any]) -> str:
    operation = payload.get("op", "")
    data = payload.get("data", {})
    if operation in {"change_plan", "change_refine"}:
        plan = data.get("plan", {}) if isinstance(data, dict) else {}
        if not isinstance(plan, dict):
            return ""
        eligibility = plan.get("eligibility", {})
        digest = plan.get("plan_digest", "")
        applicable = eligibility.get("applicable", False) if isinstance(eligibility, dict) else False
        lines = [f"plan_digest\t{digest}", f"applicable\t{str(applicable).lower()}"]
        files = plan.get("files", [])
        if isinstance(files, list):
            for item in files:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    "\t".join(
                        [
                            "file",
                            str(item.get("path", "")),
                            str(item.get("preimage_sha256", "")),
                            str(item.get("postimage_sha256", "")),
                        ]
                    )
                )
                diff = item.get("diff")
                if isinstance(diff, str) and diff:
                    lines.extend(diff.rstrip("\n").splitlines())
        return "\n".join(lines)
    if not isinstance(data, dict):
        return ""
    if operation == "change_verify":
        return f"plan_digest\t{data.get('plan_digest', '')}\tready"
    if operation == "change_apply":
        return "\t".join(
            [
                "plan_digest",
                str(data.get("plan_digest", "")),
                str(data.get("state", "")),
                str(data.get("rollback_status", "")),
            ]
        )
    return ""


def _render_interface_text(payload: dict[str, Any]) -> str:
    data = payload.get("data", {})
    items = data.get("items", []) if isinstance(data, dict) else []
    rendered: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        section = str(item.get("section", ""))
        location = _ref_location(item.get("ref"))
        if section == "symbols":
            rendered.append(
                "\t".join(
                    [
                        section,
                        str(item.get("name", "")),
                        str(item.get("kind", "")),
                        str(item.get("qualified_name", "")),
                        location,
                        str(item.get("signature", "")),
                    ]
                )
            )
        elif section == "imports":
            rendered.append(
                "\t".join(
                    [
                        section,
                        str(item.get("module_text", "")),
                        str(item.get("imported_name") or ""),
                        str(item.get("local_name") or ""),
                        location,
                    ]
                )
            )
        elif section == "exports":
            rendered.append(
                "\t".join(
                    [
                        section,
                        str(item.get("name") or ""),
                        str(item.get("module_text") or ""),
                        str(item.get("kind", "")),
                        location,
                    ]
                )
            )
    return "\n".join(rendered)


def _render_capabilities_text(payload: dict[str, Any]) -> str:
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return ""
    lines = [f"version: {data.get('version', '')}", f"healthy: {str(data.get('healthy', False)).lower()}"]
    languages = data.get("languages")
    if isinstance(languages, list):
        lines.append(f"languages: {', '.join(str(item) for item in languages)}")
    dependencies = data.get("dependencies")
    if isinstance(dependencies, list):
        lines.append("dependencies:")
        for dependency in dependencies:
            if isinstance(dependency, dict):
                lines.append(f"  {dependency.get('name', '')}: {dependency.get('state', '')}")
    operations = data.get("operations")
    if isinstance(operations, list):
        lines.append("operations:")
        for operation in operations:
            if isinstance(operation, dict):
                lines.append(f"  {operation.get('name', '')}: {operation.get('mutation', '')}")
    return "\n".join(lines)


def _write_json(payload: dict[str, Any], *, pretty: bool, stream: Any = None) -> None:
    if stream is None:
        stream = sys.stdout
    if pretty:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    else:
        text = canonical_json(payload)
    print(text, file=stream)


def _cli_budget_error(payload: dict[str, Any], minimum_bytes: int, *, include_context: bool = True) -> Error:
    operation = payload.get("op")
    values: dict[str, Any] = {
        "schema": "xray.v1",
        "ok": False,
        "error": {
            "code": "budget_too_small",
            "message": "budget_too_small: CLI output exceeds the operation hard byte ceiling",
            "details": {"minimum_bytes": max(_CLI_ERROR_RESPONSE_BYTES, minimum_bytes)},
        },
    }
    if operation in _CLI_HARD_RESPONSE_BYTES:
        values["op"] = operation
        if include_context:
            for field in ("root", "provenance"):
                if isinstance(payload.get(field), dict):
                    values[field] = payload[field]
        if operation == "change_apply":
            mutation = payload.get("mutation")
            if isinstance(mutation, dict) and mutation.get("state") != "applied":
                values["mutation"] = mutation
            else:
                values["mutation"] = {"state": "not_applied", "rollback_status": "not_attempted"}
    return Error.model_validate(values)


def _json_output_bytes(payload: dict[str, Any], *, pretty: bool) -> bytes:
    if pretty:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    else:
        text = canonical_json(payload)
    return text.encode("utf-8")


def _text_output(payload: dict[str, Any]) -> str:
    if payload.get("op") == "map":
        return _render_map_text(payload)
    if payload.get("op") == "find":
        return _render_find_text(payload)
    if payload.get("op") == "interface":
        return _render_interface_text(payload)
    if payload.get("op") == "read":
        return _render_read_text(payload)
    if payload.get("op") == "impact":
        return _render_impact_text(payload)
    if payload.get("op") == "search":
        return _render_search_text(payload)
    if payload.get("op") in {"change_plan", "change_refine", "change_verify", "change_apply"}:
        return _render_change_text(payload)
    if payload.get("op") == "capabilities":
        return _render_capabilities_text(payload)
    return ""


def _error_exit_code(code: str, *, parse: bool = False) -> int:
    if parse and code == "path_outside_root":
        return 2
    invalid = {
        "invalid_request",
        "unknown_operation",
        "invalid_pattern",
        "invalid_rule",
        "invalid_encoding",
        "invalid_reference",
        "invalid_cursor",
        "cursor_query_mismatch",
        "invalid_plan",
        "unsupported_file",
        "unsupported_configuration",
    }
    return 2 if code in invalid else 1


def _write_result(result: Result, output: OutputOptions) -> int:
    payload = result.to_payload()
    if output.format == "text" and result.ok:
        rendered = _text_output(payload)
        encoded = rendered.encode("utf-8") if rendered else b""
    else:
        encoded = _json_output_bytes(payload, pretty=output.pretty)

    if result.ok:
        limit = _CLI_HARD_RESPONSE_BYTES.get(str(payload.get("op")))
    else:
        limit = _CLI_ERROR_RESPONSE_BYTES
    framing_bytes = 1 if output.format != "text" or encoded else 0
    emitted_size = len(encoded) + framing_bytes
    authoritative_apply = (
        result.ok
        and payload.get("op") == "change_apply"
        and isinstance(payload.get("data"), dict)
        and payload["data"].get("state") == "applied"
    )
    if limit is not None and emitted_size > limit and authoritative_apply and output.pretty:
        encoded = _json_output_bytes(payload, pretty=False)
        emitted_size = len(encoded) + 1
    if limit is not None and emitted_size > limit and authoritative_apply:
        # The change service preflights canonical apply responses before the
        # first write. If an injected executor violates that invariant, report
        # the authoritative mutation outcome rather than fabricate not_applied.
        limit = None
    if limit is not None and emitted_size > limit:
        minimum_bytes = emitted_size
        result = Result(_cli_budget_error(payload, minimum_bytes))
        payload = result.to_payload()
        if output.format == "text":
            encoded = b""
        else:
            encoded = _json_output_bytes(payload, pretty=output.pretty)
            if len(encoded) + 1 > _CLI_ERROR_RESPONSE_BYTES:
                result = Result(_cli_budget_error(payload, minimum_bytes, include_context=False))
                payload = result.to_payload()
                encoded = _json_output_bytes(payload, pretty=output.pretty)

    if output.format == "text":
        if result.ok:
            if encoded:
                sys.stdout.write(encoded.decode("utf-8"))
                sys.stdout.write("\n")
        else:
            message = f"xray: {payload['error']['message']}"
            mutation = payload.get("mutation")
            if isinstance(mutation, dict):
                message += (
                    f" [mutation state={mutation.get('state', '')}"
                    f" rollback_status={mutation.get('rollback_status', '')}]"
                )
            print(message, file=sys.stderr)
    else:
        sys.stdout.write(encoded.decode("utf-8"))
        sys.stdout.write("\n")
    if result.ok:
        return 0
    return _error_exit_code(str(payload["error"]["code"]))


def _write_failure(operation: str | None, error: CliInputError, output: OutputOptions) -> int:
    if error.code.startswith("__help_"):
        help_text = {
            "__help_root__": ROOT_HELP,
            "__help_map__": MAP_HELP,
            "__help_find__": FIND_HELP,
            "__help_interface__": INTERFACE_HELP,
            "__help_read__": READ_HELP,
            "__help_impact__": IMPACT_HELP,
            "__help_search__": SEARCH_HELP,
            "__help_change__": CHANGE_HELP,
            "__help_change_plan__": CHANGE_PLAN_HELP,
            "__help_change_refine__": CHANGE_REFINE_HELP,
            "__help_change_verify__": CHANGE_VERIFY_HELP,
            "__help_change_apply__": CHANGE_APPLY_HELP,
            "__help_capabilities__": CAPABILITIES_HELP,
            "__help_skill__": SKILL_HELP,
        }[error.code]
        print(help_text, end="")
        return 0
    if output.format == "text" and operation != "skill_install":
        message = f"xray: {error}"
        if operation == "change_apply":
            message += " [mutation state=not_applied rollback_status=not_attempted]"
        print(message, file=sys.stderr)
    else:
        _write_json(_error_payload(operation, error.code, error), pretty=output.pretty)
    return _error_exit_code(error.code, parse=True)


def _run_admin(command: ParsedCommand) -> int:
    try:
        result = install_cli_skill(project_root=command.project_root, force=command.force)
    except ValueError as exc:
        error = _error_payload("skill_install", "invalid_request", exc)
        _write_json(error, pretty=command.output.pretty)
        return 2
    except OSError as exc:
        error = _error_payload("skill_install", "io_error", exc)
        _write_json(error, pretty=command.output.pretty)
        return 1
    except Exception as exc:
        error = _error_payload("skill_install", "internal_error", exc)
        _write_json(error, pretty=command.output.pretty)
        return 1

    payload = AdministrativeSuccess(
        schema="xray.v1",
        ok=True,
        op="skill_install",
        data=AdministrativeData.model_validate(
            {
                "scope": result.scope,
                "target": result.target,
                "changed": result.changed,
                "replaced": result.replaced,
                "files": list(result.files),
            }
        ),
    ).to_payload()
    _write_json(payload, pretty=command.output.pretty)
    return 0


def main(argv: list[str] | tuple[str, ...] | None = None) -> int:
    """Parse and execute one handwritten CLI command."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--version"] or (arguments and arguments[0] == "--version"):
        print(f"xray {get_version()}")
        return 0
    output = _scan_output_options(arguments)
    if arguments in (["--help"], ["-h"]):
        print(ROOT_HELP, end="")
        return 0
    if not arguments:
        return _write_failure(None, CliInputError("a command is required"), output)
    try:
        command = _parse_command(arguments)
    except CliInputError as exc:
        operation = {
            "map": "map",
            "find": "find",
            "interface": "interface",
            "read": "read",
            "impact": "impact",
            "search": "search",
            "capabilities": "capabilities",
            "skill": "skill_install",
        }.get(arguments[0] if arguments else "")
        if arguments and arguments[0] == "change" and len(arguments) > 1:
            operation = {
                "plan": "change_plan",
                "refine": "change_refine",
                "verify": "change_verify",
                "apply": "change_apply",
            }.get(arguments[1])
        return _write_failure(operation, exc, output)

    if command.admin:
        return _run_admin(command)
    try:
        result = execute(command.request)
    except Exception as exc:
        error = _error_payload(command.operation, "internal_error", exc)
        _write_json(error, pretty=command.output.pretty)
        return 1
    return _write_result(result, command.output)


if __name__ == "__main__":
    raise SystemExit(main())
