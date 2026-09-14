# Harness Maintenance

XRAY uses stock OMP roles and native configuration. The project
`.omp/config.yml` remains an empty mapping; the active OMP profile and runtime
determine bundled-agent behavior in effect, including models, reasoning,
providers, retry behavior, and task defaults. An empty project mapping does not
assert that those defaults are unchanged. `.omp/AGENTS.md` imports
`../AGENTS.md` and `../PROJECT.md` for startup guidance and project facts.
`.omp/APPEND_SYSTEM.md` carries only the planner/Main allocation policy:
planner owns P1–P4 blueprints. Planner triggers are P1 fresh architecture,
P2 a material contract pivot, P3 a blocker after two materially different
evidence-led repairs, and P4 missing load-bearing semantics. Main executes
bounded known work, delegates substantial or genuinely disjoint leaves,
integrates, and verifies the integrated candidate once at the proportional
V0–V3 level. It preserves the bundled base prompt, worker roles, permissions,
tool requirements, safety controls, and protected-action approvals. Start OMP
from the repository root so the imports and append are discovered. Changes
apply to a new session, not retroactively. No hooks or custom project role
files are part of the current runtime.

Development Sprint is the current default. The next-major I5 qualification is
paused/deactivated until an authorized maintainer explicitly accepts and
activates its named milestone. Rejected findings and evidence remain rejected
and truthful; frozen packets, reports, and old tracker records are history, not
current runtime or routine Sprint authority.

OMP is a user-level tool. Run `omp` directly and install or update it through
its supported user-level package manager. The repository does not declare an
OMP dependency, launcher wrapper, or CLI version pin. Do not add project role
aliases, custom role files, model/effort/reasoning overrides, hooks, retry
routes, per-worker ledgers, paper artifacts, or mandatory review chains. Core
bundled roles are `task`, `sonic`, `scout`, `reviewer`, and
`security-reviewer`; additional bundled roles require no repository
registration. Native planner capability chooses planning mode; it does not
dispatch automatically. A role choice never grants credentials or protected
delivery authority.

## Normal maintenance

1. Read the affected settings and their owning documentation.
2. Make the requested change and remove obsolete active references.
3. After concurrent edits finish, Main selects the relevant lightweight checks
   and runs them once on the integrated candidate.
4. Report actual behavior, evidence, limitations, risk, and any blocker.

Use on-demand diagnostics and recovery when startup, runtime, or context is
uncertain: inspect the installed OMP profile, read `PROJECT.md`, `CONTINUE.md`,
and the applicable standards, and read cited Beads records with
`bd --readonly`. Recovery is operator-driven, not a startup hook or automatic
tracker synchronization. If durable ownership or history is unavailable,
report the limitation and continue only a fully scoped independent Sprint task
whose context and authority are available.

## Maintained checks

| Command | Purpose |
|---|---|
| `make validate-agent-recipe` | Verify the empty project layer, absence of project role overrides, and the required exported bundled-role inventory; it does not discover effective routing or check model/provider health. |
| `make validate-project-readiness` | Check factual project readiness through `.omp/` without prose-size quotas or qualification claims. |

These are integrated harness checks, not a mandatory gate chain. Routine
maintenance does not require live model calls, an SDK evaluator, a benchmark,
full recipe qualification, or a mandatory review chain. Neither check activates
I5 or changes the selected operating mode.

## Product and security invariants

Harness maintenance changes no XRAY CLI or MCP behavior, schemas, package
resources, installers, skills, reports, or public identifiers. Preserve the
Python 3.10+ floor, uv-only Python commands, JSON and `jq` workflows, operation
and transport semantics, repository containment, bounded results and cursors,
mutation safety, and truthful mutation outcomes. YAML-shaped examples remain
descriptive harness notation; XRAY does not add YAML product output.

## State and authority

Native goal, todo, task, and hub state covers the session and worker lifecycle.
Beads is the durable backlog, dependency, blocker, and handoff store. Main
alone mutates it; children use read-only access for cited context. Preserve
Beads data and history, application work, credentials, provider sessions,
external state, and recoverable dirty state. Do not create a replacement store,
rewrite tracker history, or add automatic tracker synchronization.

Harness changes grant no credential, production, destructive, remote-Git,
commit, push, merge, release, publication, deployment, or Beads-remote
authority. Protected actions remain separately authorized, and historical
packets and evidence never become current runtime merely because they exist.
