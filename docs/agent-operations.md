# XRAY Agent Operations

This document owns routine planning, delegation, evidence, recovery, review,
integration, and delivery. `PROJECT.md` selects the operating mode and owns
commands, resources, and delivery facts. `ARCHITECTURE.md` owns product
boundaries, interfaces, containment, compatibility, storage, and mutation.

## Development Sprint defaults

Development Sprint is the default. A small cohesive task needs no separate
plan artifact. For multi-file work, root writes a short dependency-ordered plan
before editing. Consult `sol_design` once when a decision materially changes
architecture, a shared API or schema, persistence, a trust boundary,
compatibility, or ownership. Use its actionable contract; reconsult only when
evidence invalidates it or a material decision changes.

Implement the smallest complete requested increment. Preserve supported
behavior, authorization, containment, data protection, compatibility, resource
limits, and truthful mutation outcomes. Remove obsolete in-scope paths and
update affected callers. Do not add speculative compliance machinery,
migrations, infrastructure, or compatibility scaffolding.

## Durable work and Beads

Use the canonical Beads store for durable multi-session work, dependencies,
blockers, and handoff. Root alone mutates it through
`bd -C ~/.beads-planning`; children use `bd --readonly` for cited context and
never create, claim, update, link, close, back up, or synchronize tracker
state. A Bead is not required for every local question, edit, hypothesis, or
test. Never create a replacement canonical store or fabricate state.

After session start or context loss, recover relevant current work when durable
ownership or history matters. Do not repeatedly scan the entire frontier or
recreate a passed planning phase. If tracker recovery is unavailable, report
the limitation and continue a fully scoped independent Sprint task only when
its context, authority, and acceptance are available; stop work that depends
on unavailable ownership or history.

A handoff records the objective, active mode reference, changed paths,
evidence, remaining defects, and next action. Preserve unrelated dirty state.
Close durable work only when its named acceptance is proven; do not relabel an
incomplete Enterprise qualification as passed.

## Scoped assignment and allocation

An assignment states:

- the outcome or bounded question;
- owned paths and explicit non-goals;
- relevant interfaces, invariants, and compatibility boundaries;
- allowed operations, resources, and runtime;
- observable acceptance and focused checks;
- material risks, recovery or rollback needs, and return format.

Cite a Bead or design decision when one exists; neither is invented as a
prerequisite for every leaf. Missing information blocks only when needed for
safe execution. Root retains intent, scope, integration, and delivery
authority.

Root implements directly unless at least two genuinely independent units
shorten the critical path or a specialist materially reduces risk. Multiple
files alone do not justify delegation. Children do not create descendants,
coordinate peers, widen scope, self-approve, integrate, or deliver.

Keep current host limits and capability settings. Concurrent writers require
disjoint primary paths, generated outputs, exclusive resources, and agreed
interfaces. Serialize overlap. Use a worktree when isolation provides real
value; do not require one as routine paperwork or create commits merely to
manufacture a clean worker base when commit authority is absent.

## Routine evidence and verification

Record the actual command or scenario, exit/result, material observation,
relevant environment, and limitation in the final report or durable work item.
Exact artifact hashes are required when the product contract requires them,
especially a reviewed change-plan digest, or when an activated assurance
contract depends on exact identity. They are not required for every ordinary
file or role prompt.

Routine completion uses changed-path tests, the relevant type or static check,
and the narrowest real runtime proof. CLI-facing changes need a real focused
`uv run xray` process against an explicit small fixture or authorized root.
MCP-facing or shared behavior needs an actual `uv run xray-mcp` standard-stdio
child: initialize it, list the two adapter tools, call the changed operation,
observe the result or typed error, and shut it down cleanly. An in-process
`Client(mcp)` test, mock echo, or idle process is not transport proof.

Shared behavior gets one focused scenario per affected public transport. Add a
negative case for a changed validation, authorization, containment, or
mutation boundary. Package metadata, dependencies, entry points, installers,
resources, or version-sensitive primitives require an isolated installed
package smoke and a relevant Python-floor check. Do not run every operation,
language, cache state, or corpus without an affected-contract reason.

## Failure, recovery, and rollback

Use a failed result to obtain discriminatory evidence and repair its owning
path. Change the diagnostic approach or obtain useful specialist help when a
failure remains materially stuck. Do not impose exact retry, repair, or
follow-up quotas, and do not repeat evidence-free guesses.

Stop the affected action for unavailable authorization, a prohibited operation,
an uncertain destructive target, a material contract conflict, contradictory
evidence, an unexplained introduced regression, or an unsafe or
outcome-ambiguous mutation. Never retry an uncertain mutation merely to see
whether it applied; establish the authoritative outcome first.

Back up before a real destructive or persistent-data transition. Do not back
up every read or edit ceremonially. Routine code rollback uses the actual
pre-change state or an authorized integration boundary, not a historical
adoption base. Preserve recoverable dirty state and use exact validated
targets. Cache loss is expendable only where the product contract says it
changes performance, not truth.

## Review and adjudication

Root reviews the scoped change and proof. Independent correctness or security
review is optional unless a concrete trust, mutation, compatibility, or
delivery risk, or a named acceptance contract, makes it necessary. Review the
affected boundary rather than every component. A reviewer’s silence is not
authorization. Repair local defects with their owner; return to `sol_design`
only for a material contract-invalidating finding.

When review is used, give the reviewer the identified change, applicable
contract, complete relevant diff, actual evidence, uncertainty, residual risk,
allowed read-only operations, and observed state. The reviewer returns all
material findings; no finding is evidence, not approval.

## Enterprise/Certification milestone

The enhanced workflow is conditional. The user or authorized maintainer must
explicitly activate Enterprise/Certification in `PROJECT.md` for a named
milestone, assurance objective, and acceptance contract. A risk, role name,
Make target, broad command, old tracker item, major-version label, or recovered
handoff cannot activate it. An explicit request for one broad check authorizes
that check, not every assurance ceremony.

For an activated milestone, follow its named existing contract: bounded
planning/dependency stages, exact relevant candidate and evidence identity,
applicable full gates, independent fixed-artifact review, qualification
populations, and replay or attestation only where that contract requires them.
Use existing packet, evidence, and artifact locations. Do not add a generic
compliance framework, certification schema, service, or policy engine.

Explicitly activating next-major I5 selects the preserved v1-v4 contract and
its adjudicated method requirements. The incomplete method and rejected
product findings remain blockers for that claim; historical counts are not
current proof. At completion, cancellation, or deactivation, record the
truthful result and residual work, then return new work to Sprint.

## Integration and delivery

Root integrates accepted artifacts serially after checking paths, semantic
diff, affected evidence, and rollback. Keep unintegrated work recoverable.
Without separate delivery authority, stop after local verification. Commit,
push, merge, release, deployment, publication, remote mutation, credentials,
and Beads Dolt synchronization remain unauthorized. A passing local check or
Enterprise result never expands that authority.
