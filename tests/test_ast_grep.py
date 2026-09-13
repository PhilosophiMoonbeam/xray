"""Behavioral tests for the bounded ast-grep child boundary."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from xray.core.ast_grep import (
    AST_GREP_EXIT_POLICY,
    STRICT_CHILD_EXIT_POLICY,
    AstGrepCancelledError,
    AstGrepCommandError,
    AstGrepEncodingError,
    AstGrepError,
    AstGrepHugeLineError,
    AstGrepJsonError,
    AstGrepLimits,
    AstGrepNotFoundError,
    AstGrepOutputLimitError,
    AstGrepTimeoutError,
    AstGrepValidationError,
    BoundedAstGrepExecutor,
    BoundedAstGrepResult,
    BoundedChildExecutor,
    ChildExitPolicy,
    captured_ast_grep_session,
    collect_complete_file_candidates,
    parse_json_array,
    run_ast_grep,
    run_ast_grep_bounded,
    run_ast_grep_captured,
    run_bounded_child,
)
from xray.core.repository import capture_rule_input
from xray.core.toolchain import ToolchainProvider
from xray.models import RuleInput

_CHILD = r"""
import os
import sys
import time

mode = sys.argv[1]
pid_file = os.environ.get("XRAY_CHILD_PID_FILE")
if pid_file:
    with open(pid_file, "w", encoding="ascii") as handle:
        handle.write(str(os.getpid()))
        handle.flush()

if mode == "json":
    sys.stdout.buffer.write(b'[{"file":"a.py"}]\n')
elif mode == "json-empty":
    sys.stdout.buffer.write(b"[]")
    raise SystemExit(1)
elif mode == "stream":
    sys.stdout.buffer.write(b'{"file":"a.py"}\n{"file":"b.py"}\n')
elif mode == "many-stream":
    for index in range(5):
        sys.stdout.buffer.write(f'{{"file":"{index}.py"}}\n'.encode("ascii"))
elif mode == "stream-empty":
    raise SystemExit(1)
elif mode == "diagnostic-empty":
    sys.stderr.buffer.write(b"diagnostic")
    raise SystemExit(1)
elif mode == "validation":
    sys.stderr.buffer.write(b"invalid pattern")
    raise SystemExit(8)
elif mode == "failure":
    sys.stderr.buffer.write(b"child failed")
    raise SystemExit(2)
elif mode == "stdout-overflow":
    sys.stdout.buffer.write(b"x" * 4096)
elif mode == "stderr-overflow":
    sys.stderr.buffer.write(b"x" * 4096)
elif mode == "huge-line":
    sys.stdout.buffer.write(b"{" + b"x" * 4096)
elif mode == "invalid-utf8":
    sys.stdout.buffer.write(b"\xff")
elif mode == "invalid-json":
    sys.stdout.buffer.write(b"not-json\n")
elif mode in {"sleep", "cancel"}:
    time.sleep(30)
"""


@pytest.fixture
def child_factory(tmp_path: Path) -> Callable[..., Any]:
    script = tmp_path / "controlled_child.py"
    script.write_text(_CHILD, encoding="utf-8")

    def factory(command: Sequence[str], **kwargs: Any) -> Any:
        return subprocess.Popen([sys.executable, str(script), *command[1:]], **kwargs)

    return factory


def executor_for(
    child_factory: Callable[..., Any],
    *,
    stdout_bytes: int = 16 * 1024,
    stderr_bytes: int = 1024,
    line_bytes: int = 1024,
    timeout_seconds: float = 2.0,
) -> BoundedAstGrepExecutor:
    limits = AstGrepLimits(
        stdout_bytes=stdout_bytes,
        stderr_bytes=stderr_bytes,
        queued_bytes=max(2 * 1024, stdout_bytes + stderr_bytes),
        chunk_bytes=256,
        line_bytes=line_bytes,
        timeout_seconds=timeout_seconds,
        hard_timeout_seconds=max(timeout_seconds, 3.0),
    )
    return BoundedAstGrepExecutor(limits, process_factory=child_factory)


def wait_for_pid(path: Path) -> int:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            return int(path.read_text(encoding="ascii"))
        except (FileNotFoundError, ValueError):
            time.sleep(0.005)
    raise AssertionError("controlled child did not start")


def assert_reaped(pid: int) -> None:
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_real_child_decodes_json_and_stream_records(child_factory: Callable[..., Any]) -> None:
    executor = executor_for(child_factory)

    json_result = run_ast_grep(["json", "--json"], executor=executor)
    stream_result = run_ast_grep_bounded(["stream"], 1, executor=executor)

    assert parse_json_array(json_result.stdout) == [{"file": "a.py"}]
    assert stream_result.matches == [{"file": "a.py"}]
    assert stream_result.total_exact is False
    assert stream_result.complete is True


def test_complete_file_candidate_admission_stops_at_one_sentinel() -> None:
    consumed: list[int] = []
    transformed: list[int] = []

    def values() -> Any:
        for value in range(10):
            consumed.append(value)
            yield value

    result = collect_complete_file_candidates(
        values(),
        2,
        transform=lambda value: transformed.append(value) or value * 10,
    )

    assert result.candidates == (0, 10)
    assert result.raw_count == 3
    assert result.overflowed is True
    assert result.total_exact is False
    assert consumed == [0, 1, 2]
    assert transformed == [0, 1]


def test_bounded_stream_reports_raw_count_and_overflow_sentinel(child_factory: Callable[..., Any]) -> None:
    result = run_ast_grep_bounded(["many-stream"], 2, executor=executor_for(child_factory))

    assert result.matches == [{"file": "0.py"}, {"file": "1.py"}]
    assert result.raw_count == 3
    assert result.overflowed is True
    assert result.total_exact is False


def test_command_neutral_child_exit_policy_is_caller_owned(
    child_factory: Callable[..., Any],
) -> None:
    limits = executor_for(child_factory).limits
    no_match = run_bounded_child(
        ["controlled-child", "json-empty"],
        limits=limits,
        process_factory=child_factory,
        exit_policy=AST_GREP_EXIT_POLICY,
    )
    strict = run_bounded_child(
        ["controlled-child", "json-empty"],
        limits=limits,
        process_factory=child_factory,
        exit_policy=STRICT_CHILD_EXIT_POLICY,
    )

    assert no_match.status == "no_match"
    assert strict.status == "nonzero_exit"

    policy = ChildExitPolicy(success_codes=frozenset({0}), no_match_codes=frozenset({3}))
    assert policy.classify(3, stdout=b"", stderr=b"") == "no_match"
    assert (
        BoundedChildExecutor(limits, process_factory=child_factory)
        .run(
            ["controlled-child", "json-empty"],
            exit_policy=AST_GREP_EXIT_POLICY,
        )
        .status
        == "no_match"
    )


@pytest.mark.parametrize(
    ("output_limit", "timeout"),
    [("1", "0.001"), ("999999999999", "999999")],
)
def test_legacy_ast_grep_environment_values_do_not_change_typed_limits(
    monkeypatch: pytest.MonkeyPatch,
    child_factory: Callable[..., Any],
    output_limit: str,
    timeout: str,
) -> None:
    monkeypatch.setenv("XRAY_AST_GREP_OUTPUT_LIMIT_CHARS", output_limit)
    monkeypatch.setenv("XRAY_AST_GREP_TIMEOUT_SECONDS", timeout)
    executor = BoundedAstGrepExecutor(process_factory=child_factory)

    assert executor.limits == AstGrepLimits()
    result = run_ast_grep(["json", "--json"], executor=executor)

    assert parse_json_array(result.stdout) == [{"file": "a.py"}]


def test_real_child_preserves_genuine_no_match(child_factory: Callable[..., Any]) -> None:
    executor = executor_for(child_factory)

    json_result = run_ast_grep(["json-empty", "--json"], executor=executor)
    stream_result = run_ast_grep_bounded(["stream-empty"], 5, executor=executor)

    assert json_result.no_matches is True
    assert json_result.returncode == 1
    assert stream_result.matches == []
    assert stream_result.total_exact is True
    assert stream_result.returncode == 1


def test_empty_output_with_diagnostics_is_not_a_no_match(child_factory: Callable[..., Any]) -> None:
    executor = executor_for(child_factory)

    with pytest.raises(AstGrepCommandError):
        run_ast_grep(["diagnostic-empty"], executor=executor)
    with pytest.raises(AstGrepCommandError):
        run_ast_grep_bounded(["diagnostic-empty"], 1, executor=executor)


@pytest.mark.parametrize(
    ("mode", "error_type"),
    [("validation", AstGrepValidationError), ("failure", AstGrepCommandError)],
)
def test_real_child_classifies_nonzero_failures(
    child_factory: Callable[..., Any], mode: str, error_type: type[AstGrepError]
) -> None:
    with pytest.raises(error_type, match=r"invalid pattern|child failed"):
        run_ast_grep([mode], executor=executor_for(child_factory))


def test_missing_executable_is_typed() -> None:
    def missing_factory(command: Sequence[str], **kwargs: Any) -> Any:
        del command
        return subprocess.Popen(["/definitely/missing/xray-child"], **kwargs)

    with pytest.raises(AstGrepNotFoundError):
        run_ast_grep(["anything"], executor=executor_for(missing_factory))


@pytest.mark.parametrize(
    ("mode", "error_type"),
    [("stdout-overflow", AstGrepOutputLimitError), ("stderr-overflow", AstGrepOutputLimitError)],
)
def test_child_output_overflow_terminates_and_reaps(
    tmp_path: Path,
    child_factory: Callable[..., Any],
    mode: str,
    error_type: type[AstGrepError],
) -> None:
    pid_file = tmp_path / f"{mode}.pid"
    executor = executor_for(child_factory, stdout_bytes=512, stderr_bytes=512)

    with pytest.raises(error_type) as raised:
        run_ast_grep([mode], env={"XRAY_CHILD_PID_FILE": str(pid_file)}, executor=executor)

    assert raised.value.status == f"{mode.split('-', 1)[0]}_overflow"
    assert raised.value.reaped is True
    assert_reaped(wait_for_pid(pid_file))


def test_unterminated_stream_line_is_bounded(child_factory: Callable[..., Any]) -> None:
    executor = executor_for(child_factory, stdout_bytes=8192, line_bytes=512)

    with pytest.raises(AstGrepHugeLineError) as raised:
        run_ast_grep_bounded(["huge-line"], 1, executor=executor)

    assert raised.value.status == "huge_line"
    assert raised.value.reaped is True


@pytest.mark.parametrize(
    ("mode", "error_type"),
    [("invalid-utf8", AstGrepEncodingError), ("invalid-json", AstGrepJsonError)],
)
def test_invalid_stream_content_is_not_silently_empty(
    child_factory: Callable[..., Any], mode: str, error_type: type[AstGrepError]
) -> None:
    with pytest.raises(error_type) as raised:
        run_ast_grep_bounded([mode], 1, executor=executor_for(child_factory))

    assert raised.value.reaped is True


def test_timeout_terminates_and_reaps_one_child(tmp_path: Path, child_factory: Callable[..., Any]) -> None:
    pid_file = tmp_path / "timeout.pid"
    executor = executor_for(child_factory, timeout_seconds=0.05)

    with pytest.raises(AstGrepTimeoutError) as raised:
        run_ast_grep(["sleep"], env={"XRAY_CHILD_PID_FILE": str(pid_file)}, executor=executor)

    assert raised.value.status == "timeout"
    assert raised.value.reaped is True
    assert_reaped(wait_for_pid(pid_file))


def test_cancellation_terminates_and_reaps_one_child(tmp_path: Path, child_factory: Callable[..., Any]) -> None:
    pid_file = tmp_path / "cancel.pid"
    cancel = threading.Event()
    executor = executor_for(child_factory, timeout_seconds=2.0)
    pid_ready = threading.Thread(target=wait_for_pid, args=(pid_file,), daemon=True)
    pid_ready.start()

    def cancel_after_start() -> None:
        pid_ready.join(timeout=2.0)
        cancel.set()

    threading.Thread(target=cancel_after_start, daemon=True).start()
    with pytest.raises(AstGrepCancelledError) as raised:
        run_ast_grep(["cancel"], env={"XRAY_CHILD_PID_FILE": str(pid_file)}, cancel=cancel, executor=executor)

    assert raised.value.status == "cancelled"
    assert raised.value.reaped is True
    assert_reaped(wait_for_pid(pid_file))


def test_toolchain_observation_uses_actual_runtime_artifacts() -> None:
    observation = ToolchainProvider().observe()

    assert observation.healthy is True
    assert observation.digest
    assert observation.manifest is not None
    assert observation.executable is not None
    assert observation.executable.endswith("/ast-grep")
    assert observation.executable_version == "0.45.1"
    assert observation.analyzer_id("python") != observation.analyzer_id("javascript")
    assert {item.name for item in observation.dependencies} == {
        "ast-grep",
        "ast-grep-py",
        "python-ast",
        "xray",
    }


def test_toolchain_health_does_not_fabricate_identity_when_executable_missing() -> None:
    def missing_resolver(_: object) -> str:
        raise AstGrepNotFoundError("missing executable")

    observation = ToolchainProvider(executable_resolver=missing_resolver).observe()

    assert observation.healthy is False
    assert observation.digest is None
    assert observation.manifest is None
    assert any(item.name == "ast-grep" and item.state == "missing" for item in observation.dependencies)


def test_toolchain_identity_changes_when_analyzer_artifact_changes(tmp_path: Path) -> None:
    artifact = tmp_path / "analyzer.py"
    artifact.write_text("RANKING = 1\n", encoding="utf-8")
    first = ToolchainProvider(artifact_paths=[artifact]).observe()

    artifact.write_text("RANKING = 2\n", encoding="utf-8")
    second = ToolchainProvider(artifact_paths=[artifact]).observe()

    assert first.healthy is True
    assert second.healthy is True
    assert first.digest != second.digest


def test_real_ast_grep_uses_only_captured_rules_and_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "rules" / "nested").mkdir(parents=True)
    (root / "config.yml").write_text("ruleDirs:\n  - rules\n", encoding="utf-8")
    (root / "rules/nested/foo.yml").write_text(
        "id: foo-call\nlanguage: JavaScript\nrule:\n  pattern: foo()\n",
        encoding="utf-8",
    )
    captured_rules = capture_rule_input(root, RuleInput(kind="config", path="config.yml"))
    monkeypatch.setenv("AST_GREP_CONFIG", str(tmp_path / "hostile-sgconfig.yml"))

    result = run_ast_grep_captured(
        ["scan", "--config", str(tmp_path / "hostile-sgconfig.yml"), "--json=compact", "--color", "never"],
        {"selected.js": b"foo();\nbar();\n"},
        captured_rules,
    )
    records = parse_json_array(result.stdout)

    assert records
    assert {record["file"] for record in records} == {"selected.js"}
    assert {record["ruleId"] for record in records} == {"foo-call"}

    bounded = run_ast_grep_captured(
        ["scan", "--json=compact", "--color", "never"],
        {"selected.js": b"foo();\nbar();\nfoo();\n"},
        captured_rules,
        max_results=1,
    )
    assert isinstance(bounded, BoundedAstGrepResult)
    assert bounded.matches
    assert bounded.total_exact is False
    assert bounded.complete is True


def test_captured_pattern_preserves_rewrite_value_and_explicit_source_subset() -> None:
    with captured_ast_grep_session(
        {
            "selected.py": b"foo(1)\n",
            "ignored.py": b"foo(2)\n",
        }
    ) as session:
        result = session.execute(
            [
                "run",
                "--pattern",
                "foo($A)",
                "--rewrite",
                "bar($A)",
                "--lang",
                "python",
                "--json=stream",
                "--color",
                "never",
                "ignored.py",
            ],
            source_paths=("selected.py",),
            max_results=10,
        )

    assert isinstance(result, BoundedAstGrepResult)
    assert [record["file"] for record in result.matches] == ["selected.py"]
    assert result.matches[0]["replacement"] == "bar(1)"
