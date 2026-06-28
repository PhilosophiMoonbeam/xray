import importlib.util
import json
import importlib.metadata
import tomllib
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_config_generator():
    module_path = ROOT / "mcp-config-generator.py"
    spec = importlib.util.spec_from_file_location("mcp_config_generator", module_path)
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
    assert "pytest>=9.0.0" in data["dependency-groups"]["dev"]


def test_fastmcp_dependency_requires_verified_modern_surface():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "fastmcp>=3.4.2,<4" in data["project"]["dependencies"]


def test_packaging_includes_mcp_skill_markdown():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["tool"]["setuptools"]["package-data"]["xray"] == ["skills/**/*"]


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


def test_getting_started_documents_search_first_mcp_usage():
    guide = (ROOT / "getting_started.md").read_text(encoding="utf-8")

    assert "XRAY's MCP server uses a search-first FastMCP surface" in guide
    assert "`search_tools` - find XRAY operations" in guide
    assert "`call_tool` - run the discovered operation" in guide
    assert "Resource: `xray://workflow`" in guide
    assert "FastMCP can generate an ad hoc CLI" in guide


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
