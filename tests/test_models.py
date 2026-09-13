"""High-value invariants for the strict next-major contract lane."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from threading import Event

import pytest
from pydantic import TypeAdapter, ValidationError

import xray.operations as operations_module
from xray.core.replacement import FilesystemHooks, GuardedChangeService
from xray.core.repository import OperationBudget
from xray.models import (
    MAX_REQUEST_JSON_BYTES,
    OPERATIONS,
    AdministrativeData,
    AdministrativeSuccess,
    CapabilitiesData,
    CapabilitiesQuery,
    CapabilitiesRequest,
    ChangeApplyMutation,
    ChangePlanQuery,
    ChangePlanRequest,
    Coverage,
    Dependency,
    Error,
    ErrorValue,
    FileCheckpoint,
    FindData,
    ImpactData,
    ImpactQuery,
    ImpactRequest,
    InterfaceData,
    InterfaceSymbolQuery,
    LimitCatalog,
    LiteralSearchSource,
    LocationTarget,
    MapData,
    MapQuery,
    OperationSummary,
    PageMap,
    PageRead,
    PatternChangeSource,
    ReadQuery,
    ReadRequest,
    RepositoryCursor,
    RepositoryProvenance,
    Root,
    SearchData,
    Selection,
    SourceRef,
    SourceRefUnion,
    Success,
    SymbolSourceRef,
    ToolchainComponent,
    ToolchainManifest,
    default_limit_catalog,
)
from xray.operations import (
    SchemaValidationError,
    execute,
    operation_contracts,
    rank_operations,
    schema_for_operation,
    validate_schema_document,
)
from xray.presentation import (
    bounded_canonical_size,
    canonical_bytes,
    decode_cursor,
    digest,
    encode_cursor,
    find_row_digest,
    plan_digest,
    repository_query_digest,
    request_json_size,
    root_digest,
)

D = "a" * 64


def test_closed_models_reject_extra_null_coercion_and_boolean_integers() -> None:
    with pytest.raises(ValidationError):
        MapQuery(depth=True)
    with pytest.raises(ValidationError):
        PageMap.model_validate({"limit": "10"})
    with pytest.raises(ValidationError):
        Selection.model_validate({"paths": [".", "src"], "unknown": True})
    with pytest.raises(ValidationError):
        SourceRef(kind="source", root_id=D, path="src/a.py", file_digest=D, start=2, end=1)
    with pytest.raises(ValidationError):
        SourceRef.model_validate(
            {"kind": "source", "root_id": D, "path": "src/a.py", "file_digest": D, "start": 0, "end": 1, "note": None}
        )


def test_schema_aliases_are_wire_stable_and_internal_names_are_rejected() -> None:
    payload = {"schema": "xray.v1", "ok": False, "error": {"code": "invalid_plan", "message": "bad"}}
    result = Error.model_validate(payload)

    assert result.to_payload() == payload
    properties = Error.model_json_schema()["properties"]
    assert "schema" in properties
    assert "schema_" not in properties
    with pytest.raises(ValidationError):
        Error.model_validate({**payload, "schema_": "xray.v1"})


def test_references_and_digests_are_exact() -> None:
    assert root_digest("/repo") == digest(["xray.root.v1", "/repo"])
    assert len(find_row_digest("a.py", 0, 1, D)) == 64
    with pytest.raises(ValidationError):
        SourceRef(kind="source", root_id="A" * 64, path="../a.py", file_digest=D, start=0, end=0)


def test_paths_and_reference_discriminators_stay_strict() -> None:
    with pytest.raises(ValidationError, match="4096-byte"):
        Root(path="/" + "é" * 2048, id=D)

    assert Selection(paths=["."]).paths == ["."]
    assert MapQuery(focus=["."], depth="all").depth == "all"
    with pytest.raises(ValidationError):
        MapQuery(depth=65)

    symbol = {
        "kind": "symbol",
        "root_id": D,
        "path": "src/a.py",
        "file_digest": D,
        "start": 0,
        "end": 0,
        "symbol_id": D,
        "analyzer_id": D,
    }
    assert isinstance(TypeAdapter(SourceRefUnion).validate_python(symbol), SymbolSourceRef)
    with pytest.raises(ValidationError):
        SourceRef.model_validate(symbol)


def test_canonical_json_is_sorted_utf8_without_ascii_escaping() -> None:
    assert canonical_bytes({"é": "值", "a": 1}) == '{"a":1,"é":"值"}'.encode()
    assert canonical_bytes({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_repository_cursor_binds_every_identity_and_rejects_noncanonical_tokens() -> None:
    cursor = RepositoryCursor(
        version=1,
        op="find",
        root=D,
        query="b" * 64,
        selection="c" * 64,
        snapshot="d" * 64,
        toolchain="e" * 64,
        checkpoint=FileCheckpoint(kind="file", index=2, after="f" * 64),
    )
    token = encode_cursor(cursor)
    assert decode_cursor(token) == cursor
    raw = base64.urlsafe_b64decode(token + "=")
    noncanonical = base64.urlsafe_b64encode(raw.replace(b'"op":"find"', b'"op":"find"')).decode().rstrip("=")
    assert decode_cursor(noncanonical) == cursor


def test_coverage_is_explicit_not_warning_reconstructed() -> None:
    with pytest.raises(ValidationError):
        Coverage(state="complete", basis="source_bytes", reasons=[])
    with pytest.raises(ValidationError):
        Coverage(state="partial", basis="source_bytes")


def test_apply_errors_always_carry_authoritative_mutation() -> None:
    error = Error(
        schema="xray.v1",
        ok=False,
        op="change_apply",
        error=ErrorValue(code="invalid_plan", message="plan is invalid"),
        mutation=ChangeApplyMutation(state="not_applied", rollback_status="not_attempted"),
    )
    assert error.to_payload()["mutation"] == {"rollback_status": "not_attempted", "state": "not_applied"}
    with pytest.raises(ValidationError):
        Error(schema="xray.v1", ok=False, op="change_apply", error=ErrorValue(code="invalid_plan", message="bad"))


def test_exact_symbol_interface_schema_and_model_are_symbols_only() -> None:
    schema = schema_for_operation("interface")
    symbol_schema = next(
        branch
        for branch in schema["properties"]["query"]["anyOf"]
        if branch["properties"]["target"] == {"$ref": "#/$defs/symbolRef"}
    )
    sections = symbol_schema["properties"]["sections"]
    assert sections["items"] == {"const": "symbols"}
    assert sections["minItems"] == 1
    assert sections["maxItems"] == 1
    assert sections["default"] == ["symbols"]

    target = SymbolSourceRef(
        kind="symbol",
        root_id=D,
        path="sample.py",
        file_digest=D,
        start=0,
        end=1,
        symbol_id=D,
        analyzer_id=D,
    )
    assert InterfaceSymbolQuery(target=target).sections == ["symbols"]
    for invalid in (["imports"], ["symbols", "symbols"], []):
        with pytest.raises(ValidationError):
            InterfaceSymbolQuery.model_validate({"target": target, "sections": invalid})


def test_literal_search_schema_and_model_require_one_utf8_byte() -> None:
    schema = schema_for_operation("search")
    literal_schema = next(
        source
        for source in schema["properties"]["query"]["properties"]["source"]["anyOf"]
        if source["properties"]["kind"] == {"const": "literal"}
    )
    assert literal_schema["properties"]["text"]["minLength"] == 1
    assert LiteralSearchSource(kind="literal", text="é").text == "é"
    with pytest.raises(ValidationError):
        LiteralSearchSource(kind="literal", text="")


def test_bounded_request_size_stops_at_the_frozen_limit() -> None:
    escaped = {"value": chr(34) + chr(92) + chr(10) + "é"}
    assert request_json_size(escaped, MAX_REQUEST_JSON_BYTES) == len(canonical_bytes(escaped))

    empty_size = request_json_size({"value": ""}, MAX_REQUEST_JSON_BYTES)
    exact = {"value": "a" * (MAX_REQUEST_JSON_BYTES - empty_size)}
    over = {"value": "a" * (MAX_REQUEST_JSON_BYTES - empty_size + 1)}
    assert bounded_canonical_size(exact, MAX_REQUEST_JSON_BYTES) == MAX_REQUEST_JSON_BYTES
    assert bounded_canonical_size(over, MAX_REQUEST_JSON_BYTES) == MAX_REQUEST_JSON_BYTES + 1

    result = execute({"op": "change_apply", "payload": "a" * MAX_REQUEST_JSON_BYTES})
    assert isinstance(result.value, Error)
    assert result.value.error.code == "execution_limit"
    assert result.value.mutation is not None
    assert result.value.mutation.to_payload() == {
        "state": "not_applied",
        "rollback_status": "not_attempted",
    }


def test_repository_query_digest_binds_final_semantic_inputs() -> None:
    query = {"text": "foo", "match": "name"}
    projection = {"fields": ["name"]}
    selection = {"paths": ["."]}
    snapshot = "b" * 64
    toolchain = "c" * 64
    actual = repository_query_digest("find", query, projection, selection, snapshot, toolchain)
    assert actual == digest(["xray.query.v1", "find", query, projection, selection, snapshot, toolchain])
    assert repository_query_digest("find", query, projection, selection, "d" * 64, toolchain) != actual


def test_capabilities_detail_uses_closed_typed_components() -> None:
    component = ToolchainComponent(version="1", artifact=D)
    manifest = ToolchainManifest(
        schema="xray.toolchain.v1",
        xray_revision="test",
        xray_artifact=D,
        ast_grep=component,
        ast_grep_py=component,
        python_ast=component,
        grammars=[],
        ranking=D,
        selection=D,
        parser=D,
    )
    summaries = [
        OperationSummary.model_validate(
            {
                "name": name,
                "description": f"{name}.",
                "mutation": "guarded_mutation" if name == "change_apply" else "read_only",
            }
        )
        for name in sorted(OPERATIONS, key=lambda item: item.encode("utf-8"))
    ]
    data = CapabilitiesData(
        version="1",
        schema="xray.v1",
        plan_schema="xray.change.v1",
        healthy=True,
        languages=["python", "javascript", "typescript", "go"],
        dependencies=[Dependency(name="ast-grep-py", state="available")],
        operations=summaries,
        limits=default_limit_catalog(),
        resources=["xray://workflow"],
        toolchain=manifest,
    )
    assert isinstance(data.limits, LimitCatalog)
    assert data.operations is not None
    assert isinstance(data.operations[0], OperationSummary)
    assert isinstance(data.toolchain, ToolchainManifest)
    assert data.to_payload()["resources"] == ["xray://workflow"]


def test_plan_digest_excludes_only_plan_digest_and_rejects_noncanonical_arrays() -> None:
    assert plan_digest is not None
    with pytest.raises(ValidationError):
        Selection(paths=["z", "a"])


def test_all_callable_schemas_are_closed_acyclic_and_bounded() -> None:
    for operation in OPERATIONS:
        schema = schema_for_operation(operation)
        report = validate_schema_document(schema)
        assert report["closure"] == "closed_acyclic"
        assert report["canonical_bytes"] <= 14_336


def test_schema_projection_omits_unreachable_definitions(monkeypatch: pytest.MonkeyPatch) -> None:
    definitions = operations_module._schema_defs()
    definitions["unused"] = {"type": "string"}
    monkeypatch.setattr(operations_module, "_schema_defs", lambda: definitions)

    schema = schema_for_operation("capabilities")

    assert set(schema["$defs"]) == {"execution"}
    assert "unused" not in schema["$defs"]


def test_schema_projection_preserves_recursive_reachability(monkeypatch: pytest.MonkeyPatch) -> None:
    definitions = operations_module._schema_defs()
    definitions.update(
        {
            "recursiveA": {"$ref": "#/$defs/recursiveB"},
            "recursiveB": {"$ref": "#/$defs/recursiveA"},
        }
    )
    original_query_schema = operations_module.operation_query_schema
    monkeypatch.setattr(operations_module, "_schema_defs", lambda: definitions)
    monkeypatch.setattr(
        operations_module,
        "operation_query_schema",
        lambda operation: (
            {"$ref": "#/$defs/recursiveA"} if operation == "capabilities" else original_query_schema(operation)
        ),
    )

    schema = schema_for_operation("capabilities")

    assert schema["$defs"]["recursiveA"] == {"$ref": "#/$defs/recursiveB"}
    assert schema["$defs"]["recursiveB"] == {"$ref": "#/$defs/recursiveA"}


def test_schema_projection_rejects_reachable_unresolved_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    definitions = operations_module._schema_defs()
    definitions["broken"] = {"$ref": "#/$defs/missing"}
    original_query_schema = operations_module.operation_query_schema
    monkeypatch.setattr(operations_module, "_schema_defs", lambda: definitions)
    monkeypatch.setattr(
        operations_module,
        "operation_query_schema",
        lambda operation: (
            {"$ref": "#/$defs/broken"} if operation == "capabilities" else original_query_schema(operation)
        ),
    )

    with pytest.raises(SchemaValidationError) as error:
        schema_for_operation("capabilities")

    assert error.value.code == "unresolved_ref"


def test_schema_projection_is_deterministically_canonical() -> None:
    first = schema_for_operation("change_plan")
    second = schema_for_operation("change_plan")

    assert first == second
    assert list(first["$defs"]) == sorted(first["$defs"], key=lambda name: name.encode("utf-8"))


def test_administrative_success_is_closed_and_fixed_bundle_ordered() -> None:
    result = AdministrativeSuccess(
        schema="xray.v1",
        ok=True,
        op="skill_install",
        data=AdministrativeData(
            scope="user",
            target="/home/user/.xray/skills",
            changed=True,
            replaced=False,
            files=["SKILL.md", "agents/openai.yaml"],
        ),
    )
    assert result.to_payload()["data"]["files"] == ["SKILL.md", "agents/openai.yaml"]


def test_execute_reads_real_request(tmp_path: Path) -> None:
    source = "value = 42\n"
    (tmp_path / "sample.py").write_text(source, encoding="utf-8")
    request = ReadRequest(
        root=str(tmp_path),
        query=ReadQuery(targets=[LocationTarget(kind="location", path="sample.py", line=1)]),
    )

    result = execute(request)

    assert isinstance(result.value, Success)
    assert result.ok is True
    assert result.value.data.items[0].source == source


def test_execute_searches_unknown_regular_text_files(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("needle\n", encoding="utf-8")
    (tmp_path / "extensionless").write_text("needle\n", encoding="utf-8")
    (tmp_path / "binary.data").write_bytes(b"\xff\x00needle")

    result = execute(
        {
            "op": "search",
            "root": str(tmp_path),
            "query": {"source": {"kind": "literal", "text": "needle"}},
        }
    )

    assert isinstance(result.value, Success)
    assert [(item.ref.path, item.text) for item in result.value.data.items] == [
        ("extensionless", "needle"),
        ("notes.md", "needle"),
    ]


def test_execute_dispatches_map_find_and_interface_with_typed_envelopes(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text(
        "class Sample:\n    def method(self):\n        return 1\n\ndef helper():\n    return Sample()\n",
        encoding="utf-8",
    )

    mapped = execute({"op": "map", "root": str(tmp_path), "query": {"depth": 2}})
    found = execute({"op": "find", "root": str(tmp_path), "query": {"text": "Sample", "match": "exact"}})
    interfaced = execute(
        {
            "op": "interface",
            "root": str(tmp_path),
            "query": {"target": {"kind": "file", "path": "sample.py"}},
        }
    )

    assert isinstance(mapped.value, Success)
    assert isinstance(mapped.value.data, MapData)
    assert [item.path for item in mapped.value.data.items] == ["sample.py"]
    assert mapped.value.coverage.state == "complete"
    assert isinstance(mapped.value.provenance, RepositoryProvenance)
    assert mapped.value.provenance.kind == "repository"
    assert mapped.value.page is not None and mapped.value.page.total == 1

    assert isinstance(found.value, Success)
    assert isinstance(found.value.data, FindData)
    assert [item.name for item in found.value.data.items] == ["Sample"]
    assert found.value.coverage.basis == "supported_declarations"
    assert found.value.provenance is not None

    assert isinstance(interfaced.value, Success)

    assert isinstance(interfaced.value.data, InterfaceData)
    assert [item.name for item in interfaced.value.data.items if item.section == "symbols"] == [
        "Sample",
        "method",
        "helper",
    ]
    assert interfaced.value.coverage.state == "complete"
    assert interfaced.value.provenance is not None


def test_execute_dispatches_literal_pattern_and_rule_search_with_evidence(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text(
        "def foo(value):\n    return value\n\nfoo(1)\nfoo(2)\n",
        encoding="utf-8",
    )
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "no-foo.yml").write_text(
        "id: no-foo-call\nlanguage: Python\nrule:\n  pattern: foo($A)\nseverity: warning\n",
        encoding="utf-8",
    )
    (tmp_path / "sgconfig.yml").write_text("ruleDirs:\n  - rules\n", encoding="utf-8")

    literal = execute(
        {
            "op": "search",
            "root": str(tmp_path),
            "query": {"source": {"kind": "literal", "text": "foo"}},
        }
    )
    pattern = execute(
        {
            "op": "search",
            "root": str(tmp_path),
            "query": {
                "source": {"kind": "pattern", "pattern": "foo($A)", "language": "python"},
                "detail": "detail",
            },
        }
    )
    rule = execute(
        {
            "op": "search",
            "root": str(tmp_path),
            "query": {"source": {"kind": "rule", "input": {"kind": "rule", "path": "rules/no-foo.yml"}}},
        }
    )

    assert isinstance(literal.value, Success)
    literal_success = literal.value
    assert isinstance(literal_success.data, SearchData)
    assert [(item.ref.path, item.text) for item in literal_success.data.items] == [
        ("rules/no-foo.yml", "foo"),
        ("rules/no-foo.yml", "foo"),
        ("sample.py", "foo"),
        ("sample.py", "foo"),
        ("sample.py", "foo"),
    ]

    assert isinstance(pattern.value, Success)
    assert isinstance(pattern.value.data, SearchData)
    assert pattern.value.data.items
    captures = pattern.value.data.items[0].captures
    assert captures and captures[0].refs
    assert pattern.value.coverage.basis == "pattern_matches"

    assert isinstance(rule.value, Success)
    assert isinstance(rule.value.data, SearchData)
    assert rule.value.data.items[0].rule_id == "no-foo-call"
    assert rule.value.coverage.basis == "rule_diagnostics"


def test_execute_dispatches_syntax_and_lexical_impact_envelopes(tmp_path: Path) -> None:
    (tmp_path / "dep.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (tmp_path / "use.py").write_text(
        "from dep import foo as bar\n\ndef wrapper():\n    return foo()\n\nbar()\n# foo\nvalue = 'foo'\n",
        encoding="utf-8",
    )
    found = execute({"op": "find", "root": str(tmp_path), "query": {"text": "foo", "match": "exact"}})
    assert isinstance(found.value, Success)
    target = next(item.ref for item in found.value.data.items if item.ref.path == "dep.py")

    syntax = execute(
        ImpactRequest(
            root=str(tmp_path),
            query=ImpactQuery(target=target, mode="syntax"),
        )
    )
    lexical = execute(
        ImpactRequest(
            root=str(tmp_path),
            query=ImpactQuery(target=target, mode="lexical"),
        )
    )

    assert isinstance(syntax.value, Success)
    assert isinstance(syntax.value.data, ImpactData)
    assert syntax.value.data.resolution == "unresolved"
    assert syntax.value.data.items
    assert all(item.evidence == "ast_syntax" for item in syntax.value.data.items)
    assert syntax.value.coverage.basis == "name_occurrences"

    assert isinstance(lexical.value, Success)
    assert isinstance(lexical.value.data, ImpactData)
    assert lexical.value.data.resolution == "unresolved"
    assert lexical.value.data.items
    assert all(item.evidence == "lexical" for item in lexical.value.data.items)


def test_syntax_impact_preserves_utf8_byte_geometry_and_parser_kinds(tmp_path: Path) -> None:
    (tmp_path / "dep.js").write_text("export function foo() {}\n", encoding="utf-8")
    (tmp_path / "use.js").write_text(
        'const café = 1;\nimport { foo as bar } from "./dep.js";\n// foo\nconst text = "foo";\nbar();\n',
        encoding="utf-8",
    )
    found = execute({"op": "find", "root": str(tmp_path), "query": {"text": "foo", "match": "exact"}})
    assert isinstance(found.value, Success)
    target = next(item.ref for item in found.value.data.items if item.ref.path == "dep.js")

    result = execute(
        ImpactRequest(
            root=str(tmp_path),
            query=ImpactQuery(target=target, mode="syntax"),
        )
    )

    assert isinstance(result.value, Success)
    rows = result.value.data.items
    assert [(item.kind, item.text, item.location.start.line) for item in rows] == [
        ("import", "foo", 2),
        ("comment", "foo", 3),
        ("string", "foo", 4),
    ]
    assert rows[0].location.start.byte == len("const café = 1;\nimport { ".encode())
    assert rows[0].location.start.column == 10
    assert rows[0].location.end.byte == rows[0].location.start.byte + len(b"foo")
    assert rows[0].location.end.column == 13


def test_execute_fitting_search_keeps_required_occurrence_evidence(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text("foo\nfoo\n", encoding="utf-8")
    request = {
        "op": "search",
        "root": str(tmp_path),
        "query": {"source": {"kind": "literal", "text": "foo"}},
        "page": {"limit": 1, "max_bytes": 4096},
    }

    first = execute(request)
    assert isinstance(first.value, Success)
    assert isinstance(first.value.data, SearchData)
    item = first.value.data.items[0]
    assert item.ref.occurrence_id
    assert item.location.start.line == 1
    assert item.text == "foo"
    assert first.value.page is not None and first.value.page.next_cursor

    second = execute({**request, "page": {"limit": 1, "max_bytes": 4096, "cursor": first.value.page.next_cursor}})
    assert isinstance(second.value, Success)
    assert isinstance(second.value.data, SearchData)
    assert second.value.data.items[0].ref.occurrence_id != item.ref.occurrence_id


def test_execute_returns_typed_reference_and_cursor_failures(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text("value = 42\n", encoding="utf-8")
    wrong_root = SourceRef(kind="source", root_id="b" * 64, path="sample.py", file_digest="c" * 64, start=0, end=1)
    reference_result = execute(
        ReadRequest(root=str(tmp_path), query=ReadQuery(targets=[wrong_root], include_enclosing=False))
    )
    cursor_result = execute(
        ReadRequest(
            root=str(tmp_path),
            query=ReadQuery(targets=[LocationTarget(kind="location", path="sample.py", line=1)]),
            page=PageRead(cursor="not-a-cursor"),
        )
    )

    assert isinstance(reference_result.value, Error)
    assert reference_result.value.error.code == "invalid_reference"
    assert isinstance(cursor_result.value, Error)
    assert cursor_result.value.error.code == "invalid_cursor"
    (tmp_path / "broken.yml").write_text("id: [", encoding="utf-8")
    invalid_rule = execute(
        {
            "op": "search",
            "root": str(tmp_path),
            "query": {"source": {"kind": "rule", "input": {"kind": "rule", "path": "broken.yml"}}},
        }
    )
    assert isinstance(invalid_rule.value, Error)
    assert invalid_rule.value.error.code == "invalid_rule"
    assert invalid_rule.value.op == "search"


def test_execute_splits_reads_at_utf8_boundaries_and_reconstructs_source(tmp_path: Path) -> None:
    source = "é" * 5000
    (tmp_path / "unicode.py").write_text(source, encoding="utf-8")
    target = LocationTarget(kind="location", path="unicode.py", line=1)
    cursor: str | None = None
    reconstructed: list[str] = []
    seen_cursors: set[str] = set()
    pages = 0
    while True:
        if cursor is None:
            page = PageRead(max_bytes=4096, source_bytes=32768)
        else:
            page = PageRead(max_bytes=4096, source_bytes=32768, cursor=cursor)
        result = execute(
            ReadRequest(
                root=str(tmp_path),
                query=ReadQuery(targets=[target], include_enclosing=False),
                page=page,
            )
        )
        assert isinstance(result.value, Success)
        assert len(canonical_bytes(result.value)) <= 4096
        reconstructed.extend(item.source for item in result.value.data.items)
        pages += 1
        assert result.value.page is not None
        next_cursor = result.value.page.next_cursor
        if next_cursor is None:
            break
        assert next_cursor not in seen_cursors
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    assert pages > 1
    assert "".join(reconstructed) == source


def test_capabilities_report_only_enabled_operations_rootless_and_rooted(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text("value = 42\n", encoding="utf-8")
    rootless = execute(CapabilitiesRequest(query=CapabilitiesQuery(detail="detail")))
    rooted = execute({"op": "capabilities", "root": str(tmp_path), "query": {"detail": "detail"}})
    summary = execute({"op": "capabilities", "query": {}})

    assert isinstance(rootless.value, Success)
    assert isinstance(rooted.value, Success)
    assert isinstance(summary.value, Success)
    expected = [
        "capabilities",
        "change_apply",
        "change_plan",
        "change_refine",
        "change_verify",
        "find",
        "impact",
        "interface",
        "map",
        "read",
        "search",
    ]
    assert [item["name"] for item in rootless.to_payload()["data"]["operations"]] == expected
    assert all("input_schema" not in item for item in rootless.to_payload()["data"]["operations"])
    assert [item["name"] for item in rooted.to_payload()["data"]["operations"]] == expected
    assert rooted.to_payload()["root"]["path"] == str(tmp_path)
    assert rooted.to_payload()["provenance"]["kind"] == "repository"
    assert "operations" not in summary.to_payload()["data"]
    assert [contract.name for contract in operation_contracts()] == expected


def test_capabilities_preserves_toolchain_observation_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget = OperationBudget(timeout_seconds=30)

    class CancellingProvider:
        def observe(self, *, budget: OperationBudget | None = None) -> None:
            assert budget is not None
            budget.cancel = lambda: True
            budget.check_deadline()

    monkeypatch.setattr(operations_module, "ToolchainProvider", CancellingProvider)
    result = execute(
        CapabilitiesRequest(query=CapabilitiesQuery(detail="detail")),
        budget=budget,
    )

    assert isinstance(result.value, Error)
    assert result.value.error.code == "execution_limit"


def test_execute_dispatches_complete_change_lifecycle_and_apply_failures(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("foo(1)\nfoo(2)\n", encoding="utf-8")
    planned = execute(
        ChangePlanRequest(
            root=str(tmp_path),
            query=ChangePlanQuery(
                source=PatternChangeSource(
                    kind="pattern",
                    pattern="foo($A)",
                    replacement="bar($A)",
                    language="python",
                )
            ),
        )
    )
    assert isinstance(planned.value, Success)
    plan = planned.value.data.plan
    assert "root" not in planned.to_payload()
    assert "scope" not in planned.to_payload()
    assert "provenance" not in planned.to_payload()
    assert plan.root.path == str(tmp_path)
    assert len(plan.edits) == 2
    assert target.read_text(encoding="utf-8") == "foo(1)\nfoo(2)\n"

    refined = execute(
        {
            "op": "change_refine",
            "root": str(tmp_path),
            "query": {"plan": plan.to_payload(), "edit_ids": [plan.edits[0].edit_id]},
        }
    )
    assert isinstance(refined.value, Success)
    refined_plan = refined.value.data.plan
    assert "root" not in refined.to_payload()
    assert "scope" not in refined.to_payload()
    assert "provenance" not in refined.to_payload()
    assert refined_plan.chosen.kind == "edits"
    assert [item.edit_id for item in refined_plan.edits] == [plan.edits[0].edit_id]

    verified = execute(
        {
            "op": "change_verify",
            "root": str(tmp_path),
            "query": {"plan": refined_plan.to_payload(), "expected_digest": refined_plan.plan_digest},
        }
    )
    assert isinstance(verified.value, Success)
    assert verified.value.data.ready is True
    assert verified.value.data.plan_digest == refined_plan.plan_digest

    applied = execute(
        {
            "op": "change_apply",
            "root": str(tmp_path),
            "query": {"plan": refined_plan.to_payload(), "expected_digest": refined_plan.plan_digest},
        }
    )
    assert isinstance(applied.value, Success)
    assert applied.value.data.state == "applied"
    assert applied.value.data.rollback_status == "not_attempted"
    assert applied.value.data.plan_digest == refined_plan.plan_digest
    assert target.read_text(encoding="utf-8") == "bar(1)\nfoo(2)\n"

    malformed = execute({"op": "change_apply"})
    assert isinstance(malformed.value, Error)
    assert malformed.value.mutation is not None
    assert malformed.value.mutation.to_payload() == {
        "state": "not_applied",
        "rollback_status": "not_attempted",
    }

    target.write_text("foo(9)\nfoo(2)\n", encoding="utf-8")
    drifted = execute(
        {
            "op": "change_apply",
            "root": str(tmp_path),
            "query": {"plan": refined_plan.to_payload(), "expected_digest": refined_plan.plan_digest},
        }
    )
    assert isinstance(drifted.value, Error)
    assert drifted.value.error.code == "plan_drift"
    assert drifted.value.mutation is not None
    assert drifted.value.mutation.state == "not_applied"
    assert drifted.value.mutation.rollback_status == "not_attempted"
    assert drifted.value.mutation.plan_digest == refined_plan.plan_digest
    if drifted.value.error.details is not None:
        assert "plan_digest" not in drifted.value.error.details.to_payload()

    def runtime_failure(_request: object) -> Success:
        raise RuntimeError("injected handler failure")

    runtime = execute(
        {
            "op": "change_apply",
            "root": str(tmp_path),
            "query": {"plan": refined_plan.to_payload(), "expected_digest": refined_plan.plan_digest},
        },
        handlers={"change_apply": runtime_failure},
    )
    assert isinstance(runtime.value, Error)
    assert runtime.value.error.code == "internal_error"
    assert runtime.value.mutation is not None
    assert runtime.value.mutation.state == "not_applied"
    assert runtime.value.mutation.rollback_status == "not_attempted"
    assert runtime.value.mutation.plan_digest == refined_plan.plan_digest


def test_completed_apply_outcome_survives_post_worker_cancellation(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("foo(1)\n", encoding="utf-8")
    planned = execute(
        ChangePlanRequest(
            root=str(tmp_path),
            query=ChangePlanQuery(
                source=PatternChangeSource(
                    kind="pattern",
                    pattern="foo($A)",
                    replacement="bar($A)",
                    language="python",
                )
            ),
        )
    )
    assert isinstance(planned.value, Success)
    plan = planned.value.data.plan
    request = {
        "op": "change_apply",
        "root": str(tmp_path),
        "query": {"plan": plan.to_payload(), "expected_digest": plan.plan_digest},
    }
    cancel = Event()
    budget = OperationBudget(timeout_seconds=30, cancel=cancel)
    apply_handler = operations_module.ApplicationService().handlers["change_apply"]

    def apply_then_cancel(normalized: object) -> Success | Error:
        result = apply_handler(normalized, budget=budget)  # type: ignore[call-arg]
        cancel.set()
        return result

    applied = execute(request, handlers={"change_apply": apply_then_cancel}, budget=budget)

    assert isinstance(applied.value, Success)
    assert applied.value.data.state == "applied"
    assert target.read_text(encoding="utf-8") == "bar(1)\n"


def test_rolled_back_apply_outcome_survives_post_worker_cancellation(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("foo(1)\n", encoding="utf-8")
    planned = execute(
        ChangePlanRequest(
            root=str(tmp_path),
            query=ChangePlanQuery(
                source=PatternChangeSource(
                    kind="pattern",
                    pattern="foo($A)",
                    replacement="bar($A)",
                    language="python",
                )
            ),
        )
    )
    assert isinstance(planned.value, Success)
    plan = planned.value.data.plan
    request = {
        "op": "change_apply",
        "root": str(tmp_path),
        "query": {"plan": plan.to_payload(), "expected_digest": plan.plan_digest},
    }
    cancel = Event()
    budget = OperationBudget(timeout_seconds=30, cancel=cancel)
    replace_count = 0

    def replace_then_cancel(source: Path, destination: Path) -> None:
        nonlocal replace_count
        replace_count += 1
        os.replace(source, destination)
        if replace_count == 1:
            cancel.set()

    application = operations_module.ApplicationService(
        change_service=GuardedChangeService(filesystem=FilesystemHooks(replace=replace_then_cancel))
    )
    apply_handler = application.handlers["change_apply"]

    def apply_with_injected_cancellation(normalized: object) -> Success | Error:
        return apply_handler(normalized, budget=budget)  # type: ignore[call-arg]

    rolled_back = execute(
        request,
        handlers={"change_apply": apply_with_injected_cancellation},
        budget=budget,
    )

    assert isinstance(rolled_back.value, Error)
    assert rolled_back.value.error.code == "apply_failed"
    assert rolled_back.value.mutation is not None
    assert rolled_back.value.mutation.state == "rolled_back"
    assert rolled_back.value.mutation.rollback_status == "succeeded"
    assert target.read_text(encoding="utf-8") == "foo(1)\n"


def test_call_tool_normalization_preserves_recognized_operation_errors() -> None:
    recognized = execute({"name": "read", "arguments": {}})
    unknown = execute({"name": "future_operation", "arguments": {}})

    assert isinstance(recognized.value, Error)
    assert recognized.value.error.code == "invalid_request"
    assert recognized.value.op == "read"
    assert isinstance(unknown.value, Error)
    assert unknown.value.error.code == "unknown_operation"
    assert unknown.value.op == "call_tool"


def test_intent_ranking_uses_operation_concepts_and_precedence() -> None:
    cases = (
        ("show the source namespace", "map"),
        ("locate the named declaration", "find"),
        ("list the module's exported members", "interface"),
        ("retrieve the selected implementation body", "read"),
        ("trace callers and references", "impact"),
        ("scan for a structural expression", "search"),
        ("prepare a reviewable replacement", "change_plan"),
        ("narrow the reviewed edit selection", "change_refine"),
        ("check the plan digest before apply", "change_verify"),
        ("write the approved patch", "change_apply"),
        ("describe the service health", "capabilities"),
    )
    for intent, expected in cases:
        assert rank_operations(intent)[0] == expected

    assert rank_operations("please explain the weather") == ()
    assert rank_operations("apply a checked rule to source files")[0] == "search"
    assert rank_operations("lookup", ("read",)) == ("read",)


def test_default_operation_contracts_are_cached_and_deeply_immutable() -> None:
    contracts = operation_contracts()
    properties = contracts[0].input_schema.properties
    assert properties is not None
    with pytest.raises(TypeError):
        properties["unexpected"] = {}
    required = contracts[0].input_schema.required
    assert required is not None
    with pytest.raises(TypeError):
        required.append("query")

    assert contracts == operation_contracts()
    custom = operation_contracts(
        handlers={
            "map": lambda _request: Error(
                schema="xray.v1", ok=False, error=ErrorValue(code="invalid_request", message="unused")
            )
        }
    )
    assert custom is not contracts
    assert [contract.name for contract in custom] == ["map"]
