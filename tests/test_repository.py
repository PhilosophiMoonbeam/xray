"""Behavioral tests for captured repository reads and admission bounds."""

from __future__ import annotations

import os
import stat
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from xray.core.cache import CacheLimits, CacheSafetyError, DerivedCache
from xray.core.repository import (
    REGULAR_TEXT_DOMAIN,
    CancellationError,
    CaptureLimitError,
    ContainmentError,
    ExcludedInputError,
    InvalidEncodingError,
    InvalidRuleError,
    MaterializationError,
    NamespaceLimitError,
    OperationBudget,
    RepositoryProvider,
    RootError,
    SourceChangedError,
    SymlinkError,
    UnsupportedConfigurationError,
    UnsupportedFileError,
    capture_rule_input,
    normalize_root,
    normalize_selection,
)
from xray.models import RuleInput


def put(root: Path, relative: str, content: bytes | str) -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return target


def make_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


def derived_key(
    cache: DerivedCache,
    source_digest: str = "a" * 64,
    query_digest: str | None = None,
) -> str:
    return cache.key("xray.artifact.v1", "declarations", source_digest, "python", "b" * 64, query_digest)


def paths(values: object) -> list[str]:
    return [item.path for item in values]  # type: ignore[union-attr]


def test_root_and_selection_normalize_to_canonical_values(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)

    normalized_root = normalize_root(alias)
    normalized_selection = normalize_selection(
        {
            "paths": ["src", ".", "src"],
            "globs": ["*.py", "src/*.ts"],
            "languages": ["go", "python"],
            "exclusions": "none",
        }
    )

    assert normalized_root.path == root.resolve().as_posix()
    assert normalized_root.id
    assert normalized_selection.paths == [".", "src"]
    assert normalized_selection.globs == ["*.py", "src/*.ts"]
    assert normalized_selection.languages == ["python", "go"]
    with pytest.raises(RootError):
        normalize_root(tmp_path / "missing")
    with pytest.raises(ContainmentError):
        normalize_selection({"paths": ["../outside"]})


def test_explicit_file_is_contained_and_overrides_ignore_but_not_globs(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    put(root, ".gitignore", "ignored.py\n")
    put(root, "ignored.py", "print('kept')\n")
    put(root, "sibling.py", "print('sibling')\n")
    provider = RepositoryProvider(root, {"paths": ["ignored.py"]})

    captured = provider.capture_sources()

    assert paths(captured.sources) == ["ignored.py"]
    assert paths(captured.configuration) == [".gitignore"]
    with pytest.raises(ContainmentError):
        provider.capture_file("../ignored.py")
    with pytest.raises(ExcludedInputError):
        RepositoryProvider(root, {"paths": ["ignored.py"], "globs": ["other.py"]}).capture_sources()


def test_git_internals_are_never_selected(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    put(root, ".git/config", "private\n")
    put(root, "main.py", "print('main')\n")

    broad = RepositoryProvider(root).capture()

    assert ".git" not in paths(broad.namespace.entries if broad.namespace else ())
    assert ".git/config" not in paths(broad.sources)
    with pytest.raises(ExcludedInputError):
        RepositoryProvider(root, {"paths": [".git/config"]}).capture_sources()
    with pytest.raises(ExcludedInputError):
        RepositoryProvider(root).capture_file(".git/config")


def test_symlink_targets_are_rejected_for_explicit_reads(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    put(root, "target.py", "print('target')\n")
    (root / "link.py").symlink_to(root / "target.py")
    (root / "linkdir").symlink_to(root, target_is_directory=True)
    provider = RepositoryProvider(root)

    with pytest.raises(SymlinkError):
        provider.capture_file("link.py")
    with pytest.raises(SymlinkError):
        provider.capture_file("linkdir/target.py")


def test_captured_bytes_are_immutable_and_content_authoritative(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    target = put(root, "source.py", "print('before')\n")
    provider = RepositoryProvider(root)
    captured = provider.capture_file("source.py")

    target.write_text("print('after')\n", encoding="utf-8")

    assert captured.content == b"print('before')\n"
    assert captured.digest != provider.capture_file("source.py").digest
    with pytest.raises(FrozenInstanceError):
        captured.content = b"changed"  # type: ignore[misc]


def test_source_change_is_observable_without_mtime_truth(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    target = put(root, "source.py", "same\n")
    provider = RepositoryProvider(root)
    captured = provider.capture_file("source.py")

    os.chmod(target, target.stat().st_mode | 0o100)
    assert provider.source_changed(captured) is False

    target.write_text("changed\n", encoding="utf-8")
    assert provider.source_changed(captured) is True
    with pytest.raises(SourceChangedError):
        provider.assert_unchanged(captured)


def test_nontext_inputs_are_classified_and_retained_in_broad_capture(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    put(root, "good.py", "print('good')\n")
    put(root, "binary.py", b"\xff\x00\x01")
    provider = RepositoryProvider(root)

    binary = provider.capture_file("binary.py")
    broad = provider.capture_sources()

    assert binary.classification == "non_text_input"
    assert binary.text is None
    assert paths(broad.sources) == ["binary.py", "good.py"]
    assert broad.sources[0].content == b"\xff\x00\x01"
    with pytest.raises(InvalidEncodingError):
        provider.capture_exact_file("binary.py")


def test_regular_text_capture_domain_includes_unknown_language_files(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    put(root, "notes.md", "literal notes\n")
    put(root, "extensionless", "literal extensionless\n")
    put(root, "binary.data", b"\xff\x00")
    provider = RepositoryProvider(root, {"paths": ["notes.md", "extensionless", "binary.data"]})

    captured = provider.capture_sources(capture_domain=REGULAR_TEXT_DOMAIN)

    assert paths(captured.sources) == ["binary.data", "extensionless", "notes.md"]
    assert [item.classification for item in captured.sources] == [
        "non_text_input",
        "text",
        "text",
    ]


def test_language_filter_restricts_unknown_regular_text_and_explicit_files(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    put(root, "notes.md", "literal notes\n")
    put(root, "extensionless", "literal extensionless\n")
    put(root, "source.py", "print('source')\n")

    unrestricted = RepositoryProvider(root, {"paths": ["."]})
    assert paths(unrestricted.capture_sources(capture_domain=REGULAR_TEXT_DOMAIN).sources) == [
        "extensionless",
        "notes.md",
        "source.py",
    ]

    restricted = RepositoryProvider(root, {"paths": ["."], "languages": ["python"]})
    assert paths(restricted.capture_sources(capture_domain=REGULAR_TEXT_DOMAIN).sources) == ["source.py"]

    with pytest.raises(UnsupportedFileError):
        RepositoryProvider(root, {"paths": ["notes.md"], "languages": ["python"]}).capture_sources(
            capture_domain=REGULAR_TEXT_DOMAIN
        )


def test_file_namespace_and_configuration_limits_are_admission_failures(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    put(root, "a.py", "aaaa")
    put(root, "b.py", "bbbb")
    put(root, ".gitignore", "*.tmp\n")
    provider = RepositoryProvider(root)

    with pytest.raises(CaptureLimitError):
        provider.capture_file("a.py", budget=OperationBudget(file_bytes_limit=3))
    with pytest.raises(CaptureLimitError):
        provider.capture_sources(budget=OperationBudget(source_files_limit=1))
    with pytest.raises(NamespaceLimitError):
        provider.capture(budget=OperationBudget(namespace_entries_limit=1))
    with pytest.raises(CaptureLimitError):
        provider.capture_sources(budget=OperationBudget(configuration_file_bytes_limit=2))
    with pytest.raises(MaterializationError):
        provider.capture_file("a.py", budget=OperationBudget(temporary_bytes_limit=3))


def test_scoped_capture_does_not_populate_siblings(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    put(root, "src/selected.py", "print('selected')\n")
    put(root, "sibling.py", "print('sibling')\n")

    exact = RepositoryProvider(root, {"paths": ["src/selected.py"]}).capture()
    directory = RepositoryProvider(root, {"paths": ["src"]}).capture()

    assert exact.namespace is None
    assert paths(exact.sources) == ["src/selected.py"]
    assert paths(directory.sources) == ["src/selected.py"]
    assert paths(directory.namespace.entries if directory.namespace else ()) == [
        ".",
        "src",
        "src/selected.py",
    ]


def test_overlapping_directory_scopes_walk_once_and_charge_namespace_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = make_root(tmp_path)
    put(root, "src/deep/keep.py", "keep\n")
    put(root, "src/sibling.py", "sibling\n")

    real_scandir = os.scandir
    scanned: list[str] = []

    def tracked_scandir(path: str | os.PathLike[str]) -> object:
        candidate = Path(path)
        scanned.append(candidate.relative_to(root).as_posix())
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", tracked_scandir)
    budget = OperationBudget(namespace_entries_limit=5)
    captured = RepositoryProvider(root, {"paths": ["src", "src/deep"]}).capture(budget=budget)

    assert paths(captured.namespace.entries if captured.namespace else ()) == [
        ".",
        "src",
        "src/deep",
        "src/deep/keep.py",
        "src/sibling.py",
    ]
    assert paths(captured.sources) == ["src/deep/keep.py", "src/sibling.py"]
    assert scanned.count("src") == 1
    assert scanned.count("src/deep") == 1
    assert budget.namespace_entries == 5


def test_namespace_horizon_bounds_metadata_and_sources(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    put(root, "src/pkg/a.py", "print('a')\n")
    put(root, "src/other/b.py", "print('b')\n")
    provider = RepositoryProvider(root)

    shallow = provider.capture(horizon={"focus": ["src/pkg"], "depth": 0})
    assert paths(shallow.namespace.entries if shallow.namespace else ()) == [".", "src", "src/pkg"]
    assert paths(shallow.sources) == []

    deep = provider.capture(horizon={"focus": ["src/pkg"], "depth": 1})
    assert paths(deep.namespace.entries if deep.namespace else ()) == [".", "src", "src/pkg", "src/pkg/a.py"]
    assert paths(deep.sources) == ["src/pkg/a.py"]


def test_horizon_keeps_frontier_without_touching_excluded_descendants(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = make_root(tmp_path)
    put(root, "src/closed/inaccessible/secret.py", "secret\n")
    unsupported = root / "src/closed/unsupported\\name.py"
    unsupported.write_text("unsupported\n", encoding="utf-8")
    inaccessible = root / "src/closed/inaccessible"
    os.chmod(inaccessible, 0)
    put(root, "src/overlap/deep/keep.py", "keep\n")

    real_scandir = os.scandir
    scanned: list[str] = []

    def guarded_scandir(path: str | os.PathLike[str]) -> object:
        candidate = Path(path)
        relative = candidate.relative_to(root).as_posix() if candidate.is_relative_to(root) else str(candidate)
        scanned.append(relative)
        if candidate == root / "src" / "closed":
            raise AssertionError("horizon frontier was enumerated")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", guarded_scandir)
    try:
        captured = RepositoryProvider(root).capture(
            horizon={
                "focus": ["src/closed", "src/overlap", "src/overlap/deep/keep.py"],
                "depth": 0,
            }
        )
    finally:
        os.chmod(inaccessible, 0o700)

    assert paths(captured.namespace.entries if captured.namespace else ()) == [
        ".",
        "src",
        "src/closed",
        "src/overlap",
        "src/overlap/deep",
        "src/overlap/deep/keep.py",
    ]
    assert paths(captured.sources) == ["src/overlap/deep/keep.py"]
    assert "src/closed" not in scanned
    assert "src/overlap" in scanned


def test_materialized_capture_is_removed_on_close(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    put(root, "source.py", "print('source')\n")
    provider = RepositoryProvider(root)
    captured = provider.capture_file("source.py")

    materialized = provider.materialize([captured])
    materialized_root = materialized.root
    materialized_file = materialized.files["source.py"]
    assert materialized_file.read_bytes() == captured.content
    assert materialized_root.exists()

    materialized.close()

    assert materialized.closed is True
    assert not materialized_root.exists()
    with pytest.raises(RuntimeError):
        materialized.__enter__()


def test_derived_cache_disabled_cold_warm_clear_corrupt_and_evicted_states(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    root_id = "1" * 64
    cache = DerivedCache(root_id, cache_dir=cache_dir)
    key = derived_key(cache)
    payload = b'{"declarations":[]}'

    disabled = DerivedCache(root_id, cache_dir=cache_dir, enabled=False)
    assert disabled.get(key) is None
    assert disabled.put(key, payload) is False
    assert not cache_dir.exists()
    assert cache.get(key) is None

    assert cache.put(key, payload) is True
    assert cache.get(key) == payload
    entry = cache.namespace / f"{key}.json"
    assert entry.exists()

    assert cache.clear() == 1
    assert cache.get(key) is None

    assert cache.put(key, payload) is True
    entry.write_bytes(b"not a cache entry")
    assert cache.get(key) is None
    assert not entry.exists()

    assert cache.put(key, payload) is True
    os.utime(entry, ns=(0, 0))
    aged = DerivedCache(root_id, cache_dir=cache_dir, limits=CacheLimits(max_age_seconds=1))
    assert aged.get(key) == payload
    assert aged.evict() == 1
    assert aged.get(key) is None
    assert not entry.exists()


def test_derived_cache_warm_gets_and_puts_skip_global_eviction_scans(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import xray.core.cache as cache_module

    cache = DerivedCache("3" * 64, cache_dir=tmp_path / "cache")
    key = derived_key(cache)
    payload = b"payload"
    assert cache.put(key, payload) is True

    def unexpected_scan(namespace: Path) -> list[object]:
        raise AssertionError(f"unexpected cache namespace scan: {namespace}")

    monkeypatch.setattr(cache_module, "_scan_namespace", unexpected_scan)
    assert cache.get(key) == payload
    assert cache.put(key, payload) is True
    assert cache.get(key) == payload


def test_derived_cache_namespace_overflow_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import xray.core.cache as cache_module

    cache = DerivedCache("4" * 64, cache_dir=tmp_path / "cache")
    first_key = derived_key(cache)
    assert cache.put(first_key, b"first") is True
    (cache.namespace / "unrelated.tmp").write_bytes(b"not an artifact")
    second_key = derived_key(cache, source_digest="b" * 64)

    monkeypatch.setattr(cache_module, "_CACHE_SCAN_LIMIT", 1)
    with pytest.raises(CacheSafetyError):
        cache.put(second_key, b"second")
    assert not (cache.namespace / f"{second_key}.json").exists()
    assert cache.evict() == 0


def test_derived_cache_lifecycle_checks_operation_budget(tmp_path: Path) -> None:
    cache = DerivedCache("5" * 64, cache_dir=tmp_path / "cache")
    budget = OperationBudget(cancel=lambda: True)

    with pytest.raises(CancellationError):
        cache.put(derived_key(cache), b"payload", budget=budget)
    with pytest.raises(CancellationError):
        cache.get(derived_key(cache), budget=budget)
    with pytest.raises(CancellationError):
        cache.evict(budget=budget)


def test_derived_cache_key_uses_content_digest_not_same_size_mtime(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    target = put(root, "source.py", "same\n")
    first = RepositoryProvider(root).capture_file("source.py")
    original_mtime = target.stat().st_mtime_ns

    target.write_text("diff\n", encoding="utf-8")
    os.utime(target, ns=(original_mtime, original_mtime))
    second = RepositoryProvider(root).capture_file("source.py")

    assert len(first.content) == len(second.content)
    assert first.digest != second.digest
    cache = DerivedCache("2" * 64, cache_dir=tmp_path / "cache")
    assert derived_key(cache, first.digest) != derived_key(cache, second.digest)
    assert derived_key(cache) != derived_key(cache, query_digest="c" * 64)
    assert cache.key("xray.other.v1", "declarations", "a" * 64, "python", "b" * 64) != derived_key(cache)
    assert cache.key("xray.artifact.v1", "queries", "a" * 64, "python", "b" * 64) != derived_key(cache)
    assert cache.key("xray.artifact.v1", "declarations", "a" * 64, "rust", "b" * 64) != derived_key(cache)
    assert cache.key("xray.artifact.v1", "declarations", "a" * 64, "python", "c" * 64) != derived_key(cache)


def test_derived_cache_oversize_memory_handles_and_disk_bounds(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    limits = CacheLimits(
        disk_limit_bytes=4096,
        artifact_limit_bytes=8,
        payload_limit_bytes=5,
        root_handle_limit=2,
    )
    caches = [DerivedCache(str(index) * 64, cache_dir=cache_dir, limits=limits) for index in (1, 2, 3)]
    keys = [derived_key(cache, source_digest=str(index) * 64) for index, cache in enumerate(caches, 1)]

    for cache, key in zip(caches, keys, strict=True):
        assert cache.put(key, b"1234") is True
    with caches[-1]._memory.lock:
        assert len(caches[-1]._memory.handles) <= limits.root_handle_limit
        assert sum(handle.payload_bytes for handle in caches[-1]._memory.handles.values()) <= limits.payload_limit_bytes

    oversized_key = derived_key(caches[-1], source_digest="f" * 64)
    assert caches[-1].put(oversized_key, b"123456789") is False
    assert not (caches[-1].namespace / f"{oversized_key}.json").exists()

    disk_root = "4" * 64
    generous = DerivedCache(disk_root, cache_dir=cache_dir, limits=CacheLimits(disk_limit_bytes=4096))
    first_key = derived_key(generous, source_digest="5" * 64)
    assert generous.put(first_key, b"aaaa") is True
    disk_limit = (generous.namespace / f"{first_key}.json").stat().st_size
    bounded = DerivedCache(disk_root, cache_dir=cache_dir, limits=CacheLimits(disk_limit_bytes=disk_limit))
    second_key = derived_key(bounded, source_digest="6" * 64)
    assert bounded.put(second_key, b"bbbb") is True
    entries = list(bounded.namespace.glob("*.json"))
    assert len(entries) == 1
    assert sum(item.stat().st_size for item in entries) <= disk_limit
    assert bounded.get(first_key) is None
    assert bounded.get(second_key) == b"bbbb"


def test_derived_cache_private_modes_and_symlinks_are_not_followed(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache = DerivedCache("7" * 64, cache_dir=cache_dir)
    key = derived_key(cache)
    assert cache.put(key, b"payload") is True
    entry = cache.namespace / f"{key}.json"
    assert stat.S_IMODE(cache.namespace.stat().st_mode) == 0o700
    assert stat.S_IMODE(entry.stat().st_mode) == 0o600

    os.chmod(entry, 0o644)
    assert cache.get(key) is None
    with pytest.raises(CacheSafetyError):
        cache.put(key, b"replacement")
    assert entry.exists()

    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    linked_key = derived_key(cache, source_digest="8" * 64)
    linked_entry = cache.namespace / f"{linked_key}.json"
    linked_entry.symlink_to(outside)
    assert cache.get(linked_key) is None
    assert linked_entry.is_symlink()
    assert outside.read_bytes() == b"outside"

    public_dir = tmp_path / "public-cache"
    public_dir.mkdir(mode=0o755)
    public_cache = DerivedCache("b" * 64, cache_dir=public_dir)
    assert public_cache.get(key) is None
    with pytest.raises(CacheSafetyError):
        public_cache.put(key, b"payload")
    assert not public_cache.namespace.exists()

    real_dir = tmp_path / "real-cache"
    real_dir.mkdir(mode=0o700)
    linked_dir = tmp_path / "cache-link"
    linked_dir.symlink_to(real_dir, target_is_directory=True)
    linked_cache = DerivedCache("9" * 64, cache_dir=linked_dir)
    assert linked_cache.get(key) is None
    with pytest.raises(CacheSafetyError):
        linked_cache.put(key, b"payload")
    assert list(real_dir.iterdir()) == []


def test_derived_cache_cleanup_preserves_active_temps_and_unrelated_paths(tmp_path: Path) -> None:
    cache = DerivedCache("a" * 64, cache_dir=tmp_path / "cache")
    key = derived_key(cache)
    assert cache.put(key, b"payload") is True
    active = cache.namespace / f"{key}.active.tmp"
    unrelated = cache.namespace / "notes.txt"
    active.write_bytes(b"in progress")
    unrelated.write_bytes(b"keep me")
    assert cache.clear() == 1
    assert not (cache.namespace / f"{key}.json").exists()
    assert active.read_bytes() == b"in progress"
    assert unrelated.read_bytes() == b"keep me"


def test_captures_standalone_rule_documents_with_explicit_dependency_identity(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    put(
        root,
        "rules/standalone.yml",
        "---\nid: first\nlanguage: JavaScript\nrule:\n  pattern: foo()\n---\nid: second\nlanguage: JavaScript\nrule:\n  pattern: bar()\n",
    )

    captured = capture_rule_input(root, RuleInput(kind="rule", path="rules/standalone.yml"))

    assert captured.input.kind == "rule"
    assert captured.input_file.path == "rules/standalone.yml"
    assert captured.rules == (captured.input_file,)
    assert captured.membership == ("rules/standalone.yml",)
    assert captured.digest


def test_rule_directory_charges_irrelevant_entries_before_retention(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    put(root, "config.yml", "ruleDirs:\n  - rules\n")
    put(root, "rules/keep.yml", "id: keep\nlanguage: JavaScript\nrule:\n  pattern: keep()\n")
    for index in range(20):
        put(root, f"rules/irrelevant-{index}.txt", "not a rule\n")

    with pytest.raises(NamespaceLimitError) as raised:
        capture_rule_input(
            root,
            RuleInput(kind="config", path="config.yml"),
            budget=OperationBudget(namespace_entries_limit=3),
        )

    assert raised.value.kind == "namespace_entries"


def test_deep_rule_directory_walk_is_iterative(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    put(root, "config.yml", "ruleDirs:\n  - rules\n")
    directory = root / "rules"
    directory.mkdir()
    relative_parts = ["rules"]
    for _ in range(1100):
        directory /= "d"
        directory.mkdir()
        relative_parts.append("d")
    rule_relative = "/".join((*relative_parts, "deep.yml"))
    put(root, rule_relative, "id: deep\nlanguage: JavaScript\nrule:\n  pattern: deep()\n")

    captured = capture_rule_input(root, RuleInput(kind="config", path="config.yml"))

    assert [item.path for item in captured.rules] == [rule_relative]


def test_captures_rule_dirs_in_canonical_order_and_rejects_symlinks(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    put(root, "config.yml", "ruleDirs:\n  - rules\n")
    put(root, "rules/Z.yml", "id: z\nlanguage: JavaScript\nrule:\n  pattern: z()\n")
    put(root, "rules/a.yaml", "id: a\nlanguage: JavaScript\nrule:\n  pattern: a()\n")
    put(root, "rules/nested/b.yml", "id: b\nlanguage: JavaScript\nrule:\n  pattern: b()\n")
    outside = tmp_path / "outside.yml"
    outside.write_text("id: outside\n", encoding="utf-8")

    config = capture_rule_input(root, RuleInput(kind="config", path="config.yml"))
    repeat = capture_rule_input(root, RuleInput(kind="config", path="config.yml"))
    assert [item.path for item in config.rules] == ["rules/Z.yml", "rules/a.yaml", "rules/nested/b.yml"]
    assert list(config.membership) == sorted(config.membership, key=lambda value: value.encode("utf-8"))
    assert repeat.digest == config.digest

    (root / "rules/link.yml").symlink_to(outside)
    with pytest.raises(SymlinkError):
        capture_rule_input(root, RuleInput(kind="config", path="config.yml"))


def test_rule_yaml_node_budget_is_aggregate_across_dependencies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import xray.core.repository as repository_module

    root = make_root(tmp_path)
    put(root, "config.yml", "ruleDirs:\n  - rules\n")
    put(root, "rules/one.yml", "id: first\nlanguage: Python\nrule:\n  pattern: first()\n")
    monkeypatch.setattr(repository_module, "YAML_NODE_LIMIT", 12)

    with pytest.raises(InvalidRuleError):
        capture_rule_input(root, RuleInput(kind="config", path="config.yml"))


@pytest.mark.parametrize(
    ("name", "content", "kind", "error_type"),
    [
        ("duplicate", "id: one\nid: two\n", "rule", InvalidRuleError),
        ("alias", "a: &value [1]\nb: *value\n", "rule", InvalidRuleError),
        ("anchor", "id: &value one\n", "rule", InvalidRuleError),
        ("merge", "base: {a: 1}\n<<: {b: 2}\n", "rule", InvalidRuleError),
        ("tag", "id: !Danger one\n", "rule", InvalidRuleError),
        ("unknown-config", "ruleDirs:\n  - rules\nutilDirs:\n  - utils\n", "config", UnsupportedConfigurationError),
        ("empty-config", "ruleDirs: []\n", "config", UnsupportedConfigurationError),
        (
            "multi-config",
            "---\nruleDirs:\n  - rules\n---\nruleDirs:\n  - rules\n",
            "config",
            UnsupportedConfigurationError,
        ),
    ],
)
def test_rule_yaml_rejections_are_typed_before_execution(
    tmp_path: Path,
    name: str,
    content: str,
    kind: str,
    error_type: type[Exception],
) -> None:
    root = make_root(tmp_path)
    put(root, f"{name}.yml", content)

    with pytest.raises(error_type):
        capture_rule_input(root, RuleInput(kind=kind, path=f"{name}.yml"))  # type: ignore[arg-type]


def test_yaml_node_depth_and_file_bounds_are_admission_failures(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    put(root, "depth.yml", "- " * 65 + "0\n")
    with pytest.raises(InvalidRuleError):
        capture_rule_input(root, RuleInput(kind="rule", path="depth.yml"))

    put(root, "nodes.yml", "- 0\n" * 100_001)
    with pytest.raises(InvalidRuleError):
        capture_rule_input(root, RuleInput(kind="rule", path="nodes.yml"))

    put(root, "bytes.yml", b"id: " + b"x" * (1_048_576 + 1) + b"\n")
    with pytest.raises(CaptureLimitError):
        capture_rule_input(root, RuleInput(kind="rule", path="bytes.yml"))


def test_duplicate_yaml_is_rejected_before_safe_constructor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import xray.core.repository as repository_module

    root = make_root(tmp_path)
    put(root, "duplicate.yml", "id: one\nid: two\n")

    def fail_constructor(*args: object, **kwargs: object) -> object:
        raise AssertionError("safe constructors must not run for rejected YAML")

    monkeypatch.setattr(repository_module.yaml, "load_all", fail_constructor)
    with pytest.raises(InvalidRuleError):
        capture_rule_input(root, RuleInput(kind="rule", path="duplicate.yml"))


def test_rule_dependency_drift_is_rejected_without_using_new_bytes(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    put(root, "config.yml", "ruleDirs:\n  - rules\n")
    put(root, "rules/a.yml", "id: a\nlanguage: JavaScript\nrule:\n  pattern: a()\n")
    provider = RepositoryProvider(root)
    captured = provider.capture_rule_input(RuleInput(kind="config", path="config.yml"))

    put(root, "rules/a.yml", "id: a\nlanguage: JavaScript\nrule:\n  pattern: b()\n")
    with pytest.raises(SourceChangedError):
        provider.assert_rule_input_unchanged(captured)
