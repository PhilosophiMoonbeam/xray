#!/usr/bin/env python3
"""Validate objective invariants of XRAY's adapted Codex control plane."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import tomllib

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path(".codex/config.toml")
HOOKS = Path(".codex/hooks.json")
CLAUDE = Path(".claude/settings.json")
ROLES = {
    "sol_design": ("gpt-5.6-sol", "high"),
    "sol_write": ("gpt-5.6-sol", "high"),
    "breakthrough_read": ("gpt-5.6-sol", "xhigh"),
    "luna_read": ("gpt-5.6-luna", "max"),
    "luna_write": ("gpt-5.6-luna", "max"),
    "terra_verify": ("gpt-5.6-terra", "high"),
}
ROLE_HASHES = {
    "breakthrough_read": "f0c8475387b0f8480353396818805293007aeb4b933682d79284abb9425f276e",
    "luna_read": "e744ed380b91f420e943beac3ab9eaee6e1a3c84b975059bd461b06289c0a730",
    "luna_write": "90e31a0ad9eaa7753a6cba32f510694cc61eaf6f954ca9d5c95c6eb90a5696b1",
    "sol_design": "2936ac5c06af4472fa88fbcc78bf14d3336e1fb8de73fbf7945960083201ef38",
    "sol_write": "6ed26a090e514983340a6ed340a7317336fb721ee2d953a85097cb971a422d44",
    "terra_verify": "1314e94aba1d1f9cdaa8ac8fe99d2ce0e3e64fd65e8da8af2406ca07cc6d3fdd",
}
BYTE_INVARIANTS = {
    Path(".agents/skills/beads/agents/openai.yaml"): (
        "7748b82a366f6475ef784ccb0b47fab4fd48b3da06148eaccc6455b0ea1fc3d0"
    ),
    Path("examples/assignment-contracts.md"): "c1f74f994475d43814da986d76786b13db69727df86a1aed9405106003a2ca5c",
    Path("examples/beads-dag.md"): "4d93442f678a36d5af93becfd32309b6bcded98124f199b2d484388f3fe037b1",
    Path("examples/nested-AGENTS.md"): "89bb948cbb11dfb1c7563fce2c3fc16874ac644184effc4f6b82d2686b2eeced",
}
ROOT_KEYS = {
    "model",
    "model_reasoning_effort",
    "sandbox_mode",
    "approval_policy",
    "web_search",
    "features",
    "agents",
}
ROLE_KEYS = {
    "name",
    "description",
    "model",
    "model_reasoning_effort",
    "sandbox_mode",
    "approval_policy",
    "web_search",
    "developer_instructions",
    "agents",
}
ROLE_PATH_PARTS = 3
ROLE_WORD_BUDGET = 1160
ROLE_BYTE_BUDGET = 9250
AUTOMATION_BYTE_BUDGET = 35000
DIGEST_FIELD_COUNT = 2
TRAILING_WHITESPACE_EVIDENCE = {Path("docs/adoption-design-packet-v1.md")}
DESIGN_PACKETS = {Path(f"docs/adoption-design-packet-v{version}.md") for version in (1, 2)}
INDEX_TARGETS = {
    "PROJECT.md",
    "ARCHITECTURE.md",
    "docs/repository-language-standard.md",
    "docs/implementation-standard.md",
    "docs/agent-model-routing.md",
    "docs/agent-operations.md",
    "docs/adoption-design-packet-v2.md",
    "docs/ADAPTATION.md",
    "TEMPLATE_MANIFEST.md",
    "README.md",
}
REQUIRED_FILES = {
    Path("AGENTS.md"),
    Path("PROJECT.md"),
    Path("ARCHITECTURE.md"),
    Path("README.md"),
    Path("TEMPLATE_MANIFEST.md"),
    Path(".gitignore"),
    CONFIG,
    HOOKS,
    Path(".codex/session_start.py"),
    Path(".agents/skills/beads/SKILL.md"),
    Path(".agents/skills/beads/agents/openai.yaml"),
    CLAUDE,
    *DESIGN_PACKETS,
    *(packet.with_suffix(".sha256") for packet in DESIGN_PACKETS),
    Path("docs/ADAPTATION.md"),
    Path("docs/agent-model-routing.md"),
    Path("docs/agent-operations.md"),
    Path("docs/implementation-standard.md"),
    Path("docs/repository-language-standard.md"),
    Path("docs/instruction-transformation-evidence.md"),
    *BYTE_INVARIANTS,
    *(Path(f".codex/agents/{name}.toml") for name in ROLES),
}
MANIFEST_TARGETS = {
    "AGENTS.md",
    "PROJECT.md",
    "ARCHITECTURE.md",
    "docs/adoption-design-packet-v1.md",
    "docs/adoption-design-packet-v1.sha256",
    "docs/adoption-design-packet-v2.md",
    "docs/adoption-design-packet-v2.sha256",
    ".codex/config.toml",
    ".codex/agents/*.toml",
    ".codex/hooks.json",
    ".codex/session_start.py",
    ".codex/validate_agents.py",
    ".codex/validate_project_readiness.py",
    ".agents/skills/beads/SKILL.md",
    ".agents/skills/beads/agents/openai.yaml",
    "docs/ADAPTATION.md",
    "docs/agent-model-routing.md",
    "docs/agent-operations.md",
    "docs/implementation-standard.md",
    "docs/repository-language-standard.md",
    "docs/instruction-transformation-evidence.md",
    "examples/assignment-contracts.md",
    "examples/beads-dag.md",
    "examples/nested-AGENTS.md",
    "Makefile",
    "README.md",
    ".gitignore",
    ".claude/settings.json",
    ".xray/xray.db*",
}
DELETED_RUNTIME = {
    Path(".codex/agent_lifecycle_hook.py"),
    Path(".codex/test_agent_lifecycle_hook.py"),
    Path(".codex/inspect_agent_runtime.py"),
    Path(".codex/test_inspect_agent_runtime.py"),
    Path(".codex/validate_language.py"),
    Path(".codex/validate_text.py"),
}
BUDGETS = {
    Path("AGENTS.md"): (1050, 8500),
    Path("PROJECT.md"): (1800, 14000),
    Path("ARCHITECTURE.md"): (2500, 20000),
    Path("README.md"): (2800, 22000),
    Path("TEMPLATE_MANIFEST.md"): (600, 5000),
    Path("docs/adoption-design-packet-v1.md"): (3300, 26000),
    Path("docs/adoption-design-packet-v2.md"): (1800, 14000),
    Path("docs/ADAPTATION.md"): (700, 5200),
    Path("docs/agent-model-routing.md"): (500, 3800),
    Path("docs/agent-operations.md"): (1200, 9000),
    Path("docs/implementation-standard.md"): (850, 6500),
    Path("docs/repository-language-standard.md"): (1000, 7500),
    Path("docs/instruction-transformation-evidence.md"): (1800, 13000),
    Path("examples/assignment-contracts.md"): (350, 2800),
    Path("examples/beads-dag.md"): (250, 1700),
    Path("examples/nested-AGENTS.md"): (180, 1400),
    CONFIG: (140, 1400),
    HOOKS: (75, 800),
    Path(".codex/session_start.py"): (900, 9000),
    Path(".agents/skills/beads/SKILL.md"): (150, 1200),
    Path(".agents/skills/beads/agents/openai.yaml"): (30, 300),
    Path("Makefile"): (180, 2200),
    Path(".codex/validate_agents.py"): (1800, 21000),
    Path(".codex/validate_project_readiness.py"): (525, 5800),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as source:
        return tomllib.load(source)


def configuration_problems(config: dict[str, Any], roles: dict[str, dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    if set(config) != ROOT_KEYS:
        problems.append("root config keys differ from the XRAY schema")
    expected_root = {
        "model": "gpt-5.6-sol",
        "model_reasoning_effort": "medium",
        "sandbox_mode": "danger-full-access",
        "approval_policy": "never",
        "web_search": "disabled",
        "features": {"multi_agent": True, "multi_agent_v2": True, "hooks": True},
    }
    for key, value in expected_root.items():
        if config.get(key) != value:
            problems.append(f"root {key} differs")

    agents = config.get("agents")
    if not isinstance(agents, dict):
        return [*problems, "agents table is missing"]
    scalars = {key: value for key, value in agents.items() if not isinstance(value, dict)}
    if scalars != {"max_concurrent_threads_per_session": 3, "interrupt_message": True}:
        problems.append("thread controls differ from the root-plus-three contract")
    registrations = {key: value for key, value in agents.items() if isinstance(value, dict)}
    if set(registrations) != set(ROLES):
        problems.append("registered role set differs")

    for name, (model, effort) in ROLES.items():
        registration = registrations.get(name, {})
        role = roles.get(name, {})
        if registration.get("config_file") != f"agents/{name}.toml":
            problems.append(f"{name}: config_file differs")
        if registration.get("description") != role.get("description"):
            problems.append(f"{name}: registration and role descriptions differ")
        if set(role) != ROLE_KEYS:
            problems.append(f"{name}: role keys differ from the XRAY schema")
        expected = {
            "name": name,
            "model": model,
            "model_reasoning_effort": effort,
            "sandbox_mode": "danger-full-access",
            "approval_policy": "never",
            "web_search": "disabled",
            "agents": {"enabled": False},
        }
        for key, value in expected.items():
            if role.get(key) != value:
                problems.append(f"{name}: {key} differs")
        instructions = role.get("developer_instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            problems.append(f"{name}: developer instructions are missing")
        elif "Do not" not in instructions or "Stop for" not in instructions or "Return" not in instructions:
            problems.append(f"{name}: contract, stop, or compact return instructions are missing")
    return problems


def expected_hook() -> dict[str, Any]:
    return {
        "description": "Recover XRAY Beads workflow and current work when a Codex session starts or compacts.",
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup|resume|clear|compact",
                    "hooks": [
                        {
                            "type": "command",
                            "command": 'uv run python "$(git rev-parse --show-toplevel)/.codex/session_start.py"',
                            "statusMessage": "Loading XRAY Beads workflow and current work",
                            "additionalContextLimit": 2500,
                            "timeout": 35,
                        }
                    ],
                }
            ]
        },
    }


def hook_problems(hooks: dict[str, Any], composer: str) -> list[str]:
    problems = [] if hooks == expected_hook() else ["SessionStart hook differs from the XRAY uv contract"]
    forbidden = ("PostCompact", "PreCompact", "UserPromptSubmit", "bd codex-hook")
    combined = json.dumps(hooks, sort_keys=True) + composer
    problems.extend(f"legacy hook behavior remains: {item}" for item in forbidden if item in combined)
    required = ("--readonly", 'Path.home() / ".beads-planning"', "COMMAND_TIMEOUT_SECONDS", "parse_items")
    problems.extend(f"session composer contract is missing: {item}" for item in required if item not in composer)
    if "/home/" in composer:
        problems.append("session composer contains a personal absolute path")
    return problems


def claude_problems(settings: dict[str, Any]) -> list[str]:
    expected = {
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [{"command": "bd --readonly prime --hook-json", "timeout": 35, "type": "command"}],
                    "matcher": "startup|resume|clear|compact",
                }
            ]
        }
    }
    return [] if settings == expected else ["Claude compatibility hook differs"]


def index_problems(text: str, root: Path) -> list[str]:
    targets = set(re.findall(r"\[[^]]+\]\(([^)#]+)", text))
    problems = [f"AGENTS index target is missing: {item}" for item in sorted(INDEX_TARGETS - targets)]
    for target in sorted(targets):
        if "://" not in target and not (root / target).exists():
            problems.append(f"AGENTS index target does not exist: {target}")
    return problems


def manifest_problems(text: str) -> list[str]:
    paths = set(re.findall(r"^\| `([^`]+)`", text, re.MULTILINE))
    return [f"manifest target is missing: {item}" for item in sorted(MANIFEST_TARGETS - paths)]


def inventory_problems(paths: set[Path]) -> list[str]:
    allowed_roles = {Path(f".codex/agents/{name}.toml") for name in ROLES}
    found_roles = {
        path for path in paths if len(path.parts) == ROLE_PATH_PARTS and path.parts[:2] == (".codex", "agents")
    }
    problems = [f"unregistered role instruction: {path}" for path in sorted(found_roles - allowed_roles)]
    problems.extend(f"deleted V1 runtime remains: {path}" for path in sorted(DELETED_RUNTIME & paths))
    return problems


def hygiene_problems(relative: Path, data: bytes) -> list[str]:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return [f"{relative}: text is not UTF-8"]
    problems: list[str] = []
    if b"\r\n" in data:
        problems.append(f"{relative}: CRLF line ending")
    if relative not in TRAILING_WHITESPACE_EVIDENCE:
        for number, line in enumerate(data.splitlines(), 1):
            if line.rstrip(b" \t") != line:
                problems.append(f"{relative}:{number}: trailing whitespace")
    if data and not data.endswith(b"\n"):
        problems.append(f"{relative}: missing final newline")
    return problems


def size(data: bytes) -> tuple[int, int]:
    return len(data.decode("utf-8").split()), len(data)


def exceeds_budget(current: tuple[int, int], limit: tuple[int, int]) -> bool:
    return current[0] > limit[0] or current[1] > limit[1]


def governed_paths(root: Path) -> list[Path]:
    paths = set(REQUIRED_FILES)
    paths.update(path for path in BUDGETS if (root / path).is_file())
    paths.update({Path(".codex/validate_agents.py"), Path(".codex/validate_project_readiness.py")})
    return sorted(path for path in paths if (root / path).is_file())


def budget_problems(root: Path) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    reports: list[str] = []
    for relative, limit in BUDGETS.items():
        path = root / relative
        if not path.is_file():
            continue
        current = size(path.read_bytes())
        reports.append(f"{relative}: words={current[0]}/{limit[0]} bytes={current[1]}/{limit[1]}")
        if exceeds_budget(current, limit):
            problems.append(f"size budget exceeded: {relative}")

    role_sizes = [size((root / f".codex/agents/{name}.toml").read_bytes()) for name in ROLES]
    role_words = sum(item[0] for item in role_sizes)
    role_bytes = sum(item[1] for item in role_sizes)
    reports.append(f"six roles: words={role_words}/{ROLE_WORD_BUDGET} bytes={role_bytes}/{ROLE_BYTE_BUDGET}")
    if role_words > ROLE_WORD_BUDGET or role_bytes > ROLE_BYTE_BUDGET:
        problems.append("six-role aggregate budget exceeded")

    automation_paths = (
        Path(".codex/session_start.py"),
        Path(".codex/validate_agents.py"),
        Path(".codex/validate_project_readiness.py"),
    )
    automation_bytes = sum((root / path).stat().st_size for path in automation_paths if (root / path).is_file())
    reports.append(f"Python automation: bytes={automation_bytes}/{AUTOMATION_BYTE_BUDGET}")
    if automation_bytes > AUTOMATION_BYTE_BUDGET:
        problems.append("Python automation aggregate budget exceeded")
    return problems, reports


def digest_problems(root: Path) -> list[str]:
    problems: list[str] = []
    for packet in DESIGN_PACKETS:
        companion = packet.with_suffix(".sha256")
        fields = (root / companion).read_text(encoding="utf-8").split()
        if len(fields) != DIGEST_FIELD_COUNT or fields[1] != packet.as_posix():
            problems.append(f"{companion}: digest format differs")
        elif fields[0] != sha256((root / packet).read_bytes()):
            problems.append(f"{companion}: digest is stale")
    return problems


def byte_invariant_problems(root: Path) -> list[str]:
    expected = dict(BYTE_INVARIANTS)
    expected.update({Path(f".codex/agents/{name}.toml"): digest for name, digest in ROLE_HASHES.items()})
    return [
        f"byte-invariant artifact differs: {path}"
        for path, digest in expected.items()
        if sha256((root / path).read_bytes()) != digest
    ]


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def repository_problems(root: Path = ROOT) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    missing = sorted(path for path in REQUIRED_FILES if not (root / path).is_file())
    problems.extend(f"required XRAY control-plane file is missing: {path}" for path in missing)
    if missing:
        return problems, []

    paths = {path.relative_to(root) for path in (root / ".codex").rglob("*") if path.is_file()}
    problems.extend(inventory_problems(paths))
    try:
        config = read_toml(root / CONFIG)
        roles = {name: read_toml(root / f".codex/agents/{name}.toml") for name in ROLES}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        problems.append(f"TOML configuration is malformed or unreadable: {exc}")
    else:
        problems.extend(configuration_problems(config, roles))
    try:
        hooks = load_json(root / HOOKS)
        claude = load_json(root / CLAUDE)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        problems.append(f"hook JSON is malformed or unreadable: {exc}")
    else:
        composer = (root / ".codex/session_start.py").read_text(encoding="utf-8")
        problems.extend(hook_problems(hooks, composer))
        problems.extend(claude_problems(claude))
    problems.extend(index_problems((root / "AGENTS.md").read_text(encoding="utf-8"), root))
    problems.extend(manifest_problems((root / "TEMPLATE_MANIFEST.md").read_text(encoding="utf-8")))
    problems.extend(digest_problems(root))
    problems.extend(byte_invariant_problems(root))
    for relative in governed_paths(root):
        problems.extend(hygiene_problems(relative, (root / relative).read_bytes()))
    size_failures, reports = budget_problems(root)
    problems.extend(size_failures)
    return problems, reports


def self_test() -> None:
    config = read_toml(ROOT / CONFIG)
    roles = {name: read_toml(ROOT / f".codex/agents/{name}.toml") for name in ROLES}
    hooks = load_json(ROOT / HOOKS)
    composer = (ROOT / ".codex/session_start.py").read_text(encoding="utf-8")
    failures: list[str] = []
    cases: list[tuple[str, list[str]]] = []

    wrong_model = copy.deepcopy(roles)
    wrong_model["luna_read"]["model"] = "wrong"
    cases.append(("wrong model", configuration_problems(config, wrong_model)))
    wrong_effort = copy.deepcopy(roles)
    wrong_effort["sol_design"]["model_reasoning_effort"] = "low"
    cases.append(("wrong effort", configuration_problems(config, wrong_effort)))
    wrong_role = copy.deepcopy(config)
    del wrong_role["agents"]["terra_verify"]
    cases.append(("wrong role", configuration_problems(wrong_role, roles)))
    v1_lifecycle = copy.deepcopy(config)
    v1_lifecycle["features"]["multi_agent_v2"] = False
    cases.append(("V2 replacement disabled", configuration_problems(v1_lifecycle, roles)))
    descendants = copy.deepcopy(roles)
    descendants["terra_verify"]["agents"]["enabled"] = True
    cases.append(("descendants enabled", configuration_problems(config, descendants)))
    permissions = copy.deepcopy(config)
    permissions["approval_policy"] = "on-request"
    cases.append(("wrong permissions", configuration_problems(permissions, roles)))
    thread_limit = copy.deepcopy(config)
    thread_limit["agents"]["max_concurrent_threads_per_session"] = 5
    cases.append(("wrong thread limit", configuration_problems(thread_limit, roles)))
    wrong_hook = copy.deepcopy(hooks)
    wrong_hook["hooks"]["UserPromptSubmit"] = []
    cases.append(("wrong hook", hook_problems(wrong_hook, composer)))
    cases.append(("missing index", index_problems("# empty\n", ROOT)))
    cases.append(("wrong inventory", inventory_problems({Path(".codex/agents/unknown.toml")})))
    cases.append(("deleted V1 runtime", inventory_problems({next(iter(DELETED_RUNTIME))})))
    cases.append(("wrong manifest", manifest_problems("| Path | Action |\n")))

    for name, result in cases:
        if not result:
            failures.append(f"self-test missed {name}")
    if not hygiene_problems(Path("sample.md"), b"bad \r\n"):
        failures.append("self-test missed encoding/text hygiene")
    if not hygiene_problems(Path("sample.md"), b"\xff"):
        failures.append("self-test missed invalid UTF-8")
    if not exceeds_budget((2, 2), (1, 1)):
        failures.append("self-test missed size budget")
    for name, parser, sample in (("TOML", tomllib.loads, "["), ("JSON", json.loads, "{")):
        try:
            parser(sample)
        except (tomllib.TOMLDecodeError, json.JSONDecodeError):
            continue
        failures.append(f"self-test accepted malformed {name}")
    if failures:
        raise SystemExit("XRAY validator self-test failed:\n" + "\n".join(failures))
    print(f"validated {len(cases) + 5} XRAY control-plane negative cases")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    problems, reports = repository_problems()
    if problems:
        raise SystemExit("invalid XRAY Codex control plane:\n" + "\n".join(problems))
    print("validated XRAY Codex control plane")
    for report in reports:
        print(report)


if __name__ == "__main__":
    main()
