import json
import io
import asyncio
import subprocess
import sys
import tomllib
from pathlib import Path
from unittest.mock import patch

from xray import mcp_server
from xray import cli


def write_sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    src = repo / "src"
    src.mkdir(parents=True)
    (src / "sample.py").write_text(
        """
def target_function(value):
    return value + 1


def caller():
    return target_function(41)


class SampleService:
    pass
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return repo


def test_explore_cli_prints_tree(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["explore", str(repo), "--max-depth", "2", "--include-symbols"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "sample.py" in output
    assert "def target_function(value):" in output
    assert "class SampleService:" in output


def test_interface_cli_prints_file_skeleton(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["interface", str(repo), "src/sample.py"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "def target_function(value):" in output
    assert "def caller():" in output


def test_interface_cli_rejects_absolute_path_outside_root(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("def leaked():\n    pass\n", encoding="utf-8")

    exit_code = cli.main(["interface", str(repo), str(outside), "--format", "json"])

    assert exit_code == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert result["interface"] is None
    assert result["error"].startswith("Error reading interface:")
    assert "outside repository root" in result["error"]


def test_interface_cli_rejects_parent_traversal_outside_root(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("def leaked():\n    pass\n", encoding="utf-8")

    exit_code = cli.main(["interface", str(repo), "../outside.py"])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "Error reading interface:" in output
    assert "outside repository root" in output
    assert "def leaked" not in output


def test_interface_cli_rejects_symlink_file_outside_root(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("def leaked():\n    pass\n", encoding="utf-8")
    linked = repo / "src" / "linked.py"
    linked.symlink_to(outside)

    exit_code = cli.main(["interface", str(repo), "src/linked.py", "--format", "json"])

    assert exit_code == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert "outside repository root" in result["error"]
    assert "def leaked" not in result["error"]


def test_mcp_read_interface_preserves_string_error_for_outside_root(tmp_path):
    repo = write_sample_repo(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("def leaked():\n    pass\n", encoding="utf-8")

    result = mcp_server.read_interface(str(repo), str(outside))

    assert isinstance(result, str)
    assert result.startswith("Error reading interface:")
    assert "outside repository root" in result
    assert "def leaked" not in result


def test_explore_json_does_not_traverse_symlinked_directory_outside_root(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("def leaked():\n    pass\n", encoding="utf-8")
    (repo / "src" / "outside_link").symlink_to(outside, target_is_directory=True)

    exit_code = cli.main(["explore", str(repo), "--focus", "src", "--max-depth", "3", "--format", "json"])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    paths = {entry["path"] for entry in result["entries"]}
    assert "src/outside_link" not in paths
    assert all("secret.py" not in path for path in paths)


def test_find_cli_prints_json_symbols(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["find", str(repo), "target", "--limit", "3"])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schema_version"] == "xray.cli.v1"
    assert result["ok"] is True
    assert result["command"] == "find"
    assert result["query"] == "target"
    assert result["limit"] == 3
    assert any(symbol["name"] == "target_function" for symbol in result["symbols"])
    assert all("score" in symbol for symbol in result["symbols"])
    assert all("abs_path" in symbol for symbol in result["symbols"])
    assert all(not Path(symbol["path"]).is_absolute() for symbol in result["symbols"])
    assert all(symbol["start_line"] >= 1 for symbol in result["symbols"])


def test_find_cli_filters_by_min_score(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["find", str(repo), "definitely_not_present", "--min-score", "95"])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["min_score"] == 95
    assert result["symbols"] == []


def test_find_cli_reports_missing_ast_grep_as_json_error(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    def fake_run(cmd, *args, **kwargs):
        if cmd[0] == "git":
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")
        raise FileNotFoundError

    with patch("xray.core.indexer.subprocess.run", side_effect=fake_run):
        exit_code = cli.main(["find", str(repo), "target"])

    assert exit_code == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert result["error"] == "Symbol search failed."
    assert "ast-grep executable was not found" in result["warnings"][0]


def test_find_cli_reports_ast_grep_nonzero_as_json_error(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    failed = subprocess.CompletedProcess(
        args=["ast-grep"],
        returncode=2,
        stdout="",
        stderr="parser failed",
    )

    def fake_run(cmd, *args, **kwargs):
        if cmd[0] == "git":
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")
        return failed

    with patch("xray.core.indexer.subprocess.run", side_effect=fake_run):
        exit_code = cli.main(["find", str(repo), "target"])

    assert exit_code == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert "parser failed" in result["warnings"][0]


def test_find_cli_keeps_success_when_results_exist_with_warnings(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    match = {
        "text": "def target_function(value):\n    return value + 1",
        "file": str(repo / "src" / "sample.py"),
        "range": {
            "start": {"line": 0},
            "end": {"line": 1},
        },
        "metaVariables": {
            "single": {
                "NAME": {"text": "target_function"}
            }
        },
    }
    successful = subprocess.CompletedProcess(
        args=["ast-grep"],
        returncode=0,
        stdout=json.dumps([match]),
        stderr="",
    )
    failed = subprocess.CompletedProcess(
        args=["ast-grep"],
        returncode=2,
        stdout="",
        stderr="one pattern failed",
    )

    ast_grep_results = iter([successful])

    def fake_run(cmd, *args, **kwargs):
        if cmd[0] == "git":
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")
        return next(ast_grep_results, failed)

    with patch("xray.core.indexer.subprocess.run", side_effect=fake_run):
        exit_code = cli.main(["find", str(repo), "target"])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["symbols"][0]["name"] == "target_function"
    assert result["warnings"]


def test_find_cli_rejects_invalid_min_score(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["find", str(repo), "target", "--min-score", "101"])

    assert exit_code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["ok"] is False
    assert error["error"] == "--min-score must be between 0 and 100."


def test_find_cli_rejects_negative_limit(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["find", str(repo), "target", "--limit", "-1"])

    assert exit_code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"] == "--limit must be 0 or greater."


def test_impact_cli_accepts_manual_symbol_json(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    symbol = {
        "name": "target_function",
        "type": "function",
        "path": str(repo / "src" / "sample.py"),
        "start_line": 1,
        "end_line": 2,
    }

    exit_code = cli.main(["impact", str(repo), "--symbol-json", json.dumps(symbol)])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schema_version"] == "xray.cli.v1"
    assert result["command"] == "impact"
    assert result["impact"]["total_count"] >= 1
    assert any("sample.py" in reference["file"] for reference in result["impact"]["references"])


def test_impact_cli_reads_symbol_from_stdin(tmp_path, capsys, monkeypatch):
    repo = write_sample_repo(tmp_path)
    symbol = {
        "name": "target_function",
        "type": "function",
        "path": str(repo / "src" / "sample.py"),
        "start_line": 1,
        "end_line": 2,
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(symbol)))

    exit_code = cli.main(["impact", str(repo), "--symbol-file", "-"])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["impact"]["total_count"] >= 1


def test_impact_cli_accepts_relative_symbol_from_find_json(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    find_exit = cli.main(["find", str(repo), "target_function", "--limit", "1"])
    assert find_exit == 0
    found = json.loads(capsys.readouterr().out)["symbols"][0]

    impact_exit = cli.main(["impact", str(repo), "--symbol-json", json.dumps(found)])

    assert impact_exit == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["symbol"]["path"] == "src/sample.py"
    assert result["impact"]["total_count"] >= 1
    assert all(reference["line"] >= 1 for reference in result["impact"]["references"])


def test_mcp_what_breaks_accepts_cli_find_symbol_json(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    find_exit = cli.main(["find", str(repo), "target_function", "--limit", "1"])
    assert find_exit == 0
    found = json.loads(capsys.readouterr().out)["symbols"][0]

    result = mcp_server.what_breaks(found)

    assert "error" not in result
    assert result["total_count"] >= 1
    assert all(reference["line"] >= 1 for reference in result["references"])


def test_mcp_what_breaks_rejects_bare_relative_symbol_path():
    symbol = {
        "name": "target_function",
        "type": "function",
        "path": "src/sample.py",
        "start_line": 1,
        "end_line": 2,
    }

    result = mcp_server.what_breaks(symbol)

    assert result == {
        "error": "what_breaks requires an absolute symbol path or abs_path when called via MCP."
    }


def test_mcp_tool_surface_is_search_first_with_compact_metadata(tmp_path):
    repo = write_sample_repo(tmp_path)

    async def inspect_surface():
        from fastmcp import Client

        async with Client(mcp_server.mcp) as client:
            tools = await client.list_tools()
            search_result = await client.call_tool("search_tools", {"pattern": "impact"})
            call_result = await client.call_tool(
                "call_tool",
                {"name": "explore_repo", "arguments": {"root_path": str(repo), "max_depth": 1}},
            )
            return tools, search_result, call_result

    tools, search_result, call_result = asyncio.run(inspect_surface())

    assert [tool.name for tool in tools] == ["search_tools", "call_tool"]
    assert all("PROGRESSIVE DISCOVERY WORKFLOW" not in (tool.description or "") for tool in tools)
    matches = search_result.structured_content["result"]
    assert [match["name"] for match in matches] == ["what_breaks"]
    assert matches[0]["description"] == "Assess change impact by finding references to a returned symbol."
    assert matches[0]["inputSchema"]["properties"]["exact_symbol"]["description"].startswith("Full symbol object")
    assert call_result.structured_content["result"].startswith(str(repo))


def test_mcp_explore_reports_context_progress(tmp_path):
    repo = write_sample_repo(tmp_path)
    progress_events = []
    log_messages = []

    async def progress_handler(progress, total, message):
        progress_events.append((progress, total, message))

    async def log_handler(message):
        log_messages.append(message.data)

    async def call_explore():
        from fastmcp import Client

        async with Client(
            mcp_server.mcp,
            progress_handler=progress_handler,
            log_handler=log_handler,
        ) as client:
            search_result = await client.call_tool("search_tools", {"pattern": "map"})
            call_result = await client.call_tool(
                "call_tool",
                {"name": "explore_repo", "arguments": {"root_path": str(repo), "max_depth": 1}},
            )
            return search_result, call_result

    search_result, call_result = asyncio.run(call_explore())

    match = search_result.structured_content["result"][0]
    assert match["name"] == "explore_repo"
    assert "ctx" not in match["inputSchema"]["properties"]
    assert call_result.structured_content["result"].startswith(str(repo))
    assert progress_events == [
        (0.0, 2.0, "normalizing repository path"),
        (1.0, 2.0, "building repository map"),
        (2.0, 2.0, "repository map ready"),
    ]
    assert log_messages[0]["msg"].startswith("Exploring repository:")


def test_mcp_workflow_guidance_is_available_on_demand():
    async def inspect_guidance():
        from fastmcp import Client

        async with Client(mcp_server.mcp) as client:
            resources = await client.list_resources()
            templates = await client.list_resource_templates()
            prompts = await client.list_prompts()
            workflow = await client.read_resource("xray://workflow")
            skill = await client.read_resource("skill://xray-progressive-discovery/SKILL.md")
            prompt = await client.get_prompt("xray_discovery_plan", {"goal": "review impact"})
            return resources, templates, prompts, workflow, skill, prompt

    resources, templates, prompts, workflow, skill, prompt = asyncio.run(inspect_guidance())

    listed_resources = {(str(resource.uri), resource.name, resource.mimeType) for resource in resources}
    assert ("xray://workflow", "xray_workflow", "text/markdown") in listed_resources
    assert (
        "skill://xray-progressive-discovery/SKILL.md",
        "xray-progressive-discovery/SKILL.md",
        "text/markdown",
    ) in listed_resources
    assert any(str(template.uriTemplate) == "skill://xray-progressive-discovery/{path*}" for template in templates)
    assert [(prompt_def.name, prompt_def.description) for prompt_def in prompts] == [
        ("xray_discovery_plan", "Plan a compact XRAY discovery sequence for a code task.")
    ]
    assert workflow[0].text.startswith("# XRAY Progressive Discovery")
    assert "map -> find -> interface -> impact" in workflow[0].text
    assert skill[0].text.startswith("# XRAY Progressive Discovery")
    assert "search_tools" in skill[0].text
    prompt_text = prompt.messages[0].content.text
    assert prompt_text.startswith("Goal: review impact")
    assert "Fetch xray://workflow" in prompt_text


def test_impact_cli_rejects_absolute_symbol_path_outside_root(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("def leaked():\n    pass\n", encoding="utf-8")
    symbol = {
        "name": "leaked",
        "type": "function",
        "path": str(outside),
        "start_line": 1,
        "end_line": 2,
    }

    exit_code = cli.main(["impact", str(repo), "--symbol-json", json.dumps(symbol)])

    assert exit_code == 2
    result = json.loads(capsys.readouterr().err)
    assert result["ok"] is False
    assert "outside repository root" in result["error"]


def test_impact_cli_rejects_manual_symbol_without_start_line(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["impact", str(repo), "--name", "target_function", "--path", "src/sample.py"])

    assert exit_code == 2
    result = json.loads(capsys.readouterr().err)
    assert result["ok"] is False
    assert "Manual symbols require --start-line" in result["error"]


def test_impact_cli_rejects_missing_symbol_source(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["impact", str(repo)])

    assert exit_code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"] == "Provide exactly one symbol source: --symbol-json, --symbol-file, or --name with --path."


def test_map_alias_matches_explore(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["map", str(repo), "--max-depth", "1"])

    assert exit_code == 0
    assert "src" in capsys.readouterr().out


def test_explore_cli_rejects_negative_max_depth(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["explore", str(repo), "--max-depth", "-1", "--format", "json"])

    assert exit_code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["schema_version"] == "xray.cli.v1"
    assert error["ok"] is False
    assert error["error"] == "--max-depth must be 0 or greater."


def test_explore_cli_parse_error_returns_json_when_requested(capsys):
    exit_code = cli.main(["explore", ".", "--max-depth", "nope", "--format", "json"])

    assert exit_code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["schema_version"] == "xray.cli.v1"
    assert error["ok"] is False
    assert error["command"] == "explore"
    assert "invalid int value" in error["error"]


def test_find_cli_missing_argument_returns_text_error(capsys):
    exit_code = cli.main(["find", "."])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "xray find: error:" in captured.err
    assert "required" in captured.err


def test_find_cli_invalid_format_returns_text_error(capsys):
    exit_code = cli.main(["find", ".", "target", "--format", "xml"])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "xray find: error:" in captured.err
    assert "invalid choice" in captured.err


def test_cli_missing_command_returns_text_error(capsys):
    exit_code = cli.main([])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "xray: error:" in captured.err
    assert "required" in captured.err


def test_cli_version_returns_without_system_exit(capsys):
    exit_code = cli.main(["--version"])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "xray 0.6.1"


def test_explore_focus_keeps_root_and_focused_top_level_dir(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    (repo / "docs").mkdir()
    (repo / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")

    exit_code = cli.main(["explore", str(repo), "--focus", "src", "--max-depth", "2"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert str(repo) in output
    assert "src" in output
    assert "sample.py" in output
    assert "docs" not in output


def test_explore_json_includes_structured_entries(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main([
        "explore",
        str(repo),
        "--focus",
        "src",
        "--include-symbols",
        "--format",
        "json",
    ])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schema_version"] == "xray.cli.v1"
    assert result["ok"] is True
    assert result["command"] == "explore"
    assert result["invoked_as"] == "explore"
    assert result["root_path"] == str(repo)
    assert "tree_text" in result
    assert result["options"]["include_symbols"] is True
    entries = {entry["path"]: entry for entry in result["entries"]}
    assert entries["."]["kind"] == "directory"
    assert entries["src"]["kind"] == "directory"
    assert entries["src/sample.py"]["language"] == "python"
    assert entries["src/sample.py"]["abs_path"] == str(repo / "src" / "sample.py")
    assert any(symbol["signature"] == "def target_function(value):" for symbol in entries["src/sample.py"]["symbols"])


def test_map_json_uses_explore_command_with_invoked_alias(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["map", str(repo), "--format", "json"])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["command"] == "explore"
    assert result["invoked_as"] == "map"


def test_package_scripts_keep_mcp_and_add_cli():
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    assert data["project"]["scripts"]["xray"] == "xray.cli:main"
    assert data["project"]["scripts"]["xray-mcp"] == "xray.mcp_server:main"
