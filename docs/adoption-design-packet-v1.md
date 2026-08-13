# XRAY Multi-AgentV2 Adoption Design Packet

Version: 1
Decision Bead: `xray-oep.1`
Status: FROZEN
Frozen: 2026-08-05

This packet is the material design authority for `xray-oep`. Root may replace it
only with a new version, digest, evidence record, and synchronized Beads update.
Implementation leaves may adapt prose and project facts but may not change the
behavior, interfaces, invariants, routes, authority, or compatibility decisions
below.

The companion `docs/adoption-design-packet-v1.sha256` contains the lowercase
SHA-256 of this file's exact bytes. Recompute with:

```bash
sha256sum docs/adoption-design-packet-v1.md
```

## Authority and provenance

| Item | Frozen evidence |
|---|---|
| Recipe repository | `/home/bbferko/repos/multi-agentV2_recipe` |
| Recipe commit | `b5643c9138985701d404688e21309e04d85a83ee` |
| Recipe tree | `542a1d9ee5592897042deb56ae311815231417dc` |
| Recipe branch | `main`, equal to `origin/main` |
| Recipe status | Exactly one unstaged tracked change: `AGENTS.md`; no staged or untracked paths |
| XRAY repository | `/home/bbferko/repos/xray` |
| XRAY base commit | `d96f0d668c077d2b04d351eaa5bd1abea5f7514f` |
| XRAY branch | `main`, tracking `origin/main` |
| XRAY pre-packet base status | Empty `git status --porcelain=v2 --untracked-files=all` at the frozen base |
| XRAY packet-artifact status | HEAD `d96f0d668c077d2b04d351eaa5bd1abea5f7514f`; `main` tracks `origin/main` at `+0 -0`; exactly the packet and companion are untracked, with no staged or modified paths |
| Recipe gate | `git diff --check` passed; no path other than `AGENTS.md` differs from the pinned recipe commit |
| Codex client | `codex-cli 0.146.0`; current according to `codex doctor` on 2026-08-05 |

The complete packet-artifact status is:

```text
# branch.oid d96f0d668c077d2b04d351eaa5bd1abea5f7514f
# branch.head main
# branch.upstream origin/main
# branch.ab +0 -0
? docs/adoption-design-packet-v1.md
? docs/adoption-design-packet-v1.sha256
```

The source repository's only dirty change is authoritative adoption input, not
an accidental base mutation. Its exact default unified patch is:

```diff
diff --git a/AGENTS.md b/AGENTS.md
index ab1b862..b33f684 100644
--- a/AGENTS.md
+++ b/AGENTS.md
@@ -75,6 +75,13 @@ and clean root-created worktrees. Root plus at most five children may run. At
 most three agents may write concurrently. Root integrates one artifact at a
 time and keeps unintegrated work recoverable.
 
+MultiAgentV2 intentionally omits the V1 `close_agent` tool. After collecting a
+child's response and direct-state evidence, root may retain the completed
+thread for follow-up. When the child pool is full, a replacement spawn must
+automatically evict the least-recently-used unloadable completed child. If a
+replacement spawn fails after every child is complete, stop delegation and
+report the V2 residency failure; interruption is not slot reclamation.
+
 Evidence is an exact artifact or `command + exit status + material output +
 artifact SHA`. Reuse it only with unchanged inputs, toolchain, environment,
 and artifact. A check proves only its covered behavior. No findings is not
```

Its exact evidence is:

| Artifact | SHA-256 |
|---|---|
| Pinned `AGENTS.md` | `d9ab52b4132aac582742d452adab126108776eaaa69d91198d71a524fdbc0049` |
| Working `AGENTS.md` | `a5eb9ae04616e0527a13603d224bd62cdec9a477bf6c42209debcba247f6cf3b` |
| Default binary-capable Git patch | `7f52f7eec8f1c7da48c8065bdff07c014ae276869dcd22298a3273acc51d1e1b` |
| Seven added byte-lines | `a927174b0f0b373f173cc7cee9f5f4173f19f98dad1bb75dfbd9e170876b0fd5` |

## Outcome and supported behavior

XRAY will use the recipe's lean Codex control plane while remaining the same
Python 3.10+ code-intelligence CLI and FastMCP server. The adopted harness must
provide:

- a compact root instruction index and truthful project/architecture authority;
- six bounded roles with one root-owned allocation and integration queue;
- one trusted SessionStart recovery composer for startup, resume, clear, and
  compact;
- project-owned Beads history with root-only mutation and child read-only access;
- objective recipe/readiness validators and canonical non-interactive gates;
- exact evidence, serial integration, conservative external delivery, and the
  V2 completed-thread residency rule above.

The adoption must preserve XRAY's `xray.cli.v2` compact JSON default, full/v1
compatibility, JSON/jq/full-symbol pipelines, no-YAML-output decision, path
containment, bounded results and cursors, documented CLI/MCP compatibility and
intentional surface differences, name-based impact semantics, rewrite and
`scan --fix` mutation safety, package entry points and data, Python 3.10+, and
optional `/tmp/.xray_cache` behavior.

## Non-goals

This adoption does not redesign product source, public schemas, CLI commands,
MCP tools, packaging, installers, reports, product skills, caches, or tests. It
does not add CI, a service, a product database, a YAML output mode, a harness
generator, a new installer, credentials, production access, deployment, or
remote delivery authority. It does not copy recipe `.git/` or `.beads/` state.

## Frozen decisions

| Topic | Decision |
|---|---|
| Trusted automation | Use `sandbox_mode = "danger-full-access"` and `approval_policy = "never"`. This removes local prompts but grants no credentials, destructive, production, Git delivery, Beads sync, publication, or deployment authority. |
| Features | Enable stable `multi_agent` and `hooks`; disable role web search. Current documentation lookup continues through official OpenAI docs or Context7 under repository instructions. |
| Root route | `gpt-5.6-sol`, reasoning `medium`. |
| Design/write routes | `sol_design` and `sol_write`: `gpt-5.6-sol`, `high`; `breakthrough_read`: `gpt-5.6-sol`, `xhigh`. |
| Conventional routes | `luna_read` and `luna_write`: `gpt-5.6-luna`, `max`. |
| Verification route | `terra_verify`: `gpt-5.6-terra`, `high`. |
| Route evidence | The current official Codex manual names Sol/Luna/Terra for these classes of work. `codex debug models` exposes all three to this account and includes every frozen effort; strict doctor passes the recipe config. |
| Role isolation | Every child profile sets `[agents] enabled = false`; children do not create descendants, coordinate peers, mutate Beads, integrate, or deliver. |
| Concurrency | Set `agents.max_concurrent_threads_per_session = 3`: at most three open child threads and root plus three total, matching this host's four-slot capacity. At most three agents, including root, may write concurrently. Concurrent writers require disjoint primary writes, branches, worktrees, resources, and generated outputs. |
| V2 residency | Retain completed child threads for follow-up. A replacement spawn relies on automatic LRU eviction of an unloadable completed child. Interruption is not reclamation; a failed replacement after all children complete stops delegation and is reported. |
| Integration | `main` is the integration branch. Root adjudicates and integrates one artifact at a time. |
| Delivery | Root may create local branches/worktrees and locally integrate within the user-authorized epic. Commit, push, merge, release, deployment, remote mutation, and Beads Dolt sync remain unauthorized unless separately granted. |
| Beads | Preserve XRAY identity, 169-issue history, memory, backups, and graph. Never initialize from or copy recipe tracker state. Root alone writes through the current dedicated planning checkout during migration; children use `bd --readonly`. Leaf `.5` must remove portable dependence on personal absolute paths while preserving history and must prove clean worktree/clone behavior locally. |
| Hook | Replace all legacy direct `bd codex-hook`, `PreCompact`, `PostCompact`, and `UserPromptSubmit` groups with one `SessionStart` matcher `startup|resume|clear|compact`, timeout 35 seconds, and context limit 2500. |
| Hook entry point | Use `uv run python "$(git rev-parse --show-toplevel)/.codex/session_start.py"` to satisfy XRAY's uv-only Python rule. The script invokes Beads read-only, uses bounded JSON, deterministic ordering, and graceful missing/malformed handling. |
| Claude | Retain Claude as a narrow client compatibility adapter with one read-only SessionStart Beads recovery command. `.claude/settings.json` owns mechanics only and cannot override `AGENTS.md`, `PROJECT.md`, `ARCHITECTURE.md`, Codex operations, or root authority. |
| CI | XRAY has no current `.github` workflow or other CI configuration. Do not invent CI. Local exact-SHA gates are authoritative until external CI is separately established. |
| Nested instructions | Add no nested `AGENTS.md` now: inspected subtrees have no distinct authority, commands, or invariants that justify one. Revisit only on evidence of a real subtree difference. |
| Examples | Keep the three recipe examples unchanged and explicitly non-authoritative. Their YAML-shaped assignment illustration is not XRAY CLI output and does not reopen the no-YAML decision. |
| Product README | Preserve the XRAY product README and add only concise links to the harness authority. Do not replace it with the recipe README. |
| Tracked SQLite | Remove only `.xray/xray.db`, `.xray/xray.db-shm`, and `.xray/xray.db-wal` after recorded identity hashes and dependency checks. XRAY supports no project database; `.xray/` becomes ignored. Do not remove any Beads database. |

## Interfaces, ownership, and dependencies

Root owns design freezing, Beads mutation, allocation, integration, final
qualification, readiness, closure, and any separately authorized delivery.
Implementation leaves own only their declared paths:

| Leaves | Primary owned paths |
|---|---|
| `.2` | `PROJECT.md` |
| `.3` | `ARCHITECTURE.md` |
| `.4` | `docs/ADAPTATION.md`, agent/implementation/language standards, transformation evidence, `TEMPLATE_MANIFEST.md`, examples, concise README links |
| `.5` | Existing XRAY `.beads` topology and `.agents/skills/beads/` only; no recipe tracker state |
| `.6` | Named `.xray` SQLite files and `.gitignore` |
| `.7` | Root `AGENTS.md` |
| `.8` | `.codex/config.toml` and exactly six `.codex/agents/*.toml` files |
| `.9` | `.codex/hooks.json` and `.codex/session_start.py` |
| `.10` | `.claude/settings.json` and its migration evidence |
| `.11` | `.codex/validate_agents.py` and `.codex/validate_project_readiness.py` |
| `.12` | `Makefile` and canonical gate composition |
| `.13`-`.15` | Read-mostly audit, qualification evidence, and final readiness metadata |

Preserved MCP identifiers are resource `xray://workflow`, prompt
`xray_discovery_plan`, skill `skill://xray-progressive-discovery/SKILL.md`, and
skill template `skill://xray-progressive-discovery/{path*}`. MCP retains its
search-first `search_tools`/`call_tool` exposure. CLI and MCP share underlying
operation semantics while retaining their documented argument, root-inference,
error, and presentation differences.

The Beads dependency graph is authoritative. `.1` precedes `.2`-`.6`; those
leaves unlock the later index, roles, hook, Claude, validators, runner, audit,
qualification, and readiness sequence. Parentage alone is not a blocker.

Synchronization edges are mandatory:

- route, effort, or role name: root config, role TOML, validator, standards,
  and affected examples;
- hook or permission: config, hook JSON/script, validator, and adaptation docs;
- thread ceiling: config, operations, and validator;
- commands/resources/delivery: `PROJECT.md`, Make targets, and closer authority;
- component contract: `ARCHITECTURE.md`, packet version, dependency edges, and
  affected instructions;
- language/implementation rule: its authority and transformation evidence.

## Migration matrix

`README.md` and `TEMPLATE_MANIFEST.md` are included explicitly because the
recipe validator requires them even though the source manifest omitted their
own Copy rows.

| Source or current path | Action | Result |
|---|---|---|
| Recipe `AGENTS.md` plus dirty V2 block; current `AGENTS.md` | Replace/adapt | Lean XRAY index with every current proposition retained, relocated, or explicitly removed; include V2 residency. |
| Recipe `PROJECT.md` | Add/adapt | XRAY facts, commands, authority, resources, and truthful `NOT_READY` until final qualification. |
| Recipe `ARCHITECTURE.md` | Add/replace placeholder | XRAY component, dependency, interface, compatibility, storage, and mutation map. |
| Recipe `.codex/config.toml`; current minimal config | Replace/adapt | Frozen root route, features, six registrations, and target-specific three-child ceiling. Do not add the non-public `features.multi_agent_v2` key. |
| Recipe `.codex/agents/*.toml` | Add, byte-identical | Exactly six frozen profiles; no legacy or extra role. |
| Recipe `.codex/hooks.json`; current legacy hooks | Replace/adapt | One SessionStart group and XRAY uv entry point. |
| Recipe `.codex/session_start.py` | Add/adapt | Bounded read-only XRAY Beads recovery and self-test. |
| Recipe `.codex/validate_agents.py` | Add/adapt | XRAY inventory, synchronized routes/hooks, negative cases, hygiene, and calibrated budgets. |
| Recipe `.codex/validate_project_readiness.py` | Add/adapt | Fail under `NOT_READY`; pass only with exact `READY`, complete project facts, and non-placeholder architecture. |
| Recipe/current `.agents/skills/beads/SKILL.md` | Replace/adapt | Compact workflow plus XRAY root mutation route and child read-only rules. |
| Recipe/current `.agents/skills/beads/agents/openai.yaml` | Replace, byte-identical | Keep synchronized UI metadata at SHA-256 `7748b82a366f6475ef784ccb0b47fab4fd48b3da06148eaccc6455b0ea1fc3d0`. |
| Recipe authoritative `docs/*.md` | Add/adapt | XRAY-owned standards and transformation evidence, with no guessed facts. |
| Recipe `examples/*` | Add, byte-identical | Non-authoritative examples; no YAML product behavior. |
| Recipe `Makefile`; no current Makefile | Add/adapt | Thin non-interactive harness, product, static, build, package, smoke, and diff gates. |
| Recipe `README.md`; current product README | Omit recipe body; adapt current | Preserve product documentation and add concise authority links. |
| Recipe `TEMPLATE_MANIFEST.md` | Add/adapt | Complete XRAY inventory including its own and README rows. |
| Recipe `.gitignore`; current `.gitignore` | Merge | Preserve build/test/reference/venv/lock policy; add harness, temp, and approved Beads ignores plus `.xray/`. |
| Recipe `.git/` and `.beads/` | Omit | Never transplant identity, history, remotes, hooks, backups, or runtime state. |
| Current XRAY product-local `.beads/` and routed `/home/bbferko/.beads-planning` | Preserve/normalize in `.5` | Back up first; retain the dedicated planning store as canonical history, preserve its project identity and 169-issue graph, migrate the no-YAML memory into it, replace personal absolute routing with local `~/.beads-planning` bootstrap metadata, retain recovery material through final qualification, keep children read-only, and perform no Dolt sync. |
| Current `.claude/settings.json` | Retain/adapt | Narrow read-only SessionStart compatibility only. |
| Current `.xray/xray.db*` | Remove named files | Obsolete generated state removed from Git after identity/dependency evidence. |
| Product `src/`, `tests/`, `test_samples/`, installers, config generator, `.reports/`, product skills, `pyproject.toml` | Preserve | No harness transformation; changes only if a later verified product regression demands a separately tracked repair. |

## Byte-invariant adoption set

Only the following recipe artifacts are required to remain byte-identical in
the initial candidate. Expected-change paths use semantic validators, focused
tests, and complete diffs instead of a broad preserve manifest.

| Path | SHA-256 at recipe commit |
|---|---|
| `.codex/agents/sol_design.toml` | `2936ac5c06af4472fa88fbcc78bf14d3336e1fb8de73fbf7945960083201ef38` |
| `.codex/agents/sol_write.toml` | `6ed26a090e514983340a6ed340a7317336fb721ee2d953a85097cb971a422d44` |
| `.codex/agents/breakthrough_read.toml` | `f0c8475387b0f8480353396818805293007aeb4b933682d79284abb9425f276e` |
| `.codex/agents/luna_read.toml` | `e744ed380b91f420e943beac3ab9eaee6e1a3c84b975059bd461b06289c0a730` |
| `.codex/agents/luna_write.toml` | `90e31a0ad9eaa7753a6cba32f510694cc61eaf6f954ca9d5c95c6eb90a5696b1` |
| `.codex/agents/terra_verify.toml` | `1314e94aba1d1f9cdaa8ac8fe99d2ce0e3e64fd65e8da8af2406ca07cc6d3fdd` |
| `.agents/skills/beads/agents/openai.yaml` | `7748b82a366f6475ef784ccb0b47fab4fd48b3da06148eaccc6455b0ea1fc3d0` |
| `examples/assignment-contracts.md` | `c1f74f994475d43814da986d76786b13db69727df86a1aed9405106003a2ca5c` |
| `examples/beads-dag.md` | `4d93442f678a36d5af93becfd32309b6bcded98124f199b2d484388f3fe037b1` |
| `examples/nested-AGENTS.md` | `89bb948cbb11dfb1c7563fce2c3fc16874ac644184effc4f6b82d2686b2eeced` |

The root config, hook, session composer, validators, Makefile, Beads skill,
prose, and ignore policy are expected adaptations and therefore are not byte
invariants. The root config changes only the child-thread ceiling from the
recipe's five to the target host's three while preserving the frozen routes,
features, permissions, and registrations.

## Beads and storage evidence

The current product checkout is configured as a contributor and its local
embedded store contains zero issues. Auto-routing sends current work to
`/home/bbferko/.beads-planning`, whose embedded store contains 169 issues and
the `xray-oep` graph.

The final topology is frozen as follows:

- The dedicated planning database `xray`, project ID
  `a6bbef53-dcc7-4ef4-8a72-a42b5f7e7c62`, remains canonical for XRAY work
  history and the epic. It remains a separate contributor-planning repository;
  `.5` does not move or merge it into the product-local database.
- The product-local zero-issue database, project ID
  `eab1612b-ea97-45c1-bdcc-e757b154450a`, remains noncanonical contributor
  metadata. It must not replace or absorb the planning history.
- Local contributor bootstrap uses `routing.mode=auto`, literal
  `routing.contributor=~/.beads-planning`, and
  `repos.additional=~/.beads-planning`. No portable runtime configuration,
  hook, or instruction contains `/home/bbferko` or another personal absolute
  path; provenance evidence may record the inspected host path. A fresh clone is configured
  non-interactively with `bd init --non-interactive --role contributor
  --setup-exclude --skip-agents` plus those local config values; the interactive
  `bd init --contributor` wizard is documentation context, not a canonical gate.
- The no-YAML memory is copied into the canonical planning database under its
  existing key and verified there before the product-local copy is treated as
  redundant. No issue history is re-imported or renumbered.
- The canonical planning database keeps no Dolt remote in this adoption, so
  remote synchronization is disabled pending separate authority. The
  product-local noncanonical store retains remote name `origin` at
  `git+https://github.com/PhilosophiMoonbeam/xray.git`. Its local YAML and
  direct `config get` currently expose that literal URL while the hydrated
  config listing exposes stale value `upstream`; `.5` normalizes both views to
  remote name `origin`. No push or pull is performed.
- Git hooks remain deliberately local. `.5` installs them with
  `bd hooks install --beads` and records relative `core.hooksPath=.beads/hooks`,
  never `/home/bbferko/...`. Fresh-clone verification repeats that bootstrap.
- A new pre-migration native backup of the canonical planning store is the
  authoritative recovery source. Existing product-local backups are preserved
  but noncanonical. The new backup and the untouched planning store are retained
  through `.15`; cleanup requires later explicit authority.

Before `.5` changes tracker configuration it must create the recoverable backup
and verify project IDs, issue counts, `xray-oep`, the no-YAML memory, remotes,
Git hooks, and complete statuses. Child worktrees must never receive mutation
authority.

The three tracked product SQLite artifacts are distinct from Beads. Frozen
pre-removal SHA-256 values are:

| Path | SHA-256 |
|---|---|
| `.xray/xray.db` | `c3a58c4b0266f83c0e80a5da11149e9e1c205b3472778e695f6df046f462048f` |
| `.xray/xray.db-shm` | `9d8ea1a73f008aaa7793323341485fce83f6726d403e3e56663457896dc5de56` |
| `.xray/xray.db-wal` | `332d516c2c53dbb542fe252fd52f2c4357cc662a17a3497aa0c5fba4aea38b90` |

## Resources, risk, and reversibility

Disjoint documentation/config leaves share no runtime port. Tests may share the
uv dependency cache but each writer uses a separate Git worktree. Product
tests create temporary repositories and `/tmp/.xray_cache`; MCP keeps bounded
in-process indexers and locks. Ast-grep subprocesses, installer/PATH changes,
uninstall, product rewrites, `scan --fix`, GitHub remotes, Beads remotes,
credentials, and external publication are sensitive or mutating and are not
implicitly authorized.

Primary risks are silent recipe drift, loss of tracker history, duplicate hook
authority, unsupported routes, stale legacy lifecycle behavior, product
contract regression, hidden-state leakage, and evidence invalidation after a
patch. The pinned commits, explicit dirty delta, small invariant set, frozen
write ownership, dependency graph, negative validators, backups, complete diff
review, and exact-SHA final qualification mitigate them.

Rollback prefers reverting serial local integration commits when such commits
are later authorized. For path-level rollback, restore modified or deleted base
paths from XRAY base `d96f0d668c077d2b04d351eaa5bd1abea5f7514f` and explicitly
remove every adoption-added path listed by the migration manifest, after
preserving any recoverable unintegrated patch. Restore the three named SQLite
files from the base if rollback occurs before delivery, and restore Beads only
from the verified pre-change backup. Never replace `.beads` from the recipe.
Retain dirty/unintegrated worktrees until root has either integrated or
explicitly rejected their recoverable patches.

## Acceptance and evidence contract

Each child must prove its own Bead criteria. The integrated candidate must then
pass recipe validation, expected `NOT_READY` readiness failure, all targeted
and full pytest gates, Ruff format check and lint, Pyright, Vulture, build,
packaging, CLI/MCP smoke, generated cleanliness, `git diff --check`, strict
Codex doctor, hook/parser/negative self-tests, semantic stale-artifact audit,
fresh root/worktree/session recovery, and final exact-SHA qualification.

`PROJECT.md` remains `Status: NOT_READY` until `.14` binds all evidence to one
unchanged candidate. `.15` may change it to exact `READY` only after every
required child is proven, Git and Beads state reconcile, no required work is
open or blocked, and rollback/residual risk are recorded. Local verification
does not grant commit, push, merge, sync, release, or deployment authority.

Current official documentation evidence comes from the Codex manual fetched
2026-08-05, especially Configuration Reference, Multi-agent operations,
Custom agents, Hooks, AGENTS.md, and Worktrees. Runtime evidence comes from
`codex debug models` and `codex -C /home/bbferko/repos/multi-agentV2_recipe
--strict-config doctor`, which completed with zero warnings and zero failures.
No material design decision remains unresolved in this version.
