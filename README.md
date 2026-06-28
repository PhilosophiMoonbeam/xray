# XRAY - Agent-Centric Code Intelligence CLI and MCP Server

[![Python](https://img.shields.io/badge/Python-3.10+-green)](https://python.org)
[![MCP](https://img.shields.io/badge/MCP-Compatible-purple)](https://modelcontextprotocol.io)
[![ast-grep](https://img.shields.io/badge/Powered_by-ast--grep-orange)](https://ast-grep.github.io)

XRAY gives agents a compact way to map a repository, find symbols, inspect file
interfaces, and estimate symbol impact without running a language server. Use the
handwritten `xray` CLI in shell workflows, or run `xray-mcp` from an MCP-capable
assistant.

XRAY focuses on four operations:

- **Map** (`xray explore`, `xray map`, `explore_repo`) - show repository structure with optional symbol skeletons.
- **Find** (`xray find`, `find_symbol`) - locate functions, classes, methods, interfaces, types, enums, and common JS/TS/Go definitions by fuzzy name.
- **Interface** (`xray interface`, `read_interface`) - read signatures, class definitions, and docstrings without implementation bodies.
- **Impact** (`xray impact`, `what_breaks`) - find likely references to a symbol name.

## Quick Start

```bash
# Run from a checkout without installing
uvx --from . xray explore . --max-depth 2

# Add source symbols when the agent needs more detail
uvx --from . xray explore . --focus src --include-symbols

# Get a structured repository map for downstream automation
uvx --from . xray explore . --focus src --include-symbols --format json

# Find symbols as scored JSON, filtering weak matches when needed
uvx --from . xray find . "XRayIndexer" --min-score 60

# Inspect a file interface
uvx --from . xray interface . src/xray/core/indexer.py

# Assess impact from a symbol found by `xray find`
symbol=$(uvx --from . xray find . "XRayIndexer" --limit 1 | jq -c '.symbols[0]')
uvx --from . xray impact . --symbol-json "$symbol"
```

## Install

XRAY requires Python 3.10 or later. Runtime dependencies include FastMCP 3.4.x,
RapidFuzz, and `ast-grep-cli>=0.39.0`.

```bash
# Install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install XRAY as a persistent tool
git clone https://github.com/srijanshukla18/xray.git
cd xray
uv tool install .

# Run from anywhere after installation
xray explore . --max-depth 2
xray-mcp
```

For local development:

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
uv run pytest
uv run xray explore . --max-depth 2
uv run xray-mcp
```

The package exposes both console scripts:

- `xray` -> `xray.cli:main`
- `xray-mcp` -> `xray.mcp_server:main`

The packaged MCP skill files under `src/xray/skills/` are included in package
data so MCP clients can fetch the progressive-discovery skill resource.

## CLI Reference

The `xray` command is the supported user-facing CLI. It returns process exit
codes instead of letting `argparse` terminate the Python process, so tests and
agent wrappers can call `xray.cli.main()` directly.

### `xray explore` / `xray map`

`explore` is the canonical command. `map` is an alias that produces the same
operation; JSON output records `command: "explore"` and `invoked_as: "map"` when
the alias is used.

```bash
xray explore ROOT [--max-depth N] [--include-symbols | --symbols] \
  [--focus DIR ...] [--max-symbols-per-file N] [--format text|json]
```

Important options:

- `--max-depth N` limits directory traversal and must be zero or greater.
- `--include-symbols` and `--symbols` include compact file skeletons.
- `--focus DIR` can be repeated to keep output centered on selected top-level directories; root-level files remain visible for repository context.
- `--max-symbols-per-file N` limits skeleton detail per file and must be zero or greater.
- `--format json` returns both `tree_text` and structured `entries`.

Explore output excludes common dependency, cache, build, generated metadata, and
agent/task state directories by default so maps stay focused on maintainable
project files.

### `xray find`

```bash
xray find ROOT QUERY [--limit N] [--min-score 0-100] [--format json|text]
```

`find` defaults to JSON because symbol objects are usually piped into impact
analysis. JSON symbols include repository-relative `path`, absolute `abs_path`,
one-based `start_line`/`end_line`, `type`, and `score`.

`--limit` must be zero or greater. `--min-score` must be between 0 and 100; use
60 or higher when an agent should suppress weak fuzzy matches.

### `xray interface`

```bash
xray interface ROOT FILE_PATH [--format text|json]
```

`FILE_PATH` may be absolute or relative to `ROOT`, but it must resolve inside the
repository root. XRAY rejects parent traversal and symlink escapes rather than
reading files outside the requested repository.

### `xray impact`

```bash
xray impact ROOT --symbol-json '{"name":"target","path":"src/app.py","start_line":1}'
xray impact ROOT --symbol-file symbol.json
xray impact ROOT --symbol-file -
xray impact ROOT --name target --path src/app.py --start-line 1 [--type function]
```

Provide exactly one symbol source:

- `--symbol-json` for an inline symbol object, usually from `xray find`.
- `--symbol-file PATH` for a JSON file.
- `--symbol-file -` to read the symbol JSON from stdin.
- `--name` with `--path` and `--start-line` for manual symbols.

Manual symbols require `--start-line` so XRAY can exclude the definition line
from impact results. Symbol paths must resolve inside `ROOT`.

## JSON Output

JSON output is wrapped in a stable `schema_version: "xray.cli.v1"` envelope.
Every successful command includes `ok: true`, `command`, `root_path`, and
command-specific data. JSON errors use `ok: false`, `error`, and `warnings`.
Parse errors are JSON only when the caller requested `--format json`; otherwise
they are plain text for normal terminal ergonomics.

Command-specific fields:

- `explore`: `invoked_as`, `tree_text`, `entries`, `options`, `warnings`.
- `find`: `query`, `limit`, `min_score`, `symbols`, `error`, `warnings`.
- `interface`: `file_path`, `interface`, `error`, `warnings`.
- `impact`: `symbol`, `impact`, `error`, `warnings`. Impact payloads include `strategy`, `total_count`, `raw_count`, and `filtered_count` so callers can see when non-source, duplicate, or definition-range matches were removed.

Example:

```json
{
  "schema_version": "xray.cli.v1",
  "ok": true,
  "command": "find",
  "root_path": "/repo",
  "query": "target",
  "limit": 3,
  "min_score": 0,
  "symbols": [
    {
      "name": "target_function",
      "type": "function",
      "path": "src/sample.py",
      "abs_path": "/repo/src/sample.py",
      "start_line": 1,
      "end_line": 2,
      "score": 100
    }
  ],
  "error": null,
  "warnings": []
}
```

## MCP Usage

The MCP server is optimized for progressive discovery and context economy.
Clients initially see only `search_tools` and `call_tool`. They discover the
underlying XRAY operations through search, then execute them through `call_tool`
with a `{name, arguments}` payload.

```json
{
  "name": "explore_repo",
  "arguments": {
    "root_path": "/path/to/repo",
    "max_depth": 2,
    "include_symbols": true
  }
}
```

The transformed MCP surface exposes compact metadata and tags for:

- `explore_repo`: map repository structure and optional symbol skeletons.
- `find_symbol`: find code symbols by fuzzy name or behavior phrase.
- `read_interface`: read a file interface without implementation bodies.
- `what_breaks`: assess references to a returned symbol object.

Detailed guidance is available on demand:

- Resource: `xray://workflow`
- Prompt: `xray_discovery_plan`
- Skill: `skill://xray-progressive-discovery/SKILL.md`
- Skill template: `skill://xray-progressive-discovery/{path*}`

`what_breaks` requires an absolute `path` or `abs_path` when called through MCP.
The CLI `find` JSON already includes `abs_path`, so CLI symbols can be passed to
MCP impact analysis directly.

FastMCP's `generate-cli` can generate an ad hoc client from the MCP schema, but
XRAY does not ship that generated script as its primary CLI. With the search-first
MCP surface, generated commands mirror `search_tools` and `call_tool`; the
handwritten `xray` CLI remains clearer for map/find/interface/impact shell
workflows and keeps stable JSON envelopes for automation.

## Configure MCP Clients

XRAY supports two common MCP setup styles:

1. **Source checkout** - point the client at a cloned XRAY directory and run
   the server with `uv run`. Use this for development or when the server should
   track local source edits.
2. **Installed uv tool** - install XRAY once with `uv tool install`, then point
   the client at the installed `xray-mcp` command. Use this for everyday MCP
   client configuration when editable source behavior is not needed.

Install the persistent tool from a checkout:

```bash
git clone https://github.com/srijanshukla18/xray.git
cd xray
uv tool install .
command -v xray-mcp
```

Use `mcp-config-generator.py` from the repository root to generate either style:

```bash
uv run python mcp-config-generator.py cursor local_python
uv run python mcp-config-generator.py cursor installed_script
uv run python mcp-config-generator.py claude docker
uv run python mcp-config-generator.py claude installed_script
uv run python mcp-config-generator.py vscode source
uv run python mcp-config-generator.py vscode installed_script
```

Supported tools are `cursor`, `claude`, and `vscode`. Supported methods vary by
tool and include `local_python`, `docker`, `source`, and `installed_script`.

For source-checkout or local Python configurations, the generator emits commands
that run inside the repository environment, such as:

```json
{
  "command": "uv",
  "args": ["run", "python", "-m", "xray.mcp_server"]
}
```

For installed uv tools, the generator emits the direct installed command:

```json
{
  "command": "xray-mcp"
}
```

The installed-script configuration assumes `uv tool install .` has placed
`xray-mcp` on the MCP client's `PATH`. If the client cannot find it, use the
source-checkout configuration or add uv's tool bin directory to that client's
environment.

## Language and Symbol Support

XRAY uses ast-grep, a tree-sitter powered structural search tool, for symbol
discovery and code reference search.

Supported symbol patterns include:

- Python functions, async functions, classes, and methods.
- JavaScript functions, classes, arrow functions, and function expressions.
- TypeScript JavaScript-compatible definitions, interfaces, type aliases, and enums.
- Go functions, methods, structs, interfaces, and type aliases.

XRAY normalizes modern ast-grep JSON output, including `--json=compact` no-match
results, and supports current and older metavariable shapes.

## Architecture

```text
Agent CLI (src/xray/cli.py) / FastMCP Server (src/xray/mcp_server.py)
    |
    v
Core Engine (src/xray/core/indexer.py)
    |
    v
ast-grep subprocesses and lightweight Python fallbacks
```

XRAY is not an LSP client and does not require users to install or run language
servers. The legacy `src/xray/lsp_config.json` file is not part of the active
runtime path.

The indexer performs on-demand analysis against the repository path supplied to
the CLI or MCP tool. It does not maintain a database or project-wide service.
For speed, symbol skeleton extraction can be cached under:

```text
/tmp/.xray_cache/{root_hash}-{git_commit}/symbols.pkl
```

The root hash prevents repositories at the same commit from sharing cache files.
Cache writes are atomic to avoid partially written pickle files.

MCP requests run blocking indexer work in worker threads with
`asyncio.to_thread`. Shared indexer instances are cached per normalized root path,
and per-repository locks serialize operations that mutate or read shared indexer
state. Same-root and multi-root concurrent MCP calls are supported.

## Performance Characteristics

- Startup is lightweight; XRAY launches subprocesses on demand.
- Directory maps use Python filesystem traversal and honor focus/depth options.
- Symbol search runs multiple ast-grep patterns, so cost scales with repository size and language mix.
- Interface reads use Python AST for Python and regex skeleton extraction for other supported languages.
- Impact analysis first tries ast-grep reference search, then falls back to text search when structural search returns no references.
- Memory use is low; the only persistent runtime artifact is the optional temp cache.

## Limitations

XRAY is intentionally smaller than a language server:

- `what_breaks` is a symbol-name reference search, not a type-aware dependency graph.
- Impact fallback text search may include comments or strings.
- XRAY does not answer direct "what depends on this class?" graph queries unless that can be approximated from symbol references.
- XRAY does not provide a direct "what symbol is defined at line N?" tool.
- Unsupported languages may still appear in repository maps, but symbol extraction is limited to the supported patterns above.
- `interface` and `impact` reject paths outside the requested repository root.

## Testing

Run the full suite with:

```bash
uv run pytest
```

Quality checks:

```bash
uv run ruff format .
uv run ruff check .
uv run pyright
uv run vulture
```

Pyright currently runs in standard mode over `src`, `mcp-config-generator.py`, and `tests`; the strictness strategy is documented in `pyproject.toml`.

The tests cover:

- CLI envelopes, validation, path safety, aliases, JSON/text behavior, and package scripts.
- ast-grep command wrappers, no-match normalization, and parse errors.
- MCP search-first transforms, resource/prompt/skill exposure, progress events, and concurrent calls.
- Packaging metadata, FastMCP version bounds, package data for skills, and config generator output.

## More Details

See [`getting_started.md`](getting_started.md) for a longer installation-oriented
guide and `src/xray/skills/xray-progressive-discovery/SKILL.md` for the MCP skill
that clients can fetch at runtime.
