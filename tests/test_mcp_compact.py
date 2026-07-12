from pathlib import Path
from unittest.mock import patch

import pytest

from xray import mcp_server
from xray.core.indexer import XRayIndexer


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
        first = mcp_server.search_pattern(str(repo), "old($A)", "python", limit=2)

    assert first["matches"] == [
        {"path": "sample.py", "line": 1, "column": 5, "text": "old(0)", "captures": {"A": "0"}},
        {"path": "sample.py", "line": 2, "column": 5, "text": "old(1)", "captures": {"A": "1"}},
    ]
    assert (first["returned"], first["total"], first["truncated"]) == (2, 3, True)

    with patch.object(XRayIndexer, "search_pattern", return_value=raw):
        second = mcp_server.search_pattern(str(repo), "old($A)", "python", limit=2, cursor=first["next_cursor"])
    assert [match["text"] for match in second["matches"]] == ["old(2)"]
    assert second["truncated"] is False
    assert "next_cursor" not in second

    with patch.object(XRayIndexer, "search_pattern", return_value=raw):
        full = mcp_server.search_pattern(str(repo), "old($A)", detail="full")
    assert full["matches"] == raw
    assert full["match_count"] == 3
    assert full["pattern"] == "old($A)"


def test_mcp_cursor_validation_happens_before_search(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    with patch.object(XRayIndexer, "search_pattern", return_value=raw_matches(repo)):
        cursor = mcp_server.search_pattern(str(repo), "old($A)", limit=1)["next_cursor"]

    with patch.object(XRayIndexer, "search_pattern") as search:
        result = mcp_server.search_pattern(str(repo), "other($A)", cursor=cursor)
    search.assert_not_called()
    assert "does not match" in result["error"]


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
        result = tool(str(repo), "sample.py", limit=1)
    outline.assert_called_once_with("sample.py", item)
    assert result["items"] == [{"path": "sample.py", "line": 1, "name": "one", "signature": "import one"}]
    assert (result["returned"], result["total"], result["truncated"]) == (1, 2, True)

    with patch.object(XRayIndexer, "file_outline_items", return_value=raw):
        full = tool(str(repo), "sample.py", detail="full")
    assert full["items"] == raw
    assert full["file_path"] == "sample.py"


def test_mcp_mutating_tools_validate_first_and_do_not_offer_continuation(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    with patch.object(XRayIndexer, "rewrite_pattern") as rewrite:
        invalid = mcp_server.rewrite_pattern(str(repo), "old($A)", "new($A)", limit=-1)
    rewrite.assert_not_called()
    assert "limit must be 0 or greater" in invalid["error"]

    summary = {"matches": raw_matches(repo), "match_count": 3, "files_modified": ["sample.py"], "file_count": 1}
    with patch.object(XRayIndexer, "rewrite_pattern", return_value=summary):
        compact = mcp_server.rewrite_pattern(str(repo), "old($A)", "new($A)")
    assert compact == {"match_count": 3, "files_modified": ["sample.py"], "file_count": 1}

    with patch.object(XRayIndexer, "scan_rules") as scan:
        invalid_fix = mcp_server.scan_rules(str(repo), "rule.yml", fix=True, cursor="invalid")
    scan.assert_not_called()
    assert "cannot be used when fix is true" in invalid_fix["error"]

    with patch.object(XRayIndexer, "scan_rules", return_value=raw_matches(repo)):
        fixed = mcp_server.scan_rules(str(repo), "rule.yml", fix=True, limit=1)
    assert fixed["truncated"] is True
    assert "next_cursor" not in fixed


def test_mcp_explore_compact_default_and_full_opt_in(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    indexer = XRayIndexer(str(repo))
    compact = mcp_server.build_explore_result(indexer, None, False, None, 5)
    full = mcp_server.build_explore_result(indexer, None, False, None, 5, detail="full")

    assert "tree_text" not in compact
    assert all("abs_path" not in entry for entry in compact["entries"])
    assert full["tree_text"].startswith(str(repo))
    assert all("abs_path" in entry for entry in full["entries"])
