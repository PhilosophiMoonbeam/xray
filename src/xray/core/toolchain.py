"""Actual output-affecting analyzer and toolchain identity observations.

The provider intentionally returns an unhealthy observation instead of inventing a
placeholder digest when a required executable or parser artifact is unavailable.
Callers should observe once per operation and pass the immutable result through
provenance, cache, cursor, and capability construction.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import re
import sys
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any, Literal, cast

from xray.core.ast_grep import (
    STRICT_CHILD_EXIT_POLICY,
    AstGrepError,
    AstGrepLimits,
    ChildOutcome,
    resolve_ast_grep_executable,
    run_bounded_child,
)
from xray.core.repository import OperationBudget
from xray.models import LANGUAGE_ORDER, GrammarManifest, ToolchainComponent, ToolchainManifest

TOOLCHAIN_SCHEMA = "xray.toolchain.v1"
ANALYZER_SCHEMA = "xray.analyzer.v1"
_SUPPORTED_LANGUAGES = ("python", "javascript", "typescript", "go")
_VERSION_RE = re.compile(r"(?:^|\s)ast-grep\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)\s*$")
_VERSION_PART_RE = re.compile(r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:[.+-][0-9A-Za-z.-]+)?$")
_ARTIFACT_CHUNK_BYTES = 64 * 1024

DependencyState = Literal["available", "missing", "incompatible"]


class ToolchainError(RuntimeError):
    """Base failure for an explicitly requested complete toolchain identity."""


class ToolchainUnavailableError(ToolchainError):
    """Raised when an analyzer identity cannot be established safely."""


@dataclass(frozen=True, slots=True)
class DependencyHealth:
    """One actual runtime dependency observation for capability composition."""

    name: str
    state: DependencyState
    version: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("dependency name must be non-empty")
        if self.state == "available" and not self.version:
            raise ValueError("available dependency must carry its version")

    def payload(self) -> dict[str, str]:
        value: dict[str, str] = {"name": self.name, "state": self.state}
        if self.version is not None:
            value["version"] = self.version
        return value


@dataclass(frozen=True, slots=True)
class ArtifactObservation:
    """Immutable bytes-derived observation of one output-affecting artifact."""

    name: str
    digest: str
    size: int
    path: str | None = None

    def payload(self) -> dict[str, Any]:
        value: dict[str, Any] = {"name": self.name, "sha256": self.digest, "bytes": self.size}
        if self.path is not None:
            value["path"] = self.path
        return value


@dataclass(frozen=True, slots=True)
class ToolchainObservation:
    """One immutable health and identity observation.

    ``manifest`` and ``digest`` are both ``None`` when any required component
    cannot be observed completely.  This distinction is deliberate: a missing
    manifest is not a valid artifact identity and must not be used for cache or
    cursor binding.
    """

    manifest: ToolchainManifest | None
    digest: str | None
    healthy: bool
    dependencies: tuple[DependencyHealth, ...]
    executable: str | None = None
    executable_version: str | None = None
    analyzer_ids: Mapping[str, str] = MappingProxyType({})
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        object.__setattr__(self, "analyzer_ids", MappingProxyType(dict(self.analyzer_ids)))
        object.__setattr__(self, "errors", tuple(self.errors))
        if (self.manifest is None) != (self.digest is None):
            raise ValueError("toolchain manifest and digest must be present or absent together")
        if self.manifest is None:
            if self.healthy:
                raise ValueError("an unhealthy toolchain observation must not claim healthy")
        elif not self.healthy:
            raise ValueError("a complete toolchain manifest must be healthy")

    @property
    def toolchain_id(self) -> str | None:
        return self.digest

    @property
    def manifest_digest(self) -> str | None:
        return self.digest

    def analyzer_id(self, language: str) -> str:
        try:
            return self.analyzer_ids[language]
        except KeyError as exc:
            if self.manifest is None or self.digest is None:
                raise ToolchainUnavailableError("analyzer identity is unavailable") from exc
            raise ToolchainUnavailableError(f"unsupported analyzer language: {language}") from exc

    def dependency_payload(self) -> list[dict[str, str]]:
        return [item.payload() for item in self.dependencies]

    def manifest_payload(self) -> dict[str, Any] | None:
        if self.manifest is None:
            return None
        return self.manifest.model_dump(mode="json", by_alias=True)


@dataclass(frozen=True, slots=True)
class _PackageObservation:
    module: ModuleType | None
    version: str | None
    artifact: ArtifactObservation | None
    state: DependencyState
    detail: str | None = None


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _version_ok(value: str | None) -> bool:
    if value is None or not _VERSION_PART_RE.fullmatch(value):
        return False
    major, minor = value.split(".", 2)[:2]

    return major == "0" and minor == "45"


def _hash_file(path: Path, *, label: str, budget: OperationBudget | None = None) -> ArtifactObservation:
    if budget is not None:
        budget.check_deadline()
    try:
        stat_result = path.stat()
    except FileNotFoundError as exc:
        raise ToolchainUnavailableError(f"required artifact is missing: {path}") from exc
    except OSError as exc:
        raise ToolchainUnavailableError(f"required artifact cannot be inspected: {path}") from exc
    if not path.is_file() or path.is_symlink():
        raise ToolchainUnavailableError(f"required artifact is not a regular file: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                if budget is not None:
                    budget.check_deadline()
                chunk = handle.read(_ARTIFACT_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise ToolchainUnavailableError(f"required artifact cannot be read: {path}") from exc
    if budget is not None:
        budget.check_deadline()
    return ArtifactObservation(label, digest.hexdigest(), int(stat_result.st_size), path.as_posix())


def _hash_paths(
    paths: Sequence[Path],
    *,
    label: str,
    root: Path,
    budget: OperationBudget | None = None,
) -> ArtifactObservation:
    digest = hashlib.sha256()
    total = 0
    for path in sorted(set(paths), key=lambda item: item.as_posix().encode("utf-8")):
        if budget is not None:
            budget.check_deadline()
        try:
            relative_name = path.relative_to(root).as_posix()
        except ValueError:
            # Explicit test/probe artifacts may live outside the package.  Do
            # not bind identity to an absolute checkout path.
            relative_name = path.name
        observation = _hash_file(path, label=relative_name, budget=budget)
        relative = observation.name.encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(observation.size.to_bytes(8, "big"))
        digest.update(observation.digest.encode("ascii"))
        total += observation.size
    if budget is not None:
        budget.check_deadline()
    return ArtifactObservation(label, digest.hexdigest(), total)


def _xray_artifact_paths(*, budget: OperationBudget | None = None) -> tuple[Path, ...]:
    package_root = Path(__file__).resolve().parent.parent
    try:
        paths = []
        for path in package_root.rglob("*.py"):
            if budget is not None:
                budget.check_deadline()
            if path.is_file() and not path.is_symlink():
                paths.append(path)
        paths = tuple(paths)
    except OSError as exc:
        raise ToolchainUnavailableError("XRAY source artifacts cannot be enumerated") from exc
    if not paths:
        raise ToolchainUnavailableError("XRAY source artifacts are unavailable")
    return paths


def _package_artifact(
    module: ModuleType,
    *,
    name: str,
    budget: OperationBudget | None = None,
) -> ArtifactObservation:
    if budget is not None:
        budget.check_deadline()
    location = getattr(module, "__file__", None)
    if not isinstance(location, str) or not location:
        raise ToolchainUnavailableError(f"{name} has no inspectable artifact")
    module_path = Path(location)
    package_root = module_path.parent
    try:
        files = []
        for path in package_root.rglob("*"):
            if budget is not None:
                budget.check_deadline()
            if (
                path.is_file()
                and not path.is_symlink()
                and path.suffix.lower() in {".py", ".pyi", ".so", ".dylib", ".dll", ".pyd"}
            ):
                files.append(path)
        files = tuple(files)
    except OSError as exc:
        raise ToolchainUnavailableError(f"{name} artifacts cannot be enumerated") from exc
    if not files:
        raise ToolchainUnavailableError(f"{name} artifacts are unavailable")
    return _hash_paths(files, label=name, root=package_root, budget=budget)


def _observe_package(
    name: str,
    import_name: str,
    *,
    budget: OperationBudget | None = None,
) -> _PackageObservation:
    if budget is not None:
        budget.check_deadline()
    try:
        module = importlib.import_module(import_name)
    except ModuleNotFoundError as exc:
        return _PackageObservation(None, None, None, "missing", str(exc))
    except ImportError as exc:
        return _PackageObservation(None, None, None, "incompatible", str(exc))
    try:
        version = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError as exc:
        return _PackageObservation(module, None, None, "missing", str(exc))
    except ValueError as exc:
        return _PackageObservation(module, None, None, "incompatible", str(exc))
    if not _version_ok(version):
        return _PackageObservation(module, version, None, "incompatible", f"unsupported {name} version {version}")
    if name == "ast-grep-py" and not all(callable(getattr(module, item, None)) for item in ("SgRoot", "SgNode")):
        return _PackageObservation(module, version, None, "incompatible", "required parser symbols are unavailable")
    try:
        artifact = _package_artifact(module, name=name, budget=budget)
        if budget is not None:
            budget.check_deadline()
    except ToolchainUnavailableError as exc:
        return _PackageObservation(module, version, None, "incompatible", str(exc))
    return _PackageObservation(module, version, artifact, "available")


def _version_from_outcome(outcome: ChildOutcome) -> str | None:
    if outcome.status != "complete" or outcome.returncode != 0:
        return None
    try:
        text = outcome.stdout.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    match = _VERSION_RE.fullmatch(text)
    return match.group(1) if match is not None else None


def probe_ast_grep_version(
    executable: str,
    *,
    limits: AstGrepLimits | None = None,
    budget: OperationBudget | None = None,
) -> tuple[str | None, str | None]:
    """Probe the resolved executable through the shared bounded child owner."""

    bounded_limits = limits or AstGrepLimits(
        stdout_bytes=4096,
        stderr_bytes=4096,
        queued_bytes=8192,
        chunk_bytes=512,
        line_bytes=4096,
        timeout_seconds=2.0,
        hard_timeout_seconds=5.0,
    )
    try:
        if budget is not None:
            budget.check_deadline()
        outcome = run_bounded_child(
            [executable, "--version"],
            limits=bounded_limits,
            env={"PATH": str(Path(executable).parent)},
            budget=budget,
            exit_policy=STRICT_CHILD_EXIT_POLICY,
        )
    except AstGrepError as exc:
        return None, str(exc)
    if budget is not None:
        budget.check_deadline()
    version = _version_from_outcome(outcome)
    if version is None:
        return None, "ast-grep executable returned an incompatible version response"
    if not _version_ok(version):
        return None, f"unsupported ast-grep version {version}"
    return version, None


class ToolchainProvider:
    """Resolve and hash the actual output-affecting runtime artifacts."""

    def __init__(
        self,
        *,
        executable: str | os.PathLike[str] | None = None,
        executable_resolver: Callable[[str | os.PathLike[str] | None], str] = resolve_ast_grep_executable,
        artifact_paths: Sequence[str | os.PathLike[str]] | None = None,
        version_probe: Callable[[str], tuple[str | None, str | None]] = probe_ast_grep_version,
    ) -> None:
        self.executable = executable
        self.executable_resolver = executable_resolver
        self.artifact_paths = tuple(Path(path) for path in artifact_paths) if artifact_paths is not None else None
        self.version_probe = version_probe

    def _source_artifact(self, *, budget: OperationBudget | None = None) -> ArtifactObservation:
        if self.artifact_paths is None:
            paths = _xray_artifact_paths(budget=budget)
            root = Path(__file__).resolve().parent.parent
        else:
            paths = self.artifact_paths
            if not paths:
                raise ToolchainUnavailableError("XRAY source artifacts are unavailable")
            absolute = [path.resolve() for path in paths]
            common = Path(os.path.commonpath([path.as_posix() for path in absolute]))
            root = common if common.is_dir() else common.parent
            paths = tuple(absolute)
        return _hash_paths(paths, label="xray", root=root, budget=budget)

    def observe(self, *, budget: OperationBudget | None = None) -> ToolchainObservation:
        if budget is not None:
            budget.check_deadline()
        dependencies: list[DependencyHealth] = []
        errors: list[str] = []
        executable_path: str | None = None
        executable_version: str | None = None
        executable_artifact: ArtifactObservation | None = None
        try:
            executable_path = self.executable_resolver(self.executable)
            executable_artifact = _hash_file(Path(executable_path), label="ast-grep", budget=budget)
            if self.version_probe is probe_ast_grep_version:
                executable_version, detail = self.version_probe(executable_path, budget=budget)  # type: ignore[call-arg]
            else:
                executable_version, detail = self.version_probe(executable_path)
            if executable_version is None:
                dependencies.append(DependencyHealth("ast-grep", "incompatible", detail=detail))
                if detail:
                    errors.append(detail)
            else:
                dependencies.append(DependencyHealth("ast-grep", "available", version=executable_version))
        except AstGrepError as exc:
            dependencies.append(DependencyHealth("ast-grep", "missing", detail=str(exc)))
            errors.append(str(exc))
        except ToolchainUnavailableError as exc:
            dependencies.append(DependencyHealth("ast-grep", "incompatible", detail=str(exc)))
            errors.append(str(exc))
        except (OSError, RuntimeError, ValueError) as exc:
            dependencies.append(DependencyHealth("ast-grep", "incompatible", detail=str(exc)))
            errors.append(str(exc))

        ast_grep_package = _observe_package("ast-grep-py", "ast_grep_py", budget=budget)
        dependencies.append(
            DependencyHealth(
                "ast-grep-py",
                ast_grep_package.state,
                ast_grep_package.version,
                ast_grep_package.detail,
            )
        )
        if budget is not None:
            budget.check_deadline()
        if ast_grep_package.detail:
            errors.append(ast_grep_package.detail)

        python_version = platform.python_version()
        python_runtime = f"{platform.python_implementation()} {python_version} unicode-{unicodedata.unidata_version}"
        python_artifact = ArtifactObservation(
            "python-ast",
            _canonical_digest(
                [
                    sys.implementation.name,
                    sys.implementation.cache_tag,
                    sys.version,
                    python_runtime,
                    getattr(ast, "__file__", None),
                ]
            ),
            0,
        )
        if budget is not None:
            budget.check_deadline()
        dependencies.append(DependencyHealth("python-ast", "available", version=python_version))

        try:
            xray_artifact = self._source_artifact(budget=budget)

        except ToolchainUnavailableError as exc:
            xray_artifact = None
            errors.append(str(exc))
            dependencies.append(DependencyHealth("xray", "incompatible", detail=str(exc)))
        else:
            try:
                xray_version = _xray_version()
            except ToolchainUnavailableError as exc:
                xray_artifact = None
                errors.append(str(exc))
                dependencies.append(DependencyHealth("xray", "incompatible", detail=str(exc)))
            else:
                dependencies.append(DependencyHealth("xray", "available", version=xray_version))

        if budget is not None:
            budget.check_deadline()
        complete = (
            executable_artifact is not None
            and executable_version is not None
            and ast_grep_package.artifact is not None
            and ast_grep_package.version is not None
            and xray_artifact is not None
            and all(item.state == "available" for item in dependencies)
        )
        if not complete:
            return ToolchainObservation(
                manifest=None,
                digest=None,
                healthy=False,
                dependencies=tuple(sorted(dependencies, key=lambda item: item.name.encode("utf-8"))),
                executable=executable_path,
                executable_version=executable_version,
                errors=tuple(errors),
            )

        assert executable_artifact is not None
        assert executable_version is not None
        assert ast_grep_package.artifact is not None
        if budget is not None:
            budget.check_deadline()
        assert ast_grep_package.version is not None
        assert xray_artifact is not None
        try:
            manifest = _build_manifest(
                xray_artifact=xray_artifact,
                executable_artifact=executable_artifact,
                executable_version=executable_version,
                ast_grep_artifact=ast_grep_package.artifact,
                ast_grep_version=ast_grep_package.version,
                python_artifact=python_artifact,
                python_version=python_version,
            )
        except (TypeError, ValueError) as exc:
            errors.append(f"toolchain manifest construction failed: {exc}")
            return ToolchainObservation(
                manifest=None,
                digest=None,
                healthy=False,
                dependencies=tuple(sorted(dependencies, key=lambda item: item.name.encode("utf-8"))),
                executable=executable_path,
                executable_version=executable_version,
                errors=tuple(errors),
            )
        if budget is not None:
            budget.check_deadline()
        manifest_payload = manifest.model_dump(mode="json", by_alias=True)
        manifest_digest = _canonical_digest(manifest_payload)
        analyzer_ids = {
            language: _canonical_digest([ANALYZER_SCHEMA, language, manifest_digest])
            for language in _SUPPORTED_LANGUAGES
        }
        return ToolchainObservation(
            manifest=manifest,
            digest=manifest_digest,
            healthy=True,
            dependencies=tuple(sorted(dependencies, key=lambda item: item.name.encode("utf-8"))),
            executable=executable_path,
            executable_version=executable_version,
            analyzer_ids=analyzer_ids,
        )


def _xray_version() -> str:
    try:
        from xray import __version__
    except ImportError as exc:
        raise ToolchainUnavailableError("XRAY package version is unavailable") from exc
    if not isinstance(__version__, str) or not __version__:
        raise ToolchainUnavailableError("XRAY package version is invalid")
    return __version__


def _build_manifest(
    *,
    xray_artifact: ArtifactObservation,
    executable_artifact: ArtifactObservation,
    executable_version: str,
    ast_grep_artifact: ArtifactObservation,
    ast_grep_version: str,
    python_artifact: ArtifactObservation,
    python_version: str,
) -> ToolchainManifest:
    grammar_artifact = _canonical_digest([ast_grep_artifact.digest, ast_grep_version])
    grammar_version = ast_grep_version
    grammars = [
        GrammarManifest(language=cast(Any, language), version=grammar_version, artifact=grammar_artifact)
        for language in LANGUAGE_ORDER
        if language in _SUPPORTED_LANGUAGES
    ]
    parser = _canonical_digest(["parser", ast_grep_artifact.digest, python_artifact.digest])
    # The complete XRAY artifact digest already covers every implementation
    # module, so derive these component identities without re-reading the
    # package tree.
    ranking = _canonical_digest(["ranking", xray_artifact.digest])
    selection = _canonical_digest(["selection", xray_artifact.digest])
    return ToolchainManifest(
        schema=TOOLCHAIN_SCHEMA,
        xray_revision=_xray_version(),
        xray_artifact=xray_artifact.digest,
        ast_grep=ToolchainComponent(version=executable_version, artifact=executable_artifact.digest),
        ast_grep_py=ToolchainComponent(version=ast_grep_version, artifact=ast_grep_artifact.digest),
        python_ast=ToolchainComponent(version=python_version, artifact=python_artifact.digest),
        grammars=grammars,
        ranking=ranking,
        selection=selection,
        parser=parser,
    )


def observe_toolchain(*, budget: OperationBudget | None = None, **kwargs: Any) -> ToolchainObservation:
    """Observe actual dependencies and artifacts once for one operation."""

    return ToolchainProvider(**kwargs).observe(budget=budget)


def analyzer_id(language: str, *, observation: ToolchainObservation | None = None) -> str:
    """Return the per-language identity from one complete observation."""

    current = observation or observe_toolchain()
    return current.analyzer_id(language)


# Explicit aliases make the single identity owner discoverable to consumers.
actual_toolchain = observe_toolchain
get_toolchain = observe_toolchain


__all__ = [
    "ANALYZER_SCHEMA",
    "ArtifactObservation",
    "DependencyHealth",
    "ToolchainError",
    "ToolchainObservation",
    "ToolchainProvider",
    "ToolchainUnavailableError",
    "actual_toolchain",
    "analyzer_id",
    "get_toolchain",
    "observe_toolchain",
    "probe_ast_grep_version",
]
