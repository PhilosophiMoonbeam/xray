"""Optional bounded cache for serialized derived repository artifacts.

The cache stores only caller-owned derived bytes.  It has no knowledge of the
serializer, source files, plans, Git, or any other repository state.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import sys
import tempfile
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Final

from xray.core.repository import OperationBudget
from xray.presentation import canonical_bytes

CACHE_KEY_SCHEMA: Final[str] = "xray.cache.v1"
CACHE_DISK_LIMIT_BYTES: Final[int] = 512 * 1024 * 1024
CACHE_ARTIFACT_LIMIT_BYTES: Final[int] = 16 * 1024 * 1024
CACHE_PAYLOAD_LIMIT_BYTES: Final[int] = 64 * 1024 * 1024
CACHE_ROOT_HANDLE_LIMIT: Final[int] = 32
CACHE_MAX_AGE_SECONDS: Final[int] = 30 * 24 * 60 * 60

_CACHE_FILE_SUFFIX: Final[str] = ".json"
_CACHE_MAGIC: Final[bytes] = b"XRAY-DERIVED-CACHE-1\n"
_CACHE_HEADER_LIMIT: Final[int] = 1024
_CACHE_SCAN_LIMIT: Final[int] = 100_000
_READ_CHUNK_BYTES: Final[int] = 64 * 1024
_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")


class CacheError(RuntimeError):
    """Base typed cache failure."""


class CacheSafetyError(CacheError):
    """A cache path is not private, owned, and free of symlinks."""


@dataclass(frozen=True, slots=True)
class CacheLimits:
    """Cache ceilings; small values are useful for focused tests."""

    disk_limit_bytes: int = CACHE_DISK_LIMIT_BYTES
    artifact_limit_bytes: int = CACHE_ARTIFACT_LIMIT_BYTES
    payload_limit_bytes: int = CACHE_PAYLOAD_LIMIT_BYTES
    root_handle_limit: int = CACHE_ROOT_HANDLE_LIMIT
    max_age_seconds: float = CACHE_MAX_AGE_SECONDS

    def __post_init__(self) -> None:
        _check_positive(self.disk_limit_bytes, "disk_limit_bytes")
        _check_positive(self.artifact_limit_bytes, "artifact_limit_bytes")
        _check_positive(self.payload_limit_bytes, "payload_limit_bytes")
        _check_positive(self.root_handle_limit, "root_handle_limit")
        if (
            isinstance(self.max_age_seconds, bool)
            or not isinstance(self.max_age_seconds, (int, float))
            or not math.isfinite(float(self.max_age_seconds))
            or self.max_age_seconds < 0
        ):
            raise ValueError("max_age_seconds must be a non-negative finite number")


@dataclass(frozen=True, slots=True)
class _Entry:
    key: str
    path: Path
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class _MemoryEntry:
    payload: bytes
    fingerprint: tuple[int, int, int, int, int]


@dataclass(slots=True)
class _RootHandle:
    namespace: Path
    entries: OrderedDict[str, _MemoryEntry] = field(default_factory=OrderedDict)
    payload_bytes: int = 0


class _CorruptEntry(Exception):
    """Internal marker carrying the safe stat used for race-free cleanup."""

    def __init__(self, observed: os.stat_result | None) -> None:
        super().__init__("corrupt cache entry")
        self.observed = observed


class _MemoryManager:
    """Bounded process-local LRU state shared by cache instances."""

    def __init__(self) -> None:
        self.handles: OrderedDict[str, _RootHandle] = OrderedDict()
        self.lock = threading.RLock()

    def acquire(self, namespace: Path, limit: int) -> _RootHandle:
        identity = str(namespace)
        handle = self.handles.get(identity)
        if handle is None:
            handle = _RootHandle(namespace=namespace)
            self.handles[identity] = handle
        else:
            self.handles.move_to_end(identity)
        while len(self.handles) > limit:
            _, removed = self.handles.popitem(last=False)
            removed.entries.clear()
            removed.payload_bytes = 0
        return handle

    def lookup(self, handle: _RootHandle, key: str) -> _MemoryEntry | None:
        entry = handle.entries.get(key)
        if entry is not None:
            handle.entries.move_to_end(key)
        return entry

    def remove(self, namespace: Path, key: str) -> None:
        handle = self.handles.get(str(namespace))
        if handle is None:
            return
        entry = handle.entries.pop(key, None)
        if entry is not None:
            handle.payload_bytes -= len(entry.payload)

    def remove_namespace(self, namespace: Path) -> None:
        handle = self.handles.get(str(namespace))
        if handle is not None:
            handle.entries.clear()
            handle.payload_bytes = 0

    def remember(
        self,
        namespace: Path,
        key: str,
        payload: bytes,
        limits: CacheLimits,
        fingerprint: tuple[int, int, int, int, int],
    ) -> None:
        handle = self.acquire(namespace, limits.root_handle_limit)
        self.remove(namespace, key)
        if len(payload) > limits.payload_limit_bytes:
            return
        handle.entries[key] = _MemoryEntry(payload, fingerprint)
        handle.payload_bytes += len(payload)
        handle.entries.move_to_end(key)
        self._trim_payload(limits.payload_limit_bytes)

    def _trim_payload(self, limit: int) -> None:
        total = sum(item.payload_bytes for item in self.handles.values())
        while total > limit:
            for candidate in self.handles.values():
                if not candidate.entries:
                    continue
                _, entry = candidate.entries.popitem(last=False)
                candidate.payload_bytes -= len(entry.payload)
                total -= len(entry.payload)
                break
            else:
                return


def _check_positive(value: object, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _check_budget(budget: OperationBudget | None) -> None:
    if budget is not None:
        budget.check_deadline()


def _owner_is_current(result: os.stat_result) -> bool:
    getuid = getattr(os, "getuid", None)
    return getuid is None or result.st_uid == getuid()


def _private_mode(result: os.stat_result) -> bool:
    return stat.S_IMODE(result.st_mode) & 0o077 == 0


def _safe_directory_result(result: os.stat_result) -> bool:
    return stat.S_ISDIR(result.st_mode) and _owner_is_current(result) and _private_mode(result)


def _safe_file_result(result: os.stat_result) -> bool:
    return stat.S_ISREG(result.st_mode) and _owner_is_current(result) and _private_mode(result)


def _path_parts(path: Path) -> tuple[Path, tuple[str, ...]]:
    if path.is_absolute():
        return Path(path.anchor), path.parts[1:]
    return Path("."), path.parts


def _ensure_private_directory(path: Path) -> None:
    """Create path components without following symlinks."""

    current, parts = _path_parts(path)
    for part in parts:
        candidate = current / part
        try:
            result = os.lstat(candidate)
        except FileNotFoundError:
            try:
                os.mkdir(candidate, 0o700)
            except FileExistsError:
                result = os.lstat(candidate)
            else:
                result = os.lstat(candidate)
        except OSError as exc:
            raise CacheSafetyError(f"cannot inspect cache directory {candidate}") from exc
        if stat.S_ISLNK(result.st_mode) or not stat.S_ISDIR(result.st_mode):
            raise CacheSafetyError(f"cache directory component is unsafe: {candidate}")
        if candidate == path and not _safe_directory_result(result):
            raise CacheSafetyError(f"cache directory owner or mode is unsafe: {candidate}")
        current = candidate


def _locate_private_directory(path: Path) -> bool:
    """Return whether an existing path is private, without creating it."""

    current, parts = _path_parts(path)
    for part in parts:
        candidate = current / part
        try:
            result = os.lstat(candidate)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise CacheSafetyError(f"cannot inspect cache directory {candidate}") from exc
        if stat.S_ISLNK(result.st_mode) or not stat.S_ISDIR(result.st_mode):
            raise CacheSafetyError(f"cache directory component is unsafe: {candidate}")
        if candidate == path and not _safe_directory_result(result):
            raise CacheSafetyError(f"cache directory owner or mode is unsafe: {candidate}")
        current = candidate
    return True


def _validate_key(key: str) -> str:
    if not isinstance(key, str) or _KEY_PATTERN.fullmatch(key) is None:
        raise ValueError("cache key must be 64 lowercase hexadecimal characters")
    return key


def _validate_digest(value: str, name: str) -> str:
    if not isinstance(value, str) or _KEY_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _validate_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def build_cache_key(
    artifact_schema: str,
    kind: str,
    source_digest: str,
    language: str,
    analyzer_digest: str,
    query_digest: str | None = None,
) -> str:
    """Build a content key for one derived artifact.

    ``analyzer_digest`` is the output-affecting analyzer/toolchain identity.
    ``query_digest`` is included only for query-specific derived artifacts.
    """

    _validate_text(artifact_schema, "artifact_schema")
    _validate_text(kind, "kind")
    _validate_digest(source_digest, "source_digest")
    _validate_text(language, "language")
    _validate_digest(analyzer_digest, "analyzer_digest")
    if query_digest is not None:
        _validate_digest(query_digest, "query_digest")
    parts: list[Any] = [CACHE_KEY_SCHEMA, artifact_schema, kind, source_digest, language, analyzer_digest]
    if query_digest is not None:
        parts.append(query_digest)
    return _digest_bytes(canonical_bytes(parts))


def platform_cache_dir() -> Path:
    """Return the conventional per-user XRAY cache directory."""

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / "xray" / "derived"


def _coerce_payload(payload: object, maximum: int) -> bytes | None:
    if isinstance(payload, bytes):
        return payload if len(payload) <= maximum else None
    if isinstance(payload, memoryview):
        size = payload.nbytes
    elif isinstance(payload, bytearray):
        size = len(payload)
    else:
        raise TypeError("cache payload must be bytes-like")
    return bytes(payload) if size <= maximum else None


def _encode_entry(key: str, payload: bytes) -> bytes:
    header = {"bytes": len(payload), "key": key, "sha256": _digest_bytes(payload)}
    return _CACHE_MAGIC + canonical_bytes(header) + b"\n" + payload


def _entry_size(key: str, payload_size: int) -> int:
    header = {"bytes": payload_size, "key": key, "sha256": "0" * 64}
    return len(_CACHE_MAGIC) + len(canonical_bytes(header)) + 1 + payload_size


def _read_all(fd: int, size: int, *, budget: OperationBudget | None = None) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        _check_budget(budget)
        chunk = os.read(fd, min(remaining, _READ_CHUNK_BYTES))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    _check_budget(budget)
    return b"".join(chunks)


def _read_entry(
    path: Path,
    key: str,
    artifact_limit: int,
    *,
    budget: OperationBudget | None = None,
) -> tuple[bytes, os.stat_result]:
    _check_budget(budget)
    try:
        observed = os.lstat(path)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise _CorruptEntry(None) from exc
    if not _safe_file_result(observed):
        raise _CorruptEntry(observed)
    maximum_file_size = len(_CACHE_MAGIC) + _CACHE_HEADER_LIMIT + 1 + artifact_limit
    if observed.st_size < len(_CACHE_MAGIC) + 1 or observed.st_size > maximum_file_size:
        raise _CorruptEntry(observed)

    _check_budget(budget)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise _CorruptEntry(observed) from exc
    try:
        current = os.fstat(fd)
        if (
            current.st_dev != observed.st_dev
            or current.st_ino != observed.st_ino
            or current.st_size != observed.st_size
            or not _safe_file_result(current)
        ):
            raise _CorruptEntry(observed)
        raw = _read_all(fd, current.st_size, budget=budget)
    finally:
        os.close(fd)

    if len(raw) != observed.st_size or not raw.startswith(_CACHE_MAGIC):
        raise _CorruptEntry(observed)
    header_start = len(_CACHE_MAGIC)
    header_end = raw.find(b"\n", header_start, header_start + _CACHE_HEADER_LIMIT + 1)
    if header_end < 0:
        raise _CorruptEntry(observed)
    try:
        header = json.loads(raw[header_start:header_end].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _CorruptEntry(observed) from None
    if not isinstance(header, dict) or set(header) != {"bytes", "key", "sha256"}:
        raise _CorruptEntry(observed)
    declared_size = header.get("bytes")
    declared_key = header.get("key")
    declared_digest = header.get("sha256")
    if (
        not isinstance(declared_size, int)
        or isinstance(declared_size, bool)
        or declared_size < 0
        or declared_size > artifact_limit
        or declared_key != key
        or not isinstance(declared_digest, str)
        or _KEY_PATTERN.fullmatch(declared_digest) is None
        or canonical_bytes(header) != raw[header_start:header_end]
    ):
        raise _CorruptEntry(observed)
    payload = raw[header_end + 1 :]
    if len(payload) != declared_size or _digest_bytes(payload) != declared_digest:
        raise _CorruptEntry(observed)
    return payload, observed


def _fingerprint(result: os.stat_result) -> tuple[int, int, int, int, int]:
    return result.st_dev, result.st_ino, result.st_size, result.st_mtime_ns, result.st_ctime_ns


def _same_stat(left: os.stat_result, right: tuple[int, int, int, int, int]) -> bool:
    return _fingerprint(left) == right


def _unlink_if_same(
    path: Path,
    observed: os.stat_result | None = None,
    *,
    budget: OperationBudget | None = None,
) -> bool:
    _check_budget(budget)
    try:
        current = os.lstat(path)
    except OSError:
        return False
    if not _safe_file_result(current):
        return False
    if observed is not None and _fingerprint(current) != _fingerprint(observed):
        return False
    _check_budget(budget)
    try:
        os.unlink(path)
    except OSError:
        return False
    return True


def _scan_namespace(
    namespace: Path,
    *,
    budget: OperationBudget | None = None,
) -> list[_Entry]:
    _check_budget(budget)
    try:
        result = os.lstat(namespace)
    except FileNotFoundError:
        return []
    if not _safe_directory_result(result):
        raise CacheSafetyError(f"cache namespace is unsafe: {namespace}")
    _check_budget(budget)
    try:
        iterator: Iterator[os.DirEntry[str]] = os.scandir(namespace)
    except OSError as exc:
        raise CacheSafetyError(f"cannot scan cache namespace: {namespace}") from exc
    entries: list[_Entry] = []
    with iterator:
        for index, item in enumerate(iterator):
            _check_budget(budget)
            if index >= _CACHE_SCAN_LIMIT:
                raise CacheSafetyError(f"cache namespace exceeds {_CACHE_SCAN_LIMIT} entries: {namespace}")
            if not item.name.endswith(_CACHE_FILE_SUFFIX):
                continue
            key = item.name[: -len(_CACHE_FILE_SUFFIX)]
            if _KEY_PATTERN.fullmatch(key) is None:
                continue
            try:
                child = item.stat(follow_symlinks=False)
            except OSError:
                continue
            _check_budget(budget)
            if not _safe_file_result(child):
                continue
            entries.append(_Entry(key, namespace / item.name, child.st_size, child.st_mtime_ns))
    _check_budget(budget)
    return entries


class DerivedCache:
    """One optional root-ID-scoped cache of serialized derived bytes."""

    _memory: ClassVar[_MemoryManager] = _MemoryManager()

    def __init__(
        self,
        root_id: str,
        *,
        cache_dir: str | os.PathLike[str] | None = None,
        enabled: bool = True,
        limits: CacheLimits | None = None,
    ) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a bool")
        self.root_id = _validate_digest(root_id, "root_id")
        self.enabled = enabled
        raw_cache_dir = platform_cache_dir() if cache_dir is None else Path(cache_dir)
        self.cache_dir = Path(os.path.abspath(raw_cache_dir))
        self.namespace = self.cache_dir / self.root_id
        self.limits = limits or CacheLimits()

    @staticmethod
    def key(
        artifact_schema: str,
        kind: str,
        source_digest: str,
        language: str,
        analyzer_digest: str,
        query_digest: str | None = None,
    ) -> str:
        return build_cache_key(artifact_schema, kind, source_digest, language, analyzer_digest, query_digest)

    def _namespace_path(self, *, create: bool) -> Path | None:
        if not self.enabled:
            return None
        if create:
            _ensure_private_directory(self.cache_dir)
            _ensure_private_directory(self.namespace)
        else:
            if not _locate_private_directory(self.cache_dir):
                return None
            if not _locate_private_directory(self.namespace):
                return None
        return self.namespace

    def get(self, key: str, *, budget: OperationBudget | None = None) -> bytes | None:
        """Return a validated payload, or ``None`` for a cache miss."""

        _check_budget(budget)
        if not self.enabled:
            return None
        key = _validate_key(key)
        try:
            namespace = self._namespace_path(create=False)
        except CacheSafetyError:
            return None
        if namespace is None:
            return None
        path = namespace / f"{key}{_CACHE_FILE_SUFFIX}"
        with self._memory.lock:
            handle = self._memory.acquire(namespace, self.limits.root_handle_limit)
            self._memory._trim_payload(self.limits.payload_limit_bytes)
            cached = self._memory.lookup(handle, key)
            if cached is not None and len(cached.payload) <= self.limits.payload_limit_bytes:
                _check_budget(budget)
                try:
                    observed = os.lstat(path)
                except OSError:
                    observed = None
                if observed is not None and _safe_file_result(observed) and _same_stat(observed, cached.fingerprint):
                    return cached.payload
                self._memory.remove(namespace, key)
        try:
            payload, observed = _read_entry(path, key, self.limits.artifact_limit_bytes, budget=budget)
        except FileNotFoundError:
            return None
        except _CorruptEntry as exc:
            _unlink_if_same(path, exc.observed, budget=budget)
            with self._memory.lock:
                self._memory.remove(namespace, key)
            return None
        with self._memory.lock:
            self._memory.remember(namespace, key, payload, self.limits, _fingerprint(observed))
        return payload

    def put(
        self,
        key: str,
        payload: bytes | bytearray | memoryview,
        *,
        budget: OperationBudget | None = None,
    ) -> bool:
        """Atomically store a bounded payload and report whether it was stored."""

        _check_budget(budget)
        if not self.enabled:
            return False
        key = _validate_key(key)
        raw = _coerce_payload(payload, self.limits.artifact_limit_bytes)
        if raw is None or _entry_size(key, len(raw)) > self.limits.disk_limit_bytes:
            return False
        namespace_existed = _locate_private_directory(self.namespace)
        namespace = self._namespace_path(create=True)
        if namespace is None:
            return False
        path = namespace / f"{key}{_CACHE_FILE_SUFFIX}"
        encoded = _encode_entry(key, raw)
        with self._memory.lock:
            try:
                existing = os.lstat(path)
            except FileNotFoundError:
                existing = None
            except OSError as exc:
                raise CacheSafetyError(f"cannot inspect cache entry: {path}") from exc
            if existing is not None and not _safe_file_result(existing):
                raise CacheSafetyError(f"cache entry owner, mode, or link is unsafe: {path}")
            # A replacement that does not grow its existing entry cannot
            # exceed the namespace ceiling because of this write.  Avoid a
            # global scan on the normal warm-update path; new entries and
            # growing replacements still perform the bounded capacity check.
            capacity_check_needed = (
                (existing is None and namespace_existed)
                or (existing is not None and len(encoded) > existing.st_size)
                or (existing is not None and existing.st_size > self.limits.disk_limit_bytes)
            )
            if capacity_check_needed:
                entries = _scan_namespace(namespace, budget=budget)
                usage = sum(entry.size for entry in entries)
                replacement_size = existing.st_size if existing is not None else 0
                needed = usage - replacement_size + len(encoded) - self.limits.disk_limit_bytes
                if needed > 0:
                    self._evict_for_space(entries, needed, budget=budget)
                    entries = _scan_namespace(namespace, budget=budget)
                    usage = sum(entry.size for entry in entries)
                    try:
                        _check_budget(budget)
                        current = os.lstat(path)
                    except FileNotFoundError:
                        current = None
                    if current is not None and not _safe_file_result(current):
                        raise CacheSafetyError(f"cache entry owner, mode, or link is unsafe: {path}")
                    replacement_size = current.st_size if current is not None else 0
                    if usage - replacement_size + len(encoded) > self.limits.disk_limit_bytes:
                        return False
            temp_fd, temp_name = tempfile.mkstemp(prefix=f".{key}.", suffix=".tmp", dir=namespace)
            temp = Path(temp_name)
            try:
                os.fchmod(temp_fd, 0o600)
                offset = 0
                while offset < len(encoded):
                    _check_budget(budget)
                    written = os.write(temp_fd, encoded[offset : offset + _READ_CHUNK_BYTES])
                    if written <= 0:
                        raise OSError("cache write made no progress")
                    offset += written
                _check_budget(budget)
                os.fsync(temp_fd)
                os.close(temp_fd)
                temp_fd = -1
                try:
                    _check_budget(budget)
                    current = os.lstat(path)
                except FileNotFoundError:
                    current = None
                if current is not None and not _safe_file_result(current):
                    raise CacheSafetyError(f"cache entry owner, mode, or link is unsafe: {path}")
                _check_budget(budget)
                os.replace(temp, path)
                temp = None
            finally:
                if temp_fd >= 0:
                    os.close(temp_fd)
                if temp is not None:
                    _unlink_if_same(temp, budget=budget)
            _check_budget(budget)
            observed = os.lstat(path)
            self._memory.remember(namespace, key, raw, self.limits, _fingerprint(observed))
        return True

    def _evict_for_space(
        self,
        entries: list[_Entry],
        needed: int,
        *,
        budget: OperationBudget | None = None,
    ) -> int:
        _check_budget(budget)
        freed = 0
        for entry in sorted(entries, key=lambda item: (item.mtime_ns, item.key)):
            _check_budget(budget)
            if freed >= needed:
                break
            if _unlink_if_same(entry.path, budget=budget):
                freed += entry.size
                self._memory.remove(self.namespace, entry.key)
        return freed

    def clear(self) -> int:
        """Remove owned artifact files while preserving temporary and unknown paths."""

        with self._memory.lock:
            self._memory.remove_namespace(self.namespace)
            if not self.enabled:
                return 0
            try:
                namespace = self._namespace_path(create=False)
            except CacheSafetyError:
                return 0
            if namespace is None:
                return 0
            try:
                entries = _scan_namespace(namespace)
            except CacheSafetyError:
                return 0
            removed = 0
            for entry in entries:
                if _unlink_if_same(entry.path):
                    removed += 1
            return removed

    def evict(self, *, budget: OperationBudget | None = None) -> int:
        """Evict entries past their age and then entries needed for disk bounds."""

        _check_budget(budget)
        if not self.enabled:
            return 0
        try:
            namespace = self._namespace_path(create=False)
        except CacheSafetyError:
            return 0
        if namespace is None:
            return 0
        with self._memory.lock:
            try:
                entries = _scan_namespace(namespace, budget=budget)
            except CacheSafetyError:
                return 0
            now_ns = time.time_ns()
            age_ns = int(self.limits.max_age_seconds * 1_000_000_000)
            removed = 0
            for entry in entries:
                _check_budget(budget)
                if now_ns - entry.mtime_ns >= age_ns and _unlink_if_same(entry.path, budget=budget):
                    removed += 1
                    self._memory.remove(namespace, entry.key)
            try:
                remaining = _scan_namespace(namespace, budget=budget)
            except CacheSafetyError:
                return removed
            usage = sum(entry.size for entry in remaining)
            if usage > self.limits.disk_limit_bytes:
                before = len(remaining)
                self._evict_for_space(remaining, usage - self.limits.disk_limit_bytes, budget=budget)
                try:
                    after = len(_scan_namespace(namespace, budget=budget))
                except CacheSafetyError:
                    return removed
                removed += before - after
            return removed


__all__ = [
    "CACHE_ARTIFACT_LIMIT_BYTES",
    "CACHE_DISK_LIMIT_BYTES",
    "CACHE_KEY_SCHEMA",
    "CACHE_MAX_AGE_SECONDS",
    "CACHE_PAYLOAD_LIMIT_BYTES",
    "CACHE_ROOT_HANDLE_LIMIT",
    "CacheError",
    "CacheLimits",
    "CacheSafetyError",
    "DerivedCache",
    "build_cache_key",
    "platform_cache_dir",
]
