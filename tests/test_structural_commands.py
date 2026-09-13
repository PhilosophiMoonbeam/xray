from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from xray.core import indexer as indexer_module
from xray.core.indexer import XRayIndexer
from xray.core.repository import RepositoryProvider
from xray.models import (
    Execution,
    ImpactArguments,
    ImpactQuery,
    LiteralSearchSource,
    PageImpact,
    PageSearch,
    PatternSearchSource,
    RuleInput,
    RuleSearchSource,
    SearchArguments,
    SearchQuery,
    Selection,
    Success,
)


def _capture(root: Path, *paths: str):
    return RepositoryProvider(
        root,
        {"paths": sorted(paths), "exclusions": "none"},
    ).capture(include_namespace=False)


def _collect_search(indexer: XRayIndexer, request: SearchArguments, limit: int):
    rows = []
    cursor = None
    while True:
        if cursor is None:
            page = PageSearch(limit=limit)
        else:
            page = PageSearch(limit=limit, cursor=cursor)
        result = indexer.execute(request.model_copy(update={"page": page}))
        assert isinstance(result, Success), result
        assert result.page is not None
        rows.extend(result.data.items)
        cursor = result.page.next_cursor
        if cursor is None:
            return rows, result


def _collect_impact(indexer: XRayIndexer, request: ImpactArguments, limit: int):
    rows = []
    cursor = None
    while True:
        if cursor is None:
            page = PageImpact(limit=limit)
        else:
            page = PageImpact(limit=limit, cursor=cursor)
        result = indexer.execute(request.model_copy(update={"page": page}))
        assert isinstance(result, Success), result
        assert result.page is not None
        rows.extend(result.data.items)
        cursor = result.page.next_cursor
        if cursor is None:
            return rows, result


def _declaration_ref(root: Path, path: str, name: str):
    indexer = XRayIndexer(root)
    capture = _capture(root, path)
    captured = next(item for item in capture.files if item.path == path)
    artifact = indexer.declarations_for(captured)
    return next(item.ref for item in artifact.declarations if item.name == name)


def test_literal_search_is_utf8_exact_non_overlapping_and_paged(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("café café\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("café\n", encoding="utf-8")
    (tmp_path / "binary.py").write_bytes(b"\x00caf\xc3\xa9")
    indexer = XRayIndexer(tmp_path)
    request = SearchArguments(
        root=str(tmp_path),
        query=SearchQuery(
            source=LiteralSearchSource(kind="literal", text="café"),
            selection=Selection(paths=["a.py", "b.py", "binary.py"]),
        ),
        execution=Execution(cache="off"),
    )

    rows, last = _collect_search(indexer, request, limit=1)

    assert [(item.ref.path, item.text) for item in rows] == [
        ("a.py", "café"),
        ("a.py", "café"),
        ("b.py", "café"),
    ]
    assert rows[0].ref.start == 0
    assert rows[1].ref.start == len("café ".encode())
    assert rows[2].ref.start == 0
    assert last.coverage.state == "partial"
    assert any(reason.code == "non_text_input" for reason in last.coverage.reasons or [])
    assert last.coverage.basis == "literal_occurrences"


def test_pattern_search_detail_exposes_verified_named_captures(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text(
        "def foo(a, b):\n    return a + b\n\nfoo(1, 2)\nfoo(3, 4)\n",
        encoding="utf-8",
    )
    indexer = XRayIndexer(tmp_path)
    request = SearchArguments(
        root=str(tmp_path),
        query=SearchQuery(
            source=PatternSearchSource(
                kind="pattern",
                pattern="foo($A, $$$ARGS)",
                language="python",
            ),
            detail="detail",
        ),
        execution=Execution(cache="off"),
    )

    rows, result = _collect_search(indexer, request, limit=10)

    assert [item.text for item in rows] == ["foo(1, 2)", "foo(3, 4)"]
    assert result.coverage.state == "complete"
    assert result.coverage.basis == "pattern_matches"
    for item, expected in zip(rows, ["1", "3"]):
        captures = {capture.name: capture for capture in item.captures or []}
        assert captures["A"].kind == "single"
        assert captures["A"].text == expected
        assert captures["A"].refs
        assert captures["ARGS"].kind == "multi"
        assert captures["ARGS"].refs


def test_transformed_capture_is_clipped_only_by_the_disclosing_limiter(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text("foo(1)\n", encoding="utf-8")
    indexer = XRayIndexer(tmp_path)
    captured = _capture(tmp_path, "sample.py").files[0]
    geometry = indexer_module._SourceGeometry.from_text("foo(1)\n", data=captured.content)
    transformed = "é" * 400

    captures, verified = indexer._capture_values(
        {"metaVariables": {"transformed": {"VALUE": {"text": transformed}}}},
        captured,
        geometry,
    )

    assert verified is True
    assert captures[0].text == transformed
    rows, _ = _collect_search(
        indexer,
        SearchArguments(
            root=str(tmp_path),
            query=SearchQuery(
                source=PatternSearchSource(kind="pattern", pattern="foo($A)", language="python"),
                detail="detail",
            ),
            execution=Execution(cache="off"),
        ),
        limit=10,
    )
    limited = indexer._limit_search_captures(rows[0].model_copy(update={"captures": list(captures)}))
    assert limited.captures is not None
    assert limited.captures[0].text is not None
    assert len(limited.captures[0].text.encode("utf-8")) <= 512
    assert limited.disclosure is not None
    assert limited.disclosure.clipped == ["captures"]


def test_rule_search_supports_standalone_and_config_inputs(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text("def foo(value):\n    return value\n\nfoo(1)\n", encoding="utf-8")
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "no-foo.yml").write_text(
        "id: no-foo-call\nlanguage: Python\nrule:\n  pattern: foo($A)\nseverity: warning\n",
        encoding="utf-8",
    )
    (tmp_path / "sgconfig.yml").write_text("ruleDirs:\n  - rules\n", encoding="utf-8")
    indexer = XRayIndexer(tmp_path)
    selection = Selection(languages=["python"])

    for source in (
        RuleSearchSource(kind="rule", input=RuleInput(kind="rule", path="rules/no-foo.yml")),
        RuleSearchSource(kind="rule", input=RuleInput(kind="config", path="sgconfig.yml")),
    ):
        request = SearchArguments(
            root=str(tmp_path),
            query=SearchQuery(source=source, selection=selection),
            execution=Execution(cache="off"),
        )
        rows, result = _collect_search(indexer, request, limit=10)
        assert [item.text for item in rows] == ["foo(1)"]
        assert rows[0].rule_id == "no-foo-call"
        assert result.coverage.state == "complete"
        assert result.coverage.basis == "rule_diagnostics"


def test_impact_syntax_and_lexical_are_unresolved_exact_refs_and_paged(tmp_path: Path) -> None:
    (tmp_path / "dep.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (tmp_path / "use.py").write_text(
        "from dep import foo as bar\n\ndef wrapper():\n    return foo()\n\nbar()\n# foo\nvalue = 'foo'\n",
        encoding="utf-8",
    )
    (tmp_path / "binary.py").write_bytes(b"\x00foo")
    target = _declaration_ref(tmp_path, "dep.py", "foo")
    indexer = XRayIndexer(tmp_path)

    syntax_request = ImpactArguments(
        root=str(tmp_path),
        query=ImpactQuery(
            target=target,
            selection=Selection(paths=["binary.py", "dep.py", "use.py"]),
            mode="syntax",
        ),
        execution=Execution(cache="off"),
    )
    syntax_rows, syntax_result = _collect_impact(indexer, syntax_request, limit=1)

    assert [item.kind for item in syntax_rows] == ["import", "call", "comment", "string"]
    assert [item.text for item in syntax_rows] == ["foo", "foo", "foo", "foo"]
    assert all(item.evidence == "ast_syntax" for item in syntax_rows)
    assert syntax_rows[0].import_ is not None
    assert syntax_rows[0].import_.imported_name == "foo"
    assert syntax_rows[1].enclosing is not None
    assert syntax_rows[1].enclosing.state == "found"
    assert syntax_result.data.resolution == "unresolved"
    assert syntax_result.coverage.state == "partial"
    assert any(reason.code == "non_text_input" for reason in syntax_result.coverage.reasons or [])

    lexical_request = syntax_request.model_copy(
        update={
            "query": ImpactQuery(
                target=target,
                selection=Selection(paths=["binary.py", "dep.py", "use.py"]),
                mode="lexical",
            )
        }
    )
    lexical_rows, lexical_result = _collect_impact(indexer, lexical_request, limit=2)

    assert [item.kind for item in lexical_rows] == ["text", "text", "text", "text"]
    assert all(item.evidence == "lexical" for item in lexical_rows)
    assert {item.ref.path for item in lexical_rows} == {"use.py"}
    assert lexical_result.data.basis == "name_occurrences"
    assert lexical_result.coverage.state == "partial"


@pytest.mark.parametrize(
    "language,filename,source",
    [
        (
            "python",
            "use.py",
            'def foo():\n    return 1\n\nfoo()\nobj.foo()\n# foo()\nvalue = "foo"\n',
        ),
        (
            "javascript",
            "use.js",
            'function foo() {}\nfoo();\nobj.foo();\n// foo()\nconst value = "foo";\n',
        ),
        (
            "typescript",
            "use.ts",
            'function foo(): void {}\nfoo();\nobj.foo();\n// foo()\nconst value = "foo";\n',
        ),
        (
            "go",
            "use.go",
            'package p\nfunc foo() {}\nfunc run() { foo(); obj.foo() }\n// foo()\nvar value = "foo"\n',
        ),
    ],
)
def test_syntax_impact_uses_parser_provenance_for_four_supported_languages(
    tmp_path: Path,
    language: str,
    filename: str,
    source: str,
) -> None:
    del language
    (tmp_path / "dep.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (tmp_path / filename).write_text(source, encoding="utf-8")
    target = _declaration_ref(tmp_path, "dep.py", "foo")
    request = ImpactArguments(
        root=str(tmp_path),
        query=ImpactQuery(
            target=target,
            selection=Selection(paths=["dep.py", filename]),
            mode="syntax",
        ),
        execution=Execution(cache="off"),
    )

    rows, result = _collect_impact(XRayIndexer(tmp_path), request, limit=100)

    use_rows = [item for item in rows if item.ref.path == filename]
    assert [item.kind for item in use_rows] == ["definition", "call", "call", "comment", "string"]
    assert [item.evidence for item in use_rows] == ["ast_syntax"] * 5
    assert [item.text for item in use_rows] == ["foo"] * 5
    assert result.coverage.state == "complete"


def test_mcp_config_generator_rejects_container_method() -> None:
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parents[1] / "mcp-config-generator.py"), "cursor", "docker"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Unsupported method" in result.stdout
    assert "mcpServers" not in result.stdout
