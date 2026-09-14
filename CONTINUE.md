# XRAY next-major I5 qualification — paused recovery

## Next-session directive and authority

I5 qualification is explicitly paused and deactivated. I5 acceptance has not
occurred, and this file is a recoverable record rather than current
qualification authority. Do not claim I5, execute W4-W6, rebuild or reseal a
method, or begin a qualification ceremony from this handoff. Do not restart
completed product implementation or repeat resolved qualification repairs.

Recover Bead `xray-5e7.34` read-only when durable qualification history is
needed. Parent Bead `xray-5e7` remains open because I5 acceptance is
incomplete. A separately selected qualification outcome in `PROJECT.md` must
name the assurance objective, acceptance contract, candidate, and authority
before Main may decide whether any qualification work resumes.
Main alone mutates or closes Beads; any stock OMP worker uses `bd --readonly`
only for cited recovery context.

The current repository mode is Development Sprint. Sprint work may proceed
under `AGENTS.md`, `PROJECT.md`, `ARCHITECTURE.md`, and native OMP policy.
Historical packets, rejected methods, old commands, Beads, and worker
availability do not select or accept I5.

Commit, push, merge, release, deployment, publication, production access,
credentials, GitHub mutation, and Beads Dolt push/pull remain unauthorized.
This recovery file grants no delivery authority.

## Repository and candidate state

- Repository: `/home/bbferko/repos/xray`
- Branch recorded by this handoff: `main`
- Parent Bead `xray-5e7` remains open because I5 acceptance is incomplete.
- Method Bead `xray-5e7.34` remains `in_progress` and contains the durable
  qualification history.
- Preserve unrelated dirty state; do not assume that the current checkout is
  clean or that a prior commit/push is an authorization.
- The XRAY 1.0.0 Development Sprint candidate and its historical results are
  not I5 evidence. Qualification, if separately selected later, must bind and
  test the exact candidate it accepts.

## Rejected sealed method state

There is no accepted or mutable active method root. Preserve every existing method and evidence root. Do not edit, rebuild, rebind, reseal, or execute a qualification phase from a rejected sealed root.

The latest rejected sealed method is:

`/home/bbferko/.cache/xray-evidence/xray-5e7/qualification/v4-method-adjudicated-mcp-shutdown-zero-gate-clean-workflow-bound-closed-runtime-semantic-replay-shutdown-strict-exit-records-policy-state-proof-leaf-stable`

Its sealed identity is:

- Dual method-manifest SHA-256: `911536c409a1641f0b5bfc7c7f0914896e689f82387b59e759e9fad9e8520869`
- Binding SHA-256: `d5c9ace9dd93f277e16c764d3c66d2035933fb494a822ae2e7773909bc02ea3a`
- Inventory SHA-256: `86b604ed271587799a140a47c9ad2fe74be22447adfbddb4cb923188993a469e`
- Inventory: 50,224 entries and 18,796,587 bytes
- Dual manifests: byte-identical regular files, mode `0444`
- Generated static outputs: 16 regular files, mode `0444`
- Forbidden method-local caches: none

Pre-seal evidence for that root was otherwise green:

- Independent state and filesystem-safety review: ACCEPT; 13 decisive tests passed.
- Independent raw-prewarm, journal-partition, and relocation review: ACCEPT; 9 decisive tests passed.
- Broad non-static suite: 75 passed, 7 deselected, and 27 subtests passed.
- Decisive raw-proof, relocation, and filesystem matrix: 13 passed.
- Scoped Ruff with `--no-cache`: passed.

The one-time sealed full suite returned `185 passed, 1 failed, 46 subtests passed`. The sole failure was:

`tests/test_review_aggregate.py::test_relocated_aggregate_copies_gate_closure_byte_identically_and_replays_without_subprocess`

The sealed root is rejected. No post-seal edit, repair, rebuild, or reseal occurred.

## Recorded blocker and accepted diagnosis

The failure is deterministic and belongs to the qualification method, not the product candidate. Two independent read-only reviews reproduced it in about 0.4 seconds. It fails closed with:

`BundleError: gate registry score identity differs from aggregate support`

`tools/controller.py` records the original absolute method root in `roles.tools.capture_method_root`. That field is capture provenance. `tools/bundles.py::_close_score_identity` intentionally validates relative tool files against copied support while preserving that provenance. However, `seal_aggregate` currently constructs its comparison identity with the temporary `stage/support` directory as `method_root`. Exactly three values then differ from the authentic gate receipt:

- `roles.tools.capture_method_root`
- the derived `roles.tools.sha256`
- the derived top-level `binding_sha256`

All relative tool-file identities are byte-identical. Replacing the capture root with a staging or publication path would destroy provenance and make the identity publication-path-dependent.

Relevant spans in the rejected sealed root:

- `tools/bundles.py:438` — `_close_score_identity`
- `tools/bundles.py:1302` — incorrect aggregate comparison identity construction
- `tools/bundles.py:1315` — identity equality failure
- `tools/controller.py:559` — `capture_method_root` binding
- `tests/test_review_aggregate.py:191`, `:257`, and `:280` — fixture, seal, and relocation assertions

## Pending successor repair contract

If Main later receives a separately selected qualification outcome, create a new
writable successor from the rejected sealed root. Never mutate the sealed
source. Confine the semantic repair to `tools/bundles.py` and the regression
coverage to `tests/test_review_aggregate.py` unless new evidence proves a wider
dependency.

In `seal_aggregate`:

1. Preserve the score receipt's authoritative original `capture_method_root`.
2. Validate every relative tool-file identity against the copied aggregate
   `support` root.
3. Re-close the tools file list and role contracts using copied support bytes
   while retaining the receipt's capture root.
4. Recompute the tools-role and top-level binding digests.
5. Require exact equality with the gate receipt identity before publishing
   `support/bindings/score-identity.json`.

The preferred implementation is to pass the already validated projected receipt
identity into `_close_score_identity(..., support=support)`. Do not relax
identity equality, rewrite the provenance root, require the original method
directory during relocated replay, normalize exit evidence, or copy the
projected identity without revalidating every relative support file.

Pending focused acceptance:

1. The existing relocated-aggregate test passes unchanged through publication,
   source-method removal or relocation, and subprocess-free replay.
2. The aggregate score identity is byte-identical to the gate receipt.
3. `capture_method_root` remains the original source root and contains no
   staging or publication path.
4. The same identity validates against relocated `aggregate/support`.
5. Changed copied-support bytes fail validation.
6. An altered and fully rehashed capture root fails validation.
7. Adding, removing, or reordering a support tool fails validation.
8. Existing gate-registry replay, state-proof relocation, tamper, and
   failure-retention tests pass.
9. Focused Ruff runs with `--no-cache`, and the method contains no generated
   cache artifacts.

## Resumption conditions

No qualification action is currently authorized. If Main later records a
separately selected qualification outcome, the dependency order is:

1. Recover Bead `xray-5e7.34`, this file, and the rejected sealed-root identity
   read-only. Confirm the sealed root remains unchanged before copying it.
2. Create a fresh writable successor root only under that separately selected
   outcome. Record its derivation from the rejected sealed manifest and
   inventory; do not reuse the rejected root's identity as acceptance evidence.
3. Apply the bounded aggregate identity repair and pending focused acceptance
   above, then obtain the required independent acceptance review.
4. Do not launch W4, W5, or W6, run a qualification ceremony, or claim I5
   until the selected outcome authorizes those stages and the successor has
   passed its complete sealed acceptance. This handoff contains no executable
   W4-W6 automation, and it grants no commit or push authority.

## Preserved terminal evidence

Preserve the terminal W4 diagnostic26 evidence at:

`/home/bbferko/.cache/xray-evidence/xray-5e7/qualification/v4-w4-diagnostic-26-b6b1de7-153adabc-stable`

It contains 56 attempts and 56 bundles. Its candidate seal is:

`/home/bbferko/.cache/xray-evidence/xray-5e7/qualification/v4-candidate-seal-16-b6b1de7-153adabc.json`

Candidate-seal SHA-256: `4ba7dec698799adc644bbd6640159ff47c910c4da4babf064333480c4ddb8f06`.

Diagnostic26 produced zero gate cases because replay rejected truthful idempotent disabled-state preparation. It is terminal diagnostic evidence only. Do not rebind, reuse, or present it as qualification acceptance. Earlier rejected method and evidence roots recorded in Bead `xray-5e7.34` are also immutable.

## Stop conditions

No qualification stage is active. If a separately selected outcome later
authorizes resumption, stop the affected stage for an unbound candidate or
method, stale manifest, missing or duplicate population key, incomplete gold,
ambiguous attempt, unresolved P0/P1 finding, changed frozen contract, unsafe
mutation, contradictory evidence, unexpected sealed-suite failure, or missing
authority. Do not launch W4 or W5 before the fresh successor passes complete
sealed acceptance. Do not claim I5 from Sprint tests, historical counts,
partial populations, or a scorer whose inputs are not completely bound.

## Authoritative references

- `PROJECT.md` and `ARCHITECTURE.md` — current Sprint mode and product boundaries
- `docs/next-major-design-packet-v1.md` through v4 and companions — preserved
  I5 acceptance contract only if a separately selected outcome activates it
- `docs/implementation-standard.md` — implementation and verification requirements
- `docs/agent-operations.md` — evidence, review, integration, and delivery boundaries
- Bead `xray-5e7.34` — durable qualification history and incomplete current claim

`CONTINUE.md` is the live recovery surface, not an archive. Keep only current authority, exact recovery state, unresolved work, material evidence, and the next dependency-ordered actions.
