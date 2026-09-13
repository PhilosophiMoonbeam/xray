# XRAY next-major Enterprise/I5 qualification

## Next-session directive and authority

Resume active Bead `xray-5e7.34`. The immediate outcome is a fresh qualification-method successor that repairs the deterministic aggregate relocation defect described below, passes independent review and the complete sealed method suite, and then advances through W4, W5, and W6. Do not restart completed product implementation or repeat resolved qualification repairs.

`PROJECT.md` activates the named **XRAY next-major I5 qualification** milestone. Its assurance objective is whole-product I5 acceptance against the preserved next-major v1-v4 contract, including G1-G8, on one unchanged candidate. This activation does not claim I5 acceptance.

The user has authorized add, commit, and push checkpoints to the current branch. Merge, release, deployment, publication, production access, credentials, and Beads Dolt push/pull remain unauthorized.

## Repository and candidate state

- Repository: `/home/bbferko/repos/xray`
- Branch: `main`
- Last pushed code-bearing checkpoint: `b6b1de7428a504f384cef57ef7d4b75c3deb3218`
- The working tree was clean before this `CONTINUE.md` update.
- Parent Bead `xray-5e7` remains open because I5 acceptance is incomplete.
- Method Bead `xray-5e7.34` remains `in_progress` and contains the durable qualification history.

The XRAY 1.0.0 Development Sprint candidate is implemented and pushed. Qualification must bind and test the exact candidate it accepts. Sprint test results and historical qualification runs are not I5 evidence.

## Current qualification method state

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

## Active blocker and accepted diagnosis

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

## Fresh-successor repair contract

Create a new writable successor from the rejected sealed root. Never mutate the sealed source. Confine the semantic repair to `tools/bundles.py` and the regression coverage to `tests/test_review_aggregate.py` unless new evidence proves a wider dependency.

In `seal_aggregate`:

1. Preserve the score receipt's authoritative original `capture_method_root`.
2. Validate every relative tool-file identity against the copied aggregate `support` root.
3. Re-close the tools file list and role contracts using copied support bytes while retaining the receipt's capture root.
4. Recompute the tools-role and top-level binding digests.
5. Require exact equality with the gate receipt identity before publishing `support/bindings/score-identity.json`.

The preferred implementation is to pass the already validated projected receipt identity into `_close_score_identity(..., support=support)`. Do not relax identity equality, rewrite the provenance root, require the original method directory during relocated replay, normalize exit evidence, or copy the projected identity without revalidating every relative support file.

Required focused acceptance:

1. The existing relocated-aggregate test passes unchanged through publication, source-method removal or relocation, and subprocess-free replay.
2. The aggregate score identity is byte-identical to the gate receipt.
3. `capture_method_root` remains the original source root and contains no staging or publication path.
4. The same identity validates against relocated `aggregate/support`.
5. Changed copied-support bytes fail validation.
6. An altered and fully rehashed capture root fails validation.
7. Adding, removing, or reordering a support tool fails validation.
8. Existing gate-registry replay, state-proof relocation, tamper, and failure-retention tests pass.
9. Focused Ruff runs with `--no-cache`, and the method contains no generated cache artifacts.

## Dependency-ordered next actions

1. Recover Bead `xray-5e7.34`, this file, and the rejected sealed-root identity. Confirm the sealed root remains unchanged before copying it.
2. Create a fresh writable successor root. Record its derivation from the rejected sealed manifest and inventory; do not reuse the rejected root's identity as acceptance evidence.
3. Implement the bounded aggregate identity repair and focused regressions above.
4. Run focused aggregate, gate-registry, state-proof relocation, tamper, and failure-retention tests plus Ruff `--no-cache` with all caches outside the method root.
5. Obtain independent changed-findings review. Do not advance with any P0 or P1 finding.
6. Run the broad pre-seal suite. Update only required frozen producer identities, validate their exact semantic closure, then run the canonical static builder and inventory builder once.
7. Run the complete sealed method suite and independent sealed-method acceptance review. Abandon the sealed root on any unexpected failure; never repair or reseal it.
8. Only after sealed acceptance, run a wholly fresh W4 diagnostic and gate phase under new absent run, candidate-seal, gate, and runtime paths. Do not reuse diagnostic26 or any prior seal.
9. Reconcile every W4 result. Run W5 production populations only after W4 acceptance: 3,000 candidate trials, 2,600 paired native-baseline trials, the focused latency/RSS/source populations, C13 traversal, and G1-G8 evidence.
10. Run W6 immutable aggregation, scoring, relocation/replay, independent acceptance review, and truthful local I5 adjudication.
11. Update Beads and this file at each recoverable checkpoint. Commit and push the current branch while the user's delivery authority remains active.

## Preserved terminal evidence

Preserve the terminal W4 diagnostic26 evidence at:

`/home/bbferko/.cache/xray-evidence/xray-5e7/qualification/v4-w4-diagnostic-26-b6b1de7-153adabc-stable`

It contains 56 attempts and 56 bundles. Its candidate seal is:

`/home/bbferko/.cache/xray-evidence/xray-5e7/qualification/v4-candidate-seal-16-b6b1de7-153adabc.json`

Candidate-seal SHA-256: `4ba7dec698799adc644bbd6640159ff47c910c4da4babf064333480c4ddb8f06`.

Diagnostic26 produced zero gate cases because replay rejected truthful idempotent disabled-state preparation. It is terminal diagnostic evidence only. Do not rebind, reuse, or present it as qualification acceptance. Earlier rejected method and evidence roots recorded in Bead `xray-5e7.34` are also immutable.

## Stop conditions

Stop the affected stage for an unbound candidate or method, stale manifest, missing or duplicate population key, incomplete gold, ambiguous attempt, unresolved P0/P1 finding, changed frozen contract, unsafe mutation, contradictory evidence, unexpected sealed-suite failure, or missing authority. Do not launch W4 or W5 before the fresh successor passes complete sealed acceptance. Do not claim I5 from Sprint tests, historical counts, partial populations, or a scorer whose inputs are not completely bound.

## Authoritative references

- `PROJECT.md` and `ARCHITECTURE.md` — active mode and product boundaries
- `docs/next-major-design-packet-v1.md` through v4 and companions — I5 acceptance contract
- `docs/implementation-standard.md` — implementation and verification requirements
- `docs/agent-operations.md` — evidence, review, integration, and delivery boundaries
- Bead `xray-5e7.34` — durable qualification history and current claim

`CONTINUE.md` is the live recovery surface, not an archive. Keep only current authority, exact recovery state, unresolved work, material evidence, and the next dependency-ordered actions.
