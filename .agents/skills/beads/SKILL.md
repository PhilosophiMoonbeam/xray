---
name: beads
description: Use Beads for durable project work, dependencies, blockers, and handoff.
---

# Beads

Follow repository authority. Run `bd prime` after session start or context
loss when durable work or ownership history is needed. Use the canonical XRAY
planning checkout; never create a replacement store or fabricate tracker state.

Root reads and mutates Beads through `bd -C ~/.beads-planning`. Root may use
`update <id> --claim`, `create`, `dep add`, `update --notes`, and `close` for
durable work. Children use `bd --readonly show <id>` for cited context and do
not mutate Beads, dependencies, remotes, hooks, backups, or tracker
configuration. A Bead is not required for every local question, edit,
hypothesis, or test.

Use `--json` for machine parsing and never use blocking `bd edit`. Preserve
unrelated dirty state. If recovery is unavailable, report the limitation and
continue only a fully scoped independent Sprint task whose context and
authority are available; stop work that depends on missing ownership or
history. Never push or pull the Dolt remote without separate authority.
