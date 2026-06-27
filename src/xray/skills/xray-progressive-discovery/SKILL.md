# XRAY Progressive Discovery

Use this skill when an MCP client needs to inspect a repository with XRAY while keeping context small.

## Workflow

1. Map with `search_tools` using terms like `map`, then call `call_tool` with `name="explore_repo"`.
2. Find symbols with `search_tools` using terms like `symbol` or `find`, then call `find_symbol`.
3. Read contracts with `read_interface` before loading implementations.
4. Assess change impact with `what_breaks` by passing the full symbol object returned from `find_symbol`.

## Guidance

- Start with absolute repository paths.
- Keep `include_symbols` false for an initial map; enable it only when zooming into a focused directory.
- Preserve full symbol objects so impact analysis has path and line data.
- Fetch `xray://workflow` for a longer reference when a client needs detailed examples.
