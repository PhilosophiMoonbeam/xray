"""Canonical xray.v1 serialization, digest, fitting, and cursor helpers."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, TypeVar, cast

from .models import (
    MAX_REQUEST_JSON_BYTES,
    CatalogCursor,
    ChangePlan,
    Error,
    ErrorDetails,
    ErrorValue,
    RepositoryCursor,
    StrictModel,
)

CURSOR_LIMIT = 4096
SCHEMA_LIMIT = 14_336
DISCOVERY_LIMIT = 16_384
ERROR_LIMIT = 4096
_MIN_RESPONSE_BYTES = 4096
_JSON_ESCAPE_CODEPOINTS = {ord('"'), ord("\\")}
_JSON_CONTROL_LIMIT = 0x20
_UTF16_SURROGATE_START = 0xD800
_UTF16_SURROGATE_END = 0xDFFF
_UTF8_ONE_BYTE_LIMIT = 0x80
_UTF8_TWO_BYTE_LIMIT = 0x800
_UTF8_THREE_BYTE_LIMIT = 0x10000

T = TypeVar("T")


def _json_value(value: Any) -> Any:
    """Convert a model or mapping to JSON-compatible values without coercion."""
    if isinstance(value, StrictModel):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise ValueError("NaN and infinity are not valid canonical JSON values")
    return value


def canonical_json(value: Any) -> str:
    """Return compact sorted-key JSON using ordinary UTF-8 characters."""
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def canonical_cli_bytes(value: Any) -> bytes:
    """Serialize a semantic value with the one CLI framing LF."""
    return canonical_bytes(value) + b"\n"


class _SizeExceeded(Exception):
    """Internal stop signal for bounded canonical-size walks."""


class _SizeCounter:
    __slots__ = ("limit", "total")

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.total = 0

    def add(self, amount: int) -> None:
        self.total += amount
        if self.total > self.limit:
            raise _SizeExceeded


def _json_string_size(value: str, counter: _SizeCounter) -> None:
    counter.add(2)
    for character in value:
        codepoint = ord(character)
        if codepoint in _JSON_ESCAPE_CODEPOINTS:
            counter.add(2)
        elif codepoint < _JSON_CONTROL_LIMIT:
            counter.add(2 if codepoint in {0x08, 0x09, 0x0A, 0x0C, 0x0D} else 6)
        elif _UTF16_SURROGATE_START <= codepoint <= _UTF16_SURROGATE_END:
            raise ValueError("canonical JSON cannot encode lone UTF-16 surrogates")
        elif codepoint < _UTF8_ONE_BYTE_LIMIT:
            counter.add(1)
        elif codepoint < _UTF8_TWO_BYTE_LIMIT:
            counter.add(2)
        elif codepoint < _UTF8_THREE_BYTE_LIMIT:
            counter.add(3)
        else:
            counter.add(4)


def _json_key_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            raise ValueError("NaN and infinity are not valid canonical JSON values")
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    raise TypeError("canonical JSON object keys must be strings or JSON scalar keys")


def _walk_canonical_size(value: Any, counter: _SizeCounter) -> None:
    if isinstance(value, StrictModel):
        counter.add(1)
        first = True
        for name, field in type(value).model_fields.items():
            item = getattr(value, name)
            if item is None:
                continue
            if not first:
                counter.add(1)
            first = False
            alias = field.serialization_alias or field.alias or name
            _json_string_size(cast(str, alias), counter)
            counter.add(1)
            _walk_canonical_size(item, counter)
        counter.add(1)
        return
    if isinstance(value, Mapping):
        counter.add(1)
        first = True
        for key, item in value.items():
            if not first:
                counter.add(1)
            first = False
            _json_string_size(_json_key_text(key), counter)
            counter.add(1)
            _walk_canonical_size(item, counter)
        counter.add(1)
        return
    if isinstance(value, (list, tuple)):
        counter.add(1)
        for index, item in enumerate(value):
            if index:
                counter.add(1)
            _walk_canonical_size(item, counter)
        counter.add(1)
        return
    if value is None:
        counter.add(4)
        return
    if isinstance(value, bool):
        counter.add(4 if value else 5)
        return
    if isinstance(value, int):
        counter.add(len(str(value)))
        return
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError("NaN and infinity are not valid canonical JSON values")
        counter.add(len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)))
        return
    if isinstance(value, str):
        _json_string_size(value, counter)
        return
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def bounded_canonical_size(value: Any, max_bytes: int) -> int:
    """Count canonical UTF-8 JSON bytes, stopping at ``max_bytes + 1``."""

    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 0:
        raise ValueError("max_bytes must be a nonnegative integer")
    counter = _SizeCounter(max_bytes)
    try:
        _walk_canonical_size(value, counter)
    except _SizeExceeded:
        return max_bytes + 1
    return counter.total


def request_json_size(value: Any, max_bytes: int = MAX_REQUEST_JSON_BYTES) -> int:
    """Return bounded canonical request size without serializing the request."""

    return bounded_canonical_size(value, max_bytes)


def request_fits(value: Any, max_bytes: int = MAX_REQUEST_JSON_BYTES) -> bool:
    """Return whether a request's canonical JSON fits its admission bound."""

    return request_json_size(value, max_bytes) <= max_bytes


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(value: Any) -> str:
    """Hash the canonical semantic JSON value, excluding transport framing."""
    return sha256_bytes(canonical_bytes(value))


def root_digest(path: str) -> str:
    return digest(["xray.root.v1", path])


def occurrence_digest(path: str, file_digest: str, start: int, end: int) -> str:
    return digest(["xray.occurrence.v1", path, file_digest, start, end])


def symbol_digest(
    file_digest: str,
    analyzer_id: str,
    language: str,
    kind: str,
    full_owner_chain: list[str],
    name: str,
    start: int,
    end: int,
) -> str:
    return digest(["xray.symbol.v1", file_digest, analyzer_id, language, kind, full_owner_chain, name, start, end])


def find_row_digest(path: str, start: int, end: int, symbol_id: str) -> str:
    return digest(["xray.find.row.v1", path, start, end, symbol_id])


def plan_digest(plan: ChangePlan) -> str:
    """Return the xray.change.v1 digest over every field except plan_digest."""
    payload = plan.to_payload()
    payload.pop("plan_digest", None)
    return digest(payload)


def catalog_digest(contracts: Sequence[Mapping[str, Any]], discovery_artifact: str) -> str:
    ordered = sorted((_json_value(contract) for contract in contracts), key=canonical_bytes)
    return digest(["xray.catalog.v1", ordered, discovery_artifact])


def query_digest(mode: str, normalized_query: str, catalog: str) -> str:
    return digest(["xray.mcp.search_tools.v1", mode, normalized_query, catalog])


def repository_query_digest(
    operation: str,
    normalized_query: Any,
    projection: Any,
    selection: Any,
    snapshot: Any,
    toolchain: Any,
) -> str:
    """Hash one repository query identity from final, non-self-referential inputs.

    ``normalized_query`` and ``projection`` are semantic values after defaults
    have been applied.  ``selection``, ``snapshot``, and ``toolchain`` are the
    final captured identities.  Transport budgets, cursors, and result
    envelopes are intentionally outside this helper.
    """

    return digest(
        [
            "xray.query.v1",
            operation,
            _json_value(normalized_query),
            _json_value(projection),
            _json_value(selection),
            _json_value(snapshot),
            _json_value(toolchain),
        ]
    )


def normalize_intent(value: str) -> str:
    """Normalize discovery intent without Unicode normalization."""
    return " ".join(value.casefold().replace("_", " ").split())


def _urlsafe_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _urlsafe_decode(token: str) -> bytes:
    if not isinstance(token, str) or not token or len(token) > CURSOR_LIMIT or "=" in token:
        raise ValueError("cursor is oversized or malformed")
    if any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for character in token):
        raise ValueError("cursor is not base64url without padding")
    try:
        return base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (ValueError, binascii.Error) as exc:
        raise ValueError("cursor is malformed") from exc


def encode_cursor(cursor: RepositoryCursor | Mapping[str, Any]) -> str:
    """Encode a fully bound repository seek cursor."""
    model = cursor if isinstance(cursor, RepositoryCursor) else RepositoryCursor.model_validate(cursor)
    raw = canonical_bytes(model)
    token = _urlsafe_encode(raw)
    if len(token.encode("ascii")) > CURSOR_LIMIT:
        raise ValueError("cursor exceeds the 4096-byte encoded bound")
    return token


def decode_cursor(cursor: str | None) -> RepositoryCursor | None:
    if cursor is None:
        return None
    raw = _urlsafe_decode(cursor)
    model = RepositoryCursor.model_validate(json.loads(raw))
    if canonical_bytes(model) != raw:
        raise ValueError("cursor is not canonical")
    return model


def encode_catalog_cursor(cursor: CatalogCursor | Mapping[str, Any]) -> str:
    model = cursor if isinstance(cursor, CatalogCursor) else CatalogCursor.model_validate(cursor)
    raw = canonical_bytes(model)
    token = _urlsafe_encode(raw)
    if len(token.encode("ascii")) > CURSOR_LIMIT:
        raise ValueError("catalog cursor exceeds the 4096-byte encoded bound")
    return token


def decode_catalog_cursor(cursor: str | None) -> CatalogCursor | None:
    if cursor is None:
        return None
    raw = _urlsafe_decode(cursor)
    model = CatalogCursor.model_validate(json.loads(raw))
    if canonical_bytes(model) != raw:
        raise ValueError("catalog cursor is not canonical")
    return model


def cursor_matches(
    cursor: RepositoryCursor, *, op: str, root: str, query: str, selection: str, snapshot: str, toolchain: str
) -> bool:
    """Check every semantic binding before a caller seeks."""
    return (
        cursor.op == op
        and cursor.root == root
        and cursor.query == query
        and cursor.selection == selection
        and cursor.snapshot == snapshot
        and cursor.toolchain == toolchain
    )


def catalog_cursor_matches(cursor: CatalogCursor, *, catalog: str, query: str) -> bool:
    return cursor.op == "search_tools" and cursor.catalog == catalog and cursor.query == query


def serialized_size(value: Any) -> int:
    return len(canonical_bytes(value))


def _budget_error(operation: str | None, minimum: int, *, source: Any | None = None) -> Error:
    values: dict[str, Any] = {
        "schema": "xray.v1",
        "ok": False,
        "error": ErrorValue(
            code="budget_too_small",
            message="canonical response exceeds the requested byte budget",
            details=ErrorDetails(minimum_bytes=minimum),
        ),
    }
    if operation is not None:
        values["op"] = operation
    if source is not None:
        root = getattr(source, "root", None)
        provenance = getattr(source, "provenance", None)
        if root is not None:
            values["root"] = root
        if provenance is not None:
            values["provenance"] = provenance
    if operation == "change_apply":
        values["mutation"] = {"state": "not_applied", "rollback_status": "not_attempted"}
    return Error.model_validate(values)


def fit_success(value: T, max_bytes: int, *, hard_bytes: int = 65_536) -> T | Error:
    """Return a complete success or a typed budget failure; never truncate it."""
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < _MIN_RESPONSE_BYTES:
        raise ValueError("max_bytes must be at least 4096")
    size = serialized_size(value)
    if size > hard_bytes or size > max_bytes:
        operation = getattr(value, "op", None)
        return _budget_error(operation, size, source=value)
    return value


def fit_error(value: Error, max_bytes: int = ERROR_LIMIT) -> Error:
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < _MIN_RESPONSE_BYTES:
        raise ValueError("error max_bytes must be at least 4096")
    size = serialized_size(value)
    if size > ERROR_LIMIT or size > max_bytes:
        raise ValueError("typed error cannot fit the error byte bound")
    return value


def fit_discovery(value: Any, max_bytes: int = _MIN_RESPONSE_BYTES) -> Any | Error:
    if (
        not isinstance(max_bytes, int)
        or isinstance(max_bytes, bool)
        or not _MIN_RESPONSE_BYTES <= max_bytes <= DISCOVERY_LIMIT
    ):
        raise ValueError("discovery max_bytes must be between 4096 and 16384")
    size = serialized_size(value)
    if size > max_bytes or size > DISCOVERY_LIMIT:
        return _budget_error("search_tools", size)
    return value


def serialize(value: Any, *, max_bytes: int | None = None, hard_bytes: int | None = None) -> bytes:
    raw = canonical_bytes(value)
    if max_bytes is not None and len(raw) > max_bytes:
        raise ValueError("canonical value exceeds max_bytes")
    if hard_bytes is not None and len(raw) > hard_bytes:
        raise ValueError("canonical value exceeds hard_bytes")
    return raw


__all__ = [
    "CURSOR_LIMIT",
    "DISCOVERY_LIMIT",
    "ERROR_LIMIT",
    "MAX_REQUEST_JSON_BYTES",
    "SCHEMA_LIMIT",
    "bounded_canonical_size",
    "canonical_bytes",
    "canonical_cli_bytes",
    "canonical_json",
    "catalog_cursor_matches",
    "catalog_digest",
    "cursor_matches",
    "decode_catalog_cursor",
    "decode_cursor",
    "digest",
    "encode_catalog_cursor",
    "encode_cursor",
    "find_row_digest",
    "fit_discovery",
    "fit_error",
    "fit_success",
    "normalize_intent",
    "occurrence_digest",
    "plan_digest",
    "query_digest",
    "repository_query_digest",
    "request_fits",
    "request_json_size",
    "root_digest",
    "serialize",
    "serialized_size",
    "sha256_bytes",
    "symbol_digest",
]
