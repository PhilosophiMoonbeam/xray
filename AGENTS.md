# XRAY Agent Index

XRAY is a Python code-intelligence CLI and MCP server. Root owns intent, risk,
Beads, allocation, adjudication, integration, delivery, and completion.
Repository policy, protected systems, CI when present, and humans retain their
own authority.

User, platform, and orchestrator instructions override this file. A closer
`AGENTS.override.md` or `AGENTS.md` overrides broader repository guidance only
for its subtree. Within repository policy, `PROJECT.md` selects Development
Sprint or an explicitly activated named Enterprise/Certification milestone.
No repository instruction grants credentials, production access, destructive
authority, remote mutation, merge, publication, or deployment.

## Instruction index

Read only the sources required by the current trigger. Descriptive documents
and examples do not override an authoritative source.

| Trigger | Read | Authority |
|---|---|---|
| Before planning or claiming work | [`PROJECT.md`](PROJECT.md), [`ARCHITECTURE.md`](ARCHITECTURE.md), and the applicable instruction chain | Mode, readiness, commands, components, interfaces, resources, and project authority |
| After session start or context loss | Beads skill and current-work recovery when durable history is needed | Durable work, dependencies, blockers, and handoff |
| Before changing owned text | [`docs/repository-language-standard.md`](docs/repository-language-standard.md) | Vocabulary, strength, semantic density, and transformation evidence |
| Before implementation | [`docs/implementation-standard.md`](docs/implementation-standard.md) | Supported behavior, implementation, verification, and completion |
| Before routing or delegation | [`docs/agent-model-routing.md`](docs/agent-model-routing.md), then [`docs/agent-operations.md`](docs/agent-operations.md) | Routes, contracts, allocation, worktrees, evidence, adjudication, and delivery |
| Before integration, release, or destructive work | [`docs/agent-operations.md`](docs/agent-operations.md) and `PROJECT.md` | Reconciliation, rollback, protected gates, and cleanup |
| During historical adoption recovery | [`docs/adoption-design-packet-v2.md`](docs/adoption-design-packet-v2.md), [`docs/ADAPTATION.md`](docs/ADAPTATION.md), and [`TEMPLATE_MANIFEST.md`](TEMPLATE_MANIFEST.md) | Historical adoption procedure and frozen evidence; not routine Sprint authority |
| For product behavior or orientation | [`README.md`](README.md), then `ARCHITECTURE.md` | Public usage and component contracts |

## Readiness and scope

If `PROJECT.md` is not exactly `Status: READY`, edit only an explicitly
authorized harness, profile, architecture, validator, documentation, or
readiness-repair scope. Do not edit application source or guess a project
fact. Inspect the affected configuration, tests, scripts, permissions,
resources, and instructions before editing; preserve unrelated state. Make the
smallest complete change and remove obsolete behavior within scope.

## Root and child boundaries

Root decides meaning and risk. It delegates execution, not authority. Use a
child only for concrete, bounded work when delegation saves a turn, enables
genuine concurrency, or supplies risk-required independent evidence. Children
do not mutate Beads, coordinate peers, create descendants, widen scope,
self-approve, integrate, or deliver. Exact roles, models, efforts, and runtime
controls live in `.codex/config.toml` and `.codex/agents/*.toml`.

Only root mutates the canonical tracker through `bd -C ~/.beads-planning`.
Children read Beads with `bd --readonly` when a cited durable contract is
needed. Root uses Beads for durable multi-session work, dependencies, blockers,
and handoff; a Bead is not required for each local question, edit, hypothesis,
or test.

An assignment states the outcome or question, owned paths, relevant interfaces
and invariants, allowed operations/resources, observable acceptance, and known
risks. Add compatibility, rollback, runtime, or return details when they affect
safe execution. Missing information blocks only when needed for safe
execution.

Concurrent writers require disjoint primary writes, generated outputs,
resources, and stateful operations. Worktrees are risk-driven: use them when
isolation is needed, and serialize overlapping work. Keep current host limits
and capability settings. Root integrates accepted artifacts and keeps
unintegrated work recoverable.

MultiAgentV2 has no V1 `close_agent` tool. Root may retain a completed child
for a useful follow-up and otherwise relinquish it according to the host
lifecycle. Children never claim that interruption grants delivery authority.

Routine evidence is the actual command or scenario, exit/result, material
observation, environment when relevant, and limitation. Exact artifact hashes,
complete maps, and attestation ledgers are required only by a product contract
or an explicitly activated assurance milestone. A check proves only covered
behavior; no findings is not approval.

Stop for ambiguous intent, contract conflict, required authority or scope
expansion, contradictory evidence, an unexplained regression, a prohibited
action, or an unsafe/outcome-ambiguous mutation. Change diagnostic approach or
obtain useful specialist evidence when a failure remains materially stuck; do
not count retries or impose a fixed repair quota.

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

Harness authority changes update the affected policy, role/configuration,
validator, recovery, and applicability links. Review the semantic diff and
run only applicable configuration or static checks authorized for the change.
Frozen packets, companions, and byte-invariant examples remain historical
artifacts unless an explicitly activated milestone says otherwise. Record
limitations instead of weakening product or delivery boundaries.
