# XRAY Instruction Transformation Evidence

This non-authoritative record preserves historical instruction transformation,
adoption, qualification, and D11 deletion evidence. It is not current
authority, a mode selector, or proof of present qualification. `PROJECT.md`
selects Development Sprint by default and explicitly activates a named
Enterprise/Certification milestone when required. The maps, counts, hashes,
and commands below describe their original snapshot; do not regenerate them
for routine policy edits. Frozen packets and companions remain intact.

## Source-to-result map

| Source | Current result | Treatment/evidence |
|---|---|---|
| Recipe index and boundaries | `AGENTS.md` and standards index | XRAY facts replace placeholders; root authority and protected actions remain. |
| Readiness and architecture placeholders | `PROJECT.md`, `ARCHITECTURE.md` | Verified facts only; readiness and component gates remain. |
| Route classifier and three lanes | `docs/agent-model-routing.md` | Retained with frozen routes and target capacity. |
| Beads, contract, allocation, review, integration, delivery | `docs/agent-operations.md` | Retained for root plus three children, disjoint writes, tracker preservation. |
| Behavior and owned-text standards | `docs/implementation-standard.md`, `docs/repository-language-standard.md` | Retained with XRAY baseline, uv-only Python, JSON output, and YAML-input distinction. |
| Adoption/inventory | `docs/ADAPTATION.md`, `TEMPLATE_MANIFEST.md` | Adapted; README/self and frozen packet rows are explicit. |
| Recipe examples | `examples/*` | Byte-identical and explicitly non-authoritative. |
| Recipe Git/Beads state | No transplanted state | XRAY identity, history, graph, and recovery remain project-owned. |
| V2 override and resident lifecycle | `.codex` config, validator, routing, operations | V2 is explicit; three-child capacity and three-writer ceiling remain. |
| Product README | `README.md` | Product workflows remain; repetitive catalogs move to architecture/help. |
| Product cutover | `src/xray/`, package metadata, tests | Eleven operations, two MCP tools, closed inputs, cache, cursor, and guarded apply are implemented and tested. |

Each proposition has one owner. Current behavior is source, tests, and current
docs; packets and reports preserve history rather than reopen the contract.

## Result-to-source map

| Current result | Authority/evidence |
|---|---|
| Frozen routes, role boundaries, ceilings, V2 lifecycle, hooks, no-CI state, rollback, and delivery | Design Packet v2, retained v1 decisions, `AGENTS.md`, and validators. |
| Root-fast, parallel, and high-assurance routing | Routing standard and packet. |
| Child contracts, root-only Beads, disjoint resources, exact evidence, breakthrough stop, Terra review, serial integration | Operations standard and packet. |
| XRAY behavior and compatibility baseline | Source, focused tests, README, and architecture. |
| uv, Context7, Playwright, GitHub CLI, and non-interactive shell | Root index and implementation standard, constrained by project authority. |
| Owned-text profiles, strength, vocabulary, maps, scenarios, and budgets | Language Standard and this proof set. |
| Exact examples and Beads metadata | Packet byte-invariant set at the pinned recipe commit. |
| Eleven operations, MCP surface, bounds, cache, cursor, and guarded apply | `src/xray/`, README, architecture, and focused tests. |
| Package identity and deleted-asset absence | Metadata, lockfile, package tests, and build evidence. |

V4 source↔result edge: `docs/next-major-design-packet-v4.md` V4-A maps to the
pending method, current docs, validator, and manifest; those implementation
descriptions map back to the packet's pending applicability contract. V3-A/B/C,
v2 F1–F3, and inherited v1 decisions remain retained evidence, not reopened.

No row grants credentials, production access, publication, deployment, remote
Git/Beads synchronization, or a product schema, database, service, or YAML
output.

## Vocabulary and transformation decisions

The rewrite uses canonical terms: root, Bead, contract, artifact, evidence, gate,
accept, approve, complete, material, bounded, retry, owned text, literal content,
and semantic density. Product JSON remains distinct from a descriptive YAML-shaped
assignment example; MUST/MUST NOT, SHOULD, and MAY retain source strength.

Consolidation gives each enforceable fact one authoritative home: README owns
workflows, architecture the complete map, and this file the D11 ledger.
Receiving documents link rather than duplicate. Source, tests, and metadata
describe implementation, not pending v4 qualification; adoption v2 remains
harness authority and v4 controls only V4-A. V1–v3 packets and all adoption
pairs remain frozen evidence. Removed surfaces are cut over, not fallbacks.

## Removed and relocated behavior

| Change | Retained control |
|---|---|
| Recipe README body omitted | Product README keeps workflows and concise authority links. |
| Recipe placeholders removed | Project and architecture contain verified facts. |
| Five-child ceiling replaced | Config and validators enforce frozen three-child capacity. |
| Legacy hook groups merged | One bounded SessionStart composer covers lifecycle boundaries. |
| Personal absolute Beads routing removed | Planning-checkout bootstrap preserves canonical history. |
| Broad byte preservation rejected | Only packet-named artifacts are hashed; adapted text uses semantic gates. |

## Validation scenarios

| Scenario | Expected result |
|---|---|
| Not-ready project requests application editing | Stop outside authorized harness/profile/architecture scope. |
| Child attempts Beads mutation, descendants, coordination, integration, or delivery | Reject lane. |
| Writers share path, output, worktree, or resource | Do not allocate concurrently. |
| Completed child needs no follow-up | Interrupt and mark relinquished; do not claim immediate reclamation. |
| Full three-child pool needs replacement | Replace least-recently-used unloadable relinquished resident. |
| Replacement fails after every child is relinquished | Stop delegation and report residency failure. |
| Two evidence-free hypotheses retain one failure key | Stop and route the packet to breakthrough review. |
| Terra finds no counterexample | Record evidence, not approval. |
| YAML-shaped example appears | Keep descriptive; product output remains JSON/text. |
| Required check lacks an authorized alternative | Report the gap; do not claim completion. |
| Delivery authority is absent | Stop after local verification. |
| All requirements and exact-candidate gates are proven | Root may accept and integrate. |

## Size and integrity evidence

Counts use `wc -w -c` (`text.split()` words / UTF-8 bytes); start is the wave-2
pre-edit tree and final is this tree. Ceilings are unchanged.

| Artifact | Start | Final | Limit |
|---|---:|---:|---:|
| `PROJECT.md` | 1,790 / 13,932 | 1,790 / 13,954 | 1,800 / 14,000 |
| `ARCHITECTURE.md` | 2,496 / 19,760 | 2,494 / 19,729 | 2,500 / 20,000 |
| `README.md` | 1,921 / 15,326 | 2,064 / 16,494 | 2,800 / 22,000 |
| This evidence | 1,633 / 12,886 | 1,655 / 12,887 | 1,800 / 13,000 |
| `TEMPLATE_MANIFEST.md` | 521 / 3,981 | 569 / 4,383 | 600 / 5,000 |
| `.codex/validate_agents.py` | 1,612 / 20,990 | 1,585 / 21,000 | 1,800 / 21,000 |
| `.codex/validate_project_readiness.py` | 454 / 5,734 | 454 / 5,734 | 525 / 5,800 |
| Six role files | 924 / 7,460 | 924 / 7,460 | 1,160 / 9,250 |
| Python automation aggregate | — / 34,815 | — / 34,825 | — / 35,000 |
| CLI skill pair | 2,120 / 16,694 | 2,253 / 17,716 | parity |

Fixed recipe source SHA: `734e1ecb55554b26a7dd621432cee3d096c375b3d19c6b1ea109559a5f9f5a8e`.
The validator checks role/example byte invariants; no budget or invariant ceiling
was increased.

## XRAY 1.0.0 authority cutover and D11 deletion ledger
Current source, tests, and docs describe implemented 1.0.0 behavior; v4 governs
only its named applicability boundary. Each row records source,
replacement/removal, disposition, and negative-test classification.

| Removed source surface | Replacement or removal boundary | Disposition; negative classification |
|---|---|---|
| `explore`, `explore_repo`, alias metadata, `invoked_as`, `include-symbols`, `--max-depth`, `--all-depths`, `--strict-focus` | `map ROOT --depth N|all`, explicit focus/context | Delete aliases/skeleton output; map grammar works; removed names/flags are CLI negative tests. |
| `find_symbol`, scored handoff, `abs_path`, `min_score`, `include_scores`, confidence fields | `find ROOT QUERY`, typed references | Delete weak handoffs/fields; removed command/fields are schema and CLI rejection tests. |
| `read-symbol`, `read_symbol`, `symbol-at`, `symbol_at` | `read` location/source/occurrence/reference targets | Merge exact reads; spellings are command-rejection and package-guidance absence tests. |
| `search_pattern`, `scan`, `scan_rules`, `check_rules`, `rules check`, `rules explain`, `rules test`, `test_rules` | `search` literal/pattern/rule/closed config | Delete wrappers/mutation; routes are CLI and packaged-guidance negative tests. |
| `imports`, `file_imports`, `exports`, `file_exports` | `interface` observed import/export sections | Keep syntax evidence without operation names/resolution; catalog-absence tests classify removal. |
| `replace plan`, `replace refine`, `replace verify`, `replace apply`, `plan_replacement`, `refine_replacement`, `verify_replacement`, `apply_replacement`, `apply_rule_fixes` | `change_plan`, `change_refine`, `change_verify`, `change_apply` | One guarded lifecycle; removed routes are CLI/catalog rejection tests. |
| `rewrite`, `rewrite_pattern`, `scan --fix`, direct mutation, unsafe exact-name paths | Reviewed `change_apply` only | Delete backdoors; unknown names fail; mutation and removed-route tests classify rejection. |
| `xray.cli.v1`, `xray.cli.v2`, `xray.cli.v3`, `xray.replace.v1`, `xray.replace.v2`, `--schema`, `--detail full`, legacy strings, heterogeneous envelopes | `xray.v1` results and `xray.change.v1` plans | Delete projections; schema/legacy literals are packaging and CLI negative tests. |
| Offset cursors, shortened fingerprints, `returned`, `total_exact`, `truncated`, lower-bound side channels, `last_*` metadata | Full-bound opaque cursors, typed coverage, captured identity | Delete paging reconstruction; cursor/response tests reject stale or legacy shapes. |
| Git/mtime `symbols.json`/`inventory.json` caches and expiry assumptions | Content-derived optional artifacts, private atomic writes, fixed ceilings | Do not migrate old contents; cache tests classify corruption as performance-only and files as absent. |
| `XRAY_AST_GREP_OUTPUT_LIMIT_CHARS`, `XRAY_AST_GREP_TIMEOUT_SECONDS`, `XRAY_MCP_INDEXER_CACHE_LIMIT` | Owning request/catalog limits and bounded services | Remove environment contracts; hostile-variable tests prove bounds cannot rise. |
| Custom MCP JSON frames, duplicate tools, regex discovery, transport envelopes | FastMCP `search_tools`/`call_tool`, structured results | Delete framing/duplicate schemas; exact-two-tool and closed-call tests classify rejection. |
| Inactive `src/xray/lsp_config.json` | No language-server dependency/config asset | Delete after inventory; packaging tests prove wheel/sdist absence and no guidance route. |

### D11 deletion proof and focused commands

Pre-deletion inventory covered runtime, entry points, package data, installers,
tests, docs, skills, and configuration; no consumer remained. Packaging tests
assert current resources and removed routes. Negative literals are witnesses, not
consumers.

```text
uv lock --check
uv run xray --version
uv run xray map . --depth 1
uv run python .codex/validate_agents.py --self-test
uv run python .codex/validate_agents.py
uv run python .codex/validate_project_readiness.py --self-test
uv run python .codex/validate_project_readiness.py
uv run pytest tests/test_packaging.py
git diff --check
```
Packet SHA-256 values (v1–v3/adoption pairs frozen; v4 pending):

```text
docs/adoption-design-packet-v1.md       8b01ffd63c5d5f76936ffe873e6be2114e38ff6af1ea4e13a3d9a6993fc9eda0
docs/adoption-design-packet-v2.md       b762310d0409496f429f409c0504f86162304f168d67828f905a16b082fabd63
docs/next-major-design-packet-v1.md    c860367da05d61069726b9d4fe7d79e030031dfcc16990a786d2062d28ed7331
docs/next-major-design-packet-v2.md    726e371d0d244a25df164f9b2e1729c1b6f62d0cdf1317840d9e150e1f83a80d
docs/next-major-design-packet-v3.md    c67fb3a61d43da3708e4b42b408402ea16dd4bfcecf3d821cafcd97ca14b7fd5
docs/next-major-design-packet-v4.md    1cc251c84d4e41d5bda761ffe74cf8f34fe6d8872a82fde3dff17296c0f389d6
```

Historical hashes remain unchanged; `.codex/validate_agents.py` checks all six
packet pairs exactly. Root owns final qualification and integration.
