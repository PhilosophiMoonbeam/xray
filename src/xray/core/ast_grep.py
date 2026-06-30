"""Shared ast-grep subprocess helpers for XRAY internals."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

DEFAULT_AST_GREP_TIMEOUT_SECONDS = 30
AST_GREP_TIMEOUT_ENV = "XRAY_AST_GREP_TIMEOUT_SECONDS"
DEFAULT_AST_GREP_OUTPUT_LIMIT_CHARS = 10 * 1024 * 1024
AST_GREP_OUTPUT_LIMIT_ENV = "XRAY_AST_GREP_OUTPUT_LIMIT_CHARS"


@dataclass(frozen=True)
class AstGrepResult:
    """Completed ast-grep command with normalized no-match semantics."""

    stdout: str
    stderr: str
    returncode: int
    no_matches: bool = False


class AstGrepError(RuntimeError):
    """Base ast-grep execution failure."""


class AstGrepNotFoundError(AstGrepError):
    """Raised when the ast-grep executable is unavailable."""


class AstGrepCommandError(AstGrepError):
    """Raised when ast-grep returns an actual command failure."""


def get_ast_grep_timeout() -> float:
    """Return the configured ast-grep subprocess timeout."""
    raw_timeout = os.environ.get(AST_GREP_TIMEOUT_ENV)
    if raw_timeout is None:
        return float(DEFAULT_AST_GREP_TIMEOUT_SECONDS)
    try:
        return max(0.1, float(raw_timeout))
    except ValueError:
        return float(DEFAULT_AST_GREP_TIMEOUT_SECONDS)


def get_ast_grep_output_limit() -> int:
    """Return the maximum ast-grep stdout/stderr characters XRAY will read."""
    raw_limit = os.environ.get(AST_GREP_OUTPUT_LIMIT_ENV)
    if raw_limit is None:
        return DEFAULT_AST_GREP_OUTPUT_LIMIT_CHARS
    try:
        return max(1024, int(raw_limit))
    except ValueError:
        return DEFAULT_AST_GREP_OUTPUT_LIMIT_CHARS


def run_ast_grep(args: Sequence[str], input_text: str | None = None) -> AstGrepResult:
    """Run ast-grep and treat exit code 1 as a normal no-match outcome."""
    command = ["ast-grep", *args]
    try:
        with tempfile.TemporaryFile("w+", encoding="utf-8") as stdout_file:
            with tempfile.TemporaryFile("w+", encoding="utf-8") as stderr_file:
                completed = subprocess.run(
                    command,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    check=False,
                    input=input_text,
                    text=True,
                    timeout=get_ast_grep_timeout(),
                )
                stdout = _completed_stream_text(completed.stdout, stdout_file, "stdout")
                stderr = _completed_stream_text(completed.stderr, stderr_file, "stderr")
    except FileNotFoundError as exc:
        raise AstGrepNotFoundError("ast-grep executable was not found; symbol search could not run.") from exc
    except subprocess.TimeoutExpired as exc:
        raise AstGrepCommandError(f"ast-grep timed out after {get_ast_grep_timeout():g} seconds.") from exc

    if completed.returncode == 0:
        return AstGrepResult(stdout, stderr, completed.returncode)

    if completed.returncode == 1 and _is_no_match_output(stdout, args):
        return AstGrepResult(stdout, stderr, completed.returncode, no_matches=True)

    error_output = stderr.strip() if stderr else "(no error output)"
    raise AstGrepCommandError(f"ast-grep failed with exit code {completed.returncode}: {error_output}")


def _completed_stream_text(completed_text: str | None, stream: Any, name: str) -> str:
    """Read subprocess output from a temp stream, honoring test-provided CompletedProcess text."""
    if completed_text is not None:
        return _limit_output(completed_text, name)

    stream.seek(0, os.SEEK_END)
    length = stream.tell()
    limit = get_ast_grep_output_limit()
    if length > limit:
        raise AstGrepCommandError(f"ast-grep {name} exceeded {limit} characters.")

    stream.seek(0)
    return _limit_output(stream.read(), name)


def _limit_output(text: str, name: str) -> str:
    limit = get_ast_grep_output_limit()
    if len(text) > limit:
        raise AstGrepCommandError(f"ast-grep {name} exceeded {limit} characters.")
    return text


def parse_json_array(stdout: str) -> list[dict[str, Any]]:
    """Parse ast-grep --json output and require a JSON array."""
    parsed = json.loads(stdout or "[]")
    if not isinstance(parsed, list):
        raise ValueError("ast-grep returned unexpected JSON; expected a list of matches.")
    parsed_matches = cast(list[Any], parsed)
    if not all(isinstance(match, dict) for match in parsed_matches):
        raise ValueError("ast-grep returned unexpected JSON; expected match objects.")
    return cast(list[dict[str, Any]], parsed_matches)


def _is_no_match_output(stdout: str, args: Sequence[str]) -> bool:
    stripped = stdout.strip()
    if "--json=stream" in args:
        return stripped == "" or all(line.lstrip().startswith("{") for line in stripped.splitlines())
    if any(arg == "--json" or arg.startswith("--json=") for arg in args):
        return stripped in ("", "[]") or stripped.startswith("[")
    return stripped == ""
