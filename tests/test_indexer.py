from __future__ import annotations

from pathlib import Path

import pytest

from xray.core.cache import DerivedCache
from xray.core.indexer import DeclarationArtifact, XRayIndexer
from xray.core.repository import RepositoryProvider
from xray.models import (
    Error,
    Execution,
    FileTarget,
    FindQuery,
    FindRequest,
    InterfaceFileQuery,
    InterfaceRequest,
    InterfaceSymbolQuery,
    LocationTarget,
    MapQuery,
    MapRequest,
    OccurrenceRef,
    PageFind,
    PageInterface,
    PageMap,
    PageRead,
    ReadQuery,
    ReadRequest,
    SourceRef,
    Success,
)
from xray.presentation import occurrence_digest


def _provider(root: Path, *paths: str) -> RepositoryProvider:
    return RepositoryProvider(root, {"paths": sorted(paths), "exclusions": "none"})


def _capture(root: Path, *paths: str):
    return _provider(root, *paths).capture(include_namespace=False)


def _request(root: Path, targets, *, page: PageRead | None = None, context_lines: int = 0, enclosing: bool = True):
    values = {
        "root": str(root),
        "query": ReadQuery(
            targets=list(targets),
            context_lines=context_lines,
            include_enclosing=enclosing,
        ),
    }
    if page is not None:
        values["page"] = page
    return ReadRequest(**values)


def _source_ref(capture, path: str, start: int, end: int) -> SourceRef:
    file = next(item for item in capture.files if item.path == path)
    return SourceRef(
        kind="source",
        root_id=capture.root.id,
        path=path,
        file_digest=file.digest,
        start=start,
        end=end,
    )


def test_python_nested_owner_chain_and_defining_spans_are_canonical(tmp_path: Path) -> None:
    source = (
        "class Outer:\n"
        "    def same(self):\n"
        "        return 1\n"
        "    class Inner:\n"
        "        def same(self):\n"
        "            return 2\n"
    )
    (tmp_path / "sample.py").write_text(source, encoding="utf-8")
    capture = _capture(tmp_path, "sample.py")
    indexer = XRayIndexer(tmp_path)
    artifact = indexer.declarations_for(capture.files[0])

    assert isinstance(artifact, DeclarationArtifact)
    same = [item for item in artifact.declarations if item.name == "same"]
    assert [item.owner_chain for item in same] == [("Outer",), ("Outer", "Inner")]
    assert len({item.symbol_id for item in same}) == 2
    for item in same:
        assert source.encode("utf-8")[item.defining_start : item.defining_end] == b"same"
        assert item.start < item.defining_start < item.defining_end <= item.end
        assert item.qualified_name.endswith(".same")
    assert artifact.coverage.state == "complete"


def test_byte_identical_files_remain_distinct_artifacts(tmp_path: Path) -> None:
    source = "def same():\n    return 1\n"
    (tmp_path / "a.py").write_text(source, encoding="utf-8")
    (tmp_path / "b.py").write_text(source, encoding="utf-8")
    capture = _capture(tmp_path, "a.py", "b.py")
    indexer = XRayIndexer(tmp_path)
    first = indexer.declarations_for(next(item for item in capture.files if item.path == "a.py"))
    second = indexer.declarations_for(next(item for item in capture.files if item.path == "b.py"))

    assert first.path != second.path
    assert first.file_digest == second.file_digest
    assert first.declarations[0].symbol_id == second.declarations[0].symbol_id
    assert first.declarations[0].ref.path == "a.py"
    assert second.declarations[0].ref.path == "b.py"


def test_read_accepts_all_target_forms_and_attaches_target_local_enclosing(tmp_path: Path) -> None:
    source = "def outer():\n    def inner():\n        return 1\n    return inner()\n"
    (tmp_path / "sample.py").write_text(source, encoding="utf-8")
    capture = _capture(tmp_path, "sample.py")
    indexer = XRayIndexer(tmp_path)
    artifact = indexer.declarations_for(capture.files[0])
    outer = next(item for item in artifact.declarations if item.name == "outer")
    inner = next(item for item in artifact.declarations if item.name == "inner")
    occurrence = OccurrenceRef(
        kind="occurrence",
        root_id=capture.root.id,
        path="sample.py",
        file_digest=capture.files[0].digest,
        start=inner.defining_start,
        end=inner.defining_end,
        occurrence_id=occurrence_digest("sample.py", capture.files[0].digest, inner.defining_start, inner.defining_end),
    )
    source_ref = _source_ref(capture, "sample.py", outer.defining_start, outer.defining_end)
    location = LocationTarget(kind="location", path="sample.py", line=3, end_line=3)
    symbol = inner.ref

    data = indexer.read(capture, [source_ref, occurrence, location, symbol])

    assert len(data.items) == 2
    assert [item.targets for item in data.items] == [[0], [1, 2, 3]]
    assert data.items[0].source == "outer"
    assert data.items[1].source == "def inner():\n        return 1\n"
    assert data.items[1].enclosing is not None
    enclosing_by_target = {item.target: item.result for item in data.items[1].enclosing}
    assert enclosing_by_target[1].state == "found"
    assert enclosing_by_target[1].ref.symbol_id == inner.symbol_id
    assert enclosing_by_target[2].state == "found"
    assert enclosing_by_target[2].ref.symbol_id == inner.symbol_id
    assert enclosing_by_target[3].state == "found"
    assert enclosing_by_target[3].ref.symbol_id == inner.symbol_id
    first_enclosing = data.items[0].enclosing
    assert first_enclosing is not None
    assert first_enclosing[0].result.state == "found"
    assert first_enclosing[0].result.ref.symbol_id == outer.symbol_id


def test_eight_overlapping_targets_merge_once_and_preserve_indexes(tmp_path: Path) -> None:
    source = "0123456789abcdefghij\n"
    (tmp_path / "sample.py").write_text(source, encoding="utf-8")
    capture = _capture(tmp_path, "sample.py")
    targets = [_source_ref(capture, "sample.py", index, index + 4) for index in range(0, 8)]

    data = XRayIndexer(tmp_path).read(capture, targets, include_enclosing=False)

    assert len(data.items) == 1
    assert data.items[0].targets == list(range(8))
    assert data.items[0].source == source[:11]
    assert data.items[0].ref.start == 0
    assert data.items[0].ref.end == 11
    assert data.items[0].enclosing is None


def test_eight_disjoint_targets_share_one_source_budget(tmp_path: Path) -> None:
    source = "".join(f"{index}\n" for index in range(8))
    (tmp_path / "sample.py").write_text(source, encoding="utf-8")
    capture = _capture(tmp_path, "sample.py")
    targets = [_source_ref(capture, "sample.py", index * 2, index * 2 + 2) for index in range(8)]
    indexer = XRayIndexer(tmp_path)
    page = PageRead(max_bytes=4096, max_lines=64, source_bytes=5)
    cursor: str | None = None
    rows = []
    seen_cursors: set[str] = set()

    while True:
        current = _request(
            tmp_path,
            targets,
            page=page.model_copy(update={"cursor": cursor}),
            enclosing=False,
        )
        result = indexer.execute(current)
        assert isinstance(result, Success)
        rows.extend(result.data.items)
        assert sum(len(item.source.encode("utf-8")) for item in result.data.items) <= 5
        next_cursor = result.page.next_cursor if result.page is not None else None
        if next_cursor is None:
            break
        assert next_cursor not in seen_cursors
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    assert "".join(item.source for item in rows) == source
    assert {target for item in rows for target in item.targets} == set(range(8))


def test_zero_length_target_is_preserved_as_an_empty_read_item(tmp_path: Path) -> None:
    source = "value = 1\n"
    (tmp_path / "empty.py").write_text(source, encoding="utf-8")
    capture = _capture(tmp_path, "empty.py")
    target = LocationTarget(kind="location", path="empty.py", line=2)

    data = XRayIndexer(tmp_path).read(capture, [target], include_enclosing=False)

    assert len(data.items) == 1
    assert data.items[0].source == ""
    assert data.items[0].ref.start == len(source.encode("utf-8"))
    assert data.items[0].ref.end == data.items[0].ref.start


def test_wrong_root_stale_digest_and_tampered_symbol_are_typed_errors(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text("def target():\n    return 1\n", encoding="utf-8")
    capture = _capture(tmp_path, "sample.py")
    indexer = XRayIndexer(tmp_path)
    symbol = indexer.declarations_for(capture.files[0]).declarations[0].ref

    wrong_root = symbol.model_copy(update={"root_id": "a" * 64})
    stale = symbol.model_copy(update={"file_digest": "b" * 64})
    tampered = symbol.model_copy(update={"symbol_id": "c" * 64})
    for ref, code in ((wrong_root, "invalid_reference"), (stale, "stale_reference"), (tampered, "stale_reference")):
        result = indexer.execute(_request(tmp_path, [ref]))
        assert isinstance(result, Error)
        assert result.error.code == code


def test_long_unicode_pages_resume_at_utf8_boundary_without_repeating_bytes(tmp_path: Path) -> None:
    source = "é" * 300 + "\nlast"
    (tmp_path / "unicode.py").write_text(source, encoding="utf-8")
    capture = _capture(tmp_path, "unicode.py")
    target = _source_ref(capture, "unicode.py", 0, len(source.encode("utf-8")))
    indexer = XRayIndexer(tmp_path)
    page = PageRead(max_bytes=4096, max_lines=64, source_bytes=17)

    first = indexer.execute(_request(tmp_path, [target], page=page))
    assert isinstance(first, Success)
    assert first.page is not None
    assert first.page.next_cursor is not None
    first_cursor = first.page.next_cursor
    first_source = first.data.items[0].source
    assert 0 < len(first_source.encode("utf-8")) <= 17
    assert first_source.encode("utf-8").decode("utf-8") == first_source

    second_page = page.model_copy(update={"cursor": first_cursor})
    second = indexer.execute(_request(tmp_path, [target], page=second_page))
    assert isinstance(second, Success)
    second_page_result = second.page
    assert second_page_result is not None
    combined = first_source + "".join(item.source for item in second.data.items)
    while second_page_result.next_cursor is not None:
        next_cursor = second_page_result.next_cursor
        second_result = indexer.execute(
            _request(tmp_path, [target], page=page.model_copy(update={"cursor": next_cursor}))
        )
        assert isinstance(second_result, Success)
        assert second_result.page is not None
        combined += "".join(item.source for item in second_result.data.items)
        second_page_result = second_result.page
    assert combined == source
    assert first_source.encode("utf-8").decode("utf-8") == first_source


def test_crlf_and_no_final_newline_are_returned_as_exact_captured_bytes(tmp_path: Path) -> None:
    source = "first\r\nsecond\r\nthird"
    (tmp_path / "lines.py").write_bytes(source.encode("utf-8"))
    capture = _capture(tmp_path, "lines.py")
    data = XRayIndexer(tmp_path).read(
        capture,
        [LocationTarget(kind="location", path="lines.py", line=2, end_line=3)],
        include_enclosing=False,
    )

    assert data.items[0].source == "second\r\nthird"
    assert data.items[0].location.start.line == 2
    assert data.items[0].location.end.line == 3
    assert not data.items[0].source.endswith("\n")


def test_nontext_exact_read_fails_without_decoding_or_empty_success(tmp_path: Path) -> None:
    (tmp_path / "binary.py").write_bytes(b"\xff\x00\x01")
    result = XRayIndexer(tmp_path).execute(
        _request(tmp_path, [LocationTarget(kind="location", path="binary.py", line=1)])
    )

    assert result.ok is False
    assert result.error.code == "invalid_encoding"


def test_file_scoped_artifact_uses_captured_bytes_and_race_is_stale(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def beta():\n    return 2\n", encoding="utf-8")
    capture = _capture(tmp_path, "a.py")
    indexer = XRayIndexer(tmp_path)
    artifact = indexer.declarations_for(capture.files[0])
    assert [item.name for item in artifact.declarations] == ["alpha"]

    ref = artifact.declarations[0].ref
    (tmp_path / "a.py").write_text("def changed():\n    return 3\n", encoding="utf-8")
    result = indexer.execute(_request(tmp_path, [ref]))
    assert result.ok is False
    assert result.error.code == "stale_reference"


@pytest.mark.parametrize(
    "language,filename,source",
    [
        ("javascript", "sample.js", "export class Outer { method() { return 1; } }\n"),
        ("typescript", "sample.ts", "interface Outer { method(): string }\ntype Alias = string;\n"),
        ("go", "sample.go", "package p\ntype Outer struct { X int }\nfunc (o Outer) Method() {}\n"),
    ],
)
def test_supported_languages_have_deterministic_declarations(
    tmp_path: Path, language: str, filename: str, source: str
) -> None:
    del language
    (tmp_path / filename).write_text(source, encoding="utf-8")
    capture = _capture(tmp_path, filename)
    artifact = XRayIndexer(tmp_path).declarations_for(capture.files[0])

    assert artifact.declarations
    assert list(artifact.declarations) == sorted(
        artifact.declarations,
        key=lambda item: (item.start, item.end, item.defining_start, item.owner_chain, item.name, item.kind),
    )
    assert all(item.start <= item.defining_start < item.defining_end <= item.end for item in artifact.declarations)


def test_map_paginates_large_metadata_namespace_without_source_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    for index in range(50_000):
        (source_dir / f"{index:05d}.py").touch()

    def no_source_capture(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("metadata map must not capture source bytes")

    monkeypatch.setattr(RepositoryProvider, "_read_file", no_source_capture)
    request = MapRequest(
        root=str(tmp_path),
        query=MapQuery(focus=["src"], depth=1, exclusions="none"),
        page=PageMap(limit=2, max_bytes=4096),
    )
    first = XRayIndexer(tmp_path).execute(request)
    assert isinstance(first, Success)
    assert [item.path for item in first.data.items] == ["src", "src/00000.py"]
    assert first.data.items[0].frontier is None
    assert first.page is not None and first.page.next_cursor is not None
    assert first.page.total == 50_001
    assert "content" not in first.to_payload()

    second = XRayIndexer(tmp_path).execute(
        request.model_copy(update={"page": PageMap(limit=2, max_bytes=4096, cursor=first.page.next_cursor)})
    )
    assert isinstance(second, Success)
    assert second.data.items[0].path == "src/00001.py"


def test_map_canonicalizes_focus_before_capture_and_query_identity(tmp_path: Path) -> None:
    for directory in ("a", "b"):
        path = tmp_path / directory
        path.mkdir()
        (path / "sample.py").write_text("value = 1\n", encoding="utf-8")

    indexer = XRayIndexer(tmp_path)
    unsorted = MapRequest(
        root=str(tmp_path),
        query=MapQuery(focus=["b", "a"], depth=1, exclusions="none"),
    )
    sorted_request = unsorted.model_copy(update={"query": MapQuery(focus=["a", "b"], depth=1, exclusions="none")})
    first = indexer.execute(unsorted)
    second = indexer.execute(sorted_request)

    assert isinstance(first, Success)
    assert isinstance(second, Success)
    assert first.to_payload() == second.to_payload()


def test_find_ranks_complete_population_with_nested_duplicates_and_path_row_ids(tmp_path: Path) -> None:
    source = (
        "class Outer:\n"
        "    def same(self):\n"
        "        return 1\n"
        "    class Inner:\n"
        "        def same(self):\n"
        "            return 2\n"
    )
    (tmp_path / "a.py").write_text(source, encoding="utf-8")
    (tmp_path / "b.py").write_text(source, encoding="utf-8")
    indexer = XRayIndexer(tmp_path)
    request = FindRequest(
        root=str(tmp_path),
        query=FindQuery(text="same"),
        page=PageFind(limit=1),
        execution=Execution(cache="off"),
    )
    rows = []
    current = request
    while True:
        result = indexer.execute(current)
        assert isinstance(result, Success)
        rows.extend(result.data.items)
        if result.page is None or result.page.next_cursor is None:
            break
        current = request.model_copy(update={"page": PageFind(limit=1, cursor=result.page.next_cursor)})
    assert len(rows) == 4
    assert {(item.ref.path, item.qualified_name) for item in rows} == {
        ("a.py", "Outer.same"),
        ("a.py", "Outer.Inner.same"),
        ("b.py", "Outer.same"),
        ("b.py", "Outer.Inner.same"),
    }
    assert len({item.row_id for item in rows}) == len(rows)
    assert all("score" not in item.to_payload() for item in rows)


def test_interface_filters_before_member_expansion_and_exact_nested_owner_context(tmp_path: Path) -> None:
    source = (
        "class Outer:\n"
        "    def visible(self):\n"
        "        return 1\n"
        "    class Inner:\n"
        "        value: int = 2\n"
        "        def nested(self):\n"
        "            return 2\n"
        "\n"
        "def top():\n"
        "    return 3\n"
    )
    (tmp_path / "sample.py").write_text(source, encoding="utf-8")
    indexer = XRayIndexer(tmp_path)
    capture = _capture(tmp_path, "sample.py")
    artifact = indexer.declarations_for(capture.files[0])
    inner = next(item for item in artifact.declarations if item.qualified_name == "Outer.Inner")
    nested = next(item for item in artifact.declarations if item.qualified_name == "Outer.Inner.value")

    filtered = indexer.execute(
        InterfaceRequest(
            root=str(tmp_path),
            query=InterfaceFileQuery(
                target=FileTarget(kind="file", path="sample.py"),
                kinds=["class"],
                member_depth=1,
            ),
        )
    )
    assert isinstance(filtered, Success)
    assert [item.name for item in filtered.data.items if item.section == "symbols"] == [
        "Outer",
        "visible",
        "Inner",
        "value",
        "nested",
    ]

    exact_container = indexer.execute(
        InterfaceRequest(
            root=str(tmp_path),
            query=InterfaceSymbolQuery(target=inner.ref),
        )
    )
    assert isinstance(exact_container, Success)
    assert [item.name for item in exact_container.data.items] == ["Inner", "value", "nested"]
    assert exact_container.data.owners is None

    exact_member = indexer.execute(
        InterfaceRequest(
            root=str(tmp_path),
            query=InterfaceSymbolQuery(target=nested.ref),
        )
    )
    assert isinstance(exact_member, Success)
    assert [item.name for item in exact_member.data.items] == ["value"]
    assert exact_member.data.owners is not None
    assert [owner.name for owner in exact_member.data.owners] == ["Outer", "Inner"]


def test_interface_import_export_sections_are_flat_and_globally_paged(tmp_path: Path) -> None:
    (tmp_path / "sample.ts").write_text(
        'import main, {x as y, z} from "mod";\n'
        "export {y as q};\n"
        'export {z as alias} from "other";\n'
        'export * from "other";\n'
        "export default function run() {}\n",
        encoding="utf-8",
    )
    indexer = XRayIndexer(tmp_path)
    request = InterfaceRequest(
        root=str(tmp_path),
        query=InterfaceFileQuery(
            target=FileTarget(kind="file", path="sample.ts"),
            sections=["symbols", "imports", "exports"],
            member_depth=0,
        ),
        page=PageInterface(limit=1),
    )
    items = []
    current = request
    while True:
        result = indexer.execute(current)
        assert isinstance(result, Success)
        items.extend(result.data.items)
        if result.page is None or result.page.next_cursor is None:
            break
        current = request.model_copy(update={"page": PageInterface(limit=1, cursor=result.page.next_cursor)})
    sections = [item.section for item in items]
    assert sections == sorted(
        sections,
        key=lambda section: {"symbols": 0, "imports": 1, "exports": 2}[section],
    )
    imports = [item for item in items if item.section == "imports"]
    exports = [item for item in items if item.section == "exports"]
    assert any(item.module_text == "mod" and item.local_name == "y" for item in imports)
    assert any(item.kind == "reexport" and item.name == "alias" and item.module_text == "other" for item in exports)


def test_interface_declaration_discloses_clipped_signature_and_documentation(tmp_path: Path) -> None:
    parameters = ", ".join(f"argument_{index}" for index in range(400))
    documentation = "documentation " * 100
    (tmp_path / "sample.py").write_text(
        f'def target({parameters}):\n    """{documentation}"""\n    return 1\n',
        encoding="utf-8",
    )
    result = XRayIndexer(tmp_path).execute(
        InterfaceRequest(
            root=str(tmp_path),
            query=InterfaceFileQuery(
                target=FileTarget(kind="file", path="sample.py"),
                documentation=True,
                member_depth=0,
            ),
        )
    )

    assert isinstance(result, Success)
    declaration = next(item for item in result.data.items if item.section == "symbols")
    assert declaration.disclosure is not None
    assert declaration.disclosure.clipped == ["signature", "documentation"]
    assert len(declaration.signature.encode("utf-8")) <= 2048
    assert declaration.documentation is not None
    assert len(declaration.documentation.encode("utf-8")) <= 512


def test_declaration_cache_off_cold_warm_and_corrupt_entries_preserve_results(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text(
        "def known():\n    return 'body'\n",
        encoding="utf-8",
    )
    root_id = XRayIndexer(tmp_path).root.id
    cache = DerivedCache(root_id, cache_dir=tmp_path / "cache")
    indexer = XRayIndexer(tmp_path, cache=cache)
    off_request = FindRequest(
        root=str(tmp_path),
        query=FindQuery(text="known"),
        execution=Execution(cache="off"),
    )
    auto_request = off_request.model_copy(update={"execution": Execution(cache="auto")})
    off = indexer.execute(off_request)
    cold = indexer.execute(auto_request)
    warm = indexer.execute(auto_request)
    assert isinstance(off, Success) and isinstance(cold, Success) and isinstance(warm, Success)
    assert off.to_payload() == cold.to_payload() == warm.to_payload()
    entries = list(cache.namespace.glob("*.json"))
    assert entries
    entries[0].write_bytes(b"corrupt")
    corrupt = indexer.execute(auto_request)
    assert isinstance(corrupt, Success)
    assert corrupt.to_payload() == off.to_payload()

    symbol = off.data.items[0].ref
    read = indexer.execute(_request(tmp_path, [symbol]))
    assert isinstance(read, Success)
    assert read.data.items[0].source == "def known():\n    return 'body'"


def test_declaration_cache_rebinds_same_digest_to_requested_path(tmp_path: Path) -> None:
    source = "def same():\n    return 1\n"
    (tmp_path / "a.py").write_text(source, encoding="utf-8")
    (tmp_path / "b.py").write_text(source, encoding="utf-8")
    cache = DerivedCache(XRayIndexer(tmp_path).root.id, cache_dir=tmp_path / "cache")
    indexer = XRayIndexer(tmp_path, cache=cache)

    first = indexer.declarations_for(_capture(tmp_path, "a.py").files[0])
    second = indexer.declarations_for(_capture(tmp_path, "b.py").files[0])

    assert first.path == "a.py"
    assert second.path == "b.py"
    assert first.declarations[0].ref.path == "a.py"
    assert second.declarations[0].ref.path == "b.py"
