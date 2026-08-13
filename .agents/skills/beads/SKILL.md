---
name: beads
description: Use Beads for durable project work, dependencies, blockers, and handoff.
---

# Beads

Follow repository authority. Run `bd prime` after session start or context
loss. If empty, run `bd where`; report
`bd init --non-interactive --skip-agents` only when no tracker exists.

Root reads with `bd ready` and `bd show <id>`. XRAY uses a dedicated planning
store, so root mutates through `bd -C ~/.beads-planning`: claim with `update
<id> --claim`; use `create`, `dep add`, `update --notes`, and `close` for durable
state. Do not push or pull the Dolt remote without separate authority.

Use `--json` for machine parsing. Never use blocking `bd edit`. Children do not
mutate Beads; they use `bd --readonly show <id>` when their contract permits
reads. Local plans are temporary; Beads is the durable handoff.
