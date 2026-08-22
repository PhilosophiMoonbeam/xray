---
name: xray-cli
description: "Use XRAY to map, inspect, assess impact, search, validate rules, and make guarded structural replacements."
---

# XRAY CLI

Use installed `xray` (`uv run xray` here). Pass `ROOT`. Compact v3 is default;
`--schema v2` diagnoses the prior projection.

## Discover code

```bash
xray explore ROOT
xray explore ROOT --focus src/pkg --all-depths --limit 500
xray explore ROOT --focus src/pkg --strict-focus
xray find ROOT "AuthService.validate_user" --limit 5
xray interface ROOT src/package/module.py --limit 20 --max-members 10
xray read-symbol ROOT --symbol-json "$symbol" --max-lines 120
xray symbol-at ROOT src/package/module.py 42
xray capabilities ROOT                    # doctor is an alias
```

`map` aliases `explore`. Strict focus starts output at the focus; otherwise it
retains root context and ancestors.

`find` defaults to `min_score: 60` and 10 scored name/owner matches. Filters
narrow it; `--min-score 0` includes weak candidates. `--detail full` preserves v1.

Preserve the complete find symbol:

```bash
symbol=$(xray find ROOT target_function --limit 1 | jq -c '.symbols[0]')
xray read-symbol ROOT --symbol-json "$symbol"
xray impact ROOT --symbol-json "$symbol"
xray interface ROOT --symbol-json "$symbol"
```

`read-symbol` verifies current path/range/name/type/qualified identity and
returns typed `symbol_mismatch` for stale or tampered handoffs.

Impact is name evidence, not a type-aware graph.

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
`rules check` defaults to compact relative one-based citations; use
`--detail full` for raw diagnostics. `rules explain` includes
`inspection_lines`. Compact multi-captures contain named nodes; full keeps raw separators.

## Page and change safely

Inspect paging fields; `total_exact: false` makes `total` a lower bound.
Continuable limits are positive. A cursor binds query/scopes, projection, and
source, but a later page may use a different positive size.

```bash
xray replace plan ROOT -p 'old_api($ARG)' -r 'new_api($ARG)' -l python | jq '.plan' > plan.json
jq -r '.edit_manifest[].edit_id' plan.json
xray replace refine ROOT --plan-file plan.json --edit-id EDIT_ID | jq '.plan' > refined.json
REVIEWED_DIGEST=$(jq -r '.plan_digest' refined.json)
xray replace verify ROOT --plan-file refined.json --expected-digest "$REVIEWED_DIGEST"
xray replace apply ROOT --plan-file refined.json --expected-digest "$REVIEWED_DIGEST"
```

`xray.replace.v2` binds the review. Follow `next_actions`; blocked plans omit
verify/apply. Exceptions require recorded flags. `verify` repeats guards without writes.
Apply rejects tampering/drift, stages postimages, preserves modes, verifies writes,
and rolls back partial replacement. Check `rollback_attempted` first;
`rollback_succeeded` matters only after an attempt. Crashes can defeat rollback.
`root_fingerprint` binds selection and preimages; refine may change it without drift.

Legacy `rewrite` and `scan --fix` remain destructive. Their `--limit` limits
reporting, not edits. Pass `-l/--lang` for pattern mutations when known.

Paths stay inside `ROOT`. Exit codes: `0` success, `1` command
failure, `2` validation failure. Text is lossy.
