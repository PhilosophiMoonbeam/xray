# XRAY Progressive Discovery

Use this skill when an MCP client needs to inspect a repository with XRAY while keeping context small.

## Workflow

1. Map with `search_tools` using terms like `map`, then call `call_tool` with `name="explore_repo"`; use `entries` for file selection.
2. Find symbols with `search_tools` using terms like `symbol`, `function`, `class`, or `find`, then call `call_tool` with `name="find_symbol"`.
3. Read contracts with `search_tools` using terms like `interface`, `signature`, `contract`, or `docstring`, then call `call_tool` with `name="read_interface"` before loading implementations.
4. Assess likely symbol-name code references with `search_tools` using terms like `impact`, `usage`, or `reference`, then call `call_tool` with `name="what_breaks"` and pass the full symbol object returned from `find_symbol`.

## Guidance

- Start with absolute repository paths.
- Use `tree_text` only for visual scanning.
- Keep `include_symbols` false for an initial map; enable it only when zooming into a focused directory.
- When a symbol map is noisy, pass `symbol_types` to `explore_repo` (for example `["class", "interface"]`) to keep only those top-level outline types.
- Preserve full symbol objects so impact analysis has path and line data.
- Treat `what_breaks` as a name-based reference search, not a type-aware caller, dependent, or dependency graph.
- Use `search_pattern` for arbitrary AST-aware queries; captured metavariables are returned in match JSON.
- Use `file_imports` and `file_exports` for immediate file dependencies and public APIs.
- Use `scan_rules` to verify YAML-defined invariants. Set `fix=true` only when file mutation is intended.
- Use `rewrite_pattern` only when structural in-place replacement is intended; it is a destructive tool.
- Fetch `xray://workflow` for a longer reference when a client needs detailed examples.
