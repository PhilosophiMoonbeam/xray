---
name: xray-cli
description: "Use the XRAY command-line interface for agentic code discovery: map repositories, find symbols, inspect file interfaces, assess symbol impact, and automate JSON or jq handoffs. Use when a coding agent can run shell commands and needs the handwritten xray CLI rather than the XRAY MCP search_tools/call_tool workflow."
---

# XRAY CLI

Use XRAY as a progressive code-discovery CLI before reading large files or making changes.
Prefer this skill when shell access is available. For MCP clients, use the separate XRAY MCP skill and its `search_tools` -> `call_tool` workflow.

## Command Form

Use the installed command when available:

```bash
xray explore . --max-depth 2
```

From an XRAY source checkout, use `uv run`:

```bash
uv run xray explore . --max-depth 2
```

From another checkout without installing XRAY, use `uvx --from /path/to/xray`:

```bash
uvx --from /path/to/xray xray find . "target symbol"
```

## Progressive Workflow

1. Map the repository first.

```bash
xray explore ROOT --max-depth 2
xray explore ROOT --focus src --include-symbols --max-symbols-per-file 5
```

Use `xray map` only as an alias for `xray explore`. In JSON output, alias calls still report `command: "explore"` and include `invoked_as: "map"`.

2. Find the symbol or behavior.

```bash
xray find ROOT "AuthService.validate_user" --limit 5 --min-score 60
```

`find` defaults to JSON. Preserve the full symbol object, including `path`, `abs_path`, `start_line`, `end_line`, and `type`.

3. Inspect the file interface before loading implementation.

```bash
xray interface ROOT src/package/module.py
```

Interface output is a skeleton of signatures, classes, types, and docstrings. It is intended to reduce context use before reading full source.

4. Assess impact before changing a public symbol.

```bash
symbol=$(xray find ROOT "target_function" --limit 1 | jq -c '.symbols[0]')
xray impact ROOT --symbol-json "$symbol"
```

## JSON Automation

Use `--format json` when another tool or script will consume the result:

```bash
xray explore ROOT --focus src --include-symbols --format json
xray interface ROOT src/package/module.py --format json
xray impact ROOT --symbol-json "$symbol" --format json
```

Stable JSON envelopes use `schema_version: "xray.cli.v1"` and `ok`.
Important payload fields:

- `explore`: `entries`, `tree_text`, `options`, `invoked_as`, `warnings`
- `find`: `symbols`, `query`, `limit`, `min_score`, `error`, `warnings`
- `interface`: `interface`, `file_path`, `error`, `warnings`
- `impact`: `symbol`, `impact`, `error`, `warnings`

Pipe a symbol through stdin when shell quoting is awkward:

```bash
xray find ROOT "target_function" --limit 1 \
  | jq -c '.symbols[0]' \
  | xray impact ROOT --symbol-file -
```

Do not request YAML output. XRAY intentionally supports only `text` and `json` formats.

## Path Safety

Pass repository roots explicitly. `interface` file paths may be absolute or relative to `ROOT`, but they must resolve inside `ROOT`.

`impact` symbol paths must also resolve inside `ROOT` when called through the CLI. This is why symbols returned by `xray find` are the safest input to `xray impact`.

Expected failure behavior:

```bash
xray interface ROOT /etc/passwd --format json
xray impact ROOT --symbol-json '{"name":"x","path":"/etc/passwd","start_line":1}' --format json
```

Both should reject outside-root access without leaking file contents.

## Exit Codes And Errors

XRAY returns process exit codes instead of letting `argparse` terminate the Python process.

- `0`: successful command
- `1`: command-level failure, such as interface extraction returning an error
- `2`: parse or validation error

When `--format json` is requested, validation and parse errors are JSON error envelopes on stderr. Without JSON format, parse errors are plain terminal text.

## Practical Defaults

Use these defaults unless the task suggests otherwise:

- Start with `xray explore ROOT --max-depth 2`.
- Add `--focus DIR --include-symbols` only after identifying likely directories.
- Use `xray find` with `--min-score 60` when fuzzy matches are noisy.
- Keep full symbol JSON for impact analysis instead of reconstructing symbols by hand.
- Use `jq -c '.symbols[0]'` for compact shell handoffs.
- Treat the CLI as the automation surface; use MCP only when the environment is an MCP client.
