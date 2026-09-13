"""Focused G7 behavior for the guarded change service."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from xray.core import replacement as replacement_module
from xray.core.ast_grep import ChildOutcome
from xray.core.replacement import ChangeFailure, FilesystemHooks, GuardedChangeService
from xray.core.repository import CancellationError, OperationBudget
from xray.core.toolchain import ToolchainObservation, ToolchainProvider, ToolchainUnavailableError
from xray.models import (
    ChangeApplyQuery,
    ChangeApplyRequest,
    ChangePlanQuery,
    ChangePlanRequest,
    ChangeRefineQuery,
    ChangeRefineRequest,
    ChangeVerifyQuery,
    ChangeVerifyRequest,
    Error,
    PatternChangeSource,
    PlanBounds,
    RuleChangeSource,
    RuleInput,
    Selection,
    Success,
)


def pattern_request(root: Path) -> ChangePlanRequest:
    return ChangePlanRequest(
        root=str(root),
        query=ChangePlanQuery(
            source=PatternChangeSource(
                kind="pattern",
                pattern="foo($A)",
                replacement="bar($A)",
                language="python",
            )
        ),
    )


def test_pattern_plan_refine_verify_and_apply_are_complete_and_read_only(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("foo(1)\nfoo(2)\n", encoding="utf-8")
    service = GuardedChangeService()

    planned = service.execute(pattern_request(tmp_path))
    assert isinstance(planned, Success)
    plan = planned.data.plan
    assert plan.plan_schema == "xray.change.v1"
    assert len(plan.inputs.sources) == 1
    assert len(plan.edits) == 2
    assert plan.provenance.toolchain == plan.inputs.toolchain
    assert plan.provenance.query != plan.plan_digest
    assert plan.files[0].syntax_before.analyzer
    assert plan.files[0].syntax_before.analyzer == plan.files[0].syntax_after.analyzer
    assert target.read_text(encoding="utf-8") == "foo(1)\nfoo(2)\n"

    refined = service.execute(
        ChangeRefineRequest(
            root=str(tmp_path),
            query=ChangeRefineQuery(plan=plan, edit_ids=[plan.edits[0].edit_id]),
        )
    )
    assert isinstance(refined, Success)
    assert refined.data.plan.chosen.kind == "edits"
    assert [item.edit_id for item in refined.data.plan.edits] == [plan.edits[0].edit_id]

    verified = service.execute(
        ChangeVerifyRequest(
            root=str(tmp_path),
            query=ChangeVerifyQuery(plan=refined.data.plan, expected_digest=refined.data.plan.plan_digest),
        )
    )
    assert isinstance(verified, Success)
    assert target.read_text(encoding="utf-8") == "foo(1)\nfoo(2)\n"

    applied = service.execute(
        ChangeApplyRequest(
            root=str(tmp_path),
            query=ChangeApplyQuery(plan=refined.data.plan, expected_digest=refined.data.plan.plan_digest),
        )
    )
    assert isinstance(applied, Success)
    assert target.read_text(encoding="utf-8") == "bar(1)\nfoo(2)\n"


def test_apply_rejects_an_unrepresentable_success_before_mutation(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("foo(1)\n", encoding="utf-8")
    service = GuardedChangeService()
    planned = service.execute(pattern_request(tmp_path))
    assert isinstance(planned, Success)
    selection = Selection(paths=[f"scope/{index:05d}/{'a' * 100}" for index in range(700)])
    plan = planned.data.plan.model_copy(update={"selection": selection})

    result = service._apply(
        plan,
        cast(Any, SimpleNamespace(provider=SimpleNamespace(root=plan.root))),
    )

    assert isinstance(result, Error)
    assert result.error.code == "budget_too_small"
    assert result.mutation is not None
    assert result.mutation.state == "not_applied"
    assert target.read_bytes() == b"foo(1)\n"


def test_syntax_evidence_refuses_an_incomplete_diagnostic_set(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeNode:
        def __init__(self, index: int) -> None:
            self.index = index

        def range(self) -> SimpleNamespace:
            return SimpleNamespace(
                start=SimpleNamespace(index=self.index),
                end=SimpleNamespace(index=self.index + 1),
            )

        def text(self) -> str:
            return "syntax error"

    class FakeRoot:
        def __init__(self, _text: str, _language: str) -> None:
            pass

        def root(self) -> FakeRoot:
            return self

        def find_all(self, *, kind: str) -> list[FakeNode]:
            assert kind == "ERROR"
            return [FakeNode(index) for index in range(51)]

    monkeypatch.setattr(replacement_module, "SgRoot", FakeRoot)

    with pytest.raises(ChangeFailure) as failure:
        GuardedChangeService()._syntax_evidence(
            "javascript",
            b"x" * 64,
            "sample.js",
            analyzer_id="0" * 64,
        )

    assert failure.value.code == "analysis_limit"


def test_syntax_evidence_rejects_interrupted_diagnostic_enumeration(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenNode:
        def range(self) -> SimpleNamespace:
            raise RuntimeError("diagnostic enumeration failed")

    class FakeRoot:
        def __init__(self, _text: str, _language: str) -> None:
            pass

        def root(self) -> FakeRoot:
            return self

        def find_all(self, *, kind: str) -> list[BrokenNode]:
            assert kind == "ERROR"
            return [BrokenNode()]

    monkeypatch.setattr(replacement_module, "SgRoot", FakeRoot)

    with pytest.raises(ChangeFailure) as failure:
        GuardedChangeService()._syntax_evidence(
            "javascript",
            b"broken();\n",
            "sample.js",
            analyzer_id="0" * 64,
        )

    assert failure.value.code == "analysis_limit"


def test_syntax_evidence_preserves_cancellation_during_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeNode:
        def range(self) -> SimpleNamespace:
            return SimpleNamespace(start=SimpleNamespace(index=0), end=SimpleNamespace(index=1))

        def text(self) -> str:
            return "syntax error"

    class FakeRoot:
        def __init__(self, _text: str, _language: str) -> None:
            pass

        def root(self) -> FakeRoot:
            return self

        def find_all(self, *, kind: str) -> list[FakeNode]:
            assert kind == "ERROR"
            return [FakeNode()]

    checks = 0

    def cancel_during_enumeration() -> bool:
        nonlocal checks
        checks += 1
        return checks == 2

    monkeypatch.setattr(replacement_module, "SgRoot", FakeRoot)

    with pytest.raises(CancellationError):
        GuardedChangeService()._syntax_evidence(
            "javascript",
            b"broken();\n",
            "sample.js",
            analyzer_id="0" * 64,
            budget=OperationBudget(cancel=cancel_during_enumeration),
        )


def test_rule_plan_uses_captured_rule_fixes(tmp_path: Path) -> None:
    (tmp_path / "rules").mkdir()
    (tmp_path / "config.yml").write_text("ruleDirs:\n  - rules\n", encoding="utf-8")
    (tmp_path / "rules" / "foo.yml").write_text(
        "id: foo-call\nlanguage: JavaScript\nrule:\n  pattern: foo()\nfix: bar()\n",
        encoding="utf-8",
    )
    target = tmp_path / "sample.js"
    target.write_text("foo();\n", encoding="utf-8")
    result = GuardedChangeService().execute(
        ChangePlanRequest(
            root=str(tmp_path),
            query=ChangePlanQuery(
                source=RuleChangeSource(kind="rule", input=RuleInput(kind="config", path="config.yml"))
            ),
        )
    )
    assert isinstance(result, Success)
    assert len(result.data.plan.edits) == 1
    assert result.data.plan.files[0].postimage_sha256 != result.data.plan.files[0].preimage_sha256


def test_change_snapshot_binds_configuration_and_original_rule_digest(tmp_path: Path) -> None:
    target = tmp_path / "sample.js"
    target.write_text("foo();\n", encoding="utf-8")
    rule = tmp_path / "rule.yml"
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    rule.write_text(
        "id: foo-call\nlanguage: JavaScript\nrule:\n  pattern: foo()\nfix: bar()\n",
        encoding="utf-8",
    )
    selection = Selection(paths=["sample.js"])
    source = RuleChangeSource(kind="rule", input=RuleInput(kind="rule", path="rule.yml"))
    service = GuardedChangeService()
    planned = service.execute(
        ChangePlanRequest(
            root=str(tmp_path),
            query=ChangePlanQuery(source=source, selection=selection),
        )
    )
    assert isinstance(planned, Success)
    first = planned.data.plan

    rule.write_text(
        "id: foo-call\nlanguage: JavaScript\nrule:\n  pattern: foo()\nfix: baz()\n",
        encoding="utf-8",
    )
    changed_rule = service.execute(
        ChangePlanRequest(
            root=str(tmp_path),
            query=ChangePlanQuery(source=source, selection=selection),
        )
    )
    assert isinstance(changed_rule, Success)
    second = changed_rule.data.plan
    assert second.provenance.snapshot != first.provenance.snapshot
    (tmp_path / ".gitignore").write_text("other.py\n", encoding="utf-8")
    changed_config = service.execute(
        ChangePlanRequest(
            root=str(tmp_path),
            query=ChangePlanQuery(source=source, selection=selection),
        )
    )
    assert isinstance(changed_config, Success)
    third = changed_config.data.plan
    assert third.provenance.snapshot != second.provenance.snapshot
    assert third.provenance.query != second.provenance.query
    stale = service.execute(
        ChangeVerifyRequest(root=str(tmp_path), query=ChangeVerifyQuery(plan=first, expected_digest=first.plan_digest))
    )
    assert isinstance(stale, Error)
    assert stale.error.code == "plan_drift"

    assert second.provenance.query != first.provenance.query


def test_tamper_digest_drift_membership_mode_and_hardlink_are_rejected(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("foo(1)\n", encoding="utf-8")
    service = GuardedChangeService()
    planned = service.execute(pattern_request(tmp_path))
    assert isinstance(planned, Success)
    plan = planned.data.plan

    tampered = plan.model_copy(update={"source": plan.source.model_copy(update={"replacement": "baz($A)"})})
    bad_query = ChangeVerifyQuery.model_construct(plan=tampered, expected_digest=plan.plan_digest)
    bad_request = ChangeVerifyRequest.model_construct(root=str(tmp_path), query=bad_query)
    bad = service.execute(bad_request)
    assert isinstance(bad, Error)
    assert bad.error.code == "invalid_plan"

    target.write_text("foo(2)\n", encoding="utf-8")
    drift = service.execute(
        ChangeVerifyRequest(root=str(tmp_path), query=ChangeVerifyQuery(plan=plan, expected_digest=plan.plan_digest))
    )
    assert isinstance(drift, Error)
    assert drift.error.code == "plan_drift"

    target.write_text("foo(1)\n", encoding="utf-8")
    os.chmod(target, 0o755)
    mode_drift = service.execute(
        ChangeVerifyRequest(root=str(tmp_path), query=ChangeVerifyQuery(plan=plan, expected_digest=plan.plan_digest))
    )
    assert isinstance(mode_drift, Error)
    assert mode_drift.error.code == "plan_drift"

    os.chmod(target, 0o644)
    alias = tmp_path / "alias.py"
    alias.hardlink_to(target)
    hardlink = service.execute(
        ChangeApplyRequest(root=str(tmp_path), query=ChangeApplyQuery(plan=plan, expected_digest=plan.plan_digest))
    )
    assert isinstance(hardlink, Error)
    assert hardlink.mutation is not None
    assert hardlink.mutation.state == "not_applied"


def test_bounds_noop_and_zero_candidates_are_inapplicable(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("foo(1)\nfoo(2)\n", encoding="utf-8")
    no_match = GuardedChangeService().execute(
        ChangePlanRequest(
            root=str(tmp_path),
            query=ChangePlanQuery(
                source=PatternChangeSource(
                    kind="pattern", pattern="missing($A)", replacement="x($A)", language="python"
                )
            ),
        )
    )
    assert isinstance(no_match, Success)
    assert no_match.data.plan.eligibility.reasons == ["no_candidates"]
    verify = GuardedChangeService().execute(
        ChangeVerifyRequest(
            root=str(tmp_path),
            query=ChangeVerifyQuery(plan=no_match.data.plan, expected_digest=no_match.data.plan.plan_digest),
        )
    )
    assert isinstance(verify, Error)
    assert verify.error.code == "plan_inapplicable"

    zero = GuardedChangeService().execute(
        ChangePlanRequest(
            root=str(tmp_path),
            query=ChangePlanQuery(
                source=PatternChangeSource(kind="pattern", pattern="foo($A)", replacement="foo($A)", language="python")
            ),
        )
    )
    assert isinstance(zero, Success)
    assert zero.data.plan.eligibility.reasons == ["no_changes"]

    limited = GuardedChangeService().execute(
        ChangePlanRequest(
            root=str(tmp_path),
            query=ChangePlanQuery(
                source=PatternChangeSource(kind="pattern", pattern="foo($A)", replacement="bar($A)", language="python"),
                bounds=PlanBounds(max_candidates=1),
            ),
        )
    )
    assert isinstance(limited, Error)
    assert limited.error.code == "execution_limit"

    (tmp_path / "other.py").write_text("foo(3)\n", encoding="utf-8")
    limited_files = GuardedChangeService().execute(
        ChangePlanRequest(
            root=str(tmp_path),
            query=ChangePlanQuery(
                source=PatternChangeSource(kind="pattern", pattern="foo($A)", replacement="bar($A)", language="python"),
                bounds=PlanBounds(max_files=1),
            ),
        )
    )
    assert isinstance(limited_files, Error)
    assert limited_files.error.code == "execution_limit"


def test_apply_caught_failures_report_rollback_and_preserve_conflict(tmp_path: Path) -> None:
    first = tmp_path / "a.py"
    second = tmp_path / "b.py"
    first.write_text("foo(1)\n", encoding="utf-8")
    second.write_text("foo(2)\n", encoding="utf-8")
    service = GuardedChangeService()
    planned = service.execute(pattern_request(tmp_path))
    assert isinstance(planned, Success)
    plan = planned.data.plan

    replace_count = 0

    def replace_then_fail(source: Path, target: Path) -> None:
        nonlocal replace_count
        replace_count += 1
        if replace_count == 2:
            raise OSError("injected replacement failure")
        os.replace(source, target)

    failed = GuardedChangeService(filesystem=FilesystemHooks(replace=replace_then_fail)).execute(
        ChangeApplyRequest(root=str(tmp_path), query=ChangeApplyQuery(plan=plan, expected_digest=plan.plan_digest))
    )
    assert isinstance(failed, Error)
    assert failed.mutation is not None
    assert failed.mutation.state == "rolled_back"
    assert failed.mutation.rollback_status == "succeeded"
    assert first.read_text(encoding="utf-8") == "foo(1)\n"

    replanned = GuardedChangeService().execute(pattern_request(tmp_path))
    assert isinstance(replanned, Success)
    conflict_plan = replanned.data.plan

    replace_count = 0

    def replace_with_conflict(source: Path, target: Path) -> None:
        nonlocal replace_count
        replace_count += 1
        os.replace(source, target)
        if replace_count == 1:
            target.write_text("external\n", encoding="utf-8")
        elif replace_count == 2:
            raise OSError("injected replacement failure")

    conflicted = GuardedChangeService(filesystem=FilesystemHooks(replace=replace_with_conflict)).execute(
        ChangeApplyRequest(
            root=str(tmp_path),
            query=ChangeApplyQuery(plan=conflict_plan, expected_digest=conflict_plan.plan_digest),
        )
    )
    assert isinstance(conflicted, Error)
    assert conflicted.mutation is not None
    assert conflicted.mutation.rollback_status == "failed"
    assert first.read_text(encoding="utf-8") == "external\n"
    assert conflicted.error.details is not None
    assert conflicted.error.details.conflict_edit_ids == [
        edit.edit_id for edit in conflict_plan.edits if edit.path == "a.py"
    ]


def test_diff_marks_changed_missing_final_lf_and_preserves_crlf(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_bytes(b"foo(1)")
    result = GuardedChangeService().execute(pattern_request(tmp_path))
    assert isinstance(result, Success)
    assert result.data.plan.files[0].diff == (
        "--- a/sample.py\n"
        "+++ b/sample.py\n"
        "@@ -1 +1 @@\n"
        "-foo(1)\n"
        "\\ No newline at end of file\n"
        "+bar(1)\n"
        "\\ No newline at end of file\n"
    )

    crlf = tmp_path / "crlf.py"
    crlf.write_bytes(b"foo(1)\r\nkeep(2)")
    crlf_result = GuardedChangeService().execute(pattern_request(tmp_path))
    assert isinstance(crlf_result, Success)
    assert crlf_result.data.plan.files[0].path == "crlf.py"
    assert crlf_result.data.plan.files[0].diff == (
        "--- a/crlf.py\n+++ b/crlf.py\n@@ -1,2 +1,2 @@\n-foo(1)\r\n+bar(1)\r\n keep(2)\n\\ No newline at end of file\n"
    )


def test_missing_toolchain_blocks_planning_without_a_fallback_identity(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("foo(1)\n", encoding="utf-8")

    def unavailable() -> ToolchainObservation:
        raise ToolchainUnavailableError("ast-grep is unavailable")

    result = GuardedChangeService(toolchain_provider=unavailable).execute(pattern_request(tmp_path))
    assert isinstance(result, Error)
    assert result.error.code == "dependency_unavailable"
    assert target.read_bytes() == b"foo(1)\n"


def test_change_toolchain_observation_preserves_cancellation_error(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("foo(1)\n", encoding="utf-8")
    budget = OperationBudget(timeout_seconds=30)

    class CancellingProvider(ToolchainProvider):
        def observe(self, *, budget: OperationBudget | None = None) -> ToolchainObservation:
            assert budget is not None
            budget.cancel = lambda: True
            budget.check_deadline()
            raise AssertionError("unreachable")

    result = GuardedChangeService(toolchain_provider=CancellingProvider()).execute(
        pattern_request(tmp_path),
        budget=budget,
    )

    assert isinstance(result, Error)
    assert result.error.code == "execution_limit"
    assert target.read_bytes() == b"foo(1)\n"


@pytest.mark.parametrize("phase", ["config", "index", "status"])
@pytest.mark.parametrize(
    ("outcome", "expected_code"),
    [
        (ChildOutcome(b"", b"fatal: broken index\n", 128, "nonzero_exit", True), "io_error"),
        (ChildOutcome(b"partial", b"", 0, "stdout_overflow", True), "execution_limit"),
        (ChildOutcome(b"", b"partial", 0, "stderr_overflow", True), "execution_limit"),
        (ChildOutcome(b"", b"", None, "cancelled", True, cancelled=True), "execution_limit"),
        (ChildOutcome(b"", b"", None, "timeout", True, timed_out=True), "timeout"),
        (ChildOutcome(b" M sample.py", b"", 0, "complete", True), "io_error"),
    ],
)
def test_managed_git_baseline_requires_a_complete_bounded_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
    outcome: ChildOutcome,
    expected_code: str,
) -> None:
    (tmp_path / ".git").mkdir()
    valid_config = ChildOutcome(b"core.note\nok\0", b"", 0, "complete", True)
    valid_index = ChildOutcome(b"", b"", 0, "complete", True)
    valid_status = ChildOutcome(b"", b"", 0, "complete", True)
    outcomes = {"config": valid_config, "index": valid_index, "status": valid_status}
    outcomes[phase] = outcome
    calls: list[object] = []
    sequence = (outcomes["config"], outcomes["index"], outcomes["status"])

    def fake_child(*args: object, **kwargs: object) -> ChildOutcome:
        calls.append((args, kwargs))
        return sequence[len(calls) - 1]

    monkeypatch.setattr("xray.core.replacement.run_bounded_child", fake_child)

    with pytest.raises(ChangeFailure) as raised:
        GuardedChangeService()._observe_baseline(tmp_path, ("sample.py",))

    assert raised.value.code == expected_code
    assert len(calls) == {"config": 1, "index": 2, "status": 3}[phase]


def test_nested_git_baseline_discovers_worktree_and_translates_status_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").mkdir()
    selected = tmp_path / "selected"
    selected.mkdir()
    outcomes = [
        ChildOutcome(tmp_path.as_posix().encode() + b"\n", b"", 0, "complete", True),
        ChildOutcome(b"core.note\nok\0", b"", 0, "complete", True),
        ChildOutcome(b"", b"", 0, "complete", True),
        ChildOutcome(b" M selected/sample.py\0", b"", 0, "complete", True),
    ]
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_child(*args: object, **kwargs: object) -> ChildOutcome:
        calls.append((args, kwargs))
        return outcomes[len(calls) - 1]

    monkeypatch.setattr("xray.core.replacement.run_bounded_child", fake_child)
    GuardedChangeService()._observe_baseline(selected, ("sample.py",))

    command = calls[0][1].get("argv", calls[0][1].get("command"))
    if command is None:
        assert calls[0][0]
        command = calls[0][0][0]
    assert isinstance(command, list)
    assert command[1:5] == ["--no-pager", "--no-optional-locks", "-C", selected.as_posix()]
    assert command[-2:] == ["rev-parse", "--show-toplevel"]
    assert calls[0][1]["cwd"] == selected
    assert all(call[1]["cwd"] == tmp_path for call in calls[1:])


def test_git_metadata_parsers_accept_bounded_multiline_values_and_embedded_path_bytes() -> None:
    service = GuardedChangeService()
    service._parse_git_configuration(b"core.note\nfirst\nsecond\0")
    service._parse_git_index(b"100644 " + b"a" * 40 + b" 2\tname\twith\nbytes\0")

    with pytest.raises(ChangeFailure):
        service._parse_git_configuration(b"filter.driver.clean\n \0")
    with pytest.raises(ChangeFailure):
        service._parse_git_configuration(b"filter.driver.process\0")
    with pytest.raises(ChangeFailure):
        service._parse_git_index(b"160000 " + b"a" * 40 + b" 0\tnested\0")
    with pytest.raises(ChangeFailure):
        service._parse_git_index(b"040000 " + b"a" * 40 + b" 0\tdirectory/\0")


def test_real_git_baseline_is_read_only_and_handles_literal_arrow_and_staged_rename(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is unavailable")

    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    git("init", "--quiet")
    (tmp_path / "tracked.py").write_text("one\n", encoding="utf-8")
    (tmp_path / "rename-old.py").write_text("old\n", encoding="utf-8")
    git("add", "tracked.py", "rename-old.py")
    git(
        "-c",
        "user.name=xray-test",
        "-c",
        "user.email=xray-test@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "initial",
    )
    monitor_ran = tmp_path.parent / f"{tmp_path.name}.fsmonitor-ran"
    monitor = tmp_path / "fsmonitor.sh"
    monitor.write_text(f"#!/bin/sh\nprintf ran > '{monitor_ran}'\n", encoding="utf-8")
    monitor.chmod(0o755)
    git("config", "core.fsmonitor", monitor.as_posix())
    git("mv", "rename-old.py", "rename-new.py")
    monitor_ran.unlink(missing_ok=True)
    (tmp_path / "tracked.py").write_text("two\n", encoding="utf-8")
    (tmp_path / "a -> b.py").write_text("literal arrow\n", encoding="utf-8")

    index = tmp_path / ".git" / "index"
    index_bytes = index.read_bytes()
    index_mtime = index.stat().st_mtime_ns
    result = GuardedChangeService()._observe_baseline(
        tmp_path,
        ("a -> b.py", "rename-new.py", "rename-old.py", "tracked.py"),
    )

    assert result.kind == "git"
    assert result.dirty == ("a -> b.py", "rename-new.py", "rename-old.py", "tracked.py")
    assert not monitor_ran.exists()
    assert index.read_bytes() == index_bytes
    assert index.stat().st_mtime_ns == index_mtime
    assert not (tmp_path / ".git" / "index.lock").exists()

    managed_subdirectory = tmp_path / "managed-subdirectory"
    managed_subdirectory.mkdir()
    assert GuardedChangeService()._observe_baseline(managed_subdirectory, ("sample.py",)).kind == "git"

    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    try:
        assert GuardedChangeService()._observe_baseline(outside, ("sample.py",)).kind == "unmanaged"
    finally:
        outside.rmdir()


def test_known_remaining_rollback_reports_partial_and_cleans_each_stage(tmp_path: Path) -> None:
    first = tmp_path / "a.py"
    second = tmp_path / "b.py"
    first.write_text("foo(1)\n", encoding="utf-8")
    second.write_text("foo(2)\n", encoding="utf-8")
    planned = GuardedChangeService().execute(pattern_request(tmp_path))
    assert isinstance(planned, Success)

    stages: list[Path] = []
    removed: list[Path] = []

    def stage(target: Path, content: bytes, mode: int) -> Path:
        value = target.with_name(f".{target.name}.stage-{len(stages)}")
        value.write_bytes(content)
        value.chmod(mode & 0o777)
        stages.append(value)
        return value

    def remove(path: Path) -> None:
        removed.append(path)
        path.unlink(missing_ok=True)

    replace_count = 0

    def replace(source: Path, target: Path) -> None:
        nonlocal replace_count
        replace_count += 1
        if replace_count in {2, 3}:
            raise OSError("rollback replacement failed")
        os.replace(source, target)

    failed = GuardedChangeService(filesystem=FilesystemHooks(stage=stage, remove=remove, replace=replace)).execute(
        ChangeApplyRequest(
            root=str(tmp_path),
            query=ChangeApplyQuery(plan=planned.data.plan, expected_digest=planned.data.plan.plan_digest),
        )
    )

    assert isinstance(failed, Error)
    assert failed.error.code == "apply_failed"
    assert failed.mutation is not None
    assert failed.mutation.state == "partially_applied"
    assert failed.mutation.rollback_status == "failed"
    assert first.read_bytes() == b"bar(1)\n"
    assert second.read_bytes() == b"foo(2)\n"
    assert set(stages).issubset(set(removed))
    assert all(not path.exists() for path in stages)


def test_unknown_final_rollback_reports_indeterminate_and_cleans_stages(tmp_path: Path) -> None:
    first = tmp_path / "a.py"
    second = tmp_path / "b.py"
    first.write_text("foo(1)\n", encoding="utf-8")
    second.write_text("foo(2)\n", encoding="utf-8")
    planned = GuardedChangeService().execute(pattern_request(tmp_path))
    assert isinstance(planned, Success)

    stages: list[Path] = []
    removed: list[Path] = []
    hidden = False

    def stage(target: Path, content: bytes, mode: int) -> Path:
        value = target.with_name(f".{target.name}.stage-{len(stages)}")
        value.write_bytes(content)
        value.chmod(mode & 0o777)
        stages.append(value)
        return value

    def read(path: Path) -> bytes:
        if hidden and path == first:
            raise OSError("final target became unreadable")
        return path.read_bytes()

    def remove(path: Path) -> None:
        removed.append(path)
        path.unlink(missing_ok=True)

    def replace(source: Path, target: Path) -> None:
        nonlocal hidden
        os.replace(source, target)
        if target == first:
            hidden = True

    failed = GuardedChangeService(
        filesystem=FilesystemHooks(read=read, stage=stage, remove=remove, replace=replace)
    ).execute(
        ChangeApplyRequest(
            root=str(tmp_path),
            query=ChangeApplyQuery(plan=planned.data.plan, expected_digest=planned.data.plan.plan_digest),
        )
    )

    assert isinstance(failed, Error)
    assert failed.mutation is not None
    assert failed.mutation.state == "indeterminate"
    assert failed.mutation.rollback_status == "failed"
    assert first.read_bytes() == b"bar(1)\n"
    assert second.read_bytes() == b"foo(2)\n"
    assert set(stages).issubset(set(removed))
    assert all(not path.exists() for path in stages)
