import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from xray import cli
from xray import mcp_server as cli_mcp_server
from xray.core.ast_grep import AstGrepError, AstGrepResult, BoundedAstGrepResult
from xray.core.indexer import ReplacementApplyError, XRayIndexer


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text(
        "def old(value):\n    return value\n\n\ndef caller():\n    return old(1)\n", encoding="utf-8"
    )
    return repo


def replacement_match(path: Path, before: str, after: str) -> dict[str, object]:
    content = path.read_bytes()
    start = content.index(before.encode())
    end = start + len(before.encode())
    return {
        "file": str(path),
        "text": before,
        "replacement": after,
        "replacementOffsets": {"start": start, "end": end},
        "range": {"start": {"line": 5, "column": 11}, "end": {"line": 5, "column": 17}},
        "metaVariables": {"single": {"A": {"text": "1"}}, "multi": {}, "transformed": {}},
    }


def test_search_pattern_passes_language_and_root(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    with patch("xray.core.indexer.run_ast_grep", return_value=AstGrepResult('[{"file":"sample.py"}]', "", 0)) as run:
        result = XRayIndexer(str(repo)).search_pattern("old($A)", "python")

    assert result == [{"file": "sample.py"}]
    run.assert_called_once_with(
        ["run", "--pattern", "old($A)", "--json=compact", "--lang", "python", str(repo.resolve())]
    )


def test_rewrite_pattern_uses_staged_writer_and_truthful_summary(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    match = replacement_match(repo / "sample.py", "old(1)", "new(1)")
    with patch("xray.core.indexer.run_ast_grep", return_value=AstGrepResult(json.dumps([match]), "", 0)) as run:
        result = XRayIndexer(str(repo)).rewrite_pattern("old($A)", "new($A)")

    assert result["match_count"] == 1
    assert result["changed_match_count"] == 1
    assert result["no_op_count"] == 0
    assert result["files_modified"] == [str(repo / "sample.py")]
    assert "return new(1)" in (repo / "sample.py").read_text(encoding="utf-8")
    assert run.call_args.args[0] == [
        "run",
        "--pattern",
        "old($A)",
        "--rewrite",
        "new($A)",
        "--json=compact",
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
    with patch("xray.core.indexer.run_ast_grep", return_value=AstGrepResult("[]", "", 0)) as run:
        indexer = XRayIndexer(str(repo))
        assert indexer.scan_rules("sgconfig.yml", fix=True) == []

    summary = indexer.last_mutation_summary
    assert summary is not None
    assert summary == {
        "plan_digest": summary["plan_digest"],
        "candidate_count": 0,
        "applied_count": 0,
        "changed_count": 0,
        "no_op_count": 0,
        "matched_file_count": 0,
        "file_count": 0,
        "files_modified": [],
        "rollback_count": 0,
        "rollback_succeeded": True,
        "files": [],
    }
    assert run.call_args.args[0] == [
        "scan",
        "--config",
        str(config.resolve()),
        "--json=compact",
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
            "2 matches changed in 1 file; 0 no-op matches\nsample.py\n",
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
    with patch.object(XRayIndexer, "search_pattern", return_value=raw) as search:
        assert cli.main(["search", str(repo), "-p", "old($A)", "--limit", "2"]) == 0
    assert search.call_args.kwargs["max_results"] == 3
    first = json.loads(capsys.readouterr().out)
    assert first["schema_version"] == "xray.cli.v2"
    assert first["matches"] == [
        {"path": "sample.py", "line": 1, "column": 5, "text": "old(0)", "captures": {"A": "0"}},
        {"path": "sample.py", "line": 2, "column": 5, "text": "old(1)", "captures": {"A": "1"}},
    ]
    assert (first["returned"], first["total"], first["truncated"]) == (2, 3, True)
    assert "range" not in json.dumps(first["matches"])

    with patch.object(XRayIndexer, "search_pattern", return_value=raw) as search:
        assert cli.main(["search", str(repo), "-p", "old($A)", "--limit", "2", "--cursor", first["next_cursor"]]) == 0
    assert search.call_args.kwargs["max_results"] == 5
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


def test_replacement_plan_is_non_mutating_and_guarded_apply_changes_exact_bytes(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    sample = repo / "sample.py"
    sample.chmod(0o754)
    original = sample.read_bytes()
    original_mode = sample.stat().st_mode
    indexer = XRayIndexer(str(repo))

    plan = indexer.plan_replacement(pattern="old($A)", replacement="new($A)", lang="python")

    assert sample.read_bytes() == original
    assert plan["plan_version"] == "xray.replace.v1"
    assert plan["candidate_count"] == 1
    assert plan["changed_candidate_count"] == 1
    assert plan["no_op_count"] == 0
    assert plan["changed_file_count"] == 1
    assert plan["preview"][0]["before"] == "old(1)"
    assert plan["preview"][0]["after"] == "new(1)"

    result = indexer.apply_replacement(plan, expected_digest=plan["plan_digest"])

    assert result["changed_count"] == 1
    assert result["files_modified"] == ["sample.py"]
    assert result["files"][0]["postimage_sha256"] == plan["files"][0]["postimage_sha256"]
    assert "return new(1)" in sample.read_text(encoding="utf-8")
    assert sample.stat().st_mode == original_mode


def test_replacement_apply_rejects_digest_mismatch_and_source_drift(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    sample = repo / "sample.py"
    indexer = XRayIndexer(str(repo))
    plan = indexer.plan_replacement(pattern="old($A)", replacement="new($A)", lang="python")

    with pytest.raises(ValueError, match="expected_digest"):
        indexer.apply_replacement(plan, expected_digest="0" * 64)
    assert "return old(1)" in sample.read_text(encoding="utf-8")

    tampered_plan = json.loads(json.dumps(plan))
    tampered_plan["query"]["change"]["replacement"] = "unsafe($A)"
    with pytest.raises(ValueError, match="digest does not match"):
        indexer.apply_replacement(tampered_plan, expected_digest=plan["plan_digest"])
    assert "return old(1)" in sample.read_text(encoding="utf-8")

    sample.write_text(sample.read_text(encoding="utf-8").replace("old(1)", "old(2)"), encoding="utf-8")
    drifted = sample.read_bytes()
    with pytest.raises(ReplacementApplyError, match="no longer matches"):
        indexer.apply_replacement(plan, expected_digest=plan["plan_digest"])
    assert sample.read_bytes() == drifted


def test_replacement_noop_is_truthful_and_requires_explicit_allowance(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    sample = repo / "sample.py"
    original = sample.read_bytes()
    indexer = XRayIndexer(str(repo))
    plan = indexer.plan_replacement(pattern="old($A)", replacement="old($A)", lang="python")

    assert plan["candidate_count"] == 1
    assert plan["changed_candidate_count"] == 0
    assert plan["no_op_count"] == 1
    assert plan["changed_file_count"] == 0
    with pytest.raises(ValueError, match="no byte-changing edits"):
        indexer.apply_replacement(plan, expected_digest=plan["plan_digest"])

    summary = indexer.rewrite_pattern("old($A)", "old($A)", "python")
    assert summary["match_count"] == 1
    assert summary["changed_match_count"] == 0
    assert summary["no_op_count"] == 1
    assert summary["file_count"] == 0
    assert summary["files_modified"] == []
    assert sample.read_bytes() == original


def test_replacement_candidate_and_file_caps_fail_without_mutation(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    second = repo / "second.py"
    second.write_text("def caller_two():\n    return old(2)\n", encoding="utf-8")
    originals = {path: path.read_bytes() for path in (repo / "sample.py", second)}
    indexer = XRayIndexer(str(repo))

    with pytest.raises(ValueError, match="allowed 1 candidates"):
        indexer.plan_replacement(pattern="old($A)", replacement="new($A)", lang="python", max_matches=1, max_files=10)
    with pytest.raises(ValueError, match="allowed 1 files"):
        indexer.plan_replacement(pattern="old($A)", replacement="new($A)", lang="python", max_matches=10, max_files=1)
    assert {path: path.read_bytes() for path in originals} == originals


def test_rule_replacement_plan_and_apply_share_guarded_engine(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    rule = repo / "no-old.yml"
    rule.write_text(
        "id: no-old-call\nlanguage: Python\nrule:\n  pattern: old($A)\nfix: new($A)\nseverity: warning\n",
        encoding="utf-8",
    )
    indexer = XRayIndexer(str(repo))

    plan = indexer.plan_replacement(rule_path="no-old.yml")
    assert plan["query"]["change"] == {"kind": "rule", "rule_path": "no-old.yml"}
    assert "return old(1)" in (repo / "sample.py").read_text(encoding="utf-8")

    result = indexer.apply_replacement(plan, expected_digest=plan["plan_digest"])
    assert result["changed_count"] == 1
    assert "return new(1)" in (repo / "sample.py").read_text(encoding="utf-8")


def test_replacement_apply_rolls_back_already_replaced_files(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    second = repo / "second.py"
    second.write_text("def caller_two():\n    return old(2)\n", encoding="utf-8")
    sample = repo / "sample.py"
    originals = {sample: sample.read_bytes(), second: second.read_bytes()}
    indexer = XRayIndexer(str(repo))
    plan = indexer.plan_replacement(pattern="old($A)", replacement="new($A)", lang="python")
    real_replace = os.replace
    failed = False

    def fail_second_replace(source: str | Path, destination: str | Path) -> None:
        nonlocal failed
        if Path(destination) == second and not failed:
            failed = True
            raise OSError("injected second-file failure")
        real_replace(source, destination)

    with patch("xray.core.indexer.os.replace", side_effect=fail_second_replace):
        with pytest.raises(ReplacementApplyError) as raised:
            indexer.apply_replacement(plan, expected_digest=plan["plan_digest"])

    assert raised.value.rollback_count == 1
    assert raised.value.rollback_succeeded is True
    assert {path: path.read_bytes() for path in originals} == originals


def test_replacement_rechecks_source_after_staging_before_first_write(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    sample = repo / "sample.py"
    indexer = XRayIndexer(str(repo))
    plan = indexer.plan_replacement(pattern="old($A)", replacement="new($A)", lang="python")
    real_stage = indexer._write_staged_file

    def stage_then_inject_drift(item, content):
        staged = real_stage(item, content)
        sample.write_text(sample.read_text(encoding="utf-8").replace("old(1)", "old(9)"), encoding="utf-8")
        return staged

    with patch.object(indexer, "_write_staged_file", side_effect=stage_then_inject_drift):
        with pytest.raises(ReplacementApplyError, match="after staging"):
            indexer.apply_replacement(plan, expected_digest=plan["plan_digest"])

    assert "return old(9)" in sample.read_text(encoding="utf-8")
    assert not list(repo.glob(".xray-stage-*"))


def test_replacement_uses_utf8_byte_offsets_and_contained_path_scope(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    sample = repo / "sample.py"
    sample.write_text("café = old(1)\n", encoding="utf-8")
    other = repo / "other.py"
    other.write_text("value = old(2)\n", encoding="utf-8")
    indexer = XRayIndexer(str(repo))

    plan = indexer.plan_replacement(
        pattern="old($A)", replacement="new($A)", lang="python", paths=["sample.py"], globs=["*.py"]
    )
    result = indexer.apply_replacement(plan, expected_digest=plan["plan_digest"])

    assert result["files_modified"] == ["sample.py"]
    assert sample.read_text(encoding="utf-8") == "café = new(1)\n"
    assert other.read_text(encoding="utf-8") == "value = old(2)\n"


def test_bounded_search_passes_upstream_cap_scopes_and_reports_exactness(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    with patch(
        "xray.core.indexer.run_ast_grep_bounded",
        return_value=BoundedAstGrepResult(matches=[{"file": "sample.py"}, {"file": "sample.py"}], total_exact=False),
    ) as run:
        indexer = XRayIndexer(str(repo))
        matches = indexer.search_pattern("old($A)", "python", paths=["sample.py"], globs=["*.py"], max_results=2)

    assert len(matches) == 2
    assert indexer.last_result_total_exact is False
    assert indexer.last_result_cap == 2
    assert run.call_args.args == (
        [
            "run",
            "--pattern",
            "old($A)",
            "--lang",
            "python",
            "--globs",
            "*.py",
            str(repo / "sample.py"),
        ],
        2,
    )


def test_replace_cli_plan_file_and_guarded_apply_end_to_end(tmp_path: Path, capsys) -> None:
    repo = make_repo(tmp_path)
    sample = repo / "sample.py"
    original = sample.read_bytes()

    assert (
        cli.main(
            [
                "replace",
                "plan",
                str(repo),
                "--pattern",
                "old($A)",
                "--replacement",
                "new($A)",
                "--lang",
                "python",
                "--path",
                "sample.py",
            ]
        )
        == 0
    )
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["schema_version"] == "xray.cli.v2"
    assert envelope["command"] == "replace.plan"
    plan = envelope["plan"]
    assert plan["candidate_count"] == 1
    assert sample.read_bytes() == original

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(envelope), encoding="utf-8")
    assert (
        cli.main(
            [
                "replace",
                "apply",
                str(repo),
                "--plan-file",
                str(plan_file),
                "--expected-digest",
                plan["plan_digest"],
            ]
        )
        == 0
    )
    applied = json.loads(capsys.readouterr().out)
    assert applied["command"] == "replace.apply"
    assert applied["result"]["changed_count"] == 1
    assert sample.read_text(encoding="utf-8").endswith("return new(1)\n")


def test_replace_cli_apply_rejects_independent_digest_without_mutation(tmp_path: Path, capsys) -> None:
    repo = make_repo(tmp_path)
    sample = repo / "sample.py"
    plan = XRayIndexer(str(repo)).plan_replacement(pattern="old($A)", replacement="new($A)", lang="python")
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    original = sample.read_bytes()

    assert (
        cli.main(
            [
                "replace",
                "apply",
                str(repo),
                "--plan-file",
                str(plan_file),
                "--expected-digest",
                "0" * 64,
            ]
        )
        == 2
    )
    error = json.loads(capsys.readouterr().err)
    assert "expected_digest" in error["error"]
    assert sample.read_bytes() == original


def test_search_cursor_rejects_changed_source_snapshot(tmp_path: Path, capsys) -> None:
    repo = make_repo(tmp_path)
    second = repo / "second.py"
    second.write_text("value = old(2)\n", encoding="utf-8")

    assert cli.main(["search", str(repo), "--pattern", "old($A)", "--lang", "python", "--limit", "1"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["total_exact"] is False
    cursor = first["next_cursor"]
    second.write_text("value = old(3)\n", encoding="utf-8")

    assert (
        cli.main(
            [
                "search",
                str(repo),
                "--pattern",
                "old($A)",
                "--lang",
                "python",
                "--limit",
                "1",
                "--cursor",
                cursor,
            ]
        )
        == 2
    )
    assert "does not match" in json.loads(capsys.readouterr().err)["error"]


def test_cursor_snapshot_ignores_generated_and_gitignored_content(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    generated = repo / ".venv"
    generated.mkdir()
    ignored = repo / "ignored.txt"
    (repo / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (generated / "environment.bin").write_bytes(b"first")
    ignored.write_text("first", encoding="utf-8")

    indexer = XRayIndexer(str(repo))
    before = indexer.repository_snapshot_fingerprint()
    (generated / "environment.bin").write_bytes(b"second")
    ignored.write_text("second", encoding="utf-8")

    assert indexer.repository_snapshot_fingerprint() == before


def test_mcp_replacement_tools_have_truthful_annotations_and_apply_reviewed_plan(tmp_path: Path) -> None:
    import asyncio

    from fastmcp import Client

    repo = make_repo(tmp_path)
    sample = repo / "sample.py"

    async def exercise():
        async with Client(cli_mcp_server.mcp) as client:
            search_call = await client.call_tool("search_tools", {"pattern": "replacement"})
            assert search_call.structured_content is not None
            discovered = search_call.structured_content["result"]
            plan_call = await client.call_tool(
                "call_tool",
                {
                    "name": "plan_replacement",
                    "arguments": {
                        "root_path": str(repo),
                        "pattern": "old($A)",
                        "replacement": "new($A)",
                        "lang": "python",
                    },
                },
            )
            assert plan_call.structured_content is not None
            plan = plan_call.structured_content
            apply_call = await client.call_tool(
                "call_tool",
                {
                    "name": "apply_replacement",
                    "arguments": {
                        "root_path": str(repo),
                        "plan": plan,
                        "expected_digest": plan["plan_digest"],
                    },
                },
            )
            assert apply_call.structured_content is not None
            return discovered, apply_call.structured_content

    discovered, applied = asyncio.run(exercise())
    by_name = {tool["name"]: tool for tool in discovered}
    assert by_name["plan_replacement"]["annotations"]["readOnlyHint"] is True
    assert by_name["plan_replacement"]["annotations"]["destructiveHint"] is False
    assert by_name["apply_replacement"]["annotations"]["destructiveHint"] is True
    assert applied["changed_count"] == 1
    assert "return new(1)" in sample.read_text(encoding="utf-8")
