---
name: xray-cli
description: "Use XRAY to map, inspect, assess impact, search, validate rules, and make guarded structural replacements."
---

# XRAY CLI

Use installed `xray`; here use `uv run xray`. Pass `ROOT`. Compact
`xray.cli.v2` JSON is the default; opt into `--schema v3` for consistent
success/paging fields, typed completeness, and exact-symbol interfaces.

## Discover code

```bash
xray explore ROOT                         # defaults to depth 2
xray explore ROOT --focus src/pkg --all-depths --limit 500
xray explore ROOT --focus src/pkg --strict-focus
xray find ROOT "AuthService.validate_user" --limit 5
xray interface ROOT src/package/module.py --limit 20 --max-members 10
xray read-symbol ROOT --symbol-json "$symbol" --max-lines 120
xray symbol-at ROOT src/package/module.py 42
xray capabilities ROOT                    # doctor is an alias
```

`map` aliases `explore`. Focus retains root context and ancestors unless
`--strict-focus` is set.

`find` defaults to `min_score: 60` and 10 scored name/owner matches. Narrow with
filters; `--min-score 0` includes weak candidates. `--detail full` preserves v1.

Preserve a complete find symbol for reads and impact:

```bash
symbol=$(xray find ROOT target_function --limit 1 | jq -c '.symbols[0]')
xray read-symbol ROOT --symbol-json "$symbol"
xray impact ROOT --symbol-json "$symbol"
xray interface ROOT --symbol-json "$symbol" --schema v3
```

Impact returns classified name evidence, not a type-aware graph.

## Structural reads and rules

```bash
xray search ROOT -p 'old_api($ARG)' -l python
xray rules check ROOT --rule rule.yml
xray rules explain ROOT --rule rule.yml
xray rules test ROOT --test-dir rule-tests --config sgconfig.yml
xray imports ROOT src/package/module.py
xray exports ROOT src/package/module.py
```

YAML is ast-grep rule/test input, never XRAY output. `rules` are read-only;
`xray scan ROOT --rule rule.yml --fix` is legacy all-match mutation.

## Page and change safely

Inspect paging fields; `total_exact: false` makes `total` a lower bound. Reuse
cursors only with identical arguments and source.

```bash
xray replace plan ROOT -p 'old_api($ARG)' -r 'new_api($ARG)' -l python > plan.json
# Extract and review every edit, preview, diff, syntax result, dirty path, bound, and digest.
jq -r '(.plan // .).edit_manifest[].edit_id' plan.json
xray replace refine ROOT --plan-file plan.json --edit-id EDIT_ID > refined.json
xray replace verify ROOT --plan-file refined.json --expected-digest REVIEWED_DIGEST
xray replace apply ROOT --plan-file refined.json --expected-digest REVIEWED_DIGEST
```

`xray.replace.v2` digests bind the review artifact. Exceptional truncated,
no-op, parse-error, and dirty-file cases require their recorded flags.
New parse errors block planning unless `--allow-new-parse-errors` is recorded.
Dirty affected files block planning unless `--allow-dirty-affected` is recorded.
`verify` repeats every apply guard without writes. Apply rejects v1, tampering,
query/scope/source/syntax drift, stages all postimages, preserves modes, verifies
writes, and rolls back partial replacement. A process crash cannot guarantee
rollback; keep the worktree recoverable and inspect the final diff.

Legacy `rewrite` and `scan --fix` remain destructive. Their `--limit` limits
reporting, not edits. Pass `-l/--lang` for pattern mutations when known.

Paths stay inside `ROOT`. Compact errors are typed. Exit codes are `0` success,
`1` command failure, and `2` validation failure. Text output is lossy.
