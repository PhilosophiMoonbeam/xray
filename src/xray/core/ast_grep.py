"""Shared ast-grep subprocess helpers for XRAY internals."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


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


def run_ast_grep(args: Sequence[str], input_text: str | None = None) -> AstGrepResult:
    """Run ast-grep and treat exit code 1 as a normal no-match outcome."""
    command = ["ast-grep", *args]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            input=input_text,
            text=True,
        )
    except FileNotFoundError as exc:
        raise AstGrepNotFoundError("ast-grep executable was not found; symbol search could not run.") from exc

    if completed.returncode == 0:
        return AstGrepResult(completed.stdout, completed.stderr, completed.returncode)

    if completed.returncode == 1 and _is_no_match_output(completed.stdout, args):
        return AstGrepResult(completed.stdout, completed.stderr, completed.returncode, no_matches=True)

    stderr = completed.stderr.strip() if completed.stderr else "(no error output)"
    raise AstGrepCommandError(f"ast-grep failed with exit code {completed.returncode}: {stderr}")


def parse_json_array(stdout: str) -> list[dict[str, Any]]:
    """Parse ast-grep --json output and require a JSON array."""
    parsed = json.loads(stdout or "[]")
    if not isinstance(parsed, list):
        raise ValueError("ast-grep returned unexpected JSON; expected a list of matches.")
    return parsed


def _is_no_match_output(stdout: str, args: Sequence[str]) -> bool:
    stripped = stdout.strip()
    if "--json=stream" in args:
        return stripped == "" or all(line.lstrip().startswith("{") for line in stripped.splitlines())
    if any(arg == "--json" or arg.startswith("--json=") for arg in args):
        return stripped in ("", "[]") or stripped.startswith("[")
    return stripped == ""
