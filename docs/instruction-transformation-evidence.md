# XRAY Instruction Transformation Evidence

This non-authoritative proof set describes the XRAY instruction
transformation and subsequent recipe sync. Active frozen authority is Design
Packet version 2, Bead `xray-aly`, with its companion digest. Version 1, Bead
`xray-oep.1`, remains immutable historical adoption evidence. The current
recipe source is commit `fcf7d96810960c399696864307b18722c32c25f6`;
XRAY's base remains `d96f0d668c077d2b04d351eaa5bd1abea5f7514f`.
Git retains superseded wording. The working tree keeps one current proof set.

## Source-to-result map

| Source | Current result | Treatment |
|---|---|---|
| Recipe root index and authority boundaries | Target `AGENTS.md` and its standards index | Adapt to XRAY facts; preserve root authority and protected-action boundaries |
| Recipe project readiness and architecture placeholders | Target `PROJECT.md` and `ARCHITECTURE.md` | Replace with verified XRAY facts; do not guess or change product behavior |
| Recipe route classifier and three execution lanes | `docs/agent-model-routing.md` | Retain root-fast, parallel, and high-assurance lanes; use frozen target routes |
| Recipe Beads, contract, allocation, evidence, review, integration, and delivery rules | `docs/agent-operations.md` | Retain; adapt to root plus three children, three writers including root, XRAY tracker preservation, and conservative delivery |
| Recipe supported-behavior standard | `docs/implementation-standard.md` | Retain; name XRAY compatibility baseline, `uv`, and no-YAML constraint |
| Recipe owned-text standard | `docs/repository-language-standard.md` | Retain; distinguish product JSON from descriptive YAML-shaped example |
| Recipe adoption and inventory | `docs/ADAPTATION.md` and `TEMPLATE_MANIFEST.md` | Adapt to XRAY; add omitted README/self rows plus frozen packet/digest rows |
| Recipe examples | `examples/*` | Preserve exact bytes and non-authoritative status |
| Recipe `.git/` and `.beads/` | No target copy | Omit; XRAY tracker history is preserved and normalized independently |
| Recipe committed V2 override and relinquished-resident lifecycle | Root config, validator, routing, operations, adaptation, and target root index | Enable V2 explicitly; adapt replacement capacity to three children and retain the three-writer ceiling |
| XRAY product README | `README.md` | Preserve product body; add one concise harness-orientation section |

## Legacy XRAY proposition map

Every proposition in XRAY base `AGENTS.md`, `.codex/config.toml`, and
`.codex/hooks.json` is accounted for below. A future path names the owning
adoption leaf, not an unverified current artifact.

| Base proposition | Target authority | Treatment |
|---|---|---|
| Beads is durable tracking; use the Beads skill and `bd prime` | Root index, operations, compact Beads skill, SessionStart composer | Retained and strengthened with root-only mutation and bounded current-work recovery |
| Use Context7 for current non-Codex developer documentation | Root index | Retained; official Codex documentation remains the Codex route |
| Use Playwright for applicable browser inspection and verification | Root index and implementation standard | Retained conditionally; it grants no browser-app authority where none exists |
| Prefer bounded, independent delegation with non-overlapping writes | Routing and operations | Retained; allocation now requires frozen contracts, disjoint worktrees, paths, outputs, and resources |
| Prefer `gh` for authorized GitHub operations and never infer remote-mutation authority | Root index, `PROJECT.md`, operations | Retained; local integration authority stays separate from push, merge, release, or deployment |
| Run all Python-related commands through `uv` | Root index, `PROJECT.md`, implementation and adaptation standards | Retained, including the SessionStart Python entry point |
| File and external shell operations must be non-interactive | Root index and `PROJECT.md` canonical commands | Retained as an execution invariant; examples remain literal |
| Codex feature `hooks = true` | Target `.codex/config.toml` and validator | Retained; stable `multi_agent` is added under frozen authority |
| SessionStart directly runs `bd codex-hook SessionStart` for startup/resume/clear | Target hook JSON and composed session script | Replaced by one bounded SessionStart command for startup/resume/clear/compact |
| PreCompact directly runs `bd codex-hook PreCompact` | SessionStart `compact` recovery | Removed as a separate lifecycle group; required recovery behavior is retained after compaction |
| PostCompact directly runs `bd codex-hook PostCompact` | SessionStart `compact` recovery | Removed as a separate lifecycle group; current-work composition replaces generic refresh |
| UserPromptSubmit directly runs `bd codex-hook UserPromptSubmit` | No replacement group | Removed; per-prompt tracker execution is unnecessary latency and not an authority control |

No base proposition silently grants credentials, destructive work, production,
publication, deployment, remote Git mutation, or Beads synchronization. The
transformation does not introduce those permissions.

## Result-to-source map

| Current result | Source authority |
|---|---|
| Frozen routes, role boundaries, thread/writer ceilings, V2 lifecycle, Beads topology, hook design, Claude coexistence, no-CI state, no-YAML, rollback, and delivery limits | Active Design Packet v2 and retained Design Packet v1 decisions |
| Root-fast, parallel, and high-assurance classifier | Recipe routing standard and packet |
| Complete child contract, root-only Beads, disjoint worktrees/resources, exact evidence, two-hypothesis breakthrough, Terra review, serial integration, and protected delivery | Recipe operations standard and packet |
| XRAY supported behavior and compatibility baseline | Base product README, tests, source behavior, and packet |
| `uv`, Context7, Playwright, GitHub CLI, and non-interactive shell guidance | Base XRAY `AGENTS.md`, constrained by project authority |
| Owned-text profiles, strength, vocabulary, bidirectional proof, and size budgets | Recipe Repository Language Standard |
| Exact examples and Beads UI metadata | Packet byte-invariant set at pinned recipe commit |
| Complete target inventory and synchronization edges | Recipe manifest, corrected omissions, packet migration matrix, and Bead acceptance |
| README harness links | `xray-oep.4` outcome and packet product-README decision |

Every result traces to the packet, Bead, recipe clause, or XRAY base
proposition. No result creates a product command, output format, public schema,
database, service, CI system, credential, or external-delivery authority.

## Updated-source decision

The clean recipe advanced from commit `b5643c9` to `fcf7d96` through commits
`448e38e` and `fcf7d96`. The combined patch changes only `AGENTS.md`,
`.codex/config.toml`, and `.codex/validate_agents.py`; its SHA-256 is
`734e1ecb55554b26a7dd621432cee3d096c375b3d19c6b1ea109559a5f9f5a8e`.

The recipe now explicitly enables `features.multi_agent_v2`, rejects a false
override, and distinguishes interruption from immediate slot reclamation. A
completed lane may remain for follow-up. When no follow-up is needed, root
interrupts it to mark the resident relinquished. At a full pool, the next
spawn replaces the least-recently-used unloadable relinquished resident. A
failed replacement after every child lane is relinquished stops delegation and
is reported.

XRAY adopts those propositions while retaining its frozen ceiling of three
children and three concurrent writers including root. OpenAI Docs establishes
the current subagent surface, project-instruction triggering, thread controls,
interruption setting, and client management behavior. Strict Codex 0.147.0
diagnosis accepts the recipe's explicit V2 override. The recipe remains the
evidence for resident replacement details not published in OpenAI Docs.

## Removed and relocated behavior

| Change | Reason and retained control |
|---|---|
| Recipe README body omitted | XRAY's README remains product authority; concise links supply harness orientation |
| Recipe placeholder facts removed | `PROJECT.md` and `ARCHITECTURE.md` must contain verified XRAY facts |
| Recipe five-child ceiling replaced | Frozen host capacity is three children; synchronized configuration and validators enforce it |
| Legacy lifecycle hook groups removed | One SessionStart composer covers all required boundaries with less stale context and latency |
| Personal absolute Beads routing removed | Local `~/.beads-planning` bootstrap preserves canonical history without host-specific policy |
| Recipe tracker state omitted | XRAY identity, history, graph, memory, and recovery material remain project-owned |
| Broad byte preservation rejected | Only packet-named materially invariant artifacts are hashed; adapted paths use semantic evidence |

## Validation scenarios

| Scenario | Expected result |
|---|---|
| Project is `NOT_READY` and application editing is requested | Stop outside authorized harness/profile/architecture work |
| Child attempts Beads mutation, descendant creation, peer coordination, integration, or delivery | Stop and reject the lane |
| Concurrent writers share a path, generated output, worktree, or resource | Do not allocate concurrently |
| Completed child needs no follow-up | Interrupt it; mark its resident relinquished without claiming immediate slot reclamation |
| Full three-child pool needs replacement | Replace the least-recently-used unloadable relinquished resident on the next spawn |
| Replacement fails after every child lane is relinquished | Stop delegation and report V2 residency failure |
| Exactly two evidence-free hypotheses retain one failure key | Stop implementation and route the complete packet to `breakthrough_read` |
| Terra finds no counterexample | Treat the result as evidence, not approval |
| YAML-shaped assignment example is present | Keep it descriptive; product output remains JSON/text only |
| Required check cannot run without an authorized alternative | Report the gap and do not claim completion |
| Delivery authority is absent | Stop after local verification |
| Every requirement and exact-candidate gate is proven | Root may accept, integrate, and close under current authority |

## Size and integrity evidence

Counts use `wc -w -c`; words and bytes are deterministic proxies, not model
token counts. The corpus is the six adopted docs, `TEMPLATE_MANIFEST.md`, and
three examples. It excludes product README body, product code, `.beads/`, Git
internals, generated state, and Python automation.

| Corpus | Words | Bytes | Interpretation |
|---|---:|---:|---|
| Current recipe source corpus | 5,792 | 42,896 | Current authority and descriptive material at `fcf7d96` |
| XRAY adapted corpus | 6,413 | 47,416 | Adds target facts, recipe-sync traceability, and corrected inventory |
| Base product README | 2,536 | 18,965 | Preserved product body baseline |
| README after concise orientation | 2,568 | 19,429 | Adds 32 words and 464 bytes without replacing product content |

The three examples must match the packet hashes exactly. Final focused
evidence includes example SHA-256 checks, complete Markdown-link existence,
UTF-8/LF/trailing-whitespace/final-newline hygiene, calibrated file budgets,
stale-reference searches, `git diff --check`, and the complete diff. Final
integration qualification remains bound to one unchanged candidate SHA.
