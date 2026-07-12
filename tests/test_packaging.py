import importlib.metadata
import importlib.util
import json
import re
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import tomllib

ROOT = Path(__file__).parents[1]


def load_config_generator():
    module_path = ROOT / "mcp-config-generator.py"
    spec = importlib.util.spec_from_file_location("mcp_config_generator", module_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_project_metadata_is_cli_first_with_mcp_compatibility():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]

    assert "CLI" in project["description"]
    assert "MCP compatibility" in project["description"]
    assert "cli" in project["keywords"]
    assert "agents" in project["keywords"]
    assert project["scripts"]["xray"] == "xray.cli:main"
    assert project["scripts"]["xray-mcp"] == "xray.mcp_server:main"
    assert "pydantic>=2.0,<3" in project["dependencies"]
    assert "pyright>=1.1.407" in data["dependency-groups"]["dev"]
    assert "pytest>=9.0.0" in data["dependency-groups"]["dev"]
    assert "ruff>=0.14.0" in data["dependency-groups"]["dev"]
    assert "vulture>=2.14" in data["dependency-groups"]["dev"]


def test_quality_tooling_is_configured_for_repo_layout():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["tool"]["ruff"]["line-length"] == 120
    assert data["tool"]["ruff"]["target-version"] == "py310"
    assert "test_samples" in data["tool"]["ruff"]["extend-exclude"]
    assert data["tool"]["ruff"]["lint"]["select"] == ["E", "F", "I", "UP", "PL", "RUF"]
    assert data["tool"]["ruff"]["lint"]["per-file-ignores"]["tests/**/*"] == ["PLR2004", "E501"]
    assert data["tool"]["vulture"]["paths"] == ["src", "mcp-config-generator.py"]
    assert "test_samples" in data["tool"]["vulture"]["exclude"]
    assert data["tool"]["vulture"]["min_confidence"] == 80
    assert data["tool"]["pyright"]["include"] == [
        "src",
        "mcp-config-generator.py",
        "tests",
    ]
    assert "tests" not in data["tool"]["pyright"]["exclude"]
    assert data["tool"]["pyright"]["pythonVersion"] == "3.10"
    assert data["tool"]["pyright"]["typeCheckingMode"] == "standard"
    assert data["tool"]["pyright"]["strict"] == [
        "src/xray/models.py",
        "src/xray/core/ast_grep.py",
        "mcp-config-generator.py",
    ]
    assert data["tool"]["pyright"]["reportMissingTypeStubs"] is False


def test_fastmcp_dependency_requires_verified_modern_surface():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "fastmcp>=3.4.2,<4" in data["project"]["dependencies"]


def test_packaging_includes_mcp_skill_markdown():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["tool"]["setuptools"]["package-data"]["xray"] == ["skills/**/*"]


def test_top_level_cli_skill_is_agent_skills_compliant():
    skill_dir = ROOT / "skills" / "xray-cli"
    skill_path = skill_dir / "SKILL.md"

    assert skill_path.exists()
    assert not (ROOT / "skills" / "XRAY-CLI").exists()
    assert not (skill_dir / "skill.md").exists()

    content = skill_path.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    frontmatter, body = content.split("---\n", 2)[1:]
    metadata = {}
    for line in frontmatter.splitlines():
        key, value = line.split(": ", 1)
        metadata[key] = value.strip('"')

    assert metadata["name"] == skill_dir.name
    assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", metadata["name"])
    assert 1 <= len(metadata["description"]) <= 1024
    assert "xray explore" in body
    assert "xray find" in body
    assert "xray interface" in body
    assert "xray impact" in body
    assert "xray search" in body
    assert "xray rewrite ROOT -p 'old_api($ARG)' -r 'new_api($ARG)' -l python" in body
    assert "pass `-l/--lang` whenever the target language is known" in body
    assert "xray scan" in body
    assert "xray imports" in body
    assert "xray exports" in body
    assert "Do not request YAML" in body


def test_mcp_server_imports_with_verified_fastmcp_surface():
    from xray import mcp_server

    version = tuple(int(part) for part in importlib.metadata.version("fastmcp").split(".")[:3])

    assert (3, 4, 2) <= version < (4, 0, 0)
    assert mcp_server.mcp.name == "XRAY Code Intelligence"
    assert callable(mcp_server.main)


def test_readme_documents_generated_cli_decision():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "FastMCP's `generate-cli` can generate an ad hoc client" in readme
    assert "XRAY does not ship that generated script as its primary CLI" in readme
    assert "The `xray` command is the supported user-facing CLI" in readme
    assert "**Source checkout**" in readme
    assert "**Installed uv tool**" in readme
    assert "uv tool install ." in readme
    assert "mcp-config-generator.py cursor installed_script" in readme
    assert "mcp-config-generator.py vscode installed_script" in readme
    assert "[mcp_servers.xray]" in readme
    assert '"command": "xray-mcp"' in readme
    assert '"mcpServers": {' in readme
    assert '"xray": {' in readme
    assert "source-checkout configuration" in readme


def test_readme_documents_current_installation_and_cli_contract():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized_readme = " ".join(readme.split())

    assert "https://github.com/PhilosophiMoonbeam/xray.git" in readme
    assert "`fastmcp>=3.4.2,<4`" in readme
    assert "`ast-grep-cli>=0.44.1`" in readme
    assert "no separate installation is normally required" in normalized_readme
    assert "JSON symbols include `name`" in readme
    assert "`rewrite` and `scan --fix` modify files in place" in readme
    assert "Exit codes are `0` for success" in readme
    assert "symbols.json" in readme
    assert "symbols.pkl" not in readme
    assert "Interface reads use ast-grep's expanded outline" in readme


def test_getting_started_documents_search_first_mcp_usage():
    guide = (ROOT / "getting_started.md").read_text(encoding="utf-8")

    assert "XRAY's MCP server uses a search-first FastMCP surface" in guide
    assert "`search_tools` - find XRAY operations" in guide
    assert "`call_tool` - run the discovered operation" in guide
    assert "Resource: `xray://workflow`" in guide
    assert "FastMCP can generate an ad hoc CLI" in guide
    assert "What code references PaymentProcessor before I change it?" in guide
    assert "Find likely symbol-name code references for impact review" in guide
    assert "What function is defined at line 125" not in guide


def test_package_fallback_version_matches_pyproject():
    from xray import __version__

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert __version__ == data["project"]["version"]


def test_mcp_config_generator_uses_uv_for_local_python_configs():
    generator = load_config_generator()

    cursor = generator.CONFIGS["cursor"]["local_python"]["mcpServers"]["xray"]
    claude = generator.CONFIGS["claude"]["local_python"]["mcpServers"]["xray"]
    vscode = generator.CONFIGS["vscode"]["local_python"]["mcp"]["servers"]["xray"]

    assert cursor == {"command": "uv", "args": ["run", "python", "-m", "xray.mcp_server"]}
    assert claude == {"command": "uv", "args": ["run", "python", "-m", "xray.mcp_server"]}
    assert vscode["command"] == "uv"
    assert vscode["args"] == ["run", "python", "-m", "xray.mcp_server"]


def test_mcp_config_generator_preserves_installed_xray_mcp_command():
    generator = load_config_generator()

    for tool, path in [
        ("cursor", ("mcpServers", "xray")),
        ("claude", ("mcpServers", "xray")),
        ("vscode", ("mcp", "servers", "xray")),
    ]:
        buffer = StringIO()
        with redirect_stdout(buffer):
            assert generator.print_config(tool, "installed_script") is True

        output = buffer.getvalue()
        json_start = output.index("{")
        json_end = output.rindex("}") + 1
        config = json.loads(output[json_start:json_end])
        selected = config
        for key in path:
            selected = selected[key]
        assert selected["command"] == "xray-mcp"


def test_documented_generator_commands_are_supported():
    generator = load_config_generator()

    with redirect_stdout(StringIO()):
        assert generator.print_config("cursor", "local_python") is True
        assert generator.print_config("claude", "docker") is True
        assert generator.print_config("claude", "installed_script") is True
        assert generator.print_config("vscode", "source") is True
