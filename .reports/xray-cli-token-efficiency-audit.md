# XRAY CLI Token-Efficiency Audit

## Conclusion

XRAY is directionally agent-friendly, but its default JSON is avoidably expensive, especially for structural commands. The largest issue is that `search`, `scan`, `rewrite`, `imports`, and `exports` expose rich ast-grep payloads when agents usually need a compact, stable projection.

## Resolution Status

Implemented in the working tree: compact v2 projections are now the default for structural and explore JSON; lossless v1 payloads remain available through `--detail full`; structural output is bounded to 50 items by default with query-bound continuation cursors; compact rewrite output is summary-only; explore no longer duplicates `tree_text` or absolute paths; and successful compact envelopes omit repeated low-value fields. `find.abs_path` is intentionally retained because symbol objects are direct inputs to impact analysis and MCP handoffs.

Post-implementation measurements against the same repository show `explore` at 2,059 B (down 57%), representative `search` at 9,238 B (down 87%), `imports` at 1,738 B (down 55%), and `exports` at 7,263 B (down 75%). Exact content varies as the repository changes; the bounds and compact field contract provide the durable improvement.

The same compact projection and paging primitives are now used by safe MCP boundaries. `explore_repo`, `search_pattern`, read-only `scan_rules`, `file_imports`, and `file_exports` default to compact output; read-only structural results support bounded query-bound continuation. Mutating `rewrite_pattern` returns a summary by default, while `scan_rules(fix=true)` applies every fix but never advertises continuation against the changed worktree. Full detail remains opt-in.

## Measurements

Representative outputs were measured using the installed XRAY 0.8.2 binary against this repository. Sizes are bytes, not tokenizer-specific token counts, but the ratios reliably expose relative overhead.

| Command | Default JSON | Text | JSON overhead |
|---|---:|---:|---:|
| `explore` | 4,763 B | 679 B | 7.0x |
| `find` | 1,058 B | 346 B | 3.1x |
| `interface` | 4,796 B | 4,502 B | 1.1x |
| `search` | 72,663 B | 6,826 B | 10.6x |
| `imports` | 3,893 B | 901 B | 4.3x |
| `exports` | 28,583 B | 1,929 B | 14.8x |

## Findings

### 1. Raw ast-grep payloads dominate structural output

One ordinary match can include an absolute file path, source line, matched text, leading and trailing character counts, byte offsets, line and column ranges, and complete range trees for every metavariable. It also contains empty `multi`, `single`, or `transformed` objects.

Most agent calls need only a relative path, location, matched text, and compact captures:

```json
{
  "path": "src/xray/cli.py",
  "line": 484,
  "text": "matches = indexer.search_pattern(...) ",
  "captures": {"METHOD": "search_pattern"}
}
```

This is the highest-priority source of avoidable token use.

### 2. Structural commands have no result limit

`search`, `scan`, `imports`, and `exports` have neither `--limit` nor pagination. Broad operations therefore materialize and print every result. The measured search produced 72 KB in this relatively small repository; the same behavior could consume a large portion of an agent context in a monorepo.

Agent-first defaults should impose a conservative limit, report truncation and total counts, and support continuation.

### 3. `explore` represents the repository twice

Default JSON contains both `tree_text` and a structured `entries` array. Each entry also repeats its name, relative path, absolute path, kind, and depth.

Structured entries are useful for automation; the rendered tree should be selected explicitly instead of being returned alongside them by default.

### 4. Absolute paths are repeated

Explore entries and structural matches repeatedly carry absolute paths even though the response envelope already provides the root. `find` likewise returns both `path` and `abs_path`.

Relative paths are sufficient inside an explicitly rooted operation. Absolute paths should be opt-in or represented once at the envelope level.

### 5. The current choice is verbose JSON or lossy text

Text mode is deliberately described as lossy. This leaves no compact, machine-safe middle ground. Agents benefit most from concise structured JSON rather than either raw upstream data or tab-separated text.

A more suitable interface would be:

```text
--detail compact   # default stable, agent-oriented projection
--detail full      # raw ranges, offsets, and upstream metadata
--format json      # default machine-readable representation
--format text      # human scan
--limit 50
--cursor ...
```

Example compact search response:

```json
{
  "matches": [
    {
      "path": "src/xray/cli.py",
      "line": 484,
      "column": 14,
      "text": "indexer.search_pattern(args.pattern, args.lang)",
      "captures": {"METHOD": "search_pattern"}
    }
  ],
  "returned": 1,
  "total": 137,
  "truncated": true,
  "next_cursor": "..."
}
```

### 6. Successful envelopes repeat low-value constants

Successful responses routinely include `schema_version`, `ok`, `command`, `root_path`, and an empty `warnings` array. This is modest per call but compounds across progressive agent workflows.

Keep `schema_version` for compatibility and emit warnings when present. Consider omitting `ok: true`, `warnings: []`, echoed input fields, and other information already known to the caller.

This is lower priority than compacting match payloads.

### 7. `rewrite` returns unnecessary pre-rewrite detail

Rewrite first performs a full structural search, retains all rich match objects, applies the rewrite, and returns the matches with its summary. The common agent need is instead:

```json
{
  "match_count": 37,
  "file_count": 5,
  "files_modified": ["..."]
}
```

Full match details should require `--detail full`.

## Existing Strengths

- Compact rather than pretty JSON is the default.
- `find --limit` supports progressive narrowing.
- `explore` supports depth, focus, entry, and per-file symbol controls.
- `interface` is efficient; nearly all its output is useful interface content.
- Text mode provides meaningful size reductions.
- `impact` returns a purpose-built projection rather than raw ast-grep results.

## Recommended Implementation Order

1. Add stable compact projections for structural matches and outline items.
2. Add `--limit`, truncation metadata, and preferably cursors.
3. Make compact JSON the default and retain current payloads behind `--detail full`.
4. Remove `tree_text` and repeated absolute paths from compact `explore` output.
5. Reduce successful-envelope boilerplate.

The first three changes would yield the largest token savings without sacrificing reliable agent automation.
