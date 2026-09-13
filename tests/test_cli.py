from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any, cast

import pytest

from xray import cli as cli_module
from xray.models import ChangeApplyData, Coverage, RepositoryProvenance, Root, Selection, Success
from xray.operations import Result, execute
from xray.presentation import canonical_json, digest

ROOT = Path(__file__).parents[1]


def run_cli(
    *arguments: object, input_text: str | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    child_env = os.environ.copy()
    source_path = str(ROOT / "src")
    child_env["PYTHONPATH"] = source_path + os.pathsep + child_env.get("PYTHONPATH", "")
    if env:
        child_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "xray.cli", *(str(argument) for argument in arguments)],
        cwd=ROOT,
        env=child_env,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text("def outer():\n    return 42\n", encoding="utf-8")
    return repo


def payload(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    assert result.stdout
    value = json.loads(result.stdout)
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def test_search_config_escape_returns_typed_containment_error(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "escape-config.yml").write_text("ruleDirs:\n  - ../outside\n", encoding="utf-8")

    result = run_cli(
        "search",
        repo,
        "--config",
        "escape-config.yml",
        "--path",
        "sample.py",
        "--cache",
        "off",
    )

    assert result.returncode == 1
    assert result.stderr == ""
    value = payload(result)
    assert value["ok"] is False
    assert value["error"]["code"] == "path_outside_root"
    assert "details" not in value["error"] or "path" not in value["error"]["details"]


def test_read_natural_location_uses_canonical_result_and_explicit_root(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_cli(
        "read",
        repo,
        "sample.py",
        "--line",
        1,
        "--end-line",
        1,
        "--source-bytes",
        32768,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    value = payload(result)
    assert value["schema"] == "xray.v1"
    assert value["ok"] is True
    assert value["op"] == "read"
    data = value["data"]
    assert isinstance(data, dict)
    items = data["items"]
    assert isinstance(items, list) and len(items) == 1
    assert items[0]["source"] == "def outer():\n"
    assert items[0]["targets"] == [0]
    assert value["root"]["path"] == str(repo.resolve())


def test_read_accepts_reference_json_file_and_stdin_target_batches(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    natural = run_cli("read", repo, "sample.py", "--line", 1, "--end-line", 1, "--source-bytes", 32768)
    natural_value = payload(natural)
    ref = natural_value["data"]["items"][0]["ref"]

    ref_file = tmp_path / "ref.json"
    ref_file.write_text(json.dumps(ref), encoding="utf-8")
    from_file = run_cli("read", repo, "--ref-file", ref_file, "--source-bytes", 32768)
    from_inline = run_cli("read", repo, "--ref-json", json.dumps(ref), "--source-bytes", 32768)

    assert from_file.returncode == from_inline.returncode == 0
    assert payload(from_file)["data"]["items"][0]["source"] == "def outer():\n"
    assert payload(from_inline)["data"]["items"][0]["ref"] == ref

    targets = [
        {"kind": "location", "path": "sample.py", "line": 1, "end_line": 1},
        {"kind": "location", "path": "sample.py", "line": 2, "end_line": 2},
    ]
    stdin_result = run_cli(
        "read",
        repo,
        "--targets-file",
        "-",
        "--max-lines",
        1,
        "--source-bytes",
        32768,
        input_text=json.dumps(targets),
    )
    assert stdin_result.returncode == 0
    stdin_value = payload(stdin_result)
    stdin_items = stdin_value["data"]["items"]
    assert isinstance(stdin_items, list)
    assert [item["targets"] for item in stdin_items] == [[0, 1]]
    cursor = stdin_value["page"]["next_cursor"]
    assert isinstance(cursor, str) and cursor

    continued = run_cli(
        "read",
        repo,
        "--targets-file",
        "-",
        "--max-lines",
        1,
        "--source-bytes",
        32768,
        "--cursor",
        cursor,
        input_text=json.dumps(targets),
    )
    assert continued.returncode == 0
    continued_items = payload(continued)["data"]["items"]
    assert [item["targets"] for item in continued_items] == [[0, 1]]


def test_read_rejects_more_than_eight_targets_with_stable_invalid_exit(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    targets_file = tmp_path / "targets.json"
    targets_file.write_text(json.dumps([{"kind": "location", "path": "sample.py", "line": 1}] * 9), encoding="utf-8")

    result = run_cli("read", repo, "--targets-file", targets_file)

    assert result.returncode == 2
    assert result.stderr == ""
    value = payload(result)
    assert value == {
        "error": {
            "code": "invalid_request",
            "message": "read accepts one to eight targets",
        },
        "ok": False,
        "op": "read",
        "schema": "xray.v1",
    }


def test_read_paging_and_execution_controls_are_forwarded_to_shared_executor(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "many.py").write_text("\n".join(f"value_{index} = {index}" for index in range(30)) + "\n", encoding="utf-8")

    first = run_cli("read", repo, "many.py", "--line", 1, "--max-lines", 1, "--source-bytes", 8192)
    assert first.returncode == 0
    first_value = payload(first)
    assert first_value["page"]["next_cursor"]

    second = run_cli(
        "read",
        repo,
        "many.py",
        "--line",
        1,
        "--max-lines",
        1,
        "--source-bytes",
        8192,
        "--cursor",
        first_value["page"]["next_cursor"],
        "--timeout-seconds",
        30,
        "--cache",
        "off",
    )
    assert second.returncode == 0
    assert payload(second)["data"]["items"]

    invalid = run_cli("read", repo, "many.py", "--line", 1, "--timeout-seconds", 0)
    assert invalid.returncode == 2
    assert payload(invalid)["error"]["code"] == "invalid_request"


def test_capabilities_is_rootless_without_inference_and_supports_detail(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    rootless = run_cli("capabilities")
    detailed = run_cli("capabilities", "--detail", "--pretty")
    rooted = run_cli("capabilities", repo)
    rooted_detail = run_cli("capabilities", repo, "--detail")
    assert rootless.returncode == detailed.returncode == rooted.returncode == rooted_detail.returncode == 0
    rootless_value = payload(rootless)
    assert rootless_value["op"] == "capabilities"
    assert "root" not in rootless_value
    assert "repository" not in rootless_value["provenance"]

    detailed_value = payload(detailed)
    detailed_data = detailed_value["data"]
    assert [item["name"] for item in detailed_data["operations"]] == [
        "capabilities",
        "change_apply",
        "change_plan",
        "change_refine",
        "change_verify",
        "find",
        "impact",
        "interface",
        "map",
        "read",
        "search",
    ]
    assert len(detailed_data["limits"]["responses"]) == 12
    assert detailed_data["resources"] == [
        "skill://xray-progressive-discovery/SKILL.md",
        "skill://xray-progressive-discovery/{path*}",
        "xray://workflow",
    ]
    assert detailed_data["toolchain"]["schema"] == "xray.toolchain.v1"

    rooted_value = payload(rooted)
    assert rooted_value["root"]["path"] == str(repo.resolve())
    assert rooted_value["provenance"]["kind"] == "repository"
    rooted_detail_value = payload(rooted_detail)
    assert rooted_detail_value["data"]["toolchain"]["schema"] == "xray.toolchain.v1"
    assert rooted_detail_value["provenance"]["toolchain"] == digest(rooted_detail_value["data"]["toolchain"])


def test_json_and_lossy_text_framing_are_explicit(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    text = run_cli("read", repo, "sample.py", "--line", 1, "--end-line", 1, "--format", "text")
    pretty = run_cli("capabilities", "--pretty")

    assert text.returncode == 0
    assert text.stderr == ""
    assert "def outer():" in text.stdout
    assert "{" not in text.stdout
    assert pretty.returncode == 0
    assert pretty.stdout.startswith("{\n  ")


def test_cli_text_output_counts_framing_newline_in_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResult:
        ok = True

        @staticmethod
        def to_payload() -> dict[str, Any]:
            return {"schema": "xray.v1", "ok": True, "op": "map", "data": {}}

    result = cast(Any, FakeResult())

    limit = cli_module._CLI_HARD_RESPONSE_BYTES["map"]
    monkeypatch.setattr(cli_module, "_text_output", lambda _: "x" * (limit - 1))
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        accepted = cli_module._write_result(result, cli_module.OutputOptions(format="text"))

    assert accepted == 0
    assert len(stdout.getvalue().encode()) == limit
    assert stderr.getvalue() == ""

    monkeypatch.setattr(cli_module, "_text_output", lambda _: "x" * limit)
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        rejected = cli_module._write_result(result, cli_module.OutputOptions(format="text"))

    assert rejected == 1
    assert stdout.getvalue() == ""
    assert "budget_too_small" in stderr.getvalue()


def test_cli_preserves_large_applied_truth_within_the_hard_limit() -> None:
    identity = "0" * 64
    root_identity = digest(["xray.root.v1", "/tmp"])
    selection = Selection(paths=[f"scope/{index:05d}/item" for index in range(2500)])
    success = Success(
        schema="xray.v1",
        ok=True,
        op="change_apply",
        root=Root(path="/tmp", id=root_identity),
        scope=selection,
        provenance=RepositoryProvenance(
            kind="repository",
            consistency="captured_read_set",
            query=identity,
            selection=identity,
            snapshot=identity,
            toolchain=identity,
        ),
        data=ChangeApplyData(plan_digest=identity, state="applied", rollback_status="not_attempted"),
        coverage=Coverage(state="complete", basis="change_guards"),
    )
    payload_value = success.to_payload()
    limit = cli_module._CLI_HARD_RESPONSE_BYTES["change_apply"]
    assert len(canonical_json(payload_value).encode("utf-8")) + 1 <= limit
    assert (
        len(json.dumps(payload_value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8"))
        + 1
        > limit
    )

    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = cli_module._write_result(Result(success), cli_module.OutputOptions(format="json", pretty=True))

    emitted = stdout.getvalue().encode("utf-8")
    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert len(emitted) <= limit
    assert json.loads(emitted)["data"]["state"] == "applied"


def test_change_pattern_plan_refine_verify_apply_is_read_only_until_apply(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "sample.py"
    source.write_text("foo(1)\nfoo(2)\n", encoding="utf-8")
    original = source.read_bytes()
    pattern = f"foo({chr(36)}A)"
    replacement = f"bar({chr(36)}A)"

    planned = run_cli(
        "change",
        "plan",
        repo,
        "--pattern",
        pattern,
        "--replacement",
        replacement,
        "--lang",
        "python",
        "--path",
        "sample.py",
        "--max-candidates",
        10,
        "--max-files",
        2,
        "--max-bytes",
        32768,
        "--format",
        "text",
    )
    assert planned.returncode == 0
    assert planned.stderr == ""
    assert "plan_digest\t" in planned.stdout
    assert "{" not in planned.stdout
    assert source.read_bytes() == original

    planned_json = run_cli(
        "change",
        "plan",
        repo,
        "--pattern",
        pattern,
        "--replacement",
        replacement,
        "--lang",
        "python",
        "--path",
        "sample.py",
        "--max-candidates",
        10,
        "--max-files",
        2,
        "--max-bytes",
        32768,
        "--allow-dirty-affected",
    )
    assert planned_json.returncode == 0
    plan = payload(planned_json)["data"]["plan"]
    assert plan["acknowledgements"]["dirty_affected"] is True
    assert len(plan["edits"]) == 2
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    assert source.read_bytes() == original

    selected_id = plan["edits"][0]["edit_id"]
    refined = run_cli("change", "refine", repo, "--plan-file", plan_file, "--edit-id", selected_id)
    assert refined.returncode == 0
    refined_plan = payload(refined)["data"]["plan"]
    assert refined_plan["chosen"] == {"kind": "edits", "ids": [selected_id]}
    assert len(refined_plan["edits"]) == 1
    assert source.read_bytes() == original
    plan_file.write_text(json.dumps(refined_plan), encoding="utf-8")

    verified = run_cli(
        "change",
        "verify",
        repo,
        "--plan-file",
        plan_file,
        "--expected-digest",
        refined_plan["plan_digest"],
    )
    assert verified.returncode == 0
    assert payload(verified)["data"] == {"plan_digest": refined_plan["plan_digest"], "ready": True}
    assert source.read_bytes() == original

    applied = run_cli(
        "change",
        "apply",
        repo,
        "--plan-file",
        plan_file,
        "--expected-digest",
        refined_plan["plan_digest"],
    )
    assert applied.returncode == 0
    assert payload(applied)["data"] == {
        "plan_digest": refined_plan["plan_digest"],
        "rollback_status": "not_attempted",
        "state": "applied",
    }
    assert source.read_text(encoding="utf-8") == "bar(1)\nfoo(2)\n"


def test_change_rule_and_config_sources_apply_from_stdin(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    rules = repo / "rules"
    rules.mkdir()
    rule = rules / "foo.yml"
    rule.write_text(
        "id: foo-call\nlanguage: JavaScript\nrule:\n  pattern: foo()\nfix: bar()\n",
        encoding="utf-8",
    )
    (repo / "config.yml").write_text("ruleDirs:\n  - rules\n", encoding="utf-8")
    source = repo / "sample.js"
    source.write_text("foo();\n", encoding="utf-8")
    original = source.read_bytes()

    configured = run_cli("change", "plan", repo, "--config", "config.yml", "--path", "sample.js")
    assert configured.returncode == 0
    assert source.read_bytes() == original
    configured_plan = payload(configured)["data"]["plan"]
    assert configured_plan["source"]["input"] == {"kind": "config", "path": "config.yml"}

    planned = run_cli("change", "plan", repo, "--rule", "rules/foo.yml", "--path", "sample.js")
    assert planned.returncode == 0
    plan = payload(planned)["data"]["plan"]
    assert plan["source"]["input"] == {"kind": "rule", "path": "rules/foo.yml"}
    assert len(plan["edits"]) == 1
    assert source.read_bytes() == original

    applied = run_cli(
        "change",
        "apply",
        repo,
        "--plan-file",
        "-",
        "--expected-digest",
        plan["plan_digest"],
        input_text=json.dumps(plan),
    )
    assert applied.returncode == 0
    assert source.read_text(encoding="utf-8") == "bar();\n"


def test_change_apply_errors_are_typed_and_removed_routes_reject(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    source = repo / "sample.py"
    source.write_text("foo(1)\n", encoding="utf-8")
    planned = run_cli(
        "change",
        "plan",
        repo,
        "--pattern",
        f"foo({chr(36)}A)",
        "--replacement",
        f"bar({chr(36)}A)",
        "--lang",
        "python",
    )
    assert planned.returncode == 0
    plan = payload(planned)["data"]["plan"]
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    original = source.read_bytes()

    missing = run_cli(
        "change",
        "apply",
        repo,
        "--plan-file",
        tmp_path / "missing.json",
        "--expected-digest",
        "0" * 64,
    )
    assert missing.returncode == 2
    assert missing.stderr == ""
    missing_value = payload(missing)
    assert missing_value["op"] == "change_apply"
    assert missing_value["mutation"] == {"rollback_status": "not_attempted", "state": "not_applied"}
    assert source.read_bytes() == original

    tampered = json.loads(json.dumps(plan))
    tampered["source"]["replacement"] = f"baz({chr(36)}A)"
    tampered_file = tmp_path / "tampered.json"
    tampered_file.write_text(json.dumps(tampered), encoding="utf-8")
    altered = run_cli(
        "change",
        "apply",
        repo,
        "--plan-file",
        tampered_file,
        "--expected-digest",
        plan["plan_digest"],
    )
    assert altered.returncode == 2
    altered_value = payload(altered)
    assert altered_value["op"] == "change_apply"
    assert altered_value["error"]["code"] in {"invalid_request", "invalid_plan"}
    assert altered_value["mutation"] == {"rollback_status": "not_attempted", "state": "not_applied"}
    assert source.read_bytes() == original

    wrong_digest = run_cli(
        "change",
        "apply",
        repo,
        "--plan-file",
        plan_file,
        "--expected-digest",
        "0" * 64,
    )
    assert wrong_digest.returncode == 2
    wrong_value = payload(wrong_digest)
    assert wrong_value["error"]["code"] == "invalid_plan"
    assert wrong_value["mutation"] == {"rollback_status": "not_attempted", "state": "not_applied"}
    assert source.read_bytes() == original

    source.write_text("foo(2)\n", encoding="utf-8")
    stale = run_cli(
        "change",
        "apply",
        repo,
        "--plan-file",
        plan_file,
        "--expected-digest",
        plan["plan_digest"],
    )
    assert stale.returncode == 1
    stale_value = payload(stale)
    assert stale_value["error"]["code"] == "plan_drift"
    assert stale_value["mutation"] == {
        "plan_digest": plan["plan_digest"],
        "rollback_status": "not_attempted",
        "state": "not_applied",
    }
    assert source.read_text(encoding="utf-8") == "foo(2)\n"

    for removed in ("replace", "rewrite", "change_plan"):
        result = run_cli(removed)
        assert result.returncode == 2
        assert payload(result)["error"]["code"] == "unknown_operation"


def test_map_matches_execute_with_focus_depth_and_page_cursor(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    for name in ("a.py", "b.py", "c.py"):
        (repo / "src" / name).write_text("value = 1\n", encoding="utf-8")

    request = {
        "op": "map",
        "root": str(repo.resolve()),
        "query": {"focus": ["src"], "depth": 1, "context": "none", "exclusions": "default"},
        "page": {"limit": 2, "max_bytes": 4096},
    }
    expected = execute(request).to_payload()
    first = run_cli(
        "map",
        repo,
        "--focus",
        "src",
        "--depth",
        1,
        "--context",
        "none",
        "--exclusions",
        "default",
        "--limit",
        2,
        "--max-bytes",
        4096,
    )

    assert first.returncode == 0
    first_value = payload(first)
    assert first_value == expected
    cursor = first_value["page"]["next_cursor"]
    assert isinstance(cursor, str) and cursor

    continued = run_cli("map", repo, "--focus", "src", "--depth", 1, "--limit", 2, "--cursor", cursor)
    assert continued.returncode == 0
    assert payload(continued)["data"]["items"]


def test_find_filters_match_execute_and_interface_accepts_symbol_stdin(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text(
        '"""module docs."""\n\nclass Outer:\n    """outer docs."""\n\n    def known(self):\n        """known docs."""\n        return 1\n\n\ndef _private():\n    return 2\n',
        encoding="utf-8",
    )
    find_request = {
        "op": "find",
        "root": str(repo.resolve()),
        "query": {
            "text": "known",
            "selection": {"paths": ["."], "languages": ["python"], "exclusions": "default"},
            "match": "exact",
            "kinds": ["method"],
            "visibility": ["public"],
        },
        "page": {"limit": 1, "max_bytes": 6144},
    }
    expected_find = execute(find_request).to_payload()
    found = run_cli(
        "find",
        repo,
        "known",
        "--match",
        "exact",
        "--path",
        ".",
        "--language",
        "python",
        "--kinds",
        "method",
        "--visibility",
        "public",
        "--limit",
        1,
        "--max-bytes",
        6144,
    )

    assert found.returncode == 0
    found_value = payload(found)
    assert found_value == expected_find
    ref = found_value["data"]["items"][0]["ref"]

    interface_request = {
        "op": "interface",
        "root": str(repo.resolve()),
        "query": {
            "target": ref,
            "sections": ["symbols"],
            "member_depth": 1,
            "documentation": True,
        },
    }
    expected_interface = execute(interface_request).to_payload()
    ref_file = tmp_path / "symbol.json"
    ref_file.write_text(json.dumps(ref), encoding="utf-8")
    interface_from_file = run_cli(
        "interface",
        repo,
        "--ref-file",
        ref_file,
        "--sections",
        "symbols",
        "--member-depth",
        1,
        "--documentation",
    )
    interface = run_cli(
        "interface",
        repo,
        "--ref-file",
        "-",
        "--sections",
        "symbols",
        "--member-depth",
        1,
        "--documentation",
        input_text=json.dumps(ref),
    )

    assert interface_from_file.returncode == interface.returncode == 0
    assert payload(interface_from_file) == expected_interface
    assert payload(interface) == expected_interface
    assert payload(interface)["data"]["items"][0]["name"] == "known"


def test_interface_file_filters_and_text_framing_are_canonical(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text(
        "class Outer:\n    def known(self):\n        return 1\n\n\ndef top():\n    return 2\n",
        encoding="utf-8",
    )
    result = run_cli(
        "interface",
        repo,
        "sample.py",
        "--sections",
        "symbols",
        "--member-depth",
        0,
        "--kinds",
        "function",
        "--visibility",
        "public",
        "--format",
        "text",
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert "top" in result.stdout
    assert "Outer" not in result.stdout
    assert "{" not in result.stdout


def test_search_sources_match_execute_and_text(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text(
        "def foo(value):\n    return value\n\nfoo(1)\nfoo(2)\n",
        encoding="utf-8",
    )
    (repo / "rules").mkdir()
    (repo / "rules" / "no-foo.yml").write_text(
        "id: no-foo-call\nlanguage: Python\nrule:\n  pattern: foo($A)\nseverity: warning\n",
        encoding="utf-8",
    )
    (repo / "sgconfig.yml").write_text("ruleDirs:\n  - rules\n", encoding="utf-8")
    root = str(repo.resolve())
    cases = [
        (
            (
                "--literal",
                "foo",
                "--path",
                "sample.py",
                "--exclusions",
                "none",
                "--detail",
                "summary",
                "--limit",
                1,
                "--max-bytes",
                4096,
                "--cache",
                "off",
            ),
            {
                "source": {"kind": "literal", "text": "foo"},
                "selection": {"paths": ["sample.py"], "exclusions": "none"},
                "detail": "summary",
            },
        ),
        (
            (
                "--pattern",
                "foo($A)",
                "--lang",
                "python",
                "--language",
                "python",
                "--detail",
                "detail",
                "--limit",
                3,
                "--max-bytes",
                4096,
                "--cache",
                "off",
            ),
            {
                "source": {"kind": "pattern", "pattern": "foo($A)", "language": "python"},
                "selection": {"languages": ["python"]},
                "detail": "detail",
            },
        ),
        (
            ("--rule", "rules/no-foo.yml", "--path", "sample.py", "--cache", "off"),
            {
                "source": {
                    "kind": "rule",
                    "input": {"kind": "rule", "path": "rules/no-foo.yml"},
                },
                "selection": {"paths": ["sample.py"]},
            },
        ),
        (
            ("--config", "sgconfig.yml", "--path", "sample.py", "--cache", "off"),
            {
                "source": {
                    "kind": "rule",
                    "input": {"kind": "config", "path": "sgconfig.yml"},
                },
                "selection": {"paths": ["sample.py"]},
            },
        ),
    ]
    for arguments, query in cases:
        expected_request: dict[str, Any] = {
            "op": "search",
            "root": root,
            "query": query,
            "execution": {"cache": "off"},
        }
        if "--limit" in arguments:
            expected_request["page"] = {"limit": 1 if "--literal" in arguments else 3, "max_bytes": 4096}
        expected = execute(expected_request).to_payload()
        result = run_cli("search", repo, *arguments)
        assert result.returncode == 0
        assert result.stderr == ""
        assert payload(result) == expected

    text = run_cli("search", repo, "--literal", "foo", "--format", "text")
    assert text.returncode == 0
    assert text.stderr == ""
    assert "sample.py:" in text.stdout
    assert "\tfoo" in text.stdout
    assert "{" not in text.stdout


def test_impact_refs_modes_cursor_text_and_no_mutation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "dep.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (repo / "use.py").write_text(
        "from dep import foo as bar\n\ndef wrapper():\n    return foo()\n\nbar()\n# foo\nvalue = 'foo'\n",
        encoding="utf-8",
    )
    found = run_cli("find", repo, "foo", "--match", "exact")
    assert found.returncode == 0
    ref = payload(found)["data"]["items"][0]["ref"]
    ref_file = tmp_path / "symbol.json"
    ref_file.write_text(json.dumps(ref), encoding="utf-8")
    root = str(repo.resolve())
    query = {
        "target": ref,
        "selection": {"paths": ["dep.py", "use.py"]},
        "mode": "lexical",
    }
    expected_request: dict[str, Any] = {
        "op": "impact",
        "root": root,
        "query": query,
        "page": {"limit": 1, "max_bytes": 4096},
        "execution": {"cache": "off"},
    }
    expected = execute(expected_request).to_payload()
    inline = run_cli(
        "impact",
        repo,
        "--ref-json",
        json.dumps(ref),
        "--mode",
        "lexical",
        "--path",
        "dep.py",
        "--path",
        "use.py",
        "--limit",
        1,
        "--max-bytes",
        4096,
        "--cache",
        "off",
    )
    from_file = run_cli(
        "impact",
        repo,
        "--ref-file",
        ref_file,
        "--mode",
        "lexical",
        "--path",
        "dep.py",
        "--path",
        "use.py",
        "--limit",
        1,
        "--max-bytes",
        4096,
        "--cache",
        "off",
    )
    from_stdin = run_cli(
        "impact",
        repo,
        "--ref-file",
        "-",
        "--mode",
        "lexical",
        "--path",
        "dep.py",
        "--path",
        "use.py",
        "--limit",
        1,
        "--max-bytes",
        4096,
        "--cache",
        "off",
        input_text=json.dumps(ref),
    )
    assert inline.returncode == from_file.returncode == from_stdin.returncode == 0
    assert payload(inline) == payload(from_file) == payload(from_stdin) == expected

    syntax_request = {
        "op": "impact",
        "root": root,
        "query": {**query, "mode": "syntax"},
        "page": {"limit": 1, "max_bytes": 4096},
        "execution": {"cache": "off"},
    }
    syntax_expected = execute(syntax_request).to_payload()
    before = {(path): path.read_bytes() for path in repo.rglob("*") if path.is_file()}
    first = run_cli(
        "impact",
        repo,
        "--ref-json",
        json.dumps(ref),
        "--mode",
        "syntax",
        "--path",
        "dep.py",
        "--path",
        "use.py",
        "--limit",
        1,
        "--max-bytes",
        4096,
        "--cache",
        "off",
    )
    assert first.returncode == 0
    assert payload(first) == syntax_expected
    cursor = payload(first)["page"]["next_cursor"]
    assert isinstance(cursor, str) and cursor
    continued_request = {
        **syntax_request,
        "page": {"limit": 1, "max_bytes": 4096, "cursor": cursor},
    }
    continued = run_cli(
        "impact",
        repo,
        "--ref-json",
        json.dumps(ref),
        "--mode",
        "syntax",
        "--path",
        "dep.py",
        "--path",
        "use.py",
        "--limit",
        1,
        "--max-bytes",
        4096,
        "--cursor",
        cursor,
        "--cache",
        "off",
    )
    assert continued.returncode == 0
    assert payload(continued) == execute(continued_request).to_payload()
    text = run_cli(
        "impact",
        repo,
        "--ref-json",
        json.dumps(ref),
        "--mode",
        "lexical",
        "--path",
        "dep.py",
        "--path",
        "use.py",
        "--format",
        "text",
    )
    assert text.returncode == 0
    assert text.stderr == ""
    assert "use.py:" in text.stdout
    assert "\tlexical\t" in text.stdout
    assert "{" not in text.stdout
    assert {(path): path.read_bytes() for path in repo.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize(
    "arguments",
    [
        ("search", "--literal", "foo", "--pattern", "foo($A)", "--lang", "python"),
        ("search", "--pattern", "foo($A)"),
        ("search", "--literal", "foo", "--fix"),
        ("search", "--literal", "foo", "--limit", 0),
        ("search", "--literal", "foo", "--max-bytes", 4095),
        ("impact", "--mode", "lexical"),
        ("impact", "--name", "foo"),
    ],
)
def test_search_impact_reject_removed_forms_and_bounds(tmp_path: Path, arguments: tuple[object, ...]) -> None:
    repo = make_repo(tmp_path)
    command, *options = arguments
    result = run_cli(command, repo, *options)
    assert result.returncode == 2
    assert result.stderr == ""
    value = payload(result)
    assert value["ok"] is False
    assert value["error"]["code"] == "invalid_request"


@pytest.mark.parametrize(
    ("command", "option"),
    [("map", "--max-depth"), ("find", "--min-score"), ("interface", "--max-members")],
)
def test_removed_discovery_options_reject(tmp_path: Path, command: str, option: str) -> None:
    repo = make_repo(tmp_path)
    arguments: tuple[object, ...]
    if command == "find":
        arguments = (command, repo, "outer", option, 0)
    elif command == "interface":
        arguments = (command, repo, "sample.py", option, 1)
    else:
        arguments = (command, repo, option, 1)
    result = run_cli(*arguments)

    assert result.returncode == 2
    assert result.stderr == ""
    value = payload(result)
    assert value["ok"] is False
    assert value["error"]["code"] == "invalid_request"


@pytest.mark.parametrize(
    "removed",
    [
        "explore",
        "read-symbol",
        "symbol-at",
        "rewrite",
        "scan",
        "rules",
        "replace",
        "imports",
        "exports",
        "doctor",
    ],
)
def test_removed_commands_are_not_legacy_aliases(removed: str) -> None:
    result = run_cli(removed)

    assert result.returncode == 2
    assert result.stderr == ""
    value = payload(result)
    assert value["ok"] is False
    assert value["error"]["code"] == "unknown_operation"
    assert "command" not in value
    assert "schema_version" not in value


def test_read_parse_failures_are_json_by_default_and_text_on_request(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    missing_root = run_cli("read")
    text_error = run_cli("read", repo, "sample.py", "--line", 1, "--format", "text", "--bad")
    malformed = run_cli("read", repo, "--ref-json", "not-json")

    assert missing_root.returncode == 2
    assert payload(missing_root)["error"]["code"] == "invalid_request"
    assert text_error.returncode == 2
    assert text_error.stdout == ""
    assert text_error.stderr.startswith("xray: ")
    assert malformed.returncode == 2
    assert payload(malformed)["error"]["code"] == "invalid_request"


def test_help_and_version_are_handwritten_surfaces() -> None:
    help_result = run_cli("--help")
    version_result = run_cli("--version")

    assert help_result.returncode == 0
    assert "read" in help_result.stdout and "capabilities" in help_result.stdout
    assert "argparse" not in help_result.stdout
    assert version_result.returncode == 0
    assert version_result.stdout.strip().startswith("xray ")
