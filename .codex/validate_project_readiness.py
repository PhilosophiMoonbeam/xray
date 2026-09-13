# ruff: noqa: E501,PLR2004

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE, ARCHITECTURE = ROOT / "PROJECT.md", ROOT / "ARCHITECTURE.md"
# fmt: off
PROJECT_SECTIONS = "Purpose|Architecture|Integration branch|Component ownership|Canonical commands|Delivery authority|External and shared resources|Sensitive and destructive operations|Required nested instructions|CI qualification|Compatibility, risks, and rollback|Evidence".split("|")
ARCHITECTURE_SECTIONS = "System boundaries|Component and ownership map|CLI contract|MCP contract and intentional surface differences|Bounds, containment, and cursors|Analysis and mutation semantics|Runtime state and resources|Distribution and package compatibility|Verification and evidence boundaries|Synchronized change edges".split("|")
PLACEHOLDER = re.compile(r"^REQUIRED:|<placeholder>|Replace this explanatory text|\b(?:TBD|TODO|FIXME)\b", re.I | re.M)
LEGACY = re.compile(r"\b(?:" + "|".join(map(re.escape, "0.11.4|explore_repo|find_symbol|read_symbol|symbol_at|scan_rules|check_rules|apply_rule_fixes|rewrite_pattern|plan_replacement|refine_replacement|verify_replacement|apply_replacement".split("|"))) + r"|last_[A-Za-z_]+)\b|\bxray\.(?:replace\.v[12]|cli\.v[123])\b|\b(?:XRAY_AST_GREP_OUTPUT_LIMIT_CHARS|XRAY_AST_GREP_TIMEOUT_SECONDS|XRAY_MCP_INDEXER_CACHE_LIMIT)\b|--(?:max-depth|all-depths|strict-focus|include-symbols|max-entries|schema)\b|--detail full\b|/tmp/\.xray_cache\b|symbol skeleton|process-local indexer cache|lsp_config\.json|\brules (?:check|explain|test)\b")
CURRENT_TEXT_FILES = tuple(ROOT / p for p in "README.md docs/implementation-standard.md Makefile install.sh src/xray/guidance.md skills/xray-cli/SKILL.md src/xray/agent_skills/xray-cli/SKILL.md src/xray/skills/xray-progressive-discovery/SKILL.md".split())
VERSION_FILES = (ROOT / "pyproject.toml", ROOT / "src/xray/__init__.py", ROOT / "uv.lock")


def section_body(text: str, name: str) -> str:
    match = re.search(rf"^##\s+{re.escape(name)}\s*$\n(.*?)(?=^##\s+|\Z)", text, re.M | re.S)
    return "" if match is None else match.group(1).strip()
def release_version_problems() -> list[str]:
    problems, versions = [], []
    patterns = (r'^version\s*=\s*"([^"]+)"\s*$', r'^__version__\s*=\s*"([^"]+)"\s*$', r'(?ms)^\[\[package\]\]\nname = "xray"\nversion = "([^"]+)"')
    for path, pattern in zip(VERSION_FILES, patterns):
        try:
            match = re.search(pattern, path.read_text(encoding="utf-8"), re.M)
        except OSError:
            problems.append("version file unreadable")
            continue
        if match:
            versions.append(match[1])
        else:
            problems.append("version missing")
    if len(versions) == 3 and len(set(versions)) != 1:
        problems.append("versions differ")
    return problems

def readiness_problems(profile: str, architecture: str) -> list[str]:
    sections = (section_body(architecture, name) for name in ("XRAY 1.0.0 current contract", *ARCHITECTURE_SECTIONS))
    files = (p.read_text(encoding="utf-8") for p in CURRENT_TEXT_FILES if p.exists())
    current = "\n".join((profile, *sections, *files))
    checks = ((re.findall(r"^Status:\s*(\S+)\s*$", profile, re.M) != ["READY"], "status"), (PLACEHOLDER.search(profile + "\n" + architecture) is not None, "placeholder"), (LEGACY.search(current) is not None, "legacy"), ((ROOT / "src/xray/lsp_config.json").exists(), "inactive LSP"))
    problems = [message for failed, message in checks if failed]
    for text, names, minimum, label in ((profile, PROJECT_SECTIONS, 80, "PROJECT.md"), (architecture, ARCHITECTURE_SECTIONS, 120, "ARCHITECTURE.md")):
        found = set(re.findall(r"^##\s+(.+?)\s*$", text, re.M))
        for name in names:
            if name not in found:
                problems.append(f"{label} missing: {name}")
            elif len(section_body(text, name)) < minimum:
                problems.append(f"{label} thin: {name}")
    if len(architecture.split()) < 1200 or len(architecture.encode()) < 9000:
        problems.append("architecture too small")
    required = "XRAY 1.0.0 current contract|xray.v1|xray.change.v1|Python `>=3.10`|DerivedCache|platform cache directory|xray/derived|search_tools|call_tool|xray://workflow|Synchronized change edges".split("|")
    problems.extend(f"ARCHITECTURE.md contract is missing: {item}" for item in required if item not in architecture)
    return problems


def self_test() -> None:
    profile, architecture = PROFILE.read_text(encoding="utf-8"), ARCHITECTURE.read_text(encoding="utf-8")
    ready = profile.replace("Status: NOT_READY", "Status: READY", 1)
    cases = ((profile.replace("Status: READY", "Status: NOT_READY", 1), architecture), (ready + "\nREQUIRED: value\n", architecture), (ready, "# Architecture\n\nTBD\n"), (ready.replace("## Evidence", "## Removed"), architecture), (ready, "# XRAY Architecture\n\n## System boundaries\n\nThin.\n"), (ready, architecture + "\nexplore_repo\n"))
    if readiness_problems(ready, architecture) or release_version_problems() or any(not readiness_problems(p, a) for p, a in cases):
        raise SystemExit("self-test failed")
    print(f"validated {len(cases)} readiness negatives")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    if parser.parse_args().self_test:
        self_test()
        return
    problems = readiness_problems(PROFILE.read_text(encoding="utf-8"), ARCHITECTURE.read_text(encoding="utf-8")) + release_version_problems()
    if problems:
        raise SystemExit("XRAY project is not ready:\n" + "\n".join(problems))
    print("validated XRAY project readiness")


if __name__ == "__main__":
    main()
