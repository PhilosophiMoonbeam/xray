# XRAY 0.10.0 Agent Usability Audit

Date: 2026-08-14

Artifact: `8e4cb8ff474c521e8316621e406da4167e57e359` on `main`

Tracker: `xray-l67`

## Conclusion

XRAY has a strong agent-oriented foundation. Compact JSON, contained paths,
bounded reads, snapshot-bound cursors, exact symbol handoffs, typed failures,
truthful MCP annotations, and guarded replacement are materially better than
asking an agent to orchestrate raw ast-grep output.

The current release still has four agent-visible defects that should be fixed
before expanding the surface:

1. replacement plans can approve syntactically invalid postimages;
2. MCP tool discovery misses ordinary intent phrases and ranks the legacy
   destructive rewrite before guarded planning for `replace`;
3. nested map focus can return none of the focused contents at the default
   depth; and
4. Python `find` visibility metadata and filtering are incorrect.

The guarded replacement engine should remain the mutation foundation. Its next
version should add syntax evidence, an explicit flat edit-selection contract,
a non-mutating verification step, safer discovery ordering, and clearer
recovery limits. Legacy all-match mutation should remain compatible but should
not be the easiest agent-discovered path.

## Scope and method

This audit used the repository and installed `xray` 0.10.0 executable as an LLM
agent would use them. The repository and installed CLI skill copies have the
same SHA-256:

```text
c58dff2c4554793885d30437508cf45f8a7666085833832e8b932be7df20348c
```

Evidence included:

- every CLI help surface, including nested `replace`, `rules`, and `skill`
  commands;
- live map, find, interface, exact-source, line-to-symbol, impact, structural
  search, import/export, capabilities, error, paging, replacement-plan, and
  replacement-refinement calls;
- live FastMCP list/search/call, resource, resource-template, prompt, packaged
  skill, schema, and annotation inspection;
- `README.md`, `ARCHITECTURE.md`, both agent skills, CLI/MCP adapters, core
  implementation, presentation code, the complete test inventory, and relevant
  test implementations; and
- collection of the current 201-test suite.

No product mutation, installer action, commit, push, release, deployment, or
remote tracker operation was performed. Replacement probes stopped at planning
or refinement.

The unchanged product artifact and the added report passed:

```text
uv run pytest                       201 passed in 3.63s
uv run ruff format --check .        21 files already formatted
uv run ruff check .                 All checks passed
uv run pyright                      0 errors, 0 warnings, 0 informations
uv run vulture                      exit 0, no findings
uv build                            sdist and wheel built successfully
uv run xray --version               xray 0.10.0
uv run xray explore . --max-depth 1 live compact smoke passed
```

## What already works well

- `find -> read-symbol -> impact` is a practical progressive sequence. An exact
  qualified lookup found `XRayIndexer.plan_replacement`, returned a bounded
  31-line source slice, and produced classified paged references without raw
  ast-grep range trees.
- Compact structural search and import/export results carry relative paths,
  useful captures, exactness, truncation, and bound cursors.
- Containment failures are typed and actionable. Outside-root interface and
  search probes failed before reads with stable JSON error codes.
- Exact symbol objects are reusable between CLI reads and impact, and MCP
  schemas clearly request the complete object.
- The MCP surface initially exposes only `search_tools` and `call_tool`; its
  underlying tool schemas have complete argument descriptions and truthful
  read-only/destructive annotations.
- `xray://workflow`, `xray_discovery_plan`, and the packaged MCP skill load
  correctly. The installed, repository, and package CLI skills are identical.
- Replacement v2 binds its query, bounds, files, hashes, nested edits, preview,
  diff, warnings, applicability, acknowledgements, and selection into the plan
  digest. Apply recomputes the plan, rejects drift, stages all postimages,
  preserves modes, verifies hashes, and attempts rollback after a partial
  replacement failure.
- Tests are especially strong around containment, cursor identity, compact/full
  compatibility, replacement tampering, source drift, bounds, no-op handling,
  rollback, MCP annotations, package data, and concurrency.

## Priority findings

### P0: applicable plans do not attest syntactic validity

Live probe:

```bash
uv run xray replace plan . \
  -p 'print($A)' -r 'if' -l python --path test_samples
```

The plan proposed replacing two calls with bare `if`, produced visibly invalid
Python in its unified diff, and reported:

```json
{"applicable":true,"review_complete":true,"warnings":[]}
```

The implementation validates byte ranges, UTF-8 boundaries, overlap, size,
hashes, and drift, but it does not parse prepared postimages. Current tests do
not cover invalid replacement syntax.

Recommendation:

- Compare parser diagnostics for every supported preimage and postimage during
  planning. Record language, parser, diagnostic counts, and new diagnostic
  locations in the digested plan.
- Make a plan inapplicable when it introduces a parse error. Existing parse
  errors may remain only when the postimage does not worsen them.
- If an escape hatch is required, name it explicitly, such as
  `--allow-new-parse-errors`, record it in the plan, and keep it absent from
  ordinary agent guidance.
- Recheck syntax after staging and after replacement. Hash verification alone
  proves byte identity, not valid code.

### P1: MCP discovery is literal, brittle, and unsafe in its ordering

Live `search_tools` calls returned no matches for:

```text
find usages
who calls
rename symbol
change function safely
replace expression
validate rule
```

Individual words such as `references`, `rename`, and `help` work because they
occur literally in tool metadata. The transform applies a regular expression;
it does not tokenize or rank intent. A broad `.` returns ten complete schemas,
with no total, truncation flag, or continuation, so later tools are invisible.

More importantly, searching `replace` returns `rewrite_pattern` first. That
tool is truthfully marked destructive, but it is the legacy all-match operation;
`plan_replacement` appears second.

Recommendation:

- Replace raw-regex-only discovery with ranked token/intent matching over name,
  description, aliases, tags, mutation class, and workflow stage. Support
  quoted regex as an explicit advanced mode if compatibility requires it.
- Match multiword input as tokens with synonym expansion (`usages`, `used by`,
  `calls`, `rename symbol`, `safe change`, `rule validation`).
- Rank read-only planning before destructive application. Return legacy
  all-match mutation only for explicit `legacy`, `unsafe`, `all-match`, or
  `destructive` intent.
- Add `returned`, `total`, `truncated`, and continuation or a summary-only
  inventory mode. A broad ten-tool result was 13,620 bytes in this audit.
- Add realistic composite-phrase and safe-ordering tests. Current tests mainly
  assert phrases copied verbatim into metadata.

### P1: nested focus conflicts with the default map depth

Live probe:

```bash
uv run xray explore . --focus src/xray/core \
  --include-symbols --max-depth 2
```

The result retained `.`, `src`, `src/xray`, and every root-level file, but it
returned neither `src/xray/core` nor any focused file. Raising the root-relative
depth to four returned the expected contents.

The help describes focus as a way to narrow and zoom in, but does not explain
that a focus at or below the current depth boundary can contain no descendants.
The nested-focus test calls the engine with its unbounded `None` default; it
does not exercise the CLI/MCP depth-two default.

Recommendation:

- Define depth relative to each focus for focused traversal while retaining the
  ancestor chain. Preserve root-relative depth explicitly for unfocused maps.
- If compatibility prevents that change in v2, reject or warn when the bound
  cannot include the focus or any focused descendant. Include an exact suggested
  `--max-depth` or `--all-depths` value.
- Replace the current “all root files are context” rule with a documented named
  context policy, or add a strict-focus option. The live focused result included
  installer files and symbols from `mcp-config-generator.py` before the desired
  subtree.
- Add deep file and directory focus tests through both CLI and MCP defaults.

### P1: Python find visibility is incorrect

Live probes reported `_build_replacement_plan` and `_init_cache` as public:

```bash
uv run xray find . _build_replacement_plan \
  --path src/xray/core/indexer.py --visibility private
# returned: 0

uv run xray find . _build_replacement_plan \
  --path src/xray/core/indexer.py --visibility public
# returned: 1, visibility: "public"
```

The structured interface correctly marks the same underscore members private.
Module-level Python functions can also appear as `unknown` in `find`. The
inventory trusts upstream `isPublic`, while the Python interface applies XRAY's
own underscore convention.

Recommendation:

- Normalize Python inventory visibility with the same `_python_visibility`
  rule used by interface extraction.
- Define and test language-specific visibility semantics rather than treating
  upstream absence as a uniform value.
- Add end-to-end public/private/unknown filter tests using real Python, JS/TS,
  and Go outlines. Existing filter tests do not catch this live inconsistency.

### P1: replacement selection is hard to automate correctly

Both skills say to review a “manifest `edit_id`,” but the plan has no
`manifest` field. IDs live at:

```text
plan.files[].edits[].edit_id
```

The refined selection is recorded at:

```text
plan.query.selected_edit_ids
```

`xray replace refine --help` gives `--edit-id` no description or repeatability
note. Following the conceptual wording literally caused this audit's first
refinement to pass `null`; the typed error was correct, but the handoff was not.

Recommendation:

- Add a flat, canonical `edit_manifest` with `edit_id`, path, line, before/after
  hashes, and change status while retaining nested file detail for v2
  compatibility.
- Document exact `jq` extraction and repeated `--edit-id` examples in help,
  README, both skills, workflow resource, and prompt.
- Add `replace inspect` or `replace verify` to recompute an unchanged plan,
  summarize selected IDs, report readiness, and perform every non-mutating
  apply guard without writing.
- Expose structured `next_actions` only in plan/refine output, where the extra
  bytes prevent likely misuse.

### P1: owned guidance and authority have drifted

Confirmed contradictions include:

- README limitations say XRAY has no direct line-to-symbol tool, while CLI
  `symbol-at`, MCP `symbol_at`, skills, source, and tests provide it.
- README says compact successes include `ok: true`; live `explore` and `impact`
  omit `ok`, and a test explicitly requires `ok` to be absent from explore.
- The current frozen architecture makes MCP `scan_rules` read-only and moves
  fixes to `apply_rule_fixes`, but the later MCP comparison table still says
  `scan_rules(fix=true)` is destructive.
- Architecture describes `symbols.json` as the only optional cache file, while
  the implementation and README also use `inventory.json`.
- Architecture and skills describe a compact edit manifest without stating the
  implemented nested field path.

Recommendation:

- Reconcile the authoritative current-contract sections first, then update
  README, CLI help, both skills, MCP workflow/prompt, and tests from that source.
- Add contract checks for every current command/tool name, mutation class,
  resource, cache artifact, and JSON example. Do not use substring-only tests
  as proof that examples teach a complete workflow.

## Context and response design

Compact v2 solved much of the raw ast-grep payload problem. Remaining hot-path
measurements from this audit were:

| Response | Bytes |
|---|---:|
| depth-two explore | 3,558 |
| exact qualified find, four candidates | 2,008 |
| exact symbol source | 1,610 |
| five-result impact page | 1,750 |
| one-class interface, 20 members | 6,334 |
| default 38-symbol MCP module interface | 13,619 |
| two-edit replacement plan | 2,824 |
| broad ten-result MCP tool search | 13,620 |

Recommended v3 cleanup:

- Lower structured-interface defaults or teach the workflow to pass top-level
  filters. A found method cannot currently be handed directly to interface;
  consider `interface --symbol-json` / MCP `exact_symbol`, returning its owner
  and selected member without the whole file contract.
- Replace duplicated interface fields (`returned` and `returned_symbols`,
  `total` and `total_symbols`) with one paging vocabulary. In live output,
  `returned_symbols` meant 38 while `returned` meant the 10-item page.
- Separate member incompleteness from page truncation with structured reasons
  such as `member_truncated` and `page_truncated`; do not require warning-text
  parsing.
- Remove overlapping compact impact counters (`total`, `total_count`,
  `raw_count`, `execution_cap`, `filtered_count`) from the default projection.
  Keep execution diagnostics behind full detail or a named diagnostics object.
- Make success-envelope behavior consistent in a new schema. Preserve v2 as a
  compatibility projection instead of silently changing whether `ok` exists.
- Expand `capabilities` into per-operation CLI and MCP contracts with effective
  defaults and maxima. The current response omits map, find, interface,
  read-symbol, structural-page, subprocess-output, total-byte, and MCP cache
  limits, and mixes CLI-style and MCP-only operation names.

## Guarded replacement v3 direction

The safest incremental design is:

```text
search -> plan -> parse attest -> review/refine -> verify -> approved apply -> verify result
```

### Plan

- Keep exact candidates, contained scopes, stable IDs, pre/post hashes, bounds,
  preview, unified diff, warnings, applicability, and full-artifact digest.
- Add per-file pre/post parse diagnostics and make new syntax errors blocking.
- Add a flat edit manifest and explicit selection path.
- Record dirty-worktree state and require a digested acknowledgement before
  changing an already dirty affected file. Exact preimage hashes prevent drift,
  but they do not establish that overwriting user work was intended.

### Review and verify

- Keep `refine` non-mutating and stable-ID based.
- Add a non-mutating `verify` operation that recomputes candidates, hashes,
  syntax evidence, completeness, and applicability against the current source.
- State plainly that an independently copied digest proves artifact identity,
  not human review. MCP clients should retain their external approval boundary
  for destructive calls.

### Apply and recover

- Keep staging, pre-write drift checks, mode preservation, postimage hashes,
  and rollback.
- Recheck parse evidence on staged bytes and final files.
- Report that rollback handles caught failures but not process death or machine
  loss between multi-file replacements. Offer an optional recoverable patch or
  exact preimage bundle with an explicit path and retention policy; do not add
  hidden durable product state.
- Return verification evidence and recommended affected checks, but do not run
  arbitrary repository commands without a separate explicit contract.

### Legacy mutation

- Preserve `rewrite` and `scan --fix` only for compatibility.
- Require an unmistakable all-match acknowledgement in the next breaking CLI
  surface, such as `--unsafe-all-matches`, and keep the warning in the result.
- Do not rank or expose legacy destructive MCP tools for ordinary `replace`,
  `change`, or `fix` discovery when a guarded planner exists.

## Verification recommendations

Add regressions for:

1. invalid Python, JavaScript/TypeScript, and Go postimages becoming
   inapplicable;
2. deep focus under default CLI and MCP depth, including focused files and
   strict/context behavior;
3. real language visibility extraction and filters;
4. composite MCP intents, safe ranking, inventory exactness, and pagination;
5. exact edit-ID extraction and repeated refinement through documented
   examples;
6. every leaf help surface and every skill/workflow command example;
7. current mutation-class, cache, resource, schema, and capability inventories;
8. compact v2 field presence plus a separately designed v3 projection; and
9. staged syntax verification and documented crash-recovery limits.

The current suite's passing state should be retained, but 201 collected tests
do not cover the four confirmed live defects above. Add the regressions before
implementation so a green suite proves the repaired agent contract rather than
only the existing behavior.

## Recommended implementation order

1. Block newly invalid syntax in guarded plans and add parser evidence.
2. Fix Python visibility and deep-focus/default-depth behavior.
3. Replace or wrap MCP regex discovery with safe ranked intent search.
4. Reconcile README, architecture, skills, workflow, prompt, and leaf help.
5. Add the flat edit manifest and non-mutating replacement verification step.
6. Publish a v3 compact schema cleanup while preserving v2 compatibility.
7. Improve name-based impact incrementally only where confidence remains
   honest; do not imply type-aware dependency analysis without a new engine.
