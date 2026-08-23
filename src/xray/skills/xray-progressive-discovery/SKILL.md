# XRAY Progressive Discovery

Inspect and safely change repositories through XRAY MCP.

## Discover

`search_tools` ranks natural intent; `mode="regex"` is explicit. Page with
`next_cursor`, request full detail only for schemas, and execute via `call_tool`.

1. Map with `explore_repo`. Compact relative-path `entries` default to depth 2.
   Use contained nested `focus_dirs`; set `all_depths=true` only explicitly.
2. Locate definitions with `find_symbol`; preserve the full scored symbol.
3. Inspect signature contracts with bounded `read_interface_structured`, exact source with
   `read_symbol`, or a location with `symbol_at`. Pass the full find result as
   `exact_symbol`. Exact containers return bounded members; exact members
   return only their owner path without siblings in default v3.
   `read_symbol` returns `symbol_mismatch` for stale identity.
4. Estimate blast radius with `what_breaks` and the full find symbol. Results
   are name-based references, not a type-aware caller or dependency graph.

`xray_capabilities` reports contracts, bounds, and health.

## Page and validate

- Results expose `returned`, `total`, `total_exact`, `truncated`, and
  `next_cursor`; false `total_exact` is a lower bound. Cursors bind query,
  scopes, projection, and source but allow a different positive page size.
- Narrow find with filters; use `min_score=0` only for weak candidates.
- Use `search_pattern`, `file_imports`, and `file_exports` for structural reads.
  Compact multi-captures are named nodes; full detail keeps raw separators.
- Protocol failures set `isError=true` and return structured
  `error: {code, message, details?}`; never treat them as empty results.
- Paths, rules, files, and symbols must remain inside the supplied root.

## Rules and mutation

YAML is ast-grep rule/test input, never XRAY output. `scan_rules`, `check_rules`,
`explain_rules`, and `test_rules` are read-only. `check_rules` defaults to relative one-based
citations; full detail preserves raw diagnostics. `explain_rules` adds lossless
`inspection_lines`. Check and explain report selection, accept contained `paths`
and ordered `globs`, use root ignore defaults, and include explicit hidden paths.
For fixes, review a `plan_replacement`, then call `apply_rule_fixes` with its digest.

For pattern changes, call `plan_replacement`; review each `edit_manifest` entry,
syntax, dirty path, diff, warning, hash, bounds, `next_actions`, and digest. Blocked plans omit verify/apply. Select edits
with `refine_replacement`, then call non-mutating `verify_replacement` with the
independently copied digest before `apply_replacement`. Plans are
`xray.replace.v2`; its digest binds the review. Truncation, new parse errors,
and dirty affected files require recorded acknowledgements. Apply rejects drift before staged
writes and rolls back partial replacement. A process crash cannot guarantee
rollback. Use authoritative `rollback_status`: `not_attempted`, `succeeded`, or
`failed`; legacy Boolean/count fields remain derived compatibility evidence.
`root_fingerprint` binds selection and preimages. Keep work recoverable. Pass `lang` when known.

Keep `rewrite_pattern` only for explicit legacy all-match mutation. Its limit
does not bound edits. Fetch `xray://workflow` for longer examples.
