# XRAY Harness Migration Manifest

This inventory guides adoption; the instruction chain, project profile,
architecture, frozen packet, and Codex configuration retain runtime authority.

| Path | Action | Result |
|---|---|---|
| `AGENTS.md` | Adapt | Compact XRAY authority index plus V2 residency |
| `PROJECT.md` | Add | Verified facts, `uv` commands, resources, gates, authority |
| `ARCHITECTURE.md` | Add | Components, interfaces, compatibility, storage, mutation |
| `docs/adoption-design-packet-v1.md` | Preserve frozen | Historical `xray-oep.1` adoption authority |
| `docs/adoption-design-packet-v1.sha256` | Preserve frozen | Exact version 1 packet digest |
| `docs/adoption-design-packet-v2.md` | Add frozen | Active `xray-aly` recipe-sync authority |
| `docs/adoption-design-packet-v2.sha256` | Add frozen | Exact version 2 packet digest |
| `.codex/config.toml` | Adapt | Root route, explicit MultiAgentV2, six roles, three-child ceiling |
| `.codex/agents/*.toml` | Add byte-identical | Six frozen child profiles |
| `.codex/hooks.json` | Adapt | One SessionStart group; remove legacy groups |
| `.codex/session_start.py` | Add/adapt | Bounded read-only recovery through `uv` |
| `.codex/validate_agents.py` | Add/adapt | Inventory, routes, hook, hygiene, references, budgets |
| `.codex/validate_project_readiness.py` | Add/adapt | Exact readiness and project-authority gate |
| `.agents/skills/beads/SKILL.md` | Adapt | Compact root-write/child-read-only workflow |
| `.agents/skills/beads/agents/openai.yaml` | Replace byte-identical | Frozen UI metadata |
| `docs/ADAPTATION.md` | Add/adapt | XRAY adoption and qualification |
| `docs/agent-model-routing.md` | Add/adapt | Three lanes, classifier, frozen authority |
| `docs/agent-operations.md` | Add/adapt | Work, contracts, evidence, integration, delivery |
| `docs/implementation-standard.md` | Add/adapt | Supported behavior and verification |
| `docs/repository-language-standard.md` | Add/adapt | Owned-text and proof rules |
| `docs/instruction-transformation-evidence.md` | Add/adapt | Bidirectional maps, decisions, sizes |
| `examples/assignment-contracts.md` | Add byte-identical | Non-authoritative reference |
| `examples/beads-dag.md` | Add byte-identical | Non-authoritative reference |
| `examples/nested-AGENTS.md` | Add byte-identical | Non-authoritative reference |
| `Makefile` | Add/adapt | Non-interactive harness and product gates |
| `README.md` | Preserve/adapt | Product body plus concise harness links |
| `.gitignore` | Merge | Project, runtime, Beads, and `.xray/` policy |
| `.claude/settings.json` | Retain/adapt | Read-only SessionStart adapter |
| `.xray/xray.db*` | Remove named | Three frozen generated SQLite artifacts only |
| Product source, tests, samples, installers, reports, skills, packaging | Preserve | No harness-driven product change |
| Recipe `.git/` and `.beads/` | Omit | Never transplant recipe state |
| Existing XRAY Beads topology | Preserve/normalize | Back up history; portable routing; no child writes or sync |

The recipe omitted README and manifest rows; both appear above. The packet and
digest give each added control artifact an owner and rollback. YAML-shaped
examples remain descriptive, not product YAML output.

## Synchronization edges

- Role change: registration, role TOML, validator, routing evidence, examples.
- Permission or hook: config, hook JSON/script, validator, adaptation.
- Thread limit: config, operations, validator, packet.
- Command, resource, delivery: `PROJECT.md`, Make targets, closer authority.
- Interface: `ARCHITECTURE.md`, packet, dependencies, compatibility evidence.
- Language or implementation rule: authority, evidence, calibrated budget.
- Byte invariant: exact recipe commit and SHA; adapted paths use semantic
  gates, focused tests, and complete diffs.

Apply synchronized changes atomically or through explicit Beads dependencies.
Root alone integrates, records rollback, and changes durable work state.
