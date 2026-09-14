# XRAY Project Profile

Status: READY

This is XRAY's project-level operating authority.
`Status: READY` records a usable local harness and does not certify product
qualification or grant delivery authority.

## Operating mode

Development Sprint is the current default. Main may select a bounded Sprint
task without a qualification ceremony, frozen packet, exhaustive assignment
fields, mandatory specialist or reviewer chain, transformation or count
attestation, or I0/I5 or W0-W6 qualification.

The XRAY next-major I5 qualification is explicitly paused and deactivated. I5
acceptance has not occurred, and neither this file, `CONTINUE.md`, Beads,
historical packets, rejected methods, old commands, nor worker availability
accepts or reactivates it. The preserved next-major design packets v1-v4,
adjudicated method requirements, and rejected evidence remain truthful
historical and recovery material. Resumption would require Main to record a
separately selected qualification outcome naming its assurance objective,
acceptance contract, candidate, and authority before any qualification action.

This mode supersedes standing process obligations inherited from adoption
packets, next-major instructions, and older handoffs when they conflict with
current Sprint work. Product behavior, compatibility, authorization,
containment, data preservation, truthful mutation outcomes, and delivery limits
remain unchanged. Frozen packets and historical evidence retain their bytes and
meaning; their exhaustive procedures are not current Sprint authority.

## Purpose

XRAY 1.0.0 is a Python 3.10+ code-intelligence product for coding agents.
The handwritten `xray` shell CLI and `xray-mcp` FastMCP stdio server expose
exactly eleven repository operations: `map`, `find`, `interface`, `read`,
`search`, `impact`, `capabilities`, `change_plan`, `change_refine`,
`change_verify`, and `change_apply`. They map repositories, capture bounded
source and interfaces, report unresolved name occurrences, search selected
inputs, and perform reviewed structural changes without a language-server
process.

Product and user contracts remain in `README.md`, `ARCHITECTURE.md`, and
`src/xray/`. Historical adoption and next-major packets remain preserved
evidence; a separately selected qualification outcome would identify when a
named acceptance contract applies. Routine implementation, delegation,
evidence, and completion rules live in the current standards linked from
`AGENTS.md`.

## Architecture

The product path is CLI or MCP presentation -> shared models/presentation ->
application operations -> repository capture and analysis -> ast-grep,
filesystem, and bounded subprocess operations. `ARCHITECTURE.md` is the
authoritative component, interface, compatibility, storage, and mutation map.
`xray.v1` is the unified transport-neutral result envelope and
`xray.change.v1` is the complete reviewed change-plan artifact.

The CLI uses explicit `ROOT` values and the current `map`, `find`, `interface`,
`read`, `impact`, `search`, `change`, `capabilities`, and `skill install`
grammar. FastMCP exposes exactly `search_tools` and `call_tool`; discovery
returns closed call-ready contracts and calls carry no embedded operation
selector or custom frame. The standard resource `xray://workflow`, prompt
`xray_discovery_plan`, and packaged skill resources remain supported.

All source, rule, config, and reference paths are contained by the explicit
root. Requests, cursors, references, source capture, cache artifacts, and
guarded plans are bounded at their owning components. Current docs and tests
are the authority for implemented behavior; no future design packet silently
advertises an unimplemented operation.

## Integration branch

`main` is the integration branch. Main adjudicates and integrates accepted
artifacts serially. Exact-tree or exact-SHA qualification is permitted only
after a separately selected qualification outcome names its milestone and
contract; it must bind the candidate being qualified rather than reuse evidence
from another tree.

## Component ownership

Concurrent writes require disjoint primary paths, generated outputs, and
stateful resources. Use a worktree when it provides needed isolation; it is not
a routine paperwork requirement. Product paths remain owned by product owners,
while Main governs native OMP paths under the scoped governance contract.

| Component | Owned paths | Current allocation |
|---|---|---|
| Product CLI and JSON presentation | `src/xray/cli.py`, `src/xray/models.py`, `src/xray/presentation.py` | Main; stock OMP worker only when Main delegates |
| MCP server and packaged MCP skill | `src/xray/mcp_server.py`, `src/xray/skills/` | Main; stock OMP worker only when Main delegates |
| Indexing and ast-grep integration | `src/xray/core/` | Main; stock OMP worker only when Main delegates |
| Packaging and installation | `pyproject.toml`, `install.sh`, `uninstall.sh`, `mcp-config-generator.py` | Main; stock OMP worker only when Main delegates |
| Product verification | `tests/`, `test_samples/` | Main; stock OMP worker only when Main delegates |
| Product documentation and CLI skill | `README.md`, `.reports/`, `skills/xray-cli/` | Main; stock OMP worker only when Main delegates |
| Readiness and architecture authority | `PROJECT.md`, `ARCHITECTURE.md` | Main; planner only for P1-P4 |
| Standards, manifest, examples, and README authority links | `docs/`, `TEMPLATE_MANIFEST.md`, `examples/`, authorized harness links in `README.md` | Main; stock OMP worker only when Main delegates |
| Beads topology and compact Beads skill | existing XRAY `.beads/`, dedicated planning checkout, `.agents/skills/beads/` | Main only for tracker state; stock OMP worker read-only for cited context |
| Main instruction index | `AGENTS.md` | Main |
| Native OMP project layer | `.omp/config.yml`, `.omp/AGENTS.md`, `.omp/APPEND_SYSTEM.md` | Main |
| Session recovery and handoff | `CONTINUE.md` | Main |
| Validators and canonical runner | `.omp/validate.py`, `.omp/validate_project_readiness.py`, `Makefile` | Main |
| Generated XRAY SQLite cleanup and ignore policy | `.xray/xray.db`, `.xray/xray.db-shm`, `.xray/xray.db-wal`, `.gitignore` | Main; stock OMP worker only when Main delegates |

## Canonical command catalog

Run commands non-interactively from the repository root. Python commands use
`uv`. These are available scoped tools, not a requirement to execute every row
for every change. Select changed-path tests, relevant static checks, and the
narrowest real runtime smoke for the active mode and affected transport.

| Purpose | Working directory | Command or expectation |
|---|---|---|
| Dependency setup | repository root | `uv sync --dev` |
| Focused behavior tests | repository root | Select existing tests covering changed behavior and boundaries. |
| Relevant static check | repository root | `uv run ruff check <changed paths>` or the applicable project check. |
| Packaging check | repository root | `uv run pytest tests/test_packaging.py` when metadata, dependencies, entry points, installers, or resources change. |
| CLI adapter checks | repository root | Existing CLI tests are adapter evidence; they are not a real subprocess smoke for an unrelated path. |
| CLI live smoke | repository root | Launch `uv run xray` against an explicit small fixture or authorized root and exercise the changed operation. `uv run xray --version` and `uv run xray map . --depth 1` are launch examples only. |
| MCP stdio smoke | repository root | When MCP or shared behavior is affected, launch `uv run xray-mcp` as an actual stdio child with a throwaway client, initialize, discover the two adapter tools, and call the changed operation. |
| Broad test suite | repository root | `uv run pytest` is an explicit broad check, not a routine Sprint gate. |
| Build and package | repository root | `uv build` when packaging or distribution behavior is affected. |
| Paused I5 qualification | repository root | No current qualification command or ceremony. Main may act only after a separately selected qualification outcome names the contract, candidate, and authority. |
| Native OMP inventory | repository root | `omp agents unpack --dir <isolated temporary directory> --json` for the bundled-role inventory only. |
| OMP project validator | repository root | `uv run python .omp/validate.py` for the empty native project layer and harness inventory. |
| Factual readiness validator | repository root | `uv run python .omp/validate_project_readiness.py` for repository readiness facts without prose-size quotas. |

XRAY has no tracked generated source that must be regenerated. `uv build`
creates ignored `build/` and `dist/` artifacts; tests use temporary directories
and may use ignored Python/test caches. Broad checks remain explicit tools and
do not activate or accept the paused I5 milestone.

The native OMP project layer is intentionally empty and declarative:
`.omp/config.yml` is `{}`, `.omp/AGENTS.md` imports `AGENTS.md` and
`PROJECT.md`, and `.omp/APPEND_SYSTEM.md` defines only planner/Main
allocation. `uv run python .omp/validate.py` rejects any legacy `.codex`
surface, a populated or symlinked custom `.omp/agents` directory, or a missing
bundled stock role; it also checks the required native inventory. The factual
readiness validator retains `Status: READY`, required sections, links, release
identity, and inactive-surface checks without prose-size quotas. These checks
grant no credentials or delivery authority.

Resolved qualification gap: on 2026-08-05, `uv sync --dev` resolved Ruff 0.16.1
from `ruff>=0.14.0`, exposing 11 existing `PLR0917` violations. Repair
`xray-oep.16` preserved signatures, added the narrow exclusion and packaging
assertion, and passed static, test, build, and diff gates. This historical
observation records one repaired Ruff blocker; `Status: READY` does not certify
pending product qualification or waive any product invariant.

## Delivery authority

Main owns intent, risk, allocation, integration, and completion. Only Main
mutates or closes Beads, and only Main may create local branches or worktrees
when needed. A bounded Sprint task may proceed without a Bead; use the
canonical planning store for durable multi-session work, dependencies,
blockers, and handoff. Stock OMP workers read Beads with `bd --readonly` and do
not claim, create, update, link, close, back up, route, or synchronize tracker
state.

Commit, push, merge, release, deployment, GitHub mutation, publication, and
Beads Dolt push/pull remain unauthorized unless Main receives separate
authority. A passing check or qualification result never expands that
authority.

## External and shared resources

- XRAY has no tailnet service, container deployment, PostgreSQL/database
  product, fixed runtime port, emulator, device, production account, or
  deployment environment required for local work.
- Real focused proof uses a local CLI process and, when MCP or shared behavior
  is affected, an actual standard-stdio `xray-mcp` child. An in-process client
  test does not substitute for transport launch proof.
- Worktrees may share uv's dependency/download cache; use an isolated worktree
  only when concurrent state or path overlap makes it useful. Dependency
  installation remains project-local through uv.
- Tests create temporary repositories and files. `DerivedCache` may use the
  platform cache directory, typically `~/.cache/xray/derived` on Linux; cache
  is optional, bounded, and expendable. Cache loss changes performance, not
  product truth.
- Each rooted operation constructs its own indexer from the captured root. MCP
  admission bounds active operations and rejects overlapping same-root work; it
  retains no indexer cache and opens no listening service. Separate processes
  do not share state.
- XRAY launches ast-grep and other subprocesses on demand through bounded
  wrappers. Preserve configured request limits, timeouts, output bounds, and
  error classification.
- The canonical Beads history remains in the dedicated local planning
  checkout; only Main may write it. The product checkout's zero-issue database
  is noncanonical contributor metadata during migration.

## Sensitive and destructive operations

- `change plan`, `change refine`, and `change verify` are read-only. Only
  `change apply` can mutate source, and it requires a complete reviewed
  `xray.change.v1` plan plus an independently retained digest.
- Apply checks source identity, selection, bounds, file modes, preimages,
  postimages, and syntax before writes. Caught failures attempt
  conflict-preserving rollback, but multi-file apply is not atomic. Process
  interruption can leave partial files; inspect the worktree and restore from
  a known baseline.
- Rule and config inputs are closed and contained. Unknown keys, multiple
  documents, directory input, symlinks, ambient configuration, custom
  grammars, and external dependencies are rejected.
- `install.sh` accepts only an explicitly selected local checkout (invoked
  script or `--checkout DIRECTORY`); it may bootstrap uv/dependencies, replace
  the uv tool, update `PATH`, and never select/mutate XRAY source via
  Git/network. Remote one-line installation is deferred.
- `uninstall.sh` retains existing behavior: it uninstalls uv and recursively
  deletes `$HOME/.xray`; it is not qualification or an inverse for an
  explicitly selected checkout.
- Git remote operations, GitHub CLI mutations, credentials, releases,
  publication, production access, and deployment require separate authority.
- Beads routing, backup/restore, memory mutation, database changes, tracker
  automation installation, and Dolt remotes are Main-only. Push and pull are not
  authorized by this profile.
- The three tracked `.xray/xray.db*` files are obsolete product-index state, not
  Beads. Only the specifically assigned cleanup leaf may remove them after the
  frozen identity/dependency evidence; no Beads database may be removed.
- Cache cleanup, forceful file operations, and rollback must use exact validated
  paths. Do not target a home, repository, workspace root, or unresolved glob.

## Required nested instructions

None. The tracked base contains only `AGENTS.md`, and inspection found no
subtree with distinct authority, commands, or invariants that justifies a
nested `AGENTS.md` or `AGENTS.override.md`. Add one only when evidence
establishes a real subtree-specific rule; examples of nested instructions
remain non-authoritative.

## CI and paused qualification

XRAY has no current `.github` workflow or other CI configuration. Do not invent
or imply a remote CI gate. The command catalog above supplies focused Sprint
checks and optional broad checks. I5 qualification is paused and deactivated:
no current packet gate, population, exact-candidate ceremony, replay, or
independent qualification review is authorized. A separately selected outcome
must name the milestone, assurance objective, acceptance contract, candidate,
authority, and applicable evidence before any such work resumes. Historical
qualification evidence is not current proof or acceptance.

Local success never authorizes commit, push, merge, release, synchronization,
publication, deployment, or protected delivery.

## Compatibility, risks, and rollback

The current product baseline is XRAY 1.0.0: Python 3.10+, package scripts and
data, unified `xray.v1` JSON, `xray.change.v1` guarded plans, standard stdio
MCP, exactly eleven operations, exactly two adapter tools, repository
containment, bounded results and cursors, unresolved name-based impact,
content-derived optional caches, packaged skills, and explicit installers.
YAML remains selected rule/config input only and is never product output.
XRAY does not provide a language server, type-aware dependency graph, daemon,
project database, automatic commits, or background recovery service.

For routine work, address stale commands, silent product-contract changes,
duplicate authority, tracker-history loss, hidden generated state, and evidence
reused after a candidate changes with focused review and the smallest useful
additional safeguard. Escalate a trust-boundary, source-mutation,
persistent-data, compatibility, package, or outcome-ambiguous change to the
proportional specialist, planner, review, or recovery step named by operations.

Rollback uses the actual pre-change state or an authorized serial integration
boundary, not the historical adoption base. Back up before a real destructive
or persistent-data transition and preserve recoverable dirty state. Use exact
validated paths for cache cleanup, forceful file operations, and restoration;
never target a home, repository root, workspace root, or unresolved glob.
Restore Beads only from a verified backup when Main is authorized to mutate it;
never restore tracker state from a recipe.

## Evidence

- Product purpose, commands, contracts, caches, and limitations: `README.md`,
  `ARCHITECTURE.md`, `pyproject.toml`, `src/xray/`, and affected tests at the
  implemented 1.0.0 candidate.
- Historical adoption and next-major decisions: the preserved packet files and
  their companions. They are not routine Sprint authority or current proof
  unless Main separately selects a named qualification outcome.
- Durable work, dependencies, blockers, and handoff: the canonical Beads store
  through Main-authorized operations. A Bead is not required for each local
  question, edit, hypothesis, or test.
- Routine completion evidence: actual changed-path checks, relevant static
  checks, focused CLI/MCP smoke when affected, consumer/documentation
  consistency, material risks, and limitations. Record the command or scenario
  and result in the final report or existing durable work item.
- Exact artifact identity, hashes, complete maps, and attestation ledgers are
  required only by a product contract or an explicitly activated assurance
  milestone. This governance cutover does not run that workflow.
