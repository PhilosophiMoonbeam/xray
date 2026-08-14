# XRAY Project Profile

Status: READY

This profile is the project-level operating authority for the XRAY repository.
The adoption is `READY` after the exact integrated candidate completed the
qualification and readiness sequence defined by the frozen Design Packet.
This local readiness state does not grant commit, push, merge, synchronization,
release, deployment, or other delivery authority.

## Purpose

XRAY is a Python 3.10+ code-intelligence product for coding agents. It provides
the handwritten `xray` shell CLI and the `xray-mcp` FastMCP server so agents can
map repositories, find symbols, read interfaces, estimate name-based change
impact, and perform bounded structural operations without running a language
server. Product behavior and user contracts remain documented in `README.md`;
the harness adoption is governed by
`docs/adoption-design-packet-v2.md` and its recorded digest. Version 1 remains
frozen historical evidence.

## Architecture

The product path is CLI or MCP presentation -> shared models/presentation ->
`XRayIndexer` -> ast-grep, Git, ripgrep, and lightweight Python filesystem
operations. `ARCHITECTURE.md` is the authoritative component, interface,
compatibility, storage, and mutation map. `README.md`, `pyproject.toml`, and the
implementation under `src/xray/` remain product evidence; frozen Design Packet
version 2 is the active harness authority.

Preserved public interfaces include the `xray` and `xray-mcp` entry points,
compact `xray.cli.v2` JSON plus full/v1 compatibility, the intentional CLI/MCP
surface differences, opt-in compact `xray.cli.v3`, MCP's ranked search-first
`search_tools`/`call_tool` exposure,
resource `xray://workflow`, prompt `xray_discovery_plan`, skill
`skill://xray-progressive-discovery/SKILL.md`, and skill template
`skill://xray-progressive-discovery/{path*}`.

## Integration branch

`main` is the sole integration branch. Root adjudicates and integrates one
accepted artifact at a time. The frozen base is
`d96f0d668c077d2b04d351eaa5bd1abea5f7514f`; exact-SHA qualification must bind
the final candidate rather than reusing evidence from a different tree.

## Component ownership

Concurrent write assignments must have disjoint primary paths, worktrees,
generated outputs, and stateful resources. Product paths are preserved during
the harness adoption unless a separately tracked, evidence-backed regression
repair authorizes a product change.

| Component | Owned paths | Canonical specialist |
|---|---|---|
| Product CLI and JSON presentation | `src/xray/cli.py`, `src/xray/models.py`, `src/xray/presentation.py` | `sol_write` |
| MCP server and packaged MCP skill | `src/xray/mcp_server.py`, `src/xray/skills/` | `sol_write` |
| Indexing and ast-grep integration | `src/xray/core/`, `src/xray/lsp_config.json` (legacy evidence only) | `sol_write` |
| Packaging and installation | `pyproject.toml`, `install.sh`, `uninstall.sh`, `mcp-config-generator.py` | `luna_write` |
| Product verification | `tests/`, `test_samples/` | `terra_verify` |
| Product documentation and CLI skill | `README.md`, `.reports/`, `skills/xray-cli/` | `luna_write` |
| Readiness and architecture authority | `PROJECT.md`, `ARCHITECTURE.md` | `sol_design` |
| Standards, manifest, examples, and README authority links | `docs/`, `TEMPLATE_MANIFEST.md`, `examples/`, authorized harness links in `README.md` | `luna_write` |
| Beads topology and compact Beads skill | existing XRAY `.beads/`, dedicated planning checkout, `.agents/skills/beads/` | root only for tracker state; `luna_write` for skill files |
| Root instruction index | `AGENTS.md` | `sol_design` |
| Codex roles and root configuration | `.codex/config.toml`, `.codex/agents/` | `sol_write` |
| Session recovery | `.codex/hooks.json`, `.codex/session_start.py`, `.claude/settings.json` | `sol_write` |
| Validators and canonical runner | `.codex/validate_agents.py`, `.codex/validate_project_readiness.py`, `Makefile` | `sol_write` |
| Generated XRAY SQLite cleanup and ignore policy | `.xray/xray.db`, `.xray/xray.db-shm`, `.xray/xray.db-wal`, `.gitignore` | `luna_write` |

## Canonical commands

Run commands non-interactively from the repository root. Python commands use
`uv`. The canonical `Makefile` composes these commands and must not weaken
them.

| Purpose | Working directory | Command |
|---|---|---|
| Dependency setup | repository root | `uv sync --dev` |
| Fast targeted tests | repository root | `uv run pytest tests/test_models.py tests/test_ast_grep.py` |
| Packaging tests | repository root | `uv run pytest tests/test_packaging.py` |
| CLI/MCP smoke | repository root | `uv run pytest tests/test_mcp_compact.py tests/test_cli.py::test_package_scripts_keep_mcp_and_add_cli tests/test_cli.py::test_mcp_tool_surface_is_search_first_with_compact_metadata tests/test_cli.py::test_mcp_workflow_guidance_is_available_on_demand` |
| Ruff format check | repository root | `uv run ruff format --check .` |
| Ruff lint | repository root | `uv run ruff check .` |
| Pyright | repository root | `uv run pyright` |
| Vulture | repository root | `uv run vulture` |
| Full test suite | repository root | `uv run pytest` |
| Build and package | repository root | `uv build` |
| CLI live smoke | repository root | `uv run xray --version && uv run xray explore . --max-depth 1` |
| Generated-file cleanliness | repository root | `git diff --check && git status --porcelain=v1 --untracked-files=all` |

XRAY has no tracked generated source that must be regenerated. `uv build`
creates ignored `build/` and `dist/` artifacts; tests use temporary directories
and may use ignored Python/test caches. The cleanliness command is therefore an
inspection gate: its status output must contain only the explicitly authorized
adoption paths for the candidate, with no unexplained generated or modified
file. An empty status is required for a committed exact-SHA qualification when
commit authority is later granted.

Resolved qualification gap: on 2026-08-05, `uv sync --dev` resolved Ruff 0.16.1
from the declared `ruff>=0.14.0` range, exposing 11 existing `PLR0917`
violations. The tracked compatibility repair `xray-oep.16` documented the
current-rule decision, preserved established signatures, added the narrow rule
exclusion and packaging assertion, and passed the complete static, test, build,
and diff gate set. This evidence removes that specific blocker but does not make
the adoption READY before final exact-candidate qualification.

## Delivery authority

Root alone allocates work, mutates or closes Beads, creates local branches and
worktrees, adjudicates child output, integrates accepted artifacts serially,
runs final qualification, and changes readiness. Children inspect Beads with
`bd --readonly`; they do not claim, update, create, link, close, back up, route,
or synchronize tracker state.

The user-authorized epic permits root to create local branches/worktrees and
perform local integration. Commit, push, merge, release, deployment, GitHub
mutation, publication, and Beads Dolt push/pull remain unauthorized unless the
user separately grants them. A passing local gate never expands that authority.

## External and shared resources

- No fixed runtime port, service, emulator, device, production account, or
  deployment environment is required for the local gates.
- Each writer uses an isolated Git worktree and disjoint primary write set.
- Worktrees may share uv's dependency/download cache; dependency installation
  must remain project-local through uv and must not modify product installers.
- Tests create temporary repositories and files. Symbol skeletons and inventory
  may be cached under `/tmp/.xray_cache/{root_hash}-{git_commit}/symbols.json`
  and `inventory.json`; the root hash
  prevents same-commit repositories from sharing entries, and writes are
  atomic. Do not delete another worktree's active cache.
- XRAY launches ast-grep, Git, and ripgrep subprocesses on demand. Avoid
  unbounded concurrent scans; preserve their configured timeouts and output
  bounds.
- MCP keeps a bounded in-process indexer cache (default 32, configurable by
  `XRAY_MCP_INDEXER_CACHE_LIMIT`) with per-root locks. Separate processes do not
  share that in-memory cache or any listening port for the canonical tests.
- The canonical Beads history remains in the dedicated local planning checkout;
  only root may write it. The product checkout's zero-issue database is
  noncanonical contributor metadata during migration.

## Sensitive and destructive operations

- `xray rewrite` / MCP `rewrite_pattern` modifies every structural match in the
  selected root. The reporting limit does not limit edits; pass a language when
  known and inspect the full worktree afterward.
- `xray scan --fix` applies every configured fix and cannot continue against the
  changed result set. MCP `scan_rules` is read-only; guarded MCP rule mutation
  uses `apply_rule_fixes` with a reviewed plan and digest.
- `install.sh` may download uv, use network and Git, delete/reclone
  `$HOME/.xray`, force-install the uv tool, and update shell `PATH`.
- `uninstall.sh` uninstalls the uv tool and recursively deletes `$HOME/.xray`.
  Neither installer is a qualification command.
- Git remote operations, GitHub CLI mutations, credentials, releases,
  publication, production access, and deployment require separate authority.
- Beads routing, backup/restore, memory mutation, database changes, hook
  installation, and Dolt remotes are root-only. Push and pull are not authorized
  by this profile.
- The three tracked `.xray/xray.db*` files are obsolete product-index state, not
  Beads. Only the specifically assigned cleanup leaf may remove them after the
  frozen identity/dependency evidence; no Beads database may be removed.
- Cache cleanup, forceful file operations, and rollback must use exact validated
  paths. Do not target a home, repository, workspace root, or unresolved glob.

## Required nested instructions

None. The tracked base contains only the root `AGENTS.md`, and inspection found
no subtree with distinct authority, commands, or invariants that justifies a
nested `AGENTS.md` or `AGENTS.override.md`. Add one only when evidence establishes
a real subtree-specific rule; examples of nested instructions remain
non-authoritative.

## CI qualification

XRAY has no current `.github` workflow or other CI configuration. Do not invent
or imply a remote CI gate. Until CI is separately established, root must run the
canonical local commands above against one unchanged candidate, preserve exact
command/exit/material-output evidence, verify the complete diff and Beads state,
and bind final qualification to the exact commit or tree SHA. CI absence grants
no push, merge, release, synchronization, or deployment authority.

## Compatibility, risks, and rollback

The adoption preserves Python 3.10+, package scripts/data, JSON-first and
no-YAML-output contracts, path containment, result bounds/cursors, name-based
impact semantics, mutation warnings, product skills, installers, caches, tests,
and documented CLI/MCP compatibility with intentional surface differences. It
does not turn XRAY into an LSP client, service, project database, type-aware
dependency graph, or generated FastMCP CLI.

Primary project-profile risks are stale commands, silent product-contract
changes, duplicate hook authority, tracker-history loss, hidden generated state,
and evidence reused after the candidate changes. Exact commands, frozen
ownership, complete status/diff inspection, Beads backup and root-only mutation,
and exact-SHA qualification mitigate them.

Rollback prefers reverting authorized serial integration commits. Without such
commits, restore modified/deleted base paths from
`d96f0d668c077d2b04d351eaa5bd1abea5f7514f`, explicitly remove adoption-added
paths listed by the migration manifest after preserving recoverable patches,
restore the named SQLite files from that base when applicable, and restore Beads
only from its verified pre-change backup. Never restore tracker state from the
recipe.

## Evidence

- Product purpose, commands, contracts, caches, and limitations: `README.md`,
  `pyproject.toml`, `src/xray/`, and `tests/` at the frozen XRAY base.
- Adoption decisions, ownership, resources, non-goals, and rollback:
  `docs/adoption-design-packet-v2.md`, SHA-256
  `b762310d0409496f429f409c0504f86162304f168d67828f905a16b082fabd63`.
  Version 1 remains frozen historical adoption evidence.
- Tracker criteria and dependencies: `bd --readonly show xray-oep.2 --json`.
- Git facts: `git rev-parse HEAD`, `git branch --show-current`,
  `git status --porcelain=v2 --untracked-files=all`, and
  `git ls-tree -r --name-only`.
