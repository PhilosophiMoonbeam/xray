from pathlib import Path
from unittest.mock import patch

import pytest

from xray import cli
from xray.core.ast_grep import AstGrepError, AstGrepResult
from xray.core.indexer import XRayIndexer


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text(
        "def old(value):\n    return value\n\n\ndef caller():\n    return old(1)\n", encoding="utf-8"
    )
    return repo


def test_search_pattern_passes_language_and_root(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    with patch("xray.core.indexer.run_ast_grep", return_value=AstGrepResult('[{"file":"sample.py"}]', "", 0)) as run:
        result = XRayIndexer(str(repo)).search_pattern("old($A)", "python")

    assert result == [{"file": "sample.py"}]
    run.assert_called_once_with(
        ["run", "--pattern", "old($A)", "--json=compact", "--lang", "python", str(repo.resolve())]
    )


def test_rewrite_pattern_summarizes_unique_files(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    output = '[{"file":"sample.py"},{"file":"sample.py"}]'
    with patch(
        "xray.core.indexer.run_ast_grep",
        side_effect=[AstGrepResult(output, "", 0), AstGrepResult("", "", 0)],
    ) as run:
        result = XRayIndexer(str(repo)).rewrite_pattern("old($A)", "new($A)")

    assert result["match_count"] == 2
    assert result["files_modified"] == ["sample.py"]
    assert run.call_args_list[0].args[0] == [
        "run",
        "--pattern",
        "old($A)",
        "--json=compact",
        str(repo.resolve()),
    ]
    assert run.call_args_list[1].args[0] == [
        "run",
        "--pattern",
        "old($A)",
        "--rewrite",
        "new($A)",
        "--update-all",
        str(repo.resolve()),
    ]


@pytest.mark.parametrize("item", ["imports", "exports"])
def test_file_outline_items_resolves_repo_file(tmp_path: Path, item: str) -> None:
    repo = make_repo(tmp_path)
    with patch("xray.core.indexer.run_ast_grep", return_value=AstGrepResult("[]", "", 0)) as run:
        assert XRayIndexer(str(repo)).file_outline_items("sample.py", item) == []

    run.assert_called_once_with(["outline", f"--items={item}", "--json=compact", str((repo / "sample.py").resolve())])


def test_file_outline_items_rejects_escape(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("pass\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside repository root"):
        XRayIndexer(str(repo)).file_outline_items(str(outside), "imports")


def test_scan_rules_uses_config_and_optional_fix(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    config = repo / "sgconfig.yml"
    config.write_text("ruleDirs: [rules]\n", encoding="utf-8")
    with patch(
        "xray.core.indexer.run_ast_grep",
        side_effect=[AstGrepResult("[]", "", 0), AstGrepResult("", "", 0)],
    ) as run:
        assert XRayIndexer(str(repo)).scan_rules("sgconfig.yml", fix=True) == []

    assert run.call_args_list[0].args[0] == [
        "scan",
        "--config",
        str(config.resolve()),
        "--json=compact",
        str(repo.resolve()),
    ]
    assert run.call_args_list[1].args[0] == [
        "scan",
        "--config",
        str(config.resolve()),
        "--update-all",
        str(repo.resolve()),
    ]


@pytest.mark.parametrize(
    ("argv", "method", "return_value", "command", "payload_key"),
    [
        (["search", "{root}", "-p", "old($A)", "-l", "python"], "search_pattern", [], "search", "matches"),
        (
            ["rewrite", "{root}", "-p", "old($A)", "-r", "new($A)"],
            "rewrite_pattern",
            {"matches": [], "match_count": 0, "files_modified": [], "file_count": 0},
            "rewrite",
            "files_modified",
        ),
        (["scan", "{root}", "--rule", "sgconfig.yml", "--fix"], "scan_rules", [], "scan", "matches"),
        (["imports", "{root}", "sample.py"], "file_outline_items", [], "imports", "items"),
        (["exports", "{root}", "sample.py"], "file_outline_items", [], "exports", "items"),
    ],
)
def test_structural_cli_commands_emit_standard_envelopes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    method: str,
    return_value: object,
    command: str,
    payload_key: str,
) -> None:
    import json

    repo = make_repo(tmp_path)
    (repo / "sgconfig.yml").write_text("ruleDirs: [rules]\n", encoding="utf-8")
    argv = [str(repo) if value == "{root}" else value for value in argv]
    with patch.object(XRayIndexer, method, return_value=return_value):
        assert cli.main(argv) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "xray.cli.v2"
    assert "ok" not in output
    assert output["command"] == command
    assert payload_key in output


@pytest.mark.parametrize(
    ("argv", "method", "return_value", "expected"),
    [
        (
            ["search", "{root}", "-p", "old($A)"],
            "search_pattern",
            [{"file": "sample.py", "range": {"start": {"line": 4}}, "text": "old(1)"}],
            "sample.py:5\told(1)\n",
        ),
        (
            ["rewrite", "{root}", "-p", "old($A)", "-r", "new($A)"],
            "rewrite_pattern",
            {"matches": [], "match_count": 2, "files_modified": ["sample.py"], "file_count": 1},
            "2 matches rewritten in 1 file\nsample.py\n",
        ),
        (
            ["scan", "{root}", "--rule", "sgconfig.yml"],
            "scan_rules",
            [{"file": "sample.py", "ruleId": "no-old", "text": "old(1)"}],
            "sample.py\told(1)\n",
        ),
        (
            ["imports", "{root}", "sample.py"],
            "file_outline_items",
            [
                {
                    "path": "sample.py",
                    "items": [
                        {
                            "name": "pathlib",
                            "signature": "from pathlib import Path",
                            "range": {"start": {"line": 2}},
                        }
                    ],
                }
            ],
            "sample.py:3\tfrom pathlib import Path\n",
        ),
        (
            ["exports", "{root}", "sample.py"],
            "file_outline_items",
            [{"name": "caller"}],
            "caller\n",
        ),
    ],
)
def test_structural_cli_commands_support_lossy_text(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    method: str,
    return_value: object,
    expected: str,
) -> None:
    repo = make_repo(tmp_path)
    argv = [str(repo) if value == "{root}" else value for value in argv]
    argv.extend(["--format", "text", "--pretty"])
    with patch.object(XRayIndexer, method, return_value=return_value):
        assert cli.main(argv) == 0

    captured = capsys.readouterr()
    assert captured.out == expected
    assert captured.err == ""


def test_structural_text_parse_error_is_plain_text(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["search", ".", "--format", "text"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("xray search: error:")
    assert not captured.err.lstrip().startswith("{")


def test_structural_text_runtime_error_is_plain_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path)
    with patch.object(XRayIndexer, "search_pattern", side_effect=AstGrepError("bad pattern")):
        assert cli.main(["search", str(repo), "-p", "(", "--format", "text"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "xray: bad pattern\n"


def test_search_compacts_raw_matches_and_pages_with_bound_cursor(tmp_path: Path, capsys) -> None:
    import json

    repo = make_repo(tmp_path)
    raw = [
        {
            "file": str(repo / "sample.py"),
            "text": f"old({value})",
            "range": {"start": {"line": value, "column": 4}, "end": {"line": value, "column": 10}},
            "metaVariables": {
                "single": {"A": {"text": str(value), "range": {"start": {"line": value}}}},
                "multi": {},
                "transformed": {},
            },
        }
        for value in range(3)
    ]
    with patch.object(XRayIndexer, "search_pattern", return_value=raw):
        assert cli.main(["search", str(repo), "-p", "old($A)", "--limit", "2"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["schema_version"] == "xray.cli.v2"
    assert first["matches"] == [
        {"path": "sample.py", "line": 1, "column": 5, "text": "old(0)", "captures": {"A": "0"}},
        {"path": "sample.py", "line": 2, "column": 5, "text": "old(1)", "captures": {"A": "1"}},
    ]
    assert (first["returned"], first["total"], first["truncated"]) == (2, 3, True)
    assert "range" not in json.dumps(first["matches"])

    with patch.object(XRayIndexer, "search_pattern", return_value=raw):
        assert cli.main(["search", str(repo), "-p", "old($A)", "--limit", "2", "--cursor", first["next_cursor"]]) == 0
    second = json.loads(capsys.readouterr().out)
    assert [match["text"] for match in second["matches"]] == ["old(2)"]
    assert second["truncated"] is False
    assert "next_cursor" not in second


def test_search_full_preserves_raw_payload_and_v1_envelope(tmp_path: Path, capsys) -> None:
    import json

    repo = make_repo(tmp_path)
    raw = [{"file": "sample.py", "range": {"start": {"line": 1}}, "metaVariables": {"single": {}}}]
    with patch.object(XRayIndexer, "search_pattern", return_value=raw):
        assert cli.main(["search", str(repo), "-p", "old($A)", "--detail", "full"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schema_version"] == "xray.cli.v1"
    assert result["ok"] is True
    assert result["matches"] == raw


def test_rewrite_compact_omits_matches_and_invalid_paging_does_not_mutate(tmp_path: Path, capsys) -> None:
    import json

    repo = make_repo(tmp_path)
    summary = {"matches": [{"file": "sample.py"}], "match_count": 1, "files_modified": ["sample.py"], "file_count": 1}
    with patch.object(XRayIndexer, "rewrite_pattern", return_value=summary) as rewrite:
        assert cli.main(["rewrite", str(repo), "-p", "old($A)", "-r", "new($A)"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert "matches" not in result
    assert result["match_count"] == 1
    rewrite.assert_called_once()

    with patch.object(XRayIndexer, "rewrite_pattern") as rewrite:
        assert cli.main(["rewrite", str(repo), "-p", "old($A)", "-r", "new($A)", "--limit", "-1"]) == 2
    rewrite.assert_not_called()


def test_cursor_is_query_bound_and_scan_fix_rejects_cursor_before_mutation(tmp_path: Path, capsys) -> None:
    import json

    repo = make_repo(tmp_path)
    raw = [{"file": "sample.py", "text": str(value)} for value in range(2)]
    with patch.object(XRayIndexer, "search_pattern", return_value=raw):
        assert cli.main(["search", str(repo), "-p", "old($A)", "--limit", "1"]) == 0
    cursor = json.loads(capsys.readouterr().out)["next_cursor"]

    with patch.object(XRayIndexer, "search_pattern") as search:
        assert cli.main(["search", str(repo), "-p", "other($A)", "--cursor", cursor]) == 2
    search.assert_not_called()
    assert "does not match" in json.loads(capsys.readouterr().err)["error"]

    with patch.object(XRayIndexer, "scan_rules") as scan:
        assert cli.main(["scan", str(repo), "--rule", "rule.yml", "--fix", "--cursor", cursor]) == 2
    scan.assert_not_called()


@pytest.mark.parametrize("command", ["imports", "exports"])
def test_outline_compact_flattens_groups_before_limiting(tmp_path: Path, capsys, command: str) -> None:
    import json

    repo = make_repo(tmp_path)
    raw = [
        {
            "path": str(repo / "sample.py"),
            "items": [
                {"name": "one", "signature": "import one", "range": {"start": {"line": 0, "column": 0}}},
                {"name": "two", "signature": "import two", "range": {"start": {"line": 1, "column": 0}}},
            ],
        }
    ]
    with patch.object(XRayIndexer, "file_outline_items", return_value=raw):
        assert cli.main([command, str(repo), "sample.py", "--limit", "1"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["items"] == [{"path": "sample.py", "line": 1, "column": 1, "name": "one", "signature": "import one"}]
    assert (result["returned"], result["total"], result["truncated"]) == (1, 2, True)


def test_structural_search_and_rewrite_run_end_to_end(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    indexer = XRayIndexer(str(repo))

    matches = indexer.search_pattern("old($A)", "python")
    assert len(matches) == 1
    assert matches[0]["metaVariables"]["single"]["A"]["text"] == "1"

    summary = indexer.rewrite_pattern("old($A)", "new($A)", "python")
    assert summary["match_count"] == 1
    assert summary["file_count"] == 1
    assert "return new(1)" in (repo / "sample.py").read_text(encoding="utf-8")


def test_language_scoped_rewrite_does_not_mutate_pattern_text_in_yaml(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    rule = repo / "no-old.yml"
    original_rule = "id: no-old-call\nlanguage: Python\nrule:\n  pattern: old($A)\nseverity: warning\n"
    rule.write_text(original_rule, encoding="utf-8")

    summary = XRayIndexer(str(repo)).rewrite_pattern("old($A)", "new($A)", "python")

    assert summary["match_count"] == 1
    assert summary["file_count"] == 1
    assert summary["files_modified"] == [str(repo / "sample.py")]
    assert "return new(1)" in (repo / "sample.py").read_text(encoding="utf-8")
    assert rule.read_text(encoding="utf-8") == original_rule


def test_rule_scan_fix_runs_end_to_end(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "no-old.yml").write_text(
        "id: no-old-call\nlanguage: Python\nrule:\n  pattern: old($A)\nfix: new($A)\nseverity: warning\n",
        encoding="utf-8",
    )

    matches = XRayIndexer(str(repo)).scan_rules("no-old.yml", fix=True)

    assert len(matches) == 1
    assert "return new(1)" in (repo / "sample.py").read_text(encoding="utf-8")
