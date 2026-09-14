# XRAY Implementation Standard

## Implement the requested outcome

Make the smallest complete change that meets current requirements. Inspect the
existing implementation, relevant contracts, and current dependency
capabilities before introducing another pattern. Keep related behavior
understandable and avoid abstractions, configuration, or compatibility paths
for hypothetical use.

Preserve supported behavior and persistent user data. Make authorized schema or
data transitions explicit. Remove obsolete code, callers, tests,
configuration, and documentation when the change supersedes them; do not
retain a second path without a real compatibility requirement.

Enforce invariants in their owning component. Validate untrusted input at trust
boundaries, duplicating enforcement only across independent trust or failure
boundaries. Handle failures through the established error mechanism rather than
suppressing symptoms. Respect tool rules, ownership, and protected authority.
Resolve material ambiguity from available evidence; ask only when the
remaining choice would change the requested behavior, scope, or authority.

## Blueprint and local decision boundary

Implement against the current accepted blueprint. The planner owns a fresh
blueprint or materially changed design only under the P1–P4 triggers in
[agent operations](agent-operations.md). A current blueprint remains valid
until one of those triggers actually invalidates it.

Within a settled blueprint, Main and implementers own bounded execution and
implementation-local design. Preserve the blueprint's acceptance, interfaces,
invariants, authority, and persistent-data transitions; a contract-preserving
local refactor or known repair does not need a new planner decision. Main may
repair and integrate a known solution directly when dispatch adds no useful
parallelism or expertise. A material contract change or stubborn blocker
returns to agent operations; do not turn ordinary work into a planner or
reviewer gate.

## Verification tiers

Select the lowest tier that proves the changed claim, then record the exact
claim and limitations:

- **V0 — Policy, documentation, or mechanical.** Check changed references,
  links, JSON/configuration, commands, and the relevant maintained harness
  contract. Prose-only workflow edits do not require an application build,
  database, browser, live-model, or full test-suite run.
- **V1 — Focused behavior.** Run affected maintained checks and one actual
  exercise of the changed path. For UI work, use the actual affected surface
  and materially affected interactions or recovery states rather than every
  historical viewport and state combination.
- **V2 — Load-bearing integrated boundary.** Perform V1 plus the affected
  real containment, authorization, migration or upgrade, rollback or recovery,
  package, provider-contract, architecture, generated-data, build, browser,
  or transport lane. Choose by the changed contract and invalidated evidence,
  not by diff size; use independent risk-matched security or correctness
  review when warranted.
- **V3 — Explicit qualification.** Run the exact-candidate full software,
  scale, release, browser, performance, or operations gates when the
  requested claim reaches them, with separately authorized provider or
  operating procedures. Preserve complete existing gate semantics and fail
  closed when required evidence is missing.

V0–V2 completion is not full qualification, release readiness, operating
evidence, provider approval, or protected authorization. Those are separate
claims and remain open until their own requirements are executed. XRAY I5
qualification is paused/deactivated until an authorized acceptance reactivates
it; historical and rejected evidence remains truthful and is never relabeled
as acceptance.

## XRAY changed-path requirements

Preserve XRAY's supported product contract: Python 3.10+, `uv`-only Python
commands, the unified `xray.v1` envelope, complete `xray.change.v1` plans,
eleven CLI/MCP operations, standard FastMCP stdio discovery through exactly two
adapter tools, explicit-root containment, bounded results and snapshot-bound
cursors, unresolved name-based impact, guarded changes, package resources and
entry points, and optional content-derived caches. YAML is rule/config input
only and is never product output.

CLI-facing changes require a real focused `uv run xray` subprocess against an
explicit small fixture or authorized root. MCP-facing or shared behavior
requires a real `uv run xray-mcp` standard-stdio child initialized through a
throwaway client, with discovery of the two adapter tools and a call to the
changed operation. An in-process MCP client or idle server is not transport
proof. Add a focused negative case when validation, authorization,
containment, subprocess permission, or guarded mutation behavior changes.

Do not introduce a language server, type-aware dependency graph, daemon,
project database, automatic commits, or background recovery service. Preserve
the current subprocess bounds, timeouts, output limits, error classification,
and explicit authorization for protected actions.

## Verify once at the appropriate boundary

During concurrent editing, children skip tests, builds, lint, formatters, and
other validation. Main verifies after integration. Select affected maintained
checks and a focused exercise of changed behavior; avoid running overlapping
check chains merely to collect more receipts. Release and protected-delivery
requirements still apply when that work is in scope.

For a bug, use the reported failure or a reproduction to guide the fix and
confirm the changed path no longer fails. Keep a regression test when it
guards a plausible recurrence. For a feature, update existing tests whose
observable contract changes and exercise the new behavior. Add a permanent
test for a real boundary, invariant, failure, or uncertain edge case—not for
every edit or to assert implementation details. A focused smoke exercise can
be sufficient for a straightforward new path.

For UI changes, inspect the actual affected surface and interactions,
including loading, error, empty, keyboard, responsive, or persistence states
only when materially affected. For documentation or harness configuration,
check the changed references, configuration, or command rather than unrelated
application behavior. Agent operations supplies batch coordination and
integrated verification.

If a check fails, investigate the cause without weakening the check. If a
required check cannot run, report the command, exact blocker, unverified
behavior, and any useful alternative evidence. Do not claim proof that was
not obtained or treat a passing review as execution evidence.

## Implement before broad qualification

Build complete local increments without waiting for provider-console access,
customer pilots, production rehearsal, or unrelated release suites. Use
documented provider contracts and explicit conservative development
assumptions; keep protected effects disabled until their real activation
conditions are met. Missing external approval is not a blanket prohibition on
repository work. Missing security semantics that determine who gains
authority remain a genuine boundary: do not invent a permissive policy or
substitute a successful stub.

Exercise changed behavior locally before handing it off. That focused proof
does not certify live interoperability, operating outcomes, or production
safety. When broader verification is deferred, record the unverified claim,
exact remaining scenario, prerequisites, assumptions, and next action in the
canonical Beads handoff when durable state is needed. An initial
implementation may be available for further development while its
qualification remains pending. Report those states separately; do not
describe the whole product outcome as complete or production-ready.

## Complete and report

Complete the requested behavior, migrate affected callers, preserve required
data paths, and update relevant documentation. Main reviews material changes
and evidence without a separate acceptance form. The report identifies the
outcome, checks actually run, and unresolved risks or blockers. No commit,
push, production mutation, or deployment is implied by local completion.
