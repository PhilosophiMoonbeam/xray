"""Shared ast-grep subprocess helpers for XRAY internals."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
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


@dataclass(frozen=True)
class BoundedAstGrepResult:
    """Parsed streaming matches with honest execution-completion metadata."""

    matches: list[dict[str, Any]]
    total_exact: bool


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


def run_ast_grep(args: Sequence[str], input_text: str | None = None, *, cwd: Path | None = None) -> AstGrepResult:
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
                    cwd=cwd,
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


def run_ast_grep_bounded(args: Sequence[str], max_results: int) -> BoundedAstGrepResult:
    """Stream JSON matches and terminate ast-grep once the execution cap is reached."""
    if max_results < 1:
        raise ValueError("max_results must be 1 or greater.")
    # Early termination makes parallel result arrival cap-sensitive. A single
    # worker keeps each larger execution cap as a stable prefix for paging and
    # guarded replacement plans.
    command = ["ast-grep", *args, "--threads", "1", "--json=stream"]
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        raise AstGrepNotFoundError("ast-grep executable was not found; symbol search could not run.") from exc

    stdout_stream = process.stdout
    stderr_stream = process.stderr
    assert stdout_stream is not None
    assert stderr_stream is not None
    stdout_lines: queue.Queue[str | None] = queue.Queue()
    stderr_chunks: list[str] = []

    def read_stdout() -> None:
        try:
            for line in stdout_stream:
                stdout_lines.put(line)
        finally:
            stdout_lines.put(None)

    def read_stderr() -> None:
        stderr_chunks.append(stderr_stream.read())

    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    matches: list[dict[str, Any]] = []
    captured_chars = 0
    reached_cap = False
    deadline = time.monotonic() + get_ast_grep_timeout()
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, get_ast_grep_timeout())
            try:
                line = stdout_lines.get(timeout=remaining)
            except queue.Empty as exc:
                raise subprocess.TimeoutExpired(command, get_ast_grep_timeout()) from exc
            if line is None:
                break
            captured_chars += len(line)
            if captured_chars > get_ast_grep_output_limit():
                raise AstGrepCommandError(f"ast-grep stdout exceeded {get_ast_grep_output_limit()} characters.")
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AstGrepCommandError("ast-grep returned invalid streaming JSON.") from exc
            if not isinstance(parsed, dict):
                raise AstGrepCommandError("ast-grep returned unexpected streaming JSON; expected match objects.")
            matches.append(cast(dict[str, Any], parsed))
            if len(matches) >= max_results:
                reached_cap = True
                process.terminate()
                break
        if not reached_cap:
            remaining = max(0.1, deadline - time.monotonic())
            process.wait(timeout=remaining)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        raise AstGrepCommandError(f"ast-grep timed out after {get_ast_grep_timeout():g} seconds.") from exc
    except Exception:
        process.kill()
        process.wait()
        raise
    finally:
        if reached_cap:
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)

    stderr = _limit_output("".join(stderr_chunks), "stderr")
    if not reached_cap and process.returncode not in (0, 1):
        error_output = stderr.strip() if stderr else "(no error output)"
        raise AstGrepCommandError(f"ast-grep failed with exit code {process.returncode}: {error_output}")
    return BoundedAstGrepResult(matches=matches, total_exact=not reached_cap)


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
