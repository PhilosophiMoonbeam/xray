import io
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from xray.core.ast_grep import (
    AstGrepCommandError,
    AstGrepNotFoundError,
    parse_json_array,
    run_ast_grep,
    run_ast_grep_bounded,
)


def test_run_ast_grep_treats_json_no_matches_as_success():
    completed = subprocess.CompletedProcess(
        args=["ast-grep"],
        returncode=1,
        stdout="[]",
        stderr="",
    )

    with patch("xray.core.ast_grep.subprocess.run", return_value=completed):
        result = run_ast_grep(["run", "--pattern", "missing", "--json", "."])

    assert result.no_matches is True
    assert result.returncode == 1


def test_run_ast_grep_treats_stream_no_matches_as_success():
    completed = subprocess.CompletedProcess(
        args=["ast-grep"],
        returncode=1,
        stdout="",
        stderr="",
    )

    with patch("xray.core.ast_grep.subprocess.run", return_value=completed):
        result = run_ast_grep(["run", "--pattern", "missing", "--json=stream", "."])

    assert result.no_matches is True
    assert result.returncode == 1


def test_run_ast_grep_treats_compact_json_no_matches_as_success():
    completed = subprocess.CompletedProcess(
        args=["ast-grep"],
        returncode=1,
        stdout="[]",
        stderr="",
    )

    with patch("xray.core.ast_grep.subprocess.run", return_value=completed):
        result = run_ast_grep(["run", "--pattern", "missing", "--json=compact", "."])

    assert result.no_matches is True
    assert result.returncode == 1


def test_run_ast_grep_raises_for_real_command_failure():
    completed = subprocess.CompletedProcess(
        args=["ast-grep"],
        returncode=2,
        stdout="",
        stderr="parser failed",
    )

    with patch("xray.core.ast_grep.subprocess.run", return_value=completed):
        with pytest.raises(AstGrepCommandError, match="parser failed"):
            run_ast_grep(["run", "--pattern", "bad", "--json", "."])


def test_run_ast_grep_raises_when_executable_missing():
    with patch("xray.core.ast_grep.subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(AstGrepNotFoundError):
            run_ast_grep(["run", "--pattern", "anything", "--json", "."])


def test_run_ast_grep_raises_command_error_on_timeout(monkeypatch):
    monkeypatch.setenv("XRAY_AST_GREP_TIMEOUT_SECONDS", "0.5")

    with patch(
        "xray.core.ast_grep.subprocess.run",
        side_effect=subprocess.TimeoutExpired(["ast-grep"], timeout=0.5),
    ):
        with pytest.raises(AstGrepCommandError, match=r"timed out after 0\.5 seconds"):
            run_ast_grep(["run", "--pattern", "anything", "--json", "."])


def test_run_ast_grep_rejects_oversized_output(monkeypatch):
    monkeypatch.setenv("XRAY_AST_GREP_OUTPUT_LIMIT_CHARS", "1024")
    completed = subprocess.CompletedProcess(
        args=["ast-grep"],
        returncode=0,
        stdout=" " * 1025,
        stderr="",
    )

    with patch("xray.core.ast_grep.subprocess.run", return_value=completed):
        with pytest.raises(AstGrepCommandError, match="stdout exceeded 1024 characters"):
            run_ast_grep(["run", "--pattern", "anything", "--json", "."])


def test_run_ast_grep_bounded_forces_single_thread_for_stable_prefix():
    process = MagicMock()
    process.stdout = io.StringIO('{"file":"sample.py"}\n')
    process.stderr = io.StringIO("")

    with patch("xray.core.ast_grep.subprocess.Popen", return_value=process) as popen:
        result = run_ast_grep_bounded(["run", "--pattern", "target", "."], 1)

    assert result.matches == [{"file": "sample.py"}]
    assert result.total_exact is False
    assert popen.call_args.args[0] == [
        "ast-grep",
        "run",
        "--pattern",
        "target",
        ".",
        "--threads",
        "1",
        "--json=stream",
    ]
    process.terminate.assert_called_once_with()


def test_parse_json_array_rejects_non_array_output():
    with pytest.raises(ValueError, match="expected a list"):
        parse_json_array("{}")
