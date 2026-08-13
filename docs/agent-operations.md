# XRAY Agent Operations

This document owns durable work, contracts, allocation, evidence,
adjudication, integration, rollback, and delivery.

It implements frozen packet version 2, Bead `xray-aly`. `PROJECT.md` owns project commands,
resources, and delivery facts; `ARCHITECTURE.md` owns product boundaries.

## Beads and planning

Run `bd prime` after session start or context loss. Root then inspects the full
ready frontier and active claims. If no tracker exists, stop and follow the
packet-defined XRAY contributor bootstrap in `docs/ADAPTATION.md`; never create
an independent canonical store or import recipe state.

Only root mutates Beads. Before implementation, claim with
`bd -C ~/.beads-planning update <id> --claim`. A ready Bead is an independently
acceptable leaf with resolved authority, contract, interface, writes, and
resources. Exclude coordination parents.

Add a dependency with
`bd -C ~/.beads-planning dep add <issue> <prerequisite>` only when an exact
result is required first. Parentage, priority, context, and scheduling order are
not blockers. After graph changes, inspect cycles, blocked work, and the
explained ready frontier.

Keep notes as the current handoff: exact SHA, evidence, remaining gap, retained
artifacts, and next command. Git and Beads history retain superseded attempts.
Close only proven work.

Never initialize from or copy recipe `.beads/` state. Preserve XRAY's
project-owned history and recovery material. Children use `bd --readonly` and
do not change tracker configuration, memories, issues, dependencies, remotes,
hooks, or backups.

## Contract and allocation

Every assignment supplies or cites each value:

```yaml
bead:
outcome_or_question:
design_packet:
sol_contract:
  behavior:
  non_goals:
  interfaces_and_invariants:
  compatibility_and_rollback:
  risk_and_reversibility:
base_commit:
worktree_branch:
writes:
acceptance_checks:
resources:
runtime:
return:
overrides:
```

Use overrides only for task-specific differences. A child reads its Bead,
project profile, architecture, instruction chain, authority, and checks before
work. It verifies the base, worktree, branch, and write set. Missing or
conflicting input stops the assignment.

Delegate only when it saves a turn, enables real concurrency, or supplies
risk-required evidence. Parallel leaves need disjoint behavior, primary write
sets, generated outputs, resources, and frozen interfaces. Root allocates each
concurrent writer a clean branch and worktree from an immutable SHA.

XRAY allows at most three open child threads and at most three concurrent
writers including root. A completed child may remain resident for follow-up.
When no follow-up is needed, root interrupts the completed lane. Interruption
marks the lane as relinquished but does not itself reclaim its resident slot.
At a full pool, the next spawn replaces the least-recently-used unloadable
relinquished resident. If replacement fails after every child lane is
relinquished, stop delegation and report the V2 residency failure.

Children never mutate Beads, create descendants, coordinate peers, integrate,
deliver, widen scope, or self-approve. Writers do not merge, rebase, stash,
push, publish, deploy, remove worktrees, or delete branches. A child may commit
only when its contract requires a complete scoped artifact.

All roles run with trusted automation permissions. Those permissions do not
widen authority. Root records before-and-after repository and named state,
inspects complete diffs, and rejects unexplained changes.

## Evidence and failure handling

Run narrow checks during work, then every project gate affected by the change.
Evidence records the command, exit status, material output, environment, and
exact artifact SHA. Reuse evidence only at the same artifact with unchanged
inputs and toolchain. A patch invalidates only affected evidence.

At adoption or release boundaries, hash only small, explicit artifact sets
whose unexpected byte change is itself material, such as runtime configuration,
hooks, role TOMLs, or deliberately unchanged examples. Do not require a
repository-wide aggregate preserve manifest for routine development. For paths
expected to evolve, use semantic validators, focused tests, and complete Git
diff review. Expand a byte-invariant set only when its authority records why
byte identity, rather than behavior, is required.

XRAY's byte-invariant adoption set is limited to the six role TOMLs, Beads
skill UI metadata, and three deliberately unchanged examples named by the
frozen packet. A YAML-shaped assignment example is not XRAY CLI output and
does not reopen the JSON-first, no-YAML product decision.

For user-facing work, verify applicable loading, empty, success, validation,
error, accessibility, console, network, and responsive states. Semantic review
also covers hierarchy, spacing, alignment, density, affordance, overflow,
touch targets, content priority, and consistency.

A retry is a repeated technical hypothesis after the previous hypothesis left
the same failure and added no discriminatory evidence. Formatting, fixture
correction, deterministic test feedback, environmental outage, and contract
clarification are not retries.

Key a stubborn failure by Bead, Design Packet version and digest, artifact
lineage, and failure signature. After exactly two consecutive evidence-free
hypotheses with that unchanged key, stop implementation and send the complete
failure packet to `breakthrough_read`. Reset the counter after a key change,
new evidence, repair, rejected approach, or new packet. Route an architectural
change back through `sol_design`.

Every child stops for ambiguity, contract conflict, required expansion of
authority, scope, writes, tools, resources, permissions, or network; a
prohibited action; contradictory evidence; or an unexplained regression.
Terra also stops for an incomplete packet or artifact change.

## Review and adjudication

Use Terra only after deterministic checks when independent counterexample
search materially reduces risk. Give a fresh verifier the unchanged contract,
authority, base and artifact SHAs, complete diff, evidence, uncertainty,
residual risk, allowed operations, and observed state. Terra performs no write
or output-producing check and returns all material findings once.

P0 and P1 findings block. P2 blocks only for a direct acceptance dependency,
release risk, or material near-term rework. Re-review only changed findings.
No findings is evidence, not approval.

Root inspects the contract, diff, evidence, uncertainty, failed attempts, and
review findings. It chooses exactly one result:

1. accept for the next protected gate;
2. request one bounded repair;
3. reject and redesign;
4. declare requirements underspecified;
5. escalate to a human.

## Integration and delivery

Root uses one integration queue. For each accepted artifact, confirm ancestry
and paths, inspect the semantic diff, reconcile on the current integration SHA,
rerun invalidated checks, and record the result SHA and rollback.

Keep worktrees until their results are durable. After integration, remove a
clean accepted worktree with `git worktree remove`, delete its merged branch
without force, prune, and inspect the remaining worktree list. Never discard a
dirty or unintegrated artifact.

Without explicit project delivery authority, stop after local verification.
With authority, record residual work and rollback, verify, commit, push the
exact SHA, wait for protected CI and approval, merge or release, close Beads,
synchronize its approved remote, and audit Git, Beads, CI, and worktrees. Stop
at the last durable boundary on failure.

Repository configuration cannot enforce credentials, protected Git, retry
limits, production isolation, or human approval. Runtime permissions,
credential systems, repository rules, CI, branch protection, and humans retain
those controls.

For this adoption, root may create local branches and worktrees and integrate
locally. Commit, push, merge, release, deployment, remote mutation, and Beads
Dolt synchronization remain unauthorized until separately granted.
