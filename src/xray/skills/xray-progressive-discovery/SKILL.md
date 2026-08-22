# XRAY Progressive Discovery

Inspect and safely change repositories through XRAY MCP.

## Discover

`search_tools` ranks natural intent and supports explicit `mode="regex"`. Page
with `next_cursor`; request `detail="full"` only for schemas. Execute through
`call_tool`. Legacy mutation is hidden from ordinary intent results.

1. Map with `explore_repo`. Compact relative-path `entries` default to depth 2.
   Use contained nested `focus_dirs`; set `all_depths=true` only explicitly.
2. Locate definitions with `find_symbol`. It matches names and owner-qualified
   identities, not behavior. The default score threshold is 60 and the page is
   10; preserve the full scored symbol object.
3. Inspect signature contracts with bounded `read_interface_structured`, exact source with
   `read_symbol`, or a location with `symbol_at`. Pass the full find result as
   `exact_symbol` to return only its owner/member interface in default v3.
   `read_symbol` verifies that identity against the current inventory and returns
   `symbol_mismatch` for a stale or tampered handoff. `read_interface` is legacy text.
4. Estimate blast radius with `what_breaks` and the full find symbol. Results
   are name-based references, not a type-aware caller or dependency graph.

`xray_capabilities` reports contracts, bounds, versions, and health.

## Page and validate

- Read results expose `returned`, `total`, `total_exact`, `truncated`, and
  `next_cursor`. A false `total_exact` means a lower bound. Continuable limits
  are positive. A cursor binds query/scopes, projection, and unchanged source,
  while a later page may use a different positive size.
- Narrow find with filters; use `min_score=0` only for weak candidates.
- Use `search_pattern`, `file_imports`, and `file_exports` for structural reads.
  Compact multi-captures are named nodes; full detail keeps raw separators.
- Protocol failures set `isError=true` and return structured
  `error: {code, message, details?}` values; do not treat them as empty results.
- Paths, rules, files, and symbols must remain inside the supplied root.

## Rules and mutation

YAML is ast-grep rule/test input, never XRAY output. `scan_rules`, `check_rules`,
`explain_rules`, and `test_rules` are read-only. `check_rules` defaults to relative one-based
citations; full detail preserves raw diagnostics. `explain_rules` adds lossless
`inspection_lines`. For fixes, create a rule plan with `plan_replacement`,
review it, then call `apply_rule_fixes` with the plan and copied digest.

For pattern changes, call `plan_replacement`; review each `edit_manifest` entry,
syntax result, dirty path, preview, diff, warning, hash, bound, applicability,
`next_actions`, and `plan_digest`. Blocked plans omit verify/apply. Optionally select edits
with `refine_replacement`, then call non-mutating `verify_replacement` with the
independently copied digest before `apply_replacement`. Plans are
`xray.replace.v2`; their digest binds the complete review artifact. Truncated
review, new parse errors, and dirty affected files require their explicit
recorded acknowledgements. Apply rejects tampering or drift before staged
writes and rolls back partial replacement. A process crash cannot guarantee
rollback. Check `rollback_attempted` first; `rollback_succeeded` matters only
after an attempt. `root_fingerprint` binds selection and preimages, so refine may
change it without drift. Keep work recoverable. Pass `lang` when known.

Keep `rewrite_pattern` only for explicit legacy all-match mutation. Its limit
does not bound edits. Fetch `xray://workflow` for longer examples.
