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

## XRAY 0.11.0 current contract

XRAY 0.11.0 preserves Python 3.10+, default compact `xray.cli.v3`, explicit
legacy v2 and full/v1 output, JSON and `jq` pipelines, stdio MCP, repository
containment, snapshot-bound cursors, and direct legacy mutation. V3 standardizes
success and paging fields; `--schema v2` exposes the previous projection only
for diagnosis and is not a compatibility commitment.

V3 interface output uses only `returned`, `total`, `total_exact`, `truncated`,
and `next_cursor` for paging. `completeness` contains a Boolean and typed reasons
such as `member_truncated` and `page_truncated`. CLI symbol JSON/file input and
MCP `exact_symbol` select only the found symbol's owner/member path. V3 compact
impact retains page `total` and moves raw/filter/execution evidence under
`diagnostics`; impact remains name-based rather than a semantic dependency graph.

Repository focus depth is relative to each focus while entry `depth` remains
root-relative. Default focus retains root context and ancestors; CLI
`--strict-focus` and MCP `include_root_context=false` remove unrelated root
context. Inventory visibility follows explicit Python underscore, Go
capitalization, and JavaScript/TypeScript private/export conventions before
public/private/unknown filtering.

MCP discovery ranks natural intent over aliases, descriptions, tags, parameters,
workflow stages, and mutation classes. Search returns exact paged totals and
summary metadata by default; full detail supplies input schemas. Regex mode is
explicit. Ordinary change intent ranks guarded `plan_replacement` and omits the
direct legacy `rewrite_pattern`, which remains callable by exact name.

Replacement plans contain a flat `edit_manifest`, per-file preimage/postimage
syntax evidence, and top-level syntax validation. Planning rejects newly
introduced parse diagnostics and dirty affected files unless their exceptional
acknowledgements are recorded before digest calculation. `replace verify` and
MCP `verify_replacement` recompute digest, selection, source, syntax, dirtiness,
and applicability without writes. Apply repeats these checks for staged and
final postimages, preserves modes, and rolls back partial ordinary failures.
Process termination can interrupt rollback; callers keep a recoverable worktree
and inspect the resulting diff.

Capabilities separate CLI and MCP operation names, defaults, maxima, schemas,
resources, prompts, caches, and mutation classes. Optional disk cache files are
`symbols.json` and `inventory.json`; the MCP indexer LRU remains process-local.
YAML remains only ast-grep rule/test input and is never XRAY product output.

## Historical frozen xray-s3b design

This section preserves the implemented XRAY 0.10.0 contract as transformation
evidence. XRAY 0.11.0 above supersedes it for current behavior.

### Compatibility

XRAY 0.10.0 retains Python 3.10+, JSON-first output, `jq` symbol handoffs,
`xray.cli.v2` compact envelopes, explicit full/v1 output, the `map` alias, exit
classes, stdio MCP, search-first MCP exposure, packaged resources and skills,
repository containment, snapshot-bound cursors, staged rollback, legacy
`rewrite`, and CLI `scan --fix`.

The migration changes these compact agent surfaces:

- `find` defaults to compact v2 with calibrated filtering and retains its v1
  envelope through `--detail full`;
- `explore` defaults to depth two and requires `--all-depths` for an unbounded
  depth request;
- MCP `scan_rules` becomes read-only; guarded rule application moves to
  `apply_rule_fixes`; and
- replacement application rejects `xray.replace.v1` plans with an instruction
  to re-plan because v1 cannot attest its review fields.

YAML remains ast-grep rule and test input. XRAY does not add YAML output, a
language server, type-aware dependency analysis, automatic commits, or durable
product plan storage.

### Replacement review contract

`xray.replace.v2` binds the complete review artifact. `plan_digest` is SHA-256
over canonical JSON for every plan field except `plan_digest` itself. The
covered values include query and scope identity, bounds, file hashes, edit
manifest, selection, preview, deterministic unified diff, truncation metadata,
warnings, applicability, review completeness, and explicit acknowledgements.

Each candidate has an `edit_id` derived from its contained relative path,
preimage hash, byte range, before hash, and after hash. The plan contains a
compact manifest for every edit. Preview and unified diff content remain
bounded. If either is truncated, `review_complete` and `applicable` are false
unless `allow_truncated_review` was explicitly requested and recorded before
the digest was calculated.

Zero-candidate plans are not applicable. All-no-op plans require recorded
`allow_noop`. A plan reports the exact reason when it is not applicable.

`replace refine` accepts a complete v2 plan and repeated edit IDs. It recomputes
the original candidate set, validates every ID, and emits a new v2 plan whose
query records the selection. It does not write files. Apply recomputes the plan
with the bound query, bounds, selection, and review limits, compares the entire
canonical artifact and digest, validates source state, then uses the established
staged writer. CLI and MCP application remain stateless and require the full
plan plus an independently supplied digest.

### Symbol discovery and bounded source reads

Compact CLI `find` and MCP `find_symbol` default to `min_score: 60` and a
ten-result page. They always include scores and accept repeated contained path,
language, symbol-type, and visibility filters. Results expose `returned`,
`total`, `total_exact`, `truncated`, and `next_cursor`. The cursor binds every
filter and the supported-source snapshot. Descriptions promise name and
qualified-identity matching, not semantic or behavior search. Explicit
`--min-score 0` and CLI `--detail full` preserve low-confidence and v1 access.

Compact interface reads accept symbol-name, visibility, type, member-depth,
member-count, page-limit, and cursor controls. Defaults bound top-level symbols
and members. Truncation sets `complete: false` and adds an exact warning. Full/v1
keeps the established unbounded legacy string projection.

CLI `read-symbol` and MCP `read_symbol` accept a full contained symbol plus
context, line, and byte bounds. They return the exact source slice with path,
one-based range, returned line and byte counts, and truncation metadata. CLI
`symbol-at` and MCP `symbol_at` accept a contained path and one-based line and
return the narrowest enclosing inventory symbol. They return an explicit empty
result when no supported symbol contains the line.

### Impact continuation

Impact execution collects enough post-filter references to satisfy the
requested filtered offset and page plus one, or until upstream completion. It
may grow the raw ast-grep cap only to a named safety bound. Early definitions,
duplicates, unsupported paths, and inexact matches cannot suppress a cursor for
later valid references.

When the raw safety bound prevents exactness, the response reports
`execution_limited: true`, retains `total_exact: false`, and emits a warning. It
does not claim that omitted results are available through a cursor it cannot
honor.

### Repository mapping

Compact CLI and MCP maps default to `max_depth: 2`. CLI `--all-depths` and MCP
`all_depths: true` explicitly select unlimited depth. CLI `--limit` aliases
`--max-entries` without changing the compact field name.

Each focus value is a contained repository-relative file or directory path.
Nested focus retains the root entry, root-level context files, and the ancestor
directory chain, then traverses only selected descendant subtrees. Parent
traversal, absolute outside-root paths, and symlink escapes fail before
traversal. Full/v1 output uses the same selection semantics.

### Errors and MCP annotations

Compact CLI failures use `xray.cli.v2`, `ok: false`, the exact leaf command,
`error: {code, message, details?}`, and warnings. Explicit full/v1 output keeps
the legacy string error contract where compatibility requires it.

MCP tools return FastMCP error results with `isError: true`, JSON text content,
and the same structured error object. Adapter boundaries translate typed domain
failures to stable codes and unexpected failures to `internal_error`; neither
surface emits tracebacks.

MCP `scan_rules` accepts no mutation argument and has read-only annotations.
`apply_rule_fixes` has destructive annotations and accepts only a reviewed v2
rule plan plus its expected digest. CLI `scan --fix` remains an explicitly
legacy all-match mutation.

### Capabilities and rule tooling

CLI `capabilities [ROOT]`, its `doctor` alias, and MCP `xray_capabilities`
report product version, supported schemas and plan versions, operations with
mutation classes, language-extension support, effective bounds and timeouts,
cache behavior, required ast-grep availability and version, optional Git and
ripgrep availability, and workflow resource identifiers. Repository-dependent
checks are omitted when no root is supplied. Missing required dependencies make
doctor unhealthy without making capabilities undiscoverable.

MCP searchable descriptions include the natural intents `lookup`, `blast
radius`, `callers`, `rename`, `safe code replacement`, `help`, and `workflow`.
Regex discovery remains bounded and initially exposes only `search_tools` and
`call_tool`.

CLI `rules check`, `rules explain`, and `rules test`, plus corresponding MCP
tools, are read-only:

- check runs contained ast-grep scan diagnostics without fixes;
- explain returns bounded contained rule source, validation evidence, and
  upstream `--inspect=summary` output without parsing or reimplementing YAML;
  and
- test runs contained project tests with `ast-grep test`,
  `--skip-snapshot-tests`, disabled color, and bounded output.

Rule tooling never starts interactive sessions, updates snapshots, or applies
fixes.

### Verification matrix

Focused evidence covers:

- field-by-field plan tampering, v1 rejection, truncated-review
  acknowledgement, deterministic diffs, stable edit selection, zero/no-op
  plans, drift, staged writes, and rollback;
- scoped, calibrated, paged, empty, and nonsense symbol queries;
- protocol `isError`, typed CLI errors, leaf commands, natural-intent search,
  tool annotations, resources, prompts, and skills;
- bounded interfaces, symbol source reads, line lookup, containment, and
  truncation;
- filtered-prefix impact continuation and raw-cap exhaustion;
- nested focus, shallow defaults, explicit all-depth maps, and the limit alias;
- healthy and degraded capabilities plus contained rule check, explain, and
  test behavior; and
- compact/full compatibility, package data, installed guidance, every
  canonical gate, and live CLI/MCP smoke against one unchanged artifact.

## Historical xray-cs4 product contract

This section preserves the XRAY 0.9.1 baseline introduced by `xray-cs4` as
transformation evidence. It is superseded by the XRAY 0.10.0 contract above
and does not define current behavior. Later component, compatibility, and
verification descriptions in this historical section describe that baseline.

### Safe replacement

The CLI adds `xray replace plan` and `xray replace apply`. MCP adds the
read-only `plan_replacement` tool and destructive `apply_replacement` tool.
Pattern replacement and rule fixes use one planning and application engine.
The existing `rewrite` / `rewrite_pattern` surface remains an explicitly
destructive legacy compatibility path; it uses the shared staged writer but
does not require plan confirmation.

`replace plan` accepts exactly one change source:

- `--pattern` plus `--replacement`, with `--lang` when known; or
- `--rule`, resolved inside the root, for fixes supplied by one ast-grep rule
  or contained configuration.

Both sources accept repeated contained `--path` scopes and repeated ast-grep
`--glob` filters. Defaults cap candidates at 1,000 and changed files at 100.
Callers may lower either bound. Raising a bound is explicit. A bound failure
does not write files or return a partial applicable plan.

The compact JSON plan uses `schema_version: "xray.cli.v2"` and
`plan_version: "xray.replace.v1"`. It contains:

- normalized root and query identity, scopes, language, and safety bounds;
- exact candidate, changed-candidate, no-op, and affected-file counts;
- every affected relative path with its preimage SHA-256, proposed postimage
  SHA-256, edit count, changed edit count, and byte size;
- a root fingerprint bound to the normalized root identity, Git commit when
  available, query, and affected-file manifest;
- a plan digest over the canonical plan fields;
- a bounded compact preview with before and after text, one-based location,
  captures, and truncation metadata; and
- warnings for inferred language, no-op candidates, dirty Git state, or other
  review conditions.

Planning is JSON-only. The complete applicable plan contains the bounded compact
preview and no persisted product state; callers may redirect its CLI envelope
to a file or pass the MCP plan object directly.

`replace apply` requires the complete plan and an independently supplied
expected plan digest. It validates the schema, canonical digest, root,
language and scope identity, safety bounds, affected paths, preimage hashes,
root fingerprint, and recomputed candidate set. Any drift rejects the whole
operation before a write. An all-no-op plan is rejected unless the plan records
explicit no-op allowance.

Application builds every postimage before mutation, validates non-overlapping
contained byte ranges and output bounds, writes same-directory temporary files,
preserves file mode, flushes file data, and replaces targets only after all
stages succeed. It retains original bytes until every replacement succeeds.
A replacement failure restores every already-replaced file and reports rollback
status. Successful output reports candidate, applied, changed, no-op, file,
and rollback counts plus verified preimage and postimage hashes. `files_modified`
means files whose bytes changed; matched or no-op files use separate fields.

Legacy `rewrite` and `scan --fix` preserve their all-match behavior and warning
contract. They use the same candidate construction and staged writer, return
truthful changed/no-op counts, and never imply that `--limit` constrains edits.

### Symbol inventory and scoring

One ast-grep expanded outline builds a structured repository symbol inventory
per source snapshot. Inventory entries preserve name, type, language, relative
path, one-based range, owner, qualified name, signature, role, visibility, and
documentation when available. The cache key includes the normalized root and a
supported-source manifest so dirty worktree changes invalidate cached data.
Disk and in-process entry limits remain bounded.

Unqualified queries score symbol names only. Qualified queries may score owner
and qualified-name context; path-like queries may score relative paths. Ranking
orders exact qualified name, exact name, normalized name, prefix, token, then
fuzzy similarity. Partial substring similarity cannot give every member its
owner's exact score. Results add `qualified_name`, `owner`, `language`,
`match_reason`, and `confidence` while preserving existing symbol fields.
Confidence is `high` for exact or normalized identity, `medium` for prefix or
token matches, and `low` for fuzzy results. A minimum score filters the final
calibrated score, and unrelated long queries must not pass the documented
agent threshold of 60.

### Structured interfaces

Compact `interface` JSON uses `xray.cli.v2` and returns a structured file
contract: relative path, language, ordered top-level symbols, nested direct
members, signatures, one-based ranges, visibility, role, documentation, and a
`complete` flag with warnings. Python signatures and docstrings are recovered
from the standard-library AST when upstream outline signatures are incomplete.
Other languages preserve upstream hierarchy and expose detected incompleteness
instead of returning malformed text as success.

Unsupported files, missing files, containment failures, parse failures, and
upstream failures use typed error envelopes and nonzero CLI exits. They are not
encoded as successful interface strings. `--detail full` preserves the v1 JSON
string envelope. `--format text` renders the structured hierarchy with
indentation and documentation without implementation bodies. MCP keeps the
legacy string `read_interface` tool and adds read-only
`read_interface_structured`; this preserves existing clients while making the
structured contract discoverable.

### Bounded classified impact

Compact `impact` JSON uses `xray.cli.v2`, relative paths, compact references,
and shared paging metadata. Each result classifies `definition`, `call`,
`import`, `read`, or `text` and reports `high`, `medium`, or `low` confidence.
Other same-name definitions are not described as dependents. The response
retains the explicit name-based limitation and reports structural or text
strategy plus any degradation reason.

CLI and MCP accept `limit` and a snapshot-bound cursor. Repository-wide upstream
work stops after `offset + limit + 1` candidates. `total` is exact only when
the upstream result terminates below the cap; `total_exact: false` makes a
reported total a lower bound. Compact context defaults to the matched line;
full/v1 mode preserves legacy absolute paths and context behavior.

### Ignore, scopes, and execution bounds

Repository traversal uses Git-compatible wildmatch semantics for nested rules,
anchoring, directory patterns, and negation. Built-in generated-state
exclusions are a separate named policy. Compact maps report that policy in
`options`; callers may disable it explicitly without disabling repository
ignore rules. Tests cover Git and non-Git roots.

Repository-wide search and read-only scan pass an upstream execution cap based
on the requested page. Cursors bind command, normalized root, query, scopes,
and a source snapshot fingerprint. A changed snapshot rejects continuation.
File outline operations remain file-scoped and enforce input and result-size
bounds. CLI and MCP share cursor, paging, compact-projection, exactness, and
scope-validation primitives from `presentation.py`; adapter-local duplicates
are removed.

### Compatibility and verification

JSON remains the default. YAML remains ast-grep rule input only. Compact v3 is
the product default; explicit v2 and full/v1 modes remain diagnostic
projections. Existing entry points, `map`, symbol handoffs, process exit classes, containment, installed
skills, MCP search-first discovery, prompts, resources, package data, and
Python 3.10+ remain supported.

Focused evidence must cover preview non-mutation, digest and source drift,
candidate/file caps, no-op truthfulness, staged-write rollback, rule plans,
legacy summaries, scoring pollution, nonsense queries, inventory invalidation,
interface hierarchy/documentation/incompleteness/errors, impact bounds and
classification, ignore anchoring/negation, scoped search, snapshot cursor
rejection, and honest lower-bound totals. Final evidence includes every
canonical static, test, packaging, build, smoke, and cleanliness gate against
one unchanged artifact.

XRAY is on-demand tooling, not a daemon-backed indexing service. It has no
supported product database. The tracked `.xray/xray.db`, `.xray/xray.db-shm`,
and `.xray/xray.db-wal` files are obsolete generated state scheduled for
removal by the adoption; they are not architecture or supported storage.

## Component and ownership map

| Component | Owned paths | Responsibility and interfaces | May depend on |
|---|---|---|---|
| CLI adapter | `src/xray/cli.py`, `xray` entry point | Parses `explore`/`map`, `find`, `interface`, `impact`, guarded `replace plan`/`replace apply`, `search`, legacy `rewrite`, `scan`, `imports`, `exports`, and explicit `skill install`; validates bounded input; emits stable JSON or lossy text and process exit codes. | Public models, presentation, indexer, skill installer |
| MCP adapter | `src/xray/mcp_server.py`, `xray-mcp` entry point | Runs `FastMCP("XRAY Code Intelligence")` over explicit stdio; presents search-first tools, workflow resource/prompt, packaged skill resources, progress, tool annotations, and concurrency-safe indexer access. | Public models, presentation, indexer, FastMCP |
| Public models | `src/xray/models.py` | Pydantic validation and serialization for symbol, explore, find, interface, impact, and error values. Models allow compatible extra fields and normalize validation errors. | Pydantic and value types only |
| Presentation contract | `src/xray/presentation.py` and adapter-specific envelope code in `src/xray/cli.py` | Projects full engine data into compact relative-path records, owns pagination metadata and opaque snapshot-bound cursors, and keeps compact output sparse. | Public/core value shapes; no I/O analysis |
| Indexing engine | `src/xray/core/indexer.py` | Resolves and contains repository paths; compiles ignore policy; fingerprints source snapshots; maps trees; inventories/finds symbols; reads interfaces; estimates bounded classified name impact; plans/stages/applies replacements; owns optional cache lifecycle. | ast-grep wrapper, filesystem, pathspec, bounded Git/rg/Python fallbacks |
| ast-grep boundary | `src/xray/core/ast_grep.py` | Executes the external `ast-grep` program with time and output bounds; normalizes no-match and JSON behavior; raises typed failures. | `ast-grep` executable and subprocess APIs only |
| MCP configuration generator | `mcp-config-generator.py` | Prints JSON client configuration for Cursor, Claude, and VS Code using supported source, local-Python, Docker, or installed-script forms. It does not edit client files. | Static configuration data, JSON, current path |
| Package and entry points | `pyproject.toml`, `src/xray/__init__.py` | Defines Python `>=3.10`, dependencies, version, `xray = xray.cli:main`, `xray-mcp = xray.mcp_server:main`, package discovery, and package data. | Setuptools metadata |
| Agent skill installer | `src/xray/skill_installer.py`, `src/xray/agent_skills/xray-cli/` | Installs the bundled CLI skill under the current user's or one project's `.agents/skills/xray-cli`; identical targets are no-ops, divergent targets require `--force`, symlinked paths fail, and staged replacement rolls back on failure. | Standard-library resources and filesystem APIs |
| Install lifecycle | `install.sh`, `uninstall.sh` | Installs or removes the `xray` uv tool and its checkout under the explicit script contract; verifies both console scripts. These are sensitive filesystem, network, PATH, Git, and tool-state mutation boundaries. | uv, shell, Git/network when cloning |
| Repository CLI skill | `skills/xray-cli/SKILL.md`, `skills/xray-cli/agents/openai.yaml` | Teaches shell-capable agents the stable handwritten CLI, compact JSON, jq/symbol handoffs, containment, paging, and mutation safety. A byte-identical copy under `src/xray/agent_skills/xray-cli/` is package data for explicit installation. | Public CLI contract |
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

- Compact `explore`, `interface`, `impact`, replacement, `search`, `scan`, `rewrite`, `imports`, and `exports`
  responses use `schema_version: "xray.cli.v3"` envelopes by default.
- Compact-capable CLI commands accept `--schema v2` for the previous projection;
  v3 consistently includes success state and standardizes paging, interface
  completeness, and compact impact diagnostics. Cursor identity distinguishes
  projections when their shapes differ.
- `--detail full` preserves verbose v1-compatible data for commands that offer
  detail selection. `find` and legacy full interface/impact remain `xray.cli.v1`.
- `map` is an alias for `explore`; JSON records `command: "explore"` and
  `invoked_as: "map"`.
- JSON is one line unless `--pretty` is requested. Full symbol objects retain
  `name`, `path`, `abs_path`, one-based `start_line`/`end_line`, `type`, and
  `score`, qualified identity, match reason, and confidence, so `jq` and
  `--symbol-json`/`--symbol-file -` pipelines remain valid.
- Successful, command-failure, and parse/validation exits are respectively
  `0`, `1`, and `2`. JSON errors contain `ok: false`, `error`, and `warnings`
  unless text was explicitly selected.

Compact output is a projection, not a new engine result: it removes repeated or
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
| Interface outline | `interface` | `read_interface`, `read_interface_structured` | MCP preserves legacy text and adds a typed hierarchical tool; its structured projection defaults to v3. |
| Likely references | `impact` | `what_breaks` | MCP defaults to compact v3 and requires an absolute `path` or `abs_path`; the CLI accepts contained relative symbol paths and offers several symbol input forms. |
| Structural search | `search` | `search_pattern` | MCP exposes tool metadata/annotations and tool-native paging arguments. |
| Structural rewrite | `rewrite` | `rewrite_pattern` | MCP marks the operation destructive; there is no CLI approval protocol in the server. |
| Guarded replacement | `replace plan` / `replace verify` / `replace apply` | `plan_replacement`, `verify_replacement`, `apply_replacement` | MCP passes the full plan object directly; plan and verify are read-only, while apply is destructive. |
| Rule scan | `scan` | `scan_rules`, `apply_rule_fixes` | MCP scan is read-only; guarded rule mutation uses a reviewed plan. YAML is ast-grep input, not XRAY output. |
| File dependency outline | `imports` | `file_imports` | MCP returns tool content rather than CLI envelopes. |
| File public-API outline | `exports` | `file_exports` | MCP returns tool content rather than CLI envelopes. |
| Agent skill installation | `skill install` | None | Local `.agents/skills` management is CLI-only and is not repository analysis. |

MCP clients initially see FastMCP's `search_tools` and `call_tool`, then locate
and invoke underlying XRAY operations by name. Search ranks natural intent by
default, supports explicit regex mode, and exposes exact paged inventory. MCP additionally owns
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
- Structural, impact, and outline reads return at most 50 items by default. Compact
  pages expose `returned`, `total`, `total_exact`, `truncated`, and `next_cursor` when another
  read-only page exists.
- Cursors are opaque offsets bound by a fingerprint to command, normalized
  root, query/scopes, and source content. Reusing one for a different operation,
  query, or changed snapshot is invalid.
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
`search`, `replace plan`, `scan` without `--fix`, `imports`, and `exports`.
Product mutation is limited to three explicit paths:

1. `replace apply` / `apply_replacement` validates a reviewed plan and source
   snapshot, stages all postimages, preserves modes, verifies results, and rolls
   back already replaced files after a later failure.
2. `rewrite` / `rewrite_pattern` invokes the shared staged replacement engine across every
   match. Callers should specify `lang`; inference can include pattern-like
   configuration or documentation text.
3. CLI `scan --fix` applies every fix declared by the contained ast-grep rule
   configuration. MCP instead uses a reviewed rule plan with `apply_rule_fixes`.

No mutation path supplies automatic commits or external approval. Guarded
replacement supplies staged rollback but not a durable backup after success.
The caller owns a clean/recoverable worktree, diff inspection, and affected tests.
Engine and adapter changes must not weaken those warnings, destructive
MCP annotations, root containment, full-mutation semantics, or summary accuracy.

## Runtime state and resources

The indexer reads repository files and invokes Git, ripgrep/Python fallbacks,
and ast-grep on demand. It may write an optimization cache at:

```text
/tmp/.xray_cache/{root_hash}-{git_commit}/symbols.json
/tmp/.xray_cache/{root_hash}-{git_commit}/inventory.json
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

`pyproject.toml` is authoritative for Python `>=3.10`, FastMCP `>=3.4.7,<4`, ast-grep,
Pydantic, fuzzy-search, and Git-wildmatch (`pathspec`) dependencies. Setuptools discovers packages below
`src`; the `xray` package includes `skills/**/*` and `agent_skills/**/*` as
package data. Distribution must retain both console scripts, the packaged
progressive-discovery skill, and a byte-identical distributable copy of the
repository-level `skills/xray-cli` skill.

`uv tool install` owns package installation and does not forward XRAY-defined
flags or invoke a package post-install hook. `xray skill install --user` is the
explicit user-wide step; `xray skill install --project ROOT` uses
`ROOT/.agents/skills/xray-cli`. Existing divergent content requires `--force`;
the installer rejects symlinked target components and stages replacements in
the target parent so a failed swap can restore the prior directory.

`install.sh` and `uninstall.sh` are explicit high-impact conveniences. They may
change `$HOME/.xray`, uv tool state, shell PATH configuration, and—in install
flows—network/Git state. They do not define a second product API. The
configuration generator emits client JSON to stdout and never installs XRAY or
writes client configuration. Changes to an entry point, package-data path,
install location, generated command, or supported client/method require aligned
packaging tests, README instructions, and smoke checks.

The `xray-mcp` entry point calls FastMCP with `transport="stdio"`; environment
configuration cannot silently turn the documented subprocess command into an
HTTP server. XRAY does not configure FastMCP HTTP hosting or OAuth. FastMCP
security and reliability fixes remain inherited dependency behavior without
creating an XRAY HTTP deployment contract.

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
