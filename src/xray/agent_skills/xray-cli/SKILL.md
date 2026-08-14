---
name: xray-cli
description: "Use XRAY for compact code discovery and guarded structural change: map repositories, find and read symbols, inspect interfaces and blast radius, search code, validate rules, and plan, refine, or apply replacements."
---

# XRAY CLI

Use installed `xray`; here use `uv run xray`. Pass `ROOT`. Compact
`xray.cli.v2` JSON is the default.

## Discover code

```bash
xray explore ROOT                         # defaults to depth 2
xray explore ROOT --focus src/pkg --all-depths --limit 500
xray find ROOT "AuthService.validate_user" --limit 5
xray interface ROOT src/package/module.py --limit 20 --max-members 10
xray read-symbol ROOT --symbol-json "$symbol" --max-lines 120
xray symbol-at ROOT src/package/module.py 42
xray capabilities ROOT                    # doctor is an alias
```

`map` aliases `explore`; JSON reports `command: "explore"` and
`invoked_as: "map"`. Nested focus retains root context and ancestors.

`find` defaults to `min_score: 60`, scored results, and a 10-item page. It
matches names and owner-qualified identities, not behavior. Narrow with
repeatable `--path`, `--language`, `--type`, or `--visibility`; use
`--min-score 0` for low-confidence candidates. `--detail full` preserves v1.

Preserve a complete find symbol for reads and impact:

```bash
symbol=$(xray find ROOT target_function --limit 1 | jq -c '.symbols[0]')
xray read-symbol ROOT --symbol-json "$symbol"
xray impact ROOT --symbol-json "$symbol"
```

Impact is bounded name-based evidence, not a type-aware dependency graph.
References classify `definition`, `import`, `call`, `read`, or `text`.

## Structural reads and rules

```bash
xray search ROOT -p 'old_api($ARG)' -l python
xray rules check ROOT --rule rule.yml
xray rules explain ROOT --rule rule.yml
xray rules test ROOT --test-dir rule-tests --config sgconfig.yml
xray imports ROOT src/package/module.py
xray exports ROOT src/package/module.py
```

YAML is ast-grep rule/test input, never XRAY output. `rules` commands do not
fix files, update snapshots, or start interactive sessions. Legacy
`xray scan ROOT --rule rule.yml --fix` remains an explicit all-match mutation.

## Page and change safely

For reads, inspect `returned`, `total`, `total_exact`, `truncated`, and
`next_cursor`. `total_exact: false` makes `total` a lower bound. Impact paging
metadata remains nested under `.impact`. Reuse cursors only with identical
arguments and an unchanged source snapshot.

```bash
xray replace plan ROOT -p 'old_api($ARG)' -r 'new_api($ARG)' -l python > plan.json
# Review every manifest edit_id, preview, diff, warning, hash, bound, and digest.
xray replace refine ROOT --plan-file plan.json --edit-id EDIT_ID > refined.json
xray replace apply ROOT --plan-file refined.json --expected-digest REVIEWED_DIGEST
```

Plans are `xray.replace.v2`; the digest binds the complete review artifact.
Truncated review is inapplicable unless `--allow-truncated-review` is recorded.
Zero-candidate plans are inapplicable; no-op plans require `--allow-noop`.
Apply rejects v1, tampering, query/scope/source drift, stages all postimages,
preserves modes, verifies writes, and rolls back partial replacement.

Legacy `rewrite` and `scan --fix` remain destructive. Their `--limit` limits
reporting, not edits. Pass `-l/--lang` for pattern mutations when known.

Paths, rules, files, and symbols must remain inside `ROOT`. Compact errors use
the exact leaf command and `error: {code, message, details?}`. Exit codes are
`0` success, `1` command failure, and `2` parse/validation failure. Use
`--format text` only for lossy human scans.
