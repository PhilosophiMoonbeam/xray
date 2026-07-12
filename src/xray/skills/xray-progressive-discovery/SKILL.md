# XRAY Progressive Discovery

Use this skill when an MCP client needs to inspect a repository with XRAY while keeping context small.

## Workflow

1. Map with `search_tools` using terms like `map`, then call `call_tool` with `name="explore_repo"`; use `entries` for file selection.
2. Find symbols with `search_tools` using terms like `symbol`, `function`, `class`, or `find`, then call `call_tool` with `name="find_symbol"`.
3. Read contracts with `search_tools` using terms like `interface`, `signature`, `contract`, or `docstring`, then call `call_tool` with `name="read_interface"` before loading implementations.
4. Assess likely symbol-name code references with `search_tools` using terms like `impact`, `usage`, or `reference`, then call `call_tool` with `name="what_breaks"` and pass the full symbol object returned from `find_symbol`.

## Guidance

- Start with absolute repository paths.
- Compact `explore_repo` entries are the default. Request `detail="full"` only when `tree_text` is needed for visual scanning.
- Keep `include_symbols` false for an initial map; enable it only when zooming into a focused directory.
- When a symbol map is noisy, pass `symbol_types` to `explore_repo` (for example `["class", "interface"]`) to keep only those top-level outline types.
- Preserve full symbol objects so impact analysis has path and line data.
- Treat `what_breaks` as a name-based reference search, not a type-aware caller, dependent, or dependency graph.
- Use `search_pattern` for arbitrary AST-aware queries. Compact matches retain useful captured metavariables without raw range trees.
- Structural reads return at most 50 items by default. Check `returned`, `total`, and `truncated`; pass `next_cursor` back as `cursor` only for the identical root and query.
- Use `file_imports` and `file_exports` for compact, flattened immediate dependencies and public APIs.
- Use `detail="full"` only when raw ast-grep matches or outline wrappers are necessary.
- Use `scan_rules` to verify YAML-defined invariants. Set `fix=true` only when file mutation is intended; fixes apply to every match and do not support continuation afterward.
- Use `rewrite_pattern` only when structural in-place replacement is intended. It is destructive, applies every match, and returns a compact summary by default. Pass `lang` whenever the target language is known so pattern-like text in configuration or documentation is not also rewritten.
- Fetch `xray://workflow` for a longer reference when a client needs detailed examples.
