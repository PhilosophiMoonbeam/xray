#!/usr/bin/env python3
"""Inject bounded XRAY Beads workflow and current work at session boundaries."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

LIMIT = 20
COMMAND_TIMEOUT_SECONDS = 8
PRIME_LIMIT = 8_000
IDENTIFIER_LIMIT = 120
TITLE_LIMIT = 240
ASSIGNEE_LIMIT = 120
NOTES_LIMIT = 500


class RecoveryError(RuntimeError):
    """A bounded, user-safe Beads recovery failure."""


def tracker_root() -> Path:
    """Return XRAY's canonical contributor-planning checkout."""
    return Path.home() / ".beads-planning"


def clean_text(value: object, *, fallback: str, limit: int) -> str:
    if not isinstance(value, str):
        return fallback
    compact = " ".join(value.split())
    if not compact:
        return fallback
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1]}…"


def command_label(arguments: list[str]) -> str:
    return f"bd {' '.join(arguments)}"


def run_bd(arguments: list[str], *, json_output: bool) -> str:
    command = ["bd", "--readonly", "-C", str(tracker_root()), *arguments]
    if json_output:
        command.append("--json")
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise RecoveryError("the bd executable is unavailable") from exc
    except subprocess.TimeoutExpired as exc:
        raise RecoveryError(f"{command_label(arguments)} timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = clean_text(exc.stderr, fallback="command failed", limit=240)
        raise RecoveryError(f"{command_label(arguments)} failed: {detail}") from exc
    return result.stdout


def parse_items(raw: str, *, source: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RecoveryError(f"{source} returned malformed JSON") from exc
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RecoveryError(f"{source} returned JSON other than a list of objects")
    return value


def run_json(arguments: list[str]) -> list[dict[str, Any]]:
    return parse_items(run_bd(arguments, json_output=True), source=command_label(arguments))


def run_prime() -> str:
    prime = run_bd(["prime"], json_output=False).rstrip()
    if not prime:
        raise RecoveryError("bd prime returned no workflow context")
    if len(prime) <= PRIME_LIMIT:
        return prime
    return f"{prime[:PRIME_LIMIT].rstrip()}\n\n[bd prime output truncated at {PRIME_LIMIT} characters]"


def priority_key(item: dict[str, Any]) -> tuple[int, str]:
    value = item.get("priority")
    try:
        priority = int(value)
    except (TypeError, ValueError):
        priority = 99
    identifier = clean_text(item.get("id"), fallback="unknown", limit=IDENTIFIER_LIMIT)
    return priority, identifier


def summarize(items: list[dict[str, Any]], *, active: bool) -> str:
    if not items:
        return "- None"
    ordered = sorted(items, key=priority_key)
    lines: list[str] = []
    for item in ordered[:LIMIT]:
        identifier = clean_text(item.get("id"), fallback="unknown", limit=IDENTIFIER_LIMIT)
        priority = item.get("priority", "?")
        if not isinstance(priority, (int, str)):
            priority = "?"
        title = clean_text(item.get("title"), fallback="untitled", limit=TITLE_LIMIT)
        line = f"- `{identifier}` P{priority}: {title}"
        if active:
            assignee = clean_text(item.get("assignee"), fallback="unassigned", limit=ASSIGNEE_LIMIT)
            line += f" (assignee: {assignee})"
            notes = clean_text(item.get("notes"), fallback="", limit=NOTES_LIMIT)
            if notes:
                line += f"\n  - Handoff: {notes}"
        lines.append(line)
    if len(ordered) > LIMIT:
        lines.append(f"- More than {LIMIT} results; run the corresponding `bd` command.")
    return "\n".join(lines)


def additional_context(
    prime: str,
    ready: list[dict[str, Any]],
    active: list[dict[str, Any]],
) -> str:
    return (
        f"{prime}\n\n"
        "# Current XRAY Beads State\n\n"
        "This state was read from the canonical planning checkout at the session boundary. "
        "Run `bd --readonly show <id>` before acting when a full contract is required.\n\n"
        "## Ready frontier\n\n"
        f"{summarize(ready, active=False)}\n\n"
        "## Active claims\n\n"
        f"{summarize(active, active=True)}"
    )


def unavailable_context(error: RecoveryError) -> str:
    detail = clean_text(str(error), fallback="unknown recovery failure", limit=400)
    return (
        "# XRAY Beads Recovery Unavailable\n\n"
        f"The read-only session recovery check could not load canonical state: {detail}.\n\n"
        "Run `bd where`. If no tracker exists, stop and follow the XRAY contributor bootstrap "
        "in `docs/ADAPTATION.md`; do not create an independent canonical store or fabricate work state."
    )


def hook_payload(context: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }


def payload() -> dict[str, Any]:
    try:
        ready = run_json(["ready", f"--limit={LIMIT + 1}"])
        active = run_json(["list", "--status=in_progress", f"--limit={LIMIT + 1}"])
        context = additional_context(run_prime(), ready, active)
    except RecoveryError as exc:
        context = unavailable_context(exc)
    return hook_payload(context)


def expect_recovery_error(raw: str, source: str) -> None:
    try:
        parse_items(raw, source=source)
    except RecoveryError:
        return
    raise SystemExit(f"session-start self-test accepted malformed {source}")


def self_test() -> None:
    ready = [{"id": "xray-ready", "priority": 1, "title": "Ready work"}]
    active = [
        {
            "id": "xray-active",
            "priority": 2,
            "title": "Active work",
            "assignee": "root",
            "notes": "SHA abc; next: run checks",
        }
    ]
    context = additional_context("workflow", ready, active)
    required = (
        "workflow",
        "# Current XRAY Beads State",
        "`xray-ready` P1: Ready work",
        "`xray-active` P2: Active work (assignee: root)",
        "Handoff: SHA abc; next: run checks",
    )
    missing = [text for text in required if text not in context]
    if missing:
        raise SystemExit(f"session-start self-test missing ready/active/notes content: {missing}")
    if summarize([], active=False) != "- None" or summarize([], active=True) != "- None":
        raise SystemExit("session-start self-test mishandled empty state")
    if "unassigned" not in summarize([{"id": "x", "title": "work"}], active=True):
        raise SystemExit("session-start self-test mishandled a missing assignee")
    expect_recovery_error("{", "malformed JSON")
    expect_recovery_error("{}", "non-list JSON")
    expect_recovery_error('[{"id": "ok"}, 1]', "non-object item")
    fallback = unavailable_context(RecoveryError("test failure"))
    if "do not create an independent canonical store or fabricate work state" not in fallback:
        raise SystemExit("session-start self-test mishandled recovery failure")
    encoded = json.dumps(hook_payload(context))
    decoded = json.loads(encoded)
    if decoded["hookSpecificOutput"]["hookEventName"] != "SessionStart":
        raise SystemExit("session-start self-test emitted an invalid hook payload")
    print("validated SessionStart ready/active/notes/empty/malformed composition")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    print(json.dumps(payload()))


if __name__ == "__main__":
    main()
