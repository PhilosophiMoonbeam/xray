"""Bounded captured-read repository primitives for the next XRAY runtime.

The provider in this module is deliberately small: it owns the one filesystem
selection used by an operation, captures bytes into immutable values, and gives
analysis code no reason to consult the live tree again.  It does not cache,
parse declarations, load arbitrary configuration, or mutate source files.
"""

from __future__ import annotations

import errno
import fnmatch
import hashlib
import json
import os
import stat as stat_module
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Literal, NoReturn, TypeAlias

import yaml
from pathspec import GitIgnoreSpec
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from xray.models import LANGUAGE_ORDER, Root, RuleInput, Selection

# Frozen D04/D07 admission values.  Keeping the values local avoids making the
# repository layer depend on any adapter or the old indexer constants.
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_SOURCE_FILES = 20_000
MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_NAMESPACE_ENTRIES = 100_000
MAX_NAMESPACE_PATH_BYTES = 16 * 1024 * 1024
MAX_CONFIGURATION_FILES = 1024
MAX_CONFIGURATION_FILE_BYTES = 1 * 1024 * 1024
MAX_CONFIGURATION_BYTES = 8 * 1024 * 1024
MAX_TEMPORARY_BYTES = 320 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
HARD_TIMEOUT_SECONDS = 120.0
CAPTURE_CHUNK_BYTES = 64 * 1024
PATH_BYTES_LIMIT = 4096
SHA256_HEX_LENGTH = 64
YAML_FILE_BYTES_LIMIT = MAX_CONFIGURATION_FILE_BYTES
YAML_TOTAL_BYTES_LIMIT = MAX_CONFIGURATION_BYTES
YAML_DEPTH_LIMIT = 64
YAML_NODE_LIMIT = 100_000
MAX_RULE_DIRS = MAX_CONFIGURATION_FILES
RULE_FILE_SUFFIXES = frozenset({".yml", ".yaml"})
CaptureDomain: TypeAlias = Literal["supported_source", "regular_text"]
SUPPORTED_SOURCE_DOMAIN: CaptureDomain = "supported_source"
REGULAR_TEXT_DOMAIN: CaptureDomain = "regular_text"

_CAPTURE_DOMAINS = frozenset({SUPPORTED_SOURCE_DOMAIN, REGULAR_TEXT_DOMAIN})


@dataclass(frozen=True, slots=True)
class NamespaceHorizon:
    """Finite namespace traversal horizon used by paged map captures.

    ``focus`` contains normalized relative paths.  Ancestors needed to reach
    those paths are retained, while descendants are admitted only through the
    requested ``depth``.  A ``None`` depth means the focus subtree is open.
    """

    focus: tuple[str, ...] = (".",)
    depth: int | None = None

    def __post_init__(self) -> None:
        if not self.focus:
            raise ValueError("namespace horizon requires at least one focus path")
        if any(not isinstance(path, str) or not path for path in self.focus):
            raise ValueError("namespace horizon focus paths must be non-empty strings")
        if len(set(self.focus)) != len(self.focus):
            raise ValueError("namespace horizon focus paths must be unique")
        if self.depth is not None and (isinstance(self.depth, bool) or self.depth < 0):
            raise ValueError("namespace horizon depth must be non-negative or None")

    @staticmethod
    def _parts(path: str) -> tuple[str, ...]:
        return () if path == "." else tuple(PurePosixPath(path).parts)

    def admits(self, path: str) -> bool:
        """Return whether a relative namespace path is in this horizon."""

        candidate = self._parts(path)
        for focus_path in self.focus:
            focus = self._parts(focus_path)
            if candidate[: len(focus)] == focus:
                if self.depth is None or len(candidate) - len(focus) <= self.depth:
                    return True
            elif focus[: len(candidate)] == candidate:
                # Keep ancestors so a bounded walk can reach a focused child.
                return True
        return False

    def can_descend(self, path: str) -> bool:
        """Return whether a directory may contain an admitted descendant."""

        candidate = self._parts(path)
        for focus_path in self.focus:
            focus = self._parts(focus_path)
            if focus[: len(candidate)] == candidate:
                # A strict focus descendant still has to be reached.  At an
                # exact focus, only a positive/unbounded depth admits children.
                if len(focus) > len(candidate) or self.depth is None or self.depth > 0:
                    return True
                continue
            if candidate[: len(focus)] == focus:
                if self.depth is None or len(candidate) - len(focus) < self.depth:
                    return True
        return False


SUPPORTED_LANGUAGES: Mapping[str, str] = MappingProxyType(
    {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".mjs": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".go": "go",
    }
)

# This is the current generated-state policy, promoted to a named immutable
# policy for the captured provider.  Directory names are handled component by
# component; wildcard entries are matched against the basename.
DEFAULT_EXCLUSIONS = frozenset(
    {
        "node_modules",
        "vendor",
        "__pycache__",
        "venv",
        ".venv",
        "env",
        "target",
        "build",
        "dist",
        ".git",
        ".svn",
        ".hg",
        ".agents",
        ".beads",
        ".claude",
        ".codex",
        ".idea",
        ".vscode",
        ".reference_projects",
        ".ruff_cache",
        ".xray",
        "site-packages",
        ".tox",
        ".pytest_cache",
        ".mypy_cache",
        "*.pyc",
        "*.pyo",
        "*.pyd",
        "*.so",
        "*.dll",
        "*.egg-info",
        "*.log",
        ".DS_Store",
        "Thumbs.db",
        "*.swp",
        "*.swo",
        "*~",
    }
)
DEFAULT_EXCLUSIONS_VERSION = "xray.generated-exclusions.v1"
SAFETY_POLICY_VERSION = "xray.safety.git-internals.v1"
SELECTION_POLICY_VERSION = "xray.selection.captured-read-set.v1"

_DEFAULT_DIRECTORY_EXCLUSIONS = frozenset(item for item in DEFAULT_EXCLUSIONS if not any(c in item for c in "*?[]"))
_DEFAULT_FILE_EXCLUSIONS = tuple(item for item in DEFAULT_EXCLUSIONS if item not in _DEFAULT_DIRECTORY_EXCLUSIONS)


class RepositoryError(RuntimeError):
    """Base typed failure raised by repository capture."""

    code = "io_error"

    def __init__(self, message: str, *, path: str | None = None, kind: str | None = None) -> None:
        super().__init__(message)
        self.path = path
        self.kind = kind


class RootError(RepositoryError):
    code = "path_outside_root"


class ContainmentError(RepositoryError):
    code = "path_outside_root"


class SymlinkError(ContainmentError):
    """A source/configuration target or path component is a symlink."""

    code = "path_outside_root"


class NotFoundError(RepositoryError):
    code = "not_found"


class ExcludedInputError(RepositoryError):
    code = "excluded_input"


class UnsupportedFileError(RepositoryError):
    code = "unsupported_file"


class InvalidEncodingError(RepositoryError):
    code = "invalid_encoding"


class SourceChangedError(RepositoryError):
    code = "source_changed"


class RepositoryIOError(RepositoryError):
    code = "io_error"


class RepositoryLimitError(RepositoryError):
    """A typed admission, namespace, temporary-storage, or deadline failure."""

    code = "execution_limit"

    def __init__(self, message: str, *, path: str | None = None, kind: str | None = None) -> None:
        super().__init__(message, path=path, kind=kind)


class CaptureLimitError(RepositoryLimitError):
    """Source or configuration admission exceeded a frozen bound."""

    code = "execution_limit"


class NamespaceLimitError(RepositoryLimitError):
    """Metadata namespace admission exceeded a frozen bound."""

    code = "analysis_limit"


class DeadlineExceededError(RepositoryLimitError):
    code = "timeout"


class CancellationError(RepositoryLimitError):
    """A cooperative operation cancellation was observed."""

    code = "execution_limit"


class MaterializationError(RepositoryLimitError):
    code = "execution_limit"


class InvalidRuleError(RepositoryError):
    """A contained rule file failed strict YAML admission or construction."""

    code = "invalid_rule"


class UnsupportedConfigurationError(RepositoryError):
    """A project configuration is outside the closed ``ruleDirs`` grammar."""

    code = "unsupported_configuration"


class RuleDependencyError(RepositoryError):
    """A captured rule dependency set could not be used safely."""

    code = "invalid_rule"


@dataclass(frozen=True, slots=True)
class CapturedFile:
    """One immutable regular-file read and its content-derived identity."""

    path: str
    content: bytes
    digest: str
    size: int
    language: str | None = None
    classification: Literal["text", "non_text_input"] = "text"
    device: int | None = field(default=None, repr=False, compare=False)
    inode: int | None = field(default=None, repr=False, compare=False)
    mode: int | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        immutable = bytes(self.content)
        object.__setattr__(self, "content", immutable)
        if self.size != len(immutable):
            raise ValueError("captured file size does not match immutable bytes")
        if len(self.digest) != SHA256_HEX_LENGTH or any(char not in "0123456789abcdef" for char in self.digest):
            raise ValueError("captured file digest must be lowercase SHA-256")
        if self.classification not in {"text", "non_text_input"}:
            raise ValueError("unknown captured file classification")

    @property
    def bytes(self) -> bytes:
        """The immutable source bytes (an alias useful to analyzers)."""

        return self.content

    @property
    def sha256(self) -> str:
        return self.digest

    @property
    def is_text(self) -> bool:
        return self.classification == "text"

    @property
    def has_nul(self) -> bool:
        return b"\x00" in self.content

    @property
    def text(self) -> str | None:
        if not self.is_text:
            return None
        return self.content.decode("utf-8")

    def manifest_record(self) -> dict[str, Any]:
        return {"path": self.path, "bytes": self.size, "sha256": self.digest}


@dataclass(frozen=True, slots=True)
class CapturedNamespaceEntry:
    """Metadata-only namespace entry; no file body is retained or hashed."""

    path: str
    kind: Literal["file", "directory", "symlink"]
    language: str | None = None

    def record(self) -> dict[str, Any]:
        value: dict[str, Any] = {"path": self.path, "kind": self.kind}
        if self.language is not None:
            value["language"] = self.language
        return value


@dataclass(frozen=True, slots=True)
class CapturedNamespace:
    """Canonical path-ordered selected namespace metadata."""

    entries: tuple[CapturedNamespaceEntry, ...]
    digest: str
    root: Root
    selection: Selection

    def __post_init__(self) -> None:
        paths = [entry.path for entry in self.entries]
        if paths != sorted(paths, key=_path_sort_key):
            raise ValueError("namespace entries must be canonical path sorted")
        if len(paths) != len(set(paths)):
            raise ValueError("namespace entries must be unique")

    @property
    def items(self) -> tuple[CapturedNamespaceEntry, ...]:
        return self.entries

    @property
    def total(self) -> int:
        return len(self.entries)


@dataclass(frozen=True, slots=True)
class PolicyInput:
    name: str
    digest: str

    def record(self) -> dict[str, str]:
        return {"name": self.name, "sha256": self.digest}


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    """Content identities consumed as source inputs for one operation."""

    sources: tuple[CapturedFile, ...]
    digest: str

    @property
    def files(self) -> tuple[CapturedFile, ...]:
        return self.sources


@dataclass(frozen=True, slots=True)
class SelectionProvenance:
    """Normalized selection, relevant ignore bytes, and selected membership."""

    selection: Selection
    ignore_files: tuple[CapturedFile, ...]
    membership: tuple[CapturedNamespaceEntry, ...]
    policies: tuple[PolicyInput, ...]
    digest: str

    @property
    def configuration(self) -> tuple[CapturedFile, ...]:
        return self.ignore_files


@dataclass(frozen=True, slots=True)
class SnapshotProvenance:
    """Consumed source and namespace identity for a captured operation."""

    sources: tuple[CapturedFile, ...]
    namespace: CapturedNamespace | None
    digest: str

    @property
    def files(self) -> tuple[CapturedFile, ...]:
        return self.sources


@dataclass(frozen=True, slots=True)
class CapturedManifest:
    """Immutable manifest and all provenance inputs for one capture."""

    root: Root
    selection: Selection
    sources: tuple[CapturedFile, ...]
    configuration: tuple[CapturedFile, ...]
    policies: tuple[PolicyInput, ...]
    source: SourceProvenance
    selection_provenance: SelectionProvenance
    snapshot: SnapshotProvenance
    digest: str

    def __post_init__(self) -> None:
        source_paths = [item.path for item in self.sources]
        config_paths = [item.path for item in self.configuration]
        if source_paths != sorted(source_paths, key=_source_path_sort_key) or len(source_paths) != len(
            set(source_paths)
        ):
            raise ValueError("manifest sources must be unique and path sorted")
        if config_paths != sorted(config_paths, key=_source_path_sort_key) or len(config_paths) != len(
            set(config_paths)
        ):
            raise ValueError("manifest configuration must be unique and path sorted")

    @property
    def files(self) -> tuple[CapturedFile, ...]:
        return self.sources

    @property
    def source_files(self) -> tuple[CapturedFile, ...]:
        return self.sources

    @property
    def source_digest(self) -> str:
        return self.source.digest

    @property
    def selection_digest(self) -> str:
        return self.selection_provenance.digest

    @property
    def snapshot_digest(self) -> str:
        return self.snapshot.digest

    @property
    def manifest_digest(self) -> str:
        return self.digest

    def input_manifest(self) -> dict[str, Any]:
        return {
            "sources": [item.manifest_record() for item in self.sources],
            "configuration": [item.manifest_record() for item in self.configuration],
            "policies": [item.record() for item in self.policies],
        }


@dataclass(frozen=True, slots=True)
class CapturedRuleSet:
    """Immutable standalone-rule or closed ``ruleDirs`` dependency closure."""

    input: RuleInput
    input_file: CapturedFile
    rules: tuple[CapturedFile, ...]
    membership: tuple[str, ...]
    digest: str

    def __post_init__(self) -> None:
        if self.input_file.path != self.input.path:
            raise ValueError("captured rule input path does not match RuleInput")
        rule_paths = [item.path for item in self.rules]
        if rule_paths != sorted(rule_paths, key=_source_path_sort_key) or len(rule_paths) != len(set(rule_paths)):
            raise ValueError("captured rules must be unique and path sorted")
        if self.input.kind == "rule" and self.rules != (self.input_file,):
            raise ValueError("standalone rule input must be the sole captured rule")
        memberships = list(self.membership)
        if memberships != sorted(memberships, key=_source_path_sort_key) or len(memberships) != len(set(memberships)):
            raise ValueError("rule membership must be unique and path sorted")
        if len(self.digest) != SHA256_HEX_LENGTH or any(char not in "0123456789abcdef" for char in self.digest):
            raise ValueError("captured rule digest must be lowercase SHA-256")
        expected = _rule_dependency_digest(self.input, self.input_file, self.rules, self.membership)
        if self.digest != expected:
            raise ValueError("captured rule digest does not match its dependencies")


@dataclass(frozen=True, slots=True)
class RepositoryCapture:
    """One operation-local capture, with namespace and source values sharing selection."""

    namespace: CapturedNamespace | None
    manifest: CapturedManifest

    @property
    def files(self) -> tuple[CapturedFile, ...]:
        return self.manifest.sources

    @property
    def sources(self) -> tuple[CapturedFile, ...]:
        return self.manifest.sources

    @property
    def configuration(self) -> tuple[CapturedFile, ...]:
        return self.manifest.configuration

    @property
    def selection(self) -> Selection:
        return self.manifest.selection

    @property
    def root(self) -> Root:
        return self.manifest.root


@dataclass
class OperationBudget:
    """Mutable accounting state scoped to one operation, never persisted."""

    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    hard_timeout_seconds: float = HARD_TIMEOUT_SECONDS
    source_files_limit: int = MAX_SOURCE_FILES
    source_bytes_limit: int = MAX_SOURCE_BYTES
    file_bytes_limit: int = MAX_FILE_BYTES
    namespace_entries_limit: int = MAX_NAMESPACE_ENTRIES
    namespace_path_bytes_limit: int = MAX_NAMESPACE_PATH_BYTES
    configuration_files_limit: int = MAX_CONFIGURATION_FILES
    configuration_file_bytes_limit: int = MAX_CONFIGURATION_FILE_BYTES
    configuration_bytes_limit: int = MAX_CONFIGURATION_BYTES
    temporary_bytes_limit: int = MAX_TEMPORARY_BYTES
    cancel: object | None = field(default=None, repr=False, compare=False)
    started: float = field(default_factory=time.monotonic, init=False)
    source_files: int = field(default=0, init=False)
    source_bytes: int = field(default=0, init=False)
    namespace_entries: int = field(default=0, init=False)
    namespace_path_bytes: int = field(default=0, init=False)
    configuration_files: int = field(default=0, init=False)
    configuration_bytes: int = field(default=0, init=False)
    temporary_bytes: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if isinstance(self.hard_timeout_seconds, bool) or self.hard_timeout_seconds <= 0:
            raise ValueError("hard_timeout_seconds must be positive")
        if self.timeout_seconds > self.hard_timeout_seconds:
            raise ValueError("timeout_seconds exceeds the hard deadline")

    @property
    def deadline(self) -> float:
        return self.started + self.timeout_seconds

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def check_deadline(self) -> None:
        cancel = self.cancel
        if cancel is not None:
            cancelled = False
            if callable(cancel):
                try:
                    cancelled = bool(cancel())
                except Exception:
                    cancelled = True
            else:
                checker = getattr(cancel, "is_set", None)
                if callable(checker):
                    cancelled = bool(checker())
            if cancelled:
                raise CancellationError("repository operation was cancelled", kind="cancelled")
        if time.monotonic() >= self.deadline:
            raise DeadlineExceededError("repository operation exceeded its deadline", kind="deadline")

    def reserve_source(self, size: int, *, path: str | None = None) -> None:
        self.check_deadline()
        if size < 0 or size > self.file_bytes_limit:
            raise CaptureLimitError(
                f"source file exceeds {self.file_bytes_limit} bytes",
                path=path,
                kind="file_bytes",
            )
        if self.source_files + 1 > self.source_files_limit:
            raise CaptureLimitError(
                f"selected source files exceed {self.source_files_limit}",
                path=path,
                kind="source_files",
            )
        if self.source_bytes + size > self.source_bytes_limit:
            raise CaptureLimitError(
                f"selected source bytes exceed {self.source_bytes_limit}",
                path=path,
                kind="source_bytes",
            )
        self.source_files += 1
        self.source_bytes += size

    def reserve_configuration(self, size: int, *, path: str | None = None) -> None:
        self.check_deadline()
        if size < 0 or size > self.configuration_file_bytes_limit:
            raise CaptureLimitError(
                f"configuration file exceeds {self.configuration_file_bytes_limit} bytes",
                path=path,
                kind="configuration_file_bytes",
            )
        if self.configuration_files + 1 > self.configuration_files_limit:
            raise CaptureLimitError(
                f"configuration files exceed {self.configuration_files_limit}",
                path=path,
                kind="configuration_files",
            )
        if self.configuration_bytes + size > self.configuration_bytes_limit:
            raise CaptureLimitError(
                f"configuration bytes exceed {self.configuration_bytes_limit}",
                path=path,
                kind="configuration_bytes",
            )
        self.configuration_files += 1
        self.configuration_bytes += size

    def charge_namespace(self, path: str) -> None:
        self.check_deadline()
        path_bytes = len(path.encode("utf-8"))
        if self.namespace_entries + 1 > self.namespace_entries_limit:
            raise NamespaceLimitError(
                f"namespace entries exceed {self.namespace_entries_limit}",
                path=path,
                kind="namespace_entries",
            )
        if self.namespace_path_bytes + path_bytes > self.namespace_path_bytes_limit:
            raise NamespaceLimitError(
                f"namespace path bytes exceed {self.namespace_path_bytes_limit}",
                path=path,
                kind="namespace_path_bytes",
            )
        self.namespace_entries += 1
        self.namespace_path_bytes += path_bytes

    def charge_temporary(self, size: int, *, path: str | None = None) -> None:
        self.check_deadline()
        if size < 0 or self.temporary_bytes + size > self.temporary_bytes_limit:
            raise MaterializationError(
                f"temporary materialization exceeds {self.temporary_bytes_limit} bytes",
                path=path,
                kind="temporary_bytes",
            )
        self.temporary_bytes += size


# Common aliases make the narrow seam discoverable without duplicating values.
ResourceBudget = OperationBudget
CaptureBudget = OperationBudget


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _path_sort_key(path: str) -> tuple[bytes, ...]:
    """Canonical namespace order: compare UTF-8 path segments independently."""

    return tuple(part.encode("utf-8", "surrogateescape") for part in PurePosixPath(path).parts)


def _source_path_sort_key(path: str) -> bytes:
    """Canonical source/rule order: compare the complete relative path bytes."""

    return path.encode("utf-8", "surrogateescape")


def _identity(stat_result: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(stat_result.st_dev),
        int(stat_result.st_ino),
        int(stat_result.st_mode),
        int(stat_result.st_size),
        int(stat_result.st_mtime_ns),
    )


def _root_id(path: str) -> str:
    return _digest(["xray.root.v1", path])


def _policy_digest(name: str, values: Any) -> str:
    return _digest([name, values])


def _rule_dependency_digest(
    input_value: RuleInput,
    input_file: CapturedFile,
    rules: Sequence[CapturedFile],
    membership: Sequence[str],
) -> str:
    return _digest(
        [
            "xray.rule-dependencies.v1",
            input_value.to_payload(),
            input_file.manifest_record(),
            [item.manifest_record() for item in rules],
            list(membership),
        ]
    )


class _YamlAdmissionError(ValueError):
    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


@dataclass(frozen=True, slots=True)
class _YamlClassification:
    documents: tuple[Any, ...]
    rule_dirs: tuple[str, ...]
    bytes: int
    nodes: int
    max_depth: int
    document_count: int


class _NoDuplicateSafeLoader(yaml.SafeLoader):
    """SafeLoader variant whose mapping constructor rejects duplicate keys."""


def _construct_no_duplicates(loader: Any, node: Any, deep: bool = False) -> dict[Any, Any]:
    if not isinstance(node, MappingNode):
        raise yaml.constructor.ConstructorError(
            None,
            None,
            f"expected a mapping node, found {getattr(node, 'id', 'unknown')}",
            getattr(node, "start_mark", None),
        )
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise _YamlAdmissionError("unhashable_key", str(exc)) from exc
        if duplicate:
            raise _YamlAdmissionError("duplicate_key", str(key))
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_NoDuplicateSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_no_duplicates)


def _yaml_node_key(node: Node) -> tuple[str, str, str]:
    if isinstance(node, ScalarNode):
        if node.value == "<<":
            raise _YamlAdmissionError("merge_key", "<<")
        return ("scalar", node.tag, node.value)
    raise _YamlAdmissionError("unhashable_key", getattr(node, "id", "unknown"))


def _inspect_yaml_nodes(data: bytes, *, total_seen: int = 0) -> tuple[tuple[Node, ...], dict[str, int]]:
    """Preflight YAML events and nodes before invoking any constructors."""

    if len(data) > YAML_FILE_BYTES_LIMIT:
        raise _YamlAdmissionError("bytes_limit", str(len(data)))
    total = total_seen + len(data)
    if total > YAML_TOTAL_BYTES_LIMIT:
        raise _YamlAdmissionError("total_bytes_limit", str(total))
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _YamlAdmissionError("invalid_utf8", str(exc)) from exc

    nodes = 0
    depth = 0
    max_depth = 0
    documents = 0
    try:
        for event in yaml.parse(text):
            if isinstance(event, yaml.events.DocumentStartEvent):
                documents += 1
            if isinstance(
                event,
                (yaml.events.ScalarEvent, yaml.events.MappingStartEvent, yaml.events.SequenceStartEvent),
            ):
                nodes += 1
                if nodes > YAML_NODE_LIMIT:
                    raise _YamlAdmissionError("node_limit", str(nodes))
            if isinstance(event, yaml.events.AliasEvent):
                raise _YamlAdmissionError("alias_rejected")
            if isinstance(event, (yaml.events.MappingStartEvent, yaml.events.SequenceStartEvent)):
                if event.anchor:
                    raise _YamlAdmissionError("anchor_rejected", event.anchor)
                if event.tag is not None:
                    raise _YamlAdmissionError("explicit_tag_rejected", event.tag)
                depth += 1
                max_depth = max(max_depth, depth)
                if depth > YAML_DEPTH_LIMIT:
                    raise _YamlAdmissionError("depth_limit", str(depth))
            elif isinstance(event, (yaml.events.MappingEndEvent, yaml.events.SequenceEndEvent)):
                depth -= 1
            if isinstance(event, yaml.events.ScalarEvent):
                if event.anchor:
                    raise _YamlAdmissionError("anchor_rejected", event.anchor)
                # Explicit standard tags are still outside the frozen grammar.
                # Implicitly resolved standard scalar tags have ``tag=None``.
                if event.tag is not None:
                    raise _YamlAdmissionError("explicit_tag_rejected", event.tag)
    except _YamlAdmissionError:
        raise
    except yaml.YAMLError as exc:
        raise _YamlAdmissionError("yaml_parse", str(exc)) from exc
    if depth != 0:
        raise _YamlAdmissionError("yaml_parse", "unbalanced YAML containers")

    try:
        composed = tuple(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError as exc:
        raise _YamlAdmissionError("yaml_compose", str(exc)) from exc
    for document in composed:
        if document is None:
            continue
        stack = [document]
        while stack:
            node = stack.pop()
            if isinstance(node, MappingNode):
                seen: set[tuple[str, str, str]] = set()
                for key_node, value_node in node.value:
                    key_identity = _yaml_node_key(key_node)
                    if key_identity in seen:
                        raise _YamlAdmissionError("duplicate_key", key_identity[2])
                    seen.add(key_identity)
                    stack.append(value_node)
                    stack.append(key_node)
            elif isinstance(node, SequenceNode):
                stack.extend(reversed(node.value))
            elif isinstance(node, ScalarNode):
                if node.value == "<<":
                    raise _YamlAdmissionError("merge_key", "<<")
    return composed, {
        "bytes": len(data),
        "nodes": nodes,
        "max_depth": max_depth,
        "documents": documents,
    }


def _safe_yaml_classify(
    data: bytes,
    *,
    input_kind: Literal["rule", "config"],
    node_total: int = 0,
) -> _YamlClassification:
    """Inspect and safely construct one bounded rule/configuration input."""

    try:
        _nodes, stats = _inspect_yaml_nodes(data, total_seen=0)
        if node_total < 0 or node_total + stats["nodes"] > YAML_NODE_LIMIT:
            raise _YamlAdmissionError("node_limit", str(node_total + stats["nodes"]))
    except _YamlAdmissionError:
        raise
    try:
        text = data.decode("utf-8")
        documents = tuple(yaml.load_all(text, Loader=_NoDuplicateSafeLoader))
    except _YamlAdmissionError:
        raise
    except UnicodeDecodeError as exc:
        raise _YamlAdmissionError("invalid_utf8", str(exc)) from exc
    except yaml.YAMLError as exc:
        raise _YamlAdmissionError("yaml_construct", str(exc)) from exc

    if not documents or any(not isinstance(document, dict) for document in documents):
        raise _YamlAdmissionError("invalid_rule", "each rule document must be a mapping")
    if input_kind == "rule":
        return _YamlClassification(
            documents=documents,
            rule_dirs=(),
            bytes=stats["bytes"],
            nodes=stats["nodes"],
            max_depth=stats["max_depth"],
            document_count=stats["documents"],
        )
    if len(documents) != 1:
        raise _YamlAdmissionError("unsupported_configuration", "configuration must contain exactly one document")
    document = documents[0]
    keys = set(document)
    if keys != {"ruleDirs"}:
        detail = ",".join(sorted(str(key) for key in keys))
        raise _YamlAdmissionError("unsupported_configuration", detail or "ruleDirs")
    raw_dirs = document["ruleDirs"]
    if (
        not isinstance(raw_dirs, list)
        or not raw_dirs
        or any(not isinstance(item, str) or not item for item in raw_dirs)
    ):
        raise _YamlAdmissionError("unsupported_configuration", "ruleDirs must be a nonempty string list")
    if len(raw_dirs) > MAX_RULE_DIRS:
        raise _YamlAdmissionError("configuration_files_limit", str(len(raw_dirs)))
    if len(raw_dirs) != len(set(raw_dirs)):
        raise _YamlAdmissionError("unsupported_configuration", "ruleDirs must not contain duplicates")
    return _YamlClassification(
        documents=documents,
        rule_dirs=tuple(raw_dirs),
        bytes=stats["bytes"],
        nodes=stats["nodes"],
        max_depth=stats["max_depth"],
        document_count=stats["documents"],
    )


def normalize_root(value: Root | str | os.PathLike[str]) -> Root:
    """Resolve one existing directory into the strict immutable ``Root`` value."""

    if isinstance(value, Root):
        raw = value.path
    else:
        raw = os.fspath(value)
    if not isinstance(raw, str) or not raw:
        raise RootError("root path must be a non-empty string")
    if "\x00" in raw or "\\" in raw:
        raise RootError("root path must be a canonical POSIX path")
    try:
        candidate = Path(raw).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RootError(f"root path cannot be resolved: {raw}") from exc
    if not candidate.is_dir():
        raise RootError(f"root path is not a directory: {raw}")
    normalized = candidate.as_posix()
    try:
        root = Root(path=normalized, id=_root_id(normalized))
    except Exception as exc:
        raise RootError(f"root path is not normalized: {normalized}") from exc
    if isinstance(value, Root) and value.id != root.id:
        raise RootError("root identity does not match normalized path")
    return root


def normalize_selection(value: Selection | Mapping[str, Any] | None = None) -> Selection:
    """Normalize path/language order while preserving ordered globs."""

    if value is None:
        raw: Mapping[str, Any] = {}
    elif isinstance(value, Selection):
        raw = value.model_dump(mode="python", exclude_none=True)
    elif isinstance(value, Mapping):
        raw = value
    else:
        raise ValueError("selection must be a Selection or mapping")

    raw_paths = raw.get("paths", ["."])
    if not isinstance(raw_paths, Sequence) or isinstance(raw_paths, (str, bytes, bytearray)):
        raise ValueError("selection.paths must be a sequence")
    paths: list[str] = []
    for item in raw_paths:
        if not isinstance(item, str):
            raise ValueError("selection.paths must contain strings")
        paths.append(_normalize_relative(item, allow_dot=True))
    if not paths:
        paths = ["."]
    paths = sorted(set(paths), key=_source_path_sort_key)

    raw_globs = raw.get("globs")
    globs: list[str] | None
    if raw_globs is None:
        globs = None
    else:
        if not isinstance(raw_globs, Sequence) or isinstance(raw_globs, (str, bytes, bytearray)):
            raise ValueError("selection.globs must be a sequence")
        globs = []
        for item in raw_globs:
            if not isinstance(item, str) or not item or "\x00" in item:
                raise ValueError("selection.globs must contain non-empty strings without NUL")
            if len(item.encode("utf-8")) > PATH_BYTES_LIMIT:
                raise ValueError("selection.globs contains an oversized pattern")
            if item in globs:
                raise ValueError("selection.globs must not contain duplicate patterns")
            globs.append(item)

    raw_languages = raw.get("languages")
    languages: list[str] | None
    if raw_languages is None:
        languages = None
    else:
        if not isinstance(raw_languages, Sequence) or isinstance(raw_languages, (str, bytes, bytearray)):
            raise ValueError("selection.languages must be a sequence")
        values = [item for item in raw_languages if isinstance(item, str)]
        if len(values) != len(raw_languages) or any(item not in LANGUAGE_ORDER for item in values):
            raise ValueError("selection.languages contains an unsupported language")
        if len(values) != len(set(values)):
            raise ValueError("selection.languages must be unique")
        languages = sorted(values, key=LANGUAGE_ORDER.index)

    exclusions = raw.get("exclusions", "default")
    if exclusions not in {"default", "none"}:
        raise ValueError("selection.exclusions must be default or none")
    payload: dict[str, Any] = {"paths": paths, "exclusions": exclusions}
    if globs is not None:
        payload["globs"] = globs
    if languages is not None:
        payload["languages"] = languages
    return Selection.model_validate(payload)


def normalize_namespace_horizon(
    value: NamespaceHorizon | Mapping[str, Any] | None = None,
) -> NamespaceHorizon | None:
    """Normalize map focus/depth into a bounded traversal horizon."""

    if value is None:
        return None
    if isinstance(value, NamespaceHorizon):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("namespace horizon must be a NamespaceHorizon or mapping")
    raw_focus = value.get("focus", (".",))
    if not isinstance(raw_focus, Sequence) or isinstance(raw_focus, (str, bytes, bytearray)):
        raise ValueError("namespace horizon focus must be a sequence")
    focus = tuple(sorted({_normalize_relative(item, allow_dot=True) for item in raw_focus}, key=_source_path_sort_key))
    if not focus:
        raise ValueError("namespace horizon requires at least one focus path")
    raw_depth = value.get("depth")
    if raw_depth == "all" or raw_depth is None:
        depth = None
    elif isinstance(raw_depth, int) and not isinstance(raw_depth, bool) and raw_depth >= 0:
        depth = raw_depth
    else:
        raise ValueError("namespace horizon depth must be a non-negative integer or 'all'")
    return NamespaceHorizon(focus=focus, depth=depth)


def _normalize_relative(value: str, *, allow_dot: bool) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ContainmentError("path must be a contained POSIX path", path=str(value))
    if len(value.encode("utf-8")) > PATH_BYTES_LIMIT:
        raise ContainmentError("path exceeds the 4096-byte UTF-8 bound", path=value)
    if value == ".":
        if allow_dot:
            return value
        raise ContainmentError("file path cannot be the repository root", path=value)
    if value.startswith("/"):
        raise ContainmentError("absolute path is outside the repository selection", path=value)
    parts = value.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise ContainmentError("path contains a non-canonical component", path=value)
    return "/".join(parts)


def _normalize_capture_domain(value: str) -> CaptureDomain:
    if value == SUPPORTED_SOURCE_DOMAIN:
        return SUPPORTED_SOURCE_DOMAIN
    if value == REGULAR_TEXT_DOMAIN:
        return REGULAR_TEXT_DOMAIN
    raise ValueError(f"unknown capture domain: {value!r}")


class RepositoryProvider:
    """Own normalized selection and one operation-local captured read set."""

    def __init__(
        self,
        root: Root | str | os.PathLike[str],
        selection: Selection | Mapping[str, Any] | None = None,
    ) -> None:
        self.root = normalize_root(root)
        self.root_path = Path(self.root.path)
        self.selection = normalize_selection(selection)
        self.root_id = self.root.id
        self._glob_spec = GitIgnoreSpec.from_lines(self.selection.globs) if self.selection.globs is not None else None

    @property
    def normalized_root(self) -> Root:
        return self.root

    @property
    def normalized_selection(self) -> Selection:
        return self.selection

    @property
    def selection_digest(self) -> str:
        return _digest(["xray.selection.v1", self.selection.to_payload()])

    def canonical_path(self, value: str | os.PathLike[str], *, allow_directory: bool = True) -> str:
        """Return a validated contained relative POSIX path."""

        candidate, relative = self._resolve(value, require_existing=True)
        if not allow_directory and not self._is_regular_file(candidate):
            raise UnsupportedFileError("path is not a regular file", path=relative)
        return relative

    def resolve_path(self, value: str | os.PathLike[str], *, require_file: bool = False) -> Path:
        candidate, _ = self._resolve(value, require_existing=True)
        if require_file and not self._is_regular_file(candidate):
            raise UnsupportedFileError("path is not a regular file", path=str(value))
        return candidate

    def ensure_contained(self, value: str | os.PathLike[str], *, require_file: bool = False) -> Path:
        return self.resolve_path(value, require_file=require_file)

    def _resolve(self, value: str | os.PathLike[str], *, require_existing: bool) -> tuple[Path, str]:
        try:
            raw = os.fspath(value)
        except TypeError as exc:
            raise ContainmentError("path must be string-like", path=str(value)) from exc
        if isinstance(raw, bytes) or not raw:
            raise ContainmentError("path must be a non-empty UTF-8 POSIX path", path=str(value))
        if "\x00" in raw or "\\" in raw:
            raise ContainmentError("path must be a canonical POSIX path", path=raw)
        is_absolute = raw.startswith("/")
        if is_absolute:
            lexical = Path(raw)
            try:
                relative = lexical.relative_to(self.root_path).as_posix()
            except ValueError as exc:
                raise ContainmentError("path is outside repository root", path=raw) from exc
        else:
            relative = _normalize_relative(raw, allow_dot=True)
            lexical = self.root_path if relative == "." else self.root_path / relative
        if relative == "":
            relative = "."
        if relative != ".":
            relative = _normalize_relative(relative, allow_dot=False)
        self._assert_no_symlink_components(lexical, relative)
        if require_existing:
            try:
                lexical.lstat()
            except FileNotFoundError as exc:
                raise NotFoundError("path does not exist", path=relative) from exc
            except OSError as exc:
                raise RepositoryIOError("could not stat path", path=relative) from exc
        return lexical, relative

    def _assert_no_symlink_components(self, candidate: Path, relative: str) -> None:
        current = self.root_path
        if relative == ".":
            return
        for component in PurePosixPath(relative).parts:
            current = current / component
            try:
                mode = os.lstat(current).st_mode
            except FileNotFoundError:
                # The caller decides whether a missing leaf is acceptable.  An
                # absent component cannot be a symlink escape.
                break
            except OSError as exc:
                raise RepositoryIOError("could not inspect path component", path=relative) from exc
            if stat_module.S_ISLNK(mode):
                raise SymlinkError("symlink path components are not allowed", path=relative, kind="symlink")

    @staticmethod
    def _is_regular_file(path: Path) -> bool:
        try:
            return stat_module.S_ISREG(os.lstat(path).st_mode)
        except OSError:
            return False

    def _is_safety_path(self, relative: str) -> bool:
        return ".git" in PurePosixPath(relative).parts

    def _generated_excluded(self, relative: str) -> bool:
        parts = PurePosixPath(relative).parts
        if any(part in _DEFAULT_DIRECTORY_EXCLUSIONS for part in parts):
            return True
        basename = parts[-1] if parts else relative
        return any(fnmatch.fnmatchcase(basename, pattern) for pattern in _DEFAULT_FILE_EXCLUSIONS)

    def _glob_matches(self, relative: str, *, is_directory: bool = False) -> bool:
        if self._glob_spec is None:
            return True
        # Directory globs are not a traversal authority.  Descendants may
        # still match, so the final glob decision is made for regular files.
        if is_directory:
            return True
        return bool(self._glob_spec.match_file(relative))

    def _ignored(
        self,
        relative: str,
        *,
        is_directory: bool,
        explicit_file: bool = False,
        explicit_directory: bool = False,
        rules: Sequence[_IgnoreRule] = (),
    ) -> bool:
        if self._is_safety_path(relative):
            return True
        if explicit_file:
            # Explicit file targets override generated and repository ignores;
            # ordered globs remain the final caller restriction.
            return not self._glob_matches(relative)
        if self.selection.exclusions == "default" and not explicit_directory and self._generated_excluded(relative):
            return True
        ignored = False
        for rule in rules:
            try:
                candidate = PurePosixPath(relative).relative_to(PurePosixPath(rule.relative_dir)).as_posix()
            except ValueError:
                continue
            if is_directory:
                candidate += "/"
            decision = rule.decision(candidate)
            if decision is not None:
                ignored = decision
        if not is_directory and not self._glob_matches(relative):
            return True
        return ignored

    def _policy_inputs(self) -> tuple[PolicyInput, ...]:
        policies: list[PolicyInput] = []
        if self.selection.exclusions == "default":
            policies.append(
                PolicyInput(
                    DEFAULT_EXCLUSIONS_VERSION,
                    _policy_digest(
                        DEFAULT_EXCLUSIONS_VERSION,
                        sorted(DEFAULT_EXCLUSIONS, key=lambda item: item.encode()),
                    ),
                )
            )
        policies.append(
            PolicyInput(
                SAFETY_POLICY_VERSION,
                _policy_digest(SAFETY_POLICY_VERSION, [".git", "no_symlink_following"]),
            )
        )
        policies.append(
            PolicyInput(
                SELECTION_POLICY_VERSION,
                _policy_digest(SELECTION_POLICY_VERSION, self.selection.to_payload()),
            )
        )
        return tuple(sorted(policies, key=lambda item: (item.name.encode("utf-8"), item.digest)))

    def _read_file(
        self,
        relative: str,
        *,
        budget: OperationBudget,
        source: bool,
        exact: bool = False,
    ) -> CapturedFile:
        candidate, normalized = self._resolve(relative, require_existing=True)
        if normalized not in {relative, "."}:
            relative = normalized
        try:
            initial = os.lstat(candidate)
        except OSError as exc:
            raise RepositoryIOError("could not stat source", path=relative) from exc
        if stat_module.S_ISLNK(initial.st_mode):
            raise SymlinkError("symlink source is not allowed", path=relative, kind="symlink")
        if not stat_module.S_ISREG(initial.st_mode):
            raise UnsupportedFileError("only regular files can be captured", path=relative)
        size = int(initial.st_size)
        if source:
            budget.reserve_source(size, path=relative)
            max_bytes = budget.file_bytes_limit
        else:
            budget.reserve_configuration(size, path=relative)
            max_bytes = budget.configuration_file_bytes_limit
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(candidate, flags)
        except FileNotFoundError as exc:
            raise SourceChangedError("source disappeared during capture", path=relative) from exc
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EMLINK}:
                raise SymlinkError("symlink source is not allowed", path=relative, kind="symlink") from exc
            raise RepositoryIOError("could not open source", path=relative) from exc

        chunks: list[bytes] = []
        hasher = hashlib.sha256()
        total = 0
        try:
            opened = os.fstat(fd)
            if _identity(opened) != _identity(initial):
                raise SourceChangedError("source identity changed before read", path=relative)
            while True:
                budget.check_deadline()
                try:
                    chunk = os.read(fd, CAPTURE_CHUNK_BYTES)
                except OSError as exc:
                    raise RepositoryIOError("source read failed", path=relative) from exc
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise CaptureLimitError(
                        f"source file exceeds {max_bytes} bytes while reading",
                        path=relative,
                        kind="file_bytes",
                    )
                budget.charge_temporary(len(chunk), path=relative)
                hasher.update(chunk)
                chunks.append(chunk)
            finished = os.fstat(fd)
        finally:
            os.close(fd)

        try:
            after = os.lstat(candidate)
        except FileNotFoundError as exc:
            raise SourceChangedError("source disappeared after capture", path=relative) from exc
        except OSError as exc:
            raise RepositoryIOError("could not restat source", path=relative) from exc
        self._assert_no_symlink_components(candidate, relative)
        if _identity(finished) != _identity(opened) or _identity(after) != _identity(initial):
            raise SourceChangedError("source changed during capture", path=relative)
        content = b"".join(chunks)
        digest = hasher.hexdigest()
        try:
            content.decode("utf-8")
            valid_utf8 = True
        except UnicodeDecodeError:
            valid_utf8 = False
        classification: Literal["text", "non_text_input"] = (
            "text" if valid_utf8 and b"\x00" not in content else "non_text_input"
        )
        if exact and classification != "text":
            raise InvalidEncodingError("exact source is not valid UTF-8 text without NUL", path=relative)
        language = SUPPORTED_LANGUAGES.get(Path(relative).suffix)
        return CapturedFile(
            path=relative,
            content=content,
            digest=digest,
            size=total,
            language=language,
            classification=classification,
            device=int(initial.st_dev),
            inode=int(initial.st_ino),
            mode=int(initial.st_mode),
        )

    def capture_file(
        self,
        value: str | os.PathLike[str],
        *,
        exact: bool = False,
        budget: OperationBudget | None = None,
    ) -> CapturedFile:
        """Capture one regular file exactly once, without selecting siblings."""

        local_budget = budget or OperationBudget()
        _, relative = self._resolve(value, require_existing=True)
        if self._is_safety_path(relative):
            raise ExcludedInputError("repository internals are excluded", path=relative)
        return self._read_file(relative, budget=local_budget, source=True, exact=exact)

    def capture_exact_file(
        self,
        value: str | os.PathLike[str],
        *,
        budget: OperationBudget | None = None,
    ) -> CapturedFile:
        return self.capture_file(value, exact=True, budget=budget)

    read_file = capture_file

    @staticmethod
    def _check_rule_deadline(deadline: float | None, *, budget: OperationBudget | None = None) -> None:
        if budget is not None:
            budget.check_deadline()
        if deadline is not None and time.monotonic() >= deadline:
            raise DeadlineExceededError("rule dependency capture exceeded its deadline", kind="deadline")

    @staticmethod
    def _rule_directory_path(config_path: str, raw: str) -> str:
        normalized = _normalize_relative(raw, allow_dot=True)
        parent = PurePosixPath(config_path).parent.as_posix()
        if parent == ".":
            return normalized
        if normalized == ".":
            return parent
        return f"{parent}/{normalized}"

    @staticmethod
    def _raise_yaml_error(path: str, error: _YamlAdmissionError) -> NoReturn:
        if error.kind.startswith("unsupported_configuration") or error.kind == "configuration_files_limit":
            raise UnsupportedConfigurationError(str(error), path=path, kind=error.kind) from error
        raise InvalidRuleError(str(error), path=path, kind=error.kind) from error

    def _capture_rule_dependency(
        self,
        relative: str,
        *,
        budget: OperationBudget,
        seen: dict[str, CapturedFile],
        deadline: float | None,
        yaml_nodes: list[int] | None = None,
    ) -> CapturedFile:
        self._check_rule_deadline(deadline, budget=budget)
        existing = seen.get(relative)
        if existing is not None:
            return existing
        totals = yaml_nodes if yaml_nodes is not None else [0]
        try:
            captured = self._read_file(relative, budget=budget, source=False, exact=True)
            classification = _safe_yaml_classify(
                captured.content,
                input_kind="rule",
                node_total=totals[0],
            )
            totals[0] += classification.nodes
        except _YamlAdmissionError as exc:
            self._raise_yaml_error(relative, exc)
        except InvalidEncodingError as exc:
            raise InvalidRuleError(str(exc), path=relative, kind="invalid_utf8") from exc
        seen[relative] = captured
        return captured

    def _walk_rule_directory(
        self,
        path: Path,
        relative: str,
        *,
        budget: OperationBudget,
        seen: dict[str, CapturedFile],
        rules: dict[str, CapturedFile],
        membership: set[str],
        deadline: float | None,
        visited_entries: set[str] | None = None,
        visited_dirs: set[str] | None = None,
        yaml_nodes: list[int] | None = None,
    ) -> None:
        """Iteratively capture one rule directory without eager enumeration.

        Every unique path inspected in the closure is charged before it can be
        retained or traversed.  ``visited_entries`` and ``visited_dirs`` are
        shared by all ``ruleDirs`` roots so overlapping roots do not multiply
        namespace charges or recursively revisit one another.
        """

        entries = visited_entries if visited_entries is not None else set()
        directories = visited_dirs if visited_dirs is not None else set()
        totals = yaml_nodes if yaml_nodes is not None else [0]
        pending: list[tuple[Path, str]] = [(path, relative)]
        while pending:
            current, current_relative = pending.pop()
            self._check_rule_deadline(deadline, budget=budget)
            if current_relative in directories:
                continue
            if current_relative not in entries:
                budget.charge_namespace(current_relative)
                entries.add(current_relative)
            try:
                directory_stat = os.lstat(current)
            except FileNotFoundError as exc:
                raise NotFoundError("rule directory does not exist", path=current_relative) from exc
            except OSError as exc:
                raise RepositoryIOError("could not stat rule directory", path=current_relative) from exc
            if stat_module.S_ISLNK(directory_stat.st_mode):
                raise SymlinkError("rule directory symlink is not allowed", path=current_relative, kind="symlink")
            if not stat_module.S_ISDIR(directory_stat.st_mode):
                raise UnsupportedConfigurationError(
                    "ruleDirs entries must be directories",
                    path=current_relative,
                    kind="rule_dir",
                )
            before_identity = _identity(directory_stat)
            directories.add(current_relative)
            membership.add(current_relative)
            try:
                children = os.scandir(current)
            except FileNotFoundError as exc:
                raise SourceChangedError(
                    "rule directory disappeared during enumeration",
                    path=current_relative,
                ) from exc
            except OSError as exc:
                raise RepositoryIOError(
                    "could not enumerate rule directory",
                    path=current_relative,
                ) from exc
            try:
                for child in children:
                    self._check_rule_deadline(deadline, budget=budget)
                    name = child.name
                    if not isinstance(name, str) or not name or "\x00" in name or "\\" in name:
                        raise UnsupportedConfigurationError(
                            "rule directory contains an unsupported entry name",
                            path=current_relative,
                            kind="rule_membership",
                        )
                    child_relative = name if current_relative == "." else f"{current_relative}/{name}"
                    if child_relative in entries:
                        continue
                    # Charge before stat/retention so irrelevant files and
                    # empty directories cannot bypass the namespace ceiling.
                    budget.charge_namespace(child_relative)
                    entries.add(child_relative)
                    try:
                        child_stat = child.stat(follow_symlinks=False)
                    except FileNotFoundError as exc:
                        raise SourceChangedError(
                            "rule membership entry disappeared during enumeration",
                            path=child_relative,
                        ) from exc
                    except OSError as exc:
                        raise RepositoryIOError("could not stat rule membership", path=child_relative) from exc
                    mode = child_stat.st_mode
                    if stat_module.S_ISLNK(mode):
                        raise SymlinkError(
                            "symlink components are not allowed in rule dependencies",
                            path=child_relative,
                            kind="symlink",
                        )
                    if stat_module.S_ISDIR(mode):
                        pending.append((Path(child.path), child_relative))
                        continue
                    if not stat_module.S_ISREG(mode):
                        continue
                    if Path(name).suffix.lower() not in RULE_FILE_SUFFIXES:
                        continue
                    captured = self._capture_rule_dependency(
                        child_relative,
                        budget=budget,
                        seen=seen,
                        deadline=deadline,
                        yaml_nodes=totals,
                    )
                    rules[child_relative] = captured
                    membership.add(child_relative)
            finally:
                try:
                    children.close()
                except OSError as exc:
                    raise RepositoryIOError(
                        "could not close rule directory enumeration",
                        path=current_relative,
                    ) from exc
            try:
                after_identity = _identity(os.lstat(current))
            except FileNotFoundError as exc:
                raise SourceChangedError(
                    "rule directory disappeared during enumeration",
                    path=current_relative,
                ) from exc
            except OSError as exc:
                raise RepositoryIOError("could not restat rule directory", path=current_relative) from exc
            if after_identity != before_identity:
                raise SourceChangedError(
                    "rule directory namespace changed during enumeration",
                    path=current_relative,
                )

    def capture_rule_input(
        self,
        value: RuleInput | Mapping[str, Any],
        *,
        budget: OperationBudget | None = None,
        deadline: float | None = None,
    ) -> CapturedRuleSet:
        """Capture and admit one contained standalone rule or ``ruleDirs`` config."""
        local_budget = budget or OperationBudget()
        self._check_rule_deadline(deadline, budget=local_budget)
        try:
            input_value = value if isinstance(value, RuleInput) else RuleInput.model_validate(value)
        except Exception as exc:
            raise InvalidRuleError("rule input must be a valid RuleInput", kind="input") from exc
        relative = input_value.path
        if Path(relative).suffix.lower() not in RULE_FILE_SUFFIXES:
            raise InvalidRuleError("rule input must be a .yml or .yaml file", path=relative, kind="extension")
        if self._is_safety_path(relative):
            raise ExcludedInputError("repository internals are excluded", path=relative)
        yaml_nodes = [0]
        try:
            input_file = self._read_file(relative, budget=local_budget, source=False, exact=True)
            self._check_rule_deadline(deadline, budget=local_budget)
            classification = _safe_yaml_classify(
                input_file.content,
                input_kind=input_value.kind,
                node_total=yaml_nodes[0],
            )
            yaml_nodes[0] += classification.nodes
        except _YamlAdmissionError as exc:
            self._raise_yaml_error(relative, exc)
        except InvalidEncodingError as exc:
            raise InvalidRuleError(str(exc), path=relative, kind="invalid_utf8") from exc

        seen: dict[str, CapturedFile] = {relative: input_file}
        if input_value.kind == "rule":
            rules = (input_file,)
            membership = (relative,)
        else:
            rules_by_path: dict[str, CapturedFile] = {}
            membership_set: set[str] = set()
            visited_entries: set[str] = set()
            visited_dirs: set[str] = set()
            for raw_dir in classification.rule_dirs:
                self._check_rule_deadline(deadline, budget=local_budget)
                directory_relative = self._rule_directory_path(relative, raw_dir)
                if self._is_safety_path(directory_relative):
                    raise ExcludedInputError("repository internals are excluded", path=directory_relative)
                candidate, normalized = self._resolve(directory_relative, require_existing=True)
                if normalized != directory_relative:
                    directory_relative = normalized
                self._walk_rule_directory(
                    candidate,
                    directory_relative,
                    budget=local_budget,
                    seen=seen,
                    rules=rules_by_path,
                    membership=membership_set,
                    deadline=deadline,
                    visited_entries=visited_entries,
                    yaml_nodes=yaml_nodes,
                    visited_dirs=visited_dirs,
                )
            if not rules_by_path:
                raise InvalidRuleError(
                    "ruleDirs did not contain any .yml or .yaml rules",
                    path=relative,
                    kind="empty_rule_set",
                )
            rules = tuple(rules_by_path[path] for path in sorted(rules_by_path, key=_source_path_sort_key))
            membership = tuple(sorted(membership_set, key=_source_path_sort_key))
        self._check_rule_deadline(deadline, budget=local_budget)
        digest = _rule_dependency_digest(input_value, input_file, rules, membership)
        return CapturedRuleSet(
            input=input_value,
            input_file=input_file,
            rules=rules,
            membership=membership,
            digest=digest,
        )

    def assert_rule_input_unchanged(
        self,
        captured: CapturedRuleSet,
        *,
        budget: OperationBudget | None = None,
        deadline: float | None = None,
    ) -> None:
        """Reject any relevant rule/config/membership drift since capture."""

        if not isinstance(captured, CapturedRuleSet):
            raise RuleDependencyError("expected a CapturedRuleSet", kind="input")
        try:
            current = self.capture_rule_input(captured.input, budget=budget, deadline=deadline)
        except RepositoryError as exc:
            raise SourceChangedError(
                "captured rule dependencies no longer match the repository",
                path=captured.input.path,
                kind="rule_dependency",
            ) from exc
        if current.digest != captured.digest:
            raise SourceChangedError(
                "captured rule dependencies changed since capture",
                path=captured.input.path,
                kind="rule_dependency",
            )

    def _capture_ignore_file(
        self,
        relative: str,
        *,
        budget: OperationBudget,
        seen: dict[str, CapturedFile],
    ) -> CapturedFile | None:
        budget.check_deadline()
        if relative in seen:
            return seen[relative]
        candidate = self.root_path if relative == "." else self.root_path / relative
        try:
            st = os.lstat(candidate)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise RepositoryIOError("could not inspect .gitignore", path=relative) from exc
        if not stat_module.S_ISREG(st.st_mode) or stat_module.S_ISLNK(st.st_mode):
            return None
        captured = self._read_file(relative, budget=budget, source=False, exact=False)
        seen[relative] = captured
        return captured

    def _rule_for(
        self,
        relative_dir: str,
        captured: CapturedFile,
        *,
        budget: OperationBudget | None = None,
    ) -> _IgnoreRule:
        if budget is not None:
            budget.check_deadline()
        try:
            text = captured.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidEncodingError(".gitignore is not valid UTF-8", path=captured.path) from exc
        lines = text.splitlines()
        try:
            spec = GitIgnoreSpec.from_lines(lines)
        except Exception as exc:
            raise RepositoryIOError("could not parse .gitignore", path=captured.path) from exc
        if budget is not None:
            budget.check_deadline()
        return _IgnoreRule(relative_dir, spec, tuple(lines))

    def _load_rules_chain(
        self,
        directory: str,
        *,
        budget: OperationBudget,
        config: dict[str, CapturedFile],
        rules_cache: dict[str, tuple[_IgnoreRule, ...]] | None = None,
    ) -> tuple[_IgnoreRule, ...]:
        budget.check_deadline()
        if rules_cache is not None:
            cached = rules_cache.get(directory)
            if cached is not None:
                return cached
        parts = [] if directory == "." else list(PurePosixPath(directory).parts)
        rules: list[_IgnoreRule] = []
        for index in range(len(parts) + 1):
            budget.check_deadline()
            relative_dir = "." if index == 0 else "/".join(parts[:index])
            ignore_path = ".gitignore" if relative_dir == "." else f"{relative_dir}/.gitignore"
            captured = self._capture_ignore_file(ignore_path, budget=budget, seen=config)
            if captured is not None:
                rules.append(self._rule_for(relative_dir, captured, budget=budget))
        result = tuple(rules)
        if rules_cache is not None:
            rules_cache[directory] = result
        return result

    def _scope_paths(
        self,
        *,
        budget: OperationBudget,
        rules_cache: dict[str, tuple[_IgnoreRule, ...]] | None = None,
    ) -> tuple[tuple[str, ...], tuple[str, ...], dict[str, CapturedFile]]:
        explicit_files: list[str] = []
        explicit_dirs: list[str] = []
        config: dict[str, CapturedFile] = {}
        for scope in self.selection.paths:
            budget.check_deadline()
            candidate, relative = self._resolve(scope, require_existing=True)
            if self._is_safety_path(relative):
                raise ExcludedInputError("repository internals are excluded", path=relative)
            if self._is_regular_file(candidate):
                explicit_files.append(relative)
                parent = "." if relative == "." else str(PurePosixPath(relative).parent)
                self._load_rules_chain(parent, budget=budget, config=config, rules_cache=rules_cache)
            elif candidate.is_dir():
                explicit_dirs.append(relative)
                self._load_rules_chain(relative, budget=budget, config=config, rules_cache=rules_cache)
            else:
                raise UnsupportedFileError("selection path is not a regular file or directory", path=relative)
        return (
            tuple(sorted(set(explicit_files), key=_source_path_sort_key)),
            tuple(sorted(set(explicit_dirs), key=_source_path_sort_key)),
            config,
        )

    @staticmethod
    def _directory_walk_roots(explicit_dirs: Sequence[str]) -> tuple[str, ...]:
        """Return explicit directory roots with nested walks collapsed."""

        roots: list[str] = []
        for relative in sorted(
            explicit_dirs,
            key=lambda item: (len(PurePosixPath(item).parts), _source_path_sort_key(item)),
        ):
            if any(root in {".", relative} or relative.startswith(f"{root}/") for root in roots):
                continue
            roots.append(relative)
        return tuple(roots)

    def _entry(
        self,
        relative: str,
        kind: Literal["file", "directory", "symlink"],
        *,
        budget: OperationBudget,
    ) -> CapturedNamespaceEntry:
        budget.charge_namespace(relative)
        language = SUPPORTED_LANGUAGES.get(Path(relative).suffix) if kind == "file" else None
        return CapturedNamespaceEntry(path=relative, kind=kind, language=language)

    def _directory_identity(self, path: Path, relative: str) -> tuple[int, int, int, int, int]:
        try:
            stat_result = os.lstat(path)
        except OSError as exc:
            raise RepositoryIOError("could not stat directory", path=relative) from exc
        if not stat_module.S_ISDIR(stat_result.st_mode) or stat_module.S_ISLNK(stat_result.st_mode):
            raise SourceChangedError("directory became non-directory during enumeration", path=relative)
        return _identity(stat_result)

    def _walk_directory(
        self,
        path: Path,
        relative: str,
        *,
        budget: OperationBudget,
        config: dict[str, CapturedFile],
        entries: dict[str, CapturedNamespaceEntry],
        inherited_rules: tuple[_IgnoreRule, ...] = (),
        rules_cache: dict[str, tuple[_IgnoreRule, ...]] | None = None,
        horizon: NamespaceHorizon | None = None,
    ) -> None:
        budget.check_deadline()
        if horizon is not None and not horizon.can_descend(relative):
            return
        before = self._directory_identity(path, relative)
        own_rules = self._load_rules_chain(relative, budget=budget, config=config, rules_cache=rules_cache)
        rules = own_rules if own_rules else inherited_rules
        try:
            with os.scandir(path) as children:
                for child in children:
                    budget.check_deadline()
                    name = child.name
                    if not isinstance(name, str) or "\x00" in name or "\\" in name:
                        raise UnsupportedFileError("filesystem entry has an unsupported name", path=relative)
                    child_relative = name if relative == "." else f"{relative}/{name}"
                    if horizon is not None and not horizon.admits(child_relative):
                        continue
                    try:
                        child_stat = child.stat(follow_symlinks=False)
                    except OSError as exc:
                        raise RepositoryIOError("could not stat namespace entry", path=child_relative) from exc
                    mode = child_stat.st_mode
                    is_link = stat_module.S_ISLNK(mode)
                    is_dir = stat_module.S_ISDIR(mode) and not is_link
                    is_file = stat_module.S_ISREG(mode) and not is_link
                    if is_link:
                        if not self._ignored(child_relative, is_directory=False, rules=rules):
                            entries[child_relative] = self._entry(child_relative, "symlink", budget=budget)
                        continue
                    if is_dir:
                        explicit_directory = child_relative in self.selection.paths
                        if self._ignored(
                            child_relative,
                            is_directory=True,
                            explicit_directory=explicit_directory,
                            rules=rules,
                        ):
                            continue
                        entries[child_relative] = self._entry(child_relative, "directory", budget=budget)
                        self._walk_directory(
                            Path(child.path),
                            child_relative,
                            budget=budget,
                            config=config,
                            entries=entries,
                            inherited_rules=rules,
                            rules_cache=rules_cache,
                            horizon=horizon,
                        )
                        continue
                    if is_file:
                        explicit_file = child_relative in self.selection.paths
                        if self._ignored(
                            child_relative,
                            is_directory=False,
                            explicit_file=explicit_file,
                            rules=rules,
                        ):
                            if explicit_file and not self._glob_matches(child_relative):
                                raise ExcludedInputError(
                                    "explicit target is excluded by its glob selection", path=child_relative
                                )
                            continue
                        entries[child_relative] = self._entry(child_relative, "file", budget=budget)
                        continue
                    if child_relative in self.selection.paths:
                        raise UnsupportedFileError("selection target is not a regular file", path=child_relative)
        except OSError as exc:
            raise RepositoryIOError("could not enumerate directory", path=relative) from exc
        after = self._directory_identity(path, relative)
        if after != before:
            raise SourceChangedError("directory namespace changed during enumeration", path=relative)

    def _collect_namespace(
        self,
        *,
        budget: OperationBudget,
        scoped: tuple[tuple[str, ...], tuple[str, ...], dict[str, CapturedFile]] | None = None,
        rules_cache: dict[str, tuple[_IgnoreRule, ...]] | None = None,
        horizon: NamespaceHorizon | Mapping[str, Any] | None = None,
    ) -> tuple[CapturedNamespace, tuple[str, ...], tuple[str, ...], dict[str, CapturedFile]]:
        horizon = normalize_namespace_horizon(horizon)
        budget.check_deadline()
        if scoped is None:
            explicit_files, explicit_dirs, config = self._scope_paths(budget=budget, rules_cache=rules_cache)
        else:
            explicit_files, explicit_dirs, config = scoped
        entries: dict[str, CapturedNamespaceEntry] = {}
        entries["."] = self._entry(".", "directory", budget=budget)
        walk_roots = set(self._directory_walk_roots(explicit_dirs))
        for relative in explicit_dirs:
            budget.check_deadline()
            if horizon is not None and not horizon.admits(relative):
                continue
            parts = [] if relative == "." else list(PurePosixPath(relative).parts)
            parent = "."
            for part in parts:
                budget.check_deadline()
                child_relative = part if parent == "." else f"{parent}/{part}"
                if horizon is not None and not horizon.admits(child_relative):
                    continue
                if child_relative not in entries:
                    entries[child_relative] = self._entry(child_relative, "directory", budget=budget)
                parent = child_relative
            if relative not in walk_roots:
                continue
            candidate = self.root_path if relative == "." else self.root_path / relative
            self._walk_directory(
                candidate,
                relative,
                budget=budget,
                config=config,
                entries=entries,
                rules_cache=rules_cache,
                horizon=horizon,
            )
        for relative in explicit_files:
            budget.check_deadline()
            if horizon is not None and not horizon.admits(relative):
                continue
            if not self._glob_matches(relative):
                raise ExcludedInputError("explicit target is excluded by its glob selection", path=relative)
            parts = list(PurePosixPath(relative).parts[:-1])
            parent = "."
            for part in parts:
                budget.check_deadline()
                child_relative = part if parent == "." else f"{parent}/{part}"
                if horizon is not None and not horizon.admits(child_relative):
                    continue
                if child_relative not in entries:
                    entries[child_relative] = self._entry(child_relative, "directory", budget=budget)
                parent = child_relative
            if relative not in entries:
                entries[relative] = self._entry(relative, "file", budget=budget)
        budget.check_deadline()
        canonical = tuple(entries[path] for path in sorted(entries, key=_path_sort_key))
        namespace_digest = _digest(["xray.namespace.v1", [entry.record() for entry in canonical]])
        namespace = CapturedNamespace(canonical, namespace_digest, self.root, self.selection)
        return namespace, explicit_files, explicit_dirs, config

    def _selection_provenance(
        self,
        *,
        namespace: CapturedNamespace | None,
        config: Mapping[str, CapturedFile],
        sources: tuple[CapturedFile, ...],
        budget: OperationBudget | None = None,
    ) -> SelectionProvenance:
        if budget is not None:
            budget.check_deadline()
        membership = (
            namespace.entries
            if namespace is not None
            else tuple(CapturedNamespaceEntry(path=item.path, kind="file", language=item.language) for item in sources)
        )
        ignore_files = tuple(config[path] for path in sorted(config, key=_path_sort_key))
        policies = self._policy_inputs()
        payload = {
            "selection": self.selection.to_payload(),
            "policies": [item.record() for item in policies],
            "ignore": [item.manifest_record() for item in ignore_files],
            "membership": [item.record() for item in membership],
        }
        if budget is not None:
            budget.check_deadline()
        return SelectionProvenance(
            selection=self.selection,
            ignore_files=ignore_files,
            membership=tuple(membership),
            policies=policies,
            digest=_digest(["xray.selection.v1", payload]),
        )

    def _manifest(
        self,
        *,
        namespace: CapturedNamespace | None,
        config: Mapping[str, CapturedFile],
        sources: Iterable[CapturedFile],
        budget: OperationBudget | None = None,
    ) -> CapturedManifest:
        if budget is not None:
            budget.check_deadline()
        source_values = tuple(sorted(sources, key=lambda item: _source_path_sort_key(item.path)))
        config_values = tuple(config[path] for path in sorted(config, key=_source_path_sort_key))
        source_digest = _digest(["xray.sources.v1", [item.manifest_record() for item in source_values]])
        source_provenance = SourceProvenance(source_values, source_digest)
        selection_provenance = self._selection_provenance(
            namespace=namespace,
            config=config,
            sources=source_values,
            budget=budget,
        )
        snapshot_payload = {
            "sources": [item.manifest_record() for item in source_values],
            "namespace": namespace.digest if namespace is not None else None,
        }
        snapshot_provenance = SnapshotProvenance(
            source_values,
            namespace,
            _digest(["xray.snapshot.v1", snapshot_payload]),
        )
        payload = {
            "root": self.root.to_payload(),
            "selection": self.selection.to_payload(),
            "sources": [item.manifest_record() for item in source_values],
            "configuration": [item.manifest_record() for item in config_values],
            "policies": [item.record() for item in self._policy_inputs()],
            "selection_digest": selection_provenance.digest,
            "snapshot_digest": snapshot_provenance.digest,
        }
        if budget is not None:
            budget.check_deadline()
        return CapturedManifest(
            root=self.root,
            selection=self.selection,
            sources=source_values,
            configuration=config_values,
            policies=self._policy_inputs(),
            source=source_provenance,
            selection_provenance=selection_provenance,
            snapshot=snapshot_provenance,
            digest=_digest(["xray.manifest.v1", payload]),
        )

    def _capture_selected_sources(
        self,
        *,
        namespace: CapturedNamespace | None,
        explicit_files: Sequence[str],
        budget: OperationBudget,
        capture_domain: CaptureDomain = SUPPORTED_SOURCE_DOMAIN,
    ) -> tuple[CapturedFile, ...]:
        """Capture every selected regular file in one bounded input domain.

        ``supported_source`` is the structural-analysis profile and admits
        only files with a known language suffix.  ``regular_text`` is used by
        literal and lexical consumers and admits every regular file; those
        consumers still inspect the immutable classification before decoding.
        In both profiles a selected non-text file remains in the manifest so
        coverage and source identity describe the complete captured set.
        """

        domain = _normalize_capture_domain(capture_domain)

        def admissible(language: str | None) -> bool:
            return domain == REGULAR_TEXT_DOMAIN or language is not None

        if namespace is None:
            values: list[CapturedFile] = []
            for relative in explicit_files:
                budget.check_deadline()
                if not self._glob_matches(relative):
                    raise ExcludedInputError("explicit target is excluded by its glob selection", path=relative)
                suffix = Path(relative).suffix
                language = SUPPORTED_LANGUAGES.get(suffix)
                if not admissible(language):
                    raise UnsupportedFileError("explicit target has no supported source language", path=relative)
                if self.selection.languages is not None and language not in self.selection.languages:
                    raise UnsupportedFileError("explicit target language is outside selection", path=relative)
                captured = self._read_file(relative, budget=budget, source=True, exact=False)
                values.append(captured)
            return tuple(sorted(values, key=lambda item: _source_path_sort_key(item.path)))

        values = []
        for entry in namespace.entries:
            budget.check_deadline()
            if entry.kind != "file" or entry.path == ".":
                continue
            language = entry.language
            if not admissible(language):
                continue
            if self.selection.languages is not None and language not in self.selection.languages:
                continue
            # The captured classification is part of the source population.
            # Structural consumers filter non-text values after this boundary.
            values.append(self._read_file(entry.path, budget=budget, source=True, exact=False))
        return tuple(sorted(values, key=lambda item: _source_path_sort_key(item.path)))

    def capture_sources(
        self,
        *,
        budget: OperationBudget | None = None,
        capture_domain: CaptureDomain = SUPPORTED_SOURCE_DOMAIN,
        horizon: NamespaceHorizon | Mapping[str, Any] | None = None,
    ) -> CapturedManifest:
        """Capture the selected source set, with one selection population."""

        local_budget = budget or OperationBudget()
        domain = _normalize_capture_domain(capture_domain)
        rules_cache: dict[str, tuple[_IgnoreRule, ...]] = {}
        scoped = self._scope_paths(budget=local_budget, rules_cache=rules_cache)
        explicit_files, explicit_dirs, config = scoped
        if (
            horizon is None
            and explicit_files
            and not explicit_dirs
            and len(explicit_files) == len(self.selection.paths)
        ):
            sources = self._capture_selected_sources(
                namespace=None,
                explicit_files=explicit_files,
                budget=local_budget,
                capture_domain=domain,
            )
            return self._manifest(namespace=None, config=config, sources=sources, budget=local_budget)
        namespace, _, _, _ = self._collect_namespace(
            budget=local_budget,
            scoped=scoped,
            rules_cache=rules_cache,
            horizon=horizon,
        )
        sources = self._capture_selected_sources(
            namespace=namespace,
            explicit_files=explicit_files,
            budget=local_budget,
            capture_domain=domain,
        )
        return self._manifest(namespace=namespace, config=config, sources=sources, budget=local_budget)

    capture_source_set = capture_sources

    def capture(
        self,
        *,
        include_namespace: bool = True,
        budget: OperationBudget | None = None,
        capture_domain: CaptureDomain = SUPPORTED_SOURCE_DOMAIN,
        horizon: NamespaceHorizon | Mapping[str, Any] | None = None,
    ) -> RepositoryCapture:
        local_budget = budget or OperationBudget()
        domain = _normalize_capture_domain(capture_domain)
        rules_cache: dict[str, tuple[_IgnoreRule, ...]] = {}
        scoped = self._scope_paths(budget=local_budget, rules_cache=rules_cache)
        explicit_files, explicit_dirs, config = scoped
        if (
            horizon is None
            and explicit_files
            and not explicit_dirs
            and len(explicit_files) == len(self.selection.paths)
        ):
            sources = self._capture_selected_sources(
                namespace=None,
                explicit_files=explicit_files,
                budget=local_budget,
                capture_domain=domain,
            )
            manifest = self._manifest(namespace=None, config=config, sources=sources, budget=local_budget)
            return RepositoryCapture(None, manifest)
        namespace, _, _, _ = self._collect_namespace(
            budget=local_budget,
            scoped=scoped,
            rules_cache=rules_cache,
            horizon=horizon,
        )
        sources = self._capture_selected_sources(
            namespace=namespace,
            explicit_files=explicit_files,
            budget=local_budget,
            capture_domain=domain,
        )
        if not include_namespace:
            namespace = None
        return RepositoryCapture(
            namespace,
            self._manifest(namespace=namespace, config=config, sources=sources, budget=local_budget),
        )

    def source_changed(self, captured: CapturedFile, *, budget: OperationBudget | None = None) -> bool:
        """Observe whether current bytes differ from one captured file.

        This is an explicit freshness check for continuation/guard callers.  It
        reads and hashes the current file once; it never treats mtime as content
        truth and never retries an observable race.
        """

        local_budget = budget or OperationBudget()
        try:
            current = self._read_file(captured.path, budget=local_budget, source=True, exact=False)
        except RepositoryError:
            return True
        return current.digest != captured.digest or current.size != captured.size

    def assert_unchanged(self, captured: CapturedFile, *, budget: OperationBudget | None = None) -> None:
        if self.source_changed(captured, budget=budget):
            raise SourceChangedError("captured source no longer matches current bytes", path=captured.path)

    check_source_changed = source_changed

    def materialize(
        self,
        files: Iterable[CapturedFile] | Mapping[str, bytes],
        *,
        budget: OperationBudget | None = None,
        prefix: str = "xray-capture-",
    ) -> TemporaryMaterialization:
        """Materialize immutable bytes into an operation-owned temporary tree."""

        local_budget = budget or OperationBudget()
        local_budget.check_deadline()
        values: dict[str, bytes] = {}
        if isinstance(files, Mapping):
            for path, content_value in files.items():
                local_budget.check_deadline()
                relative = _normalize_relative(str(path), allow_dot=False)
                content = bytes(content_value)
                values[relative] = content
        else:
            for item in files:
                local_budget.check_deadline()
                values[_normalize_relative(item.path, allow_dot=False)] = item.content
        total = sum(len(content) for content in values.values())
        local_budget.charge_temporary(total)
        temporary: tempfile.TemporaryDirectory[str] | None = None
        try:
            temporary = tempfile.TemporaryDirectory(prefix=prefix)
            root = Path(temporary.name)
            materialized: dict[str, Path] = {}
            for relative, content in sorted(values.items(), key=lambda pair: _source_path_sort_key(pair[0])):
                local_budget.check_deadline()
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as handle:
                    handle.write(content)
                materialized[relative] = target
        except (OSError, ValueError) as exc:
            try:
                temporary.cleanup()  # type: ignore[has-type]
            except Exception:
                pass
            raise MaterializationError("could not materialize captured bytes") from exc
        return TemporaryMaterialization(temporary, root, materialized)

    materialize_captured = materialize


def capture_rule_input(
    root: Root | str | os.PathLike[str],
    input: RuleInput | Mapping[str, Any],
    *,
    budget: OperationBudget | None = None,
    deadline: float | None = None,
) -> CapturedRuleSet:
    """Capture one explicit contained ``RuleInput`` without directory inference."""

    return RepositoryProvider(root).capture_rule_input(input, budget=budget, deadline=deadline)


@dataclass(frozen=True, slots=True)
class _IgnoreRule:
    relative_dir: str
    spec: GitIgnoreSpec
    lines: tuple[str, ...]

    def decision(self, value: str) -> bool | None:
        """Return the final ignore decision for one rule file.

        ``GitIgnoreSpec.match_file`` deliberately hides whether a matching
        pattern was negated.  Replaying each individual pattern with the same
        pathspec parser preserves ordered Git-wildmatch semantics while
        retaining the final negation state.
        """
        decision: bool | None = None
        for line in self.lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            negated = stripped.startswith("!")
            pattern = stripped[1:] if negated else stripped
            try:
                matched = GitIgnoreSpec.from_lines([pattern]).match_file(value)
            except Exception:
                continue
            if matched:
                decision = not negated
        return decision


class TemporaryMaterialization(AbstractContextManager["TemporaryMaterialization"]):
    """Owned temporary tree for one child invocation; never persistent."""

    def __init__(self, temporary: tempfile.TemporaryDirectory[str], root: Path, files: Mapping[str, Path]) -> None:
        self._temporary = temporary
        self.root = root
        self.files: Mapping[str, Path] = MappingProxyType(dict(files))
        self._closed = False

    def __enter__(self) -> TemporaryMaterialization:
        if self._closed:
            raise RuntimeError("temporary materialization is closed")
        return self

    def __exit__(self, _exc_type: Any, exc: Any, _tb: Any) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._temporary.cleanup()
            self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed


# Clear names for callers that prefer the value type without the "Captured"
# prefix.  They are aliases, not mutable compatibility wrappers.
FileCapture: TypeAlias = CapturedFile
NamespaceCapture: TypeAlias = CapturedNamespace
ManifestCapture: TypeAlias = CapturedManifest

__all__ = [
    "CAPTURE_CHUNK_BYTES",
    "DEFAULT_EXCLUSIONS",
    "DEFAULT_EXCLUSIONS_VERSION",
    "DEFAULT_TIMEOUT_SECONDS",
    "HARD_TIMEOUT_SECONDS",
    "MAX_CONFIGURATION_BYTES",
    "MAX_CONFIGURATION_FILES",
    "MAX_CONFIGURATION_FILE_BYTES",
    "MAX_FILE_BYTES",
    "MAX_NAMESPACE_ENTRIES",
    "MAX_NAMESPACE_PATH_BYTES",
    "MAX_RULE_DIRS",
    "MAX_SOURCE_BYTES",
    "MAX_SOURCE_FILES",
    "MAX_TEMPORARY_BYTES",
    "REGULAR_TEXT_DOMAIN",
    "RULE_FILE_SUFFIXES",
    "SUPPORTED_LANGUAGES",
    "SUPPORTED_SOURCE_DOMAIN",
    "YAML_DEPTH_LIMIT",
    "YAML_FILE_BYTES_LIMIT",
    "YAML_NODE_LIMIT",
    "YAML_TOTAL_BYTES_LIMIT",
    "CancellationError",
    "CaptureBudget",
    "CaptureDomain",
    "CaptureLimitError",
    "CapturedFile",
    "CapturedManifest",
    "CapturedNamespace",
    "CapturedNamespaceEntry",
    "CapturedRuleSet",
    "ContainmentError",
    "DeadlineExceededError",
    "ExcludedInputError",
    "FileCapture",
    "InvalidEncodingError",
    "InvalidRuleError",
    "ManifestCapture",
    "MaterializationError",
    "NamespaceCapture",
    "NamespaceLimitError",
    "NotFoundError",
    "OperationBudget",
    "PolicyInput",
    "RepositoryCapture",
    "RepositoryError",
    "RepositoryIOError",
    "RepositoryLimitError",
    "RepositoryProvider",
    "ResourceBudget",
    "RootError",
    "RuleDependencyError",
    "SelectionProvenance",
    "SourceChangedError",
    "SourceProvenance",
    "SymlinkError",
    "TemporaryMaterialization",
    "UnsupportedConfigurationError",
    "UnsupportedFileError",
    "capture_rule_input",
    "normalize_root",
    "normalize_selection",
]
