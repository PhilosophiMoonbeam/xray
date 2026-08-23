---
name: xray-cli
description: "Use XRAY to inspect code and make guarded structural changes."
---

# XRAY CLI

Use `xray` (`uv run xray` here) with `ROOT`. Compact v3 is default;
`--schema v2` diagnoses v2.

## Discover code

```bash
xray explore ROOT
xray explore ROOT --focus src/pkg --strict-focus
xray find ROOT "AuthService.validate_user" --limit 5
xray interface ROOT src/package/module.py --limit 20 --max-members 10
xray read-symbol ROOT --symbol-json "$symbol" --max-lines 120
xray symbol-at ROOT src/package/module.py 42
xray capabilities ROOT                    # doctor is an alias
```

`map` aliases `explore`; strict focus omits ancestors.

`find` defaults to `min_score: 60` and 10 scored name/owner matches. Filters
narrow it; `--min-score 0` includes weak candidates. `--detail full` preserves v1.

Preserve the complete find symbol:

```bash
symbol=$(xray find ROOT target_function --limit 1 | jq -c '.symbols[0]')
xray read-symbol ROOT --symbol-json "$symbol"
xray impact ROOT --symbol-json "$symbol"
xray interface ROOT --symbol-json "$symbol"
```

Exact containers return bounded members; exact members return only their owner
path without siblings.

`read-symbol` verifies identity and returns `symbol_mismatch` for stale handoffs.

Impact is name evidence, not a type graph.

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
`rules check` defaults to relative one-based citations; `--detail full` keeps
raw diagnostics. Check and explain report selection and accept contained
`--path` and ordered `--glob` scopes. Root scans use ast-grep ignore defaults;
an explicitly selected hidden path is included. Explain includes
`inspection_lines`. Compact multi-captures contain named nodes.

## Page and change safely

`total_exact: false` makes `total` a lower bound. Cursors bind query/scopes,
projection, and source; a page may use a different positive size.

```bash
xray replace plan ROOT -p 'old_api($ARG)' -r 'new_api($ARG)' -l python | jq '.plan' > plan.json
jq -r '.edit_manifest[].edit_id' plan.json
xray replace refine ROOT --plan-file plan.json --edit-id EDIT_ID | jq '.plan' > refined.json
REVIEWED_DIGEST=$(jq -r '.plan_digest' refined.json)
xray replace verify ROOT --plan-file refined.json --expected-digest "$REVIEWED_DIGEST"
xray replace apply ROOT --plan-file refined.json --expected-digest "$REVIEWED_DIGEST"
```

`xray.replace.v2` binds review. Blocked plans omit
verify/apply. `verify` repeats guards without writes. Apply rejects drift,
stages and verifies writes, and rolls back partial replacement. Use authoritative
`rollback_status`: `not_attempted`, `succeeded`, or `failed`. Legacy
`rollback_attempted`, `rollback_succeeded`, and count are derived. Crashes can defeat rollback.
`root_fingerprint` binds selection and preimages; refine may change it without drift.

Legacy `rewrite` and `scan --fix` remain destructive. Their `--limit` limits
reporting, not edits. Pass `-l/--lang` for pattern mutations when known.

Paths stay inside `ROOT`. Exit codes: `0` success, `1` operational failure,
`2` invalid input. Invalid ast-grep patterns/rules/tests use `2`; missing tools,
timeouts, I/O, and output bounds use `1`. Text is lossy.
