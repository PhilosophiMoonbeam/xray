# XRAY Progressive Discovery

Use this skill to inspect and safely change a repository through XRAY MCP while
keeping context small.

## Discover

`search_tools` accepts a regular expression and returns at most 10 matches. Use
a focused intent such as `lookup`, `blast radius`, `interface|signature`,
`safe code replacement`, `help`, or `workflow`; a broad `.` can hide later
tools. Execute one result through `call_tool` with its exact name and arguments.

1. Map with `explore_repo`. Compact relative-path `entries` default to depth 2.
   Use contained nested `focus_dirs`; set `all_depths=true` only explicitly.
2. Locate definitions with `find_symbol`. It matches names and owner-qualified
   identities, not behavior. The default score threshold is 60 and the page is
   10; preserve the full scored symbol object.
3. Inspect contracts with bounded `read_interface_structured`, exact source with
   `read_symbol`, or a location with `symbol_at`. `read_interface` is legacy text.
4. Estimate blast radius with `what_breaks` and the full find symbol. Results
   are name-based references, not a type-aware caller or dependency graph.

`xray_capabilities` reports help, workflow resources, schemas, operations,
bounds, dependency versions, health, and optional repository checks.

## Page and validate

- Read results expose `returned`, `total`, `total_exact`, `truncated`, and
  `next_cursor`. A false `total_exact` means a lower bound. Reuse a cursor only
  with identical arguments and unchanged source. Impact paging stays under
  `.impact` only in the CLI; MCP returns its result fields directly.
- Narrow find with `paths`, `languages`, `symbol_types`, or `visibility`.
  Request `min_score=0` only to inspect low-confidence candidates.
- Use `search_pattern`, `file_imports`, and `file_exports` for bounded structural
  matches and outlines. Request `detail="full"` only for raw ast-grep metadata.
- Protocol failures set `isError=true` and return structured
  `error: {code, message, details?}` values; do not treat them as empty results.
- Paths, rules, files, and symbols must remain inside the supplied root.

## Rules and mutation

YAML is ast-grep rule/test input, never XRAY output. `scan_rules`, `check_rules`,
`explain_rules`, and `test_rules` are read-only. Tests never update snapshots or
start interactive review. For fixes, create a rule plan with `plan_replacement`,
review it, then call destructive `apply_rule_fixes` with the full plan and an
independently copied digest.

For pattern changes, call `plan_replacement`, review every manifest `edit_id`,
preview, deterministic diff, warning, hash, bound, applicability value, and
`plan_digest`, optionally select edits with `refine_replacement`, then call
`apply_replacement`. Plans are `xray.replace.v2`; their digest binds the complete
review artifact. Truncated review requires recorded acknowledgement. Zero-match
plans cannot apply, v1 plans are rejected, and apply rejects tampering or drift
before staged writes and rolls back partial replacement. Pass `lang` when known.

Keep `rewrite_pattern` only for explicit legacy all-match mutation. Its limit
does not bound edits. Fetch `xray://workflow` for longer examples.
