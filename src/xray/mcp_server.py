"""XRAY's standard FastMCP stdio adapter.

The application and presentation layers own XRAY's semantic contracts.  This
module only publishes the two MCP tools required for discovery and invocation,
then maps their canonical values to FastMCP ``ToolResult`` objects.
"""

from __future__ import annotations

import asyncio
import os
import select
import threading
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_context
from fastmcp.server.providers.skills import SkillsDirectoryProvider
from fastmcp.tools import Tool, ToolResult
from mcp.types import ToolAnnotations
from pydantic import PrivateAttr, TypeAdapter

from xray.core.repository import OperationBudget
from xray.models import (
    CatalogCursor,
    Error,
    ErrorValue,
    OperationContract,
    OperationSummary,
    SearchToolsCatalogRequest,
    SearchToolsExactRequest,
    SearchToolsIntentRequest,
    SearchToolsRequest,
    SearchToolsSuccess,
)
from xray.operations import (
    RequestPreparationError,
    catalog_identity,
    execute,
    operation_contracts,
    prepare_request,
    rank_operations,
)
from xray.presentation import (
    canonical_json,
    catalog_cursor_matches,
    decode_catalog_cursor,
    encode_catalog_cursor,
    fit_discovery,
    normalize_intent,
    query_digest,
)

# FastMCP owns JSON-RPC, stdio framing, request IDs, protocol cancellation and
# progress notifications.  XRAY owns only this bounded admission gate for real
# repository operations.
MAX_ACTIVE_OPERATIONS = 4
MIN_DISCOVERY_BYTES = 4096
MAX_DISCOVERY_BYTES = 16384
MAX_STDIO_FRAME_BYTES = 1_048_576
_STDIO_READ_CHUNK_BYTES = 64 * 1024
_STDIO_WAIT_SECONDS = 0.1


class _AdmissionToken:
    __slots__ = ("root_id", "slot")

    def __init__(self, slot: int) -> None:
        self.slot = slot
        self.root_id: str | None = None


class _Admission:
    """A non-queuing process-wide operation admission gate."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = 0
        self._next_slot = 0
        self._tokens: dict[int, _AdmissionToken] = {}
        self._roots: dict[str, int] = {}

    def acquire(self) -> _AdmissionToken | None:
        with self._lock:
            if self._active >= MAX_ACTIVE_OPERATIONS:
                return None
            self._next_slot += 1
            token = _AdmissionToken(self._next_slot)
            self._tokens[token.slot] = token
            self._active += 1
            return token

    def bind(self, token: _AdmissionToken, root_id: str) -> bool:
        with self._lock:
            if self._tokens.get(token.slot) is not token:
                return False
            owner = self._roots.get(root_id)
            if owner is not None and owner != token.slot:
                return False
            if token.root_id is not None and token.root_id != root_id:
                self._roots.pop(token.root_id, None)
            token.root_id = root_id
            self._roots[root_id] = token.slot
            return True

    def release(self, token: _AdmissionToken) -> None:
        with self._lock:
            if self._tokens.pop(token.slot, None) is None:
                return
            if token.root_id is not None and self._roots.get(token.root_id) == token.slot:
                self._roots.pop(token.root_id, None)
            self._active = max(0, self._active - 1)


_admission = _Admission()


# The catalog and schemas are supplied by the accepted canonical operation
# service. There is deliberately no legacy operation registration here.
_ENABLED_CONTRACTS: tuple[OperationContract, ...] = operation_contracts()
_ENABLED_CONTRACTS_BY_NAME: Mapping[str, OperationContract] = MappingProxyType(
    {item.name: item for item in _ENABLED_CONTRACTS}
)
_ENABLED_CATALOG_IDENTITY = catalog_identity()
_ENABLED_OPERATIONS: tuple[str, ...] = tuple(item.name for item in _ENABLED_CONTRACTS)
_SEARCH_REQUEST_ADAPTER = TypeAdapter(SearchToolsRequest)


GUIDANCE_PATH = Path(__file__).with_name("guidance.md")


SEARCH_TOOLS_PARAMETERS: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "oneOf": [
        {
            "type": "object",
            "properties": {
                "mode": {"const": "intent", "default": "intent"},
                "query": {"type": "string", "minLength": 1, "maxLength": 1024},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
                "max_bytes": {"type": "integer", "minimum": 4096, "maximum": 16384, "default": 4096},
                "cursor": {"type": "string", "maxLength": 4096},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "mode": {"const": "exact"},
                "query": {"type": "string", "enum": list(_ENABLED_OPERATIONS)},
                "max_bytes": {"type": "integer", "minimum": 4096, "maximum": 16384, "default": 4096},
            },
            "required": ["mode", "query"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "mode": {"const": "catalog"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
                "max_bytes": {"type": "integer", "minimum": 4096, "maximum": 16384, "default": 4096},
                "cursor": {"type": "string", "maxLength": 4096},
            },
            "required": ["mode"],
            "additionalProperties": False,
        },
    ],
}

CALL_TOOL_PARAMETERS: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "name": {"type": "string", "enum": list(_ENABLED_OPERATIONS)},
        "arguments": {"type": "object", "additionalProperties": True},
    },
    "required": ["name", "arguments"],
    "additionalProperties": False,
}


class _AdapterTool(Tool):
    """Thin public FastMCP Tool extension that receives raw JSON arguments."""

    _handler: Callable[[dict[str, Any]], Awaitable[ToolResult]] | None = PrivateAttr(default=None)

    def __init__(
        self,
        *,
        handler: Callable[[dict[str, Any]], Awaitable[ToolResult]],
        name: str,
        description: str,
        parameters: dict[str, Any],
        annotations: ToolAnnotations,
    ) -> None:
        super().__init__(
            name=name,
            description=description,
            parameters=parameters,
            annotations=annotations,
        )
        self._handler = handler

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        handler = self._handler
        if handler is None:
            raise RuntimeError("MCP adapter handler is not installed")
        return await handler(arguments)


_MAX_ERROR_MESSAGE_BYTES = 512


def _bounded_message(message: object) -> str:
    text = str(message) or "invalid request"
    raw = text.encode("utf-8")
    if len(raw) <= _MAX_ERROR_MESSAGE_BYTES:
        return text
    return raw[:_MAX_ERROR_MESSAGE_BYTES].decode("utf-8", errors="ignore") or "invalid request"


def _error(
    code: str,
    message: object,
    *,
    operation: str,
    apply: bool = False,
    mutation: Mapping[str, Any] | None = None,
) -> Error:
    """Build only the shared canonical XRAY error value."""
    values: dict[str, Any] = {
        "schema": "xray.v1",
        "ok": False,
        "op": cast(Any, operation),
        "error": ErrorValue(code=cast(Any, code), message=_bounded_message(message)),
    }
    if apply:
        values["mutation"] = mutation or {"state": "not_applied", "rollback_status": "not_attempted"}
    return Error.model_validate(values)


def _as_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_payload"):
        payload = value.to_payload()
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        raise TypeError("canonical operation returned a non-object value")
    if not isinstance(payload, dict):
        raise TypeError("canonical operation returned a non-object value")
    return cast(dict[str, Any], payload)


def _tool_result(value: Any) -> ToolResult:
    """Map one semantic value to the standard MCP result without a wrapper."""
    payload = _as_payload(value)
    return ToolResult(
        content=canonical_json(payload),
        structured_content=payload,
        is_error=payload.get("ok") is False,
    )


def _enabled_contracts() -> tuple[OperationContract, ...]:
    """Return the immutable enabled catalog in canonical UTF-8 name order."""
    return _ENABLED_CONTRACTS


def _catalog_state() -> tuple[tuple[OperationContract, ...], Mapping[str, OperationContract], str]:
    return _ENABLED_CONTRACTS, _ENABLED_CONTRACTS_BY_NAME, _ENABLED_CATALOG_IDENTITY


def _catalog_error(code: str, message: object) -> ToolResult:
    return _tool_result(_error(code, message, operation="search_tools"))


def _seek_names(
    names: tuple[str, ...],
    *,
    mode: str,
    normalized_query: str,
    cursor: str | None,
    catalog: str,
) -> tuple[int, ToolResult | None]:
    if cursor is None:
        return 0, None
    try:
        decoded = decode_catalog_cursor(cursor)
    except Exception as exc:
        return 0, _catalog_error("invalid_cursor", str(exc))
    if decoded is None:
        return 0, _catalog_error("invalid_cursor", "cursor is missing")
    expected_query = query_digest(mode, normalized_query, catalog)
    if decoded.catalog != catalog:
        return 0, _catalog_error("stale_cursor", "cursor catalog does not match the current catalog")
    if not catalog_cursor_matches(decoded, catalog=catalog, query=expected_query):
        return 0, _catalog_error("cursor_query_mismatch", "cursor query does not match the current discovery query")
    try:
        return names.index(decoded.after) + 1, None
    except ValueError:
        return 0, _catalog_error("invalid_cursor", "cursor checkpoint is not in the selected catalog")


def _discovery_page(
    *,
    mode: str,
    normalized_query: str,
    names: tuple[str, ...],
    limit: int,
    max_bytes: int,
    cursor: str | None,
    contracts: Mapping[str, OperationContract],
    catalog: str,
) -> ToolResult:
    start, cursor_error = _seek_names(
        names,
        mode=mode,
        normalized_query=normalized_query,
        cursor=cursor,
        catalog=catalog,
    )
    if cursor_error is not None:
        return cursor_error

    query = query_digest(mode, normalized_query, catalog)
    page_names = names[start : start + limit]
    if not page_names:
        page_names = ()

    def build_success(returned: tuple[str, ...]) -> SearchToolsSuccess:
        values: dict[str, Any] = {
            "schema": "xray.v1",
            "ok": True,
            "op": "search_tools",
            "provenance": {"catalog": catalog, "query": query},
            "data": {"alternatives": []},
            "page": {"total": len(names)},
            "coverage": {"state": "complete", "basis": "capabilities"},
        }
        if returned:
            values["data"]["best"] = contracts[returned[0]]
            values["data"]["alternatives"] = [OperationSummary.model_validate(contracts[name]) for name in returned[1:]]
            if start + len(returned) < len(names):
                values["page"]["next_cursor"] = encode_catalog_cursor(
                    CatalogCursor(
                        version=1,
                        op="search_tools",
                        catalog=catalog,
                        query=query,
                        after=cast(Any, returned[-1]),
                    )
                )
        return SearchToolsSuccess.model_validate(values)

    try:
        returned: list[str] = []
        for name in page_names:
            candidate = build_success(tuple([*returned, name]))
            fitted = fit_discovery(candidate, max_bytes)
            if isinstance(fitted, Error):
                if not returned:
                    return _tool_result(fitted)
                break
            returned.append(name)
        fitted = fit_discovery(build_success(tuple(returned)), max_bytes)
    except Exception as exc:
        return _catalog_error("internal_error", exc)
    return _tool_result(fitted)


async def _search_tools(arguments: dict[str, Any]) -> ToolResult:
    if not isinstance(arguments, dict):
        return _catalog_error("invalid_request", "search_tools arguments must be an object")
    try:
        request = _SEARCH_REQUEST_ADAPTER.validate_python(arguments)
    except Exception as exc:
        if (
            arguments.get("mode") == "exact"
            and isinstance(arguments.get("query"), str)
            and arguments.get("query")
            and set(arguments).issubset({"mode", "query", "max_bytes"})
        ):
            raw_max_bytes = arguments.get("max_bytes", MIN_DISCOVERY_BYTES)
            if (
                isinstance(raw_max_bytes, int)
                and not isinstance(raw_max_bytes, bool)
                and MIN_DISCOVERY_BYTES <= raw_max_bytes <= MAX_DISCOVERY_BYTES
            ):
                return _catalog_error(
                    "unknown_operation",
                    f"operation {arguments['query']!r} is unknown or disabled",
                )
        return _catalog_error("invalid_request", exc)

    contracts, by_name, catalog = _catalog_state()
    if isinstance(request, SearchToolsIntentRequest):
        normalized = normalize_intent(request.query)
        if not normalized:
            return _catalog_error("invalid_request", "query must not be empty after normalization")
        names = rank_operations(normalized, tuple(item.name for item in contracts))
        return _discovery_page(
            mode="intent",
            normalized_query=normalized,
            names=names,
            limit=request.limit,
            max_bytes=request.max_bytes,
            cursor=request.cursor,
            contracts=by_name,
            catalog=catalog,
        )
    if isinstance(request, SearchToolsCatalogRequest):
        names = tuple(item.name for item in contracts)
        return _discovery_page(
            mode="catalog",
            normalized_query="",
            names=names,
            limit=request.limit,
            max_bytes=request.max_bytes,
            cursor=request.cursor,
            contracts=by_name,
            catalog=catalog,
        )

    assert isinstance(request, SearchToolsExactRequest)
    if request.query not in by_name:
        return _catalog_error("unknown_operation", f"operation {request.query!r} is unknown or disabled")
    return _discovery_page(
        mode="exact",
        normalized_query=request.query,
        names=(request.query,),
        limit=1,
        max_bytes=request.max_bytes,
        cursor=None,
        contracts=by_name,
        catalog=catalog,
    )


async def _report_progress(progress: float, message: str) -> None:
    try:
        context = get_context()
    except Exception:
        return
    await context.report_progress(progress, 1, message)


async def _await_worker(task: asyncio.Task[Any]) -> Any:
    """Wait for a worker to terminate even if the caller is cancelled again."""
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                return task.result()


async def _call_tool(arguments: dict[str, Any]) -> ToolResult:
    if not isinstance(arguments, dict):
        return _tool_result(_error("invalid_request", "call_tool arguments must be an object", operation="call_tool"))

    name = arguments.get("name")
    if not isinstance(name, str):
        return _tool_result(_error("invalid_request", "call_tool.name must be a string", operation="call_tool"))
    if name not in _ENABLED_OPERATIONS:
        return _tool_result(
            _error("unknown_operation", f"operation {name!r} is unknown or disabled", operation="call_tool")
        )

    apply = name == "change_apply"
    if set(arguments) != {"name", "arguments"}:
        return _tool_result(
            _error("invalid_request", "call_tool requires exactly name and arguments", operation=name, apply=apply)
        )
    operation_arguments = arguments["arguments"]
    if not isinstance(operation_arguments, dict):
        return _tool_result(
            _error("invalid_request", "call_tool.arguments must be an object", operation=name, apply=apply)
        )
    if "op" in operation_arguments:
        return _tool_result(
            _error("invalid_request", "call_tool.arguments must not contain op", operation=name, apply=apply)
        )

    token = _admission.acquire()
    if token is None:
        return _tool_result(
            _error(
                "execution_limit",
                "operation admission limit is busy",
                operation=name,
                apply=apply,
            )
        )

    task: asyncio.Task[Any] | None = None
    cancellation = threading.Event()
    try:
        raw_request = dict(operation_arguments)
        raw_request["op"] = name
        try:
            prepared = prepare_request(raw_request)
        except RequestPreparationError as exc:
            return _tool_result(_error(exc.code, exc, operation=name, apply=apply))
        except Exception as exc:
            return _tool_result(_error("internal_error", exc, operation=name, apply=apply))

        if prepared.root is not None and not _admission.bind(token, prepared.root.id):
            return _tool_result(
                _error(
                    "execution_limit",
                    "operation admission limit is busy",
                    operation=name,
                    apply=apply,
                )
            )

        budget = OperationBudget(
            timeout_seconds=prepared.request.execution.timeout_seconds,
            cancel=cancellation,
        )
        task = asyncio.create_task(asyncio.to_thread(execute, prepared, budget=budget))
        await _report_progress(0, f"starting {name}")
        try:
            result = await asyncio.wait_for(
                asyncio.shield(task),
                timeout=budget.remaining_seconds,
            )
        except asyncio.TimeoutError:
            cancellation.set()
            try:
                result = await _await_worker(task)
            except Exception as exc:
                return _tool_result(_error("internal_error", exc, operation=name, apply=apply))
            if apply:
                # The guarded service owns mutation truth; return only the
                # result produced after it observed the shared cancellation.
                return _tool_result(result)
            return _tool_result(_error("timeout", f"operation {name!r} exceeded its deadline", operation=name))
        except asyncio.CancelledError:
            cancellation.set()
            try:
                await _await_worker(task)
            except BaseException:
                pass
            raise
        except Exception as exc:
            cancellation.set()
            try:
                await _await_worker(task)
            except Exception:
                pass
            return _tool_result(_error("internal_error", exc, operation=name, apply=apply))
        await _report_progress(1, f"completed {name}")
        return _tool_result(result)
    finally:
        if task is not None and not task.done():
            cancellation.set()
            try:
                await _await_worker(task)
            except BaseException:
                pass
        _admission.release(token)


def _close_fd(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _write_stdio_bytes(fd: int, payload: bytes, stop: threading.Event) -> bool:
    """Forward one complete frame without retaining more than one frame."""

    view = memoryview(payload)
    offset = 0
    while offset < len(view):
        if stop.is_set():
            return False
        try:
            _, writable, _ = select.select([], [fd], [], _STDIO_WAIT_SECONDS)
        except (OSError, ValueError):
            return False
        if not writable:
            continue
        try:
            written = os.write(fd, view[offset:])
        except OSError:
            return False
        if written <= 0:
            return False
        offset += written
    return True


def _bounded_stdio_forwarder(source_fd: int, sink_fd: int, stop: threading.Event) -> None:
    """Copy newline-delimited bytes into FastMCP's standard stdin pipe.

    This is deliberately an I/O-only seam: it never decodes, parses, or
    interprets JSON-RPC.  A frame over the raw one-megabyte bound, or an
    unterminated frame at EOF, is discarded and closes the pipe before the
    framework can observe it.
    """

    pending = bytearray()
    try:
        while not stop.is_set():
            try:
                readable, _, _ = select.select([source_fd], [], [], _STDIO_WAIT_SECONDS)
            except (OSError, ValueError):
                return
            if not readable:
                continue
            try:
                chunk = os.read(source_fd, _STDIO_READ_CHUNK_BYTES)
            except OSError:
                return
            if not chunk:
                # Do not forward an unterminated line: FastMCP must not
                # decode a partial frame after the transport reaches EOF.
                return
            pending.extend(chunk)
            while True:
                newline = pending.find(b"\n")
                if newline < 0:
                    if len(pending) > MAX_STDIO_FRAME_BYTES:
                        return
                    break
                if newline > MAX_STDIO_FRAME_BYTES:
                    return
                frame = bytes(pending[: newline + 1])
                del pending[: newline + 1]
                if not _write_stdio_bytes(sink_fd, frame, stop):
                    return
    finally:
        _close_fd(source_fd)
        _close_fd(sink_fd)


def _run_bounded_stdio() -> None:
    """Run FastMCP with an I/O-only bounded stdin forwarding seam."""

    restore_fd = os.dup(0)
    source_fd = os.dup(restore_fd)
    read_fd, sink_fd = os.pipe()
    stop = threading.Event()
    try:
        os.dup2(read_fd, 0)
    finally:
        _close_fd(read_fd)

    forwarder = threading.Thread(
        target=_bounded_stdio_forwarder,
        args=(source_fd, sink_fd, stop),
        name="xray-stdio-forwarder",
        daemon=True,
    )
    forwarder.start()
    try:
        mcp.run(transport="stdio")
    finally:
        stop.set()
        forwarder.join(timeout=2)
        if forwarder.is_alive():
            _close_fd(source_fd)
            _close_fd(sink_fd)
            forwarder.join(timeout=1)
        _close_fd(0)
        os.dup2(restore_fd, 0)
        _close_fd(restore_fd)


def _register_server() -> FastMCP:
    server = FastMCP(
        "XRAY Code Intelligence",
        strict_input_validation=False,
        dereference_schemas=False,
        tasks=False,
    )
    server.add_tool(
        _AdapterTool(
            handler=_search_tools,
            name="search_tools",
            description="Discover enabled XRAY operations and complete call-ready schemas.",
            parameters=SEARCH_TOOLS_PARAMETERS,
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
    )
    server.add_tool(
        _AdapterTool(
            handler=_call_tool,
            name="call_tool",
            description="Execute one enabled XRAY operation with its exact validated arguments.",
            parameters=CALL_TOOL_PARAMETERS,
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=False,
            ),
        )
    )

    @server.resource(
        "xray://workflow",
        name="xray_workflow",
        description="Detailed XRAY discovery and enabled-operation guidance.",
        mime_type="text/markdown",
        annotations={"readOnlyHint": True, "idempotentHint": True},
    )
    def xray_workflow() -> str:
        return GUIDANCE_PATH.read_text(encoding="utf-8")

    @server.prompt(
        name="xray_discovery_plan",
        description="Plan a compact XRAY discovery sequence for a code task.",
    )
    def xray_discovery_plan(goal: str = "understand a code change") -> str:
        return (
            f"Goal: {goal}\n\n"
            "Use search_tools with intent, exact, or catalog mode, then call the "
            "selected enabled operation through call_tool.\n"
            "For source inspection, call read with its complete targets and page "
            "controls. Call capabilities for health and enabled-operation summaries.\n"
            "Use the returned canonical page cursor only with the same discovery "
            "mode and query."
        )

    server.add_provider(
        SkillsDirectoryProvider(
            roots=Path(__file__).parent / "skills",
            supporting_files="template",
        )
    )
    return server


mcp = _register_server()


def main() -> None:
    """Run XRAY over FastMCP's standard stdio transport."""
    _run_bounded_stdio()


if __name__ == "__main__":
    main()
