"""Focused behavioral coverage for XRAY's standard FastMCP surface."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from xray import mcp_server
from xray.operations import execute, operation_contracts
from xray.presentation import canonical_json

EXPECTED_OPERATION_NAMES = (
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
)
ENABLED_OPERATION_NAMES = tuple(contract.name for contract in operation_contracts())

ROOT = Path(__file__).parents[1]


def semantic(result: Any) -> dict[str, Any]:
    value = result.structured_content
    assert isinstance(value, dict)
    assert result.content
    assert result.content[0].type == "text"
    assert result.content[0].text == canonical_json(value)
    assert json.loads(result.content[0].text) == value
    assert result.is_error is (value.get("ok") is False)
    return cast(dict[str, Any], value)


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text("value = 42\n", encoding="utf-8")
    return repo


async def in_process_client():
    from fastmcp import Client

    return Client(mcp_server.mcp)


def test_standard_tools_list_has_exactly_two_raw_adapter_tools() -> None:
    async def exercise() -> list[Any]:
        async with await in_process_client() as client:
            return await client.list_tools()

    tools = asyncio.run(exercise())
    assert [tool.name for tool in tools] == ["search_tools", "call_tool"]

    search, call = tools
    assert ENABLED_OPERATION_NAMES == EXPECTED_OPERATION_NAMES
    assert len(search.inputSchema["oneOf"]) == 3
    assert set(call.inputSchema["properties"]) == {"name", "arguments"}
    assert call.inputSchema["properties"]["arguments"] == {"type": "object", "additionalProperties": True}
    assert call.inputSchema["properties"]["name"]["enum"] == list(EXPECTED_OPERATION_NAMES)
    assert search.annotations.readOnlyHint is True
    assert search.annotations.destructiveHint is False
    assert search.annotations.idempotentHint is True
    assert search.annotations.openWorldHint is False
    assert call.annotations.readOnlyHint is False
    assert call.annotations.destructiveHint is True
    assert call.annotations.idempotentHint is False
    assert call.annotations.openWorldHint is False


def test_discovery_publishes_complete_enabled_contract_and_seek_cursor() -> None:
    async def exercise() -> tuple[dict[str, Any], list[Any], Any, Any, Any]:
        async with await in_process_client() as client:
            exact = {
                name: await client.call_tool(
                    "search_tools",
                    {"mode": "exact", "query": name, "max_bytes": 16384},
                    raise_on_error=False,
                )
                for name in ENABLED_OPERATION_NAMES
            }
            pages: list[Any] = []
            page = await client.call_tool(
                "search_tools", {"mode": "catalog", "limit": 1, "max_bytes": 16384}, raise_on_error=False
            )
            while True:
                pages.append(page)
                cursor = semantic(page)["page"].get("next_cursor")
                if cursor is None:
                    break
                page = await client.call_tool(
                    "search_tools",
                    {"mode": "catalog", "limit": 1, "max_bytes": 16384, "cursor": cursor},
                    raise_on_error=False,
                )
            first_cursor = semantic(pages[0])["page"]["next_cursor"]
            invalid_cursor = await client.call_tool(
                "search_tools",
                {"mode": "catalog", "limit": 1, "max_bytes": 16384, "cursor": "not-a-cursor"},
                raise_on_error=False,
            )
            mismatched_cursor = await client.call_tool(
                "search_tools",
                {"mode": "intent", "query": "search", "limit": 1, "max_bytes": 16384, "cursor": first_cursor},
                raise_on_error=False,
            )
            unknown = await client.call_tool(
                "search_tools", {"mode": "exact", "query": "scan", "max_bytes": 16384}, raise_on_error=False
            )
            return exact, pages, invalid_cursor, mismatched_cursor, unknown

    exact, pages, invalid_cursor, mismatched_cursor, unknown = asyncio.run(exercise())
    expected_contracts = {item.name: item.to_payload() for item in operation_contracts()}
    for name, response in exact.items():
        value = semantic(response)
        assert value["op"] == "search_tools"
        assert value["data"]["best"] == expected_contracts[name]
        assert value["data"]["alternatives"] == []
        assert value["page"] == {"total": 1}

    values = [semantic(page) for page in pages]
    assert [value["data"]["best"]["name"] for value in values] == list(EXPECTED_OPERATION_NAMES)
    assert len(values) == len(EXPECTED_OPERATION_NAMES) == 11
    for value in values:
        contract = value["data"]["best"]
        assert contract["input_schema"]["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert contract["input_schema"]["type"] == "object"
        assert contract["input_schema"]["additionalProperties"] is False
        assert contract["input_schema"]["required"] == (
            ["query"] if contract["name"] == "capabilities" else ["root", "query"]
        )
        assert contract["mutation"] == ("guarded_mutation" if contract["name"] == "change_apply" else "read_only")
        if contract["name"] in {"change_plan", "change_refine", "change_verify", "change_apply"}:
            assert "page" not in contract["input_schema"]["properties"]
        assert value["data"]["alternatives"] == []
        assert value["page"]["total"] == len(EXPECTED_OPERATION_NAMES)
    assert all("next_cursor" in value["page"] for value in values[:-1])
    assert "next_cursor" not in values[-1]["page"]
    assert semantic(invalid_cursor)["error"]["code"] == "invalid_cursor"
    assert semantic(mismatched_cursor)["error"]["code"] == "cursor_query_mismatch"
    assert semantic(unknown)["error"]["code"] == "unknown_operation"


@pytest.mark.parametrize(("query", "expected"), (("lookup", "read"), ("change code", "change_plan")))
def test_default_intent_discovery_fits_minimum_budget(query: str, expected: str) -> None:
    async def exercise() -> Any:
        async with await in_process_client() as client:
            return await client.call_tool("search_tools", {"query": query}, raise_on_error=False)

    response = asyncio.run(exercise())
    value = semantic(response)

    assert value["ok"] is True
    assert value["data"]["best"]["name"] == expected
    assert len(canonical_json(value).encode("utf-8")) <= 4096


def test_tools_call_enabled_operations_preserve_core_semantics_and_strict_errors(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "navigation.py").write_text(
        "class Sample:\n    def method(self):\n        return 1\n\ndef helper():\n    return Sample()\n",
        encoding="utf-8",
    )
    find_arguments = {"root": str(repo), "query": {"text": "Sample", "match": "exact"}}
    find_value = execute({"op": "find", **find_arguments}).to_payload()
    target = find_value["data"]["items"][0]["ref"]
    operation_arguments: dict[str, dict[str, Any]] = {
        "map": {"root": str(repo), "query": {"depth": 2}},
        "find": find_arguments,
        "interface": {
            "root": str(repo),
            "query": {"target": {"kind": "file", "path": "navigation.py"}},
        },
        "read": {"root": str(repo), "query": {"targets": [{"kind": "location", "path": "sample.py", "line": 1}]}},
        "impact": {"root": str(repo), "query": {"target": target, "mode": "syntax"}},
        "search": {
            "root": str(repo),
            "query": {"source": {"kind": "literal", "text": "Sample"}, "detail": "summary"},
        },
        "capabilities": {"query": {"detail": "detail"}},
    }

    async def exercise() -> tuple[list[tuple[str, dict[str, Any], Any]], Any]:
        async with await in_process_client() as client:
            responses = [
                (
                    name,
                    arguments,
                    await client.call_tool(
                        "call_tool",
                        {"name": name, "arguments": arguments},
                        raise_on_error=False,
                    ),
                )
                for name, arguments in operation_arguments.items()
            ]
            invalid = await client.call_tool(
                "call_tool", {"name": "read", "arguments": {"query": {}}}, raise_on_error=False
            )
            return responses, invalid

    responses, invalid = asyncio.run(exercise())
    for name, arguments, response in responses:
        assert semantic(response) == execute({"op": name, **arguments}).to_payload()
    invalid_value = semantic(invalid)
    assert invalid.is_error is True
    assert invalid_value["error"]["code"] == "invalid_request"


def test_search_sources_and_impact_modes_preserve_core_semantics(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "dep.py").write_text("def foo(value):\n    return value\n", encoding="utf-8")
    (repo / "use.py").write_text(
        "from dep import foo\n\nfoo(1)\n# foo\nvalue = 'foo'\n",
        encoding="utf-8",
    )
    (repo / "rules").mkdir()
    (repo / "rules" / "no-foo.yml").write_text(
        "id: no-foo-call\nlanguage: Python\nrule:\n  pattern: foo($A)\nseverity: warning\n",
        encoding="utf-8",
    )
    (repo / "sgconfig.yml").write_text("ruleDirs:\n  - rules\n", encoding="utf-8")

    find_arguments = {"root": str(repo), "query": {"text": "foo", "match": "exact"}}
    find_value = execute({"op": "find", **find_arguments}).to_payload()
    target = next(item["ref"] for item in find_value["data"]["items"] if item["ref"]["path"] == "dep.py")
    requests: list[tuple[str, dict[str, Any]]] = [
        (
            "search",
            {
                "root": str(repo),
                "query": {
                    "source": {"kind": "literal", "text": "foo"},
                    "selection": {"languages": ["python"]},
                    "detail": "summary",
                },
            },
        ),
        (
            "search",
            {
                "root": str(repo),
                "query": {
                    "source": {"kind": "pattern", "pattern": "foo($A)", "language": "python"},
                    "selection": {"languages": ["python"]},
                    "detail": "detail",
                },
            },
        ),
        (
            "search",
            {
                "root": str(repo),
                "query": {
                    "source": {"kind": "rule", "input": {"kind": "config", "path": "sgconfig.yml"}},
                    "selection": {"languages": ["python"]},
                },
            },
        ),
        (
            "impact",
            {
                "root": str(repo),
                "query": {"target": target, "selection": {"languages": ["python"]}, "mode": "syntax"},
            },
        ),
        (
            "impact",
            {
                "root": str(repo),
                "query": {"target": target, "selection": {"languages": ["python"]}, "mode": "lexical"},
            },
        ),
    ]

    async def exercise() -> list[tuple[str, dict[str, Any], Any]]:
        async with await in_process_client() as client:
            return [
                (
                    name,
                    arguments,
                    await client.call_tool(
                        "call_tool",
                        {"name": name, "arguments": arguments},
                        raise_on_error=False,
                    ),
                )
                for name, arguments in requests
            ]

    responses = asyncio.run(exercise())
    values = [semantic(response) for _, _, response in responses]
    for (name, arguments, _), value in zip(responses, values):
        assert value == execute({"op": name, **arguments}).to_payload()
    assert values[0]["coverage"]["basis"] == "literal_occurrences"
    assert values[1]["coverage"]["basis"] == "pattern_matches"
    assert values[2]["coverage"]["basis"] == "rule_diagnostics"


def test_invalid_routing_and_removed_operations_are_domain_errors() -> None:
    async def exercise() -> tuple[Any, list[Any], Any, Any]:
        async with await in_process_client() as client:
            missing = await client.call_tool("call_tool", {"arguments": {}}, raise_on_error=False)
            removed = [
                await client.call_tool("call_tool", {"name": name, "arguments": {}}, raise_on_error=False)
                for name in ("replace", "rewrite", "scan-fix")
            ]
            bad_discovery = await client.call_tool(
                "search_tools", {"pattern": "read", "max_bytes": 16384}, raise_on_error=False
            )
            bad_arguments = await client.call_tool(
                "call_tool",
                {
                    "name": "search",
                    "arguments": {
                        "root": str(ROOT),
                        "query": {"source": {"kind": "literal", "text": "read"}},
                        "confidence": 0.5,
                    },
                },
                raise_on_error=False,
            )
            return missing, removed, bad_discovery, bad_arguments

    missing, removed, bad_discovery, bad_arguments = asyncio.run(exercise())
    assert semantic(missing)["op"] == "call_tool"
    assert semantic(missing)["error"]["code"] == "invalid_request"
    for response in removed:
        assert semantic(response)["op"] == "call_tool"
        assert semantic(response)["error"]["code"] == "unknown_operation"
    assert semantic(bad_discovery)["op"] == "search_tools"
    assert semantic(bad_discovery)["error"]["code"] == "invalid_request"
    assert semantic(bad_arguments)["op"] == "search"
    assert semantic(bad_arguments)["error"]["code"] == "invalid_request"


def test_call_tool_recognizes_selected_apply_before_outer_and_inner_validation() -> None:
    async def exercise() -> list[dict[str, Any]]:
        values = [
            await mcp_server._call_tool({"name": "change_apply"}),
            await mcp_server._call_tool({"name": "change_apply", "arguments": None}),
            await mcp_server._call_tool({"name": "change_apply", "arguments": {}, "extra": True}),
            await mcp_server._call_tool({"name": "change_apply", "arguments": {"op": "map"}}),
            await mcp_server._call_tool(
                "not-a-dict"  # type: ignore[arg-type]
            ),
        ]
        return [semantic(value) for value in values]

    values = asyncio.run(exercise())
    for value in values[:4]:
        assert value["op"] == "change_apply"
        assert value["error"]["code"] == "invalid_request"
        assert value["mutation"] == {"rollback_status": "not_attempted", "state": "not_applied"}
    assert values[4]["op"] == "call_tool"
    assert values[4]["error"]["code"] == "invalid_request"


def test_apply_timeout_returns_worker_outcome_and_releases_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    prepared = SimpleNamespace(
        root=None,
        request=SimpleNamespace(execution=SimpleNamespace(timeout_seconds=0.001)),
    )
    started = threading.Event()
    calls = 0

    def fake_prepare(_: Any) -> Any:
        return prepared

    def fake_execute(_: Any, *, budget: Any = None) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            assert budget is not None
            while not budget.cancel.is_set():
                budget.cancel.wait(0.001)
            return {
                "schema": "xray.v1",
                "ok": False,
                "op": "change_apply",
                "error": {"code": "internal_error", "message": "worker completed after cancellation"},
                "mutation": {"state": "not_applied", "rollback_status": "not_attempted"},
            }
        return {"schema": "xray.v1", "ok": True, "op": "map", "data": {}}

    monkeypatch.setattr(mcp_server, "prepare_request", fake_prepare)
    monkeypatch.setattr(mcp_server, "execute", fake_execute)

    async def exercise() -> tuple[dict[str, Any], dict[str, Any]]:
        timed_out = await mcp_server._call_tool({"name": "change_apply", "arguments": {}})
        recovered = await mcp_server._call_tool({"name": "map", "arguments": {}})
        return semantic(timed_out), semantic(recovered)

    timed_out, recovered = asyncio.run(exercise())
    assert started.is_set()
    assert timed_out["error"]["code"] == "internal_error"
    assert timed_out["mutation"] == {"state": "not_applied", "rollback_status": "not_attempted"}
    assert recovered == {"schema": "xray.v1", "ok": True, "op": "map", "data": {}}


def test_admission_uses_normalized_root_identity_for_aliases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text("value = 42\n", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(repo, target_is_directory=True)
    entered = threading.Event()
    release = threading.Event()
    original_execute = mcp_server.execute

    def blocked_execute(request: Any, *, budget: Any = None, cancel: Any = None) -> Any:
        entered.set()
        release.wait(timeout=5)
        return original_execute(request, budget=budget, cancel=cancel)

    monkeypatch.setattr(mcp_server, "execute", blocked_execute)

    async def exercise() -> tuple[Any, list[dict[str, Any]]]:
        first = asyncio.create_task(
            mcp_server._call_tool({"name": "map", "arguments": {"root": str(repo), "query": {"depth": 0}}})
        )
        assert await asyncio.to_thread(entered.wait, 5)
        aliases = (str(repo) + "/", str(repo) + "/.", str(link), str(link) + "/.")
        blocked = [
            semantic(await mcp_server._call_tool({"name": "map", "arguments": {"root": alias, "query": {"depth": 0}}}))
            for alias in aliases
        ]
        release.set()
        return await first, blocked

    first, blocked = asyncio.run(exercise())
    assert semantic(first)["ok"] is True
    assert all(value["error"]["code"] == "execution_limit" for value in blocked)


def test_raw_stdio_forwarder_discards_over_limit_and_unterminated_frames() -> None:
    def exercise(payload: bytes) -> bytes:
        source_read, source_write = os.pipe()
        sink_read, sink_write = os.pipe()
        stop = threading.Event()
        worker = threading.Thread(
            target=mcp_server._bounded_stdio_forwarder,
            args=(source_read, sink_write, stop),
        )
        worker.start()
        try:
            offset = 0
            while offset < len(payload):
                try:
                    offset += os.write(source_write, payload[offset : offset + 65_536])
                except BrokenPipeError:
                    break
        finally:
            os.close(source_write)
        worker.join(timeout=5)
        assert not worker.is_alive()
        try:
            return os.read(sink_read, 1)
        finally:
            os.close(sink_read)

    assert exercise(b"x" * (mcp_server.MAX_STDIO_FRAME_BYTES + 1) + b"\n") == b""
    assert exercise(b"x" * 100_000) == b""


def test_resources_templates_and_prompts_remain_standard() -> None:
    async def exercise() -> tuple[list[Any], list[Any], list[Any], list[Any], Any]:
        async with await in_process_client() as client:
            resources = await client.list_resources()
            templates = await client.list_resource_templates()
            prompts = await client.list_prompts()
            workflow = await client.read_resource("xray://workflow")
            rendered = await client.get_prompt("xray_discovery_plan", {"goal": "inspect source"})
            return resources, templates, prompts, workflow, rendered

    resources, templates, prompts, workflow, rendered = asyncio.run(exercise())
    assert any(str(item.uri) == "xray://workflow" for item in resources)
    assert any("skill://xray-progressive-discovery" in str(item.uriTemplate) for item in templates)
    assert any(item.name == "xray_discovery_plan" for item in prompts)
    assert "XRAY progressive discovery" in workflow[0].text
    assert "search_tools" in rendered.messages[0].content.text


def test_stdio_transport_uses_standard_newline_json_rpc_framing_and_enabled_semantics(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text(
        "class Sample:\n    def method(self):\n        return 1\n\ndef helper():\n    return Sample()\n",
        encoding="utf-8",
    )
    (repo / "dep.py").write_text("def foo(value):\n    return value\n", encoding="utf-8")
    (repo / "use.py").write_text(
        "from dep import foo\n\nfoo(1)\n# foo\nvalue = 'foo'\n",
        encoding="utf-8",
    )
    (repo / "rules").mkdir()
    (repo / "rules" / "no-foo.yml").write_text(
        "id: no-foo-call\nlanguage: Python\nrule:\n  pattern: foo($A)\nseverity: warning\n",
        encoding="utf-8",
    )
    (repo / "sgconfig.yml").write_text("ruleDirs:\n  - rules\n", encoding="utf-8")

    async def read_response(process: asyncio.subprocess.Process) -> dict[str, Any]:
        assert process.stdout is not None
        while True:
            line = await asyncio.wait_for(process.stdout.readline(), timeout=10)
            assert line.endswith(b"\n")
            response = cast(dict[str, Any], json.loads(line))
            if "id" in response:
                return response

    async def send_request(
        process: asyncio.subprocess.Process, request_id: int, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        assert process.stdin is not None
        process.stdin.write(
            (json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}) + "\n").encode()
        )
        await process.stdin.drain()
        return await read_response(process)

    def stdio_semantic(response: dict[str, Any]) -> dict[str, Any]:
        result = response["result"]
        value = result["structuredContent"]
        assert isinstance(value, dict)
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == canonical_json(value)
        assert json.loads(result["content"][0]["text"]) == value
        assert result["isError"] is (value.get("ok") is False)
        return cast(dict[str, Any], value)

    async def exercise() -> tuple[
        dict[str, Any],
        dict[str, Any],
        dict[str, dict[str, Any]],
        dict[str, Any],
        dict[str, Any],
        dict[str, tuple[str, dict[str, Any], dict[str, Any]]],
    ]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "xray.mcp_server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=ROOT,
            env=env,
        )
        assert process.stdin is not None
        initialize = await send_request(
            process,
            1,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )
        process.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}\n')
        await process.stdin.drain()
        tools = await send_request(process, 2, "tools/list", {})
        exact_contracts: dict[str, dict[str, Any]] = {}
        request_id = 3
        for name in ENABLED_OPERATION_NAMES:
            exact_contracts[name] = await send_request(
                process,
                request_id,
                "tools/call",
                {"name": "search_tools", "arguments": {"mode": "exact", "query": name, "max_bytes": 16384}},
            )
            request_id += 1
        first_catalog = await send_request(
            process,
            request_id,
            "tools/call",
            {"name": "search_tools", "arguments": {"mode": "catalog", "limit": 1, "max_bytes": 16384}},
        )
        request_id += 1
        first_value = stdio_semantic(first_catalog)
        cursor = first_value["page"]["next_cursor"]
        second_catalog = await send_request(
            process,
            request_id,
            "tools/call",
            {
                "name": "search_tools",
                "arguments": {"mode": "catalog", "limit": 1, "max_bytes": 16384, "cursor": cursor},
            },
        )
        request_id += 1

        find_arguments = {"root": str(repo), "query": {"text": "foo", "match": "exact"}}
        find_response = await send_request(
            process,
            request_id,
            "tools/call",
            {"name": "call_tool", "arguments": {"name": "find", "arguments": find_arguments}},
        )
        request_id += 1
        target = next(
            item["ref"] for item in stdio_semantic(find_response)["data"]["items"] if item["ref"]["path"] == "dep.py"
        )
        operation_calls: list[tuple[str, str, dict[str, Any]]] = [
            ("map", "map", {"root": str(repo), "query": {"depth": 2}}),
            (
                "interface",
                "interface",
                {"root": str(repo), "query": {"target": {"kind": "file", "path": "sample.py"}}},
            ),
            (
                "read",
                "read",
                {"root": str(repo), "query": {"targets": [{"kind": "location", "path": "sample.py", "line": 1}]}},
            ),
            ("impact_syntax", "impact", {"root": str(repo), "query": {"target": target, "mode": "syntax"}}),
            ("impact_lexical", "impact", {"root": str(repo), "query": {"target": target, "mode": "lexical"}}),
            (
                "search_literal",
                "search",
                {
                    "root": str(repo),
                    "query": {
                        "source": {"kind": "literal", "text": "foo"},
                        "selection": {"languages": ["python"]},
                    },
                },
            ),
            (
                "search_pattern",
                "search",
                {
                    "root": str(repo),
                    "query": {
                        "source": {"kind": "pattern", "pattern": "foo($A)", "language": "python"},
                        "selection": {"languages": ["python"]},
                        "detail": "detail",
                    },
                },
            ),
            (
                "search_rule",
                "search",
                {
                    "root": str(repo),
                    "query": {
                        "source": {"kind": "rule", "input": {"kind": "config", "path": "sgconfig.yml"}},
                        "selection": {"languages": ["python"]},
                    },
                },
            ),
            ("capabilities", "capabilities", {"root": str(repo), "query": {"detail": "detail"}}),
        ]
        operations: dict[str, tuple[str, dict[str, Any], dict[str, Any]]] = {
            "find": ("find", find_arguments, find_response)
        }
        for label, name, arguments in operation_calls:
            operations[label] = (
                name,
                arguments,
                await send_request(
                    process,
                    request_id,
                    "tools/call",
                    {"name": "call_tool", "arguments": {"name": name, "arguments": arguments}},
                ),
            )
            request_id += 1
        process.stdin.close()
        await asyncio.wait_for(process.wait(), timeout=10)
        return initialize, tools, exact_contracts, first_catalog, second_catalog, operations

    initialize, tools, exact_contracts, first_catalog, second_catalog, operations = asyncio.run(exercise())
    assert initialize["jsonrpc"] == "2.0"
    assert initialize["result"]["serverInfo"]["name"] == "XRAY Code Intelligence"
    assert [tool["name"] for tool in tools["result"]["tools"]] == ["search_tools", "call_tool"]
    assert tools["result"]["tools"][0]["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    assert tools["result"]["tools"][1]["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    }
    assert tools["result"]["tools"][1]["inputSchema"]["properties"]["name"]["enum"] == list(EXPECTED_OPERATION_NAMES)

    for name, response in exact_contracts.items():
        value = stdio_semantic(response)
        assert value["data"]["best"]["name"] == name
        assert value["data"]["best"]["mutation"] == ("guarded_mutation" if name == "change_apply" else "read_only")
        assert value["data"]["best"]["input_schema"]["type"] == "object"
        assert value["data"]["best"]["input_schema"]["additionalProperties"] is False

    first_value = stdio_semantic(first_catalog)
    second_value = stdio_semantic(second_catalog)
    assert first_value["data"]["best"]["name"] == "capabilities"
    assert second_value["data"]["best"]["name"] == "change_apply"
    assert first_value["page"]["total"] == len(EXPECTED_OPERATION_NAMES)
    assert second_value["page"]["total"] == len(EXPECTED_OPERATION_NAMES)
    assert "next_cursor" in first_value["page"]
    assert "next_cursor" in second_value["page"]

    for label, (name, arguments, response) in operations.items():
        value = stdio_semantic(response)
        assert value == execute({"op": name, **arguments}).to_payload()
        if label == "search_literal":
            assert value["coverage"]["basis"] == "literal_occurrences"
        elif label == "search_pattern":
            assert value["coverage"]["basis"] == "pattern_matches"
        elif label == "search_rule":
            assert value["coverage"]["basis"] == "rule_diagnostics"
        elif label == "impact_syntax":
            assert value["data"]["resolution"] == "unresolved"
        elif label == "impact_lexical":
            assert value["coverage"]["basis"] == "name_occurrences"


def test_in_process_change_lifecycle_matches_core_without_pre_apply_writes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "sample.py"
    original = "foo(1)\nfoo(2)\n"
    target.write_text(original, encoding="utf-8")

    plan_arguments = {
        "root": str(repo),
        "query": {
            "source": {
                "kind": "pattern",
                "pattern": "foo($A)",
                "replacement": "bar($A)",
                "language": "python",
            }
        },
    }

    async def exercise() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        async with await in_process_client() as client:
            plan_response = await client.call_tool(
                "call_tool", {"name": "change_plan", "arguments": plan_arguments}, raise_on_error=False
            )
            plan_value = semantic(plan_response)
            plan = plan_value["data"]["plan"]
            core_plan = execute({"op": "change_plan", **plan_arguments}).to_payload()
            refine_arguments = {
                "root": str(repo),
                "query": {"plan": plan, "edit_ids": sorted(item["edit_id"] for item in plan["edits"])[:1]},
            }
            refine_response = await client.call_tool(
                "call_tool", {"name": "change_refine", "arguments": refine_arguments}, raise_on_error=False
            )
            refined_value = semantic(refine_response)
            core_refine = execute({"op": "change_refine", **refine_arguments}).to_payload()
            refined_plan = refined_value["data"]["plan"]
            guard_arguments = {
                "root": str(repo),
                "query": {"plan": refined_plan, "expected_digest": refined_plan["plan_digest"]},
            }
            verify_response = await client.call_tool(
                "call_tool", {"name": "change_verify", "arguments": guard_arguments}, raise_on_error=False
            )
            verify_value = semantic(verify_response)
            core_verify = execute({"op": "change_verify", **guard_arguments}).to_payload()
            assert target.read_text(encoding="utf-8") == original
            malformed_response = await client.call_tool(
                "call_tool", {"name": "change_apply", "arguments": {}}, raise_on_error=False
            )
            malformed_value = semantic(malformed_response)
            core_apply = execute({"op": "change_apply", **guard_arguments}).to_payload()
            target.write_text(original, encoding="utf-8")
            apply_response = await client.call_tool(
                "call_tool", {"name": "change_apply", "arguments": guard_arguments}, raise_on_error=False
            )
            apply_value = semantic(apply_response)
            return (
                plan_value,
                refined_value,
                verify_value,
                {
                    "core_plan": core_plan,
                    "core_refine": core_refine,
                    "core_verify": core_verify,
                    "malformed": malformed_value,
                    "core_apply": core_apply,
                    "apply": apply_value,
                },
            )

    plan_value, refined_value, verify_value, expected = asyncio.run(exercise())
    assert plan_value == expected["core_plan"]
    assert refined_value == expected["core_refine"]
    assert verify_value == expected["core_verify"]
    assert expected["malformed"]["op"] == "change_apply"
    assert expected["malformed"]["error"]["code"] == "invalid_request"
    assert expected["malformed"]["mutation"] == {
        "state": "not_applied",
        "rollback_status": "not_attempted",
    }
    assert expected["core_apply"] == expected["apply"]
    assert expected["apply"]["data"]["state"] == "applied"
    assert target.read_text(encoding="utf-8") == "bar(1)\nfoo(2)\n"


def test_stdio_change_lifecycle_matches_core_and_mutates_only_on_apply(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "sample.py"
    original = "foo(1)\nfoo(2)\n"
    target.write_text(original, encoding="utf-8")
    plan_arguments = {
        "root": str(repo),
        "query": {
            "source": {
                "kind": "pattern",
                "pattern": "foo($A)",
                "replacement": "bar($A)",
                "language": "python",
            }
        },
    }

    async def exercise() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "xray.mcp_server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=ROOT,
            env=env,
        )

        async def read_response() -> dict[str, Any]:
            assert process.stdout is not None
            while True:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=10)
                assert line.endswith(b"\n")
                response = cast(dict[str, Any], json.loads(line))
                if "id" in response:
                    return response

        async def send(request_id: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
            assert process.stdin is not None
            process.stdin.write(
                (json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}) + "\n").encode()
            )
            await process.stdin.drain()
            return await read_response()

        def value(response: dict[str, Any]) -> dict[str, Any]:
            result = response["result"]
            semantic_value = result["structuredContent"]
            assert isinstance(semantic_value, dict)
            assert result["content"][0]["text"] == canonical_json(semantic_value)
            assert result["isError"] is (semantic_value.get("ok") is False)
            return cast(dict[str, Any], semantic_value)

        try:
            await send(
                1,
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            )
            assert process.stdin is not None
            process.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}\n')
            await process.stdin.drain()
            plan_value = value(
                await send(
                    2,
                    "tools/call",
                    {"name": "call_tool", "arguments": {"name": "change_plan", "arguments": plan_arguments}},
                )
            )
            core_plan = execute({"op": "change_plan", **plan_arguments}).to_payload()
            plan = plan_value["data"]["plan"]
            refine_arguments = {
                "root": str(repo),
                "query": {"plan": plan, "edit_ids": sorted(item["edit_id"] for item in plan["edits"])[:1]},
            }
            refined_value = value(
                await send(
                    3,
                    "tools/call",
                    {"name": "call_tool", "arguments": {"name": "change_refine", "arguments": refine_arguments}},
                )
            )
            core_refine = execute({"op": "change_refine", **refine_arguments}).to_payload()
            refined_plan = refined_value["data"]["plan"]
            verify_arguments = {
                "root": str(repo),
                "query": {"plan": refined_plan, "expected_digest": refined_plan["plan_digest"]},
            }
            verify_value = value(
                await send(
                    4,
                    "tools/call",
                    {"name": "call_tool", "arguments": {"name": "change_verify", "arguments": verify_arguments}},
                )
            )
            core_verify = execute({"op": "change_verify", **verify_arguments}).to_payload()
            assert target.read_text(encoding="utf-8") == original
            malformed = value(
                await send(
                    5,
                    "tools/call",
                    {"name": "call_tool", "arguments": {"name": "change_apply", "arguments": {}}},
                )
            )
            core_apply = execute({"op": "change_apply", **verify_arguments}).to_payload()
            target.write_text(original, encoding="utf-8")
            applied = value(
                await send(
                    6,
                    "tools/call",
                    {"name": "call_tool", "arguments": {"name": "change_apply", "arguments": verify_arguments}},
                )
            )
            return (
                plan_value,
                refined_value,
                verify_value,
                {
                    "core_plan": core_plan,
                    "core_refine": core_refine,
                    "core_verify": core_verify,
                    "malformed": malformed,
                    "core_apply": core_apply,
                    "applied": applied,
                },
            )
        finally:
            if process.stdin is not None:
                process.stdin.close()
            await asyncio.wait_for(process.wait(), timeout=10)

    plan_value, refined_value, verify_value, expected = asyncio.run(exercise())
    assert plan_value == expected["core_plan"]
    assert refined_value == expected["core_refine"]
    assert verify_value == expected["core_verify"]
    assert expected["malformed"]["op"] == "change_apply"
    assert expected["malformed"]["mutation"] == {
        "state": "not_applied",
        "rollback_status": "not_attempted",
    }
    assert expected["core_apply"] == expected["applied"]
    assert target.read_text(encoding="utf-8") == "bar(1)\nfoo(2)\n"


def test_admission_saturation_and_cancellation_are_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = make_repo(tmp_path)
    monkeypatch.setenv("XRAY_MCP_INDEXER_CACHE_LIMIT", "1000000")
    original_execute = mcp_server.execute
    started = threading.Event()
    release = threading.Event()
    completed = threading.Event()

    def blocking_execute(request: Any, *, budget: Any = None) -> Any:
        started.set()
        release.wait(10)
        try:
            return original_execute(request, budget=budget)
        finally:
            completed.set()

    monkeypatch.setattr(mcp_server, "execute", blocking_execute)

    async def exercise() -> tuple[Any, Any, Any]:
        async with await in_process_client() as client:
            first_task = asyncio.create_task(
                client.call_tool(
                    "call_tool",
                    {"name": "capabilities", "arguments": {"root": str(repo), "query": {}}},
                    raise_on_error=False,
                )
            )
            await asyncio.to_thread(started.wait, 5)
            saturated = await client.call_tool(
                "call_tool",
                {"name": "capabilities", "arguments": {"root": str(repo), "query": {}}},
                raise_on_error=False,
            )
            first_task.cancel()
            await asyncio.sleep(0)
            still_active = await client.call_tool(
                "call_tool",
                {"name": "capabilities", "arguments": {"root": str(repo), "query": {}}},
                raise_on_error=False,
            )
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await first_task
            await asyncio.to_thread(completed.wait, 5)
            recovered = await client.call_tool(
                "call_tool",
                {"name": "capabilities", "arguments": {"root": str(repo), "query": {}}},
                raise_on_error=False,
            )
            return saturated, still_active, recovered

    saturated, still_active, recovered = asyncio.run(exercise())
    assert semantic(saturated)["error"]["code"] == "execution_limit"
    assert semantic(still_active)["error"]["code"] == "execution_limit"
    assert semantic(recovered)["ok"] is True
