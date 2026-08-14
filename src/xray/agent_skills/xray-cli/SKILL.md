---
name: xray-cli
description: "Use XRAY for compact code discovery and guarded structural change: map repositories, find symbols, inspect typed interfaces and classified name impact, search code, plan and apply replacements, scan rules, inspect imports or exports, and pass JSON through jq."
---

# XRAY CLI

Use installed `xray`; inside this repository use `uv run xray`. Pass `ROOT`
explicitly. Compact JSON is the default.

## Select an operation

```bash
xray explore ROOT --max-depth 2
xray find ROOT "AuthService.validate_user" --limit 5 --min-score 60
xray interface ROOT src/package/module.py
xray search ROOT -p 'old_api($ARG)' -l python
xray imports ROOT src/package/module.py
xray exports ROOT src/package/module.py
xray scan ROOT --rule sgconfig.yml
```

`map` aliases `explore`; JSON still reports `command: "explore"` and
`invoked_as: "map"`.

Preserve the complete `find` symbol when requesting impact:

```bash
xray find ROOT "target_function" --limit 1 \
  | jq -c '.symbols[0]' \
  | xray impact ROOT --symbol-file -
```

Impact is bounded name-based evidence, not a type-aware dependency graph.
References classify `definition`, `import`, `call`, `read`, or `text` with
confidence. Review same-name definitions separately.

## Output

- Compact `xray.cli.v2` JSON is default for `explore`, `interface`, `impact`,
  `replace`, `search`, `scan`, `rewrite`, `imports`, and `exports`.
- `find` remains `xray.cli.v1` and has no `--detail` option.
- Where offered, use `--detail full` only for lossless upstream or legacy v1
  fields, and `--format text` only for lossy scans.
- Use `--pretty` only for visual JSON.
- YAML is rule input for `scan`, never XRAY output.
- For paged reads, inspect `returned`, `total`, `total_exact`, `truncated`, and
  `next_cursor`. `total_exact: false` makes `total` a lower bound. Reuse a
  cursor only with the same command, root, query, scopes, and source snapshot.

## Change code

Prefer reviewed plan/apply:

```bash
xray replace plan ROOT -p 'old_api($ARG)' -r 'new_api($ARG)' -l python \
  --path src --glob '*.py' > plan.json
# Review preview, counts, paths, warnings, hashes, and .plan.plan_digest.
xray replace apply ROOT --plan-file plan.json --expected-digest REVIEWED_DIGEST
```

Copy `REVIEWED_DIGEST` after review. Apply rejects digest, query, scope, count,
root, or source drift; stages all postimages; preserves modes; verifies writes;
and rolls back already replaced files after a later failure. Use `--rule`
instead of pattern/replacement for a fix-bearing rule.

Legacy mutations remain explicit all-match operations:

```bash
xray rewrite ROOT -p 'old_api($ARG)' -r 'new_api($ARG)' -l python
xray scan ROOT --rule sgconfig.yml --fix
```

For `rewrite` and `scan --fix`, `--limit` limits reporting, not edits. They do
not require plan confirmation or support continuation after mutation. Review
their summaries and the worktree.

## Boundaries

- Pass `-l/--lang` for pattern mutations when known.
- Paths, rule files, interface targets, and symbol definitions must resolve
  inside `ROOT`; parent traversal and symlink escapes fail.
- Exit codes: `0` success, `1` command failure, `2` parse or validation error.
  Errors are JSON unless `--format text` was requested.
