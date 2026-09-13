"""Complete, guarded AST-backed change planning and application.

The service deliberately owns one ordinary lifecycle for pattern and captured-rule
sources.  Repository capture and ast-grep remain the authorities for selection,
matching, and fix rendering; this module only turns their bounded evidence into a
closed ``xray.change.v1`` plan and performs the guarded filesystem cut-over.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import os
import shutil
import stat as stat_module
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from ast_grep_py import SgRoot  # pyright: ignore[reportMissingImports]

from xray.core.ast_grep import (
    STRICT_CHILD_EXIT_POLICY,
    AstGrepError,
    AstGrepLimits,
    BoundedAstGrepExecutor,
    BoundedAstGrepResult,
    ChildExitPolicy,
    ChildOutcome,
    run_ast_grep_captured,
    run_bounded_child,
)
from xray.core.repository import (
    SUPPORTED_SOURCE_DOMAIN,
    CapturedFile,
    CapturedRuleSet,
    OperationBudget,
    RepositoryCapture,
    RepositoryError,
    RepositoryProvider,
    normalize_root,
)
from xray.core.toolchain import ToolchainObservation, ToolchainProvider, ToolchainUnavailableError
from xray.models import (
    Acknowledgements,
    BaselineGit,
    BaselineUnmanaged,
    ChangeApplyArguments,
    ChangeApplyData,
    ChangeApplyRequest,
    ChangePlan,
    ChangePlanArguments,
    ChangePlanData,
    ChangePlanQuery,
    ChangePlanRequest,
    ChangeRefineArguments,
    ChangeRefineRequest,
    ChangeSource,
    ChangeVerifyArguments,
    ChangeVerifyData,
    ChangeVerifyRequest,
    ChosenAll,
    ChosenEdits,
    Coverage,
    Eligibility,
    Error,
    ErrorDetails,
    ErrorValue,
    InputManifest,
    ManifestItem,
    PatternChangeSource,
    PlanBounds,
    PlanEdit,
    PlanFile,
    PolicyItem,
    Position,
    Range,
    RepositoryProvenance,
    RuleChangeSource,
    Selection,
    Success,
    SyntaxDiagnostic,
    SyntaxEvidence,
)
from xray.presentation import canonical_bytes, digest, repository_query_digest
from xray.presentation import plan_digest as canonical_plan_digest

_MAX_DIAGNOSTICS = 50
_MAX_DIAGNOSTIC_TEXT_BYTES = 200
_APPLY_RESPONSE_HARD_BYTES = 65_536
_MAX_PLAN_ERROR_BYTES = 512


MUTATION_WORKING_BYTES_LIMIT = 200 * 1024 * 1024
_GIT_STATUS_CODES = frozenset(b" MARDTCU?!")
_GIT_INDEX_HEADER_FIELDS = 3
_GIT_STATUS_PREFIX_BYTES = 3


class ChangeFailure(RuntimeError):
    """Internal typed failure converted to a transport-neutral ``Error``."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: str | None = None,
        kind: str | None = None,
        action: str | None = None,
        details: ErrorDetails | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.kind = kind
        self.action = action
        self.details = details


@dataclass(frozen=True, slots=True)
class FilesystemHooks:
    """Narrow filesystem seam used by apply and deterministic failure tests."""

    read: Callable[[Path], bytes] | None = None
    lstat: Callable[[Path], os.stat_result] | None = None
    stage: Callable[[Path, bytes, int], Path] | None = None
    replace: Callable[[Path, Path], None] | None = None
    remove: Callable[[Path], None] | None = None
    chmod: Callable[[Path, int], None] | None = None


@dataclass(frozen=True, slots=True)
class _CapturedPlanInputs:
    provider: RepositoryProvider
    capture: RepositoryCapture
    rule_set: CapturedRuleSet | None
    candidate_files: tuple[CapturedFile, ...]
    input_manifest: InputManifest
    toolchain: ToolchainObservation


@dataclass(frozen=True, slots=True)
class _Candidate:
    path: str
    start: int
    end: int
    before: bytes
    after: bytes
    before_sha256: str
    after_sha256: str
    edit_id: str


@dataclass(frozen=True, slots=True)
class _PreparedFile:
    plan_file: PlanFile
    preimage: bytes
    postimage: bytes


@dataclass(frozen=True, slots=True)
class _ImageSizing:
    path: str
    captured: CapturedFile
    edits: tuple[_Candidate, ...]
    preimage_bytes: int
    postimage_bytes: int


@dataclass(frozen=True, slots=True)
class _PreparedStage:
    prepared: _PreparedFile
    stage: Path
    edit_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _BaselineObservation:
    kind: Literal["git", "unmanaged"]
    dirty: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _RollbackOutcome:
    state: Literal["all_restored", "known_remaining", "unknown_final"]
    conflicts: tuple[str, ...] = ()


class _DefaultFilesystem:
    @staticmethod
    def read(path: Path) -> bytes:
        return path.read_bytes()

    @staticmethod
    def lstat(path: Path) -> os.stat_result:
        return os.lstat(path)

    @staticmethod
    def stage(path: Path, content: bytes, mode: int) -> Path:
        # Stage beside the target.  ``delete=False`` makes the replacement an
        # ordinary same-directory rename rather than a copy across filesystems.
        fd, raw = tempfile.mkstemp(prefix=f".xray-stage-{path.name}-", dir=path.parent)
        staged = Path(raw)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(staged, stat_module.S_IMODE(mode))
            return staged
        except Exception:
            try:
                staged.unlink()
            except OSError:
                pass
            raise

    @staticmethod
    def replace(source: Path, target: Path) -> None:
        os.replace(source, target)

    @staticmethod
    def remove(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def chmod(path: Path, mode: int) -> None:
        os.chmod(path, stat_module.S_IMODE(mode))


class GuardedChangeService:
    """Plan, refine, verify, and apply one complete guarded change artifact.

    The constructor has no root.  ``change_plan`` obtains its root from the typed
    arguments while refine/verify/apply recover it from the complete plan.  The
    optional hooks are intentionally small: repository capture, bounded executor,
    baseline observation, actual toolchain observation, and target filesystem
    primitives.
    """

    def __init__(
        self,
        *,
        provider_factory: Callable[[Any, Any], RepositoryProvider] = RepositoryProvider,
        executor: BoundedAstGrepExecutor | None = None,
        filesystem: FilesystemHooks | Mapping[str, Callable[..., Any]] | Any | None = None,
        baseline_provider: Callable[[Path, Sequence[str]], Any] | None = None,
        toolchain_provider: ToolchainProvider | Callable[[], ToolchainObservation] | None = None,
    ) -> None:
        self._provider_factory = provider_factory
        self._executor = executor
        self._baseline_provider = baseline_provider
        self._toolchain_provider = toolchain_provider if toolchain_provider is not None else ToolchainProvider()
        self._filesystem = self._coerce_filesystem(filesystem)
        self._root_for_fs = ""

    @staticmethod
    def _coerce_filesystem(value: FilesystemHooks | Mapping[str, Callable[..., Any]] | Any | None) -> Any:
        if value is None:
            return _DefaultFilesystem()
        if isinstance(value, FilesystemHooks):
            defaults = _DefaultFilesystem()
            return FilesystemHooks(
                read=value.read or defaults.read,
                lstat=value.lstat or defaults.lstat,
                stage=value.stage or defaults.stage,
                replace=value.replace or defaults.replace,
                remove=value.remove or defaults.remove,
                chmod=value.chmod or defaults.chmod,
            )
        if isinstance(value, Mapping):
            defaults = _DefaultFilesystem()
            return FilesystemHooks(
                read=cast(Any, value.get("read", defaults.read)),
                lstat=cast(Any, value.get("lstat", defaults.lstat)),
                stage=cast(Any, value.get("stage", defaults.stage)),
                replace=cast(Any, value.get("replace", defaults.replace)),
                remove=cast(Any, value.get("remove", defaults.remove)),
                chmod=cast(Any, value.get("chmod", defaults.chmod)),
            )
        return value

    # ------------------------------------------------------------------
    # Public service seam

    def execute(
        self,
        request: ChangePlanRequest
        | ChangeRefineRequest
        | ChangeVerifyRequest
        | ChangeApplyRequest
        | ChangePlanArguments
        | ChangeRefineArguments
        | ChangeVerifyArguments
        | ChangeApplyArguments,
        *,
        budget: OperationBudget | None = None,
        cancel: object | None = None,
    ) -> Success | Error:
        local_budget = budget
        if local_budget is None:
            execution = getattr(request, "execution", None)
            timeout_seconds = getattr(execution, "timeout_seconds", 30)
            local_budget = OperationBudget(timeout_seconds=timeout_seconds, cancel=cancel)
        elif cancel is not None and local_budget.cancel is None:
            local_budget.cancel = cancel
        operation: Literal["change_plan", "change_refine", "change_verify", "change_apply"] | None = None
        apply = False
        validated_digest: str | None = None
        root: Any | None = None
        try:
            local_budget.check_deadline()
            operation, query, root, apply = self._request_values(request)
            if operation == "change_plan":
                assert isinstance(query, ChangePlanQuery)
                plan = self._make_plan(
                    root,
                    query.source,
                    query.selection,
                    query.bounds,
                    query.acknowledgements,
                    budget=local_budget,
                )
                return Success(
                    schema="xray.v1",
                    ok=True,
                    op="change_plan",
                    data=ChangePlanData(plan=plan),
                    coverage=Coverage(state="complete", basis="change_guards"),
                )
            plan, expected_digest = query  # type: ignore[misc]
            normalized_plan = self._validate_plan(plan)
            calculated = canonical_plan_digest(normalized_plan)
            if calculated != normalized_plan.plan_digest:
                raise ChangeFailure("invalid_plan", "plan digest does not match its complete canonical artifact")
            if operation in {"change_verify", "change_apply"}:
                if expected_digest != normalized_plan.plan_digest:
                    raise ChangeFailure("invalid_plan", "expected_digest does not match the reviewed plan")
                validated_digest = normalized_plan.plan_digest
            if operation == "change_refine":
                refined = self._refine(
                    normalized_plan,
                    cast(list[str], expected_digest),
                    root,
                    budget=local_budget,
                )
                return Success(
                    schema="xray.v1",
                    ok=True,
                    op="change_refine",
                    data=ChangePlanData(plan=refined),
                    coverage=Coverage(state="complete", basis="change_guards"),
                )
            checked, context = self._guard_plan(normalized_plan, root, budget=local_budget)
            if operation == "change_verify":
                return Success(
                    schema="xray.v1",
                    ok=True,
                    op="change_verify",
                    root=checked.root,
                    scope=checked.selection,
                    provenance=checked.provenance,
                    data=ChangeVerifyData(plan_digest=checked.plan_digest, ready=True),
                    coverage=Coverage(state="complete", basis="change_guards"),
                )
            assert operation == "change_apply"
            return self._apply(checked, context, budget=local_budget)
        except ChangeFailure as exc:
            return self._error(
                operation,
                root,
                exc,
                apply=apply,
                plan_digest=validated_digest,
                state="not_applied",
            )
        except RepositoryError as exc:
            failure = ChangeFailure(exc.code, str(exc), path=exc.path, kind=exc.kind)
            return self._error(
                operation,
                root,
                failure,
                apply=apply,
                plan_digest=validated_digest,
                state="not_applied",
            )
        except AstGrepError as exc:
            failure = ChangeFailure(
                getattr(exc, "code", "execution_limit"), str(exc), kind=getattr(exc, "status", None)
            )
            return self._error(
                operation,
                root,
                failure,
                apply=apply,
                plan_digest=validated_digest,
                state="not_applied",
            )
        except Exception as exc:  # application boundary never leaks service errors
            failure = ChangeFailure("internal_error", f"change operation failed: {exc}", action="report_bug")
            return self._error(
                operation,
                root,
                failure,
                apply=apply,
                plan_digest=validated_digest,
                state="not_applied",
            )

    def _request_values(
        self,
        request: Any,
    ) -> tuple[
        Literal["change_plan", "change_refine", "change_verify", "change_apply"],
        Any,
        Any,
        bool,
    ]:
        if isinstance(request, (ChangePlanRequest, ChangePlanArguments)):
            return "change_plan", request.query, request.root, False
        if isinstance(request, (ChangeRefineRequest, ChangeRefineArguments)):
            return "change_refine", (request.query.plan, request.query.edit_ids), request.root, False
        if isinstance(request, (ChangeVerifyRequest, ChangeVerifyArguments)):
            return "change_verify", (request.query.plan, request.query.expected_digest), request.root, False
        if isinstance(request, (ChangeApplyRequest, ChangeApplyArguments)):
            return "change_apply", (request.query.plan, request.query.expected_digest), request.root, True
        raise ChangeFailure(
            "invalid_request", "change service accepts only typed change arguments", action="correct_input"
        )

    # ------------------------------------------------------------------
    # Capture, candidate collection, and complete plan construction

    def _observe_toolchain(self, *, budget: OperationBudget | None = None) -> ToolchainObservation:
        if budget is not None:
            budget.check_deadline()
        try:
            provider = self._toolchain_provider
            observe = getattr(provider, "observe", None)
            if callable(observe):
                raw = observe(budget=budget) if isinstance(provider, ToolchainProvider) else observe()
            else:
                raw = cast(Callable[[], Any], provider)()
        except RepositoryError:
            raise
        except ToolchainUnavailableError as exc:
            raise ChangeFailure("dependency_unavailable", str(exc), kind="toolchain") from exc
        except (AstGrepError, OSError, RuntimeError, ValueError) as exc:
            raise ChangeFailure(
                "dependency_unavailable",
                f"toolchain observation failed: {exc}",
                kind="toolchain",
            ) from exc
        if not isinstance(raw, ToolchainObservation) or not raw.healthy or raw.digest is None:
            details = "; ".join(getattr(raw, "errors", ())) if isinstance(raw, ToolchainObservation) else ""
            message = "required toolchain identity is unavailable"
            if details:
                message += f": {details}"
            raise ChangeFailure("dependency_unavailable", message, kind="toolchain")
        if budget is not None:
            budget.check_deadline()
        return raw

    @staticmethod
    def _toolchain_executor(
        configured: BoundedAstGrepExecutor | None,
        observation: ToolchainObservation,
    ) -> BoundedAstGrepExecutor:
        if configured is not None:
            return configured
        executable = observation.executable
        if executable is None:
            raise ChangeFailure(
                "dependency_unavailable",
                "toolchain executable identity is unavailable",
                kind="toolchain",
            )
        return BoundedAstGrepExecutor(executable=executable)

    @staticmethod
    def _snapshot_digest(captured: _CapturedPlanInputs) -> str:
        return digest(
            [
                "xray.change.snapshot.v1",
                captured.capture.manifest.snapshot_digest,
                [item.to_payload() for item in captured.input_manifest.configuration],
                captured.rule_set.digest if captured.rule_set is not None else None,
            ]
        )

    def _capture_inputs(
        self,
        root_value: Any,
        source: ChangeSource,
        selection: Selection | None,
        *,
        budget: OperationBudget | None = None,
        toolchain: ToolchainObservation | None = None,
    ) -> _CapturedPlanInputs:
        if budget is not None:
            budget.check_deadline()
        observed_toolchain = toolchain if toolchain is not None else self._observe_toolchain(budget=budget)
        provider = self._provider_factory(root_value, selection or Selection())
        capture = provider.capture(
            include_namespace=True,
            budget=budget,
            capture_domain=SUPPORTED_SOURCE_DOMAIN,
        )
        rule_set: CapturedRuleSet | None = None
        if isinstance(source, RuleChangeSource):
            if budget is not None:
                budget.check_deadline()
            rule_set = provider.capture_rule_input(source.input, budget=budget)
        candidate_values = [item for item in capture.files if item.is_text and not item.has_nul]
        if isinstance(source, PatternChangeSource):
            candidate_values = [item for item in candidate_values if item.language == source.language]
        candidates = tuple(sorted(candidate_values, key=lambda item: item.path.encode("utf-8")))
        config: dict[str, CapturedFile] = {item.path: item for item in capture.configuration}
        if rule_set is not None:
            config[rule_set.input_file.path] = rule_set.input_file
            for item in rule_set.rules:
                config[item.path] = item
        toolchain_digest = observed_toolchain.digest
        if toolchain_digest is None:
            raise ChangeFailure("dependency_unavailable", "toolchain identity is unavailable", kind="toolchain")

        input_manifest = InputManifest(
            sources=[ManifestItem(path=item.path, bytes=item.size, sha256=item.digest) for item in capture.files],
            configuration=[
                ManifestItem(path=item.path, bytes=item.size, sha256=item.digest)
                for item in sorted(config.values(), key=lambda item: item.path.encode("utf-8"))
            ],
            policies=[PolicyItem(name=item.name, sha256=item.digest) for item in capture.manifest.policies],
            toolchain=toolchain_digest,
        )
        return _CapturedPlanInputs(provider, capture, rule_set, candidates, input_manifest, observed_toolchain)

    @staticmethod
    def _source_text_inputs(files: Sequence[CapturedFile]) -> dict[str, bytes]:
        return {
            item.path: item.content for item in files if item.is_text and not item.has_nul and item.language is not None
        }

    def _collect_candidates(
        self,
        source: ChangeSource,
        captured: _CapturedPlanInputs,
        bounds: PlanBounds,
        *,
        budget: OperationBudget | None = None,
    ) -> tuple[_Candidate, ...]:
        if budget is not None:
            budget.check_deadline()
        inputs = self._source_text_inputs(captured.candidate_files)
        if not inputs:
            return ()
        if isinstance(source, PatternChangeSource):
            args = [
                "run",
                "--pattern",
                source.pattern,
                "--rewrite",
                source.replacement,
                "--lang",
                source.language,
                "--json=stream",
                "--color",
                "never",
            ]
            rule_set = None
            mode: Literal["search", "render_fixes"] = "search"
        else:
            args = [
                "scan",
                "--config",
                source.input.path,
                "--json=stream",
                "--color",
                "never",
            ]
            rule_set = self._rule_set_for_execution(captured.rule_set)
            mode = "render_fixes"
        result = run_ast_grep_captured(
            args,
            inputs,
            rule_set=rule_set,
            max_results=bounds.max_candidates,
            budget=budget,
            executor=self._toolchain_executor(self._executor, captured.toolchain),
            mode=mode,
        )
        if not isinstance(result, BoundedAstGrepResult):
            raise ChangeFailure(
                "internal_error",
                "ast-grep did not return a complete-file bounded candidate result",
                action="report_bug",
            )
        if not result.total_exact:
            raise ChangeFailure("execution_limit", "candidate universe exceeds max_candidates", kind="candidates")
        records = result.matches
        by_path = {item.path: item for item in captured.candidate_files}
        values: list[_Candidate] = []
        for raw in records:
            if budget is not None:
                budget.check_deadline()
            if not isinstance(raw, Mapping):
                raise ChangeFailure("internal_error", "ast-grep returned a non-object candidate", action="report_bug")
            path = self._result_path(raw.get("file"), by_path)
            captured_file = by_path.get(path)
            if captured_file is None:
                raise ChangeFailure("internal_error", "ast-grep returned a path outside the captured universe")
            start, end = self._record_offsets(raw.get("replacementOffsets") or raw.get("range"), captured_file)
            replacement = raw.get("replacement")
            if not isinstance(replacement, str):
                raise ChangeFailure("invalid_rule", "matched rule has no rendered fix", path=path, kind="fix")
            before = captured_file.content[start:end]
            after = replacement.encode("utf-8")
            before_digest = hashlib.sha256(before).hexdigest()
            after_digest = hashlib.sha256(after).hexdigest()
            edit_id = digest(["xray.edit.v1", path, captured_file.digest, start, end, before_digest, after_digest])
            values.append(_Candidate(path, start, end, before, after, before_digest, after_digest, edit_id))
        if budget is not None:
            budget.check_deadline()
        values.sort(key=lambda item: (item.path.encode("utf-8"), item.start, item.end, item.edit_id.encode("ascii")))
        deduplicated: list[_Candidate] = []
        seen: set[tuple[str, int, int, bytes, bytes]] = set()
        for item in values:
            if budget is not None:
                budget.check_deadline()
            key = (item.path, item.start, item.end, item.before, item.after)
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(item)
        for index, left in enumerate(deduplicated):
            if budget is not None:
                budget.check_deadline()
            for right in deduplicated[index + 1 :]:
                if budget is not None:
                    budget.check_deadline()
                if left.path != right.path:
                    break
                if left.start == right.start and left.end == right.end and left.after != right.after:
                    raise ChangeFailure(
                        "mutation_conflict", "candidate fixes conflict at one source range", path=left.path
                    )
                if left.start < right.end and right.start < left.end:
                    raise ChangeFailure("mutation_conflict", "candidate fixes overlap", path=left.path)
        return tuple(deduplicated)

    @staticmethod
    def _rule_set_for_execution(rule_set: CapturedRuleSet | None) -> CapturedRuleSet:
        if rule_set is None:
            raise ChangeFailure("invalid_rule", "captured rule input is missing")
        if rule_set.input.kind != "rule":
            return rule_set
        # ``run_ast_grep_captured``'s generated config resolves ruleDirs from
        # ast-grep's source cwd.  Prefix standalone files with its generated
        # ``rules`` directory while retaining immutable captured bytes.
        values = object.__new__(CapturedRuleSet)
        object.__setattr__(values, "input", rule_set.input)
        object.__setattr__(values, "input_file", rule_set.input_file)
        object.__setattr__(
            values,
            "rules",
            tuple(
                item.__class__(
                    path=f"rules/{item.path}",
                    content=item.content,
                    digest=item.digest,
                    size=item.size,
                    language=item.language,
                    classification=item.classification,
                    device=item.device,
                    inode=item.inode,
                    mode=item.mode,
                )
                for item in rule_set.rules
            ),
        )
        object.__setattr__(values, "membership", tuple(f"rules/{item}" for item in rule_set.membership))
        object.__setattr__(values, "digest", rule_set.digest)
        return cast(CapturedRuleSet, values)

    @staticmethod
    def _result_path(value: Any, files: Mapping[str, CapturedFile]) -> str:
        if not isinstance(value, str):
            raise ChangeFailure("internal_error", "ast-grep candidate has no file path", action="report_bug")
        path = PurePosixPath(value).as_posix()
        while path.startswith("./"):
            path = path[2:]
        if path in files:
            return path
        if path.startswith("sources/") and path[8:] in files:
            return path[8:]
        raise ChangeFailure("internal_error", "ast-grep candidate path is outside captured source set", path=path)

    @staticmethod
    def _record_offsets(value: Any, captured: CapturedFile) -> tuple[int, int]:
        if not isinstance(value, Mapping):
            raise ChangeFailure("internal_error", "ast-grep candidate has no byte range", action="report_bug")
        byte_offsets: Any = value.get("byteOffset")
        if not isinstance(byte_offsets, Mapping):
            # ``replacementOffsets`` is a flat ``{start,end}`` object while
            # ``range`` wraps the same values in ``byteOffset``.
            byte_offsets = value
        start, end = byte_offsets.get("start"), byte_offsets.get("end")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 0
            or end < start
            or end > len(captured.content)
        ):
            raise ChangeFailure("invalid_reference", "ast-grep candidate range is outside captured bytes")
        try:
            captured.content[:start].decode("utf-8")
            captured.content[start:end].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ChangeFailure("invalid_encoding", "ast-grep candidate range is not UTF-8 aligned") from exc
        return start, end

    def _make_plan(
        self,
        root_value: Any,
        source: ChangeSource,
        selection: Selection | None,
        bounds: PlanBounds | None,
        acknowledgements: Acknowledgements | None,
        *,
        chosen_ids: Sequence[str] | None = None,
        budget: OperationBudget | None = None,
        toolchain: ToolchainObservation | None = None,
    ) -> ChangePlan:
        selected_bounds = bounds or PlanBounds()
        acks = acknowledgements or Acknowledgements()
        if budget is not None:
            budget.check_deadline()
        captured = self._capture_inputs(
            root_value,
            source,
            selection,
            budget=budget,
            toolchain=toolchain,
        )
        candidates = self._collect_candidates(source, captured, selected_bounds, budget=budget)
        if budget is not None:
            budget.check_deadline()
        if len(candidates) > selected_bounds.max_candidates:
            raise ChangeFailure("execution_limit", "candidate universe exceeds max_candidates", kind="candidates")
        all_ids = {item.edit_id for item in candidates}
        if chosen_ids is not None:
            requested = tuple(sorted(set(chosen_ids), key=lambda item: item.encode("ascii")))
            unknown = [item for item in requested if item not in all_ids]
            if unknown:
                raise ChangeFailure(
                    "invalid_plan",
                    "refine requested an unknown edit_id",
                    details=ErrorDetails(conflict_edit_ids=unknown),
                )
            chosen = {item for item in requested}
        else:
            requested = ()
            chosen = all_ids
        selected = tuple(item for item in candidates if item.edit_id in chosen)
        prepared = self._images(
            captured.candidate_files,
            selected,
            selected_bounds,
            budget=budget,
            toolchain=captured.toolchain,
        )
        baseline = self._baseline(
            captured.capture.root.path,
            [item.plan_file.path for item in prepared],
            budget=budget,
        )
        new_errors = sum(item.plan_file.new_diagnostic_count for item in prepared)
        reasons: list[Literal["no_candidates", "no_changes", "dirty_affected", "new_parse_errors"]] = []
        if not candidates:
            reasons.append("no_candidates")
        elif not any(item.before != item.after for item in selected):
            reasons.append("no_changes")
        dirty_affected = bool(getattr(baseline, "dirty_affected", ()))
        if dirty_affected and not acks.dirty_affected:
            reasons.append("dirty_affected")
        if new_errors and not acks.new_parse_errors:
            reasons.append("new_parse_errors")
        eligibility = Eligibility(applicable=not reasons, reasons=reasons)
        chosen_value = ChosenAll(kind="all") if chosen_ids is None else ChosenEdits(kind="edits", ids=list(requested))
        bounds_payload = selected_bounds.to_payload()
        bounds_payload.pop("max_bytes", None)
        toolchain_digest = captured.toolchain.digest
        assert toolchain_digest is not None
        snapshot_digest = self._snapshot_digest(captured)
        query_digest = repository_query_digest(
            "change_plan",
            {
                "source": source.to_payload(),
                "bounds": bounds_payload,
                "acknowledgements": acks.to_payload(),
                "chosen": chosen_value.to_payload(),
            },
            {"kind": "change_plan", "fields": ["files", "edits", "baseline", "eligibility"]},
            captured.capture.manifest.selection_digest,
            snapshot_digest,
            toolchain_digest,
        )
        provenance = RepositoryProvenance(
            kind="repository",
            consistency="captured_read_set",
            query=query_digest,
            selection=captured.capture.manifest.selection_digest,
            snapshot=snapshot_digest,
            toolchain=toolchain_digest,
        )
        plan_values: dict[str, Any] = {
            "plan_schema": "xray.change.v1",
            "root": captured.capture.root,
            "selection": captured.capture.selection,
            "source": source,
            "provenance": provenance,
            "inputs": captured.input_manifest,
            "bounds": selected_bounds,
            "chosen": chosen_value,
            "files": [item.plan_file for item in prepared],
            "edits": [self._edit_model(item) for item in selected],
            "baseline": baseline,
            "acknowledgements": acks,
            "eligibility": eligibility,
            "plan_digest": "0" * 64,
        }
        if budget is not None:
            budget.check_deadline()
        provisional = ChangePlan.model_construct(**plan_values)
        plan_values["plan_digest"] = canonical_plan_digest(provisional)
        try:
            plan = ChangePlan.model_validate(plan_values)
        except Exception as exc:
            raise ChangeFailure("invalid_plan", f"constructed plan is not canonical: {exc}") from exc
        if budget is not None:
            budget.check_deadline()
        if len(canonical_bytes(plan)) > selected_bounds.max_bytes:
            raise ChangeFailure(
                "budget_too_small",
                "complete plan exceeds max_bytes",
                details=ErrorDetails(minimum_bytes=len(canonical_bytes(plan))),
            )
        if budget is not None:
            budget.check_deadline()
        return plan

    @staticmethod
    def _edit_model(item: _Candidate) -> PlanEdit:
        return PlanEdit(
            edit_id=item.edit_id,
            path=item.path,
            start=item.start,
            end=item.end,
            before_sha256=item.before_sha256,
            after_sha256=item.after_sha256,
            changed=item.before != item.after,
        )

    def _images(
        self,
        files: Sequence[CapturedFile],
        candidates: Sequence[_Candidate],
        bounds: PlanBounds,
        *,
        budget: OperationBudget | None = None,
        toolchain: ToolchainObservation | None = None,
    ) -> tuple[_PreparedFile, ...]:
        if budget is not None:
            budget.check_deadline()
        if toolchain is None:
            raise ChangeFailure("dependency_unavailable", "toolchain observation is missing", kind="toolchain")
        by_path = {item.path: item for item in files}
        grouped: dict[str, list[_Candidate]] = {}
        for item in candidates:
            if budget is not None:
                budget.check_deadline()
            grouped.setdefault(item.path, []).append(item)
        ordered_paths = sorted(grouped, key=lambda item: item.encode("utf-8"))
        if len(ordered_paths) > bounds.max_files:
            raise ChangeFailure("execution_limit", "affected files exceed max_files", kind="files")

        sizings: list[_ImageSizing] = []
        total_pre = 0
        total_post = 0
        for path in ordered_paths:
            if budget is not None:
                budget.check_deadline()
            captured = by_path[path]
            edits = tuple(sorted(grouped[path], key=lambda item: (item.start, item.end, item.edit_id.encode("ascii"))))
            preimage_bytes = len(captured.content)
            postimage_bytes = preimage_bytes
            for item in edits:
                if budget is not None:
                    budget.check_deadline()
                postimage_bytes += len(item.after) - (item.end - item.start)
            if preimage_bytes > bounds.max_file_bytes or postimage_bytes > bounds.max_file_bytes:
                raise ChangeFailure(
                    "execution_limit", "source or postimage exceeds max_file_bytes", path=path, kind="file_bytes"
                )
            total_pre += preimage_bytes
            total_post += postimage_bytes
            if total_pre > bounds.max_total_preimage_bytes or total_post > bounds.max_total_postimage_bytes:
                raise ChangeFailure("execution_limit", "plan images exceed aggregate byte bounds", kind="image_bytes")
            sizings.append(_ImageSizing(path, captured, edits, preimage_bytes, postimage_bytes))

        # One retained prepared image pair and one stage/rollback image may
        # coexist.  Reserve the logical worst case before making any complete
        # postimage or touching the target tree.
        working_bytes = 2 * (total_pre + total_post)
        if working_bytes > MUTATION_WORKING_BYTES_LIMIT:
            raise ChangeFailure(
                "execution_limit",
                "mutation working images exceed the 200 MiB bound",
                kind="mutation_working",
            )
        if budget is not None:
            budget.check_deadline()

        prepared: list[_PreparedFile] = []
        for sizing in sizings:
            if budget is not None:
                budget.check_deadline()
            captured = sizing.captured
            post = bytearray(captured.content)
            for item in reversed(sizing.edits):
                if budget is not None:
                    budget.check_deadline()
                if post[item.start : item.end] != item.before:
                    raise ChangeFailure(
                        "mutation_conflict", "candidate preimage does not match captured source", path=sizing.path
                    )
                post[item.start : item.end] = item.after
            post_bytes = bytes(post)
            if len(post_bytes) != sizing.postimage_bytes:
                raise ChangeFailure(
                    "internal_error",
                    "precomputed postimage size does not match rendered bytes",
                    path=sizing.path,
                    action="report_bug",
                )
            try:
                language = captured.language
                if language is None:
                    raise ChangeFailure(
                        "unsupported_file",
                        "captured mutation source has no language",
                        path=sizing.path,
                    )
                analyzer_id = toolchain.analyzer_id(language)
            except ToolchainUnavailableError as exc:
                raise ChangeFailure("dependency_unavailable", str(exc), kind="toolchain") from exc
            syntax_before = self._syntax_evidence(
                captured.language,
                captured.content,
                sizing.path,
                analyzer_id=analyzer_id,
                budget=budget,
            )
            syntax_after = self._syntax_evidence(
                captured.language,
                post_bytes,
                sizing.path,
                analyzer_id=analyzer_id,
                budget=budget,
            )
            new_count = self._new_diagnostic_count(syntax_before, syntax_after)
            diff = self._diff(sizing.path, captured.content, post_bytes, budget=budget)
            mode = captured.mode if captured.mode is not None else 0
            prepared.append(
                _PreparedFile(
                    PlanFile(
                        path=sizing.path,
                        preimage_sha256=captured.digest,
                        postimage_sha256=hashlib.sha256(post_bytes).hexdigest(),
                        preimage_bytes=sizing.preimage_bytes,
                        postimage_bytes=sizing.postimage_bytes,
                        mode=int(mode),
                        syntax_before=syntax_before,
                        syntax_after=syntax_after,
                        new_diagnostic_count=new_count,
                        diff=diff,
                    ),
                    captured.content,
                    post_bytes,
                )
            )
        return tuple(prepared)

    @staticmethod
    def _diff(
        path: str,
        before: bytes,
        after: bytes,
        *,
        budget: OperationBudget | None = None,
    ) -> str:
        try:
            old = before.decode("utf-8").splitlines(keepends=True)
            new = after.decode("utf-8").splitlines(keepends=True)
        except UnicodeDecodeError as exc:
            raise ChangeFailure("invalid_encoding", "plan image is not valid UTF-8", path=path) from exc
        values = difflib.unified_diff(
            old,
            new,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
            lineterm="\n",
        )
        output: list[str] = []
        for line in values:
            if budget is not None:
                budget.check_deadline()
            output.append(line)
            # ``difflib`` intentionally leaves a source line without a final
            # LF unterminated.  Normalize that line to one output row and
            # place the marker immediately after it.  CRLF lines already end
            # in LF and therefore remain byte-for-byte intact.
            if line.startswith(("-", "+", " ")) and not line.endswith("\n"):
                output.append("\n")
                output.append("\\ No newline at end of file\n")
        return "".join(output)

    # ------------------------------------------------------------------
    # Syntax and baseline evidence
    @staticmethod
    def _geometry_positions(data: bytes, offset: int) -> tuple[int, int]:
        line = data.count(b"\n", 0, offset) + 1
        start = data.rfind(b"\n", 0, offset)
        line_start = 0 if start < 0 else start + 1
        return line, offset - line_start + 1

    def _syntax_evidence(
        self,
        language: str | None,
        content: bytes,
        path: str,
        *,
        analyzer_id: str,
        budget: OperationBudget | None = None,
    ) -> SyntaxEvidence:
        if budget is not None:
            budget.check_deadline()
        if language not in {"python", "javascript", "typescript", "go"}:
            raise ChangeFailure("unsupported_file", "syntax evidence requires a supported language", path=path)
        text = content.decode("utf-8")
        diagnostics: list[SyntaxDiagnostic] = []
        analyzer = analyzer_id
        raw: list[tuple[int, int, str]] = []
        if language == "python":
            try:
                ast.parse(text)
            except SyntaxError as exc:
                line = max(1, int(exc.lineno or 1))
                column_char = max(0, int(exc.offset or 1) - 1)
                lines = text.splitlines(keepends=True)
                line_text = lines[line - 1] if line <= len(lines) else ""
                line_start = sum(len(item.encode("utf-8")) for item in lines[: line - 1])
                start = line_start + len(line_text[:column_char].encode("utf-8"))
                end = min(len(content), max(start + 1, line_start + len(line_text.rstrip("\r\n").encode("utf-8"))))
                raw.append((start, end, str(exc.msg or "syntax error")))
        else:
            try:
                root = SgRoot(text, language).root()
                nodes = root.find_all(kind="ERROR")
            except RepositoryError:
                raise
            except Exception:
                # An unavailable grammar is itself a parser failure, represented
                # as one bounded diagnostic rather than an untruthful clean plan.
                raw.append((0, min(len(content), 1), "parser unavailable"))
            else:
                try:
                    for node in nodes:
                        if budget is not None:
                            budget.check_deadline()
                        value = node.range()
                        start_char = int(value.start.index)
                        end_char = int(value.end.index)
                        start = len(text[:start_char].encode("utf-8"))
                        end = len(text[:end_char].encode("utf-8"))
                        raw.append((start, max(start + 1, end), node.text()))
                except RepositoryError:
                    raise
                except Exception as exc:
                    raise ChangeFailure(
                        "analysis_limit",
                        "complete syntax diagnostics could not be established",
                        path=path,
                        action="narrow_query",
                    ) from exc
        ordered = sorted(raw, key=lambda item: (item[0], item[1], item[2].encode("utf-8")))
        if len(ordered) > _MAX_DIAGNOSTICS:
            raise ChangeFailure(
                "analysis_limit",
                "complete syntax diagnostics exceed the bounded diagnostic count",
                path=path,
                action="narrow_query",
            )
        if any(len(value.encode("utf-8")) > _MAX_DIAGNOSTIC_TEXT_BYTES for _, _, value in ordered):
            raise ChangeFailure(
                "analysis_limit",
                "complete syntax diagnostic text exceeds the bounded diagnostic size",
                path=path,
                action="narrow_query",
            )
        for start, end, value in ordered:
            if budget is not None:
                budget.check_deadline()
            text_value = value or "syntax error"
            start_line, start_col = self._geometry_positions(content, min(start, len(content)))
            end_line, end_col = self._geometry_positions(content, min(end, len(content)))
            diagnostic_range = Range(
                start=Position(byte=start, line=start_line, column=start_col),
                end=Position(byte=end, line=end_line, column=end_col),
            )
            signature = digest(["xray.syntax.error.v1", language, text_value])
            diagnostics.append(SyntaxDiagnostic(range=diagnostic_range, signature=signature, text=text_value))
        signatures = [item.signature for item in diagnostics]
        fingerprint = digest(["xray.syntax.fingerprint.v1", language, signatures])
        return SyntaxEvidence(
            analyzer=analyzer,
            language=cast(Any, language),
            diagnostic_count=len(raw),
            fingerprint=fingerprint,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _new_diagnostic_count(before: SyntaxEvidence, after: SyntaxEvidence) -> int:
        old = Counter(item.signature for item in before.diagnostics)
        new = Counter(item.signature for item in after.diagnostics)
        return sum(max(0, count - old[item]) for item, count in new.items())

    def _baseline(
        self,
        root: str,
        affected: Sequence[str],
        *,
        budget: OperationBudget | None = None,
    ) -> BaselineGit | BaselineUnmanaged:
        if budget is not None:
            budget.check_deadline()
        observation = self._observe_baseline(Path(root), affected, budget=budget)
        if observation.kind == "git":
            return BaselineGit(kind="git", dirty_affected=list(observation.dirty))
        return BaselineUnmanaged(kind="unmanaged")

    @staticmethod
    def _git_environment(extra: Mapping[str, str] | None = None) -> dict[str, str]:
        # Keep repository-local configuration available for read-only metadata,
        # while dropping every inherited Git control variable and ambient
        # user/system configuration source.
        path = os.environ.get("PATH", os.defpath)
        if extra is not None and "PATH" in extra:
            path_value = extra["PATH"]
            if "\x00" in path_value:
                raise ValueError("Git child environment values must be NUL-free strings")
            path = path_value
        environment = {
            "PATH": path,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
        if extra:
            for key, value in extra.items():
                if (
                    key.startswith("GIT_")
                    or key in environment
                    or key in {"HOME", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_CONFIG_DIRS"}
                ):
                    continue
                if "\x00" in key or "\x00" in value:
                    raise ValueError("Git child environment values must be NUL-free strings")
                environment[key] = value
        return environment

    @staticmethod
    def _resolve_git_executable() -> str:
        try:
            value = shutil.which("git")
            if value is None:
                raise FileNotFoundError("git executable was not found")
            executable = Path(value).resolve(strict=True)
            if not executable.is_file() or not os.access(executable, os.X_OK):
                raise OSError("git executable is not a regular executable file")
            return executable.as_posix()
        except (OSError, RuntimeError, ValueError) as exc:
            raise ChangeFailure(
                "dependency_unavailable",
                f"managed Git executable is unavailable: {exc}",
                kind="git",
            ) from exc

    @staticmethod
    def _containing_git_marker(root: Path) -> Path | None:
        """Return the nearest ancestor containing a non-symlink ``.git`` marker."""
        current = root
        while True:
            marker = current / ".git"
            try:
                observed = os.lstat(marker)
            except FileNotFoundError:
                observed = None
            except OSError as exc:
                raise ChangeFailure("io_error", "could not inspect managed Git marker", kind="git") from exc
            if observed is not None:
                if stat_module.S_ISLNK(observed.st_mode):
                    raise ChangeFailure(
                        "path_outside_root",
                        "managed Git marker must not be a symlink",
                        kind="symlink",
                    )
                return current
            parent = current.parent
            if parent == current:
                return None
            current = parent

    def _discover_git_worktree(
        self,
        root: Path,
        *,
        executable: str,
        baseline_deadline: float,
        budget: OperationBudget | None,
    ) -> Path:
        """Discover the containing worktree without changing the selected source root."""
        now = time.monotonic()
        operation_remaining = float("inf") if budget is None else budget.remaining_seconds
        remaining = min(baseline_deadline - now, operation_remaining)
        if remaining <= 0:
            raise self._git_child_failure("timeout")
        environment = self._git_environment()
        prefix = self._git_prefix(executable, root)
        try:
            outcome = run_bounded_child(
                [*prefix, "rev-parse", "--show-toplevel"],
                limits=AstGrepLimits(),
                env=environment,
                cwd=root,
                timeout=remaining,
                budget=budget,
                exit_policy=ChildExitPolicy(success_codes=frozenset({0})),
                environment_builder=self._git_environment,
            )
        except AstGrepError as exc:
            raise self._git_child_failure(
                getattr(exc, "status", "io_error"),
                getattr(exc, "stderr", b""),
                returncode=getattr(exc, "returncode", None),
            ) from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise ChangeFailure("io_error", f"could not discover managed Git worktree: {exc}", kind="git") from exc
        if not isinstance(outcome, ChildOutcome):
            raise ChangeFailure("io_error", "Git discovery returned an invalid outcome", kind="git")
        if (
            outcome.status != "complete"
            or outcome.returncode != 0
            or not outcome.reaped
            or not isinstance(outcome.stdout, bytes)
            or not isinstance(outcome.stderr, bytes)
            or outcome.error is not None
        ):
            raise self._git_child_failure(
                outcome.status,
                outcome.stderr if isinstance(outcome.stderr, bytes) else b"",
                returncode=outcome.returncode,
            )
        if outcome.stderr:
            raise self._git_child_failure("io_error", outcome.stderr, returncode=outcome.returncode)
        if time.monotonic() >= baseline_deadline:
            raise self._git_child_failure("timeout")
        raw = outcome.stdout
        if not raw or not raw.endswith(b"\n") or raw.count(b"\n") != 1:
            raise ChangeFailure("io_error", "Git worktree discovery output was malformed", kind="git")
        value = raw[:-1]
        if not value or b"\r" in value or b"\0" in value:
            raise ChangeFailure("io_error", "Git worktree discovery path was malformed", kind="git")
        try:
            discovered = Path(value.decode("utf-8", errors="strict")).resolve(strict=True)
        except (OSError, RuntimeError, UnicodeDecodeError, ValueError) as exc:
            raise ChangeFailure("io_error", "Git worktree discovery path was invalid", kind="git") from exc
        if not discovered.is_dir():
            raise ChangeFailure("io_error", "Git worktree discovery did not return a directory", kind="git")
        try:
            root.relative_to(discovered)
        except ValueError as exc:
            raise ChangeFailure(
                "path_outside_root",
                "Git worktree discovery did not contain the selected source root",
                kind="git",
            ) from exc
        return discovered

    @staticmethod
    def _git_prefix(executable: str, root: Path) -> list[str]:
        return [
            executable,
            "--no-pager",
            "--no-optional-locks",
            "-C",
            root.as_posix(),
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.untrackedCache=false",
            "-c",
            "submodule.recurse=false",
        ]

    @staticmethod
    def _git_nul_records(stdout: bytes, *, label: str, kind: str) -> Iterator[bytes]:
        if not isinstance(stdout, bytes):
            raise ChangeFailure("io_error", f"{label} output was not binary", kind=kind)
        if not stdout:
            return
        if not stdout.endswith(b"\0"):
            raise ChangeFailure("io_error", f"{label} output was not NUL terminated", kind=kind)
        start = 0
        while start < len(stdout):
            end = stdout.find(b"\0", start)
            if end < 0:
                raise ChangeFailure("io_error", f"{label} output was not NUL terminated", kind=kind)
            if end == start:
                raise ChangeFailure("io_error", f"{label} output contained an empty record", kind=kind)
            yield stdout[start:end]
            start = end + 1

    @staticmethod
    def _parse_git_configuration(stdout: bytes) -> None:
        for record in GuardedChangeService._git_nul_records(stdout, label="Git configuration", kind="git_config"):
            key_bytes, separator, value = record.partition(b"\n")
            if not key_bytes:
                raise ChangeFailure("io_error", "Git configuration output contained an empty key", kind="git_config")
            try:
                key = key_bytes.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise ChangeFailure("io_error", "Git configuration key was not UTF-8", kind="git_config") from exc
            if separator and b"\0" in value:
                raise ChangeFailure("io_error", "Git configuration value contained a NUL", kind="git_config")
            section, dot, variable = key.lower().rpartition(".")
            if not dot or not section.startswith("filter.") or not section[7:] or variable not in {"clean", "process"}:
                continue
            if not separator or value:
                raise ChangeFailure(
                    "io_error",
                    "managed Git repository configures an executable clean/process filter",
                    kind="git_config",
                )

    @staticmethod
    def _parse_git_index(stdout: bytes) -> None:
        normal_modes = {b"100644", b"100755", b"120000"}
        for record in GuardedChangeService._git_nul_records(stdout, label="Git index", kind="git_index"):
            separator = record.find(b"\t")
            if separator <= 0:
                raise ChangeFailure("io_error", "Git index record had no path delimiter", kind="git_index")
            header = record[:separator]
            path_bytes = record[separator + 1 :]
            fields = header.split(b" ")
            if len(fields) != _GIT_INDEX_HEADER_FIELDS or any(not field for field in fields):
                raise ChangeFailure("io_error", "Git index record header was malformed", kind="git_index")
            mode, object_id, stage = fields
            if mode == b"160000":
                raise ChangeFailure("io_error", "managed Git index contains a gitlink", kind="git_index")
            if mode == b"040000":
                raise ChangeFailure("io_error", "managed Git index contains a sparse directory", kind="git_index")
            if mode not in normal_modes:
                raise ChangeFailure("io_error", "managed Git index contains an unsupported mode", kind="git_index")
            if stage not in {b"0", b"1", b"2", b"3"}:
                raise ChangeFailure("io_error", "Git index record stage was malformed", kind="git_index")
            if len(object_id) not in {40, 64} or any(value not in b"0123456789abcdef" for value in object_id):
                raise ChangeFailure("io_error", "Git index object id was malformed", kind="git_index")
            try:
                path = path_bytes.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise ChangeFailure("io_error", "Git index path was not valid UTF-8", kind="git_index") from exc
            if (
                not path
                or path.startswith("/")
                or "\\" in path
                or any(part in {"", ".", ".."} for part in path.split("/"))
                or PurePosixPath(path).as_posix() != path
            ):
                raise ChangeFailure("io_error", "Git index path was not canonical", path=path, kind="git_index")

    def _git_child(
        self,
        command: Sequence[str],
        *,
        root: Path,
        environment: Mapping[str, str],
        baseline_deadline: float,
        budget: OperationBudget | None,
    ) -> bytes:
        now = time.monotonic()
        operation_remaining = float("inf") if budget is None else budget.remaining_seconds
        remaining = min(baseline_deadline - now, operation_remaining)
        if remaining <= 0:
            raise self._git_child_failure("timeout")
        try:
            outcome = run_bounded_child(
                list(command),
                limits=AstGrepLimits(),
                env=environment,
                cwd=root,
                timeout=remaining,
                budget=budget,
                exit_policy=STRICT_CHILD_EXIT_POLICY,
                environment_builder=self._git_environment,
            )
        except AstGrepError as exc:
            raise self._git_child_failure(
                getattr(exc, "status", "io_error"),
                getattr(exc, "stderr", b""),
                returncode=getattr(exc, "returncode", None),
            ) from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise ChangeFailure("io_error", f"could not obtain managed Git baseline: {exc}", kind="git") from exc
        if not isinstance(outcome, ChildOutcome):
            raise ChangeFailure("io_error", "Git child returned an invalid outcome", kind="git")
        if (
            outcome.status != "complete"
            or outcome.returncode != 0
            or not outcome.reaped
            or not isinstance(outcome.stdout, bytes)
            or not isinstance(outcome.stderr, bytes)
            or outcome.error is not None
        ):
            raise self._git_child_failure(
                outcome.status,
                outcome.stderr if isinstance(outcome.stderr, bytes) else b"",
                returncode=outcome.returncode,
            )
        if outcome.stderr:
            raise self._git_child_failure("io_error", outcome.stderr, returncode=outcome.returncode)
        if time.monotonic() >= baseline_deadline:
            raise self._git_child_failure("timeout")
        return outcome.stdout

    @staticmethod
    def _parse_git_status(stdout: bytes) -> tuple[str, ...]:
        if not isinstance(stdout, bytes):
            raise ChangeFailure("io_error", "Git baseline output was not binary", kind="git_status")
        if not stdout:
            return ()
        if not stdout.endswith(b"\0"):
            raise ChangeFailure("io_error", "Git baseline output was not NUL terminated", kind="git_status")
        records = stdout[:-1].split(b"\0")
        if not records or any(not record for record in records):
            raise ChangeFailure("io_error", "Git baseline output contained an empty record", kind="git_status")
        paths: set[str] = set()
        for record in records:
            if (
                len(record) <= _GIT_STATUS_PREFIX_BYTES
                or record[2:3] != b" "
                or record[0] not in _GIT_STATUS_CODES
                or record[1] not in _GIT_STATUS_CODES
            ):
                raise ChangeFailure("io_error", "Git baseline output was malformed porcelain-v1", kind="git_status")
            # ``--no-renames`` makes every record carry exactly one path.  A
            # rename/copy status here means the command contract was not held.
            if record[0] in b"RC" or record[1] in b"RC":
                raise ChangeFailure("io_error", "Git baseline unexpectedly emitted a rename", kind="git_status")
            try:
                path = record[_GIT_STATUS_PREFIX_BYTES:].decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise ChangeFailure("io_error", "Git baseline path was not valid UTF-8", kind="git_status") from exc
            if (
                not path
                or path.startswith("/")
                or "\\" in path
                or any(part in {"", ".", ".."} for part in path.split("/"))
                or PurePosixPath(path).as_posix() != path
            ):
                raise ChangeFailure("io_error", "Git baseline path was not canonical", path=path, kind="git_status")
            paths.add(path)
        return tuple(sorted(paths, key=lambda item: item.encode("utf-8")))

    @staticmethod
    def _git_child_failure(status: str, stderr: bytes = b"", *, returncode: int | None = None) -> ChangeFailure:
        if status == "timeout":
            code = "timeout"
        elif status in {"cancelled", "stdout_overflow", "stderr_overflow", "output_overflow", "huge_line"}:
            code = "execution_limit"
        else:
            code = "io_error"
        detail = ""
        if stderr:
            detail = stderr[: AstGrepLimits().stderr_bytes].decode("utf-8", errors="replace").strip()
            if detail:
                detail = f": {detail}"
        suffix = f" (exit {returncode})" if status == "nonzero_exit" and returncode is not None else ""
        return ChangeFailure(code, f"could not obtain managed Git baseline{suffix}{detail}", kind="git")

    def _observe_baseline(
        self,
        root: Path,
        affected: Sequence[str],
        *,
        budget: OperationBudget | None = None,
    ) -> _BaselineObservation:
        if budget is not None:
            budget.check_deadline()
        if self._baseline_provider is not None:
            raw = self._baseline_provider(root, affected)
            if budget is not None:
                budget.check_deadline()
            if isinstance(raw, BaselineGit):
                return _BaselineObservation("git", tuple(raw.dirty_affected))
            if isinstance(raw, BaselineUnmanaged):
                return _BaselineObservation("unmanaged", ())
            if isinstance(raw, _BaselineObservation):
                return raw
            if isinstance(raw, Mapping):
                raw_kind = raw.get("kind")
                if raw_kind not in {"git", "unmanaged"}:
                    raise ChangeFailure("io_error", "baseline provider returned an unknown kind", kind="git")
                if raw_kind == "unmanaged":
                    return _BaselineObservation("unmanaged", ())
                raw_dirty = raw.get("dirty", raw.get("dirty_affected", ()))
                if not isinstance(raw_dirty, Sequence) or isinstance(raw_dirty, (str, bytes, bytearray)):
                    raise ChangeFailure("io_error", "baseline provider returned malformed dirty paths", kind="git")
                if any(not isinstance(item, str) for item in raw_dirty):
                    raise ChangeFailure("io_error", "baseline provider returned malformed dirty paths", kind="git")
                dirty = tuple(sorted(set(raw_dirty), key=lambda item: item.encode("utf-8")))
                return _BaselineObservation("git", dirty)
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
                if any(not isinstance(item, str) for item in raw):
                    raise ChangeFailure("io_error", "baseline provider returned malformed dirty paths", kind="git")
                dirty = tuple(sorted(set(raw), key=lambda item: item.encode("utf-8")))
                return _BaselineObservation("git", dirty)
            raise ChangeFailure("io_error", "baseline provider returned no baseline", kind="git")

        marker_root = self._containing_git_marker(root)
        if marker_root is None:
            return _BaselineObservation("unmanaged", ())
        baseline_deadline = time.monotonic() + 5.0
        executable = self._resolve_git_executable()
        if marker_root == root:
            worktree_root = root
        else:
            worktree_root = self._discover_git_worktree(
                root,
                executable=executable,
                baseline_deadline=baseline_deadline,
                budget=budget,
            )
        prefix = self._git_prefix(executable, worktree_root)
        environment = self._git_environment()

        configuration = self._git_child(
            [*prefix, "config", "--null", "--list", "--includes"],
            root=worktree_root,
            environment=environment,
            baseline_deadline=baseline_deadline,
            budget=budget,
        )
        self._parse_git_configuration(configuration)

        index = self._git_child(
            [*prefix, "ls-files", "--stage", "--sparse", "-z"],
            root=worktree_root,
            environment=environment,
            baseline_deadline=baseline_deadline,
            budget=budget,
        )
        self._parse_git_index(index)

        status = self._git_child(
            [
                *prefix,
                "status",
                "--porcelain=v1",
                "-z",
                "--no-renames",
                "--untracked-files=all",
                "--ignore-submodules=all",
            ],
            root=worktree_root,
            environment=environment,
            baseline_deadline=baseline_deadline,
            budget=budget,
        )
        paths = self._parse_git_status(status)
        try:
            source_prefix = root.relative_to(worktree_root).as_posix()
        except ValueError as exc:
            raise ChangeFailure(
                "path_outside_root",
                "managed Git worktree does not contain the selected source root",
                kind="git",
            ) from exc
        affected_set = set(affected)
        dirty_values: set[str] = set()
        for path in paths:
            relative = path
            if source_prefix != ".":
                prefix_text = f"{source_prefix}/"
                if not path.startswith(prefix_text):
                    continue
                relative = path[len(prefix_text) :]
            if relative in affected_set:
                dirty_values.add(relative)
        dirty = tuple(sorted(dirty_values, key=lambda item: item.encode("utf-8")))
        return _BaselineObservation("git", dirty)

    # ------------------------------------------------------------------
    # Plan validation, refine, verify, and apply

    @staticmethod
    def _validate_plan(plan: Any) -> ChangePlan:
        if not isinstance(plan, ChangePlan):
            raise ChangeFailure("invalid_plan", "change operation requires a typed complete plan")
        try:
            value = ChangePlan.model_validate(plan.to_payload())
        except Exception as exc:
            raise ChangeFailure("invalid_plan", f"plan schema validation failed: {exc}") from exc
        if value.plan_schema != "xray.change.v1":
            raise ChangeFailure("invalid_plan", "unsupported change plan schema")
        if canonical_plan_digest(value) != value.plan_digest:
            raise ChangeFailure("invalid_plan", "plan digest does not match the complete canonical plan")
        return value

    def _refine(
        self,
        plan: ChangePlan,
        edit_ids: Sequence[str],
        root_value: Any,
        *,
        budget: OperationBudget | None = None,
    ) -> ChangePlan:
        if budget is not None:
            budget.check_deadline()
        root = normalize_root(plan.root.path)
        if root.id != plan.root.id or (root_value is not None and normalize_root(root_value).id != root.id):
            raise ChangeFailure("plan_drift", "refine root does not match the complete plan")
        refined = self._make_plan(
            root,
            plan.source,
            plan.selection,
            plan.bounds,
            plan.acknowledgements,
            chosen_ids=edit_ids,
            budget=budget,
        )
        # Re-evaluation must preserve the original candidate universe, not rescue
        # a plan that was already over bounds or had unknown identity.
        if plan.chosen.kind == "all" and len(plan.edits) > plan.bounds.max_candidates:
            raise ChangeFailure("execution_limit", "cannot refine an oversized plan")
        return refined

    def _guard_plan(
        self,
        plan: ChangePlan,
        root_value: Any,
        *,
        budget: OperationBudget | None = None,
    ) -> tuple[ChangePlan, _CapturedPlanInputs]:
        if budget is not None:
            budget.check_deadline()
        try:
            root = normalize_root(plan.root.path)
        except RepositoryError as exc:
            raise ChangeFailure(exc.code, str(exc), path=exc.path, kind=exc.kind) from exc
        if root.id != plan.root.id:
            raise ChangeFailure("plan_drift", "plan root identity changed")
        if root_value is not None and normalize_root(root_value).id != root.id:
            raise ChangeFailure("plan_drift", "request root does not match plan root")
        toolchain = self._observe_toolchain(budget=budget)
        captured = self._capture_inputs(
            root,
            plan.source,
            plan.selection,
            budget=budget,
            toolchain=toolchain,
        )
        if captured.capture.selection != plan.selection:
            raise ChangeFailure("plan_drift", "selection changed since planning")
        if captured.input_manifest != plan.inputs:
            raise ChangeFailure("plan_drift", "captured source, configuration, policy, or toolchain manifest changed")
        if captured.input_manifest.toolchain != toolchain.digest:
            raise ChangeFailure("plan_drift", "toolchain identity changed")
        if budget is not None:
            budget.check_deadline()
        fresh = self._make_plan(
            root,
            plan.source,
            plan.selection,
            plan.bounds,
            plan.acknowledgements,
            chosen_ids=None if plan.chosen.kind == "all" else plan.chosen.ids,
            budget=budget,
            toolchain=toolchain,
        )
        if fresh.to_payload() != plan.to_payload():
            raise ChangeFailure(
                "plan_drift", "candidate membership, syntax, ranges, modes, or complete plan fields changed"
            )
        if not plan.eligibility.applicable:
            raise ChangeFailure("plan_inapplicable", "reviewed plan is not applicable")
        return plan, captured

    def _apply(
        self,
        plan: ChangePlan,
        captured: _CapturedPlanInputs,
        *,
        budget: OperationBudget | None = None,
    ) -> Success | Error:
        self._root_for_fs = captured.provider.root.path
        applied = Success(
            schema="xray.v1",
            ok=True,
            op="change_apply",
            root=plan.root,
            scope=plan.selection,
            provenance=plan.provenance,
            data=ChangeApplyData(plan_digest=plan.plan_digest, state="applied", rollback_status="not_attempted"),
            coverage=Coverage(state="complete", basis="change_guards"),
        )
        minimum_bytes = len(canonical_bytes(applied)) + 1
        if minimum_bytes > _APPLY_RESPONSE_HARD_BYTES:
            return self._error(
                "change_apply",
                plan.root,
                ChangeFailure(
                    "budget_too_small",
                    "change_apply result exceeds the hard response byte ceiling",
                    action="narrow_query",
                    details=ErrorDetails(minimum_bytes=minimum_bytes),
                ),
                apply=True,
                plan_digest=plan.plan_digest,
                state="not_applied",
            )
        stages: list[_PreparedStage] = []
        replaced: list[_PreparedStage] = []
        try:
            if budget is not None:
                budget.check_deadline()
            prepared = self._prepared_from_plan(plan, captured, budget=budget)
            # All postimages and stages are prepared before the first target write.
            for item in prepared:
                if budget is not None:
                    budget.check_deadline()
                if item.preimage == item.postimage:
                    continue
                target = self._target(captured.provider, item.plan_file.path)
                self._ensure_exclusive(target, item.plan_file.path)
                if budget is not None:
                    budget.check_deadline()
                stage = self._fs_call("stage", target, item.postimage, item.plan_file.mode)
                stage = Path(stage)
                edit_ids = tuple(
                    sorted(
                        {edit.edit_id for edit in plan.edits if edit.path == item.plan_file.path},
                        key=lambda value: value.encode("ascii"),
                    )
                )
                stages.append(_PreparedStage(item, stage, edit_ids))
                if budget is not None:
                    budget.check_deadline()
                observed = self._fs_call("read", stage)
                if observed != item.postimage:
                    raise ChangeFailure(
                        "apply_failed", "staged bytes do not match planned postimage", path=item.plan_file.path
                    )
                staged_stat = self._fs_call("lstat", stage)
                if budget is not None:
                    budget.check_deadline()
                if stat_module.S_IMODE(staged_stat.st_mode) != stat_module.S_IMODE(item.plan_file.mode):
                    raise ChangeFailure(
                        "apply_failed", "staged mode does not match planned mode", path=item.plan_file.path
                    )
            for staged in stages:
                if budget is not None:
                    budget.check_deadline()
                target = self._target(captured.provider, staged.prepared.plan_file.path)
                self._ensure_exclusive(target, staged.prepared.plan_file.path)
                if budget is not None:
                    budget.check_deadline()
                current = self._fs_call("read", target)
                if current != staged.prepared.preimage:
                    raise ChangeFailure(
                        "plan_drift",
                        "affected source changed immediately before replacement",
                        path=staged.prepared.plan_file.path,
                    )
                if budget is not None:
                    budget.check_deadline()
                current_stat = self._fs_call("lstat", target)
                if stat_module.S_IMODE(current_stat.st_mode) != stat_module.S_IMODE(staged.prepared.plan_file.mode):
                    raise ChangeFailure(
                        "plan_drift",
                        "affected source mode changed immediately before replacement",
                        path=staged.prepared.plan_file.path,
                    )
                if budget is not None:
                    budget.check_deadline()
                # Record the attempted target before invoking the rename.  A
                # filesystem hook may mutate the target and then raise.
                replaced.append(staged)
                self._fs_call("replace", staged.stage, target)
                if budget is not None:
                    budget.check_deadline()
                after = self._fs_call("read", target)
                if after != staged.prepared.postimage:
                    raise ChangeFailure(
                        "apply_failed", "postimage verification failed", path=staged.prepared.plan_file.path
                    )
                if budget is not None:
                    budget.check_deadline()
                after_stat = self._fs_call("lstat", target)
                if stat_module.S_IMODE(after_stat.st_mode) != stat_module.S_IMODE(staged.prepared.plan_file.mode):
                    raise ChangeFailure(
                        "apply_failed", "postimage mode verification failed", path=staged.prepared.plan_file.path
                    )
                self._verify_syntax_after(
                    staged.prepared.plan_file,
                    after,
                    toolchain=captured.toolchain,
                    budget=budget,
                )
            for staged in stages:
                if staged not in replaced:
                    self._remove_stage(staged.stage)
            return applied
        except Exception as exc:
            for staged in stages:
                if staged not in replaced:
                    self._remove_stage(staged.stage)
            if not replaced:
                failure = exc if isinstance(exc, ChangeFailure) else ChangeFailure("apply_failed", str(exc))
                return self._error(
                    "change_apply", plan.root, failure, apply=True, plan_digest=plan.plan_digest, state="not_applied"
                )
            rollback = self._rollback(replaced)
            if rollback.state == "all_restored":
                state: Literal["rolled_back", "partially_applied", "indeterminate"] = "rolled_back"
                rollback_status: Literal["succeeded", "failed"] = "succeeded"
            elif rollback.state == "known_remaining":
                state = "partially_applied"
                rollback_status = "failed"
            else:
                state = "indeterminate"
                rollback_status = "failed"
            failure = exc if isinstance(exc, ChangeFailure) else ChangeFailure("apply_failed", str(exc))
            if rollback.conflicts:
                visible_conflicts = list(rollback.conflicts[:8])
                additional = len(rollback.conflicts) - len(visible_conflicts)
                detail_values: dict[str, Any] = {"conflict_edit_ids": visible_conflicts}
                if additional:
                    detail_values["additional_conflicts"] = additional
                failure = ChangeFailure(
                    "mutation_conflict",
                    "rollback preserved an independently modified third value",
                    details=ErrorDetails(**detail_values),
                )
            return self._error(
                "change_apply",
                plan.root,
                failure,
                apply=True,
                plan_digest=plan.plan_digest,
                state=state,
                rollback_status=rollback_status,
            )
        finally:
            for staged in stages:
                self._remove_stage(staged.stage)

    def _prepared_from_plan(
        self,
        plan: ChangePlan,
        captured: _CapturedPlanInputs,
        *,
        budget: OperationBudget | None = None,
    ) -> tuple[_PreparedFile, ...]:
        if budget is not None:
            budget.check_deadline()
        candidates = self._collect_candidates(plan.source, captured, plan.bounds, budget=budget)
        chosen_ids = None if plan.chosen.kind == "all" else set(plan.chosen.ids)
        selected = tuple(item for item in candidates if chosen_ids is None or item.edit_id in chosen_ids)
        prepared = self._images(
            captured.candidate_files,
            selected,
            plan.bounds,
            budget=budget,
            toolchain=captured.toolchain,
        )
        if budget is not None:
            budget.check_deadline()
        if [item.plan_file.to_payload() for item in prepared] != [item.to_payload() for item in plan.files]:
            raise ChangeFailure("invalid_plan", "planned file images do not match rendered bytes")
        edit_values = [self._edit_model(item).to_payload() for item in selected]
        if budget is not None:
            budget.check_deadline()
        if edit_values != [item.to_payload() for item in plan.edits]:
            raise ChangeFailure("invalid_plan", "planned edit ranges do not match rendered candidates")
        return prepared

    def _verify_syntax_after(
        self,
        plan_file: PlanFile,
        content: bytes,
        *,
        toolchain: ToolchainObservation,
        budget: OperationBudget | None = None,
    ) -> None:
        if budget is not None:
            budget.check_deadline()
        try:
            analyzer_id = toolchain.analyzer_id(plan_file.syntax_after.language)
        except ToolchainUnavailableError as exc:
            raise ChangeFailure("dependency_unavailable", str(exc), kind="toolchain") from exc
        evidence = self._syntax_evidence(
            plan_file.syntax_after.language,
            content,
            plan_file.path,
            analyzer_id=analyzer_id,
            budget=budget,
        )
        if (
            evidence.fingerprint != plan_file.syntax_after.fingerprint
            or evidence.diagnostic_count != plan_file.syntax_after.diagnostic_count
        ):
            raise ChangeFailure("apply_failed", "final syntax verification failed", path=plan_file.path)

    def _rollback(self, replaced: Sequence[_PreparedStage]) -> _RollbackOutcome:
        conflicts: set[str] = set()
        unknown = False
        known_remaining = False
        for staged in reversed(replaced):
            path_outcome = self._rollback_path(staged)
            conflicts.update(path_outcome.conflicts)
            if path_outcome.state == "unknown_final":
                unknown = True
            elif path_outcome.state == "known_remaining":
                known_remaining = True
        if unknown:
            outcome = "unknown_final"
        elif known_remaining:
            outcome = "known_remaining"
        else:
            outcome = "all_restored"
        return _RollbackOutcome(
            outcome,
            tuple(sorted(conflicts, key=lambda item: item.encode("ascii"))),
        )

    def _rollback_path(self, staged: _PreparedStage) -> _RollbackOutcome:
        prepared = staged.prepared
        target = self._target_path(prepared.plan_file.path)
        expected_mode = stat_module.S_IMODE(prepared.plan_file.mode)
        conflict_ids = staged.edit_ids
        initial = self._final_observation(target)
        if initial is None:
            return _RollbackOutcome("unknown_final")
        current, mode = initial
        if current == prepared.preimage and mode == expected_mode:
            return _RollbackOutcome("all_restored")
        if current != prepared.postimage or mode != expected_mode:
            return _RollbackOutcome("known_remaining", conflict_ids)

        rollback_stage: Path | None = None
        try:
            rollback_stage = Path(self._fs_call("stage", target, prepared.preimage, prepared.plan_file.mode))
            self._fs_call("replace", rollback_stage, target)
        except Exception:
            # The final observation below, rather than the thrown exception,
            # determines whether this path is restored, known remaining, or
            # impossible to classify.
            pass
        finally:
            if rollback_stage is not None:
                self._remove_stage(rollback_stage)

        final = self._final_observation(target)
        if final is None:
            return _RollbackOutcome("unknown_final")
        restored, restored_mode = final
        if restored == prepared.preimage and restored_mode == expected_mode:
            return _RollbackOutcome("all_restored")
        if restored == prepared.postimage and restored_mode == expected_mode:
            return _RollbackOutcome("known_remaining")
        return _RollbackOutcome("known_remaining", conflict_ids)

    def _final_observation(self, target: Path) -> tuple[bytes, int] | None:
        try:
            content = self._fs_call("read", target)
            observed = self._fs_call("lstat", target)
            if not isinstance(content, bytes):
                return None
            return content, stat_module.S_IMODE(observed.st_mode)
        except Exception:
            return None

    def _target_path(self, path: str) -> Path:
        return Path(self._root_for_fs) / path

    def _target(self, provider: RepositoryProvider, path: str) -> Path:
        try:
            target = provider.resolve_path(path, require_file=True)
        except RepositoryError as exc:
            raise ChangeFailure(exc.code, str(exc), path=exc.path, kind=exc.kind) from exc
        self._root_for_fs = provider.root.path
        return target

    def _ensure_exclusive(self, path: Path, relative: str) -> None:
        try:
            observed = self._fs_call("lstat", path)
        except OSError as exc:
            raise ChangeFailure("io_error", "could not stat mutation target", path=relative) from exc
        if stat_module.S_ISLNK(observed.st_mode) or not stat_module.S_ISREG(observed.st_mode):
            raise ChangeFailure("path_outside_root", "mutation target is not a regular file", path=relative)
        if getattr(observed, "st_nlink", 1) != 1:
            raise ChangeFailure(
                "mutation_conflict", "hard-linked mutation target is not exclusive", path=relative, kind="hardlink"
            )

    def _fs_call(self, method: str, *args: Any) -> Any:
        value = getattr(self._filesystem, method)
        return value(*args)

    def _remove_stage(self, path: Path) -> None:
        try:
            self._fs_call("remove", path)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Typed error values

    def _error(
        self,
        operation: str | None,
        root_value: Any,
        failure: ChangeFailure,
        *,
        apply: bool,
        plan_digest: str | None,
        state: Literal["not_applied", "rolled_back", "partially_applied", "indeterminate"],
        rollback_status: Literal["not_attempted", "succeeded", "failed"] = "not_attempted",
    ) -> Error:
        code = (
            failure.code
            if failure.code
            in {
                "invalid_request",
                "unknown_operation",
                "path_outside_root",
                "not_found",
                "excluded_input",
                "unsupported_file",
                "unsupported_configuration",
                "invalid_pattern",
                "invalid_rule",
                "invalid_encoding",
                "invalid_reference",
                "stale_reference",
                "invalid_cursor",
                "cursor_query_mismatch",
                "stale_cursor",
                "source_changed",
                "dependency_unavailable",
                "io_error",
                "timeout",
                "execution_limit",
                "analysis_limit",
                "budget_too_small",
                "invalid_plan",
                "plan_drift",
                "plan_inapplicable",
                "mutation_conflict",
                "apply_failed",
                "internal_error",
            }
            else "internal_error"
        )
        message = (
            str(failure).encode("utf-8")[:_MAX_PLAN_ERROR_BYTES].decode("utf-8", errors="ignore")
            or "change operation failed"
        )
        details = failure.details
        if details is None and (failure.kind or failure.path):
            detail_values: dict[str, Any] = {}
            if failure.kind:
                detail_values["kind"] = failure.kind
            if failure.path not in {None, "."}:
                detail_values["path"] = failure.path
            details = ErrorDetails(**detail_values) if detail_values else None
        error_values: dict[str, Any] = {"code": cast(Any, code), "message": message}
        if failure.action:
            error_values["action"] = cast(Any, failure.action)
        if details is not None:
            error_values["details"] = details
        error = ErrorValue(**error_values)
        values: dict[str, Any] = {"schema": "xray.v1", "ok": False, "error": error}
        if operation is not None:
            values["op"] = operation
        if root_value is not None:
            try:
                values["root"] = normalize_root(root_value)
            except Exception:
                if hasattr(root_value, "path"):
                    values["root"] = root_value
        if apply:
            values["mutation"] = {
                "state": state,
                "rollback_status": rollback_status,
                **({"plan_digest": plan_digest} if plan_digest is not None and state != "not_applied" else {}),
            }
        return Error(**values)


__all__ = ["ChangeFailure", "FilesystemHooks", "GuardedChangeService"]
