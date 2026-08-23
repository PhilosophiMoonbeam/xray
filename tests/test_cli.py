import asyncio
import io
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
import tomllib

from xray import cli, mcp_server
from xray.core.ast_grep import (
    AstGrepCommandError,
    AstGrepNotFoundError,
    AstGrepResult,
    BoundedAstGrepResult,
)
from xray.core.indexer import InterfaceReadError, XRayIndexer


def structured_content(result: Any) -> dict[str, Any]:
    content = result.structured_content
    assert content is not None
    return cast(dict[str, Any], content)


def direct_tool_error(result: Any) -> dict[str, Any]:
    assert result.is_error is True
    return cast(dict[str, Any], result.structured_content)["error"]


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

    exit_code = cli.main(["explore", str(repo), "--max-depth", "2", "--include-symbols", "--format", "text"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "sample.py" in output
    assert "def target_function(value):" in output
    assert "class SampleService:" in output


def test_explore_cli_filters_outline_symbol_types(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(
        ["explore", str(repo), "--max-depth", "2", "--include-symbols", "--type", "class", "--format", "json"]
    )

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    sample = next(entry for entry in result["entries"] if entry["path"] == "src/sample.py")
    assert result["options"]["symbol_types"] == ["class"]
    assert [symbol["name"] for symbol in sample["symbols"]] == ["SampleService"]
    assert sample["symbols"][0]["type"] == "class"


def test_outline_extraction_uses_expanded_json_and_type_filter(tmp_path):
    repo = write_sample_repo(tmp_path)
    indexer = XRayIndexer(str(repo))
    outline = [
        {
            "path": "src/sample.py",
            "items": [
                {
                    "name": "SampleService",
                    "symbolType": "class",
                    "signature": "class SampleService:",
                    "members": [{"name": "run", "symbolType": "method", "signature": "def run(self):"}],
                }
            ],
        }
    ]

    with patch(
        "xray.core.indexer.run_ast_grep",
        return_value=AstGrepResult(json.dumps(outline), "", 0),
    ) as run:
        symbols = indexer._get_file_symbol_data(repo / "src" / "sample.py", 5, ["class", "interface"])

    run.assert_called_once_with(
        [
            "outline",
            "--json=compact",
            "--view=expanded",
            "--type",
            "class,interface",
            str(repo / "src" / "sample.py"),
        ]
    )
    assert [(symbol["name"], symbol["type"]) for symbol in symbols] == [
        ("SampleService", "class"),
        ("run", "method"),
    ]


def test_interface_cli_prints_file_skeleton(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["interface", str(repo), "src/sample.py", "--format", "text"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "def target_function(value):" in output
    assert "def caller():" in output


def test_interface_cli_compact_is_structured_and_full_preserves_legacy_string(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    assert cli.main(["interface", str(repo), "src/sample.py"]) == 0
    compact = json.loads(capsys.readouterr().out)
    assert compact["schema_version"] == "xray.cli.v3"
    assert compact["interface"]["path"] == "src/sample.py"
    assert compact["interface"]["completeness"]["complete"] is True
    assert compact["interface"]["symbols"][0]["signature"] == "def target_function(value):"

    assert cli.main(["interface", str(repo), "src/sample.py", "--detail", "full"]) == 0
    full = json.loads(capsys.readouterr().out)
    assert full["schema_version"] == "xray.cli.v1"
    assert full["ok"] is True
    assert isinstance(full["interface"], str)
    assert "def target_function(value):" in full["interface"]


def test_mcp_structured_interface_is_read_only_and_returns_hierarchy(tmp_path):
    repo = write_sample_repo(tmp_path)

    async def exercise():
        from fastmcp import Client

        async with Client(mcp_server.mcp) as client:
            search = await client.call_tool("search_tools", {"pattern": "read_interface_structured"})
            call = await client.call_tool(
                "call_tool",
                {
                    "name": "read_interface_structured",
                    "arguments": {"root_path": str(repo), "file_path": "src/sample.py"},
                },
            )
            return structured_content(search)["matches"], structured_content(call)

    discovered, result = asyncio.run(exercise())
    tool = next(item for item in discovered if item["name"] == "read_interface_structured")
    assert tool["annotations"]["readOnlyHint"] is True
    assert result["path"] == "src/sample.py"
    assert result["symbols"][0]["role"] == "item"


def test_interface_cli_rejects_absolute_path_outside_root(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("def leaked():\n    pass\n", encoding="utf-8")

    exit_code = cli.main(["interface", str(repo), str(outside), "--format", "json"])

    assert exit_code == 1
    result = json.loads(capsys.readouterr().err)
    assert result["ok"] is False
    assert result["schema_version"] == "xray.cli.v3"
    assert result["error"]["code"] == "path_outside_root"
    assert "outside repository root" in result["error"]["message"]


def test_interface_cli_rejects_parent_traversal_outside_root(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("def leaked():\n    pass\n", encoding="utf-8")

    exit_code = cli.main(["interface", str(repo), "../outside.py", "--format", "text"])

    assert exit_code == 1
    output = capsys.readouterr().err
    assert "xray:" in output
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
    result = json.loads(capsys.readouterr().err)
    assert result["ok"] is False
    assert result["error"]["code"] == "path_outside_root"
    assert "outside repository root" in result["error"]["message"]
    assert "def leaked" not in result["error"]["message"]


def test_mcp_read_interface_returns_protocol_error_for_outside_root(tmp_path):
    repo = write_sample_repo(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("def leaked():\n    pass\n", encoding="utf-8")

    result = mcp_server.read_interface(str(repo), str(outside))

    error = direct_tool_error(result)
    assert error["code"] == "path_outside_root"
    assert "outside repository root" in error["message"]
    assert "def leaked" not in error["message"]


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
    assert result["schema_version"] == "xray.cli.v3"
    assert result["ok"] is True
    assert result["command"] == "find"
    assert result["query"] == "target"
    assert result["limit"] == 3
    assert any(symbol["name"] == "target_function" for symbol in result["symbols"])
    assert all("score" in symbol for symbol in result["symbols"])
    assert all("abs_path" in symbol for symbol in result["symbols"])
    assert all(not Path(symbol["path"]).is_absolute() for symbol in result["symbols"])
    assert all(symbol["start_line"] >= 1 for symbol in result["symbols"])


def test_find_cli_defaults_to_compact_json(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["find", str(repo), "target", "--limit", "1"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert json.loads(output)["command"] == "find"
    assert output.count("\n") == 1
    assert "\n  " not in output


def test_find_cli_pretty_prints_json(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["find", str(repo), "target", "--limit", "1", "--pretty"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert json.loads(output)["command"] == "find"
    assert output.startswith("{\n  ")


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


def test_indexer_prunes_expired_disk_cache_entries(tmp_path, monkeypatch):
    cache_root = tmp_path / "cache"
    expired = cache_root / "expired"
    recent = cache_root / "recent"
    expired.mkdir(parents=True)
    recent.mkdir()
    (expired / "symbols.json").write_text("{}", encoding="utf-8")
    (recent / "symbols.json").write_text("{}", encoding="utf-8")
    old = time.time() - 100
    import os

    os.utime(expired, (old, old))
    monkeypatch.setattr("xray.core.indexer.CACHE_MAX_AGE_SECONDS", 50)

    XRayIndexer._prune_disk_cache(cache_root / "current")

    assert not expired.exists()
    assert recent.exists()


def test_indexer_prunes_oldest_disk_cache_entries_to_size_limit(tmp_path, monkeypatch):
    cache_root = tmp_path / "cache"
    oldest = cache_root / "oldest"
    newest = cache_root / "newest"
    oldest.mkdir(parents=True)
    newest.mkdir()
    (oldest / "symbols.json").write_bytes(b"x" * 8)
    (newest / "symbols.json").write_bytes(b"x" * 8)
    now = time.time()
    import os

    os.utime(oldest, (now - 10, now - 10))
    monkeypatch.setattr("xray.core.indexer.CACHE_MAX_BYTES", 8)

    XRayIndexer._prune_disk_cache(cache_root / "current")

    assert not oldest.exists()
    assert newest.exists()


def test_indexer_disk_cache_cleanup_preserves_current_and_active_temp_entries(tmp_path, monkeypatch):
    cache_root = tmp_path / "cache"
    current = cache_root / "current"
    active = cache_root / "active"
    current.mkdir(parents=True)
    active.mkdir()
    (current / "symbols.json").write_bytes(b"x" * 8)
    (active / "tmp-in-progress").write_bytes(b"x" * 8)
    monkeypatch.setattr("xray.core.indexer.CACHE_MAX_AGE_SECONDS", -1)
    monkeypatch.setattr("xray.core.indexer.CACHE_MAX_BYTES", 0)

    XRayIndexer._prune_disk_cache(current)

    assert current.exists()
    assert active.exists()


def test_indexer_disk_cache_cleanup_removes_abandoned_temp_entries(tmp_path, monkeypatch):
    cache_root = tmp_path / "cache"
    abandoned = cache_root / "abandoned"
    abandoned.mkdir(parents=True)
    temp_file = abandoned / "tmp-abandoned"
    temp_file.write_bytes(b"x" * 8)
    old = time.time() - 100
    import os

    os.utime(temp_file, (old, old))
    os.utime(abandoned, (old, old))
    monkeypatch.setattr("xray.core.indexer.CACHE_ACTIVE_TEMP_SECONDS", 50)
    monkeypatch.setattr("xray.core.indexer.CACHE_MAX_AGE_SECONDS", 50)

    XRayIndexer._prune_disk_cache(cache_root / "current")

    assert not abandoned.exists()


def test_indexer_disk_cache_cleanup_tolerates_concurrent_removal(tmp_path):
    cache_root = tmp_path / "cache"
    entry = cache_root / "vanishing"
    entry.mkdir(parents=True)

    with patch("xray.core.indexer.Path.stat", side_effect=FileNotFoundError):
        XRayIndexer._prune_disk_cache(cache_root / "current")


def test_indexer_save_cache_writes_validated_json(tmp_path):
    repo = write_sample_repo(tmp_path)
    completed = subprocess.CompletedProcess(
        args=["git", "rev-parse", "HEAD"],
        returncode=0,
        stdout="def456\n",
        stderr="",
    )

    with patch("xray.core.indexer.subprocess.run", return_value=completed):
        indexer = XRayIndexer(str(repo))

    indexer._set_cached_symbols("sample", [{"signature": "def target_function(value):", "doc": ""}])
    indexer._save_cache()

    assert indexer.cache_dir is not None
    cache_file = indexer.cache_dir / "symbols.json"
    saved = json.loads(cache_file.read_text(encoding="utf-8"))

    assert saved == indexer._cache
    assert list(indexer.cache_dir.glob("tmp*")) == []


def test_indexer_load_cache_rejects_invalid_json_shape(tmp_path):
    repo = write_sample_repo(tmp_path)
    completed = subprocess.CompletedProcess(
        args=["git", "rev-parse", "HEAD"],
        returncode=0,
        stdout="invalid-shape\n",
        stderr="",
    )

    with patch("xray.core.indexer.subprocess.run", return_value=completed):
        indexer = XRayIndexer(str(repo))

    assert indexer.cache_dir is not None
    (indexer.cache_dir / "symbols.json").write_text(
        json.dumps(
            {
                "valid": [{"signature": "def target_function(value):", "doc": ""}],
                "not-a-list": {"signature": "bad"},
                "bad-symbol": [{"signature": 123, "doc": ""}],
            }
        ),
        encoding="utf-8",
    )

    with patch("xray.core.indexer.subprocess.run", return_value=completed):
        reloaded = XRayIndexer(str(repo))

    assert dict(reloaded._cache) == {"valid": [{"signature": "def target_function(value):", "doc": ""}]}


def test_indexer_symbol_cache_is_bounded(tmp_path, monkeypatch):
    repo = write_sample_repo(tmp_path)
    indexer = XRayIndexer(str(repo))
    monkeypatch.setattr("xray.core.indexer.MAX_SYMBOL_CACHE_ENTRIES", 2)

    indexer._set_cached_symbols("old", [{"signature": "def old():", "doc": ""}])
    indexer._set_cached_symbols("middle", [{"signature": "def middle():", "doc": ""}])
    indexer._set_cached_symbols("new", [{"signature": "def new():", "doc": ""}])

    assert list(indexer._cache) == ["middle", "new"]


def test_indexer_skips_oversized_files_for_skeleton_extraction(tmp_path, monkeypatch):
    repo = write_sample_repo(tmp_path)
    large_file = repo / "src" / "large.py"
    large_file.write_text("def huge():\n    pass\n" + ("# filler\n" * 20), encoding="utf-8")
    indexer = XRayIndexer(str(repo))
    monkeypatch.setattr("xray.core.indexer.MAX_SKELETON_FILE_BYTES", 10)

    assert indexer._get_file_skeleton_enhanced(large_file, max_symbols=5) == []
    assert indexer._cache == {}


def test_find_cli_reports_missing_ast_grep_as_json_error(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    with patch(
        "xray.core.indexer.run_ast_grep",
        side_effect=AstGrepNotFoundError("ast-grep executable was not found; symbol search could not run."),
    ):
        exit_code = cli.main(["find", str(repo), "target"])

    assert exit_code == 1
    result = json.loads(capsys.readouterr().err)
    assert result["ok"] is False
    assert result["error"]["code"] == "ast_grep_error"
    assert "ast-grep executable was not found" in result["error"]["message"]


def test_find_cli_reports_ast_grep_nonzero_as_json_error(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    with patch(
        "xray.core.indexer.run_ast_grep",
        side_effect=AstGrepCommandError("ast-grep failed with exit code 2: parser failed"),
    ):
        exit_code = cli.main(["find", str(repo), "target"])

    assert exit_code == 1
    result = json.loads(capsys.readouterr().err)
    assert result["ok"] is False
    assert "parser failed" in result["error"]["message"]


def test_find_cli_uses_one_expanded_outline_inventory(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    outline = [
        {
            "path": str(repo / "src" / "sample.py"),
            "language": "Python",
            "items": [
                {
                    "role": "item",
                    "symbolType": "function",
                    "name": "target_function",
                    "signature": "def target_function(value):",
                    "range": {"start": {"line": 0}, "end": {"line": 1}},
                }
            ],
        }
    ]

    with patch("xray.core.indexer.run_ast_grep", return_value=AstGrepResult(json.dumps(outline), "", 0)) as run:
        exit_code = cli.main(["find", str(repo), "target"])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["symbols"][0]["name"] == "target_function"
    assert result["warnings"] == []
    run.assert_called_once()
    assert run.call_args.args[0][:3] == ["outline", "--json=compact", "--view=expanded"]


def test_find_cli_rejects_invalid_min_score(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["find", str(repo), "target", "--min-score", "101"])

    assert exit_code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["ok"] is False
    assert error["error"]["message"] == "--min-score must be between 0 and 100."


@pytest.mark.parametrize("limit", ["-1", "0"])
def test_find_cli_rejects_nonpositive_limit(tmp_path, capsys, limit):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["find", str(repo), "target", "--limit", limit])

    assert exit_code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["message"] == "--limit must be 1 or greater for a continuable read."


def test_impact_cli_accepts_manual_symbol_json(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    symbol = {
        "name": "target_function",
        "type": "function",
        "path": str(repo / "src" / "sample.py"),
        "start_line": 1,
        "end_line": 2,
    }

    exit_code = cli.main(["impact", str(repo), "--symbol-json", json.dumps(symbol), "--detail", "full"])

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
    assert result["impact"]["total"] >= 1


def test_impact_cli_rejects_missing_symbol_file_as_json_error(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["impact", str(repo), "--symbol-file", str(tmp_path / "missing.json")])

    assert exit_code == 2
    result = json.loads(capsys.readouterr().err)
    assert result["ok"] is False
    assert "Could not read symbol file" in result["error"]["message"]


def test_impact_cli_rejects_empty_stdin_symbol_json(tmp_path, capsys, monkeypatch):
    repo = write_sample_repo(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    exit_code = cli.main(["impact", str(repo), "--symbol-file", "-"])

    assert exit_code == 2
    result = json.loads(capsys.readouterr().err)
    assert result["ok"] is False
    assert result["error"]["message"] == "Symbol JSON from stdin is empty."


def test_impact_cli_rejects_oversized_stdin_symbol_json(tmp_path, capsys, monkeypatch):
    repo = write_sample_repo(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(" " * (cli.MAX_SYMBOL_JSON_CHARS + 1)))

    exit_code = cli.main(["impact", str(repo), "--symbol-file", "-"])

    assert exit_code == 2
    result = json.loads(capsys.readouterr().err)
    assert result["ok"] is False
    assert "exceeds" in result["error"]["message"]


def test_impact_cli_accepts_relative_symbol_from_find_json(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    find_exit = cli.main(["find", str(repo), "target_function", "--limit", "1"])
    assert find_exit == 0
    found = json.loads(capsys.readouterr().out)["symbols"][0]

    impact_exit = cli.main(["impact", str(repo), "--symbol-json", json.dumps(found)])

    assert impact_exit == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schema_version"] == "xray.cli.v3"
    assert result["symbol"]["path"] == "src/sample.py"
    assert result["impact"]["total"] >= 1
    assert result["impact"]["total_exact"] is True
    assert all(reference["line"] >= 1 for reference in result["impact"]["references"])
    assert all(not Path(reference["path"]).is_absolute() for reference in result["impact"]["references"])
    assert {reference["type"] for reference in result["impact"]["references"]} == {"call"}
    assert {reference["confidence"] for reference in result["impact"]["references"]} == {"high"}


def test_impact_filters_duplicate_non_source_and_inexact_structural_matches(tmp_path):
    repo = write_sample_repo(tmp_path)
    (repo / "README.md").write_text("target_function in docs should not be an impact code hit.\n", encoding="utf-8")
    indexer = XRayIndexer(str(repo))
    valid_lines = "target_function = ignored\n    return target_function(41)"
    valid_match = {
        "text": "target_function",
        "file": str(repo / "src" / "sample.py"),
        "range": {"start": {"line": 4}},
        "lines": valid_lines,
        "charCount": {"leading": valid_lines.rfind("target_function")},
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
            "text": valid_lines,
            "matched_text": "return target_function(41)",
            "type": "call",
            "confidence": "high",
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

    result = cast(dict[str, Any], mcp_server.what_breaks(found))

    assert "error" not in result
    assert result["total"] >= 1
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

    error = direct_tool_error(result)
    assert error == {
        "code": "invalid_symbol_path",
        "message": "what_breaks requires an absolute symbol path or abs_path when called via MCP.",
    }


def test_mcp_what_breaks_rejects_absolute_symbol_without_inferable_root(tmp_path, monkeypatch):
    repo = write_sample_repo(tmp_path)
    symbol_path = repo / "src" / "sample.py"

    def fail_if_root_scan(path, operation):
        assert Path(path) != Path("/")
        raise AssertionError("run_indexer_operation should not be called without an inferable root")

    monkeypatch.setattr(mcp_server, "run_indexer_operation", fail_if_root_scan)

    result = mcp_server.what_breaks(
        {
            "name": "target_function",
            "type": "function",
            "path": str(symbol_path),
            "start_line": 1,
            "end_line": 2,
        }
    )

    assert "requires a CLI find symbol" in direct_tool_error(result)["message"]


def test_mcp_what_breaks_infers_root_from_cli_symbol_without_git(tmp_path, monkeypatch):
    repo = write_sample_repo(tmp_path)
    symbol_path = repo / "src" / "sample.py"
    seen = {}

    def fake_run_indexer_operation(path, operation):
        seen["path"] = path
        return {
            "references": [],
            "total_count": 0,
            "raw_count": 0,
            "filtered_count": 0,
            "strategy": "text",
            "note": "Found 0 references using text search.",
        }

    monkeypatch.setattr(mcp_server, "run_indexer_operation", fake_run_indexer_operation)

    result = cast(
        dict[str, Any],
        mcp_server.what_breaks(
            {
                "name": "target_function",
                "type": "function",
                "path": "src/sample.py",
                "abs_path": str(symbol_path),
                "start_line": 1,
                "end_line": 2,
            }
        ),
    )

    assert "error" not in result
    assert seen["path"] == str(repo)


def test_mcp_tool_surface_is_search_first_with_compact_metadata(tmp_path):
    repo = write_sample_repo(tmp_path)

    async def inspect_surface():
        from fastmcp import Client

        async with Client(mcp_server.mcp) as client:
            tools = await client.list_tools()
            search_result = await client.call_tool("search_tools", {"pattern": "impact"})
            full_search_result = await client.call_tool("search_tools", {"pattern": "impact", "detail": "full"})
            call_result = await client.call_tool(
                "call_tool",
                {"name": "explore_repo", "arguments": {"root_path": str(repo), "max_depth": 1}},
            )
            return tools, search_result, full_search_result, call_result

    tools, search_result, full_search_result, call_result = asyncio.run(inspect_surface())

    assert [tool.name for tool in tools] == ["search_tools", "call_tool"]
    assert all("PROGRESSIVE DISCOVERY WORKFLOW" not in (tool.description or "") for tool in tools)
    assert "ranked intent" in (tools[0].description or "")
    assert "Natural-language intent" in tools[0].inputSchema["properties"]["pattern"]["description"]
    summary = structured_content(search_result)
    assert summary["total_exact"] is True
    assert summary["detail"] == "summary"
    matches = summary["matches"]
    assert [match["name"] for match in matches] == ["what_breaks"]
    assert matches[0]["description"].startswith("Estimate blast radius")
    assert "not a type-aware caller" in matches[0]["description"]
    assert matches[0]["mutation_class"] == "read_only"
    full_match = structured_content(full_search_result)["matches"][0]
    assert full_match["inputSchema"]["properties"]["exact_symbol"]["description"].startswith("Full symbol object")
    explore = structured_content(call_result)
    assert "tree_text" not in explore
    assert explore["root_path"] == str(repo)
    assert any(entry["path"] == "src" for entry in explore["entries"])
    assert all("abs_path" not in entry for entry in explore["entries"])


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
            terms = [
                "map",
                "find symbol",
                "interface",
                "find usages",
                "who calls",
                "used by",
                "change impact",
                "structural search",
                "rename symbol",
                "change function safely",
                "replace expression",
                "replace",
                "fix",
                "apply replacement",
                "validate rule",
                "scan rules",
                "file imports",
                "file exports",
                "help",
                "rewrite pattern",
            ]
            searches = {
                term: structured_content(await client.call_tool("search_tools", {"pattern": term, "detail": "full"}))
                for term in terms
            }
            inventory_pages = []
            cursor = None
            while True:
                arguments = {"pattern": ".", "detail": "full", "limit": 7}
                if cursor is not None:
                    arguments["cursor"] = cursor
                page = structured_content(await client.call_tool("search_tools", arguments))
                inventory_pages.append(page)
                cursor = page.get("next_cursor")
                if cursor is None:
                    break
            summary_inventory = structured_content(
                await client.call_tool("search_tools", {"pattern": ".", "limit": 50})
            )
            legacy = structured_content(
                await client.call_tool("search_tools", {"pattern": "legacy rewrite", "detail": "full"})
            )
            regex = structured_content(
                await client.call_tool(
                    "search_tools", {"pattern": "plan_replacement|verify_replacement", "mode": "regex"}
                )
            )
            invalid_regex = await client.call_tool(
                "search_tools", {"pattern": "[", "mode": "regex"}, raise_on_error=False
            )
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
                "legacy_rewrite": await client.call_tool(
                    "call_tool",
                    {
                        "name": "rewrite_pattern",
                        "arguments": {
                            "root_path": str(repo),
                            "pattern": "never_matches($A)",
                            "replacement": "still_never($A)",
                            "lang": "python",
                        },
                    },
                ),
            }
            return searches, inventory_pages, summary_inventory, legacy, regex, invalid_regex, calls

    searches, inventory_pages, summary_inventory, legacy, regex, invalid_regex, calls = asyncio.run(
        inspect_search_and_calls()
    )
    matches = {term: result["matches"] for term, result in searches.items()}

    assert matches["map"][0]["name"] == "explore_repo"
    assert matches["find symbol"][0]["name"] == "find_symbol"
    assert matches["interface"][0]["name"] == "read_interface"
    for term in ("find usages", "who calls", "used by", "change impact"):
        assert matches[term][0]["name"] == "what_breaks"
    assert matches["structural search"][0]["name"] == "search_pattern"
    for term in ("rename symbol", "change function safely", "replace expression", "replace", "fix"):
        assert matches[term][0]["name"] == "plan_replacement"
    assert matches["apply replacement"][0]["name"] == "apply_replacement"
    assert matches["validate rule"][0]["name"] == "check_rules"
    assert matches["scan rules"][0]["name"] == "scan_rules"
    assert matches["file imports"][0]["name"] == "file_imports"
    assert matches["file exports"][0]["name"] == "file_exports"
    assert matches["help"][0]["name"] == "xray_capabilities"
    assert all(match["name"] != "rewrite_pattern" for result in matches.values() for match in result)
    assert legacy["matches"][0]["name"] == "rewrite_pattern"
    assert legacy["legacy_tools_included"] is True
    assert {match["name"] for match in regex["matches"]} >= {"plan_replacement", "verify_replacement"}
    assert all(match["name"] != "rewrite_pattern" for match in regex["matches"])
    assert invalid_regex.is_error is True
    assert invalid_regex.structured_content is not None
    assert invalid_regex.structured_content["error"]["code"] == "invalid_regex"

    assert len(inventory_pages) == 3
    assert inventory_pages[0]["returned"] == 7
    assert inventory_pages[0]["total"] == 20
    assert inventory_pages[0]["total_exact"] is True
    assert inventory_pages[0]["truncated"] is True
    assert inventory_pages[-1]["truncated"] is False
    inventory = [match for page in inventory_pages for match in page["matches"]]
    assert summary_inventory["total"] == 20
    assert summary_inventory["truncated"] is False
    assert all("inputSchema" not in match for match in summary_inventory["matches"])
    assert len(json.dumps(summary_inventory)) < len(json.dumps(inventory))
    all_tools = {match["name"]: match for match in inventory}
    assert set(all_tools) == {
        "explore_repo",
        "find_symbol",
        "read_interface",
        "read_interface_structured",
        "read_symbol",
        "symbol_at",
        "what_breaks",
        "search_pattern",
        "plan_replacement",
        "refine_replacement",
        "verify_replacement",
        "apply_replacement",
        "scan_rules",
        "apply_rule_fixes",
        "check_rules",
        "explain_rules",
        "test_rules",
        "xray_capabilities",
        "file_imports",
        "file_exports",
    }
    detail_tools = {"explore_repo", "search_pattern", "scan_rules", "check_rules"}
    limited_tools = {"search_pattern", "scan_rules"}
    cursor_tools = {"search_pattern", "scan_rules", "check_rules"}
    for name in detail_tools:
        assert all_tools[name]["inputSchema"]["properties"]["detail"]["default"] == "compact"
    for name in limited_tools:
        assert all_tools[name]["inputSchema"]["properties"]["limit"]["default"] == 50
    for name in cursor_tools:
        assert "cursor" in all_tools[name]["inputSchema"]["properties"]
    assert "at most 50 compact matches" in all_tools["search_pattern"]["description"]
    assert "read-only" in all_tools["scan_rules"]["description"]
    assert "page size may change" in all_tools["search_pattern"]["inputSchema"]["properties"]["cursor"]["description"]

    for match in inventory:
        properties = match["inputSchema"]["properties"]
        assert "ctx" not in properties
        assert match["description"]
        assert match["meta"]["fastmcp"]["tags"]
        if match["name"] in {"apply_replacement", "apply_rule_fixes"}:
            assert match["annotations"] == {
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": False,
            }
        else:
            assert match["annotations"] == {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            }
        assert all(property_schema.get("description") for property_schema in properties.values())

    explore = structured_content(calls["explore_repo"])
    assert "tree_text" not in explore
    assert any(entry["path"] == "src" for entry in explore["entries"])
    found_symbols = structured_content(calls["find_symbol"])["symbols"]
    assert any(symbol_result["name"] == "target_function" for symbol_result in found_symbols)
    assert all(Path(symbol_result["abs_path"]).is_absolute() for symbol_result in found_symbols)
    assert "def target_function(value):" in text_content(calls["read_interface"].content[0])
    impact = structured_content(calls["what_breaks"])
    assert impact["total"] >= 1
    assert all(reference["line"] >= 1 for reference in impact["references"])
    assert structured_content(calls["legacy_rewrite"])["match_count"] == 0


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
            search_result = await client.call_tool("search_tools", {"pattern": "map", "detail": "full"})
            call_result = await client.call_tool(
                "call_tool",
                {"name": "explore_repo", "arguments": {"root_path": str(repo), "max_depth": 1}},
            )
            return search_result, call_result

    search_result, call_result = asyncio.run(call_explore())

    match = structured_content(search_result)["matches"][0]
    assert match["name"] == "explore_repo"
    assert "ctx" not in match["inputSchema"]["properties"]
    explore = structured_content(call_result)
    assert "tree_text" not in explore
    assert any(entry["path"] == "src" for entry in explore["entries"])
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

    calls = 0

    def fake_run_indexer_operation(path, operation):
        nonlocal calls
        calls += 1
        started.set()
        if not release.wait(timeout=2):
            raise AssertionError("blocking operation was not released")
        if calls == 1:
            return "snapshot"
        return (
            [
                {
                    "name": "target_function",
                    "path": str(repo / "src" / "sample.py"),
                    "type": "function",
                    "start_line": 1,
                }
            ],
            True,
            [],
        )

    monkeypatch.setattr(mcp_server, "run_indexer_operation", fake_run_indexer_operation)

    async def exercise():
        task = asyncio.create_task(mcp_server.find_symbol(str(repo), "target", cast(Any, FakeContext())))
        assert await asyncio.to_thread(started.wait, 1)
        result = await asyncio.wait_for(asyncio.sleep(0, result="event loop alive"), timeout=0.1)
        release.set()
        return result, await asyncio.wait_for(task, timeout=1)

    loop_probe, symbols_value = asyncio.run(exercise())
    symbols = cast(dict[str, Any], symbols_value)

    assert loop_probe == "event loop alive"
    assert symbols["symbols"][0]["name"] == "target_function"
    assert symbols["symbols"][0]["type"] == "function"
    assert symbols["symbols"][0]["start_line"] == 1


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

    def payload(result) -> Any:
        content = result.structured_content
        if content is None:
            return text_content(result.content[0])
        return content.get("result", content)

    same_results = [payload(result) for result in same_root]
    assert same_results[0]["root_path"] == str(repo_a)
    assert any(symbol["name"] == "target_function" for symbol in same_results[1]["symbols"])
    assert "def target_function(value):" in same_results[2]
    assert same_results[3]["total"] >= 1
    assert all("error" not in result for result in same_results[1:])

    multi_results = [payload(result) for result in multi_root]
    assert any(symbol["name"] == "target_function" for symbol in multi_results[0]["symbols"])
    assert any(symbol["name"] == "target_function" for symbol in multi_results[1]["symbols"])
    assert multi_results[2]["root_path"] == str(repo_a)
    assert multi_results[3]["root_path"] == str(repo_b)


def test_mcp_indexer_cache_eviction_is_lru_and_bounded(tmp_path, monkeypatch):
    repos = [write_sample_repo(tmp_path / str(index)) for index in range(3)]
    monkeypatch.setenv("XRAY_MCP_INDEXER_CACHE_LIMIT", "2")
    with mcp_server._indexer_cache_lock:
        mcp_server._indexer_cache.clear()
        mcp_server._indexer_locks.clear()
        mcp_server._indexer_active_operations.clear()

    for repo in repos:
        mcp_server.get_indexer(str(repo))

    with mcp_server._indexer_cache_lock:
        cached_paths = list(mcp_server._indexer_cache)

    assert cached_paths == [str(repos[1].resolve()), str(repos[2].resolve())]
    assert set(mcp_server._indexer_locks) == set(cached_paths)


def test_mcp_indexer_cache_does_not_evict_active_operations(tmp_path, monkeypatch):
    repo_a = write_sample_repo(tmp_path / "a")
    repo_b = write_sample_repo(tmp_path / "b")
    release = threading.Event()
    started = threading.Event()
    monkeypatch.setenv("XRAY_MCP_INDEXER_CACHE_LIMIT", "1")
    with mcp_server._indexer_cache_lock:
        mcp_server._indexer_cache.clear()
        mcp_server._indexer_locks.clear()
        mcp_server._indexer_active_operations.clear()

    def long_operation(indexer):
        started.set()
        assert release.wait(timeout=2)
        return indexer.root_path

    worker = threading.Thread(
        target=mcp_server.run_indexer_operation,
        args=(str(repo_a), long_operation),
    )
    worker.start()
    assert started.wait(timeout=2)

    mcp_server.get_indexer(str(repo_b))
    with mcp_server._indexer_cache_lock:
        assert str(repo_a.resolve()) in mcp_server._indexer_cache
        assert str(repo_b.resolve()) in mcp_server._indexer_cache

    release.set()
    worker.join(timeout=2)

    with mcp_server._indexer_cache_lock:
        cached_paths = list(mcp_server._indexer_cache)

    assert cached_paths == [str(repo_b.resolve())]


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
    assert "relative-path `entries`" in workflow_text
    assert 'detail="full"' in workflow_text
    assert "return at most 50 compact items" in workflow_text
    assert "ranked `search_tools`" in workflow_text
    assert "regex mode is explicit" in workflow_text
    assert "regardless of the reporting limit" in workflow_text
    xray_workflow = next(resource for resource in resources if str(resource.uri) == "xray://workflow")
    annotations = xray_workflow.annotations
    assert annotations is not None
    assert getattr(annotations, "readOnlyHint") is True
    assert getattr(annotations, "idempotentHint") is True
    skill_text = text_content(skill[0])
    assert skill_text.startswith("# XRAY Progressive Discovery")
    assert "search_tools" in skill_text
    assert "ranks natural intent" in skill_text
    assert '`mode="regex"`' in skill_text
    assert "relative-path `entries`" in skill_text
    assert "signature" in skill_text
    assert "name-based references" in skill_text
    assert "dependency graph" in skill_text
    prompt_text = text_content(prompt.messages[0].content)
    assert prompt_text.startswith("Goal: review impact")
    assert "use compact entries for file selection" in prompt_text
    assert "detail='full' only for tree_text" in prompt_text
    assert "returned/total/total_exact/truncated" in prompt_text
    assert "plan_replacement" in workflow_text
    assert "apply_replacement" in workflow_text
    assert "independently copied digest" in prompt_text
    assert "ranked search_tools intent search" in prompt_text
    assert "verify_replacement" in prompt_text
    assert "pass lang whenever the target language is known" in prompt_text
    assert "Legacy rewrite still applies every match" in prompt_text
    assert "Rule fixes require a reviewed plan" in prompt_text
    assert "name-based references" in prompt_text
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
    assert "outside repository root" in result["error"]["message"]


def test_impact_cli_rejects_manual_symbol_without_start_line(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["impact", str(repo), "--name", "target_function", "--path", "src/sample.py"])

    assert exit_code == 2
    result = json.loads(capsys.readouterr().err)
    assert result["ok"] is False
    assert "Manual symbols require --start-line" in result["error"]["message"]


def test_impact_cli_rejects_missing_symbol_source(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["impact", str(repo)])

    assert exit_code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["message"] == (
        "Provide exactly one symbol source: --symbol-json, --symbol-file, or --name with --path."
    )


def test_impact_cli_validates_symbol_json_with_pydantic(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["impact", str(repo), "--symbol-json", json.dumps({"path": "src/sample.py"})])

    assert exit_code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["ok"] is False
    assert "Symbol input field 'name'" in error["error"]["message"]


def test_mcp_what_breaks_validates_symbol_input():
    result = mcp_server.what_breaks({"path": "/tmp/sample.py"})

    assert direct_tool_error(result)["message"].startswith("Symbol input field 'name'")


def test_map_alias_matches_explore(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["map", str(repo), "--max-depth", "1", "--format", "text"])

    assert exit_code == 0
    assert "src" in capsys.readouterr().out


def test_explore_cli_rejects_negative_max_depth(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["explore", str(repo), "--max-depth", "-1", "--format", "json"])

    assert exit_code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["schema_version"] == "xray.cli.v3"
    assert error["ok"] is False
    assert error["error"]["message"] == "--max-depth must be 0 or greater."


def test_explore_cli_parse_error_returns_json_by_default(capsys):
    exit_code = cli.main(["explore", ".", "--max-depth", "nope"])

    assert exit_code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["schema_version"] == "xray.cli.v3"
    assert error["ok"] is False
    assert error["command"] == "explore"
    assert "invalid int value" in error["error"]["message"]


def test_find_cli_missing_argument_returns_json_error_by_default(capsys):
    exit_code = cli.main(["find", "."])

    assert exit_code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["schema_version"] == "xray.cli.v3"
    assert error["ok"] is False
    assert error["command"] == "find"
    assert "required" in error["error"]["message"]


def test_find_cli_missing_argument_returns_text_error_when_requested(capsys):
    exit_code = cli.main(["find", ".", "--format", "text"])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "xray find: error:" in captured.err
    assert "required" in captured.err


def test_find_cli_invalid_format_returns_json_error_by_default(capsys):
    exit_code = cli.main(["find", ".", "target", "--format", "xml"])

    assert exit_code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["schema_version"] == "xray.cli.v3"
    assert error["ok"] is False
    assert error["command"] == "find"
    assert "invalid choice" in error["error"]["message"]


def test_cli_missing_command_returns_json_error(capsys):
    exit_code = cli.main([])

    assert exit_code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["schema_version"] == "xray.cli.v3"
    assert error["ok"] is False
    assert error["command"] is None
    assert "required" in error["error"]["message"]


def test_cli_version_returns_without_system_exit(capsys):
    exit_code = cli.main(["--version"])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "xray 0.11.4"


def test_cli_help_is_current_safe_and_token_bounded(capsys):
    def get_help(*command: str) -> str:
        assert cli.main([*command, "--help"]) == 0
        return capsys.readouterr().out

    helps = {
        "root": get_help(),
        "explore": get_help("explore"),
        "find": get_help("find"),
        "interface": get_help("interface"),
        "read-symbol": get_help("read-symbol"),
        "symbol-at": get_help("symbol-at"),
        "impact": get_help("impact"),
        "search": get_help("search"),
        "rewrite": get_help("rewrite"),
        "scan": get_help("scan"),
        "replace": get_help("replace"),
        "replace plan": get_help("replace", "plan"),
        "replace apply": get_help("replace", "apply"),
        "replace refine": get_help("replace", "refine"),
        "replace verify": get_help("replace", "verify"),
        "rules check": get_help("rules", "check"),
        "rules explain": get_help("rules", "explain"),
        "rules test": get_help("rules", "test"),
        "skill": get_help("skill"),
        "skill install": get_help("skill", "install"),
        "imports": get_help("imports"),
        "exports": get_help("exports"),
        "capabilities": get_help("capabilities"),
    }
    normalized = {name: " ".join(value.split()) for name, value in helps.items()}

    root = normalized["root"]
    assert "xray explore ROOT --max-depth 2" in root
    assert "jq -c '.symbols[0]'" in root
    assert "xray replace plan ROOT" in root
    assert "xray replace apply ROOT" in root
    assert "Compact v3 JSON is default" in root
    assert "where offered, use --detail full" in root
    assert "total_exact" in root
    assert "YAML output is unsupported" in root
    assert "replace apply, rewrite, and scan --fix mutate files" in root
    assert "--limit never bounds legacy edits" in root
    assert "Exit codes: 0 success, 1 operational failure, 2 parse or validation error" in root
    assert "Install the bundled xray-cli agent skill." in root

    explore = normalized["explore"]
    assert "Start shallow" in explore
    assert "--no-default-exclusions" in explore
    assert "--detail {compact,full}" in explore
    assert "invoked_as" in explore

    find = normalized["find"]
    assert "owner-qualified identity" in find
    assert "--min-score 60" in find
    assert "qualified identity" in find
    assert "match reason" in find

    interface = normalized["interface"]
    assert "typed hierarchy" in interface
    assert "must resolve inside the root" in interface
    assert "parent traversal and symlink escapes fail" in interface
    assert "legacy v1 string envelope" in interface
    assert "Exact symbol JSON" in interface
    assert "Maximum returned lines" in normalized["read-symbol"]
    assert "narrowest symbol" in normalized["symbol-at"]

    impact = normalized["impact"]
    assert "Provide exactly one symbol source" in impact
    assert "not a type-aware dependency graph" in impact
    assert "required with --name and --path" in impact
    assert "--symbol-file -" in impact
    assert "definition/import/call/read/text" in impact
    assert "total_exact=false means a lower bound" in impact

    assert "also bounds upstream search" in normalized["search"]
    assert "edits still cover every match" in normalized["rewrite"]
    assert "pattern-like non-code text" in normalized["rewrite"]
    assert "--fix still applies every fix" in normalized["scan"]
    assert "without writing files" in normalized["replace plan"]
    assert "Candidate cap (default: 1000)" in normalized["replace plan"]
    assert "Affected-file cap (default: 100)" in normalized["replace plan"]
    assert "Preview cap (default: 50)" in normalized["replace plan"]
    assert "bounded to 10 MiB" in normalized["replace apply"]
    assert "Independently copied reviewed plan digest" in normalized["replace apply"]
    assert "stable edit ID" in normalized["replace refine"]
    assert "without writes" in normalized["replace verify"]
    assert "syntax" in normalized["replace verify"]
    assert "--allow-dirty-affected" in normalized["replace plan"]
    assert "--allow-new-parse-errors" in normalized["replace plan"]
    assert "schemas, operations, bounds" in normalized["capabilities"]
    assert "Replace divergent content" in normalized["skill install"]
    assert "Use ROOT/.agents/skills" in normalized["skill install"]
    assert "Page size (default: 50)" in normalized["imports"]
    assert "Page size (default: 50)" in normalized["exports"]

    assert all("read-only repository scans" not in value for value in normalized.values())
    assert len(helps["root"].encode()) <= 3200
    assert sum(len(value.encode()) for value in helps.values()) <= 30_000


@pytest.mark.parametrize(
    "argv",
    [
        ["explore", "ROOT", "--max-depth", "2"],
        ["map", "ROOT", "--max-depth", "2"],
        ["find", "ROOT", "AuthService.validate_user", "--limit", "5", "--min-score", "60"],
        ["interface", "ROOT", "src/package/module.py"],
        ["impact", "ROOT", "--symbol-file", "-"],
        ["search", "ROOT", "-p", "old_api($ARG)", "-l", "python"],
        ["imports", "ROOT", "src/package/module.py"],
        ["exports", "ROOT", "src/package/module.py"],
        ["scan", "ROOT", "--rule", "sgconfig.yml"],
        [
            "replace",
            "plan",
            "ROOT",
            "-p",
            "old_api($ARG)",
            "-r",
            "new_api($ARG)",
            "-l",
            "python",
            "--path",
            "src",
            "--glob",
            "*.py",
        ],
        [
            "replace",
            "apply",
            "ROOT",
            "--plan-file",
            "plan.json",
            "--expected-digest",
            "REVIEWED_DIGEST",
        ],
        ["rewrite", "ROOT", "-p", "old_api($ARG)", "-r", "new_api($ARG)", "-l", "python"],
        ["scan", "ROOT", "--rule", "sgconfig.yml", "--fix"],
    ],
)
def test_cli_skill_examples_parse_current_options(argv):
    args = cli.build_parser().parse_args(argv)

    assert callable(args.handler)


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
    assert result["schema_version"] == "xray.cli.v3"
    assert result["ok"] is True
    assert result["command"] == "explore"
    assert result["invoked_as"] == "explore"
    assert result["root_path"] == str(repo)
    assert "tree_text" not in result
    assert result["options"]["include_symbols"] is True
    assert result["options"]["max_entries"] == 5000
    assert result["truncated"] is False
    entries = {entry["path"]: entry for entry in result["entries"]}
    assert entries["."]["kind"] == "directory"
    assert entries["src"]["kind"] == "directory"
    assert entries["src/sample.py"]["language"] == "python"
    assert "abs_path" not in entries["src/sample.py"]
    assert any(symbol["signature"] == "def target_function(value):" for symbol in entries["src/sample.py"]["symbols"])


def test_symbol_inventory_prevents_owner_pollution_and_filters_nonsense(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "service.py").write_text(
        "class BillingService:\n    def unrelated_member(self):\n        return 1\n",
        encoding="utf-8",
    )
    indexer = XRayIndexer(str(repo))

    owner_results = indexer.find_symbol("BillingService", min_score=60, include_scores=True)
    qualified = indexer.find_symbol("BillingService.unrelated_member", min_score=60, include_scores=True)
    nonsense = indexer.find_symbol(
        "this query has no plausible symbol identity whatsoever", min_score=60, include_scores=True
    )

    assert [result["name"] for result in owner_results] == ["BillingService"]
    assert qualified[0].get("qualified_name") == "BillingService.unrelated_member"
    assert qualified[0].get("owner") == "BillingService"
    assert qualified[0].get("match_reason") == "exact_qualified_name"
    assert qualified[0].get("confidence") == "high"
    assert nonsense == []


def test_symbol_inventory_invalidates_on_same_size_dirty_source_change(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "sample.py"
    source.write_text("def alpha():\n    pass\n", encoding="utf-8")
    first_outline = [
        {
            "path": str(source),
            "items": [
                {
                    "name": "alpha",
                    "symbolType": "function",
                    "signature": "def alpha():",
                    "range": {"start": {"line": 0}, "end": {"line": 1}},
                }
            ],
        }
    ]
    second_outline = [
        {
            "path": str(source),
            "items": [
                {
                    "name": "bravo",
                    "symbolType": "function",
                    "signature": "def bravo():",
                    "range": {"start": {"line": 0}, "end": {"line": 1}},
                }
            ],
        }
    ]
    indexer = XRayIndexer(str(repo))

    with patch(
        "xray.core.indexer.run_ast_grep",
        side_effect=[AstGrepResult(json.dumps(first_outline), "", 0), AstGrepResult(json.dumps(second_outline), "", 0)],
    ) as run:
        assert indexer.find_symbol("alpha", min_score=100)[0]["name"] == "alpha"
        source.write_text("def bravo():\n    pass\n", encoding="utf-8")
        assert indexer.find_symbol("bravo", min_score=100)[0]["name"] == "bravo"

    assert run.call_count == 2


def test_structured_python_interface_preserves_hierarchy_docs_and_signatures(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "service.py"
    source.write_text(
        '''class Service(Base):
    """Public service contract."""

    def fetch(self, key: str, retries: int = 2) -> bytes:
        """Fetch one value."""
        secret_implementation = key * retries
        return secret_implementation.encode()
''',
        encoding="utf-8",
    )
    indexer = XRayIndexer(str(repo))

    result = indexer.read_interface_structured("service.py")
    rendered = indexer.render_interface(result)

    assert result["path"] == "service.py"
    assert result["language"] == "python"
    assert result["complete"] is True
    assert result["symbols"][0]["documentation"] == "Public service contract."
    member = result["symbols"][0]["members"][0]
    assert member["signature"] == "def fetch(self, key: str, retries: int=2) -> bytes:"
    assert member["documentation"] == "Fetch one value."
    assert "secret_implementation" not in rendered
    assert "    def fetch" in rendered


@pytest.mark.parametrize(("suffix", "language"), [(".js", "javascript"), (".ts", "typescript"), (".go", "go")])
def test_exact_non_python_container_preserves_bounded_members(tmp_path, suffix, language):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / f"service{suffix}"
    source.write_text("placeholder\n", encoding="utf-8")
    symbols = [
        {
            "name": "Service",
            "type": "class",
            "signature": "Service",
            "start_line": 1,
            "end_line": 3,
            "visibility": "public",
            "role": "item",
            "documentation": None,
            "members": [
                {
                    "name": "first",
                    "type": "method",
                    "signature": "first",
                    "start_line": 2,
                    "end_line": 2,
                    "visibility": "public",
                    "role": "member",
                    "documentation": None,
                    "members": [],
                },
                {
                    "name": "second",
                    "type": "method",
                    "signature": "second",
                    "start_line": 3,
                    "end_line": 3,
                    "visibility": "public",
                    "role": "member",
                    "documentation": None,
                    "members": [],
                },
            ],
        }
    ]
    indexer = XRayIndexer(str(repo))
    with patch.object(indexer, "_outline_interface", return_value=(symbols, [])):
        result = indexer.read_interface_structured(
            source.name,
            exact_symbol={"name": "Service", "path": source.name, "start_line": 1},
            max_members=1,
        )
    assert result["language"] == language
    assert [member["name"] for member in result["symbols"][0]["members"]] == ["first"]
    assert result["complete"] is False


def test_structured_interface_surfaces_typed_errors_and_incompleteness(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (repo / "notes.md").write_text("# Notes\n", encoding="utf-8")
    script = repo / "script.js"
    script.write_text("const value = 1;\n", encoding="utf-8")
    indexer = XRayIndexer(str(repo))

    with pytest.raises(InterfaceReadError) as parse_error:
        indexer.read_interface_structured("broken.py")
    with pytest.raises(InterfaceReadError) as unsupported:
        indexer.read_interface_structured("notes.md")
    with pytest.raises(InterfaceReadError) as missing:
        indexer.read_interface_structured("missing.py")
    assert parse_error.value.code == "parse_error"
    assert unsupported.value.code == "unsupported_file"
    assert missing.value.code == "not_found"

    incomplete_outline = [
        {
            "path": str(script),
            "items": [{"name": "value", "symbolType": "constant", "range": {"start": {"line": 0}}}],
        }
    ]
    with patch("xray.core.indexer.run_ast_grep", return_value=AstGrepResult(json.dumps(incomplete_outline), "", 0)):
        incomplete = indexer.read_interface_structured("script.js")
    assert incomplete["complete"] is False
    assert incomplete["warnings"]
    assert incomplete["symbols"][0]["signature"] == "value"


def test_bounded_impact_classifies_definitions_imports_and_calls(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "target.py"
    target.write_text("def work():\n    pass\n", encoding="utf-8")
    other = repo / "other.py"
    other.write_text("def work():\n    pass\nfrom target import work\nwork()\n", encoding="utf-8")
    matches = [
        {"file": str(target), "text": "work", "lines": "def work():", "range": {"start": {"line": 0}}},
        {"file": str(other), "text": "work", "lines": "def work():", "range": {"start": {"line": 0}}},
        {
            "file": str(other),
            "text": "work",
            "lines": "from target import work",
            "range": {"start": {"line": 2}},
        },
        {"file": str(other), "text": "work", "lines": "work()", "range": {"start": {"line": 3}}},
    ]
    indexer = XRayIndexer(str(repo))

    with patch(
        "xray.core.indexer.run_ast_grep_bounded",
        side_effect=[
            BoundedAstGrepResult(matches=matches, total_exact=False),
            BoundedAstGrepResult(matches=matches, total_exact=True),
        ],
    ) as run:
        result = indexer.what_breaks(
            {"name": "work", "path": str(target), "start_line": 1, "end_line": 2}, max_results=4
        )

    assert [reference.get("type") for reference in result["references"]] == ["definition", "import", "call"]
    assert [reference.get("confidence") for reference in result["references"]] == ["high", "high", "high"]
    assert result["total_exact"] is True
    assert "not dependents" in result["note"]
    assert [call.args[1] for call in run.call_args_list] == [4, 8]


def test_find_symbol_defaults_are_calibrated_scoped_and_scored(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "other").mkdir()
    (repo / "src" / "public.py").write_text("def exact_target():\n    pass\n", encoding="utf-8")
    (repo / "other" / "private.py").write_text("def _exact_target():\n    pass\n", encoding="utf-8")
    indexer = XRayIndexer(str(repo))

    results = indexer.find_symbol("exact_target", paths=["src"], languages=["python"], symbol_types=["function"])

    assert [result["path"] for result in results] == ["src/public.py"]
    assert results[0].get("score") == 100
    assert results[0].get("confidence") == "high"
    assert indexer.find_symbol("utterly unrelated behavior phrase") == []
    assert indexer.last_find_total == 0


def test_interface_symbol_reads_and_symbol_at_are_bounded_and_contained(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "service.py"
    source.write_text(
        "class Service:\n"
        "    def first(self):\n"
        "        return 1\n"
        "    def second(self):\n"
        "        return 2\n"
        "\n"
        "def helper():\n"
        "    return Service().first()\n",
        encoding="utf-8",
    )
    indexer = XRayIndexer(str(repo))

    interface = indexer.read_interface_structured("service.py", max_symbols=1, max_members=1)
    assert interface["complete"] is False
    assert interface["returned_symbols"] == 1
    assert len(interface["symbols"][0]["members"]) == 1
    assert interface["warnings"]

    found = indexer.find_symbol("helper", min_score=100)[0]
    at_line = indexer.symbol_at("service.py", int(found["start_line"]))
    assert at_line is not None and at_line["name"] == "helper"
    read = indexer.read_symbol(found, max_lines=1, max_bytes=12)
    assert read["path"] == "service.py"
    assert read["returned_lines"] <= 1
    assert read["returned_bytes"] <= 12
    assert read["truncated"] is True
    with pytest.raises(ValueError, match="outside repository"):
        indexer.read_symbol({"path": "../outside.py", "start_line": 1, "end_line": 1})

    for field, value in (
        ("name", "forged"),
        ("type", "class"),
        ("start_line", int(found["start_line"]) + 1),
        ("end_line", int(found["end_line"]) + 1),
        ("qualified_name", "Service.helper"),
        ("owner", "Service"),
        ("language", "typescript"),
    ):
        tampered = {**found, field: value}
        with pytest.raises(InterfaceReadError) as mismatch:
            indexer.read_symbol(tampered)
        assert mismatch.value.code == "symbol_mismatch"

    other = repo / "other.py"
    other.write_text("def other():\n    pass\n", encoding="utf-8")
    with pytest.raises(InterfaceReadError) as path_mismatch:
        indexer.read_symbol({**found, "abs_path": str(other)})
    assert path_mismatch.value.code == "symbol_mismatch"


def test_nested_map_focus_keeps_root_context_and_ancestor_chain(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src" / "pkg").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "README.md").write_text("context\n", encoding="utf-8")
    (repo / "src" / "pkg" / "selected.py").write_text("def selected():\n    pass\n", encoding="utf-8")
    (repo / "src" / "other.py").write_text("def other():\n    pass\n", encoding="utf-8")
    (repo / "docs" / "guide.md").write_text("not selected\n", encoding="utf-8")

    data = XRayIndexer(str(repo)).explore_repo_data(focus_dirs=["src/pkg"])
    paths = {entry["path"] for entry in data["entries"]}

    assert {".", "README.md", "src", "src/pkg", "src/pkg/selected.py"} <= paths
    assert "src/other.py" not in paths
    assert "docs" not in paths
    assert data["options"]["focus_dirs"] == ["src/pkg"]


@pytest.mark.parametrize("focus", ["src/pkg", "src/pkg/selected.py"])
def test_strict_focus_limit_one_emits_the_focus_before_internal_ancestors(tmp_path, focus):
    repo = tmp_path / "repo"
    (repo / "src" / "pkg").mkdir(parents=True)
    (repo / "src" / "pkg" / "selected.py").write_text("def selected():\n    pass\n", encoding="utf-8")

    data = XRayIndexer(str(repo)).explore_repo_data(focus_dirs=[focus], include_root_context=False, max_entries=1)

    assert data["entries"][0]["path"] == focus
    assert data["tree_text"].splitlines()[0].strip("├└─ ") == Path(focus).name


def test_deep_map_focus_uses_focus_relative_depth_and_explicit_context_mode(tmp_path, capsys):
    repo = tmp_path / "repo"
    focused = repo / "src" / "xray" / "core"
    (focused / "deeper").mkdir(parents=True)
    (repo / "src" / "other").mkdir()
    (repo / "README.md").write_text("context\n", encoding="utf-8")
    (focused / "indexer.py").write_text("def indexer():\n    pass\n", encoding="utf-8")
    (focused / "deeper" / "worker.py").write_text("def worker():\n    pass\n", encoding="utf-8")
    (repo / "src" / "other" / "ignored.py").write_text("def ignored():\n    pass\n", encoding="utf-8")

    assert cli.main(["map", str(repo), "--focus", "src/xray/core"]) == 0
    contextual = json.loads(capsys.readouterr().out)
    contextual_paths = {entry["path"] for entry in contextual["entries"]}
    assert {
        ".",
        "src",
        "src/xray",
        "src/xray/core",
        "src/xray/core/indexer.py",
        "src/xray/core/deeper",
        "src/xray/core/deeper/worker.py",
        "README.md",
    } <= contextual_paths
    assert "src/other" not in contextual_paths
    assert contextual["options"]["max_depth"] == 2
    assert contextual["options"]["focus_mode"] == "root_context"

    assert cli.main(["map", str(repo), "--focus", "src/xray/core/deeper/worker.py", "--strict-focus"]) == 0
    strict = json.loads(capsys.readouterr().out)
    strict_paths = {entry["path"] for entry in strict["entries"]}
    assert "src/xray/core/deeper/worker.py" in strict_paths
    assert "README.md" not in strict_paths
    assert "src/xray/core/indexer.py" not in strict_paths
    assert strict["options"]["include_root_context"] is False
    assert strict["options"]["focus_mode"] == "strict"


def test_mcp_deep_focus_defaults_are_relative_and_support_strict_mode(tmp_path):
    repo = tmp_path / "repo"
    focused = repo / "src" / "xray" / "core"
    focused.mkdir(parents=True)
    (repo / "README.md").write_text("context\n", encoding="utf-8")
    (focused / "indexer.py").write_text("def indexer():\n    pass\n", encoding="utf-8")

    async def exercise():
        from fastmcp import Client

        async with Client(mcp_server.mcp) as client:
            contextual = await client.call_tool(
                "call_tool",
                {"name": "explore_repo", "arguments": {"root_path": str(repo), "focus_dirs": ["src/xray/core"]}},
            )
            strict = await client.call_tool(
                "call_tool",
                {
                    "name": "explore_repo",
                    "arguments": {
                        "root_path": str(repo),
                        "focus_dirs": ["src/xray/core/indexer.py"],
                        "include_root_context": False,
                        "max_entries": 1,
                    },
                },
            )
            return structured_content(contextual), structured_content(strict)

    contextual, strict = asyncio.run(exercise())
    assert "src/xray/core/indexer.py" in {entry["path"] for entry in contextual["entries"]}
    assert "README.md" in {entry["path"] for entry in contextual["entries"]}
    assert contextual["options"]["max_depth"] == 2
    assert strict["options"]["focus_mode"] == "strict"
    assert [entry["path"] for entry in strict["entries"]] == ["src/xray/core/indexer.py"]
    assert "README.md" not in {entry["path"] for entry in strict["entries"]}


def test_real_multilanguage_inventory_visibility_and_filters(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text(
        "def public_py():\n    pass\n\ndef _private_py():\n    pass\n\ndef __dunder__():\n    pass\n",
        encoding="utf-8",
    )
    (repo / "sample.js").write_text(
        "export function exportedJs() {}\nfunction localJs() {}\nclass JsService { #privateJs() {} publicJs() {} }\n",
        encoding="utf-8",
    )
    (repo / "sample.ts").write_text(
        "export class TsService { public publicTs() {} private privateTs() {} #hashPrivate() {} }\n",
        encoding="utf-8",
    )
    (repo / "sample.go").write_text(
        "package demo\nfunc PublicGo() {}\nfunc privateGo() {}\n",
        encoding="utf-8",
    )
    indexer = XRayIndexer(str(repo))

    cases = [
        ("public_py", "public"),
        ("_private_py", "private"),
        ("__dunder__", "public"),
        ("exportedJs", "public"),
        ("localJs", "unknown"),
        ("#privateJs", "private"),
        ("publicJs", "public"),
        ("publicTs", "public"),
        ("privateTs", "private"),
        ("#hashPrivate", "private"),
        ("PublicGo", "public"),
        ("privateGo", "private"),
    ]
    for name, visibility in cases:
        matching = indexer.find_symbol(name, min_score=100, visibility=[visibility])
        rejected = indexer.find_symbol(
            name,
            min_score=100,
            visibility=[next(value for value in ("public", "private", "unknown") if value != visibility)],
        )
        assert any(symbol["name"] == name and symbol.get("visibility") == visibility for symbol in matching)
        assert all(symbol["name"] != name for symbol in rejected)


def test_impact_reports_when_raw_safety_bound_blocks_filtered_page(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "target.py"
    target.write_text("def work():\n    pass\n", encoding="utf-8")
    other = repo / "other.py"
    other.write_text("work()\n", encoding="utf-8")
    definition = {"file": str(target), "text": "work", "lines": "def work():", "range": {"start": {"line": 0}}}
    valid = {"file": str(other), "text": "work", "lines": "work()", "range": {"start": {"line": 0}}}
    indexer = XRayIndexer(str(repo))

    with (
        patch("xray.core.indexer.MAX_IMPACT_RAW_RESULTS", 4),
        patch(
            "xray.core.indexer.run_ast_grep_bounded",
            side_effect=[
                BoundedAstGrepResult(matches=[definition, valid], total_exact=False),
                BoundedAstGrepResult(matches=[definition, valid, definition, definition], total_exact=False),
            ],
        ),
    ):
        result = indexer.what_breaks(
            {"name": "work", "path": str(target), "start_line": 1, "end_line": 2}, max_results=2
        )

    assert result["total_count"] == 1
    assert result["total_exact"] is False
    assert result["execution_limited"] is True
    assert result["execution_cap"] == 4


def test_rule_explain_and_capabilities_are_read_only_and_bounded(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text("old(1)\n", encoding="utf-8")
    (repo / "rule.yml").write_text(
        "id: no-old\nlanguage: Python\nrule:\n  pattern: old($A)\nseverity: warning\n",
        encoding="utf-8",
    )
    indexer = XRayIndexer(str(repo))

    checked = indexer.check_rules("rule.yml", max_results=10)
    explained = indexer.explain_rules("rule.yml", source_limit=16)
    capabilities = indexer.capabilities()
    with patch(
        "xray.core.indexer.run_ast_grep",
        return_value=AstGrepResult("2 tests passed\n", "", 0),
    ) as run:
        tested = indexer.test_rules(test_dir=".")

    assert checked["valid"] is True and checked["returned"] == 1
    assert explained["valid"] is True
    assert explained["source_truncated"] is True
    assert len(explained["source"]) == 16
    assert explained["inspection_lines"] == explained["inspection"].splitlines()
    assert capabilities["replacement_plan_versions"] == ["xray.replace.v2"]
    assert capabilities["replacement_semantics"] == {
        "root_fingerprint_inputs": [
            "normalized_root",
            "git_commit_when_available",
            "query_including_selection",
            "affected_source_preimages",
        ],
        "selection_refinement_changes_root_fingerprint": True,
        "rollback_status": {
            "primary": True,
            "values": ["not_attempted", "succeeded", "failed"],
            "legacy_fields": ["rollback_attempted", "rollback_succeeded", "rollback_count"],
        },
    }
    assert capabilities["rule_selection"] == {
        "default": "repository root with ast-grep ignore defaults",
        "scopes": ["contained_paths", "ordered_globs"],
        "explicit_hidden_paths": "included",
    }
    assert capabilities["paging"] == {
        "continuable_min_limit": 1,
        "adaptive_page_size": True,
        "cursor_identity": ["command", "root", "query_scopes", "projection", "source_snapshot"],
    }
    assert capabilities["mutation_classes"]["guarded"]["mcp"] == ["apply_replacement", "apply_rule_fixes"]
    assert capabilities["mutation_classes"]["direct_legacy"]["mcp"] == ["rewrite_pattern"]
    assert capabilities["product"]["version"]
    assert capabilities["dependencies"]["ast_grep"]["available"] is True
    assert capabilities["healthy"] is True
    assert tested["ok"] is True
    assert "--skip-snapshot-tests" in run.call_args.args[0]
    assert "--color" in run.call_args.args[0]
    assert run.call_args.kwargs["cwd"] == repo


def test_cli_find_compact_scopes_scores_pages_and_preserves_full_v1(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    (repo / "src" / "second.py").write_text("def target_helper():\n    pass\n", encoding="utf-8")

    assert cli.main(["find", str(repo), "target", "--path", "src", "--language", "python", "--limit", "1"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["schema_version"] == "xray.cli.v3"
    assert first["ok"] is True
    assert first["returned"] == 1
    assert first["total"] >= 2
    assert first["total_exact"] is True
    assert first["truncated"] is True
    assert first["next_cursor"]
    assert first["symbols"][0]["score"] >= 60

    assert (
        cli.main(
            [
                "find",
                str(repo),
                "target",
                "--path",
                "src",
                "--language",
                "python",
                "--limit",
                "1",
                "--cursor",
                first["next_cursor"],
            ]
        )
        == 0
    )
    second = json.loads(capsys.readouterr().out)
    assert second["symbols"][0]["qualified_name"] != first["symbols"][0]["qualified_name"]

    assert cli.main(["find", str(repo), "target", "--detail", "full", "--limit", "1"]) == 0
    full = json.loads(capsys.readouterr().out)
    assert full["schema_version"] == "xray.cli.v1"


def test_cli_bounded_interface_read_symbol_and_symbol_at(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    sample = repo / "src" / "sample.py"

    assert cli.main(["interface", str(repo), "src/sample.py", "--limit", "1", "--max-members", "1"]) == 0
    interface = json.loads(capsys.readouterr().out)
    assert interface["schema_version"] == "xray.cli.v3"
    assert interface["interface"]["returned"] == 1
    assert interface["interface"]["completeness"]["complete"] is False

    assert cli.main(["find", str(repo), "target_function", "--limit", "1"]) == 0
    symbol = json.loads(capsys.readouterr().out)["symbols"][0]
    assert (
        cli.main(
            ["read-symbol", str(repo), "--symbol-json", json.dumps(symbol), "--max-lines", "1", "--max-bytes", "24"]
        )
        == 0
    )
    read = json.loads(capsys.readouterr().out)
    assert read["command"] == "read-symbol"
    assert read["result"]["returned_lines"] <= 1

    tampered = {**symbol, "name": "forged_target"}
    assert cli.main(["read-symbol", str(repo), "--symbol-json", json.dumps(tampered)]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert error["code"] == "symbol_mismatch"
    assert read["result"]["returned_bytes"] <= 24

    assert cli.main(["symbol-at", str(repo), "src/sample.py", str(symbol["start_line"])]) == 0
    at = json.loads(capsys.readouterr().out)
    assert at["found"] is True
    assert at["symbol"]["name"] == "target_function"
    assert sample.exists()


def test_cli_map_defaults_all_depth_limit_alias_capabilities_and_leaf_errors(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    assert cli.main(["explore", str(repo), "--limit", "2"]) == 0
    shallow = json.loads(capsys.readouterr().out)
    assert shallow["options"]["max_depth"] == 2
    assert shallow["options"]["max_entries"] == 2
    assert cli.main(["explore", str(repo), "--all-depths", "--limit", "2"]) == 0
    unlimited = json.loads(capsys.readouterr().out)
    assert unlimited["options"]["max_depth"] is None

    assert cli.main(["capabilities"]) == 0
    capabilities = json.loads(capsys.readouterr().out)
    assert capabilities["command"] == "capabilities"
    assert "repository" not in capabilities["capabilities"]
    assert cli.main(["doctor", str(repo)]) == 0
    doctor = json.loads(capsys.readouterr().out)
    assert doctor["invoked_as"] == "doctor"
    assert doctor["capabilities"]["repository"]["root_path"] == str(repo)

    assert cli.main(["replace", "plan", str(repo)]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["schema_version"] == "xray.cli.v3"
    assert error["command"] == "replace.plan"
    assert error["error"]["code"] == "invalid_request"


def test_compact_v3_defaults_and_explicit_v2_legacy_projection(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "service.py"
    source.write_text(
        "class Service:\n"
        "    def first(self):\n"
        "        return 1\n"
        "    def second(self):\n"
        "        return 2\n"
        "\n"
        "def helper():\n"
        "    return Service()\n",
        encoding="utf-8",
    )
    exact = {
        "name": "second",
        "owner": "Service",
        "qualified_name": "Service.second",
        "type": "method",
        "path": "service.py",
        "start_line": 4,
        "end_line": 5,
    }

    assert cli.main(["interface", str(repo), "service.py", "--schema", "v2", "--limit", "1"]) == 0
    compatible = json.loads(capsys.readouterr().out)
    assert compatible["schema_version"] == "xray.cli.v2"
    assert "returned_symbols" in compatible["interface"]
    assert "completeness" not in compatible["interface"]

    assert cli.main(["interface", str(repo), "service.py", "--limit", "1", "--max-members", "1"]) == 0
    incomplete = json.loads(capsys.readouterr().out)["interface"]
    assert incomplete["completeness"]["complete"] is False
    assert set(incomplete["completeness"]["reasons"]) == {"member_truncated", "page_truncated"}

    assert cli.main(["interface", str(repo), "--symbol-json", json.dumps(exact), "--max-members", "1"]) == 0
    selected = json.loads(capsys.readouterr().out)
    interface = selected["interface"]
    assert selected["schema_version"] == "xray.cli.v3" and selected["ok"] is True
    assert "returned_symbols" not in interface and "total_symbols" not in interface
    assert interface["returned"] == 1 and interface["total"] == 1
    assert interface["completeness"] == {"complete": True, "reasons": []}
    assert [item["name"] for item in interface["symbols"]] == ["Service"]
    assert [item["name"] for item in interface["symbols"][0]["members"]] == ["second"]

    exact_class = {
        "name": "Service",
        "qualified_name": "Service",
        "type": "class",
        "path": "service.py",
        "start_line": 1,
        "end_line": 5,
    }
    assert cli.main(["interface", str(repo), "--symbol-json", json.dumps(exact_class), "--max-members", "1"]) == 0
    selected_class = json.loads(capsys.readouterr().out)["interface"]
    assert [member["name"] for member in selected_class["symbols"][0]["members"]] == ["first"]
    assert selected_class["completeness"] == {"complete": False, "reasons": ["member_truncated"]}

    assert cli.main(["interface", str(repo), "--symbol-json", json.dumps(exact), "--detail", "full"]) == 2
    assert "--detail full" in json.loads(capsys.readouterr().err)["error"]
    assert cli.main(["interface", str(repo), "--symbol-json", json.dumps(exact), "--schema", "v2"]) == 2
    assert "--schema v2" in json.loads(capsys.readouterr().err)["error"]["message"]
    assert (
        cli.main(["interface", str(repo), "--symbol-json", json.dumps(exact), "--detail", "full", "--schema", "v2"])
        == 2
    )
    assert "--detail full" in json.loads(capsys.readouterr().err)["error"]

    impact_result = {
        "references": [
            {
                "file": str(source),
                "line": 5,
                "text": "capabilities = other\n        return capabilities()",
                "matched_text": "return capabilities()",
                "type": "call",
            }
        ],
        "total_count": 1,
        "raw_count": 3,
        "filtered_count": 2,
        "strategy": "structural",
        "note": "one reference",
        "total_exact": True,
        "execution_limited": False,
        "execution_cap": 51,
    }
    with patch.object(XRayIndexer, "what_breaks", return_value=impact_result):
        assert cli.main(["impact", str(repo), "--symbol-json", json.dumps(exact)]) == 0
    impact = json.loads(capsys.readouterr().out)
    assert impact["schema_version"] == "xray.cli.v3" and impact["ok"] is True
    assert "total_count" not in impact["impact"] and "raw_count" not in impact["impact"]
    assert impact["impact"]["total"] == 1
    assert impact["impact"]["total_exact"] is True
    assert impact["impact"]["references"][0]["text"] == "return capabilities()"
    assert impact["impact"]["diagnostics"]["raw_count"] == 3
    assert "total_exact" not in impact["impact"]["diagnostics"]

    assert cli.main(["capabilities", str(repo)]) == 0
    capabilities = json.loads(capsys.readouterr().out)
    contract = capabilities["capabilities"]
    assert capabilities["schema_version"] == "xray.cli.v3"
    assert contract["schema_contracts"]["cli_default"] == "xray.cli.v3"
    assert contract["schema_contracts"]["cli_legacy"] == ["xray.cli.v2"]
    assert contract["schema_contracts"]["mcp_default"] == "v3"
    assert contract["schema_contracts"]["mcp_legacy"] == ["v2"]
    assert contract["surfaces"]["cli"]["defaults"]["read_symbol"]["max_bytes"] == 65536
    assert contract["surfaces"]["mcp"]["cache"]["indexers"]["effective_limit"] >= 1
    assert contract["surfaces"]["mcp"]["defaults"]["read_interface_structured"]["schema"] == "v3"
    assert contract["surfaces"]["mcp"]["defaults"]["what_breaks"]["schema"] == "v3"
    assert "scan" in contract["surfaces"]["cli"]["operations"]["read_only"]
    assert contract["surfaces"]["cli"]["administrative"] == ["skill-install"]
    assert contract["surfaces"]["mcp"]["resource_templates"] == ["skill://xray-progressive-discovery/{path*}"]
    assert contract["cache"]["files"] == ["symbols.json", "inventory.json"]
    assert contract["bounds"]["replacement_total_bytes"] == 50 * 1024 * 1024

    assert cli.main(["explore", str(repo), "--limit", "1"]) == 0
    explore = json.loads(capsys.readouterr().out)
    assert explore["schema_version"] == "xray.cli.v3" and explore["ok"] is True

    assert cli.main(["interface", str(repo)]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["schema_version"] == "xray.cli.v3" and error["ok"] is False


def test_cli_rules_and_replacement_refinement_are_non_mutating(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    rule = repo / "rule.yml"
    rule.write_text(
        "id: no-old\nlanguage: Python\nrule:\n  pattern: target_function($A)\nseverity: warning\n",
        encoding="utf-8",
    )
    original = (repo / "src" / "sample.py").read_bytes()

    assert cli.main(["rules", "check", str(repo), "--rule", "rule.yml", "--limit", "5"]) == 0
    checked = json.loads(capsys.readouterr().out)
    assert checked["command"] == "rules.check"
    assert checked["result"]["valid"] is True
    assert checked["result"]["matches"]
    assert checked["result"]["matches"][0]["path"] == "src/sample.py"
    assert checked["result"]["matches"][0]["line"] >= 1
    assert not Path(checked["result"]["matches"][0]["path"]).is_absolute()

    assert cli.main(["rules", "check", str(repo), "--rule", "rule.yml", "--detail", "full"]) == 0
    full_check = json.loads(capsys.readouterr().out)
    assert "range" in full_check["result"]["matches"][0]
    assert cli.main(["rules", "explain", str(repo), "--rule", "rule.yml", "--source-limit", "8"]) == 0
    explained = json.loads(capsys.readouterr().out)
    assert explained["command"] == "rules.explain"
    assert explained["result"]["source_truncated"] is True
    assert (repo / "src" / "sample.py").read_bytes() == original

    assert (
        cli.main(
            [
                "replace",
                "plan",
                str(repo),
                "--pattern",
                "target_function($A)",
                "--replacement",
                "renamed($A)",
                "--lang",
                "python",
            ]
        )
        == 0
    )
    plan_envelope = json.loads(capsys.readouterr().out)
    plan_path = repo / "plan.json"
    plan_path.write_text(json.dumps(plan_envelope), encoding="utf-8")
    edit_id = plan_envelope["plan"]["files"][0]["edits"][0]["edit_id"]
    assert cli.main(["replace", "refine", str(repo), "--plan-file", str(plan_path), "--edit-id", edit_id]) == 0
    refined = json.loads(capsys.readouterr().out)
    assert refined["command"] == "replace.refine"
    assert refined["plan"]["query"]["selected_edit_ids"] == [edit_id]
    assert (repo / "src" / "sample.py").read_bytes() == original


def test_cli_ast_grep_validation_failures_use_exit_two_for_all_projections(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    invalid_rule = repo / "not-a-rule.txt"
    invalid_rule.write_text("not an ast-grep rule\n", encoding="utf-8")

    for extra in ([], ["--schema", "v2"], ["--format", "text"]):
        assert (
            cli.main(
                [
                    "search",
                    str(repo),
                    "--pattern",
                    "except Exception: pass",
                    "--lang",
                    "python",
                    *extra,
                ]
            )
            == 2
        )
        assert "Cannot parse query" in capsys.readouterr().err

    for command in ("check", "explain"):
        assert cli.main(["rules", command, str(repo), "--rule", invalid_rule.name]) == 2
        error = json.loads(capsys.readouterr().err)
        assert error["error"]["code"] == "invalid_request"


def test_interface_page_warnings_are_local_with_global_off_page_signal(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "service.py").write_text(
        "class Alpha:\n"
        "    def one(self): pass\n"
        "    def two(self): pass\n"
        "class Beta:\n"
        "    def one(self): pass\n"
        "    def two(self): pass\n",
        encoding="utf-8",
    )
    base = ["interface", str(repo), "service.py", "--limit", "1", "--max-members", "1"]
    assert cli.main(base) == 0
    first = json.loads(capsys.readouterr().out)["interface"]
    assert any("Alpha" in warning for warning in first["warnings"])
    assert all("Beta" not in warning for warning in first["warnings"])
    assert first["global_warnings"] == ["Additional symbols have bounded members on other pages."]

    assert cli.main([*base, "--cursor", first["next_cursor"]]) == 0
    second = json.loads(capsys.readouterr().out)["interface"]
    assert any("Beta" in warning for warning in second["warnings"])
    assert all("Alpha" not in warning for warning in second["warnings"])
    assert second["global_warnings"] == ["Additional symbols have bounded members on other pages."]


@pytest.mark.parametrize("initialize_git", [False, True])
def test_rule_selection_exposes_defaults_and_includes_explicit_hidden_paths(tmp_path, capsys, initialize_git):
    repo = tmp_path / "repo"
    repo.mkdir()
    if initialize_git:
        subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    hidden = repo / ".fixtures"
    hidden.mkdir()
    (hidden / "sample.py").write_text("old(1)\n", encoding="utf-8")
    (repo / "rule.yml").write_text(
        "id: no-old\nlanguage: Python\nrule:\n  pattern: old($A)\nseverity: warning\n",
        encoding="utf-8",
    )

    assert cli.main(["rules", "check", str(repo), "--rule", "rule.yml"]) == 0
    default = json.loads(capsys.readouterr().out)["result"]
    assert default["matches"] == []
    assert default["selection"]["default_root"] is True
    assert default["selection"]["ignore_policy"] == "ast_grep_defaults"

    scoped = ["rules", "check", str(repo), "--rule", "rule.yml", "--path", ".fixtures"]
    assert cli.main(scoped) == 0
    selected = json.loads(capsys.readouterr().out)["result"]
    assert selected["matches"][0]["path"] == ".fixtures/sample.py"
    assert selected["selection"]["paths"] == [".fixtures"]
    assert selected["selection"]["explicit_hidden_paths"] == "included"

    assert cli.main(["rules", "explain", str(repo), "--rule", "rule.yml", "--path", ".fixtures"]) == 0
    explained = json.loads(capsys.readouterr().out)["result"]
    assert explained["selection"]["paths"] == [".fixtures"]


@pytest.mark.parametrize("with_git_directory", [False, True])
def test_gitignore_wildmatch_anchoring_negation_nested_rules_and_builtin_policy(tmp_path, with_git_directory):
    repo = tmp_path / ("git-repo" if with_git_directory else "plain-repo")
    (repo / "ignored").mkdir(parents=True)
    (repo / "src" / "deep").mkdir(parents=True)
    (repo / ".codex").mkdir()
    if with_git_directory:
        (repo / ".git").mkdir()
    (repo / ".gitignore").write_text("/root_only.py\nignored/*.py\n!ignored/keep.py\n", encoding="utf-8")
    (repo / "src" / ".gitignore").write_text("/secret.py\n", encoding="utf-8")
    for relative in (
        "root_only.py",
        "src/root_only.py",
        "ignored/drop.py",
        "ignored/keep.py",
        "src/secret.py",
        "src/deep/secret.py",
        ".codex/state.py",
    ):
        (repo / relative).write_text("def visible():\n    pass\n", encoding="utf-8")

    indexer = XRayIndexer(str(repo))
    default_paths = {entry["path"] for entry in indexer.explore_repo_data(max_depth=4)["entries"]}
    unfiltered = indexer.explore_repo_data(max_depth=4, use_default_exclusions=False)
    unfiltered_paths = {entry["path"] for entry in unfiltered["entries"]}

    assert "root_only.py" not in default_paths
    assert "src/root_only.py" in default_paths
    assert "ignored/drop.py" not in default_paths
    assert "ignored/keep.py" in default_paths
    assert "src/secret.py" not in default_paths
    assert "src/deep/secret.py" in default_paths
    assert ".codex/state.py" not in default_paths
    assert ".codex/state.py" in unfiltered_paths
    assert "root_only.py" not in unfiltered_paths
    assert unfiltered["options"]["use_default_exclusions"] is False


def test_explore_cli_bounds_and_reports_truncated_output(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["explore", str(repo), "--max-entries", "2"])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["entries"]) == 2
    assert result["truncated"] is True
    assert result["options"]["max_entries"] == 2
    assert "truncated at 2 entries" in result["warnings"][0]
    assert "tree_text" not in result


def test_explore_full_preserves_v1_tree_and_absolute_paths(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)
    assert cli.main(["explore", str(repo), "--detail", "full"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schema_version"] == "xray.cli.v1"
    assert result["ok"] is True
    assert "tree_text" in result
    assert all("abs_path" in entry for entry in result["entries"])


def test_explore_text_reports_truncated_output(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["explore", str(repo), "--max-entries", "1", "--format", "text"])

    assert exit_code == 0
    assert "output truncated at 1 entries" in capsys.readouterr().out


def test_mcp_explore_result_reports_truncated_output(tmp_path):
    repo = write_sample_repo(tmp_path)

    result = cast(
        dict[str, Any],
        mcp_server.build_explore_result(
            XRayIndexer(str(repo)),
            max_depth=None,
            include_symbols=False,
            focus_dirs=None,
            max_symbols_per_file=5,
            max_entries=2,
        ),
    )

    assert len(result["entries"]) == 2
    assert result["truncated"] is True
    assert result["options"]["max_entries"] == 2
    assert "truncated at 2 entries" in result["warnings"][0]


def test_explore_cli_rejects_nonpositive_max_entries(tmp_path, capsys):
    repo = write_sample_repo(tmp_path)

    exit_code = cli.main(["explore", str(repo), "--max-entries", "0"])

    assert exit_code == 2
    assert json.loads(capsys.readouterr().err)["error"]["message"] == "--max-entries must be 1 or greater."


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
