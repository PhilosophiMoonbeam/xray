# Installed XRAY CLI 0.8.3 dogfood report

Date: 2026-07-12

## Scope

Dogfood-tested the installed executable at `/root/.local/bin/xray` (resolved to
`/root/.local/share/uv/tools/xray/bin/xray`) by following the installed
`xray-cli` skill. `uv tool list` reported `xray v0.8.3` with the `xray` and
`xray-mcp` entry points.

All tests used the installed `xray` command, not `uv run xray`. Mutating tests
ran against disposable fixture copies outside the worktree.

## Coverage and results

| Feature | Live coverage | Result |
| --- | --- | --- |
| Root CLI | `--version`, `--help`, missing command | Pass |
| `explore` | compact/full JSON, text, pretty, depth, symbols, `--symbols` alias, focus, symbol type, per-file symbol cap, entry cap/truncation | Pass |
| `map` | alias behavior and `invoked_as: "map"` | Pass |
| `find` | fuzzy query, limit, minimum score, JSON/text/pretty, complete symbol object | Pass |
| `interface` | relative and absolute in-root paths, JSON/text/pretty | Pass |
| `impact` | `--symbol-json`, stdin and file `--symbol-file`, manual symbol fields, context lines, JSON/text/pretty | Pass |
| `search` | explicit and inferred language, compact/full/text/pretty, limits, continuation, query-bound cursor | Pass |
| `rewrite` | explicit and inferred language, compact/full/text/pretty, limit reporting, all-match mutation | Pass |
| `scan` | rule file, compact/full/text/pretty, limit, continuation, `--fix`, all-match mutation | Pass |
| `imports` | compact/full/text/pretty, limit and continuation | Pass |
| `exports` | compact/full/text/pretty, limit and continuation | Pass |
| Safety/errors | outside-root paths, malformed symbol JSON, incomplete manual symbols, invalid ast-grep pattern, invalid cursor, mismatched cursor, cursor with fix, invalid numeric bounds, unsupported YAML output | Pass |
| Exit codes | success `0`, runtime command failure `1`, parse/validation failure `2`; JSON and text errors | Pass |

Pagination was exercised with multi-page search, scan, import, and export
results. Compact structural envelopes reported consistent `returned`, `total`,
`truncated`, and `next_cursor` fields. Full detail retained upstream ranges and
outline wrappers. Rewrite and scan-fix limits bounded only returned diagnostics;
all four fixture call sites were modified across both source files.

## Findings

No CLI defect was found.

Mutation precision depends on language scoping. A rewrite without `--lang`
correctly used ast-grep inference, but its broad repository scan also matched
the pattern text embedded in the fixture YAML rule, reporting five matches in
three files instead of four code matches in two files. Agents should pass
`-l/--lang` for mutation commands whenever the target language is known. This
is consistent with the installed skill's structural examples, which specify
`-l python` for search; mutation examples would benefit from the same explicit
language habit when a repository contains configuration or documentation with
pattern-like text.

Resolution: agent-facing CLI and MCP guidance now requires an explicit language
whenever the rewrite target language is known. An adversarial regression test
and a repeat dogfood run against the installed executable prove a Python-scoped
rewrite changes Python call sites without changing the same pattern text in
YAML. A fresh-agent forward test independently selected the language-scoped
command and preserved the YAML fixture. The repository and installed CLI skill
copies are byte-identical, and the force-installed package contains the updated
CLI help, MCP tool hint, and MCP skill guidance.

## Regression verification

- `uv run pytest -q`: 136 passed
- `uv run ruff check .`: all checks passed
- Worktree fixtures removed after testing
