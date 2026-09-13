# XRAY Harness Migration Manifest

This inventory records the current XRAY control-plane paths and historical
adoption artifacts. `PROJECT.md` is the sole mode selector and activation home;
current standards and configuration retain their stated authority. Frozen
packets and companions remain intact evidence, not routine Sprint instructions.

| Path | Action | Result |
|---|---|---|
| `AGENTS.md` | Maintain | Compact authority index that points to the active mode and current standards |
| `PROJECT.md` | Maintain | Development Sprint default, explicit Enterprise activation, commands, resources, and delivery facts |
| `ARCHITECTURE.md` | Maintain | Product components, interfaces, compatibility, storage, and mutation |
| `docs/adoption-design-packet-v1.md` | Preserve frozen | Historical `xray-oep.1` adoption evidence |
| `docs/adoption-design-packet-v1.sha256` | Preserve frozen | Exact version 1 packet digest |
| `docs/adoption-design-packet-v2.md` | Preserve frozen | Historical `xray-aly` adoption evidence |
| `docs/adoption-design-packet-v2.sha256` | Preserve frozen | Exact version 2 packet digest |
| `docs/next-major-design-packet-v3.md` | Preserve frozen | Historical pending V3 qualification evidence |
| `docs/next-major-design-packet-v3.sha256` | Preserve frozen | Exact version 3 packet digest |
| `docs/next-major-design-packet-v4.md` | Preserve frozen | Historical pending applicability evidence |
| `docs/next-major-design-packet-v4.sha256` | Preserve frozen | Exact version 4 packet digest |
| `.codex/config.toml` | Adapt | Current root route, MultiAgentV2, six roles, and host ceiling |
| `.codex/agents/*.toml` | Adapt mutable | Mode-aware role prompts with preserved models, permissions, and no descendants |
| `.codex/hooks.json` | Retain | One SessionStart group and existing hook mechanics |
| `.codex/session_start.py` | Adapt | Bounded read-only recovery through `uv` |
| `.codex/validate_agents.py` | Adapt | Parsing, registration, permissions, historical packet checks, and hygiene |
| `.codex/validate_project_readiness.py` | Retain | Existing readiness schema and checks |
| `.agents/skills/beads/SKILL.md` | Adapt | Compact canonical-store/root-write/child-read-only workflow |
| `.agents/skills/beads/agents/openai.yaml` | Preserve byte-invariant | Historical UI metadata |
| `docs/ADAPTATION.md` | Preserve/adapt | Historical adoption procedure and applicability boundaries |
| `docs/agent-model-routing.md` | Adapt | Sprint routing and conditional independent review |
| `docs/agent-operations.md` | Adapt | Sprint work, conditional assurance, evidence, recovery, and delivery |
| `docs/implementation-standard.md` | Adapt | Supported behavior, focused verification, and completion |
| `docs/repository-language-standard.md` | Adapt | Owned-text clarity and conditional transformation proof |
| `docs/instruction-transformation-evidence.md` | Preserve/adapt | Historical transformation and deletion evidence |
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

The recipe omitted README and manifest rows; both appear above. Frozen packets,
companions, examples, and historical evidence remain preserved. YAML-shaped
examples remain descriptive, not product YAML output.

## Synchronization edges

- Role change: registration, role TOML, validator, routing, and applicable
  current evidence. Mutable role prose is not byte-hashed.
- Permission or hook: config, hook JSON/script, validator, and recovery.
- Thread limit: config, operations, validator, and host capability settings.
- Command, resource, delivery: `PROJECT.md`, Make targets, and closer authority.
- Interface: `ARCHITECTURE.md`, dependencies, compatibility evidence, and
  affected consumers.
- Language or implementation rule: its named authority, affected links, and
  focused evidence.
- Historical byte invariant: exact packet/example or metadata contract only;
  mutable policy uses semantic checks and focused review.

Apply synchronized changes through the owning authority and preserve unrelated
state. Root alone integrates, records rollback, and changes durable work state.
