# XRAY Implementation Standard

## Outcome and scope

Meet current requirements with the lowest total complexity and diagnostic cost
allowed by authority. Apply this standard only after the readiness gate permits
implementation. It grants no authority and does not override closer
instructions. Apply the Repository Language Standard to changed owned text.

**Supported behavior** is externally observable behavior required by task or
repository authority, an authoritative owned specification, compatibility or
deployment requirements, persistent-data constraints, or a required upgrade
path. Existing code, tests, releases, data, and consumers are evidence of
possible support; they do not create authority alone.

XRAY's current compatibility baseline includes compact `xray.cli.v2` JSON,
full/v1 behavior, JSON and `jq` pipelines, documented CLI/MCP semantics and
surface differences, path containment, bounded results and cursors,
name-based impact analysis, safe rewrite and `scan --fix` mutation, package
entry points and data, Python 3.10+, and optional `/tmp/.xray_cache` behavior.
YAML output is not supported and this harness adoption does not add it.

## Required actions

1. Make the smallest complete change that satisfies current requirements.
2. Build end-to-end increments that keep affected behavior testable and
   understandable.
3. Before a material behavior change, identify affected behavior and use
   applicable evidence to determine support and compatibility.
4. Preserve supported behavior after each increment.
5. Remove obsolete code, tests, configuration, and documentation unless
   supported behavior requires them.
6. Enforce each introduced or changed invariant in its owning component.
7. Validate untrusted input at each introduced or changed trust boundary.
   Duplicate enforcement only across independent trust or failure boundaries.
8. Handle or surface each introduced or changed operational failure through the
   established error mechanism.

Preserve persistent user data unless explicit authority permits deletion or
reinterpretation. Implement required data changes explicitly. Retain a
migration only for supported behavior, data preservation, or an authorized
upgrade path.

Before adding a dependency or custom implementation, inspect current
documentation, types, and capabilities of existing dependencies. Prefer an
existing maintained dependency when it lowers total implementation and
maintenance cost without a blocking defect.

Add focused tests when existing infrastructure can verify changed requirements
or a reproduced regression. Test observable behavior instead of implementation
details when both provide equal precision.

## Prohibited actions

Do not:

- retain obsolete runtime paths, fallbacks, compatibility layers, migrations,
  or tests without supported behavior;
- add abstractions, configuration, indirection, or extension points for
  hypothetical requirements;
- add production code that requirements mandate replacing later, unless
  authority requires temporary code with a recorded removal condition;
- restructure an unaffected component for preference compliance;
- discard a failure unless authority defines it as irrelevant;
- classify an unexplained check failure as unrelated;
- weaken, skip, or bypass a required check.

## Verification

Run every project gate for the affected scope and the narrowest additional
checks that cover materially changed behavior. Run the narrowest available
end-to-end workflow when the environment provides one.

Run Python, tests, builds, and Python tooling through the canonical `uv`
commands in `PROJECT.md`. Commands must be non-interactive. Use Playwright only
when browser behavior is in scope and current repository authority supplies the
application and command.

If a required check cannot run, report the command, reason, unverified
behavior, and any authority-permitted alternative. Do not mark completion when
a required check lacks a passing authorized alternative. Treat a failure as
unrelated only with evidence; report the failure and remaining uncertainty.

Update affected owned documentation. Record temporary production code in an
owned version-controlled artifact with its location, reason, and observable
removal condition.

For user-facing behavior, verify applicable loading, empty, success,
validation, error, accessibility, console, network, persistence, and responsive
states. A passing browser test does not prove semantic or spatial quality.

## Stop and completion

After inspecting available evidence, stop when at least two plausible readings
would materially change behavior, authority, scope, risk, compatibility,
output, acceptance, or delivery. Report the governing source, evidence,
interpretations, consequences, and recommendation. Continue when evidence
resolves the question or all choices are reversible, in scope, and
behaviorally equivalent.

Implementation is complete only when:

1. every applicable requirement and supported behavior is satisfied;
2. verification finds no covered regression;
3. every required gate passes or an authorized alternative passes;
4. focused tests cover changed requirements and reproduced regressions;
5. the narrowest applicable end-to-end workflow passes;
6. no unsupported obsolete implementation remains;
7. required data and upgrade paths remain valid;
8. affected documentation matches behavior;
9. the final report identifies checks, limitations, and uncertainty.
