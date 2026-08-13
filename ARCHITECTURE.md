# XRAY Architecture

This document is the authority for XRAY component boundaries, dependency
direction, public interfaces, compatibility, storage, and mutation behavior.
The product is a Python 3.10+ code-intelligence CLI and FastMCP server. The
multi-agent harness controls development of that product; it is not part of the
product runtime.

## System boundaries

```text
shell agents and scripts                 MCP-capable clients
          |                                      |
          v                                      v
  src/xray/cli.py                       src/xray/mcp_server.py
          |                                      |
          +-----------+--------------------------+
                      v
        src/xray/models.py + src/xray/presentation.py
                      |
                      v
              src/xray/core/indexer.py
                      |
                      v
              src/xray/core/ast_grep.py
                      |
                      v
        repository files + ast-grep subprocesses
```

Dependencies point downward in this diagram. Adapters may call presentation,
models, and the core; the core never imports the CLI, MCP server, installers,
skills, reports, tests, or harness. Presentation and public models may describe
core values but do not perform repository analysis. Distribution and guidance
wrap the adapters without becoming runtime dependencies of them.

XRAY is on-demand tooling, not a daemon-backed indexing service. It has no
supported product database. The tracked `.xray/xray.db`, `.xray/xray.db-shm`,
and `.xray/xray.db-wal` files are obsolete generated state scheduled for
removal by the adoption; they are not architecture or supported storage.

## Component and ownership map

| Component | Owned paths | Responsibility and interfaces | May depend on |
|---|---|---|---|
| CLI adapter | `src/xray/cli.py`, `xray` entry point | Parses `explore`/`map`, `find`, `interface`, `impact`, `search`, `rewrite`, `scan`, `imports`, and `exports`; validates bounded input; emits stable JSON or lossy text and process exit codes. | Public models, presentation, indexer |
| MCP adapter | `src/xray/mcp_server.py`, `xray-mcp` entry point | Runs `FastMCP("XRAY Code Intelligence")`; presents search-first tools, workflow resource/prompt, packaged skill resources, progress, tool annotations, and concurrency-safe indexer access. | Public models, presentation, indexer, FastMCP |
| Public models | `src/xray/models.py` | Pydantic validation and serialization for symbol, explore, find, interface, impact, and error values. Models allow compatible extra fields and normalize validation errors. | Pydantic and value types only |
| Presentation contract | `src/xray/presentation.py` and adapter-specific envelope code in `src/xray/cli.py` | Projects full engine data into compact relative-path records, owns pagination metadata and opaque query-bound cursors, and keeps compact output sparse. | Public/core value shapes; no I/O analysis |
| Indexing engine | `src/xray/core/indexer.py` | Resolves and contains repository paths; maps trees; extracts outlines; finds symbols; reads interfaces; estimates name-based impact; delegates structural operations; owns optional cache lifecycle. | ast-grep wrapper, filesystem, bounded Git/rg/Python fallbacks |
| ast-grep boundary | `src/xray/core/ast_grep.py` | Executes the external `ast-grep` program with time and output bounds; normalizes no-match and JSON behavior; raises typed failures. | `ast-grep` executable and subprocess APIs only |
| MCP configuration generator | `mcp-config-generator.py` | Prints JSON client configuration for Cursor, Claude, and VS Code using supported source, local-Python, Docker, or installed-script forms. It does not edit client files. | Static configuration data, JSON, current path |
| Package and entry points | `pyproject.toml`, `src/xray/__init__.py` | Defines Python `>=3.10`, dependencies, version, `xray = xray.cli:main`, `xray-mcp = xray.mcp_server:main`, package discovery, and package data. | Setuptools metadata |
| Install lifecycle | `install.sh`, `uninstall.sh` | Installs or removes the `xray` uv tool and its checkout under the explicit script contract; verifies both console scripts. These are sensitive filesystem, network, PATH, Git, and tool-state mutation boundaries. | uv, shell, Git/network when cloning |
| Repository CLI skill | `skills/xray-cli/SKILL.md`, `skills/xray-cli/agents/openai.yaml` | Teaches shell-capable agents the stable handwritten CLI, compact JSON, jq/symbol handoffs, containment, paging, and mutation safety. It is repository guidance, not Python package data. | Public CLI contract |
| Packaged MCP skill | `src/xray/skills/xray-progressive-discovery/SKILL.md` | Supplies progressive MCP discovery through `skill://xray-progressive-discovery/SKILL.md` and its template resource. It ships as `xray` package data. | Public MCP contract |
| Tests and fixtures | `tests/`, `test_samples/` | Verify adapters, contracts, safety, packaging, configuration output, ast-grep normalization, and concurrency. Samples are multi-language fixtures and are excluded from production package/runtime authority. | Public behavior and test dependencies |
| Audit reports | `.reports/` | Preserve point-in-time token-efficiency and installed-dogfood evidence. Reports are descriptive evidence, not runtime or current contract authority. | Observed artifacts only |
| Development harness | `AGENTS.md`, `PROJECT.md`, `ARCHITECTURE.md`, `TEMPLATE_MANIFEST.md`, `docs/`, `examples/`, `.codex/`, `.claude/`, `.agents/`, `Makefile`, `.gitignore` | Defines readiness, agent behavior, checks, recovery, and adoption policy. Harness scripts may invoke product gates; product source does not import harness assets. | Repository policy and development tools |

The product owner controls supported behavior in `src/xray/`, packaging, the
configuration generator, installers, product skills, and product documentation.
The engine owner controls repository traversal, containment, caches,
subprocesses, and mutation mechanics. Adapter owners control their respective
surface shapes without changing shared engine semantics. The harness owner may
strengthen development gates but may not redefine product APIs or schemas.

## CLI contract

The handwritten `xray` CLI is the automation authority for shell workflows.
JSON is the default; YAML is not an output mode and is not planned. Text output
is explicitly lossy and intended for visual scanning.

- Compact `explore`, `search`, `scan`, `rewrite`, `imports`, and `exports`
  responses use sparse `schema_version: "xray.cli.v2"` envelopes by default.
- `--detail full` preserves verbose v1-compatible data for commands that offer
  detail selection. `find`, `interface`, `impact`, and error envelopes remain
  `xray.cli.v1`.
- `map` is an alias for `explore`; JSON records `command: "explore"` and
  `invoked_as: "map"`.
- JSON is one line unless `--pretty` is requested. Full symbol objects retain
  `name`, `path`, `abs_path`, one-based `start_line`/`end_line`, `type`, and
  `score`, so `jq` and `--symbol-json`/`--symbol-file -` pipelines remain valid.
- Successful, command-failure, and parse/validation exits are respectively
  `0`, `1`, and `2`. JSON errors contain `ok: false`, `error`, and `warnings`
  unless text was explicitly selected.

Compact v2 is a projection, not a new engine result: it removes repeated or
empty data while retaining command identity and continuation/safety metadata.
Changing a compact field, full/v1 field, symbol handoff, alias, exit code, or
default format is a compatibility change and requires synchronized adapter,
model/presentation, documentation, skill, and test updates.

## MCP contract and intentional surface differences

The MCP adapter provides the same analysis and mutation capabilities as the CLI
where listed below. CLI/MCP compatibility means equivalent core semantics and
safety—not identical names, arguments, envelopes, or discovery mechanics.

| Core capability | CLI surface | MCP operation | Intentional MCP difference |
|---|---|---|---|
| Repository map | `explore` / `map` | `explore_repo` | MCP supports progress reporting and is invoked through search-first discovery. |
| Symbol search | `find` | `find_symbol` | MCP returns tool-native symbol values rather than the CLI process envelope. |
| Interface outline | `interface` | `read_interface` | MCP returns tool content without CLI format/exit-code controls. |
| Likely references | `impact` | `what_breaks` | MCP requires an absolute `path` or `abs_path`; the CLI accepts contained relative symbol paths and offers several symbol input forms. |
| Structural search | `search` | `search_pattern` | MCP exposes tool metadata/annotations and tool-native paging arguments. |
| Structural rewrite | `rewrite` | `rewrite_pattern` | MCP marks the operation destructive; there is no CLI approval protocol in the server. |
| Rule scan | `scan` | `scan_rules` | The MCP tool bears destructive annotations because `fix=true` can mutate; YAML is an ast-grep rule input format, not XRAY output. |
| File dependency outline | `imports` | `file_imports` | MCP returns tool content rather than CLI envelopes. |
| File public-API outline | `exports` | `file_exports` | MCP returns tool content rather than CLI envelopes. |

MCP clients initially see FastMCP's `search_tools` and `call_tool`, then locate
and invoke underlying XRAY operations by name. MCP additionally owns
`xray://workflow`, `xray_discovery_plan`, the packaged skill resource/template,
read-only versus destructive annotations, contexts, and progress events. These
have no required one-to-one CLI commands. Conversely, CLI aliases, JSON/text
formatting, pretty printing, symbol files/stdin, and process exit codes are
CLI-only concerns.

Both adapters must preserve the same repository containment, symbol semantics,
structural mutation scope, compact projection meaning, default result bounds,
and continuation identity. A capability added to only one adapter must be
documented as intentional; otherwise an engine capability change updates both
adapters and their tests.

## Bounds, containment, and cursors

Every caller supplies an explicit repository root. File and symbol paths used
by interface, impact, import/export, rule, and structural operations resolve
inside that root. Parent traversal, absolute outside-root paths, and symlink
escapes are rejected. The rule configuration for `scan` is also contained.

- Repository maps default to at most 5,000 entries and expose `truncated` plus
  a warning when the bound is reached.
- Structural and outline reads return at most 50 items by default. Compact
  pages expose `returned`, `total`, `truncated`, and `next_cursor` when another
  read-only page exists.
- Cursors are opaque offsets bound by a fingerprint to command, normalized
  root, and query identity. Reusing one for a different operation or query is
  invalid.
- Symbol JSON input is bounded to 1 MiB. Subprocess time and captured output,
  skeleton file size, in-memory symbol cache, MCP root cache, and cache disk
  usage are bounded in their owning components.
- A reporting `limit` never limits mutation: rewrite and `scan --fix` apply all
  matches. Mutating responses therefore do not advertise continuation.

## Analysis and mutation semantics

`find` uses fuzzy scoring over ast-grep-derived symbols. `interface` extracts
declaration skeletons without promising implementation bodies. `impact` and
`what_breaks` search for references to a symbol name, filter definitions and
unsupported/duplicate matches, and may fall back to bounded text search. They
are not type-aware caller, dependency, or build graphs; same-name references,
comments, and strings can require human review.

Read-only operations are `explore`/`map`, `find`, `interface`, `impact`,
`search`, `scan` without `--fix`, `imports`, and `exports`. Product mutation is
limited to two explicit paths:

1. `rewrite` / `rewrite_pattern` invokes ast-grep replacement across every
   match. Callers should specify `lang`; inference can include pattern-like
   configuration or documentation text.
2. `scan --fix` / `scan_rules(fix=true)` applies every fix declared by the
   contained ast-grep rule configuration.

Neither path supplies transactions, backups, automatic commits, or approval.
The caller owns a clean/recoverable worktree, diff inspection, and affected
tests. Engine and adapter changes must not weaken those warnings, destructive
MCP annotations, root containment, full-mutation semantics, or summary accuracy.

## Runtime state and resources

The indexer reads repository files and invokes Git, ripgrep/Python fallbacks,
and ast-grep on demand. It may write an optimization cache at:

```text
/tmp/.xray_cache/{root_hash}-{git_commit}/symbols.json
```

The repository-root hash prevents repositories at the same commit from sharing
cache entries. Cache JSON is written atomically; entries are age/size bounded
and expendable. Cache loss changes performance, not product truth. This optional
temporary cache is the only supported persistent runtime artifact.

The MCP process holds a bounded LRU of indexers keyed by normalized root path,
per-root reentrant locks, active-operation counts, and a global cache lock.
Same-root operations serialize around shared indexer state; independent roots
may proceed concurrently. The `XRAY_MCP_INDEXER_CACHE_LIMIT` environment value
controls the positive cache bound, default 32. ast-grep time/output bounds use
`XRAY_AST_GREP_TIMEOUT_SECONDS` and `XRAY_AST_GREP_OUTPUT_LIMIT_CHARS`.
These resources are process-local and do not form a service or database.

`src/xray/lsp_config.json` is inactive legacy data. No current Python module,
entry point, installer, CLI command, or MCP tool reads it. XRAY does not start,
install, configure, or communicate with language servers. Activating it would
be a new product architecture requiring an explicit design and compatibility
decision; its present contents grant no dependency or capability.

## Distribution and package compatibility

`pyproject.toml` is authoritative for Python `>=3.10`, FastMCP `<4`, ast-grep,
Pydantic, and fuzzy-search dependencies. Setuptools discovers packages below
`src`; the `xray` package includes `skills/**/*` as package data. Distribution
must retain both console scripts and the packaged progressive-discovery skill.
The repository-level `skills/xray-cli` directory is deliberately not package
data and serves shell-agent installations separately.

`install.sh` and `uninstall.sh` are explicit high-impact conveniences. They may
change `$HOME/.xray`, uv tool state, shell PATH configuration, and—in install
flows—network/Git state. They do not define a second product API. The
configuration generator emits client JSON to stdout and never installs XRAY or
writes client configuration. Changes to an entry point, package-data path,
install location, generated command, or supported client/method require aligned
packaging tests, README instructions, and smoke checks.

## Verification and evidence boundaries

`tests/test_cli.py`, `tests/test_structural_commands.py`, and
`tests/test_models.py` own CLI, schema, containment, cursor, and mutation
contract evidence. `tests/test_mcp_compact.py` owns search-first MCP behavior,
compact transforms, resources, annotations, progress, caches, and concurrency.
`tests/test_ast_grep.py` owns subprocess normalization and failures.
`tests/test_packaging.py` owns metadata, dependency bounds, console scripts,
package data, installers, and generated configurations. `test_samples/` supplies
Python, JavaScript, TypeScript, and Go fixtures; it is not shipped product data.

`.reports/` may support a decision only at the artifact named in the report.
It cannot override current tests, source, this architecture, or public contract
documentation. Harness validators and Make targets compose product gates; they
do not replace the focused owner tests above.

## Synchronized change edges

The following changes are one logical update even when their paths are assigned
to separate implementation leaves:

- CLI command, option, envelope, exit, or default-format change: CLI adapter,
  models/presentation as applicable, README, repository CLI skill, CLI tests,
  and any affected MCP mapping.
- MCP tool, discovery, annotation, resource, prompt, or concurrency change: MCP
  adapter, packaged MCP skill, README, MCP tests, and configuration/smoke docs.
- Core result or semantic change: indexer/ast-grep wrapper, both adapters,
  models/presentation, compatibility documentation, and both adapter test sets.
- Compact/full field or cursor change: presentation, CLI and MCP projections,
  both skills, README, v1/v2 compatibility tests, and consumers named by those
  contracts.
- Containment, bound, cache, or mutation change: owning core code, adapter
  validation and warnings, destructive annotations, tests, and rollback/risk
  documentation.
- Dependency, Python floor, version, entry point, or package-data change:
  `pyproject.toml`, `src/xray/__init__.py` when versioned, installers,
  configuration output, package tests, README, and smoke gates.
- Harness authority, role, hook, or gate change: its `.codex`/`.agents`/docs or
  Make authority, validators, transformation evidence, and frozen adoption
  packet when the product boundary or a material architecture decision moves.

No change to a descriptive example, report, generated client snippet, or skill
alone changes product behavior. Product source and its owner tests remain the
implementation authority under the compatibility decisions in this document.
