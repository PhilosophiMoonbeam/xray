# XRAY Multi-AgentV2 Recipe Sync Design Packet

Version: 2
Decision Bead: `xray-aly`
Status: FROZEN
Frozen: 2026-08-13

This packet supersedes version 1 as the active material design authority for
the XRAY harness. Version 1 remains immutable historical adoption evidence.
Every version 1 decision, interface, invariant, compatibility boundary,
resource rule, ownership rule, and rollback rule remains in force unless this
packet explicitly replaces it.

The companion `docs/adoption-design-packet-v2.sha256` contains the lowercase
SHA-256 of this file's exact bytes. Recompute it with:

```bash
sha256sum docs/adoption-design-packet-v2.md
```

## Authority and provenance

| Item | Frozen evidence |
|---|---|
| User authority | Sync and adapt XRAY from the updated `/home/bbferko/repos/multi-agentV2_recipe`, including Codex subagents and other applicable harness concerns |
| XRAY Bead | `xray-aly`, claimed by root on 2026-08-13 |
| Prior packet | Version 1, Bead `xray-oep.1`, SHA-256 `8b01ffd63c5d5f76936ffe873e6be2114e38ff6af1ea4e13a3d9a6993fc9eda0` |
| Prior recipe commit | `b5643c9138985701d404688e21309e04d85a83ee` |
| Current recipe commit | `fcf7d96810960c399696864307b18722c32c25f6` |
| Current recipe tree | `e912dcd7c4899c989d5276e8f0ff9b0b8491eba0` |
| Current recipe state | Clean `main`, equal to `origin/main` |
| Recipe delta | Commits `448e38e` and `fcf7d96`; only `AGENTS.md`, `.codex/config.toml`, and `.codex/validate_agents.py` changed |
| Delta patch SHA-256 | `734e1ecb55554b26a7dd621432cee3d096c375b3d19c6b1ea109559a5f9f5a8e` |
| Codex runtime | `codex-cli 0.147.0`; strict doctor accepted the recipe and XRAY configurations on 2026-08-13 |
| Official documentation | OpenAI Docs, `https://learn.chatgpt.com/docs/agent-configuration/subagents`, fetched 2026-08-13 |

Current recipe artifact hashes are:

| Path | SHA-256 |
|---|---|
| `AGENTS.md` | `b1472ab97d1d0b90f6dd47014d6d1e43872fd0779a1c4a6fc9f1f4d1af65ab7c` |
| `.codex/config.toml` | `16fe5bdd44e2bcf300bf0c131d3cc85f67f9324cb2d963977abe40a5e973176e` |
| `.codex/validate_agents.py` | `6a34594c8a95187ccbba1fbe5ad69308c2edb91327bbd59371bbe3b4ecfc58b5` |

## Outcome and supported behavior

XRAY adopts the recipe's restored MultiAgentV2 lane replacement behavior. The
root configuration explicitly enables `features.multi_agent_v2`; the semantic
validator rejects a disabled or missing override; and every active lifecycle
authority uses the relinquished-resident replacement contract below.

XRAY remains the same Python code-intelligence CLI and MCP server. Version 1's
product compatibility baseline, six role definitions, root route, three-child
ceiling, three-writer ceiling, root-only Beads mutation, recovery design,
permissions, delivery boundary, and byte-invariant set remain unchanged.

## Frozen changes

### V2 feature selection

`.codex/config.toml` sets both `features.multi_agent = true` and
`features.multi_agent_v2 = true`. The explicit V2 override selects the recipe's
lane replacement implementation on Codex 0.147.0. The target-specific
`agents.max_concurrent_threads_per_session = 3` remains unchanged.

`.codex/validate_agents.py` requires the exact synchronized feature table and
contains a negative self-test that sets `multi_agent_v2 = false`. The validator
must reject that V1 lifecycle case.

### Relinquished-resident lifecycle

MultiAgentV2 has no V1 `close_agent` tool. Root may retain a completed child
thread for follow-up. When no follow-up is needed, root interrupts the completed
lane. Interruption marks the lane as relinquished but does not itself reclaim
the resident slot.

When the three-child pool is full, the next spawn replaces the
least-recently-used unloadable relinquished resident. If replacement fails after
every child lane is relinquished, root stops delegation and reports the V2
residency failure. Interruption is eligibility for replacement, not immediate
slot reclamation.

## Non-goals and unchanged authority

This sync does not change role TOMLs, role routing, models, effort levels,
child descendant restrictions, the delegation classifier, writer allocation,
hooks, session recovery, Claude compatibility, Beads topology, product source,
public behavior, packaging, tests, CI state, or delivery authority. It does not
copy recipe `.git/` or `.beads/` state.

Official OpenAI documentation establishes the current subagent surface,
project-instruction triggering, thread controls, interruption setting, and
client management behavior. It does not document resident replacement
internals or the `features.multi_agent_v2` compatibility override. The clean
recipe artifact and strict Codex 0.147.0 diagnosis are the frozen evidence for
those two recipe-specific details.

## Interfaces, ownership, and synchronization

Root owns this packet, its digest, Beads state, integration, qualification, and
delivery. The sync is one serial root-fast change over the existing uncommitted
adoption candidate. No child assignment or concurrent write is required.

The following paths form one synchronized artifact:

- `.codex/config.toml` and `.codex/validate_agents.py`;
- `AGENTS.md`, `PROJECT.md`, and `TEMPLATE_MANIFEST.md`;
- `docs/ADAPTATION.md`, `docs/agent-model-routing.md`, and
  `docs/agent-operations.md`;
- this packet, its companion digest, and
  `docs/instruction-transformation-evidence.md`.

The validator must retain both packet versions and validate both companion
digests. Runtime authority links target version 2; version 1 stays available as
historical evidence.

## Risk, compatibility, and rollback

Primary risks are a feature-table mismatch that silently restores the V1
lifecycle, lifecycle prose that treats interruption as immediate reclamation,
or evidence that overwrites the frozen version 1 history. Exact feature-table
validation, a negative V1 case, bidirectional transformation evidence, and both
packet digests mitigate those risks.

Rollback removes only the version 2 packet and companion, restores the
pre-sync bytes of the synchronized paths above, and reactivates version 1. It
must preserve the pre-existing XRAY adoption candidate, canonical Beads
history, and all product files. No rollback action may copy tracker state from
the recipe or perform a remote Git or Dolt operation.

## Acceptance and evidence

The integrated artifact must prove:

1. the recipe delta maps completely to XRAY without unrelated recipe changes;
2. strict Codex diagnosis accepts the explicit V2 override;
3. the validator accepts the repository and rejects `multi_agent_v2 = false`;
4. active lifecycle text consistently uses relinquished-resident replacement;
5. both packet companion digests, governed-file hygiene, budgets, links, and
   byte invariants pass;
6. affected harness gates and `git diff --check` pass;
7. complete status and diff review finds no product behavior change or
   unexplained path.

Local success grants no commit, push, merge, release, deployment, GitHub
mutation, publication, production action, or Beads Dolt synchronization.
