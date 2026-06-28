"""Validated data models for XRAY public JSON/MCP boundaries."""

from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class PublicModel(BaseModel):
    """Base model for public payloads that may grow compatibly over time."""

    model_config = ConfigDict(extra="allow")

    def to_payload(self) -> dict[str, Any]:
        """Return the sparse dict shape used by existing CLI/MCP JSON."""
        return self.model_dump(exclude_none=True)


class SymbolInput(BaseModel):
    """Symbol object accepted by CLI JSON and MCP impact analysis."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    path: str = Field(min_length=1)
    type: str = "symbol"
    start_line: int = -1
    end_line: int | None = None
    abs_path: str | None = None


class SymbolOutput(PublicModel):
    """Symbol object emitted by find and accepted by impact analysis."""

    name: str = Field(min_length=1)
    path: str = Field(min_length=1)
    type: str = "symbol"
    start_line: int = -1
    end_line: int | None = None
    abs_path: str | None = None
    score: int | None = None


class ExploreSymbol(PublicModel):
    """Symbol skeleton embedded in structured explore entries."""

    name: str
    type: str
    signature: str
    doc: str = ""


class ExploreEntry(PublicModel):
    """Structured repository map entry."""

    path: str
    abs_path: str
    name: str
    kind: str
    depth: int
    language: str | None = None
    symbols: list[ExploreSymbol] | None = None


class ExploreOptions(PublicModel):
    """Structured repository map options."""

    max_depth: int | None = None
    include_symbols: bool
    focus_dirs: list[str] = Field(default_factory=list)
    max_symbols_per_file: int


class ExploreData(PublicModel):
    """Structured repository map payload before CLI envelope fields are added."""

    root_path: str
    entries: list[ExploreEntry]
    options: ExploreOptions


class ExploreEnvelope(ExploreData):
    """CLI JSON envelope for explore/map output."""

    schema_version: str
    ok: bool
    command: str
    invoked_as: str
    tree_text: str
    warnings: list[str] = Field(default_factory=list)


class FindEnvelope(PublicModel):
    """CLI JSON envelope for symbol search output."""

    schema_version: str
    ok: bool
    command: str
    root_path: str
    query: str
    limit: int
    min_score: int
    symbols: list[SymbolOutput]
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)


class InterfaceEnvelope(PublicModel):
    """CLI JSON envelope for interface output."""

    schema_version: str
    ok: bool
    command: str
    root_path: str
    file_path: str
    interface: str | None = None
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ImpactReference(PublicModel):
    """One impact reference from structural or text search."""

    file: str
    line: int
    text: str = ""
    type: str | None = None


class ImpactResult(PublicModel):
    """Successful impact-analysis payload."""

    references: list[ImpactReference]
    total_count: int
    strategy: str
    note: str


class ImpactEnvelope(PublicModel):
    """CLI JSON envelope for impact output."""

    schema_version: str
    ok: bool
    command: str
    root_path: str
    symbol: SymbolOutput
    impact: ImpactResult | dict[str, Any]
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ErrorEnvelope(PublicModel):
    """CLI JSON envelope for parse and validation errors."""

    schema_version: str
    ok: bool = False
    command: str | None = None
    error: str
    warnings: list[str] = Field(default_factory=list)


def _validation_error_message(exc: ValidationError) -> str:
    error = exc.errors()[0]
    location = ".".join(str(part) for part in error["loc"])
    return f"field '{location}': {error['msg']}"


def dump_symbol_output(value: Any) -> dict[str, Any]:
    """Validate and dump a public symbol payload."""
    return SymbolOutput.model_validate(value).to_payload()


def dump_explore_data(value: Any) -> dict[str, Any]:
    """Validate and dump structured explore data."""
    model = ExploreData.model_validate(value)
    payload = model.to_payload()
    payload["options"]["max_depth"] = model.options.max_depth
    return payload


def dump_explore_envelope(value: Any) -> dict[str, Any]:
    """Validate and dump the CLI explore envelope."""
    model = ExploreEnvelope.model_validate(value)
    payload = model.to_payload()
    payload["options"]["max_depth"] = model.options.max_depth
    return payload


def dump_find_envelope(value: Any) -> dict[str, Any]:
    """Validate and dump the CLI find envelope."""
    model = FindEnvelope.model_validate(value)
    payload = model.to_payload()
    payload["error"] = model.error
    return payload


def dump_interface_envelope(value: Any) -> dict[str, Any]:
    """Validate and dump the CLI interface envelope."""
    model = InterfaceEnvelope.model_validate(value)
    payload = model.to_payload()
    payload["interface"] = model.interface
    payload["error"] = model.error
    return payload


def dump_impact_result(value: Any) -> dict[str, Any]:
    """Validate and dump an impact result or preserve an error payload."""
    if isinstance(value, dict) and "error" in value:
        error_payload = cast(dict[Any, Any], value)
        return {str(key): item for key, item in error_payload.items()}
    return ImpactResult.model_validate(value).to_payload()


def dump_impact_envelope(value: Any) -> dict[str, Any]:
    """Validate and dump the CLI impact envelope."""
    model = ImpactEnvelope.model_validate(value)
    payload = model.to_payload()
    payload["error"] = model.error
    return payload


def dump_error_envelope(value: Any) -> dict[str, Any]:
    """Validate and dump a CLI error envelope."""
    model = ErrorEnvelope.model_validate(value)
    payload = model.to_payload()
    payload["command"] = model.command
    return payload


def validate_symbol_input(value: Any) -> dict[str, Any]:
    """Validate a symbol-like mapping and return a plain dict preserving extras."""
    try:
        return SymbolInput.model_validate(value).model_dump(exclude_none=True)
    except ValidationError as exc:
        raise ValueError(f"Symbol input {_validation_error_message(exc)}") from exc
