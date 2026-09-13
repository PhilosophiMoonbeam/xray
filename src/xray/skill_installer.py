"""Safe installation of XRAY's bundled shell-agent skill."""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path
from typing import Any
from uuid import uuid4

CLI_SKILL_NAME = "xray-cli"
CLI_SKILL_FILES = ("SKILL.md", "agents/openai.yaml")
MAX_INSTALL_TARGET_BYTES = 4096

_RENAME_NOREPLACE = 1
_CREATE_MODE = 0o666
_DIRECTORY_MODE = 0o777
_SUPPORTED_DIR_FD = frozenset(os.supports_dir_fd)
_SUPPORTED_FD = frozenset(os.supports_fd)
_ORIGINAL_OPEN = os.open
_ORIGINAL_STAT = os.stat
_ORIGINAL_MKDIR = os.mkdir
_ORIGINAL_UNLINK = os.unlink
_ORIGINAL_RMDIR = os.rmdir
_ORIGINAL_SCANDIR = os.scandir
_PRIVATE_DIRECTORY_MODE = 0o700


@dataclass(frozen=True)
class SkillInstallResult:
    """Machine-readable result for one skill installation."""

    scope: str
    target: str
    changed: bool
    replaced: bool
    files: tuple[str, ...] = CLI_SKILL_FILES

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _NodeRecord:
    """Identity and stable metadata for one descriptor-owned entry."""

    kind: int
    identity: tuple[int, int, int]
    size: int
    mtime_ns: int
    ctime_ns: int

    @property
    def is_directory(self) -> bool:
        return self.kind == stat.S_IFDIR

    def matches(self, current: os.stat_result, *, strict_file: bool = True) -> bool:
        if _identity(current) != self.identity:
            return False
        if strict_file and not self.is_directory:
            return current.st_size == self.size and current.st_mtime_ns == self.mtime_ns
        return True


@dataclass(frozen=True)
class _TreeSnapshot:
    """A complete, no-follow snapshot of a tree owned by this operation."""

    records: dict[str, _NodeRecord]
    strict_files: bool = True

    @property
    def root(self) -> _NodeRecord:
        return self.records[""]


@dataclass(frozen=True)
class _Binding:
    """A visible name bound to one held directory descriptor."""

    parent_fd: int
    name: str
    record: _NodeRecord
    label: str


@dataclass(frozen=True)
class _TargetInspection:
    """The admitted target state and its complete no-follow snapshot."""

    exists: bool
    record: _NodeRecord | None
    snapshot: _TreeSnapshot | None
    matches: bool


def _bundled_files() -> dict[str, bytes]:
    root = resources.files("xray").joinpath("agent_skills").joinpath(CLI_SKILL_NAME)
    bundled: dict[str, bytes] = {}
    for relative in CLI_SKILL_FILES:
        resource = root
        for component in relative.split("/"):
            resource = resource.joinpath(component)
        if not resource.is_file():
            raise RuntimeError(f"bundled skill is incomplete: missing {relative}")
        bundled[relative] = resource.read_bytes()
    return bundled


def _identity(value: os.stat_result) -> tuple[int, int, int]:
    return (value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode))


def _record(value: os.stat_result) -> _NodeRecord:
    return _NodeRecord(
        kind=stat.S_IFMT(value.st_mode),
        identity=_identity(value),
        size=value.st_size,
        mtime_ns=value.st_mtime_ns,
        ctime_ns=value.st_ctime_ns,
    )


def _stamp(value: os.stat_result) -> tuple[tuple[int, int, int], int, int, int]:
    return (_identity(value), value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _existing_directory(path: Path, label: str) -> Path:
    """Validate a caller-selected existing directory before descriptor pinning."""
    try:
        initial = os.lstat(path)
    except (OSError, ValueError) as exc:
        raise ValueError(f"{label} does not exist: {path}") from exc
    if stat.S_ISLNK(initial.st_mode):
        raise ValueError(f"{label} must not be a symlink: {path}")
    if not stat.S_ISDIR(initial.st_mode):
        raise ValueError(f"{label} is not a directory: {path}")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"{label} cannot be resolved: {path}") from exc
    try:
        current = os.lstat(path)
    except (OSError, ValueError) as exc:
        raise OSError(errno.EAGAIN, f"{label} changed while being selected: {path}") from exc
    if stat.S_ISLNK(current.st_mode):
        raise ValueError(f"{label} must not be a symlink: {path}")
    if _identity(initial) != _identity(current):
        raise OSError(errno.EAGAIN, f"{label} changed while being selected: {path}")
    return resolved


def _required_flag(name: str) -> int:
    value = getattr(os, name, None)
    if not isinstance(value, int) or value == 0:
        raise OSError(errno.ENOTSUP, f"safe skill installation requires {name}")
    return value


def _directory_flags() -> int:
    return os.O_RDONLY | _required_flag("O_DIRECTORY") | _required_flag("O_NOFOLLOW") | _required_flag("O_CLOEXEC")


def _read_flags() -> int:
    return os.O_RDONLY | _required_flag("O_NOFOLLOW") | _required_flag("O_CLOEXEC") | _required_flag("O_NONBLOCK")


def _load_renameat2() -> Any:
    """Load the Linux no-replace rename primitive without a syscall table."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
    except (AttributeError, OSError) as exc:
        raise OSError(errno.ENOSYS, "Linux renameat2 is unavailable") from exc
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    return renameat2


def _preflight_primitives() -> None:
    """Fail closed before creating either destination parent."""
    if sys.platform != "linux":
        raise OSError(errno.ENOTSUP, "descriptor-relative skill installation requires Linux")
    if not all(
        function in _SUPPORTED_DIR_FD
        for function in (
            _ORIGINAL_OPEN,
            _ORIGINAL_STAT,
            _ORIGINAL_MKDIR,
            _ORIGINAL_UNLINK,
            _ORIGINAL_RMDIR,
        )
    ):
        raise OSError(errno.ENOTSUP, "descriptor-relative filesystem APIs are unavailable")
    if _ORIGINAL_SCANDIR not in _SUPPORTED_FD:
        raise OSError(errno.ENOTSUP, "descriptor-relative directory scanning is unavailable")
    if not all(callable(getattr(os, name, None)) for name in ("open", "stat", "mkdir", "unlink", "rmdir", "scandir")):
        raise OSError(errno.ENOTSUP, "descriptor-relative filesystem APIs are unavailable")
    if not callable(_load_renameat2()):
        raise OSError(errno.ENOSYS, "Linux renameat2 is unavailable")


def _basename(name: str) -> bytes:
    if not isinstance(name, str) or not name or name in {".", ".."} or "/" in name or "\x00" in name:
        raise ValueError(f"unsafe descriptor-relative name: {name!r}")
    return os.fsencode(name)


def _rename_noreplace(
    source_fd: int,
    source_name: str,
    destination_fd: int,
    destination_name: str,
) -> None:
    """Rename two basenames without ever replacing an occupied destination."""
    source = _basename(source_name)
    destination = _basename(destination_name)
    renameat2 = _load_renameat2()
    result = renameat2(
        source_fd,
        source,
        destination_fd,
        destination,
        _RENAME_NOREPLACE,
    )
    if result != 0:
        error_number = ctypes.get_errno() or errno.EIO
        raise OSError(
            error_number,
            os.strerror(error_number),
            source_name,
            destination_name,
        )


def _stat_entry(parent_fd: int, name: str) -> os.stat_result:
    _basename(name)
    return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)


def _drift(label: str) -> OSError:
    return OSError(errno.EAGAIN, f"{label} changed during skill installation")


def _open_directory(
    parent_fd: int,
    name: str,
    label: str,
    *,
    before: os.stat_result | None = None,
    static: bool = False,
) -> tuple[int, _NodeRecord]:
    if before is None:
        before = _stat_entry(parent_fd, name)
    if stat.S_ISLNK(before.st_mode):
        if static:
            raise ValueError(f"skill install path must not contain symlinks: {label}")
        raise _drift(label)
    if not stat.S_ISDIR(before.st_mode):
        if static:
            raise ValueError(f"skill install path component is not a directory: {label}")
        raise _drift(label)
    descriptor = os.open(name, _directory_flags(), dir_fd=parent_fd)
    try:
        after = os.fstat(descriptor)
        if _identity(after) != _identity(before) or not stat.S_ISDIR(after.st_mode):
            raise _drift(label)
        return descriptor, _record(after)
    except BaseException:
        os.close(descriptor)
        raise


def _pin_root(root: Path) -> tuple[list[int], list[_Binding]]:
    """Open every component of a resolved absolute root with no-follow flags."""
    if not root.is_absolute() or root.anchor != "/":
        raise OSError(errno.EINVAL, f"resolved skill root is not an absolute Linux path: {root}")
    descriptors: list[int] = []
    bindings: list[_Binding] = []
    try:
        current = os.open("/", _directory_flags())
        descriptors.append(current)
        for component in root.parts[1:]:
            before = _stat_entry(current, component)
            child, child_record = _open_directory(
                current,
                component,
                str(root),
                before=before,
                static=False,
            )
            bindings.append(_Binding(current, component, child_record, str(root)))
            descriptors.append(child)
            current = child
        return descriptors, bindings
    except BaseException:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise


def _validate_bindings(bindings: list[_Binding]) -> None:
    for binding in bindings:
        try:
            current = _stat_entry(binding.parent_fd, binding.name)
        except OSError as exc:
            raise _drift(binding.label) from exc
        if not binding.record.matches(current, strict_file=False):
            raise _drift(binding.label)


def _open_or_create_directory(
    parent_fd: int,
    name: str,
    label: str,
) -> tuple[int, _NodeRecord, _Binding]:
    """Admit an existing directory or create one, then pin its identity."""
    try:
        before = _stat_entry(parent_fd, name)
    except FileNotFoundError:
        try:
            os.mkdir(name, _DIRECTORY_MODE, dir_fd=parent_fd)
        except FileExistsError:
            try:
                raced = _stat_entry(parent_fd, name)
            except OSError as exc:
                raise _drift(label) from exc
            child, child_record = _open_directory(
                parent_fd,
                name,
                label,
                before=raced,
                static=False,
            )
        else:
            created = _stat_entry(parent_fd, name)
            child, child_record = _open_directory(
                parent_fd,
                name,
                label,
                before=created,
                static=False,
            )
    else:
        if stat.S_ISLNK(before.st_mode):
            raise ValueError(f"skill install path must not contain symlinks: {label}")
        if not stat.S_ISDIR(before.st_mode):
            raise ValueError(f"skill install path component is not a directory: {label}")
        child, child_record = _open_directory(
            parent_fd,
            name,
            label,
            before=before,
            static=False,
        )
    return child, child_record, _Binding(parent_fd, name, child_record, label)


def _join_relative(prefix: str, name: str) -> str:
    return name if not prefix else f"{prefix}/{name}"


def _file_matches(
    parent_fd: int,
    name: str,
    before: os.stat_result,
    expected: bytes,
    label: str,
) -> bool:
    """Read no more than the expected payload plus one byte."""
    if before.st_size > len(expected) + 1:
        try:
            after = _stat_entry(parent_fd, name)
        except OSError as exc:
            raise _drift(label) from exc
        if _stamp(before) != _stamp(after):
            raise _drift(label)
        return False
    descriptor = os.open(name, _read_flags(), dir_fd=parent_fd)
    try:
        opened = os.fstat(descriptor)
        if _identity(opened) != _identity(before) or not stat.S_ISREG(opened.st_mode):
            raise _drift(label)
        remaining = len(expected) + 1
        received = bytearray()
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            received.extend(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        if _stamp(opened) != _stamp(after):
            raise _drift(label)
        return bytes(received) == expected
    finally:
        os.close(descriptor)


def _inspect_directory_fd(
    root_fd: int,
    bundled: dict[str, bytes],
    *,
    label: str,
    symlink_is_value_error: bool,
) -> tuple[_TreeSnapshot, bool]:
    """Stream a directory tree entirely through held descriptors."""
    initial = os.fstat(root_fd)
    if not stat.S_ISDIR(initial.st_mode):
        raise _drift(label)
    records: dict[str, _NodeRecord] = {"": _record(initial)}
    seen_files: set[str] = set()
    seen_directories: set[str] = set()
    has_special = False

    def walk(descriptor: int, prefix: str) -> None:
        nonlocal has_special
        before_directory = os.fstat(descriptor)
        if not stat.S_ISDIR(before_directory.st_mode):
            raise _drift(label)
        with os.scandir(descriptor) as entries:
            for entry in entries:
                name = entry.name
                _basename(name)
                relative = _join_relative(prefix, name)
                try:
                    before = _stat_entry(descriptor, name)
                except OSError as exc:
                    raise _drift(relative) from exc
                if stat.S_ISLNK(before.st_mode):
                    if symlink_is_value_error:
                        raise ValueError(f"installed skill must not contain symlinks: {relative}")
                    raise _drift(relative)
                current_record = _record(before)
                records[relative] = current_record
                if stat.S_ISDIR(before.st_mode):
                    seen_directories.add(relative)
                    child, _ = _open_directory(
                        descriptor,
                        name,
                        relative,
                        before=before,
                        static=False,
                    )
                    try:
                        walk(child, relative)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(before.st_mode):
                    seen_files.add(relative)
                    expected = bundled.get(relative)
                    if expected is not None and not _file_matches(
                        descriptor,
                        name,
                        before,
                        expected,
                        relative,
                    ):
                        has_special = True
                else:
                    # Never open a FIFO, socket, device, or other special file.
                    has_special = True
        after_directory = os.fstat(descriptor)
        if _stamp(before_directory) != _stamp(after_directory):
            raise _drift(label)

    walk(root_fd, "")
    allowed_directories = {relative.rsplit("/", 1)[0] for relative in bundled if "/" in relative}
    matches = not has_special and seen_files == set(bundled) and seen_directories == allowed_directories
    return _TreeSnapshot(records), matches


def _inspect_target(
    parent_fd: int,
    name: str,
    bundled: dict[str, bytes],
    *,
    symlink_is_value_error: bool = True,
) -> _TargetInspection:
    try:
        before = _stat_entry(parent_fd, name)
    except FileNotFoundError:
        return _TargetInspection(False, None, None, False)
    if stat.S_ISLNK(before.st_mode):
        if symlink_is_value_error:
            raise ValueError(f"installed skill must not contain symlinks: {name}")
        raise _drift(name)
    if not stat.S_ISDIR(before.st_mode):
        raise ValueError(f"skill target is not a directory: {name}")
    descriptor, target_record = _open_directory(
        parent_fd,
        name,
        name,
        before=before,
        static=False,
    )
    try:
        snapshot, matches = _inspect_directory_fd(
            descriptor,
            bundled,
            label=name,
            symlink_is_value_error=symlink_is_value_error,
        )
    finally:
        os.close(descriptor)
    return _TargetInspection(True, target_record, snapshot, matches)


def _assert_entry(
    parent_fd: int,
    name: str,
    expected: _NodeRecord | None,
    label: str,
    *,
    allow_absent: bool = False,
    static_symlink: bool = False,
    allow_symlink: bool = False,
) -> os.stat_result | None:
    try:
        current = _stat_entry(parent_fd, name)
    except FileNotFoundError:
        if allow_absent:
            return None
        raise _drift(label)
    except OSError as exc:
        raise _drift(label) from exc
    if stat.S_ISLNK(current.st_mode) and not allow_symlink:
        if static_symlink:
            raise ValueError(f"installed skill must not contain symlinks: {label}")
        raise _drift(label)
    if expected is not None and not expected.matches(current, strict_file=False):
        raise _drift(label)
    return current


def _assert_absent(parent_fd: int, name: str, label: str) -> None:
    try:
        current = _stat_entry(parent_fd, name)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise _drift(label) from exc
    if stat.S_ISLNK(current.st_mode):
        raise _drift(label)
    raise OSError(errno.EEXIST, f"{label} is occupied")


def _reserve_name(parent_fd: int, prefix: str) -> str:
    for _ in range(128):
        name = f"{prefix}{uuid4().hex}"
        _basename(name)
        try:
            _stat_entry(parent_fd, name)
        except FileNotFoundError:
            return name
        except OSError as exc:
            raise _drift(name) from exc
    raise OSError(errno.EEXIST, f"could not reserve a private {prefix} name")


def _write_all(descriptor: int, content: bytes) -> None:
    view = memoryview(content)
    offset = 0
    while offset < len(view):
        written = os.write(descriptor, view[offset:])
        if written <= 0:
            raise OSError(errno.EIO, "skill staging write made no progress")
        offset += written


def _partial_snapshot(root_record: _NodeRecord, records: dict[str, _NodeRecord]) -> _TreeSnapshot:
    complete = dict(records)
    complete.setdefault("", root_record)
    return _TreeSnapshot(complete, strict_files=False)


def _create_workspace(skills_fd: int) -> tuple[str, int, _NodeRecord]:
    for _ in range(128):
        name = f".xray-skill-stage-{uuid4().hex}"
        try:
            os.mkdir(name, _PRIVATE_DIRECTORY_MODE, dir_fd=skills_fd)
        except FileExistsError:
            continue
        descriptor: int | None = None
        try:
            before = _stat_entry(skills_fd, name)
            descriptor, workspace_record = _open_directory(
                skills_fd,
                name,
                name,
                before=before,
                static=False,
            )
            return name, descriptor, workspace_record
        except BaseException as exc:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            try:
                current = _stat_entry(skills_fd, name)
            except OSError:
                current = None
            if current is not None and stat.S_ISDIR(current.st_mode):
                try:
                    _cleanup_tree(
                        skills_fd,
                        name,
                        _TreeSnapshot({"": _record(current)}),
                    )
                except Exception as cleanup_error:
                    raise OSError(
                        errno.EIO,
                        "skill staging failed and private workspace cleanup failed",
                    ) from cleanup_error
            raise exc
    raise OSError(errno.EEXIST, "could not create a private skill workspace")


def _create_stage(
    workspace_fd: int,
    bundled: dict[str, bytes],
) -> tuple[int, _NodeRecord, _TreeSnapshot]:
    stage_name = "stage"
    stage_fd: int | None = None
    agent_fd: int | None = None
    records: dict[str, _NodeRecord] = {}
    try:
        os.mkdir(stage_name, _PRIVATE_DIRECTORY_MODE, dir_fd=workspace_fd)
        stage_stat = _stat_entry(workspace_fd, stage_name)
        stage_fd, stage_record = _open_directory(
            workspace_fd,
            stage_name,
            stage_name,
            before=stage_stat,
            static=False,
        )
        records[""] = stage_record
        os.mkdir("agents", _DIRECTORY_MODE, dir_fd=stage_fd)
        agents_stat = _stat_entry(stage_fd, "agents")
        agent_fd, agent_record = _open_directory(
            stage_fd,
            "agents",
            "agents",
            before=agents_stat,
            static=False,
        )
        records["agents"] = agent_record

        for relative, content in bundled.items():
            components = relative.split("/")
            if len(components) == 1:
                file_parent = stage_fd
                record_name = relative
            elif components == ["agents", "openai.yaml"]:
                file_parent = agent_fd
                record_name = relative
            else:
                raise RuntimeError(f"unsupported bundled skill path: {relative}")
            file_fd: int | None = None
            try:
                file_fd = os.open(
                    components[-1],
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | _required_flag("O_NOFOLLOW") | _required_flag("O_CLOEXEC"),
                    _CREATE_MODE,
                    dir_fd=file_parent,
                )
                file_stat = os.fstat(file_fd)
                if not stat.S_ISREG(file_stat.st_mode):
                    raise _drift(record_name)
                records[record_name] = _record(file_stat)
                _write_all(file_fd, content)
                after_file = os.fstat(file_fd)
                if _identity(after_file) != _identity(file_stat):
                    raise _drift(record_name)
            finally:
                if file_fd is not None:
                    os.close(file_fd)
            _assert_entry(
                file_parent,
                components[-1],
                records[record_name],
                record_name,
            )

        snapshot, matches = _inspect_directory_fd(
            stage_fd,
            bundled,
            label=stage_name,
            symlink_is_value_error=False,
        )
        if not matches:
            raise OSError(errno.EIO, "private staged skill does not match its bundle")
        if agent_fd is not None:
            os.close(agent_fd)
            agent_fd = None
        return stage_fd, stage_record, snapshot
    except BaseException as exc:
        if agent_fd is not None:
            try:
                os.close(agent_fd)
            except OSError:
                pass
        if stage_fd is not None:
            try:
                os.close(stage_fd)
            except OSError:
                pass
        root_record = records.get("")
        if root_record is not None:
            try:
                _cleanup_tree(
                    workspace_fd,
                    stage_name,
                    _partial_snapshot(root_record, records),
                )
            except Exception as cleanup_error:
                raise OSError(
                    errno.EIO,
                    "skill staging failed and private stage cleanup failed",
                ) from cleanup_error
        raise exc


def _capture_tree(parent_fd: int, name: str) -> _TreeSnapshot:
    before = _stat_entry(parent_fd, name)
    if stat.S_ISLNK(before.st_mode):
        raise _drift(name)
    if not stat.S_ISDIR(before.st_mode):
        return _TreeSnapshot({"": _record(before)})
    descriptor, _ = _open_directory(parent_fd, name, name, before=before, static=False)
    try:
        snapshot, _ = _inspect_directory_fd(
            descriptor,
            {},
            label=name,
            symlink_is_value_error=False,
        )
        return snapshot
    finally:
        os.close(descriptor)


def _move_owned_entry(
    parent_fd: int,
    name: str,
    expected: _NodeRecord,
    label: str,
    *,
    strict_file: bool,
) -> str:
    """Move an admitted entry to a private name before deleting it."""
    current = _stat_entry(parent_fd, name)
    if not expected.matches(current, strict_file=strict_file):
        raise _drift(label)
    trash_name = _reserve_name(parent_fd, ".cleanup-")
    _rename_noreplace(parent_fd, name, parent_fd, trash_name)
    moved = _stat_entry(parent_fd, trash_name)
    if not expected.matches(moved, strict_file=strict_file):
        try:
            _assert_absent(parent_fd, name, label)
            _rename_noreplace(parent_fd, trash_name, parent_fd, name)
        except BaseException as restore_error:
            raise OSError(
                errno.EIO,
                f"{label} changed and private cleanup recovery failed",
            ) from restore_error
        raise _drift(label)
    try:
        _assert_absent(parent_fd, name, label)
    except BaseException:
        # Keep the moved object private when a third value occupied its name.
        raise
    return trash_name


def _remove_private_entry(
    parent_fd: int,
    name: str,
    expected: _NodeRecord,
    label: str,
    *,
    strict_file: bool,
) -> None:
    current = _stat_entry(parent_fd, name)
    if not expected.matches(current, strict_file=strict_file):
        raise _drift(label)
    if expected.is_directory:
        os.rmdir(name, dir_fd=parent_fd)
    else:
        os.unlink(name, dir_fd=parent_fd)


def _cleanup_directory_fd(
    descriptor: int,
    prefix: str,
    snapshot: _TreeSnapshot,
) -> None:
    expected_children = {
        relative: record
        for relative, record in snapshot.records.items()
        if relative and (relative.rsplit("/", 1)[0] if "/" in relative else "") == prefix
    }
    for relative in sorted(expected_children):
        name = relative.rsplit("/", 1)[-1]
        expected = expected_children[relative]
        if expected.is_directory:
            current = _stat_entry(descriptor, name)
            if not expected.matches(current, strict_file=False):
                raise _drift(relative)
            child, _ = _open_directory(
                descriptor,
                name,
                relative,
                before=current,
                static=False,
            )
            try:
                _cleanup_directory_fd(child, relative, snapshot)
            finally:
                os.close(child)
            trash_name = _move_owned_entry(
                descriptor,
                name,
                expected,
                relative,
                strict_file=False,
            )
            _remove_private_entry(
                descriptor,
                trash_name,
                expected,
                relative,
                strict_file=False,
            )
        else:
            trash_name = _move_owned_entry(
                descriptor,
                name,
                expected,
                relative,
                strict_file=snapshot.strict_files,
            )
            _remove_private_entry(
                descriptor,
                trash_name,
                expected,
                relative,
                strict_file=snapshot.strict_files,
            )
    with os.scandir(descriptor) as entries:
        try:
            unexpected = next(entries)
        except StopIteration:
            return
        raise OSError(errno.ENOTEMPTY, f"private cleanup found an unexpected entry: {unexpected.name}")


def _cleanup_tree(
    parent_fd: int,
    name: str,
    snapshot: _TreeSnapshot | None = None,
) -> None:
    """Remove only the identities recorded for one descriptor-owned tree."""
    if snapshot is None:
        snapshot = _capture_tree(parent_fd, name)
    root = snapshot.root
    current = _stat_entry(parent_fd, name)
    if not root.matches(
        current,
        strict_file=not root.is_directory and snapshot.strict_files,
    ):
        raise _drift(name)
    if root.is_directory:
        descriptor, _ = _open_directory(
            parent_fd,
            name,
            name,
            before=current,
            static=False,
        )
        try:
            _cleanup_directory_fd(descriptor, "", snapshot)
        finally:
            os.close(descriptor)
        trash_name = _move_owned_entry(
            parent_fd,
            name,
            root,
            name,
            strict_file=False,
        )
        _remove_private_entry(
            parent_fd,
            trash_name,
            root,
            name,
            strict_file=False,
        )
    else:
        trash_name = _move_owned_entry(
            parent_fd,
            name,
            root,
            name,
            strict_file=snapshot.strict_files,
        )
        _remove_private_entry(
            parent_fd,
            trash_name,
            root,
            name,
            strict_file=snapshot.strict_files,
        )


def _empty_directory_snapshot(record: _NodeRecord) -> _TreeSnapshot:
    return _TreeSnapshot({"": record})


def _verify_published_target(
    skills_fd: int,
    target_name: str,
    bundled: dict[str, bytes],
    stage_record: _NodeRecord,
) -> _TreeSnapshot:
    current = _assert_entry(skills_fd, target_name, stage_record, target_name)
    if current is None or not stat.S_ISDIR(current.st_mode):
        raise _drift(target_name)
    descriptor, _ = _open_directory(
        skills_fd,
        target_name,
        target_name,
        before=current,
        static=False,
    )
    try:
        snapshot, matches = _inspect_directory_fd(
            descriptor,
            bundled,
            label=target_name,
            symlink_is_value_error=False,
        )
    finally:
        os.close(descriptor)
    if not matches:
        raise _drift(target_name)
    return snapshot


def _as_recovery_error(context: str, error: BaseException) -> OSError:
    if isinstance(error, OSError):
        return OSError(error.errno or errno.EIO, f"{context}: {error}")
    return OSError(errno.EIO, f"{context}: {error}")


def _rollback_install(
    *,
    bindings: list[_Binding],
    workspace_binding: _Binding,
    skills_fd: int,
    workspace_fd: int,
    workspace_name: str,
    workspace_record: _NodeRecord,
    target_name: str,
    stage_snapshot: _TreeSnapshot,
    stage_record: _NodeRecord,
    previous_name: str | None,
    previous_record: _NodeRecord | None,
    moved_old: bool,
    published: bool,
    bundled: dict[str, bytes],
) -> list[BaseException]:
    errors: list[BaseException] = []
    try:
        _validate_bindings([*bindings, workspace_binding])
    except BaseException as exc:
        return [_as_recovery_error("visible skill parents changed; recovery was not attempted", exc)]

    abort_name: str | None = None
    abort_cleaned = False
    restored = False

    if published:
        try:
            _verify_published_target(skills_fd, target_name, bundled, stage_record)
            abort_name = _reserve_name(workspace_fd, ".abort-")
            _rename_noreplace(skills_fd, target_name, workspace_fd, abort_name)
            _assert_entry(workspace_fd, abort_name, stage_record, abort_name)
        except BaseException as exc:
            errors.append(_as_recovery_error("installed stage could not be moved aside for recovery", exc))

    if (
        moved_old
        and previous_name is not None
        and previous_record is not None
        and (not published or abort_name is not None)
    ):
        try:
            _validate_bindings([*bindings, workspace_binding])
            _assert_entry(
                workspace_fd,
                previous_name,
                previous_record,
                previous_name,
                allow_symlink=True,
            )
            _assert_absent(skills_fd, target_name, target_name)
            _rename_noreplace(workspace_fd, previous_name, skills_fd, target_name)
            _assert_entry(
                skills_fd,
                target_name,
                previous_record,
                target_name,
                allow_symlink=True,
            )
            restored = True
        except BaseException as exc:
            errors.append(_as_recovery_error("the previous skill could not be restored", exc))

    if published:
        if abort_name is not None and not errors:
            try:
                _cleanup_tree(workspace_fd, abort_name, stage_snapshot)
                abort_cleaned = True
            except BaseException as exc:
                errors.append(_as_recovery_error("the staged skill could not be cleaned", exc))
    else:
        try:
            _cleanup_tree(workspace_fd, "stage", stage_snapshot)
            abort_cleaned = True
        except BaseException as exc:
            errors.append(_as_recovery_error("the staged skill could not be cleaned", exc))

    if (not moved_old or restored) and abort_cleaned and not errors:
        try:
            _validate_bindings([*bindings, workspace_binding])
            _cleanup_tree(
                skills_fd,
                workspace_name,
                _empty_directory_snapshot(workspace_record),
            )
        except BaseException as exc:
            errors.append(_as_recovery_error("the private skill workspace could not be removed", exc))
    return errors


def install_cli_skill(
    *,
    project_root: str | Path | None = None,
    home: str | Path | None = None,
    force: bool = False,
) -> SkillInstallResult:
    """Install the bundled CLI skill user-wide or below one project root."""
    if project_root is None:
        try:
            selected = Path.home() if home is None else Path(home).expanduser()
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError(f"invalid user home: {home}") from exc
        root = _existing_directory(selected, "user home")
        scope = "user"
    else:
        if home is not None:
            raise ValueError("home cannot be combined with project_root")
        try:
            selected = Path(project_root).expanduser()
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError(f"invalid project root: {project_root}") from exc
        root = _existing_directory(selected, "project root")
        scope = "project"

    target = root / ".agents" / "skills" / CLI_SKILL_NAME
    target_text = target.as_posix()
    try:
        target_bytes = target_text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"skill install target is not valid UTF-8: {target_text!r}") from exc
    if "\x00" in target_text or len(target_bytes) > MAX_INSTALL_TARGET_BYTES:
        raise ValueError(f"skill install target exceeds the {MAX_INSTALL_TARGET_BYTES}-byte UTF-8 path bound")

    _preflight_primitives()
    bundled = _bundled_files()
    root_descriptors, bindings = _pin_root(root)
    agents_fd: int | None = None
    skills_fd: int | None = None
    workspace_fd: int | None = None
    stage_fd: int | None = None
    try:
        root_fd = root_descriptors[-1]
        agents_fd, _, agents_binding = _open_or_create_directory(
            root_fd,
            ".agents",
            f"{root}/.agents",
        )
        bindings.append(agents_binding)
        skills_fd, _, skills_binding = _open_or_create_directory(
            agents_fd,
            "skills",
            f"{root}/.agents/skills",
        )
        bindings.append(skills_binding)

        initial = _inspect_target(skills_fd, CLI_SKILL_NAME, bundled)
        if initial.exists and initial.matches:
            _validate_bindings(bindings)
            stable = _inspect_target(
                skills_fd,
                CLI_SKILL_NAME,
                bundled,
                symlink_is_value_error=False,
            )
            if (
                not stable.matches
                or stable.record is None
                or initial.record is None
                or stable.record.identity != initial.record.identity
            ):
                raise _drift(str(target))
            _validate_bindings(bindings)
            _assert_entry(skills_fd, CLI_SKILL_NAME, stable.record, str(target))
            return SkillInstallResult(
                scope=scope,
                target=target_text,
                changed=False,
                replaced=False,
            )
        if initial.exists and not force:
            raise ValueError(
                f"skill target differs from the bundled skill; review it or rerun with --force: {target_text}"
            )

        replaced = initial.exists
        _validate_bindings(bindings)
        _assert_entry(
            skills_fd,
            CLI_SKILL_NAME,
            initial.record if replaced else None,
            str(target),
            allow_absent=not replaced,
        )

        workspace_name, workspace_fd, workspace_record = _create_workspace(skills_fd)
        workspace_binding = _Binding(
            skills_fd,
            workspace_name,
            workspace_record,
            f"{root}/.agents/skills/{workspace_name}",
        )
        try:
            stage_fd, stage_record, stage_snapshot = _create_stage(workspace_fd, bundled)
        except BaseException:
            try:
                _validate_bindings([*bindings, workspace_binding])
                _cleanup_tree(
                    skills_fd,
                    workspace_name,
                    _empty_directory_snapshot(workspace_record),
                )
            except BaseException as cleanup_error:
                raise OSError(
                    errno.EIO,
                    "skill staging failed; private workspace cleanup did not complete",
                ) from cleanup_error
            raise

        previous_name: str | None = None
        previous_record: _NodeRecord | None = None
        moved_old = False
        published = False
        committed = False
        try:
            _validate_bindings([*bindings, workspace_binding])
            if replaced:
                if initial.record is None:
                    raise _drift(str(target))
                previous_name = _reserve_name(workspace_fd, "previous-")
                _assert_entry(skills_fd, CLI_SKILL_NAME, initial.record, str(target))
                _rename_noreplace(
                    skills_fd,
                    CLI_SKILL_NAME,
                    workspace_fd,
                    previous_name,
                )
                moved_old = True
                previous_current = _stat_entry(workspace_fd, previous_name)
                previous_record = _record(previous_current)
                if previous_record.identity != initial.record.identity:
                    raise _drift(str(target))

            _validate_bindings([*bindings, workspace_binding])
            _assert_entry(workspace_fd, "stage", stage_record, "private stage")
            _assert_absent(skills_fd, CLI_SKILL_NAME, str(target))
            _rename_noreplace(
                workspace_fd,
                "stage",
                skills_fd,
                CLI_SKILL_NAME,
            )
            published = True
            _verify_published_target(skills_fd, CLI_SKILL_NAME, bundled, stage_record)
            _validate_bindings(bindings)
            committed = True
        except BaseException as failure:
            if committed:
                raise
            recovery_errors = _rollback_install(
                bindings=bindings,
                workspace_binding=workspace_binding,
                skills_fd=skills_fd,
                workspace_fd=workspace_fd,
                workspace_name=workspace_name,
                workspace_record=workspace_record,
                target_name=CLI_SKILL_NAME,
                stage_snapshot=stage_snapshot,
                stage_record=stage_record,
                previous_name=previous_name,
                previous_record=previous_record,
                moved_old=moved_old,
                published=published,
                bundled=bundled,
            )
            if recovery_errors:
                raise OSError(
                    errno.EIO,
                    "skill installation failed; restoration or private cleanup did not complete",
                ) from failure
            if isinstance(failure, OSError):
                outcome = "previous skill restored" if moved_old else "destination unchanged"
                raise OSError(
                    failure.errno or errno.EIO,
                    f"skill installation failed; {outcome}",
                ) from failure
            raise

        try:
            _validate_bindings(bindings)
            if previous_name is not None and previous_record is not None:
                _cleanup_tree(workspace_fd, previous_name, initial.snapshot)
            _validate_bindings(bindings)
            _cleanup_tree(
                skills_fd,
                workspace_name,
                _empty_directory_snapshot(workspace_record),
            )
            _validate_bindings(bindings)
            _verify_published_target(skills_fd, CLI_SKILL_NAME, bundled, stage_record)
            _validate_bindings(bindings)
        except BaseException as cleanup_failure:
            raise OSError(
                errno.EIO,
                "skill installed but private cleanup failed; inspect the recovery workspace",
            ) from cleanup_failure

        return SkillInstallResult(
            scope=scope,
            target=target_text,
            changed=True,
            replaced=replaced,
        )
    finally:
        descriptors_to_close = [stage_fd, workspace_fd, skills_fd, agents_fd, *root_descriptors]
        seen: set[int] = set()
        for descriptor in descriptors_to_close:
            if descriptor is None or descriptor in seen:
                continue
            seen.add(descriptor)
            try:
                os.close(descriptor)
            except OSError:
                pass
