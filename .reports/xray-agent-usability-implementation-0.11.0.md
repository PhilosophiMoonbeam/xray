# XRAY 0.11.0 Agent Usability Implementation Evidence

This non-authoritative report maps the 0.10.0 usability audit to the 0.11.0
implementation. Authority remains in `ARCHITECTURE.md`; Git retains superseded
wording. The implementation base is
`8c42d293bb2d5d8fbec1dcbacb217ce10d789228`. The source audit SHA-256 is
`c739290a95daa05940477a3b3fb0e7eff0729eb39353bfcfd7e78a1e48142a2a`.

## Source-to-result map

| Audit finding | Current result | Evidence |
|---|---|---|
| Deep focus omitted the focus itself | Focus depth is relative to each focus; root context is explicit and strict focus is available | `XRayIndexer.explore_repo_data`, CLI/MCP focus regressions |
| Python and cross-language visibility disagreed | Inventory applies Python underscore, Go capitalization, and JavaScript/TypeScript private/export conventions | real-language visibility filter regressions |
| MCP regex discovery did not rank intent or page inventory | Ranked intent search, explicit regex mode, summary/full detail, exact totals, cursors, and guarded-change ranking | MCP discovery and call-proxy regressions |
| Replacement could produce syntactically invalid files | Plans compare preimage/postimage parse diagnostics; verify/apply repeat staged and final syntax checks | Python, JavaScript, TypeScript, and Go syntax regressions |
| A reviewed plan could overwrite existing worktree changes | Dirty affected paths block applicability unless their acknowledgement is digested | Git worktree regressions |
| Review required nested edit-ID traversal | Every plan contains a flat `edit_manifest`; documented `jq` works for bare and CLI-enveloped plans | replacement manifest and documentation tests |
| No non-mutating final guard check | CLI/MCP `verify_replacement` recomputes every apply guard without writes | no-write, drift, and call-surface regressions |
| Interface output duplicated paging counts and over-returned context | Default v3 uses one paging vocabulary and exact-symbol owner/member selection | CLI/MCP default-v3 and explicit-v2 regressions |
| Interface completeness required warning parsing | V3 exposes structured completeness reasons | member/page truncation regressions |
| Compact impact exposed overlapping counters | V3 retains page total and groups raw/filter/execution evidence under `diagnostics` | CLI/MCP impact projection regressions |
| Compact success fields were inconsistent | Default v3 consistently emits CLI `ok`; v2 remains an explicit diagnostic projection | default-v3 and explicit-v2 success/error regressions |
| Capabilities omitted bounds, caches, and surface distinctions | Capabilities separate CLI/MCP names, defaults, maxima, caches, schemas, resources, prompts, and mutation classes | capability assertions and live doctor output |
| README, architecture, skills, prompt, and help contradicted runtime | Owned guidance now teaches ranked search, focus, symbol-at, exact interface, verification, syntax/dirty guards, cache files, and legacy boundaries | help, packaging, byte-identity, resource, prompt, and stale-text checks |

## Result-to-source map

Every current result above traces to an audit recommendation except dirty-file
blocking and syntax attestation, which implement the audit's guarded replacement
direction. Default v3, explicit v2 and full/v1, JSON/`jq`, direct legacy mutation, and name-based
impact trace to the compatibility constraints recorded in the audit and project
standards. No result adds YAML output, type-aware graphs, automatic commits,
durable plan storage, or crash-proof rollback.

## Removed or relocated propositions

- Regex-only MCP guidance was removed because ranked intent is now the default;
  regex remains explicit compatibility behavior.
- The claim that XRAY lacked line-to-symbol lookup was removed; `symbol-at` and
  `symbol_at` are current bounded lookup surfaces.
- MCP `scan_rules(fix=true)` guidance was removed; scan is read-only and guarded
  rule application belongs to `apply_rule_fixes`.
- Uniform compact-success claims moved to v3; v2 field presence remains frozen.
- The single-cache-file inventory expanded to the actual `symbols.json` and
  `inventory.json` files.

## Validation scenarios

| Scenario | Required result |
|---|---|
| A replacement introduces a new parse diagnostic | Plan is inapplicable unless the exceptional acknowledgement is recorded |
| An affected file is already dirty | Plan is inapplicable unless the dirty-file acknowledgement is recorded |
| Source, digest, selection, syntax, or dirty state drifts before verify/apply | Reject before writes |
| Ordinary intent asks to rename or change code safely | Rank `plan_replacement`; omit legacy rewrite from ordinary results |
| Exact legacy rewrite is requested | Discover or call `rewrite_pattern` with destructive metadata |
| A found method is passed to v3 interface | Return its owner and selected member path only |
| V2 or full/v1 is requested | Preserve the established compatibility projection |
| A process terminates during replacement | Do not promise rollback; require recoverable worktree and diff inspection |

## Size and integrity evidence

The CLI skill remains at most 500 words and 3,600 bytes; the MCP skill remains
at most 500 words and 3,600 bytes. Repository and packaged CLI skill bytes are
identical. Final evidence records the exact candidate commit, full gate commands,
artifact hashes, diff review, and push result after qualification.
