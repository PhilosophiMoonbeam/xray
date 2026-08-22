import asyncio
import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from xray import mcp_server
from xray.core.indexer import XRayIndexer


def error_value(result: Any) -> dict[str, Any]:
    assert result.is_error is True
    assert result.structured_content is not None
    return result.structured_content["error"]


def success_value(result: Any) -> dict[str, Any]:
    assert isinstance(result, dict)
    return cast(dict[str, Any], result)


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text("def old(value):\n    return old(value)\n", encoding="utf-8")
    return repo


def raw_matches(repo: Path) -> list[dict]:
    return [
        {
            "file": str(repo / "sample.py"),
            "text": f"old({value})",
            "range": {"start": {"line": value, "column": 4}},
            "metaVariables": {"single": {"A": {"text": str(value)}}, "multi": {}, "transformed": {}},
        }
        for value in range(3)
    ]


def test_mcp_search_compacts_pages_and_preserves_full_detail(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    raw = raw_matches(repo)
    with patch.object(XRayIndexer, "search_pattern", return_value=raw):
        first = success_value(mcp_server.search_pattern(str(repo), "old($A)", "python", limit=2))

    assert first["matches"] == [
        {"path": "sample.py", "line": 1, "column": 5, "text": "old(0)", "captures": {"A": "0"}},
        {"path": "sample.py", "line": 2, "column": 5, "text": "old(1)", "captures": {"A": "1"}},
    ]
    assert (first["returned"], first["total"], first["truncated"]) == (2, 3, True)

    with patch.object(XRayIndexer, "search_pattern", return_value=raw):
        second = success_value(
            mcp_server.search_pattern(str(repo), "old($A)", "python", limit=2, cursor=first["next_cursor"])
        )
    assert [match["text"] for match in second["matches"]] == ["old(2)"]
    assert second["truncated"] is False
    assert "next_cursor" not in second

    with patch.object(XRayIndexer, "search_pattern", return_value=raw):
        full = success_value(mcp_server.search_pattern(str(repo), "old($A)", detail="full"))
    assert full["matches"] == raw
    assert full["match_count"] == 3
    assert full["pattern"] == "old($A)"


def test_mcp_search_projects_semantic_multi_captures(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "sample.py").write_text("invoke(first, second, mode=True)\n", encoding="utf-8")

    compact = success_value(mcp_server.search_pattern(str(repo), "invoke($$$ARGS)", "python"))
    assert compact["matches"][0]["captures"]["ARGS"] == ["first", "second", "mode=True"]

    full = success_value(mcp_server.search_pattern(str(repo), "invoke($$$ARGS)", "python", detail="full"))
    assert [value["text"] for value in full["matches"][0]["metaVariables"]["multi"]["ARGS"]] == [
        "first",
        ",",
        "second",
        ",",
        "mode=True",
    ]


def test_mcp_read_symbol_rejects_tampered_exact_identity_with_typed_error(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    found = XRayIndexer(str(repo)).find_symbol("old", min_score=100)[0]

    genuine = success_value(mcp_server.read_symbol(str(repo), dict(found)))
    assert genuine["symbol"]["name"] == "old"

    result = mcp_server.read_symbol(str(repo), {**found, "qualified_name": "forged.old"})
    error = error_value(result)
    assert error["code"] == "symbol_mismatch"
    assert "current inventory" in error["message"]


def test_mcp_cursor_validation_happens_before_search(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    with patch.object(XRayIndexer, "search_pattern", return_value=raw_matches(repo)):
        cursor = success_value(mcp_server.search_pattern(str(repo), "old($A)", limit=1))["next_cursor"]

    with patch.object(XRayIndexer, "search_pattern") as search:
        result = mcp_server.search_pattern(str(repo), "other($A)", cursor=cursor)
    search.assert_not_called()
    assert "does not match" in error_value(result)["message"]


@pytest.mark.parametrize(("tool", "item"), [(mcp_server.file_imports, "imports"), (mcp_server.file_exports, "exports")])
def test_mcp_outline_tools_flatten_before_paging(tmp_path: Path, tool, item: str) -> None:
    repo = make_repo(tmp_path)
    raw = [
        {
            "path": str(repo / "sample.py"),
            "items": [
                {"name": "one", "signature": "import one", "range": {"start": {"line": 0}}},
                {"name": "two", "signature": "import two", "range": {"start": {"line": 1}}},
            ],
        }
    ]
    with patch.object(XRayIndexer, "file_outline_items", return_value=raw) as outline:
        result = success_value(tool(str(repo), "sample.py", limit=1))
    outline.assert_called_once_with("sample.py", item)
    assert result["items"] == [{"path": "sample.py", "line": 1, "name": "one", "signature": "import one"}]
    assert (result["returned"], result["total"], result["truncated"]) == (1, 2, True)

    with patch.object(XRayIndexer, "file_outline_items", return_value=raw):
        full = success_value(tool(str(repo), "sample.py", detail="full"))
    assert full["items"] == raw
    assert full["file_path"] == "sample.py"


def test_mcp_mutating_tools_validate_first_and_do_not_offer_continuation(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    with patch.object(XRayIndexer, "rewrite_pattern") as rewrite:
        invalid = mcp_server.rewrite_pattern(str(repo), "old($A)", "new($A)", limit=-1)
    rewrite.assert_not_called()
    assert "limit must be 0 or greater" in error_value(invalid)["message"]

    summary = {"matches": raw_matches(repo), "match_count": 3, "files_modified": ["sample.py"], "file_count": 1}
    with patch.object(XRayIndexer, "rewrite_pattern", return_value=summary) as rewrite:
        compact = mcp_server.rewrite_pattern(str(repo), "old($A)", "new($A)", lang="python")
    rewrite.assert_called_once_with("old($A)", "new($A)", "python")
    assert compact == {"match_count": 3, "files_modified": ["sample.py"], "file_count": 1}

    with patch.object(XRayIndexer, "scan_rules", return_value=raw_matches(repo)):
        scanned = success_value(mcp_server.scan_rules(str(repo), "rule.yml", limit=1))
    assert scanned["truncated"] is True
    assert scanned["next_cursor"]

    with patch.object(XRayIndexer, "apply_replacement") as apply:
        invalid_rule_plan = mcp_server.apply_rule_fixes(str(repo), {"query": {"change": {"kind": "pattern"}}}, "x")
    apply.assert_not_called()
    assert "change kind is rule" in error_value(invalid_rule_plan)["message"]


def test_mcp_explore_compact_default_and_full_opt_in(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    indexer = XRayIndexer(str(repo))
    compact = success_value(mcp_server.build_explore_result(indexer, None, False, None, 5))
    full = success_value(mcp_server.build_explore_result(indexer, None, False, None, 5, detail="full"))

    assert "tree_text" not in compact
    assert all("abs_path" not in entry for entry in compact["entries"])
    assert full["tree_text"].startswith(str(repo))
    assert all("abs_path" in entry for entry in full["entries"])


def test_mcp_protocol_errors_natural_discovery_and_annotations(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    async def exercise():
        from fastmcp import Client

        async with Client(mcp_server.mcp) as client:
            visible = await client.list_tools()
            invalid = await client.call_tool(
                "call_tool",
                {"name": "search_pattern", "arguments": {"root_path": str(repo), "pattern": "old", "limit": -1}},
                raise_on_error=False,
            )
            searches = {}
            for term in ("lookup", "blast radius", "callers", "rename", "safe code replacement", "help", "workflow"):
                result = await client.call_tool("search_tools", {"pattern": term})
                assert result.structured_content is not None
                searches[term] = result.structured_content["matches"]
            scan_result = await client.call_tool("search_tools", {"pattern": "scan_rules", "detail": "full"})
            fixes_result = await client.call_tool("search_tools", {"pattern": "apply_rule_fixes", "detail": "full"})
            assert scan_result.structured_content is not None
            assert fixes_result.structured_content is not None
            scan = scan_result.structured_content["matches"][0]
            fixes = fixes_result.structured_content["matches"][0]
            return visible, invalid, searches, scan, fixes

    visible, invalid, searches, scan, fixes = asyncio.run(exercise())

    assert [tool.name for tool in visible] == ["search_tools", "call_tool"]
    assert invalid.is_error is True
    assert invalid.structured_content == {
        "error": {"code": "invalid_request", "message": "limit must be 1 or greater for a continuable read."}
    }
    assert json.loads(cast(Any, invalid.content[0]).text) == invalid.structured_content
    assert any(match["name"] == "find_symbol" for match in searches["lookup"])
    assert searches["blast radius"][0]["name"] == "what_breaks"
    assert searches["callers"][0]["name"] == "what_breaks"
    assert any(match["name"] == "plan_replacement" for match in searches["rename"])
    assert any(match["name"] == "plan_replacement" for match in searches["safe code replacement"])
    assert any(match["name"] == "xray_capabilities" for match in searches["help"])
    assert searches["workflow"][0]["name"] == "xray_capabilities"
    assert scan["annotations"]["readOnlyHint"] is True
    assert scan["annotations"]["destructiveHint"] is False
    assert "fix" not in scan["inputSchema"]["properties"]
    assert fixes["annotations"]["readOnlyHint"] is False
    assert fixes["annotations"]["destructiveHint"] is True


def test_mcp_find_reads_capabilities_rules_and_replacement_refinement(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "second.py").write_text("def old_helper():\n    return old(2)\n", encoding="utf-8")
    (repo / "rule.yml").write_text(
        "id: no-old\nlanguage: Python\nrule:\n  pattern: old($A)\nseverity: warning\n",
        encoding="utf-8",
    )

    async def call(name: str, arguments: dict) -> dict:
        from fastmcp import Client

        async with Client(mcp_server.mcp) as client:
            result = await client.call_tool("call_tool", {"name": name, "arguments": arguments})
            assert result.structured_content is not None
            return result.structured_content

    first = asyncio.run(call("find_symbol", {"root_path": str(repo), "query": "old", "limit": 1}))
    assert first["returned"] == 1
    assert first["total"] >= 2
    assert first["symbols"][0]["score"] >= 60
    second = asyncio.run(
        call(
            "find_symbol",
            {"root_path": str(repo), "query": "old", "limit": 3, "cursor": first["next_cursor"]},
        )
    )
    assert first["symbols"][0]["qualified_name"] not in {symbol["qualified_name"] for symbol in second["symbols"]}
    nonsense = asyncio.run(call("find_symbol", {"root_path": str(repo), "query": "unrelated behavior phrase"}))
    assert nonsense["symbols"] == []

    exact = first["symbols"][0]
    read = asyncio.run(
        call(
            "read_symbol",
            {"root_path": str(repo), "exact_symbol": exact, "max_lines": 1, "max_bytes": 24},
        )
    )
    assert read["returned_lines"] <= 1 and read["returned_bytes"] <= 24
    at = asyncio.run(
        call(
            "symbol_at",
            {"root_path": str(repo), "file_path": exact["path"], "line": exact["start_line"]},
        )
    )
    assert at["found"] is True

    capabilities = asyncio.run(call("xray_capabilities", {"root_path": str(repo)}))
    assert capabilities["replacement_plan_versions"] == ["xray.replace.v2"]
    checked = asyncio.run(call("check_rules", {"root_path": str(repo), "rule_path": "rule.yml", "limit": 1}))
    checked_full = asyncio.run(call("check_rules", {"root_path": str(repo), "rule_path": "rule.yml", "detail": "full"}))
    explained = asyncio.run(call("explain_rules", {"root_path": str(repo), "rule_path": "rule.yml", "source_limit": 8}))
    assert checked["valid"] is True
    assert checked["matches"][0]["path"] in {"sample.py", "second.py"}
    assert checked["matches"][0]["line"] >= 1
    assert "range" in checked_full["matches"][0]
    assert explained["source_truncated"] is True

    plan = asyncio.run(
        call(
            "plan_replacement",
            {
                "root_path": str(repo),
                "pattern": "old($A)",
                "replacement": "new($A)",
                "lang": "python",
            },
        )
    )
    edit_id = plan["files"][0]["edits"][0]["edit_id"]
    refined = asyncio.run(
        call(
            "refine_replacement",
            {"root_path": str(repo), "plan": plan, "edit_ids": [edit_id]},
        )
    )
    assert refined["query"]["selected_edit_ids"] == [edit_id]


def test_mcp_v3_exact_interface_and_named_impact_diagnostics(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    source = repo / "sample.py"
    source.write_text(
        "class Service:\n    def first(self):\n        return 1\n    def second(self):\n        return 2\n",
        encoding="utf-8",
    )
    exact = {
        "name": "second",
        "owner": "Service",
        "qualified_name": "Service.second",
        "type": "method",
        "path": "sample.py",
        "abs_path": str(source),
        "start_line": 4,
        "end_line": 5,
    }

    interface = success_value(mcp_server.read_interface_structured(str(repo), exact_symbol=exact, max_members=1))
    assert interface["completeness"] == {"complete": True, "reasons": []}
    assert "returned_symbols" not in interface and interface["returned"] == 1
    assert interface["symbols"][0]["members"][0]["name"] == "second"

    result = {
        "references": [{"file": str(source), "line": 5, "text": "return 2", "type": "read"}],
        "total_count": 1,
        "raw_count": 2,
        "filtered_count": 1,
        "strategy": "structural",
        "note": "one reference",
        "total_exact": True,
        "execution_limited": False,
        "execution_cap": 51,
    }
    with patch.object(XRayIndexer, "what_breaks", return_value=result):
        impact = success_value(mcp_server.what_breaks(exact))
    assert impact["total"] == 1 and "total_count" not in impact
    assert impact["total_exact"] is True
    assert impact["diagnostics"]["raw_count"] == 2

    compatible_error = mcp_server.read_interface_structured(str(repo), exact_symbol=exact, schema="v2")
    assert error_value(compatible_error)["code"] == "invalid_request"
