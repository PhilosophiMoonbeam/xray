import asyncio
import io
import json
import pickle
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import tomllib

from xray import cli, mcp_server
from xray.core.ast_grep import AstGrepCommandError, AstGrepNotFoundError, AstGrepResult
from xray.core.indexer import XRayIndexer


def structured_content(result: Any) -> dict[str, Any]:
    content = result.structured_content
    assert content is not None
    return cast(dict[str, Any], content)


def text_content(value: Any) -> str:
    text = getattr(value, "text", None)
    assert isinstance(text, str)
    return text


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


def write_js_sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    src = repo / "src"
    src.mkdir(parents=True)
    (src / "sample.js").write_text(
        """
const fetchData = async (url) => {
    return url;
};

const helper = function(value) {
    return value * 2;
};
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return repo


def write_mixed_symbol_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    src = repo / "src"
    src.mkdir(parents=True)
    (src / "types.ts").write_text(
        """
enum Status {
    Active = "ACTIVE",
    Inactive = "INACTIVE",
}

type UserRole = "admin" | "user";
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (src / "types.go").write_text(
        """
package sample

type User struct {
    ID int
}

type Service interface {
    GetUser(id int) (*User, error)
}

type UserID int
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


def test_find_cli_finds_js_arrow_function_without_no_match_warnings(tmp_path, capsys):
    repo = write_js_sample_repo(tmp_path)

    exit_code = cli.main(["find", str(repo), "fetchData", "--limit", "3"])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["warnings"] == []
    assert result["symbols"][0]["name"] == "fetchData"


def test_find_cli_finds_js_function_expression(tmp_path, capsys):
    repo = write_js_sample_repo(tmp_path)

    exit_code = cli.main(["find", str(repo), "helper", "--limit", "3"])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["warnings"] == []
    assert result["symbols"][0]["name"] == "helper"


def test_find_cli_ranks_qualified_method_query_by_owner_context(tmp_path, capsys):
    repo = tmp_path / "repo"
    src = repo / "src" / "xray" / "core"
    src.mkdir(parents=True)
    (src / "indexer.py").write_text(
        """
class XRayIndexer:
    def find_symbol(self, query):
        return query
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (repo / "src" / "xray" / "mcp_server.py").write_text(
        """
def find_symbol(root_path, query):
    return query
""".strip()
        + "\n",
        encoding="utf-8",
    )

    exit_code = cli.main(["find", str(repo), "XRayIndexer.find_symbol", "--limit", "2"])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["symbols"][0]["name"] == "find_symbol"
    assert result["symbols"][0]["path"] == "src/xray/core/indexer.py"


def test_find_cli_finds_typescript_enum(tmp_path, capsys):
    repo = write_mixed_symbol_repo(tmp_path)

    exit_code = cli.main(["find", str(repo), "Status", "--min-score", "100", "--limit", "1"])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["symbols"][0]["name"] == "Status"
    assert result["symbols"][0]["type"] == "enum"


def test_find_cli_finds_go_type_alias(tmp_path, capsys):
    repo = write_mixed_symbol_repo(tmp_path)

    exit_code = cli.main(["find", str(repo), "UserID", "--min-score", "100", "--limit", "1"])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["symbols"][0]["name"] == "UserID"
    assert result["symbols"][0]["type"] == "type"


def test_indexer_cache_dir_is_scoped_by_root_path(tmp_path):
    repo_a = write_sample_repo(tmp_path / "a")
    repo_b = write_sample_repo(tmp_path / "b")
    completed = subprocess.CompletedProcess(
        args=["git", "rev-parse", "HEAD"],
        returncode=0,
        stdout="abc123\n",
        stderr="",
    )

    with patch("xray.core.indexer.subprocess.run", return_value=completed):
        indexer_a = XRayIndexer(str(repo_a))
        indexer_b = XRayIndexer(str(repo_b))

    assert indexer_a.cache_dir is not None
    assert indexer_b.cache_dir is not None
    assert indexer_a.cache_dir != indexer_b.cache_dir
    assert indexer_a.cache_dir.name.endswith("-abc123")
    assert indexer_b.cache_dir.name.endswith("-abc123")


def test_indexer_save_cache_writes_readable_pickle(tmp_path):
    repo = write_sample_repo(tmp_path)
    completed = subprocess.CompletedProcess(
        args=["git", "rev-parse", "HEAD"],
        returncode=0,
        stdout="def456\n",
        stderr="",
    )

    with patch("xray.core.indexer.subprocess.run", return_value=completed):
        indexer = XRayIndexer(str(repo))

    indexer._cache = {"sample": [{"signature": "def target_function(value):", "doc": ""}]}
    indexer._save_cache()

    assert indexer.cache_dir is not None
    cache_file = indexer.cache_dir / "symbols.pkl"
    with open(cache_file, "rb") as f:
        saved = pickle.load(f)

    assert saved == indexer._cache
    assert list(indexer.cache_dir.glob("tmp*")) == []


def test_find_cli_reports_missing_ast_grep_as_json_error(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    with patch(
        "xray.core.indexer.run_ast_grep",
        side_effect=AstGrepNotFoundError("ast-grep executable was not found; symbol search could not run."),
    ):
        exit_code = cli.main(["find", str(repo), "target"])

    assert exit_code == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert result["error"] == "Symbol search failed."
    assert "ast-grep executable was not found" in result["warnings"][0]


def test_find_cli_reports_ast_grep_nonzero_as_json_error(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    with patch(
        "xray.core.indexer.run_ast_grep",
        side_effect=AstGrepCommandError("ast-grep failed with exit code 2: parser failed"),
    ):
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
        "metaVariables": {"single": {"NAME": {"text": "target_function"}}},
    }
    successful = AstGrepResult(stdout=json.dumps([match]), stderr="", returncode=0)

    ast_grep_results = iter([successful])

    def fake_run(cmd, *args, **kwargs):
        try:
            return next(ast_grep_results)
        except StopIteration:
            raise AstGrepCommandError("ast-grep failed with exit code 2: one pattern failed")

    with patch("xray.core.indexer.run_ast_grep", side_effect=fake_run):
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


def test_impact_filters_duplicate_non_source_and_inexact_structural_matches(tmp_path):
    repo = write_sample_repo(tmp_path)
    (repo / "README.md").write_text("target_function in docs should not be an impact code hit.\n", encoding="utf-8")
    indexer = XRayIndexer(str(repo))
    valid_match = {
        "text": "target_function",
        "file": str(repo / "src" / "sample.py"),
        "range": {"start": {"line": 4}},
        "lines": "def caller():\n    return target_function(41)",
    }
    matches = [
        valid_match,
        dict(valid_match),
        {
            "text": "target_function",
            "file": str(repo / "README.md"),
            "range": {"start": {"line": 0}},
            "lines": "target_function in docs should not be an impact code hit.",
        },
        {
            "text": "_",
            "file": str(repo / "src" / "sample.py"),
            "range": {"start": {"line": 5}},
            "lines": "return helper(41)",
        },
        {
            "text": "target_function",
            "file": str(repo / "src" / "sample.py"),
            "range": {"start": {"line": 0}},
            "lines": "def target_function(value):",
        },
    ]

    with patch("xray.core.indexer.run_ast_grep", return_value=AstGrepResult(json.dumps(matches), "", 0)):
        result = indexer.what_breaks(
            {
                "name": "target_function",
                "type": "function",
                "path": str(repo / "src" / "sample.py"),
                "start_line": 1,
                "end_line": 2,
            }
        )

    assert result["strategy"] == "structural"
    assert result["total_count"] == 1
    assert result["raw_count"] == 5
    assert result["filtered_count"] == 4
    assert result["references"] == [
        {
            "file": str(repo / "src" / "sample.py"),
            "line": 5,
            "text": "def caller():\n    return target_function(41)",
            "type": "code",
        }
    ]


def test_impact_text_fallback_filters_to_source_and_excludes_definition(tmp_path):
    repo = write_sample_repo(tmp_path)
    (repo / "README.md").write_text("target_function in docs should not be an impact code hit.\n", encoding="utf-8")
    indexer = XRayIndexer(str(repo))

    with patch("xray.core.indexer.run_ast_grep", return_value=AstGrepResult("[]", "", 1, no_matches=True)):
        result = indexer.what_breaks(
            {
                "name": "target_function",
                "type": "function",
                "path": str(repo / "src" / "sample.py"),
                "start_line": 1,
                "end_line": 2,
            },
            context_lines=0,
        )

    assert result["strategy"] == "text"
    assert result["total_count"] == 1
    assert result["raw_count"] == 2
    assert result["filtered_count"] == 1
    assert result["references"][0]["file"] == str(repo / "src" / "sample.py")
    assert result["references"][0]["line"] == 6
    assert "target_function(41)" in result["references"][0]["text"]


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

    assert result == {"error": "what_breaks requires an absolute symbol path or abs_path when called via MCP."}


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
    matches = structured_content(search_result)["result"]
    assert [match["name"] for match in matches] == ["what_breaks"]
    assert matches[0]["description"].startswith("Find breaking change impact")
    assert matches[0]["inputSchema"]["properties"]["exact_symbol"]["description"].startswith("Full symbol object")
    assert structured_content(call_result)["result"].startswith(str(repo))


def test_mcp_search_first_transform_quality_and_structured_call_results(tmp_path):
    repo = write_sample_repo(tmp_path)
    (repo / ".git").mkdir()
    symbol = {
        "name": "target_function",
        "type": "function",
        "path": str(repo / "src" / "sample.py"),
        "start_line": 1,
        "end_line": 2,
    }

    async def inspect_search_and_calls():
        from fastmcp import Client

        async with Client(mcp_server.mcp) as client:
            searches = {
                term: structured_content(await client.call_tool("search_tools", {"pattern": term}))["result"]
                for term in [
                    "map",
                    "tree",
                    "find",
                    "function",
                    "class",
                    "interface",
                    "signature",
                    "contract",
                    "docstring",
                    "impact",
                    "usage",
                    "caller",
                    "dependency",
                    "overview",
                    "layout",
                    "file tree",
                    "definitions",
                    "method",
                    "type",
                    "enum",
                    "api",
                    "summary",
                    "body",
                    "uses",
                    "used by",
                    "dependencies",
                    "dependents",
                    "blast radius",
                    "breaking change",
                    "change impact",
                    "root path",
                    "line data",
                    ".",
                    "[",
                ]
            }
            calls = {
                "explore_repo": await client.call_tool(
                    "call_tool",
                    {"name": "explore_repo", "arguments": {"root_path": str(repo), "max_depth": 1}},
                ),
                "find_symbol": await client.call_tool(
                    "call_tool",
                    {"name": "find_symbol", "arguments": {"root_path": str(repo), "query": "target"}},
                ),
                "read_interface": await client.call_tool(
                    "call_tool",
                    {"name": "read_interface", "arguments": {"root_path": str(repo), "file_path": "src/sample.py"}},
                ),
                "what_breaks": await client.call_tool(
                    "call_tool",
                    {"name": "what_breaks", "arguments": {"exact_symbol": symbol}},
                ),
            }
            return searches, calls

    searches, calls = asyncio.run(inspect_search_and_calls())

    assert searches["map"][0]["name"] == "explore_repo"
    assert searches["tree"][0]["name"] == "explore_repo"
    assert searches["find"][0]["name"] == "find_symbol"
    assert any(match["name"] == "find_symbol" for match in searches["function"])
    assert any(match["name"] == "find_symbol" for match in searches["class"])
    assert searches["interface"][0]["name"] == "read_interface"
    assert searches["signature"][0]["name"] == "read_interface"
    assert searches["contract"][0]["name"] == "read_interface"
    assert searches["docstring"][0]["name"] == "read_interface"
    assert searches["impact"][0]["name"] == "what_breaks"
    assert searches["usage"][0]["name"] == "what_breaks"
    assert searches["caller"][0]["name"] == "what_breaks"
    assert searches["dependency"][0]["name"] == "what_breaks"
    assert searches["overview"][0]["name"] == "explore_repo"
    assert searches["layout"][0]["name"] == "explore_repo"
    assert searches["file tree"][0]["name"] == "explore_repo"
    assert searches["definitions"][0]["name"] == "find_symbol"
    assert searches["method"][0]["name"] == "find_symbol"
    assert searches["type"][0]["name"] == "find_symbol"
    assert searches["enum"][0]["name"] == "find_symbol"
    assert searches["api"][0]["name"] == "read_interface"
    assert searches["summary"][0]["name"] == "read_interface"
    assert searches["body"][0]["name"] == "read_interface"
    assert searches["uses"][0]["name"] == "what_breaks"
    assert searches["used by"][0]["name"] == "what_breaks"
    assert searches["dependencies"][0]["name"] == "what_breaks"
    assert searches["dependents"][0]["name"] == "what_breaks"
    assert searches["blast radius"][0]["name"] == "what_breaks"
    assert searches["breaking change"][0]["name"] == "what_breaks"
    assert searches["change impact"][0]["name"] == "what_breaks"
    assert {match["name"] for match in searches["root path"]} >= {
        "explore_repo",
        "find_symbol",
        "read_interface",
    }
    assert searches["line data"][0]["name"] == "what_breaks"
    assert [match["name"] for match in searches["."]] == [
        "explore_repo",
        "find_symbol",
        "read_interface",
        "what_breaks",
    ]
    assert searches["["] == []

    for matches in searches.values():
        assert len(matches) <= 10
        for match in matches:
            properties = match["inputSchema"]["properties"]
            assert "ctx" not in properties
            assert match["description"]
            assert match["annotations"] == {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            }
            assert all(property_schema.get("description") for property_schema in properties.values())

    assert structured_content(calls["explore_repo"])["result"].startswith(str(repo))
    assert any(
        symbol_result["name"] == "target_function"
        for symbol_result in structured_content(calls["find_symbol"])["result"]
    )
    assert "def target_function(value):" in structured_content(calls["read_interface"])["result"]
    impact = structured_content(calls["what_breaks"])
    assert impact["total_count"] >= 1
    assert all(reference["line"] >= 1 for reference in impact["references"])


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

    match = structured_content(search_result)["result"][0]
    assert match["name"] == "explore_repo"
    assert "ctx" not in match["inputSchema"]["properties"]
    assert structured_content(call_result)["result"].startswith(str(repo))
    assert progress_events == [
        (0.0, 2.0, "normalizing repository path"),
        (1.0, 2.0, "building repository map"),
        (2.0, 2.0, "repository map ready"),
    ]
    assert log_messages[0]["msg"].startswith("Exploring repository:")


def test_async_mcp_find_symbol_offloads_blocking_indexer(tmp_path, monkeypatch):
    repo = write_sample_repo(tmp_path)
    started = threading.Event()
    release = threading.Event()

    class FakeContext:
        async def info(self, message):
            pass

        async def report_progress(self, progress, total, message):
            pass

        async def error(self, message):
            pass

    def fake_run_indexer_operation(path, operation):
        started.set()
        if not release.wait(timeout=2):
            raise AssertionError("blocking operation was not released")
        return [
            {"name": "target_function", "path": str(repo / "src" / "sample.py"), "type": "function", "start_line": 1}
        ]

    monkeypatch.setattr(mcp_server, "run_indexer_operation", fake_run_indexer_operation)

    async def exercise():
        task = asyncio.create_task(mcp_server.find_symbol(str(repo), "target", cast(Any, FakeContext())))
        assert await asyncio.to_thread(started.wait, 1)
        result = await asyncio.wait_for(asyncio.sleep(0, result="event loop alive"), timeout=0.1)
        release.set()
        return result, await asyncio.wait_for(task, timeout=1)

    loop_probe, symbols = asyncio.run(exercise())

    assert loop_probe == "event loop alive"
    assert symbols[0]["name"] == "target_function"
    assert symbols[0]["type"] == "function"
    assert symbols[0]["start_line"] == 1


def test_mcp_concurrent_call_tool_requests_succeed_same_and_multi_root(tmp_path):
    repo_a = write_sample_repo(tmp_path / "a")
    repo_b = write_sample_repo(tmp_path / "b")
    (repo_a / ".git").mkdir()
    (repo_b / ".git").mkdir()

    def symbol_for(repo: Path) -> dict[str, object]:
        return {
            "name": "target_function",
            "type": "function",
            "path": str(repo / "src" / "sample.py"),
            "start_line": 1,
            "end_line": 2,
        }

    async def call_concurrently():
        from fastmcp import Client

        async with Client(mcp_server.mcp) as client:
            same_root = await asyncio.gather(
                client.call_tool(
                    "call_tool",
                    {"name": "explore_repo", "arguments": {"root_path": str(repo_a), "max_depth": 1}},
                ),
                client.call_tool(
                    "call_tool",
                    {"name": "find_symbol", "arguments": {"root_path": str(repo_a), "query": "target"}},
                ),
                client.call_tool(
                    "call_tool",
                    {"name": "read_interface", "arguments": {"root_path": str(repo_a), "file_path": "src/sample.py"}},
                ),
                client.call_tool(
                    "call_tool",
                    {"name": "what_breaks", "arguments": {"exact_symbol": symbol_for(repo_a)}},
                ),
            )
            multi_root = await asyncio.gather(
                client.call_tool(
                    "call_tool",
                    {"name": "find_symbol", "arguments": {"root_path": str(repo_a), "query": "target"}},
                ),
                client.call_tool(
                    "call_tool",
                    {"name": "find_symbol", "arguments": {"root_path": str(repo_b), "query": "target"}},
                ),
                client.call_tool(
                    "call_tool",
                    {"name": "explore_repo", "arguments": {"root_path": str(repo_a), "max_depth": 1}},
                ),
                client.call_tool(
                    "call_tool",
                    {"name": "explore_repo", "arguments": {"root_path": str(repo_b), "max_depth": 1}},
                ),
            )
            return same_root, multi_root

    same_root, multi_root = asyncio.run(call_concurrently())

    def payload(result):
        content = structured_content(result)
        return content.get("result", content)

    same_results = [payload(result) for result in same_root]
    assert same_results[0].startswith(str(repo_a))
    assert any(symbol["name"] == "target_function" for symbol in same_results[1])
    assert "def target_function(value):" in same_results[2]
    assert same_results[3]["total_count"] >= 1
    assert all("error" not in result for result in same_results[1:])

    multi_results = [payload(result) for result in multi_root]
    assert any(symbol["name"] == "target_function" for symbol in multi_results[0])
    assert any(symbol["name"] == "target_function" for symbol in multi_results[1])
    assert multi_results[2].startswith(str(repo_a))
    assert multi_results[3].startswith(str(repo_b))


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
    workflow_text = text_content(workflow[0])
    assert workflow_text.startswith("# XRAY Progressive Discovery")
    assert "map -> find -> interface -> impact" in workflow_text
    xray_workflow = next(resource for resource in resources if str(resource.uri) == "xray://workflow")
    annotations = xray_workflow.annotations
    assert annotations is not None
    assert getattr(annotations, "readOnlyHint") is True
    assert getattr(annotations, "idempotentHint") is True
    skill_text = text_content(skill[0])
    assert skill_text.startswith("# XRAY Progressive Discovery")
    assert "search_tools" in skill_text
    assert "signature" in skill_text
    assert "dependency" in skill_text
    prompt_text = text_content(prompt.messages[0].content)
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


def test_impact_cli_validates_symbol_json_with_pydantic(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["impact", str(repo), "--symbol-json", json.dumps({"path": "src/sample.py"})])

    assert exit_code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["ok"] is False
    assert "Symbol input field 'name'" in error["error"]


def test_mcp_what_breaks_validates_symbol_input():
    result = mcp_server.what_breaks({"path": "/tmp/sample.py"})

    assert result["error"].startswith("Error finding references: Symbol input field 'name'")


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


def test_cli_help_documents_agent_workflow_json_and_safety(capsys):
    root_exit = cli.main(["--help"])
    root_help = " ".join(capsys.readouterr().out.split())

    explore_exit = cli.main(["explore", "--help"])
    explore_help = " ".join(capsys.readouterr().out.split())

    find_exit = cli.main(["find", "--help"])
    find_help = " ".join(capsys.readouterr().out.split())

    interface_exit = cli.main(["interface", "--help"])
    interface_help = " ".join(capsys.readouterr().out.split())

    impact_exit = cli.main(["impact", "--help"])
    impact_help = " ".join(capsys.readouterr().out.split())

    assert root_exit == 0
    assert "Progressive workflow" in root_help
    assert "xray explore ROOT --max-depth 2" in root_help
    assert "jq -c '.symbols[0]'" in root_help
    assert "YAML is intentionally unsupported" in root_help
    assert explore_exit == 0
    assert "Start shallow" in explore_help
    assert "xray map ROOT --format json" in explore_help
    assert "invoked_as" in explore_help
    assert "YAML is not supported" in explore_help
    assert find_exit == 0
    assert "owner-qualified symbol path" in find_help
    assert "Symbols include path, abs_path, start_line, end_line, type, and score" in find_help
    assert "jq and impact handoff" in find_help
    assert interface_exit == 0
    assert "must resolve inside the root" in interface_help
    assert "rejects parent traversal and symlink escapes" in interface_help
    assert impact_exit == 0
    assert "Provide exactly one symbol source" in impact_help
    assert "required with --name and --path" in impact_help
    assert "--symbol-file -" in impact_help
    assert "CLI symbol paths must resolve inside ROOT" in impact_help
    assert "total_count, raw_count, filtered_count" in impact_help


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


def test_explore_cli_excludes_generated_and_agent_state_dirs(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    noisy_dirs = [
        ".agents",
        ".beads",
        ".codex",
        ".claude",
        ".reference_projects",
        ".ruff_cache",
        "xray.egg-info",
    ]
    for dirname in noisy_dirs:
        target = repo / dirname
        target.mkdir()
        (target / "state.py").write_text("def generated_state():\n    pass\n", encoding="utf-8")

    exit_code = cli.main(["explore", str(repo), "--max-depth", "2", "--format", "json"])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    paths = {entry["path"] for entry in result["entries"]}
    assert "src" in paths
    assert "src/sample.py" in paths
    assert all(dirname not in paths for dirname in noisy_dirs)


def test_explore_json_includes_structured_entries(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(
        [
            "explore",
            str(repo),
            "--focus",
            "src",
            "--include-symbols",
            "--format",
            "json",
        ]
    )

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
