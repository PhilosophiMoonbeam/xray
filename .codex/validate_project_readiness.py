#!/usr/bin/env python3
"""Gate XRAY readiness on a complete project profile and architecture."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "PROJECT.md"
ARCHITECTURE = ROOT / "ARCHITECTURE.md"
PROJECT_SECTIONS = (
    "Purpose",
    "Architecture",
    "Integration branch",
    "Component ownership",
    "Canonical commands",
    "Delivery authority",
    "External and shared resources",
    "Sensitive and destructive operations",
    "Required nested instructions",
    "CI qualification",
    "Compatibility, risks, and rollback",
    "Evidence",
)
ARCHITECTURE_SECTIONS = (
    "System boundaries",
    "Component and ownership map",
    "CLI contract",
    "MCP contract and intentional surface differences",
    "Bounds, containment, and cursors",
    "Analysis and mutation semantics",
    "Runtime state and resources",
    "Distribution and package compatibility",
    "Verification and evidence boundaries",
    "Synchronized change edges",
)
PLACEHOLDER_PATTERNS = (
    r"^REQUIRED:",
    r"\bTBD\b",
    r"\bTODO\b",
    r"\bFIXME\b",
    r"<placeholder>",
    r"Replace this explanatory text",
)
PROJECT_SECTION_MIN_CHARS = 80
ARCHITECTURE_SECTION_MIN_CHARS = 120
ARCHITECTURE_MIN_WORDS = 1200
ARCHITECTURE_MIN_BYTES = 9000


def headings(text: str) -> set[str]:
    return set(re.findall(r"^##\s+(.+?)\s*$", text, re.MULTILINE))


def section_body(text: str, name: str) -> str:
    pattern = rf"^##\s+{re.escape(name)}\s*$\n(.*?)(?=^##\s+|\Z)"
    match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    return "" if match is None else match.group(1).strip()


def readiness_problems(profile_text: str, architecture_text: str) -> list[str]:
    problems: list[str] = []
    statuses = re.findall(r"^Status:\s*(\S+)\s*$", profile_text, re.MULTILINE)
    if statuses != ["READY"]:
        problems.append("PROJECT.md status must occur once and be exactly READY")
    combined = profile_text + "\n" + architecture_text
    for pattern in PLACEHOLDER_PATTERNS:
        if re.search(pattern, combined, re.MULTILINE | re.IGNORECASE):
            problems.append(f"unresolved placeholder matches {pattern}")

    project_headings = headings(profile_text)
    for name in PROJECT_SECTIONS:
        if name not in project_headings:
            problems.append(f"PROJECT.md mandatory section is missing: {name}")
        elif len(section_body(profile_text, name)) < PROJECT_SECTION_MIN_CHARS:
            problems.append(f"PROJECT.md mandatory section is not substantive: {name}")

    architecture_headings = headings(architecture_text)
    for name in ARCHITECTURE_SECTIONS:
        if name not in architecture_headings:
            problems.append(f"ARCHITECTURE.md mandatory section is missing: {name}")
        elif len(section_body(architecture_text, name)) < ARCHITECTURE_SECTION_MIN_CHARS:
            problems.append(f"ARCHITECTURE.md section is not substantive: {name}")
    if (
        len(architecture_text.split()) < ARCHITECTURE_MIN_WORDS
        or len(architecture_text.encode("utf-8")) < ARCHITECTURE_MIN_BYTES
    ):
        problems.append("ARCHITECTURE.md is too small to substantiate the frozen component contract")
    architecture_contracts = (
        "xray.cli.v2",
        "xray.cli.v1",
        "Python `>=3.10`",
        "/tmp/.xray_cache",
        "src/xray/lsp_config.json",
        "Synchronized change edges",
    )
    problems.extend(
        f"ARCHITECTURE.md contract is missing: {item}"
        for item in architecture_contracts
        if item not in architecture_text
    )
    return problems


def self_test() -> None:
    profile = PROFILE.read_text(encoding="utf-8")
    architecture = ARCHITECTURE.read_text(encoding="utf-8")
    ready = profile.replace("Status: NOT_READY", "Status: READY", 1)
    failures: list[str] = []
    cases = {
        "current NOT_READY": readiness_problems(profile, architecture),
        "REQUIRED field": readiness_problems(ready + "\nREQUIRED: value\n", architecture),
        "placeholder architecture": readiness_problems(ready, "# Architecture\n\nTBD\n"),
        "missing project section": readiness_problems(ready.replace("## Evidence", "## Removed"), architecture),
        "thin architecture": readiness_problems(ready, "# XRAY Architecture\n\n## System boundaries\n\nThin.\n"),
    }
    if readiness_problems(ready, architecture):
        failures.append("self-test rejected the current substantive authority after exact READY substitution")
    failures.extend(f"self-test missed {name}" for name, problems in cases.items() if not problems)
    if failures:
        raise SystemExit("readiness validator self-test failed:\n" + "\n".join(failures))
    print(f"validated exact READY positive case and {len(cases)} readiness negative cases")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    profile_text = PROFILE.read_text(encoding="utf-8")
    architecture_text = ARCHITECTURE.read_text(encoding="utf-8")
    problems = readiness_problems(profile_text, architecture_text)
    if problems:
        raise SystemExit("XRAY project is not ready:\n" + "\n".join(problems))
    print("validated XRAY project readiness")


if __name__ == "__main__":
    main()
