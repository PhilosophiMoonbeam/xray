# XRAY Implementation Standard

## Outcome and scope

Meet current requirements with the lowest total complexity and diagnostic cost
allowed by authority. Apply this standard only when PROJECT permits the work.
It grants no authority and does not override closer instructions. Apply the
Repository Language Standard to changed owned text.

**Supported behavior** is externally observable behavior required by the task,
repository authority, an owned specification, compatibility, deployment, or
persistent-data constraint. Existing code, tests, releases, data, and consumers
are evidence of possible support; they do not create authority alone.

XRAY 1.0.0 remains the compatibility baseline: unified `xray.v1` JSON,
complete `xray.change.v1` plans, eleven CLI/MCP operations, standard FastMCP
stdio discovery through two adapter tools, explicit-root containment, bounded
results and snapshot-bound cursors, unresolved name-based impact, guarded
changes, package entry points and resources, Python 3.10+, and optional
content-derived `DerivedCache` artifacts. YAML is contained rule/config input
only and is never product output. XRAY does not add a language server,
type-aware dependency graph, daemon, project database, automatic commits, or
background recovery service.

## Required actions

1. Make the smallest complete change that satisfies the requested outcome.
2. Build an end-to-end increment that keeps affected behavior testable and
   understandable.
3. Before material behavior changes, identify affected behavior and support,
   compatibility, authorization, and data-preservation consequences.
4. Preserve supported behavior after each increment.
5. Remove obsolete in-scope code, tests, configuration, and documentation.
6. Enforce each introduced or changed invariant at its owning component.
7. Validate untrusted input at each introduced or changed trust boundary.
8. Handle or surface each introduced operational failure through the established
   error mechanism.

Preserve persistent user data unless explicit authority permits deletion or
reinterpretation. Implement required data changes explicitly. Retain a
migration only for supported behavior, data preservation, or an authorized
upgrade path.

Before adding a dependency or custom implementation, inspect current
documentation, types, and capabilities of existing dependencies. Prefer an
existing maintained dependency when it lowers total implementation and
maintenance cost without a blocking defect.

Add a focused permanent test when existing infrastructure can verify changed
behavior or a reproduced regression and the test protects a plausible future
failure. Otherwise use a throwaway behavioral smoke. Test observable behavior,
not implementation details, when both provide equal precision.

## Prohibited actions

Do not:

- retain obsolete runtime paths, fallbacks, compatibility layers, migrations,
  or tests without supported behavior;
- add abstractions, configuration, indirection, or extension points for
  hypothetical requirements;
- restructure an unaffected component for preference compliance;
- discard a failure without evidence or weaken a required product guard;
- expand scope, authority, resources, or delivery claims because a broad check
  or old qualification item exists.

## Verification

Select the narrowest checks covering changed behavior and materially affected
boundaries. Routine Sprint completion uses:

- changed-path tests for observable behavior and relevant regressions;
- the applicable type or static check for changed code and its contract
  surface;
- a real focused CLI process for CLI-facing changes;
- a real standard-stdio `xray-mcp` child, initialized through a throwaway
  client, for MCP-facing or shared behavior;
- consistent affected consumers, documentation, and configuration;
- a focused negative case when validation, authorization, containment, or
  mutation failure behavior changed.

An in-process MCP `Client(mcp)` test or an idle server does not prove stdio
transport behavior. Shared changes need one focused scenario on each affected
public transport. Do not run every operation, language, cache state, or corpus
without an affected-contract reason.

Run Python, tests, builds, and Python tooling through the `uv` commands in
`PROJECT.md`. Package metadata, dependencies, entry points, installers,
resources, or version-sensitive primitives require an isolated installed
package smoke and a Python-floor check relevant to the claim. Routine source
work does not require an offline multi-interpreter qualification matrix.

Governance-only edits need no product smoke, build, or product test when
product behavior is unchanged. Review changed authority, links, scenarios, and
applicable configuration syntax. Report unavailable checks with the exact
prerequisite, unverified behavior, and authorized alternative. An unavailable
required changed-path proof prevents claiming that path complete; unrelated
pre-existing failures remain recorded evidence, not an unbounded repair task.

For an authorized instruction change, concise rationale, changed authoritative
rules, and scenario review are sufficient unless an explicitly activated
Enterprise/Certification milestone names a formal evidence contract. Exact
artifact hashes, complete transformation maps, attestation ledgers, and broad
qualification are not routine verification.

## Risk-proportional safeguards

Escalate the actual risk, not the label of the task. Seek a planner decision,
specialist review, focused negative proof, disposable-root checkpoint, or
recoverable backup when changing a trust boundary, untrusted parser/config
input, secret handling, subprocess permission, source mutation, installer,
rollback, cancellation, persistent data, compatibility floor, package
boundary, shared schema/API, or outcome-ambiguous write.

Back up before a real destructive or persistent-data transition. Do not back up
every read or edit ceremonially. Never retry an uncertain mutation merely to
discover whether it applied; establish the authoritative outcome first.

## Stop and completion

After inspecting available evidence, stop when unresolved intent, authority,
scope, risk, compatibility, output, acceptance, or delivery has two plausible
readings that would change behavior. Report the governing source,
interpretations, consequences, and recommendation. Continue when evidence
resolves the question or all choices are reversible and in scope.

Stop the affected action for unavailable authorization, a prohibited operation,
an uncertain destructive target, a material contract conflict, contradictory
evidence, an unexplained introduced regression, or an unsafe/outcome-ambiguous
mutation. Do not use missing qualification artifacts, a missing per-task Bead,
document-count ceiling, inactive benchmark population, or fixed retry quota as
a routine blocker.

Ordinary product work is complete only when:

1. requested acceptance criteria are met;
2. changed-path tests pass, including a retained regression test when warranted;
3. the relevant type or static check passes;
4. the real focused CLI and/or MCP smoke covering each affected public
   transport passes;
5. affected consumers, documentation, and configuration are consistent;
6. no introduced or acceptance-relevant material defect remains; and
7. actual checks, limitations, risks, and unverified claims are reported.

Stop there. Do not automatically run the full suite, whole-repository static
analysis, package matrix, `make qualify`, historical G/Q populations, exact
candidate sealing, replay, or independent review rounds. An explicitly
activated Enterprise/Certification milestone instead uses its named existing
acceptance contract and records a truthful result without granting delivery
authority.
