---
name: beads
description: Use Beads for durable XRAY outcomes, dependencies, blockers, and cross-session handoff; use native omp goal, todo, task, and hub for session execution.
---

# Beads

Follow [agent operations](../../../docs/agent-operations.md), including its
orchestration and parallel-execution policy. Beads holds durable XRAY
outcomes, bugs, real dependencies, and cross-session handoff; native `goal`,
`todo`, `task`, and `hub` hold current-session work and worker state.

## Select and resume work

Run `bd --readonly prime` after session start or context loss only when durable
context or ownership history is needed. Then inspect an outcome with
`bd --readonly ready` and `bd --readonly show <id>`. When enumerating ready
work, use `bd --readonly ready --limit=0`; if it has no actionable outcome,
inspect `bd --readonly list --all --status=open,blocked,in_progress --limit=0`.
A ready parent epic is not an implementation assignment. Do not routinely
audit the whole graph.

Main alone mutates the canonical XRAY planning checkout through
`bd -C ~/.beads-planning`. Main may claim an outcome actually underway with
`update <id> --claim`, and may create, link, update, or close durable work
there. Workers use read-only commands for cited context and never create,
claim, update, link, close, back up, or synchronize tracker state.

Ready means its prerequisites are available, not that its files are free of
contention. Claim only an outcome actually underway; keep session steps in
native `todo`. Main may complete a bounded known repair directly under the
current blueprint. Do not create a Bead for that repair, a lookup, review,
check, retry, or pause unless it is an independently actionable outcome or
bug.

## Dependencies and updates

Create one Bead for one independently useful outcome or bug with meaningful
acceptance in plain prose. Split mixed code, decision, external, and
qualification obligations only into independently useful outcomes with
distinct completion prerequisites, preserving the acceptance they jointly
deliver. A genuine missing decision or separately gated qualification or
external outcome may have its own Bead.

Do not create Beads for workers, reviews, integration, retries, checks,
handoffs, tiny direct repairs, or metadata, and do not mirror native task
state. File contention is not a blocker: choose disjoint mutation slices and
coordinate shared contracts through `task` and `hub`. A dependency blocks only
when unavailable code, a real missing contract, or an artifact prevents the
next outcome. Do not wait to code for unrelated live approvals.

At a milestone or actual pause, Main makes a concise durable update with the
changed result, evidence actually obtained and its source scope, and any
remaining blocker or next action. Include unique-work location, ownership, or
retained-resource facts only when needed for safe resumption. A pause is not a
completion gate: do not run release suites, generate broad handles, force a
clean tree, or commit the whole checkout merely to stop. Close with
`bd -C ~/.beads-planning close <id>` only when the outcome is complete. Do not
represent skipped checks as passed or relax product security or
human-approval requirements.

Use `--json` for machine parsing and `bd update` rather than interactive
`bd edit`. If read-only recovery is unavailable, report the limitation and
continue only a fully scoped independent Sprint task whose context, authority,
and acceptance are available; stop work that depends on missing ownership or
history. Never push or pull the Dolt remote without separate authority.
Tracker use does not authorize commit, push, deployment, publication, or any
other protected delivery action.
