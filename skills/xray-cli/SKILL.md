---
name: xray-cli
description: "Use the XRAY command-line interface for agentic code discovery: map repositories, find symbols, inspect interfaces and likely symbol-name impact, structurally search or rewrite code, scan rules, inspect imports or exports, and automate JSON or jq handoffs. Use when a coding agent can run shell commands and needs the handwritten xray CLI rather than the XRAY MCP search_tools/call_tool workflow."
---

# XRAY CLI

Use XRAY for progressive code discovery before reading large files. Prefer the CLI when shell access is available; use the XRAY MCP skill only in MCP-only clients.

## Command Form

Use the command form available in the current workspace:

```bash
xray explore . --max-depth 2
uv run xray explore . --max-depth 2
uvx --from /path/to/xray xray find . "target symbol"
```

## Workflow

Map first, then narrow:

```bash
xray explore ROOT --max-depth 2
xray explore ROOT --focus src --include-symbols --max-symbols-per-file 5
```

Find symbols as JSON and keep the full object:

```bash
xray find ROOT "AuthService.validate_user" --limit 5 --min-score 60
```

Inspect interfaces before reading implementation:

```bash
xray interface ROOT src/package/module.py
```

Assess likely symbol-name references from full symbol JSON:

```bash
symbol=$(xray find ROOT "target_function" --limit 1 | jq -c '.symbols[0]')
xray impact ROOT --symbol-json "$symbol"
```

Use `xray map` only as an alias for `xray explore`; JSON still reports `command: "explore"` and `invoked_as: "map"`.

## Output Modes

- Compact JSON is the default for all commands.
- Use `--pretty` only for indented JSON inspection.
- Use `--format text` only for lossy, token-friendly scans.
- Do not request YAML.
- Preserve full symbol objects: `name`, `path`, `abs_path`, `start_line`, `end_line`, `type`, `score`.
- Treat `xray impact` as a name-based reference search, not a type-aware caller, dependent, or dependency graph.

```bash
xray find ROOT "target_function" --limit 1 \
  | jq -c '.symbols[0]' \
  | xray impact ROOT --symbol-file -
```

## Safety

Pass roots explicitly. `interface` paths and `impact` symbol paths must resolve inside `ROOT`; symbols from `xray find` are the safest input.

Use structural operations when symbol-name discovery is not enough:

```bash
xray search ROOT -p 'old_api($ARG)' -l python
xray imports ROOT src/package/module.py
xray exports ROOT src/package/module.py
xray scan ROOT --rule sgconfig.yml
xray rewrite ROOT -p 'old_api($ARG)' -r 'new_api($ARG)'
```

`rewrite` and `scan --fix` modify files in place. Review their JSON summaries and
the worktree after running them.

Expected outside-root failures:

```bash
xray interface ROOT /etc/passwd
xray impact ROOT --symbol-json '{"name":"x","path":"/etc/passwd","start_line":1}'
```

Exit codes: `0` success, `1` command failure, `2` parse or validation error. Errors are JSON by default; `--format text` makes them plain text.
