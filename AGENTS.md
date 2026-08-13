# XRAY Agent Index

XRAY is a Python code-intelligence CLI and MCP server. Root owns intent, risk,
Beads, allocation, adjudication, integration, delivery, and completion.
Repository policy, protected systems, CI when present, and humans retain their
own authority.

User, platform, and orchestrator instructions override this file. A closer
`AGENTS.override.md` or `AGENTS.md` overrides broader repository guidance only
for its subtree. No instruction grants credentials, production access,
destructive authority, remote mutation, merge, publication, or deployment.

## Instruction index

Read only the sources required by the current trigger. Descriptive documents
and examples do not override an authoritative source.

| Trigger | Read | Authority |
|---|---|---|
| Before planning or claiming work | [`PROJECT.md`](PROJECT.md), [`ARCHITECTURE.md`](ARCHITECTURE.md), and the applicable instruction chain | Readiness, commands, components, interfaces, resources, and project authority |
| After session start or context loss | Run `bd prime`; then inspect the ready frontier and active claims | Durable work, dependencies, blockers, and handoff |
| Before changing owned text | [`docs/repository-language-standard.md`](docs/repository-language-standard.md) | Vocabulary, strength, semantic density, and transformation evidence |
| Before implementation | [`docs/implementation-standard.md`](docs/implementation-standard.md) | Supported behavior, implementation, verification, and completion |
| Before routing or delegation | [`docs/agent-model-routing.md`](docs/agent-model-routing.md), then [`docs/agent-operations.md`](docs/agent-operations.md) | Routes, contracts, allocation, worktrees, evidence, adjudication, and delivery |
| Before integration, release, or destructive work | [`docs/agent-operations.md`](docs/agent-operations.md) and `PROJECT.md` | Reconciliation, rollback, protected gates, and cleanup |
| While adopting or updating the harness | [`docs/adoption-design-packet-v2.md`](docs/adoption-design-packet-v2.md), [`docs/ADAPTATION.md`](docs/ADAPTATION.md), and [`TEMPLATE_MANIFEST.md`](TEMPLATE_MANIFEST.md) | Active frozen design, procedure, and inventory |
| For product behavior or orientation | [`README.md`](README.md), then `ARCHITECTURE.md` | Public usage and component contracts |

## Readiness and scope

If `PROJECT.md` is not exactly `Status: READY`, edit only an explicitly
authorized harness, profile, architecture, validator, documentation, or
readiness-repair scope. Do not edit application source or guess a project
fact. Before editing, inventory applicable configuration, tests, CI, scripts,
permissions, worktrees, schemas, and instructions. Preserve unrelated state.
Make the smallest complete change and remove obsolete behavior within scope.

## Root and child boundaries

Root decides meaning and risk. It delegates execution, not authority. Use a
child only for concrete, bounded work when delegation saves a turn, enables
safe concurrency, or supplies risk-required independent evidence. Children do
not mutate Beads, coordinate peers, create descendants, widen scope,
self-approve, integrate, or deliver. Exact roles, models, efforts, and runtime
controls live in `.codex/config.toml` and `.codex/agents/*.toml`.

Only root mutates the canonical tracker through `bd -C ~/.beads-planning`.
Children read Beads with `bd --readonly`. Root claims a ready leaf before
implementation and records frozen design authority or exact
architecture-neutral authority. Hierarchy and priority do not create blocking
dependencies.

Every assignment supplies the Bead, outcome, authority, behavior, non-goals,
interfaces, invariants, compatibility, rollback, risk, base commit, worktree,
branch, writes, checks, resources, runtime, return schema, and task-specific
overrides. A missing or conflicting field stops the lane.

Concurrent writers require disjoint primary writes, generated outputs,
resources, branches, and clean root-created worktrees. Root plus at most three
children may run. At most three agents, including root, may write concurrently.
Root integrates one artifact at a time and keeps unintegrated work recoverable.

MultiAgentV2 has no V1 `close_agent` tool. Root may retain a completed child
for follow-up. When no follow-up is needed, root interrupts the completed lane.
Interruption marks the lane as relinquished but does not itself reclaim its
resident slot. At a full pool, the next spawn replaces the least-recently-used
unloadable relinquished resident. If replacement fails after every child lane
is relinquished, stop delegation and report the V2 residency failure.

Evidence is an exact artifact or command, exit status, material output,
environment, and artifact SHA. Reuse it only with unchanged artifact, inputs,
toolchain, and environment. A check proves only covered behavior; no findings
is not approval. Completion requires proof of every acceptance requirement and
no remaining required work.

Stop for ambiguous intent, contract conflict, required authority or scope
expansion, contradictory evidence, an unexplained regression, or a prohibited
action. After exactly two consecutive evidence-free technical hypotheses for
one unchanged failure key, use the breakthrough route in operations.

Root alone integrates locally. Without separate delivery authority, stop after
local verification. Commit, push, merge, release, deployment, GitHub mutation,
publication, credentials, production actions, and Beads Dolt push/pull remain
unauthorized.

## Project tool rules

Use the Beads skill and `bd prime` for durable context. Use Context7 for
current non-Codex library, framework, SDK, API, CLI, or cloud documentation;
use current official OpenAI documentation for Codex. Use Playwright for
browser inspection or verification only when browser behavior is in scope and
project authority supplies the application and command.

For Context7, run at most three commands:

```bash
npx ctx7@latest library <Official-Name> "<one precise concept>"
npx ctx7@latest docs <selected-/org/project[/version]> "<one precise concept>"
```

Resolve first unless an exact Context7 ID is supplied. Split unrelated
concepts, exclude secrets, and do not substitute model memory after a quota
failure; report `npx ctx7@latest login` or `CONTEXT7_API_KEY`. Skip lookup for
refactoring, original scripts, business logic, code review, and general
programming concepts.

Use `gh` for authorized GitHub pull requests, reviews, Actions, releases,
repository metadata, and issues; use `git` for local repository state. Never
infer remote-mutation authority. Run every Python-related command through `uv`,
including scripts, tests, builds, package operations, and temporary
dependencies; canonical commands live in `PROJECT.md`.

All shell operations must be non-interactive. Use `cp -f`, `mv -f`, `rm -f`,
`rm -rf`, and `cp -rf` instead of prompting forms; validate exact destructive
targets first. Use `scp -o BatchMode=yes` and `ssh -o BatchMode=yes`; use
`apt-get -y`; set `HOMEBREW_NO_AUTO_UPDATE=1` for `brew`. Do not target a home,
repository root, workspace root, unresolved variable, or broad glob with a
destructive command.

Changes to this index, Codex configuration, roles, hooks, validators, or
canonical gates require their synchronized transformation evidence, complete
diff review, strict configuration diagnosis when applicable, and
`git diff --check`. Record limitations instead of weakening a gate.
