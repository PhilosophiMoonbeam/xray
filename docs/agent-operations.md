# XRAY Agent Operations

Main owns user intent, routing, accepted-blueprint reuse, adaptive execution,
shared-contract coordination, integration, affected verification, acceptance,
and completion. The designated planner owns deep design when a P1–P4 trigger
applies; Main remains the orchestrator and may directly handle bounded known
work. Delegate substantial leaf work and independent branches to the matching
stock roles.

## Blueprint triggers and reuse

Classify the next decision, not the file count or apparent size. Use the first
applicable trigger below. An accepted blueprint remains valid until one of
these triggers actually invalidates it.

- **P1 — Fresh blueprint.** An admitted outcome has no reusable blueprint and
  requires materially different behavior, component ownership, shared
  interfaces, state transitions, persistence or migration strategy, or
  cross-layer architecture. The planner returns one selected design, governing
  requirements and exclusions, invariant and contract boundaries, complete
  vertical acceptance, real dependency order, and bounded verification. It
  need not provide a fixed schema or exhaustive file manifest.
- **P2 — Major pivot.** New evidence or a changed request invalidates a
  blueprint invariant or accepted cross-layer contract, changes authority or
  data ownership, requires a materially different migration or rollback
  strategy, replaces an architectural mechanism, or changes agreed product
  acceptance. The planner names the invalid assumption, affected contracts and
  consumers, replacement design, compatibility effects, and revised proof; it
  does not replan unaffected work.
- **P3 — Stubborn blocker.** The same blocker survives two materially
  different, evidence-led repair attempts within the blueprint, or diagnosis
  exposes a cross-contract contradiction sooner. An attempt is a concrete
  hypothesis and repair with an observed result, not two reruns of a failing
  command. Count attempts across Main and workers; reassignment does not reset
  the count. The planner diagnoses the blocker from the source, reproduction
  or report, and both approaches, then chooses the repair or required
  blueprint delta. Stop local patch cycling while that decision is pending.
- **P4 — Missing load-bearing semantics.** A needed security or authorization,
  persistent-data, acceptance, or phase-boundary rule cannot be derived from
  current governing sources. First establish whether the existing architecture
  resolves it. If it is genuinely a product, risk, or authority choice, the
  planner identifies one precise owner decision and the safe disabled or
  unchanged boundary; the planner cannot invent permission.

These are not triggered by a routine bug with a supported cause or known
repair, a documented dependency or API fix, straightforward implementation of
a settled contract, a worker failure or merge conflict, stale generated
output, an unavailable disposable resource, an ordinary understood
lint/type/test failure, a new session, a commit, an assignment boundary, a
failed first repair, or a request to restate an accepted plan. A local
refactor or small pivot that preserves acceptance, interfaces, invariants,
authority, and data-transition semantics stays in execution.

Known means supported by current source, accepted contracts, a documented
dependency capability, or an established repository pattern—not merely
familiar to the model. Main checks a returned blueprint for intent,
constraints, omissions, and feasibility once. Request a specific correction
only for a material defect; there is no mandatory planner–reviewer–planner
approval carousel. If the designated deep-design capability is unavailable,
report that gap and continue only work covered by a current blueprint or known
solution. Do not silently replace it with a general implementation agent or a
model-selector name.

## Main adaptive execution

Main may investigate, reproduce, repair, and verify a bounded known solution
directly when dispatch would add overhead without useful parallelism or
expertise. Main may also perform small implementation-local pivots,
integration repairs, contract-preserving wiring, documentation or fixture
corrections, and local unblockers. Main may inspect implementation deeply
enough to diagnose and integrate; it is not limited to routing investigation
or trivial edits.

Main remains primarily an orchestrator. Delegate substantial leaf work,
focused debugging, or independently useful parallel branches to the most
specific existing specialist, otherwise `task`; do not consume a large worker
assignment simply because it is familiar. Agents own implementation-local
design inside the blueprint. Sonic is for completely specified mechanical
work, not uncertain code design. Main may coordinate a blueprint-preserving
shared-interface correction and migrate its callers atomically. If the
semantic contract changes materially, P2 applies. Main never edits an actively
owned worker surface without first transferring or reconciling ownership.

## Workflow state machine

- **ROUTE — Main.** Read the relevant current contract and selected outcome,
  establish authority, reuse an accepted blueprint, and identify the next
  complete vertical result. P1–P4 transitions to `BLUEPRINT`; settled known
  work transitions to `EXECUTE`; an unavailable owner or external input
  transitions to `BLOCKED`.
- **BLUEPRINT — Planner, with Main supplying objective and constraints.**
  Select the architecture or bounded delta and identify exact prerequisites and
  proof. Main converts it to work without independently replanning.
  Technically settled and authorized work transitions to `EXECUTE`; a genuine
  product, risk, or authority choice is `BLOCKED` for that path.
- **EXECUTE — Main plus assigned implementers.** Implement the vertical
  outcome, release ready disjoint consumers, and let Main handle known local
  repairs and central integration. An integrated candidate transitions to
  `VERIFY`; material invalidation or two distinct failed approaches returns to
  `BLUEPRINT`; an unavailable prerequisite transitions to `BLOCKED`.
- **VERIFY — Main, with risk-matched review when needed.** Run affected
  maintained checks and an actual changed-path exercise once on the integrated
  candidate, recording exactly the claim proved. A local defect returns to
  `EXECUTE`; a blueprint invalidation or stubborn blocker returns to
  `BLUEPRINT`; unavailable required proof is `BLOCKED` or an explicit
  verification-pending handoff; all selected-outcome criteria satisfied
  transitions to `COMPLETE`.
- **COMPLETE — Main.** Report the result and limitations, update the owning
  outcome, and perform only authorized delivery. Qualification siblings and
  parent outcomes remain open until their own requirements pass. A newly
  observed regression reopens affected work; completion grants no later-phase
  or protected authority.
- **BLOCKED / PAUSED — Main.** Preserve reachable unique work, exact failed
  or unrun evidence, ownership and resource facts needed for safe resumption,
  and the next input or action. Continue unrelated ready work. When input
  arrives or the user resumes, return to `ROUTE` with the existing blueprint;
  do not perform a routine full-graph audit, requalification, or replan merely
  to stop or restart.

Implementation status, focused verification, full software qualification,
release or provider qualification, operating evidence, and protected
authorization are separate claims. An unsatisfied selected outcome is never
closed by relabeling it. Historical or rejected qualification evidence remains
truthful and cannot be relabeled as acceptance.

## Ownership and dispatch

Use native `goal` for the objective when one is available and warranted, and
`todo` only for genuinely multi-step session work. Native `task` and `hub`
already track workers; do not copy that state into another ledger.
Assignments are concise prose stating the outcome, applicable blueprint and
policy pointers, needed facts and shared contracts, exclusive mutable
ownership, real prerequisites or resources, exclusions, and expected
behavioral evidence. Reference shared context once rather than copying an
entire plan. No fixed machine assignment, handoff, review, or approval schema
is required.

Children do not inherit the parent conversation or necessarily startup files;
they must read applicable policy before acting. Pass needed context, not the
full history or a document dump. For isolated writers, name owned files
relative to the worker's checkout. Do not direct them to the canonical
checkout with absolute write paths or `cwd` overrides; identify any authorized
shared or external resource separately.

Read [agent routing](agent-model-routing.md) before selecting workers. Use
the most specific available stock role and report missing required capabilities;
do not invent roles or silently take over specialist work. Dispatch actionable,
independent assignments in one native `task` batch. Maintain a bounded rolling
frontier: integrate a prerequisite before a dependent uses it in that checkout,
release newly actionable consumers without waiting for unrelated branches, and
continue unaffected branches after a failure. A planning-only reply or
sequential worker loop is not concurrent orchestration unless the work is
genuinely serial or blocked.

Serialize only shared contracts, mutations, integration, or genuinely
exclusive resources. In a shared checkout, concurrent writers require
disjoint primary paths, generated outputs, and stateful resources. If a
contract drifts, pause affected consumers while Main reconciles it, then
continue independent work. Native isolation is opt-in when needed; a worktree
does not resolve semantic conflicts.

Children in concurrent editing batches skip validation, tests, builds, lint,
and formatters. Main reviews integrated writes and runs affected checks once.
Use `reviewer` or `security-reviewer` when independent correctness or security
scrutiny materially reduces risk, not as a mandatory approval layer. An
explicitly assigned isolated proof owner may exercise a stable independent
surface with exclusive resources; it does not claim integrated acceptance.

## XRAY verification

XRAY product behavior remains governed by `PROJECT.md`, `ARCHITECTURE.md`, and
the affected product contract. Python commands, tests, builds, and package
operations run through `uv`. CLI-facing changes require a real focused
`uv run xray` subprocess against an explicit small fixture or authorized root.
MCP-facing or shared behavior requires an actual `uv run xray-mcp` standard-
stdio child: initialize it, discover the two adapter tools, call the changed
operation, observe the result or typed error, and shut it down cleanly. An
in-process MCP client or idle server is not transport proof.

Preserve explicit-root containment, bounded results and snapshot-bound cursors,
unresolved name-based impact, guarded `xray.change.v1` mutation, truthful
mutation outcomes, and protected authorization. Add a focused negative case
when validation, authorization, containment, or mutation behavior changes.
Select the narrowest proof for the affected public transport; do not run every
operation, language, cache state, or corpus without an affected-contract
reason.

Report the changed result, checks actually run, and any remaining limitation,
blocker, or next action. Repair observed defects at their source; do not treat
failed checks or missing security semantics as mere verification debt.

## Durable backlog and session handoff

Beads holds durable XRAY outcomes, bugs, genuine dependencies, and
cross-session handoff. It is not a worker scheduler. Main alone mutates the
canonical planning checkout through `bd -C ~/.beads-planning`; workers use
`bd --readonly` for cited context and never create, claim, update, link, close,
back up, or synchronize tracker state.

Create one Bead for one independently valuable outcome or bug with meaningful
acceptance in plain prose. Split meaningful local implementation, a missing
security decision, an external action, and qualification only when their
completion prerequisites differ; preserve every acceptance requirement without
inflating per-stage or per-worker issues. A tiny direct repair, lookup, review,
check, or pause normally updates its owning outcome rather than creating a new
Bead; create a new one only when it is independently actionable.

Current repository policy supersedes historical frozen dispatch, custom-role,
and per-worker tracker instructions; preserve product requirements and
external-authority limits. To recover durable context on demand, use the
read-only Beads procedure in the Beads skill; do not routinely audit the whole
graph.

At an actual milestone or pause, record only the changed result, evidence
actually obtained and its source scope, and any remaining blocker or next
action. Include unique-work location, ownership, or retained-resource facts
only when needed for safe resumption. A pause is not a completion gate: do not
run release suites, generate broad handles, require a reviewer, force a clean
tree, or commit the whole checkout merely to stop. Preserve work first and
label unverified material explicitly.

## Authority and delivery

Assignments grant no credentials, production access, destructive action, Git
delivery, publication, or deployment. Main coordinates protected operations
and tracker changes. Application human-approval controls remain product
behavior and are not relaxed by this workflow. Without separate delivery
authority, stop after local verification. Commit, push, merge, release,
deployment, GitHub mutation, publication, credentials, and Beads Dolt
push/pull remain unauthorized.
