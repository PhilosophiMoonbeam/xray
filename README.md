# XRAY - Agent-Centric Code Intelligence CLI and MCP Server

[![Python](https://img.shields.io/badge/Python-3.10+-green)](https://python.org)
[![MCP](https://img.shields.io/badge/MCP-Compatible-purple)](https://modelcontextprotocol.io)
[![ast-grep](https://img.shields.io/badge/Powered_by-ast--grep-orange)](https://ast-grep.github.io)

XRAY gives agents a compact way to map a repository, find symbols, inspect file
interfaces, estimate symbol impact, and perform structural code operations without
running a language server. Use the handwritten `xray` CLI in shell workflows, or
run `xray-mcp` from an MCP-capable assistant.

## Agent harness

Repository automation starts at [`AGENTS.md`](AGENTS.md). The
[`migration manifest`](TEMPLATE_MANIFEST.md) links the XRAY-owned
[`adaptation`](docs/ADAPTATION.md), [`routing`](docs/agent-model-routing.md),
[`operations`](docs/agent-operations.md),
[`implementation`](docs/implementation-standard.md), and
[`language`](docs/repository-language-standard.md) authorities. These harness
documents do not change the product behavior described below.

Progressive discovery starts with four operations:

- **Map** (`xray explore`, `xray map`, `explore_repo`) - show repository structure with optional symbol skeletons.
- **Find** (`xray find`, `find_symbol`) - locate definitions by calibrated name or owner-qualified identity.
- **Interface** (`xray interface`, `read_interface`) - read signatures, types, and public members without implementation bodies.
- **Impact** (`xray impact`, `what_breaks`) - find likely references to a symbol name.

Structural search, rewrite, rule scanning, and import/export outlines complement
that workflow when symbol-name analysis is not enough. For changes, prefer the
guarded replacement plan/apply workflow over the explicit legacy all-match rewrite.

## Quick Start

```bash
# Run from a checkout without installing
uvx --from . xray explore . --max-depth 2

# Add source symbols when the agent needs more detail
uvx --from . xray explore . --focus src --include-symbols

# Use text only for a compact lossy scan
uvx --from . xray explore . --focus src --include-symbols --format text

# Find symbols as scored JSON, filtering weak matches when needed
uvx --from . xray find . "XRayIndexer" --min-score 60

# Inspect a file interface
uvx --from . xray interface . src/xray/core/indexer.py

# Review likely symbol-name references from a symbol found by `xray find`
symbol=$(uvx --from . xray find . "XRayIndexer" --limit 1 | jq -c '.symbols[0]')
uvx --from . xray impact . --symbol-json "$symbol"
```

## Install

XRAY requires Python 3.10 or later. Its direct runtime dependencies are
`fastmcp>=3.4.7,<4`, `ast-grep-cli>=0.45.1,<0.46`,
`ast-grep-py>=0.45.1,<0.46`, `thefuzz>=0.20.0`, `pydantic>=2,<3`, and
`pathspec>=0.12,<1`.

XRAY requires the `ast-grep` executable. The installation commands below provide
it automatically through `ast-grep-cli`; the aligned `ast-grep-py` runtime
provides semantic compact-capture projection; no separate installation is
normally required.

```bash
# Install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install XRAY as a persistent tool
git clone https://github.com/PhilosophiMoonbeam/xray.git
cd xray
uv tool install .

# Install XRAY's bundled agent skill for this user
xray skill install --user

# Run from anywhere after installation
xray explore . --max-depth 2
xray-mcp
```

`uv tool install` accepts uv's own options, but it does not forward arbitrary
XRAY flags or run a package-defined post-install hook. Skill placement is
therefore an explicit second step. To keep the skill only in one repository,
run:

```bash
xray skill install --project /path/to/project
```

Both scopes install `xray-cli` below `.agents/skills/`. Repeating the command
is a no-op when the installed files already match. If that target contains
different files, XRAY preserves it and exits with a validation error; inspect
the target before explicitly replacing it with `--force`. Symlinked install
paths are rejected.

For local development:

```bash
uv sync --dev
uv run pytest
uv run xray explore . --max-depth 2
uv run xray-mcp
```

The package exposes both console scripts:

- `xray` -> `xray.cli:main`
- `xray-mcp` -> `xray.mcp_server:main`

The packaged MCP skill files under `src/xray/skills/` are included in package
data so MCP clients can fetch the progressive-discovery skill resource. An
exact distributable copy of the repository CLI skill is packaged under
`src/xray/agent_skills/` for `xray skill install`; packaging tests keep the two
copies byte-identical.

## CLI Reference

The `xray` command is the supported user-facing CLI. Run `xray COMMAND --help`
for complete command options.

### `xray explore` / `xray map`

`explore` is the canonical command. `map` is an alias that produces the same
operation; JSON output records `command: "explore"` and `invoked_as: "map"` when
the alias is used.

```bash
xray explore ROOT [--max-depth N | --all-depths] [--include-symbols | --symbols] \
  [--focus PATH]... [--max-symbols-per-file N] [--type TYPE[,TYPE...]] [--max-entries N | --limit N] \
  [--strict-focus] [--no-default-exclusions] \
  [--detail compact|full] [--schema v2|v3] [--format json|text] [--pretty]
```

Important options:

- Maps default to depth two. `--max-depth N` changes that bound;
  `--all-depths` explicitly removes it.
- `--include-symbols` and `--symbols` include compact file skeletons.
- `--focus PATH` accepts contained nested files or directories. Focus retains
  root-level context files and the complete ancestor chain, then traverses only
  selected descendant subtrees.
- `--strict-focus` traverses focus ancestors internally but emits only each
  focus and its descendants, so entry limits are spent on requested results.
- `--max-symbols-per-file N` limits skeleton detail per file and must be zero or greater.
- `--max-entries N` and its `--limit N` alias bound map entries (default: 5000).
- Compact JSON is the default and returns structured `entries` without duplicated `tree_text`, absolute paths, names derivable from paths, or empty envelope fields.
- `--detail full` preserves the v1 JSON tree and entry payload.
- `--format text` returns the compact lossy tree view.
- `--pretty` indents JSON output for visual inspection.

Explore output excludes common dependency, cache, build, generated metadata, and
agent/task state directories by default so maps stay focused on maintainable
project files. `--no-default-exclusions` disables only that named built-in policy;
root and nested `.gitignore` rules, including anchoring and negation, remain active.

Explore uses one traversal to produce both `tree_text` and `entries`. When the
entry bound is reached, JSON and MCP payloads set `truncated: true` and include
a warning; text output appends a truncation notice. Narrow with `--focus` or
`--max-depth`, or explicitly raise `--max-entries`, to continue exploration.

`xray explore --include-symbols --type class,interface` filters skeletons to the
requested top-level ast-grep outline symbol types. The filter is recorded as
`options.symbol_types` in JSON output. ast-grep's expanded outline supplies the
signatures used by both `explore` and `interface`, improving consistent extraction
across Python, JavaScript/TypeScript, and Go.

### `xray find`

```bash
xray find ROOT QUERY [--limit N] [--cursor TOKEN] [--min-score 0-100] \
  [--path PATH]... [--language LANG]... [--type TYPE]... \
  [--visibility public|private|unknown]... [--detail compact|full]
```

JSON is the default because symbol objects are usually piped into impact
analysis. JSON symbols include `name`, repository-relative `path`, absolute
`abs_path`, one-based `start_line`/`end_line`, `type`, `score`, `qualified_name`,
`owner`, `language`, `match_reason`, and `confidence`. One expanded ast-grep
outline supplies a snapshot-cached inventory; dirty source changes invalidate it.

Compact v3 is the default, with scores, a 10-result page, and `min_score: 60`.
Filters run before paging and every filter is cursor-bound. Use `--min-score 0`
only to inspect calibrated low-confidence candidates. `--detail full` preserves
the v1 envelope. Find promises name identity matching, not semantic behavior search.

### `xray interface`

```bash
xray interface ROOT FILE_PATH [--name NAME]... [--type TYPE]... \
  [--visibility VISIBILITY]... [--member-depth N] [--max-members N] \
  [--limit N] [--cursor TOKEN] [--detail compact|full] [--schema v2|v3]
xray interface ROOT --symbol-json "$symbol"
```

`FILE_PATH` may be absolute or relative to `ROOT`, but it must resolve inside the
repository root. XRAY rejects parent traversal and symlink escapes rather than
reading files outside the requested repository. Compact JSON returns hierarchical
symbols, direct members, signatures, one-based ranges, visibility, role,
documentation, `complete`, and warnings. `--detail full` preserves the legacy v1
string envelope. Typed compact errors distinguish missing, unsupported,
containment, parse, upstream, and size failures.

V3 removes duplicate symbol/page counts, returns `completeness.reasons` such as
`member_truncated` and `page_truncated`, and accepts exact symbol JSON/file input.
A member symbol returns only its owner and selected member path.

Use `xray read-symbol ROOT` with the same symbol JSON/file/manual inputs as
impact to return a bounded exact source slice. `xray symbol-at ROOT FILE LINE`
returns the narrowest enclosing symbol or an explicit `found: false` result.
Exact reads verify the supplied path, range, name, type, and qualified identity
against the current inventory; stale or tampered handoffs fail with
`symbol_mismatch` instead of returning source under caller-supplied labels.

### `xray impact`

```bash
xray impact ROOT --symbol-json '{"name":"target","path":"src/app.py","start_line":1}'
xray impact ROOT --symbol-file symbol.json
xray impact ROOT --symbol-file -
xray impact ROOT --name target --path src/app.py --start-line 1 [--type function]
```

Impact also accepts `--limit N`, `--cursor TOKEN`, `--detail compact|full`,
`--context-lines N`, `--schema v2|v3`, `--format json|text`, and `--pretty`.

Provide exactly one symbol source:

- `--symbol-json` for an inline symbol object, usually from `xray find`.
- `--symbol-file PATH` for a JSON file.
- `--symbol-file -` to read the symbol JSON from stdin.
- `--name` with `--path` and `--start-line` for manual symbols.

Manual symbols require `--start-line` so XRAY can exclude the definition line
from impact results. Symbol paths must resolve inside `ROOT`. Impact analysis
is name-based; review results for same-name symbols because XRAY is not a
type-aware caller or dependency graph. Use `--end-line` to supply the full
definition range and `--context-lines N` to control reference context. Compact
references use relative paths, one matched line, a `definition`, `import`, `call`,
`read`, or `text` classification, and `high`, `medium`, or `low` confidence.
Other same-name definitions are classified rather than described as dependents.

### Structural search, rewrite, rules, imports, and exports

```bash
xray search ROOT -p 'old_api($ARG)' [-l python]
xray rewrite ROOT -p 'old_api($ARG)' -r 'new_api($ARG)' -l python
xray scan ROOT --rule sgconfig.yml [--fix]
xray rules check ROOT --rule rule.yml
xray rules explain ROOT --rule rule.yml
xray rules test ROOT --test-dir rule-tests [--config sgconfig.yml]
xray imports ROOT src/package/module.py
xray exports ROOT src/package/module.py
```

`search` and `scan` accept repeatable `--path` scopes and ordered `--glob`
filters. Every path must resolve inside `ROOT`.

Read-only `search`, `scan`, `rules check`, `imports`, and `exports` accept
`--detail compact|full`, a positive `--limit N`, `--cursor TOKEN`,
`--format json|text`, and `--pretty`. Compact detail is the default and returns
XRAY-owned fields such as relative `path`, one-based `line`/`column`, `text`, and
`captures`. Full detail retains lossless upstream ast-grep JSON.

Continuable reads require a positive limit; the default is 50 returned items.
Repository-wide read-only search, scan, and impact stop upstream work after the
page-derived candidate cap. Responses
include `returned`, `total`, `total_exact`, and `truncated`; `total_exact: false`
means `total` is a lower bound. When more results exist, pass the opaque
`next_cursor` back as `--cursor`. Cursors bind command, root, query, scopes,
projection, and source content; continuation rejects a changed snapshot. Page
size is not cursor identity, so a later page may use a different positive limit
without overlap or omission. Limits only bound
reported diagnostics for legacy mutation: `rewrite` and `scan --fix` still apply
every matching edit and do not advertise continuation after mutation.

`search` returns ast-grep matches, including captured metavariables. `rewrite`
applies every structural replacement in place and reports match and modified-file
counts. `scan` runs a rule configuration inside `ROOT`; `--fix` applies configured
fixes without prompting. Import/export paths are confined to `ROOT` and use
ast-grep outline for file dependency and public-API inspection.

The `rules check`, `rules explain`, and `rules test` family is read-only.
Check returns compact relative-path, one-based citations by default and supports
paging; `--detail full` retains raw ast-grep diagnostics. Explain returns bounded
rule source, validation evidence, raw `inspection`, and lossless
`inspection_lines` without parsing YAML into an XRAY format. Test disables
snapshot updates, color, and interactive review. Legacy CLI `scan --fix` remains
the explicit all-match rule mutation path.

Compact `rewrite` output omits pre-rewrite matches and reports only counts and
modified paths. Use `--detail full` when the match payload is required.

`rewrite` and `scan --fix` modify files in place. Review their JSON summaries and
the worktree after running them.

For rewrites, pass `-l/--lang` whenever the target language is known. Inference
can still produce an overly broad repository scan that matches pattern-like text
inside configuration or documentation files.

### Guarded replacement

Use JSON-first plan/apply for new mutation workflows:

```bash
xray replace plan ROOT \
  --pattern 'old_api($ARG)' --replacement 'new_api($ARG)' --lang python \
  --path src --glob '*.py' | jq '.plan' > plan.json

# Review every edit_id, preview, diff, warning, bound, applicability value, hash, and digest.
jq -r '.edit_manifest[].edit_id' plan.json
xray replace refine ROOT --plan-file plan.json --edit-id EDIT_ID | jq '.plan' > refined.json
reviewed_digest=$(jq -r '.plan_digest' refined.json)
xray replace verify ROOT --plan-file refined.json --expected-digest "$reviewed_digest"
xray replace apply ROOT --plan-file refined.json --expected-digest "$reviewed_digest"
```

Planning is non-mutating and defaults to at most 1000 candidates, 100 affected
files, 50 preview edits, and a bounded deterministic unified diff. An
`xray.replace.v2` plan records every stable edit ID, exact query/selection,
source/postimage hashes, warnings, applicability, and complete-artifact digest.
Preview or diff truncation makes a plan inapplicable unless explicit
`--allow-truncated-review` acknowledgement is recorded. Zero-candidate plans
are inapplicable and all-no-op plans require `--allow-noop`. Applying rejects
new parse errors and dirty affected files unless their exceptional
`--allow-new-parse-errors` or `--allow-dirty-affected` acknowledgements were
recorded in the plan. `replace verify` recomputes every apply guard without
writing. Applying rejects v1 plans and requires the complete plan plus an independently copied reviewed
digest. XRAY recomputes the candidate set and rejects root, query, count, digest,
source, syntax, or dirty-state drift before writing. It prepares same-directory
staged files, preserves file modes, verifies postimages, and restores already
replaced files if a later replacement fails. Process termination cannot
guarantee rollback, so use a recoverable worktree and inspect the final diff.
Interpret rollback fields by checking `rollback_attempted` first;
`rollback_succeeded` is meaningful only when an attempt occurred. A successful
apply or pre-write failure therefore reports no restoration attempt.
`root_fingerprint` binds the normalized root, Git commit when available, the
complete query (including selected edit IDs), and affected source preimages.
Selection-only refinement changes it even when source bytes do not drift.
Use `--rule` instead of pattern/replacement to plan a fix-bearing
ast-grep rule. `rewrite` remains available only as an explicit legacy all-match
operation.

## JSON Output

Compact output defaults to `schema_version: "xray.cli.v3"`, with consistent
`ok`, one paging vocabulary, typed interface completeness reasons, exact-symbol
interface handoff, and named compact impact diagnostics. `--schema v2` selects
the previous compact projection for diagnosis; it is not a compatibility
commitment. `--detail full` preserves v1 where supported. JSON is one line
unless `--pretty` is requested; text is lossy.

Exit codes are `0` for success, `1` for command failure, and `2` for parse or
validation errors.

Command-specific fields:

- compact `explore`: `invoked_as`, `root_path`, `entries`, `options`, `truncated`, and warnings only when present.
- compact `find`: filtered scored `symbols` plus exact paging metadata; full preserves v1.
- compact `interface`: typed hierarchical `interface` with completeness/warnings; full v1 preserves the string projection.
- compact `impact`: `symbol` plus classified relative-path references, strategy/degradation, counts, and exact paging metadata.
- `replace.plan` / `replace.refine`: complete `xray.replace.v2` review artifacts;
  `replace.apply`: truthful changed/no-op/file and rollback evidence.
- compact `search` / `scan` / `rules.check`: projected `matches` and page metadata.
- compact `rewrite`: `match_count`, `files_modified`, and `file_count`.
- compact `imports` / `exports`: projected `items` and page metadata.

Example:

```json
{
  "schema_version": "xray.cli.v3",
  "ok": true,
  "command": "find",
  "root_path": "/repo",
  "query": "target",
  "limit": 3,
  "min_score": 60,
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
  "returned": 1,
  "total": 1,
  "total_exact": true,
  "truncated": false,
  "warnings": []
}
```

Impact keeps its page metadata under `.impact`; other compact paged commands
place it at the command result level. `xray capabilities [ROOT]` and its
`doctor` alias report version, schemas, plan versions, mutation classes,
language support, bounds, timeouts, cache behavior, dependencies, health, and
workflow resources. Repository checks appear only when `ROOT` is supplied.

## MCP Usage

The MCP server is optimized for progressive discovery and context economy.
Clients initially see only `search_tools` and `call_tool`. They discover the
underlying XRAY operations through search, then execute them through `call_tool`
with a `{name, arguments}` payload.

`search_tools` ranks natural intent by default and supports `mode: "regex"` for
explicit regular expressions. Summary results omit full schemas; request
`detail: "full"` only when preparing a call. Results report exact totals,
truncation, and `next_cursor`. Ordinary change intent ranks guarded planning and
hides legacy `rewrite_pattern`; exact legacy intent can still discover it.

```json
{
  "name": "explore_repo",
  "arguments": {
    "root_path": "/path/to/repo",
    "max_depth": 2,
    "include_symbols": true,
    "symbol_types": ["class", "interface"]
  }
}
```

The transformed MCP surface exposes compact metadata and tags for:

- `explore_repo`: depth-two compact map with nested focus; `all_depths: true`
  explicitly removes the depth bound.
- `find_symbol`: calibrated name/qualified-identity filters, scores, and paging.
- `read_interface`: read a text file interface without implementation bodies.
- `read_interface_structured`: bounded/filterable typed hierarchy with paging;
  default v3 `exact_symbol` returns only the selected owner/member path.
- `read_symbol` and `symbol_at`: bounded exact source and line-to-symbol lookup.
- `search_pattern`: compact structural matches, bounded to 50 by default, with `returned`, `total`, `truncated`, and snapshot-bound `next_cursor` continuation. Set `detail: "full"` for raw ast-grep matches.
- `rewrite_pattern`: in-place replacement with a compact count/path summary by default. Full detail is bounded but never advertises continuation after mutation.
- `plan_replacement`, `refine_replacement`, and `verify_replacement`: non-mutating v2 review, edit selection, and guard verification.
- `apply_replacement`: destructive guarded application requiring the complete plan and independently supplied digest.
- `scan_rules`, `check_rules`, `explain_rules`, and `test_rules`: read-only rule operations.
- `apply_rule_fixes`: destructive application of a reviewed v2 rule plan.
- `xray_capabilities`: help, contracts, limits, dependencies, and health.
- `file_imports` and `file_exports`: compact flattened dependency and public-API outlines with limits and continuation cursors.
- `what_breaks`: assess bounded classified symbol-name references with snapshot-bound continuation; compact v3 is the default projection.

MCP failures are protocol errors (`isError: true`) with identical JSON text and
structured `error: {code, message, details?}` content. `scan_rules` has read-only
annotations and no mutation argument; `apply_rule_fixes` alone carries the
guarded destructive rule-fix contract.

Detailed guidance is available on demand:

- Resource: `xray://workflow`
- Prompt: `xray_discovery_plan`
- Skill: `skill://xray-progressive-discovery/SKILL.md`
- Skill template: `skill://xray-progressive-discovery/{path*}`

`what_breaks` requires an absolute `path` or `abs_path` when called through MCP.
The CLI `find` JSON already includes `abs_path`, so CLI symbols can be passed to
MCP impact analysis directly.

`xray skill install` is intentionally CLI-only. It manages local agent guidance
under `.agents/skills`; it is not a repository-analysis MCP capability.

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
git clone https://github.com/PhilosophiMoonbeam/xray.git
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

For installed uv tools, configure clients to run the direct installed command.
`xray-mcp` fixes the FastMCP transport to stdio; XRAY does not expose an HTTP or
OAuth deployment surface through this entry point.
For example:

Codex `config.toml`:

```toml
[mcp_servers.xray]
command = "xray-mcp"
```

JSON MCP clients:

```json
{
  "mcpServers": {
    "xray": {
      "command": "xray-mcp"
    }
  }
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
/tmp/.xray_cache/{root_hash}-{git_commit}/symbols.json
/tmp/.xray_cache/{root_hash}-{git_commit}/inventory.json
```

The root hash prevents repositories at the same commit from sharing cache files;
JSON cache writes are atomic.

MCP indexer instances are cached per normalized root path, and per-repository
locks serialize operations against shared indexer state. Same-root and multi-root
concurrent calls are supported.

## Performance Characteristics

- Startup is lightweight; XRAY launches subprocesses on demand.
- Directory maps use Python traversal with Git-wildmatch repository ignores, named built-in exclusions, focus, and depth bounds.
- Symbol search uses one expanded ast-grep outline per content-hashed supported-source snapshot, then scores the cached inventory in memory.
- Python interface reads use the standard-library AST for complete signatures/docstrings; other supported languages preserve ast-grep's expanded hierarchy and report incompleteness.
- Impact uses a page-derived execution cap for supported source files, then falls back to bounded text search when structural search returns no references.
- Memory use is low; the only persistent runtime artifact is the optional temp cache.

## Limitations

XRAY is intentionally smaller than a language server:

- `what_breaks` is a symbol-name reference search, not a type-aware dependency graph.
- Impact fallback text search may include comments or strings.
- XRAY does not answer direct "what depends on this class?" graph queries unless that can be approximated from symbol references.
- `symbol-at`/`symbol_at` resolves the narrowest supported symbol at a line; it
  does not provide language-server type or reference resolution.
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

See `src/xray/skills/xray-progressive-discovery/SKILL.md` for the MCP skill that
clients can fetch at runtime.
