#!/usr/bin/env python3
"""Check factual XRAY project readiness without imposing prose-size quotas."""

from __future__ import annotations

import argparse
import re
import tempfile
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_RELEASE_IDENTITY_SOURCES = 3

PROJECT_SECTIONS = (
    "Purpose",
    "Architecture",
    "Integration branch",
    "Component ownership",
    "Canonical command catalog",
    "Delivery authority",
    "External and shared resources",
    "Sensitive and destructive operations",
    "Required nested instructions",
    "CI and paused qualification",
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
    "Current change policy",
)

CURRENT_DOCS = tuple(
    Path(path)
    for path in (
        "AGENTS.md",
        "PROJECT.md",
        "ARCHITECTURE.md",
        "README.md",
        "docs/repository-language-standard.md",
        "docs/implementation-standard.md",
        "docs/agent-model-routing.md",
        "docs/agent-operations.md",
        ".omp/AGENTS.md",
    )
)
CURRENT_TEXT_FILES = tuple(
    Path(path)
    for path in (
        "AGENTS.md",
        "README.md",
        "docs/repository-language-standard.md",
        "docs/implementation-standard.md",
        "docs/agent-model-routing.md",
        "docs/agent-operations.md",
        "Makefile",
        "install.sh",
        "src/xray/guidance.md",
        "skills/xray-cli/SKILL.md",
        "src/xray/agent_skills/xray-cli/SKILL.md",
        "src/xray/skills/xray-progressive-discovery/SKILL.md",
    )
)
LINK_SOURCES = (Path("AGENTS.md"), Path(".omp/AGENTS.md"))
INDEX_REQUIRED_LINKS = (
    "PROJECT.md",
    "ARCHITECTURE.md",
    "docs/repository-language-standard.md",
    "docs/implementation-standard.md",
    "docs/agent-model-routing.md",
    "docs/agent-operations.md",
)
NATIVE_REQUIRED_IMPORTS = ("../AGENTS.md", "../PROJECT.md")
INACTIVE_ASSETS = (Path("src/xray/lsp_config.json"),)

PLACEHOLDER = re.compile(
    r"^REQUIRED:|<placeholder>|Replace this explanatory text|\b(?:TBD|TODO|FIXME)\b",
    re.IGNORECASE | re.MULTILINE,
)
LEGACY = re.compile(
    r"\b(?:"
    + "|".join(
        map(
            re.escape,
            (
                "0.11.4",
                "explore_repo",
                "find_symbol",
                "read_symbol",
                "symbol_at",
                "scan_rules",
                "check_rules",
                "apply_rule_fixes",
                "rewrite_pattern",
                "plan_replacement",
                "refine_replacement",
                "verify_replacement",
                "apply_replacement",
            ),
        )
    )
    + r"|last_[A-Za-z_]+)\b"
    r"|\bxray\.(?:replace\.v[12]|cli\.v[123])\b"
    r"|\b(?:XRAY_AST_GREP_OUTPUT_LIMIT_CHARS|XRAY_AST_GREP_TIMEOUT_SECONDS|XRAY_MCP_INDEXER_CACHE_LIMIT)\b"
    r"|--(?:max-depth|all-depths|strict-focus|include-symbols|max-entries|schema)\b"
    r"|--detail full\b"
    r"|/tmp/\.xray_cache\b"
    r"|symbol skeleton"
    r"|process-local indexer cache"
    r"|lsp_config\.json"
    r"|\brules (?:check|explain|test)\b",
    re.IGNORECASE,
)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)\s]+)(?:\s+[^)]*)?\)")
NATIVE_IMPORT = re.compile(r"^\s*@([^\s#]+)\s*$", re.MULTILINE)


def resolve_target(value: str | None) -> Path:
    raw = ROOT if value is None else Path(value)
    try:
        target = raw.expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise SystemExit(f"project profile is not ready: invalid target root: {raw}") from error
    if not target.is_dir():
        raise SystemExit(f"project profile is not ready: target root is not a directory: {target}")
    return target


def read_required(root: Path, relative: Path) -> str:
    path = root / relative
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise SystemExit(f"project profile is not ready: cannot read {relative}: {error}") from error


def _required_document_problems(root: Path) -> list[str]:
    return [
        f"required current document is missing: {relative}"
        for relative in CURRENT_DOCS
        if not (root / relative).is_file()
    ]


def _section_problems(text: str, names: tuple[str, ...], label: str) -> list[str]:
    found = set(re.findall(r"^##\s+(.+?)\s*$", text, re.MULTILINE))
    return [f"{label} missing required section: {name}" for name in names if name not in found]


def _local_target(value: str) -> str:
    target = unquote(value.split("#", 1)[0].split("?", 1)[0])
    if not target or target.startswith("/") or "://" in target or target.startswith(("mailto:", "tel:")):
        return ""
    return target


def _link_targets(root: Path, source: Path) -> tuple[list[str], list[str]]:
    path = root / source
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return [], []
    markdown = [_local_target(match.group(1)) for match in MARKDOWN_LINK.finditer(text)]
    imports = [match.group(1) for match in NATIVE_IMPORT.finditer(text)]
    return [target for target in markdown if target], [target for target in imports if target]


def link_problems(root: Path) -> list[str]:
    """Resolve the root index's local Markdown links and native @ imports."""

    problems: list[str] = []
    for source in LINK_SOURCES:
        markdown, imports = _link_targets(root, source)
        for target in (*markdown, *imports):
            candidate = root / source.parent / target
            if not candidate.exists():
                problems.append(f"{source} links to missing local path: {target}")

    markdown, _ = _link_targets(root, Path("AGENTS.md"))
    for target in INDEX_REQUIRED_LINKS:
        if target not in markdown:
            problems.append(f"AGENTS.md is missing required authority link: {target}")

    _, imports = _link_targets(root, Path(".omp/AGENTS.md"))
    for target in NATIVE_REQUIRED_IMPORTS:
        if target not in imports:
            problems.append(f".omp/AGENTS.md is missing required native import: @{target}")
    return problems


def _current_text(root: Path, profile: str, architecture: str) -> str:
    values = [profile, architecture]
    for relative in CURRENT_TEXT_FILES:
        path = root / relative
        if not path.is_file() or relative in {Path("PROJECT.md"), Path("ARCHITECTURE.md")}:
            continue
        try:
            values.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return "\n".join(values)


def _legacy_problems(text: str) -> list[str]:
    seen: set[str] = set()
    problems: list[str] = []
    for match in LEGACY.finditer(text):
        marker = match.group(0).strip()
        if marker and marker not in seen:
            seen.add(marker)
            problems.append(f"current docs contain forbidden legacy surface: {marker!r}")
    return problems


def _inactive_asset_problems(root: Path) -> list[str]:
    return [
        f"inactive asset remains live: {relative}"
        for relative in INACTIVE_ASSETS
        if (root / relative).exists() or (root / relative).is_symlink()
    ]


def release_version_problems(root: Path = ROOT) -> list[str]:
    problems: list[str] = []
    versions: list[str] = []
    sources = (
        (Path("pyproject.toml"), r'^version\s*=\s*["\']([^"\']+)["\']\s*$'),
        (Path("src/xray/__init__.py"), r'^__version__\s*=\s*["\']([^"\']+)["\']\s*$'),
    )
    for relative, pattern in sources:
        path = root / relative
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            problems.append(f"release identity file unreadable: {relative}")
            continue
        matches = re.findall(pattern, text, re.MULTILINE)
        if len(matches) != 1:
            problems.append(f"release version missing or ambiguous: {relative}")
            continue
        versions.append(matches[0])

    lock_path = root / "uv.lock"
    try:
        lock_text = lock_path.read_text(encoding="utf-8")
    except OSError:
        problems.append("release identity file unreadable: uv.lock")
    else:
        blocks = re.findall(r"(?ms)^\[\[package\]\]\n(.*?)(?=^\[\[package\]\]|\Z)", lock_text)
        lock_versions = [
            version
            for block in blocks
            if re.search(r'^name\s*=\s*["\']xray["\']\s*$', block, re.MULTILINE)
            for version in re.findall(r'^version\s*=\s*["\']([^"\']+)["\']\s*$', block, re.MULTILINE)
        ]
        if len(lock_versions) != 1:
            problems.append("release version missing or ambiguous: uv.lock package xray")
        else:
            versions.append(lock_versions[0])

    if versions and len(versions) == EXPECTED_RELEASE_IDENTITY_SOURCES and len(set(versions)) != 1:
        problems.append(f"release versions differ: {', '.join(versions)}")
    return problems


def readiness_problems(profile: str, architecture: str, root: Path = ROOT) -> list[str]:
    problems: list[str] = []
    statuses = re.findall(r"^Status:\s*(\S+)\s*$", profile, re.MULTILINE)
    if statuses != ["READY"]:
        problems.append("PROJECT.md must contain exactly one status line: Status: READY")
    if PLACEHOLDER.search(profile + "\n" + architecture) is not None:
        problems.append("PROJECT.md or ARCHITECTURE.md contains a placeholder marker")

    problems.extend(_required_document_problems(root))
    problems.extend(_section_problems(profile, PROJECT_SECTIONS, "PROJECT.md"))
    problems.extend(_section_problems(architecture, ARCHITECTURE_SECTIONS, "ARCHITECTURE.md"))
    problems.extend(link_problems(root))
    problems.extend(_legacy_problems(_current_text(root, profile, architecture)))
    problems.extend(_inactive_asset_problems(root))
    return problems


def _expect_negative(label: str, profile: str, architecture: str, root: Path) -> None:
    if not readiness_problems(profile, architecture, root):
        raise SystemExit(f"self-test failed: {label} was accepted")


def self_test(root: Path = ROOT) -> None:
    profile = read_required(root, Path("PROJECT.md"))
    architecture = read_required(root, Path("ARCHITECTURE.md"))
    baseline = readiness_problems(profile, architecture, root) + release_version_problems(root)
    if baseline:
        raise SystemExit("self-test baseline is not ready:\n" + "\n".join(baseline))

    cases = (
        (
            "non-ready status",
            re.sub(r"^Status:\s*READY\s*$", "Status: NOT_READY", profile, count=1, flags=re.MULTILINE),
            architecture,
        ),
        ("duplicate ready status", profile + "\nStatus: READY\n", architecture),
        ("placeholder", profile + "\nREQUIRED: unfinished\n", architecture),
        (
            "missing required section",
            re.sub(r"^## Evidence\s*$", "## Removed", profile, count=1, flags=re.MULTILINE),
            architecture,
        ),
        ("legacy surface", profile, architecture + "\nexplore_repo\n"),
    )
    for label, case_profile, case_architecture in cases:
        _expect_negative(label, case_profile, case_architecture, root)

    with tempfile.TemporaryDirectory(prefix="xray-readiness-") as directory:
        disposable = Path(directory)
        (disposable / "AGENTS.md").write_text("[missing](missing.md)\n", encoding="utf-8")
        if not link_problems(disposable):
            raise SystemExit("self-test failed: broken local link was accepted")
        asset = disposable / "src/xray/lsp_config.json"
        asset.parent.mkdir(parents=True)
        asset.write_text("{}\n", encoding="utf-8")
        if not _inactive_asset_problems(disposable):
            raise SystemExit("self-test failed: inactive asset was accepted")
        (disposable / "pyproject.toml").write_text('version = "1.0.0"\n', encoding="utf-8")
        (disposable / "src/xray/__init__.py").write_text('__version__ = "1.0.1"\n', encoding="utf-8")
        (disposable / "uv.lock").write_text(
            '[[package]]\nname = "xray"\nversion = "1.0.0"\n', encoding="utf-8"
        )
        if not release_version_problems(disposable):
            raise SystemExit("self-test failed: mismatched release identity was accepted")

    print(f"validated {len(cases) + 3} disposable readiness negatives")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", nargs="?")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    root = resolve_target(args.target)

    if args.self_test:
        self_test(root)
        return

    profile = read_required(root, Path("PROJECT.md"))
    architecture = read_required(root, Path("ARCHITECTURE.md"))
    problems = readiness_problems(profile, architecture, root) + release_version_problems(root)
    if problems:
        raise SystemExit("XRAY project is not ready:\n" + "\n".join(f"- {problem}" for problem in problems))
    print("validated XRAY project readiness facts; no product qualification or delivery claim")


if __name__ == "__main__":
    main()
