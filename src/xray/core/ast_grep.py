"""Bounded ast-grep child execution for XRAY.

The current indexer still calls ``run_ast_grep`` and
``run_ast_grep_bounded``. Those names remain the narrow callable seam while
this module enforces binary fixed-size readers, bounded queues, strict decoding,
and one operation-local child. New code can use ``BoundedAstGrepExecutor``
directly with explicitly captured inputs.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from xray.core.repository import OperationBudget

DEFAULT_AST_GREP_TIMEOUT_SECONDS = 30.0
HARD_AST_GREP_TIMEOUT_SECONDS = 120.0
AST_GREP_VALIDATION_EXIT_CODE = 8
STDOUT_LIMIT_BYTES = 16 * 1024 * 1024
STDERR_LIMIT_BYTES = 64 * 1024
QUEUED_BYTES_LIMIT = 256 * 1024
CHUNK_BYTES = 4096
LINE_BYTES_LIMIT = 64 * 1024
TEMPORARY_BYTES_LIMIT = 320 * 1024 * 1024
CHILD_TERM_GRACE_SECONDS = 0.5


class AstGrepError(RuntimeError):
    """Base typed ast-grep execution failure."""

    code = "execution_limit"
    status = "failed"

    def __init__(
        self,
        message: str,
        *,
        status: str | None = None,
        returncode: int | None = None,
        reaped: bool | None = None,
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> None:
        super().__init__(message)
        self.status = status or self.status
        self.returncode = returncode
        self.reaped = reaped
        self.stdout = bytes(stdout)
        self.stderr = bytes(stderr)


class AstGrepNotFoundError(AstGrepError):
    """Raised when the ast-grep executable is unavailable."""

    code = "dependency_unavailable"
    status = "not_found"


class AstGrepCommandError(AstGrepError):
    """Raised when ast-grep returns an actual command or I/O failure."""

    code = "io_error"
    status = "command_failed"


class AstGrepValidationError(AstGrepError):
    """Raised when ast-grep rejects caller-provided syntax or configuration."""

    code = "invalid_pattern"
    status = "validation_failed"


class AstGrepOutputLimitError(AstGrepCommandError):
    """Raised when bounded stdout/stderr or a JSON line exceeds its limit."""

    code = "execution_limit"
    status = "output_overflow"


class AstGrepHugeLineError(AstGrepOutputLimitError):
    """Raised when one streaming JSON record is too large to bound safely."""

    status = "huge_line"


class AstGrepEncodingError(AstGrepCommandError):
    """Raised when child output is not strict UTF-8."""

    code = "invalid_encoding"
    status = "invalid_utf8"


class AstGrepJsonError(AstGrepCommandError):
    """Raised when child output is not the expected strict JSON shape."""

    code = "execution_limit"
    status = "invalid_json"


class AstGrepTimeoutError(AstGrepCommandError):
    """Raised when the one operation deadline expires."""

    code = "timeout"
    status = "timeout"


class AstGrepCancelledError(AstGrepCommandError):
    """Raised when the operation's cancellation token is set."""

    code = "execution_limit"
    status = "cancelled"


@dataclass(frozen=True, slots=True)
class AstGrepResult:
    """Completed ast-grep command with normalized no-match semantics."""

    stdout: str
    stderr: str
    returncode: int
    no_matches: bool = False


@dataclass(frozen=True, slots=True)
class BoundedAstGrepResult:
    """Parsed streaming matches with honest execution-completion metadata."""

    matches: list[dict[str, Any]]
    total_exact: bool
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    complete: bool = True
    raw_count: int = 0
    overflowed: bool = False


@dataclass(frozen=True, slots=True)
class CapturedInput:
    """One explicit immutable input offered to a child through a temp tree."""

    path: str
    content: bytes

    def __post_init__(self) -> None:
        parts = self.path.split("/")
        if (
            not self.path
            or self.path.startswith("/")
            or "\x00" in self.path
            or "\\" in self.path
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise ValueError("captured input path must be canonical relative and NUL-free")
        object.__setattr__(self, "content", bytes(self.content))


@dataclass(frozen=True, slots=True)
class AstGrepLimits:
    """Hard child bounds; no environment value can raise these limits."""

    stdout_bytes: int = STDOUT_LIMIT_BYTES
    stderr_bytes: int = STDERR_LIMIT_BYTES
    queued_bytes: int = QUEUED_BYTES_LIMIT
    chunk_bytes: int = CHUNK_BYTES
    line_bytes: int = LINE_BYTES_LIMIT
    timeout_seconds: float = DEFAULT_AST_GREP_TIMEOUT_SECONDS
    hard_timeout_seconds: float = HARD_AST_GREP_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.stdout_bytes < 1 or self.stderr_bytes < 1 or self.queued_bytes < self.chunk_bytes:
            raise ValueError("child bounds must be positive and queue must fit one chunk")
        if self.line_bytes < 1 or self.chunk_bytes < 1:
            raise ValueError("child chunk and line bounds must be positive")
        if self.timeout_seconds <= 0 or self.timeout_seconds > self.hard_timeout_seconds:
            raise ValueError("child timeout must be within the hard deadline")


def sanitized_environment(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build an environment with no ambient project/home configuration."""

    env = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    if extra:
        for key, value in extra.items():
            if key in _SANITIZED_ENVIRONMENT_KEYS:
                continue
            if "\x00" in key or "\x00" in value:
                raise ValueError("child environment values must be NUL-free strings")
            env[key] = value
    return env


_SANITIZED_ENVIRONMENT_KEYS = frozenset(
    {
        "AST_GREP_CONFIG",
        "AST_GREP_CONFIG_FILE",
        "AST_GREP_CONFIG_PATH",
        "HOME",
        "USERPROFILE",
        "XDG_CONFIG_HOME",
        "XDG_CONFIG_DIRS",
        "SG_CONFIG",
        "SG_CONFIG_FILE",
        "SG_CONFIG_PATH",
        "RIPGREP_CONFIG_PATH",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
        "GIT_CONFIG_NOSYSTEM",
    }
)


def _is_cancelled(cancel: object | None) -> bool:
    if cancel is None:
        return False
    if isinstance(cancel, threading.Event):
        return cancel.is_set()
    if callable(cancel):
        try:
            return bool(cancel())
        except Exception:
            return True
    checker = getattr(cancel, "is_set", None)
    return bool(checker()) if callable(checker) else False


def _budget_check(budget: OperationBudget | None) -> None:
    if budget is not None:
        budget.check_deadline()


def _combined_cancel(cancel: object | None, budget: OperationBudget | None) -> object | None:
    budget_cancel = budget.cancel if budget is not None else None
    if cancel is None:
        return budget_cancel
    if budget_cancel is None:
        return cancel
    return lambda: _is_cancelled(cancel) or _is_cancelled(budget_cancel)


def _budget_timeout(
    budget: OperationBudget | None,
    timeout: float | None,
) -> float | None:
    if budget is None:
        return timeout
    budget.check_deadline()
    remaining = budget.remaining_seconds
    return remaining if timeout is None else min(timeout, remaining)


def _budget_failure(exc: BaseException, *, reaped: bool = True) -> AstGrepError:
    if getattr(exc, "kind", None) == "cancelled" or exc.__class__.__name__ == "CancellationError":
        return AstGrepCancelledError("ast-grep execution was cancelled", status="cancelled", reaped=reaped)
    return AstGrepTimeoutError("ast-grep timed out before the operation completed", status="timeout", reaped=reaped)


def _budget_gate(budget: OperationBudget | None) -> None:
    try:
        _budget_check(budget)
    except Exception as exc:
        raise _budget_failure(exc) from exc


def _coerce_input_bytes(value: str | bytes | None) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    return value.encode("utf-8")


def _is_strict_int(value: object) -> bool:
    return type(value) is int


def resolve_ast_grep_executable(value: str | os.PathLike[str] | None = None) -> str:
    """Resolve the executable used by both health probes and child execution.

    Only the canonical ``ast-grep`` executable is accepted when no explicit
    path is supplied.  ``sg`` is intentionally not treated as an alias: a
    health report must describe the binary that execution will actually run.
    """

    if value is not None:
        raw = os.fspath(value)
        if isinstance(raw, bytes) or not raw or "\x00" in raw:
            raise ValueError("ast-grep executable must be a non-empty NUL-free path")
        candidate = Path(raw)
        if candidate.is_absolute() or "/" in raw:
            resolved = candidate
            if not resolved.is_file() or not os.access(resolved, os.X_OK):
                raise AstGrepNotFoundError(f"ast-grep executable is unavailable: {raw}")
            return resolved.resolve(strict=True).as_posix()
        found = shutil.which(raw)
        if found is None or not os.access(found, os.X_OK):
            raise AstGrepNotFoundError(f"ast-grep executable is unavailable: {raw}")
        return Path(found).resolve(strict=True).as_posix()
    found = shutil.which("ast-grep")
    if found is None or not os.access(found, os.X_OK):
        raise AstGrepNotFoundError("ast-grep executable was not found; symbol search could not run.")
    try:
        return Path(found).resolve(strict=True).as_posix()
    except (OSError, RuntimeError) as exc:
        raise AstGrepNotFoundError("ast-grep executable could not be resolved safely.") from exc


@dataclass(frozen=True, slots=True)
class ChildExitPolicy:
    """Caller-owned interpretation of a bounded child exit status."""

    success_codes: frozenset[int] = frozenset({0})
    no_match_codes: frozenset[int] = frozenset()
    no_match_requires_empty: bool = True

    def __post_init__(self) -> None:
        invalid_success = any(not _is_strict_int(code) for code in self.success_codes)
        if not self.success_codes or invalid_success:
            raise ValueError("child success_codes must contain at least one integer")
        if any(not _is_strict_int(code) for code in self.no_match_codes):
            raise ValueError("child no-match exit codes must contain integers")
        if self.success_codes & self.no_match_codes:
            raise ValueError("child success and no-match exit codes must be disjoint")

    def classify(self, returncode: int | None, *, stdout: bytes, stderr: bytes) -> str:
        if returncode in self.success_codes:
            return "complete"
        if returncode in self.no_match_codes and (not self.no_match_requires_empty or (not stdout and not stderr)):
            return "no_match"
        return "nonzero_exit"


AST_GREP_EXIT_POLICY = ChildExitPolicy(
    success_codes=frozenset({0}),
    no_match_codes=frozenset({1}),
    no_match_requires_empty=False,
)
STRICT_CHILD_EXIT_POLICY = ChildExitPolicy(success_codes=frozenset({0}))


def _exit_policy(value: ChildExitPolicy | None) -> ChildExitPolicy:
    return value or STRICT_CHILD_EXIT_POLICY


@dataclass(frozen=True, slots=True)
class ChildOutcome:
    """Bounded child bytes and lifecycle state, independent of command meaning."""

    stdout: bytes
    stderr: bytes
    returncode: int | None
    status: str
    reaped: bool
    timed_out: bool = False
    cancelled: bool = False
    error: BaseException | None = None


_ChildOutcome = ChildOutcome


@dataclass(frozen=True, slots=True)
class CompleteFileCandidateResult:
    """Complete-file candidate admission with one non-returned overflow sentinel."""

    candidates: tuple[Any, ...]
    raw_count: int
    overflowed: bool
    complete: bool = True

    @property
    def total_exact(self) -> bool:
        return self.complete and not self.overflowed

    @property
    def sentinel_seen(self) -> bool:
        return self.overflowed


def collect_complete_file_candidates(
    values: Iterable[Any],
    remaining: int,
    *,
    transform: Callable[[Any], Any] | None = None,
    budget: OperationBudget | None = None,
) -> CompleteFileCandidateResult:
    """Admit at most ``remaining`` candidates and inspect one extra sentinel.

    ``transform`` is deliberately not invoked for the sentinel, which lets
    callers avoid constructing a model for the one record used solely to prove
    overflow.  Once the sentinel is observed, no later candidate is extracted
    or transformed; the complete-file result is intentionally bounded by
    ``remaining + 1`` raw units.
    """
    if not _is_strict_int(remaining) or remaining < 0:
        raise ValueError("remaining candidate budget must be a non-negative integer")
    admitted: list[Any] = []
    raw_count = 0
    overflowed = False
    for value in values:
        _budget_gate(budget)
        raw_count += 1
        if raw_count <= remaining:
            admitted.append(transform(value) if transform is not None else value)
            continue
        overflowed = True
        break
    _budget_gate(budget)
    return CompleteFileCandidateResult(tuple(admitted), raw_count, overflowed)


class _BinaryChildCapture:
    """Stream one child through bounded binary readers and queues."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        limits: AstGrepLimits,
        process_factory: Callable[..., Any] | None = None,
        environment_builder: Callable[[Mapping[str, str] | None], Mapping[str, str]] | None = None,
        check_line: bool = False,
    ) -> None:
        self.command = tuple(command)
        self.limits = limits
        self.process_factory = process_factory or subprocess.Popen
        self.environment_builder = environment_builder or sanitized_environment
        self.check_line = check_line
        self.process: Any = None
        queue_slots = max(1, limits.queued_bytes // limits.chunk_bytes)
        self.queues: dict[str, queue.Queue[bytes]] = {
            "stdout": queue.Queue(maxsize=queue_slots),
            "stderr": queue.Queue(maxsize=queue_slots),
        }
        self.queue_lock = threading.Lock()
        self.queued_bytes = 0
        self.peak_queued_bytes = 0
        self.seen = {"stdout": 0, "stderr": 0}
        self.stored = {"stdout": bytearray(), "stderr": bytearray()}
        self.reader_done = {"stdout": False, "stderr": False}
        self.reader_errors: list[tuple[str, BaseException]] = []
        self.stop_readers = threading.Event()
        self.input_error = False
        self.status: str | None = None
        self.line_length = 0
        self._status_lock = threading.Lock()

    def _set_status(self, status: str) -> None:
        with self._status_lock:
            if self.status is None:
                self.status = status
                self.stop_readers.set()

    def _reader(self, name: Literal["stdout", "stderr"], stream: Any) -> None:
        try:
            while not self.stop_readers.is_set():
                chunk = stream.read(self.limits.chunk_bytes)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    self._set_status("io_error")
                    break
                with self._status_lock:
                    self.seen[name] += len(chunk)
                    hard = self.limits.stdout_bytes if name == "stdout" else self.limits.stderr_bytes
                    if self.seen[name] > hard:
                        self.status = self.status or f"{name}_overflow"
                        self.stop_readers.set()
                        break
                while not self.stop_readers.is_set():
                    with self.queue_lock:
                        if self.queued_bytes + len(chunk) <= self.limits.queued_bytes:
                            self.queues[name].put_nowait(chunk)
                            self.queued_bytes += len(chunk)
                            self.peak_queued_bytes = max(self.peak_queued_bytes, self.queued_bytes)
                            break
                    time.sleep(0.001)
        except BaseException as exc:
            self.reader_errors.append((name, exc))
            self._set_status("io_error")
        finally:
            self.reader_done[name] = True

    def _consume(self, name: Literal["stdout", "stderr"], chunk: bytes) -> None:
        with self.queue_lock:
            self.queued_bytes = max(0, self.queued_bytes - len(chunk))
        hard = self.limits.stdout_bytes if name == "stdout" else self.limits.stderr_bytes
        remaining = hard - len(self.stored[name])
        if remaining > 0:
            self.stored[name].extend(chunk[:remaining])
        if not self.check_line or name != "stdout" or self.status is not None:
            return
        parts = chunk.split(b"\n")
        for index, part in enumerate(parts):
            self.line_length += len(part)
            if self.line_length > self.limits.line_bytes:
                self._set_status("huge_line")
                return
            if index < len(parts) - 1:
                self.line_length = 0

    def _terminate(self, *, force: bool = False) -> None:
        process = self.process
        if process is None:
            return
        try:
            poll = process.poll()
        except Exception:
            poll = None
        if poll is not None and not force:
            return
        pid = getattr(process, "pid", None)
        sent_group = False
        if isinstance(pid, int) and pid > 0:
            try:
                os.killpg(pid, signal.SIGKILL if force else signal.SIGTERM)
                sent_group = True
            except (OSError, ProcessLookupError):
                pass
        try:
            if force:
                process.kill()
            elif not sent_group:
                process.terminate()
        except (OSError, ProcessLookupError):
            pass

    def _reap(self) -> bool:
        process = self.process
        if process is None:
            return True
        try:
            process.wait(timeout=0.5)
            return True
        except subprocess.TimeoutExpired:
            self._terminate(force=True)
            try:
                process.wait(timeout=1.0)
                return True
            except subprocess.TimeoutExpired:
                return False
        except (OSError, ProcessLookupError):
            try:
                process.wait()
                return True
            except Exception:
                return False

    def run(
        self,
        *,
        input_bytes: bytes | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        cancel: object | None = None,
        budget: OperationBudget | None = None,
        check_line: bool = False,
        exit_policy: ChildExitPolicy | None = None,
    ) -> _ChildOutcome:
        policy = _exit_policy(exit_policy)
        try:
            budget_timeout = _budget_timeout(budget, timeout)
        except Exception as exc:
            raise _budget_failure(exc) from exc
        timeout_value = (
            self.limits.timeout_seconds
            if budget_timeout is None
            else min(budget_timeout, self.limits.hard_timeout_seconds)
        )
        if timeout_value <= 0:
            raise ValueError("timeout must be positive")
        effective_cancel = _combined_cancel(cancel, budget)
        deadline = time.monotonic() + timeout_value
        try:
            self.process = self.process_factory(
                list(self.command),
                stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=self.environment_builder(env),
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise AstGrepNotFoundError("ast-grep executable was not found; symbol search could not run.") from exc
        except OSError as exc:
            raise AstGrepCommandError(f"could not start ast-grep: {exc}", status="start_failed") from exc

        stdout_stream = getattr(self.process, "stdout", None)
        stderr_stream = getattr(self.process, "stderr", None)
        if stdout_stream is None or stderr_stream is None:
            self._set_status("io_error")
            self._terminate()
            reaped = self._reap()
            return _ChildOutcome(b"", b"", self._returncode(), self.status or "io_error", reaped)

        threads = [
            threading.Thread(target=self._reader, args=("stdout", stdout_stream), daemon=True),
            threading.Thread(target=self._reader, args=("stderr", stderr_stream), daemon=True),
        ]
        for thread in threads:
            thread.start()

        input_thread: threading.Thread | None = None
        if input_bytes is not None:
            stdin_stream = getattr(self.process, "stdin", None)
            if stdin_stream is not None:

                def write_input() -> None:
                    try:
                        for offset in range(0, len(input_bytes), self.limits.chunk_bytes):
                            if self.stop_readers.is_set():
                                break
                            stdin_stream.write(input_bytes[offset : offset + self.limits.chunk_bytes])
                        stdin_stream.close()
                    except (BrokenPipeError, OSError):
                        self.input_error = True
                        try:
                            stdin_stream.close()
                        except Exception:
                            pass

                input_thread = threading.Thread(target=write_input, daemon=True)
                input_thread.start()

        termination_started: float | None = None
        while True:
            drained = False
            for name in ("stdout", "stderr"):
                while True:
                    try:
                        chunk = self.queues[name].get_nowait()
                    except queue.Empty:
                        break
                    self._consume(name, chunk)
                    drained = True
            if self.status is not None:
                if termination_started is None:
                    termination_started = time.monotonic()
                self._terminate()
                if time.monotonic() - termination_started >= CHILD_TERM_GRACE_SECONDS:
                    self._terminate(force=True)
            elif budget is not None:
                try:
                    budget.check_deadline()
                except Exception as exc:
                    self._set_status(_budget_failure(exc).status)
                    termination_started = time.monotonic()
                if self.status is None and _is_cancelled(effective_cancel):
                    self._set_status("cancelled")
                    self._terminate()
                    termination_started = time.monotonic()
                elif self.status is None and time.monotonic() >= deadline:
                    self._set_status("timeout")
                    self._terminate()
                    termination_started = time.monotonic()
            elif _is_cancelled(effective_cancel):
                self._set_status("cancelled")
                self._terminate()
                termination_started = time.monotonic()
            elif time.monotonic() >= deadline:
                self._set_status("timeout")
                self._terminate()
                termination_started = time.monotonic()
            try:
                exited = self.process.poll() is not None
            except Exception:
                exited = False
            if exited and all(self.reader_done.values()) and all(q.empty() for q in self.queues.values()):
                break
            if not drained:
                time.sleep(0.001)

        reaped = self._reap()
        self.stop_readers.set()
        for thread in threads:
            thread.join(timeout=1.0)
        if input_thread is not None:
            input_thread.join(timeout=1.0)
        for stream in (stdout_stream, stderr_stream):
            try:
                stream.close()
            except Exception:
                pass
        status = self.status
        returncode = self._returncode()
        stdout = bytes(self.stored["stdout"])
        stderr = bytes(self.stored["stderr"])
        if status is None:
            if self.reader_errors or self.input_error:
                status = "io_error"
            else:
                status = policy.classify(returncode, stdout=stdout, stderr=stderr)
        return _ChildOutcome(
            stdout,
            stderr,
            returncode,
            status,
            reaped,
            timed_out=status == "timeout",
            cancelled=status == "cancelled",
        )

    def _returncode(self) -> int | None:
        value = getattr(self.process, "returncode", None)
        return value if isinstance(value, int) else 0


class BoundedAstGrepExecutor:
    """One-child bounded executor with explicit input and cancellation seams."""

    def __init__(
        self,
        limits: AstGrepLimits | None = None,
        *,
        process_factory: Callable[..., Any] | None = None,
        executable: str | os.PathLike[str] | None = None,
        environment_builder: Callable[[Mapping[str, str] | None], Mapping[str, str]] | None = None,
    ) -> None:
        self.limits = limits or AstGrepLimits()
        self.process_factory = process_factory or subprocess.Popen
        self.executable = executable
        self.environment_builder = environment_builder or sanitized_environment

    def execute(
        self,
        args: Sequence[str],
        *,
        input_bytes: bytes | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        cancel: object | None = None,
        budget: OperationBudget | None = None,
        check_line: bool = False,
    ) -> _ChildOutcome:
        executable = resolve_ast_grep_executable(self.executable)
        command = [executable, *(str(arg) for arg in args)]
        if any("\x00" in arg for arg in command):
            raise ValueError("ast-grep arguments must not contain NUL bytes")
        return BoundedChildExecutor(
            self.limits,
            process_factory=self.process_factory,
            environment_builder=self.environment_builder,
        ).execute(
            command,
            input_bytes=input_bytes,
            cwd=cwd,
            env=env,
            timeout=timeout,
            cancel=cancel,
            budget=budget,
            check_line=check_line,
            exit_policy=AST_GREP_EXIT_POLICY,
        )

    run = execute


class BoundedChildExecutor:
    """Command-neutral bounded child lifecycle with explicit exit policy."""

    def __init__(
        self,
        limits: AstGrepLimits | None = None,
        *,
        process_factory: Callable[..., Any] | None = None,
        environment_builder: Callable[[Mapping[str, str] | None], Mapping[str, str]] | None = None,
    ) -> None:
        self.limits = limits or AstGrepLimits()
        self.process_factory = process_factory or subprocess.Popen
        self.environment_builder = environment_builder or sanitized_environment

    def execute(
        self,
        command: Sequence[str],
        *,
        input_bytes: bytes | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        cancel: object | None = None,
        budget: OperationBudget | None = None,
        check_line: bool = False,
        exit_policy: ChildExitPolicy | None = None,
    ) -> ChildOutcome:
        values = [str(value) for value in command]
        if not values or any("\x00" in value for value in values):
            raise ValueError("child command must be non-empty and NUL-free")
        return _BinaryChildCapture(
            values,
            limits=self.limits,
            process_factory=self.process_factory,
            environment_builder=self.environment_builder,
            check_line=check_line,
        ).run(
            input_bytes=input_bytes,
            cwd=cwd,
            env=env,
            timeout=timeout,
            cancel=cancel,
            budget=budget,
            check_line=check_line,
            exit_policy=exit_policy,
        )

    run = execute


def run_bounded_child(
    command: Sequence[str],
    *,
    limits: AstGrepLimits | None = None,
    process_factory: Callable[..., Any] | None = None,
    environment_builder: Callable[[Mapping[str, str] | None], Mapping[str, str]] | None = None,
    input_bytes: bytes | None = None,
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    cancel: object | None = None,
    budget: OperationBudget | None = None,
    check_line: bool = False,
    exit_policy: ChildExitPolicy | None = None,
) -> ChildOutcome:
    """Run one command through the shared bounded child lifecycle."""

    return BoundedChildExecutor(
        limits,
        process_factory=process_factory,
        environment_builder=environment_builder,
    ).execute(
        command,
        input_bytes=input_bytes,
        cwd=cwd,
        env=env,
        timeout=timeout,
        cancel=cancel,
        budget=budget,
        check_line=check_line,
        exit_policy=exit_policy,
    )


def _raise_outcome(outcome: _ChildOutcome, *, limits: AstGrepLimits | None = None) -> None:
    status = outcome.status
    hard_limits = limits or AstGrepLimits()
    error_type: type[AstGrepError] = AstGrepCommandError
    if status in {"stdout_overflow", "stderr_overflow"}:
        stream = status.split("_", 1)[0]
        limit = hard_limits.stdout_bytes if stream == "stdout" else hard_limits.stderr_bytes
        message = f"ast-grep {stream} exceeded {limit} bytes"
        error_type = AstGrepOutputLimitError
    elif status == "huge_line":
        message = f"ast-grep streaming record exceeded {hard_limits.line_bytes} bytes"
        error_type = AstGrepHugeLineError
    elif status == "invalid_utf8":
        message = "ast-grep returned invalid UTF-8"
        error_type = AstGrepEncodingError
    elif status == "timeout":
        message = f"ast-grep timed out after {hard_limits.timeout_seconds:g} seconds"
        error_type = AstGrepTimeoutError
    elif status == "cancelled":
        message = "ast-grep execution was cancelled"
        error_type = AstGrepCancelledError
    elif status == "nonzero_exit":
        message = f"ast-grep failed with exit code {outcome.returncode}: " + (
            outcome.stderr.decode("utf-8", "replace").strip() or "(no error output)"
        )
        if outcome.returncode == AST_GREP_VALIDATION_EXIT_CODE:
            error_type = AstGrepValidationError
        else:
            error_type = AstGrepCommandError
    elif status == "io_error":
        message = "ast-grep child I/O failed"
    else:
        message = f"ast-grep child execution failed: {status}"
    raise error_type(
        message,
        status=status,
        returncode=outcome.returncode,
        reaped=outcome.reaped,
        stdout=outcome.stdout,
        stderr=outcome.stderr,
    )


def _decode_utf8(data: bytes, *, stream: str, outcome: _ChildOutcome | None = None) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AstGrepEncodingError(
            f"ast-grep {stream} was not valid UTF-8",
            status="invalid_utf8",
            returncode=outcome.returncode if outcome is not None else None,
            reaped=outcome.reaped if outcome is not None else None,
            stdout=(outcome.stdout if stream == "stdout" else b"") if outcome is not None else data,
            stderr=(outcome.stderr if stream == "stderr" else b"") if outcome is not None else b"",
        ) from exc


def run_ast_grep(
    args: Sequence[str],
    input_text: str | None = None,
    *,
    cwd: Path | None = None,
    input_bytes: bytes | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    cancel: object | None = None,
    budget: OperationBudget | None = None,
    executor: BoundedAstGrepExecutor | None = None,
) -> AstGrepResult:
    """Run one bounded ast-grep command and preserve current no-match behavior."""
    _budget_gate(budget)
    if input_text is not None and input_bytes is not None:
        raise ValueError("supply input_text or input_bytes, not both")
    raw_input = input_bytes if input_bytes is not None else _coerce_input_bytes(input_text)
    runner = executor or BoundedAstGrepExecutor()
    outcome = runner.execute(
        args,
        input_bytes=raw_input,
        cwd=cwd,
        env=env,
        timeout=timeout,
        cancel=cancel,
        budget=budget,
    )
    _budget_gate(budget)
    stdout = _decode_utf8(outcome.stdout, stream="stdout", outcome=outcome)
    stderr = _decode_utf8(outcome.stderr, stream="stderr", outcome=outcome)
    if (
        outcome.status in {"complete", "no_match", "nonzero_exit"}
        and outcome.returncode == 1
        and not stderr.strip()
        and _is_no_match_output(stdout, args)
    ):
        return AstGrepResult(stdout, stderr, 1, no_matches=True)
    if outcome.status not in {"complete", "no_match"}:
        _raise_outcome(outcome, limits=runner.limits)
    if outcome.returncode == 0:
        return AstGrepResult(stdout, stderr, 0)
    error_output = stderr.strip() if stderr else "(no error output)"
    error_type = AstGrepValidationError if outcome.returncode == AST_GREP_VALIDATION_EXIT_CODE else AstGrepCommandError
    raise error_type(
        f"ast-grep failed with exit code {outcome.returncode}: {error_output}",
        status="validation_failed" if error_type is AstGrepValidationError else "command_failed",
        returncode=outcome.returncode,
        reaped=outcome.reaped,
        stdout=outcome.stdout,
        stderr=outcome.stderr,
    )


def _strict_json_loads(value: str) -> Any:
    def reject_constant(token: str) -> Any:
        raise ValueError(token)

    return json.loads(value, parse_constant=reject_constant)


def _iter_stream_lines(stdout: bytes) -> Iterator[bytes]:
    """Yield bounded newline-delimited records without building splitlines()."""

    start = 0
    while start < len(stdout):
        newline = stdout.find(b"\n", start)
        if newline < 0:
            yield stdout[start:]
            return
        yield stdout[start:newline]
        start = newline + 1


def _stream_record(line: bytes, *, outcome: _ChildOutcome | None = None) -> dict[str, Any]:
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AstGrepEncodingError(
            "ast-grep streaming output was not valid UTF-8",
            status="invalid_utf8",
            returncode=outcome.returncode if outcome is not None else None,
            reaped=outcome.reaped if outcome is not None else None,
            stdout=outcome.stdout if outcome is not None else line,
            stderr=outcome.stderr if outcome is not None else b"",
        ) from exc
    try:
        parsed = _strict_json_loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise AstGrepJsonError("ast-grep returned invalid streaming JSON", status="invalid_json") from exc
    if not isinstance(parsed, dict):
        raise AstGrepJsonError(
            "ast-grep returned unexpected streaming JSON; expected match objects",
            status="invalid_json",
        )
    return cast(dict[str, Any], parsed)


def _parsed_stream_objects(
    stdout: bytes,
    *,
    outcome: _ChildOutcome | None = None,
    budget: OperationBudget | None = None,
) -> Iterator[dict[str, Any]]:
    for line in _iter_stream_lines(stdout):
        _budget_gate(budget)
        if not line.strip():
            continue
        yield _stream_record(line, outcome=outcome)
    _budget_gate(budget)


def run_ast_grep_bounded(
    args: Sequence[str],
    max_results: int,
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
    input_bytes: bytes | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    cancel: object | None = None,
    budget: OperationBudget | None = None,
    executor: BoundedAstGrepExecutor | None = None,
) -> BoundedAstGrepResult:
    """Run a complete bounded stream and admit only complete-file records.

    At most ``max_results`` records are retained.  One additional raw record
    is consumed as an overflow sentinel; no later candidate is extracted.
    """
    if not _is_strict_int(max_results) or max_results < 0:
        raise ValueError("max_results must be a non-negative integer")
    _budget_gate(budget)
    if input_text is not None and input_bytes is not None:
        raise ValueError("supply input_text or input_bytes, not both")
    raw_input = input_bytes if input_bytes is not None else _coerce_input_bytes(input_text)
    stream_args: list[str] = []
    skip_next_thread_value = False
    for arg in (str(value) for value in args):
        _budget_gate(budget)
        if skip_next_thread_value:
            skip_next_thread_value = False
            continue
        if arg == "--threads":
            skip_next_thread_value = True
            continue
        if arg.startswith("--json"):
            continue
        stream_args.append(arg)
    streaming_flags = ["--threads", "1", "--json=stream"]
    try:
        separator = stream_args.index("--")
    except ValueError:
        stream_args.extend(streaming_flags)
    else:
        stream_args[separator:separator] = streaming_flags
    runner = executor or BoundedAstGrepExecutor()
    outcome = runner.execute(
        stream_args,
        input_bytes=raw_input,
        cwd=cwd,
        env=env,
        timeout=timeout,
        cancel=cancel,
        budget=budget,
        check_line=True,
    )
    _budget_gate(budget)
    if outcome.status not in {"complete", "no_match"}:
        _raise_outcome(outcome, limits=runner.limits)
    try:
        admitted = collect_complete_file_candidates(
            _parsed_stream_objects(outcome.stdout, outcome=outcome, budget=budget),
            max_results,
            budget=budget,
        )
    except AstGrepEncodingError:
        raise
    except AstGrepError as exc:
        raise type(exc)(
            str(exc),
            status=exc.status,
            returncode=outcome.returncode,
            reaped=outcome.reaped,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
        ) from exc
    stdout = _decode_utf8(outcome.stdout, stream="stdout", outcome=outcome)
    stderr = _decode_utf8(outcome.stderr, stream="stderr", outcome=outcome)
    if outcome.returncode not in (0, 1):
        error_type = (
            AstGrepValidationError if outcome.returncode == AST_GREP_VALIDATION_EXIT_CODE else AstGrepCommandError
        )
        raise error_type(
            f"ast-grep failed with exit code {outcome.returncode}: {stderr.strip() or '(no error output)'}",
            status="validation_failed" if error_type is AstGrepValidationError else "command_failed",
            returncode=outcome.returncode,
            reaped=outcome.reaped,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
        )
    if outcome.returncode == 1 and (admitted.raw_count or stderr.strip()):
        raise AstGrepCommandError(
            "ast-grep returned a nonzero exit with output or diagnostics",
            status="nonzero_exit",
            returncode=outcome.returncode,
            reaped=outcome.reaped,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
        )
    return BoundedAstGrepResult(
        matches=[cast(dict[str, Any], item) for item in admitted.candidates],
        total_exact=admitted.total_exact,
        stdout=stdout,
        stderr=stderr,
        returncode=outcome.returncode or 0,
        complete=admitted.complete,
        raw_count=admitted.raw_count,
        overflowed=admitted.overflowed,
    )


def _normalize_captured_inputs(
    inputs: Mapping[str, bytes] | Iterable[Any],
    *,
    budget: OperationBudget | None = None,
) -> list[CapturedInput]:
    normalized: list[CapturedInput] = []
    if isinstance(inputs, Mapping):
        mapping_inputs = cast(Mapping[str, bytes], inputs)
        values: Iterable[tuple[str, bytes]] = ((path, content) for path, content in mapping_inputs.items())
    else:
        values = ((item.path, item.content) for item in inputs)
    for path, content in values:
        _budget_gate(budget)
        normalized.append(CapturedInput(path, content))
    paths = [item.path for item in normalized]
    if len(paths) != len(set(paths)):
        raise ValueError("captured input paths must be unique")
    return normalized


_DROP_RULE_VALUE_FLAGS = frozenset({"--config", "-c", "--rule", "-r", "--inline-rules", "--globs", "--no-ignore"})
_KEEP_RULE_VALUE_FLAGS = frozenset(
    {
        "--threads",
        "-j",
        "--max-results",
        "--format",
        "--report-style",
        "--color",
        "--error",
        "--warning",
        "--info",
        "--hint",
        "--off",
        "--after",
        "-A",
        "--before",
        "-B",
        "--context",
        "-C",
        "--lang",
    }
)


def _rule_execution_arguments(
    args: Sequence[str],
    *,
    source_paths: Sequence[str],
    config_path: str,
    mode: str,
) -> list[str]:
    if mode not in {"search", "render_fixes"}:
        raise ValueError("captured rule execution mode must be search or render_fixes")
    values = [str(value) for value in args]
    if not values or values[0] != "scan":
        raise ValueError("captured rule execution requires the ast-grep scan command")
    result = ["scan"]
    skip_next = False
    keep_next = False
    for value in values[1:]:
        if skip_next:
            skip_next = False
            continue
        if keep_next:
            result.append(value)
            keep_next = False
            continue
        if value in _DROP_RULE_VALUE_FLAGS:
            skip_next = True
            continue
        if any(value.startswith(flag + "=") for flag in _DROP_RULE_VALUE_FLAGS):
            continue
        if value in {"--follow", "--stdin", "--update-all"}:
            continue
        if value in _KEEP_RULE_VALUE_FLAGS:
            result.append(value)
            keep_next = True
            continue
        if value.startswith("-"):
            result.append(value)
            continue
        # Positional paths are owned by the captured source set below.  Drop
        # every caller-provided one so an invocation cannot widen the set.
    result.extend(["--config", config_path])
    if mode == "render_fixes":
        result.append("--update-all")
    result.extend(["--", *source_paths])
    return result


def _rule_set_values(rule_set: Any) -> tuple[Any, ...]:
    try:
        from xray.core.repository import CapturedRuleSet
    except ImportError as exc:
        raise ValueError("captured rule execution requires repository support") from exc
    if not isinstance(rule_set, CapturedRuleSet):
        raise ValueError("rule_set must be a CapturedRuleSet")
    rules = tuple(rule_set.rules)
    if not rules:
        raise ValueError("captured rule set is empty")
    paths = [item.path for item in rules]
    if paths != sorted(paths, key=lambda value: value.encode("utf-8")) or len(paths) != len(set(paths)):
        raise ValueError("captured rule files must be unique and path sorted")
    return rules


def _reserve_temporary_bytes(budget: OperationBudget | None, size: int) -> None:
    if budget is None:
        return
    try:
        budget.charge_temporary(size)
    except Exception as exc:
        if getattr(exc, "kind", None) in {"cancelled", "deadline"}:
            raise _budget_failure(exc) from exc
        raise AstGrepOutputLimitError(str(exc), status="temporary_overflow") from exc


_PATTERN_VALUE_FLAGS = frozenset(
    {
        "--pattern",
        "-p",
        "--rewrite",
        "-r",
        "--lang",
        "--threads",
        "-j",
        "--max-results",
        "--format",
        "--report-style",
        "--color",
        "--error",
        "--warning",
        "--info",
        "--hint",
        "--off",
        "--after",
        "-A",
        "--before",
        "-B",
        "--context",
        "-C",
        "--globs",
    }
)


def _pattern_execution_arguments(args: Sequence[str], *, source_paths: Sequence[str]) -> list[str]:
    values = [str(value) for value in args]
    if not values or values[0] != "run":
        raise ValueError("captured pattern execution requires the ast-grep run command")
    result = ["run"]
    keep_next = False
    for value in values[1:]:
        if value == "--":
            break
        if keep_next:
            result.append(value)
            keep_next = False
            continue
        if value in _PATTERN_VALUE_FLAGS:
            result.append(value)
            keep_next = True
            continue
        if any(value.startswith(flag + "=") for flag in _PATTERN_VALUE_FLAGS):
            result.append(value)
            continue
        if value.startswith("-"):
            result.append(value)
            continue
        # Positional paths belong to the explicit captured source subset.
    result.extend(["--", *source_paths])
    return result


class _CapturedAstGrepSession:
    """One immutable captured tree shared by bounded per-file executions."""

    def __init__(
        self,
        normalized: Sequence[CapturedInput],
        rule_set: Any | None,
        *,
        budget: OperationBudget | None,
    ) -> None:
        self._normalized = tuple(normalized)
        self._rule_set = rule_set
        self._rules = _rule_set_values(rule_set) if rule_set is not None else ()
        self._budget = budget
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self._root: Path | None = None
        self._source_root: Path | None = None
        self._config_path: Path | None = None
        self._opened = False
        self.source_paths = tuple(item.path for item in self._normalized)

    def open(self) -> _CapturedAstGrepSession:
        if self._opened:
            raise RuntimeError("captured ast-grep session is already open")
        generated_config = b"ruleDirs:\n  - rules\n" if self._rule_set is not None else b""
        total_bytes = len(generated_config) + sum(len(item.content) for item in self._normalized)
        total_bytes += sum(len(item.content) for item in self._rules)
        if total_bytes > TEMPORARY_BYTES_LIMIT:
            raise AstGrepOutputLimitError(
                f"captured ast-grep inputs exceed {TEMPORARY_BYTES_LIMIT} bytes",
                status="temporary_overflow",
            )
        _reserve_temporary_bytes(self._budget, total_bytes)
        try:
            temporary = tempfile.TemporaryDirectory(prefix="xray-ast-grep-")
        except OSError as exc:
            raise AstGrepCommandError("could not create ast-grep capture directory", status="io_error") from exc
        self._temporary = temporary
        root = Path(temporary.name)
        source_root = root / "sources" if self._rule_set is not None else root
        config_path = root / "sgconfig.yml" if self._rule_set is not None else None
        self._root = root
        self._source_root = source_root
        self._config_path = config_path
        try:
            for item in sorted(self._normalized, key=lambda value: value.path.encode("utf-8")):
                _budget_gate(self._budget)
                target = source_root / item.path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(item.content)
            if self._rule_set is not None:
                rule_root = root / "rules"
                for item in self._rules:
                    _budget_gate(self._budget)
                    target = rule_root / item.path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(item.content)
                _budget_gate(self._budget)
                if config_path is None:
                    raise RuntimeError("captured rule session has no configuration path")
                config_path.write_bytes(generated_config)
        except (OSError, ValueError) as exc:
            temporary.cleanup()
            self._temporary = None
            self._root = None
            self._source_root = None
            self._config_path = None
            raise AstGrepCommandError(
                "could not materialize captured ast-grep execution",
                status="io_error",
            ) from exc
        self._opened = True
        return self

    def close(self) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()
        self._temporary = None
        self._root = None
        self._source_root = None
        self._config_path = None
        self._opened = False

    def _selected_paths(self, source_paths: Sequence[str]) -> tuple[str, ...]:
        values = tuple(str(value) for value in source_paths)
        if len(values) != len(set(values)):
            raise ValueError("captured source paths must be unique")
        known = set(self.source_paths)
        for value in values:
            try:
                CapturedInput(value, b"")
            except ValueError as exc:
                raise ValueError("captured source path must be canonical and contained") from exc
            if value not in known:
                raise ValueError("captured source path is not part of this session")
        return values

    @staticmethod
    def _empty_result(max_results: int | None) -> AstGrepResult | BoundedAstGrepResult:
        if max_results is None:
            return AstGrepResult("[]", "", 0, no_matches=True)
        return BoundedAstGrepResult(
            matches=[],
            total_exact=True,
            stdout="[]",
            stderr="",
            returncode=0,
            complete=True,
            raw_count=0,
            overflowed=False,
        )

    def execute(
        self,
        args: Sequence[str],
        *,
        source_paths: Sequence[str],
        max_results: int | None = None,
        timeout: float | None = None,
        cancel: object | None = None,
        executor: BoundedAstGrepExecutor | None = None,
        mode: Literal["search", "render_fixes"] = "search",
    ) -> AstGrepResult | BoundedAstGrepResult:
        if not self._opened or self._root is None or self._source_root is None:
            raise RuntimeError("captured ast-grep session is not open")
        if max_results is not None and (not _is_strict_int(max_results) or max_results < 0):
            raise ValueError("max_results must be a non-negative integer")
        _budget_gate(self._budget)
        selected = self._selected_paths(source_paths)
        if self._rule_set is not None:
            if self._config_path is None:
                raise RuntimeError("captured rule session has no generated configuration")
            execution_args = _rule_execution_arguments(
                args,
                source_paths=selected,
                config_path=self._config_path.as_posix(),
                mode=mode,
            )
            cwd = self._source_root
        else:
            if mode not in {"search", "render_fixes"}:
                raise ValueError("captured execution mode must be search or render_fixes")
            execution_args = _pattern_execution_arguments(args, source_paths=selected)
            cwd = self._root
        if not selected:
            return self._empty_result(max_results)
        if max_results is None:
            return run_ast_grep(
                execution_args,
                cwd=cwd,
                timeout=timeout,
                cancel=cancel,
                budget=self._budget,
                executor=executor,
            )
        return run_ast_grep_bounded(
            execution_args,
            max_results,
            cwd=cwd,
            timeout=timeout,
            cancel=cancel,
            budget=self._budget,
            executor=executor,
        )


@contextmanager
def captured_ast_grep_session(
    inputs: Mapping[str, bytes] | Iterable[CapturedInput] | Iterable[Any],
    rule_set: Any | None = None,
    *,
    budget: OperationBudget | None = None,
) -> Generator[_CapturedAstGrepSession, None, None]:
    """Materialize captured sources and rules once for explicit file scans."""

    _budget_gate(budget)
    normalized = _normalize_captured_inputs(inputs, budget=budget)
    session = _CapturedAstGrepSession(normalized, rule_set, budget=budget)
    session.open()
    try:
        yield session
    finally:
        session.close()


def run_ast_grep_captured(
    args: Sequence[str],
    inputs: Mapping[str, bytes] | Iterable[CapturedInput] | Iterable[Any],
    rule_set: Any | None = None,
    *,
    max_results: int | None = None,
    timeout: float | None = None,
    cancel: object | None = None,
    budget: OperationBudget | None = None,
    executor: BoundedAstGrepExecutor | None = None,
    mode: Literal["search", "render_fixes"] = "search",
) -> AstGrepResult | BoundedAstGrepResult:
    """Execute once over the complete captured source set."""

    with captured_ast_grep_session(inputs, rule_set, budget=budget) as session:
        return session.execute(
            args,
            source_paths=session.source_paths,
            max_results=max_results,
            timeout=timeout,
            cancel=cancel,
            executor=executor,
            mode=mode,
        )


def parse_json_array(stdout: str) -> list[dict[str, Any]]:
    """Parse ast-grep JSON output and require a strict array of objects."""

    try:
        parsed = _strict_json_loads(stdout or "[]")
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("ast-grep returned invalid JSON") from exc
    if not isinstance(parsed, list):
        raise ValueError("ast-grep returned unexpected JSON; expected a list of matches.")
    parsed_matches = cast(list[Any], parsed)
    if not all(isinstance(match, dict) for match in parsed_matches):
        raise ValueError("ast-grep returned unexpected JSON; expected match objects.")
    return cast(list[dict[str, Any]], parsed_matches)


def _is_no_match_output(stdout: str, args: Sequence[str]) -> bool:
    stripped = stdout.strip()
    if not stripped:
        return True
    if "--json=stream" in args:
        return False
    if any(arg == "--json" or arg.startswith("--json=") for arg in args):
        try:
            parsed = _strict_json_loads(stripped)
        except (json.JSONDecodeError, ValueError):
            return False
        return isinstance(parsed, list) and not parsed
    return False


__all__ = [
    "AST_GREP_EXIT_POLICY",
    "AST_GREP_VALIDATION_EXIT_CODE",
    "CHUNK_BYTES",
    "DEFAULT_AST_GREP_TIMEOUT_SECONDS",
    "HARD_AST_GREP_TIMEOUT_SECONDS",
    "LINE_BYTES_LIMIT",
    "QUEUED_BYTES_LIMIT",
    "STDERR_LIMIT_BYTES",
    "STDOUT_LIMIT_BYTES",
    "STRICT_CHILD_EXIT_POLICY",
    "AstGrepCancelledError",
    "AstGrepCommandError",
    "AstGrepEncodingError",
    "AstGrepError",
    "AstGrepHugeLineError",
    "AstGrepJsonError",
    "AstGrepLimits",
    "AstGrepNotFoundError",
    "AstGrepOutputLimitError",
    "AstGrepResult",
    "AstGrepTimeoutError",
    "AstGrepValidationError",
    "BoundedAstGrepExecutor",
    "BoundedAstGrepResult",
    "BoundedChildExecutor",
    "CapturedInput",
    "ChildExitPolicy",
    "ChildOutcome",
    "CompleteFileCandidateResult",
    "captured_ast_grep_session",
    "collect_complete_file_candidates",
    "parse_json_array",
    "resolve_ast_grep_executable",
    "run_ast_grep",
    "run_ast_grep_bounded",
    "run_ast_grep_captured",
    "run_bounded_child",
    "sanitized_environment",
]
