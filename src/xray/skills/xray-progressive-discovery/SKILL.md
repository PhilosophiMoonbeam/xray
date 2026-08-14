# XRAY Progressive Discovery

Use this skill when an MCP client needs to inspect a repository with XRAY while keeping context small.

## Workflow

`search_tools` accepts a regular expression and returns at most 10 matches. Use
a focused literal or alternation such as `interface|signature`; a broad `.` can
hide later tools. Call one result through `call_tool` with its exact name and
arguments.

1. Map with `search_tools` using terms like `map`, then call `call_tool` with `name="explore_repo"`; use `entries` for file selection.
2. Find symbols with `search_tools` using terms like `symbol`, `function`, `class`, or `find`, then call `call_tool` with `name="find_symbol"`.
3. Read source contracts with `search_tools` using terms like `interface`, `signature`, `contract`, or `documentation`. Prefer `read_interface_structured` for typed hierarchy, documentation, visibility, and completeness; use `read_interface` for legacy text.
4. Assess likely symbol-name code references with `search_tools` using terms like `impact`, `usage`, or `reference`, then call `call_tool` with `name="what_breaks"` and pass the full symbol object returned from `find_symbol`.

## Guidance

- Start with absolute repository paths.
- Compact `explore_repo` entries are the default. Request `detail="full"` only when `tree_text` is needed for visual scanning.
- Keep `include_symbols` false for an initial map; enable it only when zooming into a focused directory.
- Python interfaces use enriched standard-library AST data. Other supported languages use ast-grep outlines and report completeness warnings.
- When a symbol map is noisy, pass `symbol_types` to `explore_repo` (for example `["class", "interface"]`) to keep only those top-level outline types.
- Preserve full symbol objects so impact analysis has path and line data.
- Treat `what_breaks` as a name-based reference search, not a type-aware caller, dependent, or dependency graph.
- Use `search_pattern` for arbitrary AST-aware queries. Compact matches retain useful captured metavariables without raw range trees.
- Structural reads return at most 50 items by default. Check `returned`, `total`, `total_exact`, and `truncated`; `total_exact=false` means a lower bound. Pass `next_cursor` back only for the identical root/query/scopes and unchanged source snapshot.
- Use `file_imports` and `file_exports` for compact, flattened immediate dependencies and public APIs.
- Use `detail="full"` only when raw ast-grep matches or outline wrappers are necessary.
- Use `scan_rules` to verify YAML-defined invariants. Set `fix=true` only when file mutation is intended; fixes apply to every match and do not support continuation afterward.
- For structural mutation, call read-only `plan_replacement`, review all preview edits, counts, paths, warnings, hashes, and `plan_digest`, then call destructive `apply_replacement` with the complete plan and an independently copied reviewed digest. Apply rejects drift before writing and rolls back already replaced files after a later failure. Pass `lang` whenever the pattern language is known.
- Keep `rewrite_pattern` only for explicit legacy all-match replacement. It is destructive and does not require plan confirmation. Pass `lang` whenever known so pattern-like configuration or documentation text is not also rewritten.
- Fetch `xray://workflow` for a longer reference when a client needs detailed examples.
