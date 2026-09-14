#!/usr/bin/env python3
"""Validate XRAY's thin native OMP project layer.

This check covers only the project layer: its empty YAML mapping, removal of
legacy project overrides, and the required subset of roles exported by the
installed OMP runtime. It does not validate worker prompt prose, product
behavior, qualification, or protected delivery authority.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".omp" / "config.yml"
UNPACK_TIMEOUT = 60
MAX_OUTPUT_BYTES = 1_048_576
REQUIRED_BUNDLED_AGENTS = frozenset(
    {
        "task",
        "sonic",
        "scout",
        "reviewer",
        "security-reviewer",
    }
)


def _output_text(value: object) -> str:
    """Return bounded diagnostic text from a subprocess field."""

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value or "").strip()


def check_config() -> None:
    """Require a valid, empty YAML mapping in the project config."""

    try:
        raw = CONFIG.read_bytes()
    except OSError as error:
        raise ValueError(f"cannot read .omp/config.yml: {error}") from error
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(".omp/config.yml must be UTF-8 YAML") from error
    try:
        config = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ValueError(f".omp/config.yml is invalid YAML: {error}") from error
    if not isinstance(config, dict):
        raise ValueError(".omp/config.yml must contain an empty YAML mapping")
    if config:
        raise ValueError(
            ".omp/config.yml must remain an empty mapping; configure roles and runtime globally"
        )


def check_project_overrides() -> None:
    """Reject repository Codex state and project-local OMP role overrides."""

    obsolete = ROOT / ".codex"
    if obsolete.exists() or obsolete.is_symlink():
        raise ValueError("remove every repository .codex entry; use native .omp configuration")

    agents = ROOT / ".omp" / "agents"
    if agents.is_symlink():
        raise ValueError("remove symlinked .omp/agents overrides; use bundled OMP roles")
    if not agents.exists():
        return
    if not agents.is_dir():
        raise ValueError(".omp/agents must be absent or an empty directory")
    try:
        next(agents.iterdir())
    except StopIteration:
        return
    except OSError as error:
        raise ValueError(f"cannot inspect .omp/agents: {error}") from error
    raise ValueError("remove populated .omp/agents overrides; use bundled OMP roles")


def _run_unpack(directory: str) -> subprocess.CompletedProcess[str]:
    command = ["omp", "agents", "unpack", "--dir", directory, "--json"]
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=UNPACK_TIMEOUT,
        )
    except FileNotFoundError as error:
        raise ValueError("omp executable is missing; cannot unpack bundled agents") from error
    except subprocess.TimeoutExpired as error:
        raise ValueError(f"omp agents unpack timed out after {UNPACK_TIMEOUT} seconds") from error
    except OSError as error:
        raise ValueError(f"could not execute omp agents unpack: {error}") from error

    stdout = _output_text(result.stdout)
    stderr = _output_text(result.stderr)
    if len(stdout.encode("utf-8")) + len(stderr.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise ValueError("omp agents unpack produced more than the bounded output limit")
    if result.returncode != 0:
        detail = stderr or stdout
        suffix = f": {detail[:256]}" if detail else ""
        raise ValueError(f"omp agents unpack failed with exit status {result.returncode}{suffix}")
    return result


def _parse_unpack_output(result: subprocess.CompletedProcess[str]) -> frozenset[str]:
    raw = _output_text(result.stdout)
    try:
        payload: Any = json.loads(raw)
    except (TypeError, UnicodeError, json.JSONDecodeError) as error:
        suffix = f" ({raw[:256]!r})" if raw else ""
        raise ValueError(f"omp agents unpack returned malformed JSON{suffix}") from error
    if not isinstance(payload, dict):
        raise ValueError("omp agents unpack JSON must be an object")

    written = payload.get("written")
    if not isinstance(written, list) or any(
        not isinstance(path, str) or not path.strip() for path in written
    ):
        raise ValueError("omp agents unpack did not return a written-file list of strings")

    actual = frozenset(Path(path).stem for path in written)
    if not actual:
        raise ValueError("omp agents unpack returned no written agent files")
    missing = sorted(REQUIRED_BUNDLED_AGENTS - actual)
    if missing:
        raise ValueError(f"required bundled agents were not exported: {missing}")
    return actual


def check_bundled_agents() -> frozenset[str]:
    with tempfile.TemporaryDirectory(prefix="xray-omp-agents-") as directory:
        result = _run_unpack(directory)
        return _parse_unpack_output(result)


def main() -> int:
    try:
        check_project_overrides()
        check_config()
        bundled_agents = check_bundled_agents()
    except (OSError, TypeError, ValueError) as error:
        print(f"XRAY native OMP project layer invalid: {error}", file=sys.stderr)
        return 1

    print(
        "validated XRAY native OMP project layer and required bundled-agent subset: "
        f"{', '.join(sorted(bundled_agents))}; no product, prompt, qualification, or delivery claim"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
