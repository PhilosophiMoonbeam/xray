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

    assert project["version"] == "0.11.4"
    assert "CLI" in project["description"]
    assert "MCP compatibility" in project["description"]
    assert "cli" in project["keywords"]
    assert "agents" in project["keywords"]
    assert project["scripts"]["xray"] == "xray.cli:main"
    assert project["scripts"]["xray-mcp"] == "xray.mcp_server:main"
    assert "ast-grep-cli>=0.45.1,<0.46" in project["dependencies"]
    assert "ast-grep-py>=0.45.1,<0.46" in project["dependencies"]
    assert "pydantic>=2.0,<3" in project["dependencies"]
    assert "pathspec>=0.12,<1" in project["dependencies"]
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
    assert "PLR0917" in data["tool"]["ruff"]["lint"]["ignore"]
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

    assert "fastmcp>=3.4.7,<4" in data["project"]["dependencies"]


def test_packaging_includes_mcp_and_agent_skill_data():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["tool"]["setuptools"]["package-data"]["xray"] == ["skills/**/*", "agent_skills/**/*"]


def test_packaged_cli_skill_exactly_matches_repository_source():
    source = ROOT / "skills" / "xray-cli"
    packaged = ROOT / "src" / "xray" / "agent_skills" / "xray-cli"

    source_files = {path.relative_to(source) for path in source.rglob("*") if path.is_file()}
    packaged_files = {path.relative_to(packaged) for path in packaged.rglob("*") if path.is_file()}

    assert source_files == packaged_files == {Path("SKILL.md"), Path("agents/openai.yaml")}
    for relative in source_files:
        assert (packaged / relative).read_bytes() == (source / relative).read_bytes()


def test_packaged_mcp_skill_is_current_and_token_bounded():
    content = (ROOT / "src" / "xray" / "skills" / "xray-progressive-discovery" / "SKILL.md").read_text(encoding="utf-8")

    assert "ranks natural intent" in content
    assert '`mode="regex"`' in content
    assert "read_interface_structured" in content
    assert "read_symbol" in content
    assert "symbol_at" in content
    assert "xray_capabilities" in content
    assert "apply_rule_fixes" in content
    assert "`scan_rules`, `check_rules`," in content
    assert "plan_replacement" in content
    assert "refine_replacement" in content
    assert "verify_replacement" in content
    assert "apply_replacement" in content
    assert "xray.replace.v2" in content
    assert "`isError=true`" in content
    assert "YAML is ast-grep rule/test input, never XRAY output" in content
    assert "Pass `lang` when known" in content
    assert len(content.split()) <= 500
    assert len(content.encode()) <= 3600


def test_top_level_cli_skill_is_agent_skills_compliant():
    skill_dir = ROOT / "skills" / "xray-cli"
    skill_path = skill_dir / "SKILL.md"
    openai_path = skill_dir / "agents" / "openai.yaml"

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
    assert "xray read-symbol" in body
    assert "xray symbol-at" in body
    assert "xray impact" in body
    assert "xray search" in body
    assert "xray replace plan ROOT" in body
    assert "xray replace refine ROOT" in body
    assert "xray replace verify ROOT" in body
    assert "xray replace apply ROOT" in body
    assert ".edit_manifest[].edit_id" in body
    assert "xray.replace.v2" in body
    assert "REVIEWED_DIGEST" in body
    assert "Legacy `rewrite` and `scan --fix` remain destructive" in body
    assert "Pass `-l/--lang` for pattern mutations when known" in body
    assert "xray scan" in body
    assert "xray rules check" in body
    assert "xray rules explain" in body
    assert "xray rules test" in body
    assert "xray capabilities" in body
    assert "xray imports" in body
    assert "xray exports" in body
    assert "never XRAY output" in body
    assert "total_exact: false" in body
    assert "reporting, not edits" in body
    assert "`find` defaults to `min_score: 60`" in body
    assert "`--detail full` preserves v1" in body
    assert "symbol_mismatch" in body
    assert "page may use a different positive size" in body
    assert "inspection_lines" in body
    assert "rollback_attempted" in body
    assert "rollback_status" in body
    assert "explicitly selected hidden path" in body
    assert len(content.split()) <= 500
    assert len(content.encode()) <= 3600

    openai = openai_path.read_text(encoding="utf-8")
    assert "$xray-cli" in openai
    assert "guarded structural changes" in openai
    assert len(openai.encode()) <= 256


def test_mcp_server_imports_with_verified_fastmcp_surface():
    from xray import mcp_server

    version = tuple(int(part) for part in importlib.metadata.version("fastmcp").split(".")[:3])

    assert (3, 4, 7) <= version < (4, 0, 0)
    assert mcp_server.mcp.name == "XRAY Code Intelligence"
    assert callable(mcp_server.main)


def test_mcp_entrypoint_forces_documented_stdio_transport(monkeypatch):
    from xray import mcp_server

    calls = []
    monkeypatch.setattr(mcp_server.mcp, "run", lambda **kwargs: calls.append(kwargs))

    mcp_server.main()

    assert calls == [{"transport": "stdio"}]


def test_readme_documents_generated_cli_decision():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "FastMCP's `generate-cli` can generate an ad hoc client" in readme
    assert "XRAY does not ship that generated script as its primary CLI" in readme
    assert "The `xray` command is the supported user-facing CLI" in readme
    assert "**Source checkout**" in readme
    assert "**Installed uv tool**" in readme
    assert "uv tool install ." in readme
    assert "xray skill install --user" in readme
    assert "xray skill install --project /path/to/project" in readme
    assert "does not forward arbitrary" in readme
    assert "`search_tools` ranks natural intent by default" in readme
    assert "xray replace verify ROOT" in readme
    assert ".edit_manifest[].edit_id" in readme
    assert "`symbol-at`/`symbol_at` resolves" in readme
    assert "`xray skill install` is intentionally CLI-only" in readme
    assert "`xray-mcp` fixes the FastMCP transport to stdio" in readme
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
    assert "`fastmcp>=3.4.7,<4`" in readme
    assert "`ast-grep-cli>=0.45.1,<0.46`" in readme
    assert "`ast-grep-py>=0.45.1,<0.46`" in readme
    assert "`pathspec>=0.12,<1`" in readme
    assert "no separate installation is normally required" in normalized_readme
    assert "JSON symbols include `name`" in readme
    assert "`rewrite` and `scan --fix` modify files in place" in readme
    assert "Exit codes are `0` for success" in readme
    assert "symbols.json" in readme
    assert "symbols.pkl" not in readme
    assert "Python interface reads use the standard-library AST" in readme
    assert "xray replace plan ROOT" in readme
    assert '--expected-digest "$reviewed_digest"' in readme
    assert "plan_replacement" in readme
    assert "apply_replacement" in readme


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
