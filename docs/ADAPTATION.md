# XRAY Harness Adaptation

This procedure implements the active frozen Design Packet version 2. It
does not override `AGENTS.md`, `PROJECT.md`, `ARCHITECTURE.md`, Codex
configuration, or the packet and its companion digest.

## 1. Establish project authority

Keep `PROJECT.md` at `Status: NOT_READY` while project facts, canonical `uv`
commands, resources, delivery authority, and local qualification gates are
unproven. `ARCHITECTURE.md` must describe XRAY's CLI, MCP adapter, core engine,
packaging, caches, compatibility surfaces, generated artifacts, and mutation
boundaries without changing product behavior.

The root `AGENTS.md` remains a compact index. Add no nested instruction file
without a real subtree-specific command, owner, invariant, or review rule.
Apply the Repository Language Standard to owned prose and keep each rule at
its named authority.

## 2. Install the frozen Codex routes

Use the packet's root route and six byte-invariant child profiles. The target
ceiling is three child threads and at most three concurrent writers including
root. Children remain unable to create descendants. Update configuration,
operations, validators, and transformation evidence together if an authorized
packet revision changes a route, effort, role, or ceiling.

Enable both `features.multi_agent` and `features.multi_agent_v2`. The semantic
validator rejects a disabled V2 override so the control plane cannot silently
return to the V1 lifecycle.

Trusted local automation uses `danger-full-access` with approval `never`.
Those settings grant no credentials, destructive authority, production
access, protected Git action, Beads synchronization, publication, release, or
deployment. Use current official Codex documentation for Codex behavior and
Context7 for other current developer documentation under root instructions.

## 3. Normalize XRAY-owned recovery

Never copy recipe `.git/` or `.beads/` state. Preserve and back up XRAY's
canonical planning database before changing contributor routing. Root alone
mutates Beads; children use `bd --readonly`. Replace legacy direct
`bd codex-hook`, `PreCompact`, `PostCompact`, and `UserPromptSubmit` groups
with one SessionStart recovery composer for `startup|resume|clear|compact`.
Run its Python entry point through `uv run python`.

Retain Claude only as the packet-defined read-only compatibility adapter.
Verify fresh-root, compaction, resume, and fresh-worktree recovery against an
active claim absent from prior chat context. Hook execution alone is not
proof of current-work recovery.

## 4. Preserve XRAY behavior

This adoption does not change CLI or MCP behavior, schemas, packages, product
skills, installers, reports, tests, caches, or public identifiers. Preserve
compact JSON defaults, v1/full compatibility, JSON and `jq` pipelines,
CLI/MCP semantics and documented surface differences, path containment,
bounded results and cursors, mutation safety, Python 3.10+, and package data.
The YAML-shaped assignment example is descriptive harness notation; XRAY does
not add YAML output.

## 5. Calibrate execution

Use root-fast for a cohesive slice. Allocate parallel writers only when
independent leaves have disjoint behavior, paths, branches, worktrees,
resources, and generated outputs. Add Terra only when fixed-artifact
counterexample search materially reduces risk. Root integrates serially and
keeps every unintegrated result recoverable.

MultiAgentV2 has no V1 `close_agent` tool. Root may retain a completed child
for follow-up. When no follow-up is needed, root interrupts the completed lane.
Interruption marks the lane as relinquished but does not itself reclaim its
resident slot. When the three-child pool is full, the next spawn replaces the
least-recently-used unloadable relinquished resident. A failed replacement
after every child lane is relinquished stops delegation and is reported.

## 6. Qualify the exact candidate

Hash only the small byte-invariant set named by the packet. Validate adapted
paths through semantic validators, focused tests, and complete diff review;
do not create a repository-wide preserve manifest. Run the canonical Make
targets, product tests, static checks, packaging and smoke checks, strict
Codex diagnosis, link and stale-reference scans, and `git diff --check`.

Keep readiness `NOT_READY` until every required value, command, architecture
claim, recovery path, and exact-SHA gate is proven. Local success does not
authorize commit, push, merge, sync, release, or deployment. Record exact
evidence, rollback, residual risk, and remaining work in Beads.
