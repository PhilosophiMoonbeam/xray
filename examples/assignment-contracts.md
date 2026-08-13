# Example Assignment Contracts

These examples are non-authoritative. Repository operations and each role TOML
own the contract and output rules.

## Common envelope

```yaml
bead: <preclaimed ID>
outcome_or_question: <one independently useful result>
design_packet: <Bead, version, digest, or exact architecture-neutral authority>
sol_contract:
  behavior: <observable result>
  non_goals: <excluded behavior>
  interfaces_and_invariants: <frozen boundaries>
  compatibility_and_rollback: <requirements and recovery>
  risk_and_reversibility: <material risk and reversal>
base_commit: <immutable SHA>
worktree_branch: <absolute path and branch, or read-only checkout>
writes: <exact paths or none>
acceptance_checks: <commands and observable evidence>
resources: <exclusive allocation or none>
runtime: <observed permissions and behavioral controls>
return: <role schema; at most 12 lines>
overrides: <task-specific differences only>
```

## Route deltas

- `sol_design`: `writes: none`; return packet version, digest procedure,
  architecture changes, evidence, and unknowns.
- `sol_write`: use for semantic-quality-sensitive implementation; return
  commit, paths, checks, risk, and uncertainty.
- `luna_read`: one question, no writes or collaboration; return cited answer,
  contradictions, unknowns, and uncertainty.
- `luna_write`: conventional implementation, no collaboration; return the same
  implementation evidence as Sol write.
- `breakthrough_read`: include the unchanged failure key, exactly two
  evidence-free hypotheses, commands, results, and artifact; return diagnosis
  and next discrimination.
- `terra_verify`: use fresh context after deterministic checks; include the
  unchanged contract, authority, base and artifact SHAs, complete diff,
  evidence, uncertainty, residual risk, allowed read-only operations, and
  observed state. Return findings and untested requirements, never approval.

Every child refuses missing or conflicting fields. Full local permissions do
not widen scope. Root inspects the resulting artifact and decides whether it
can advance to the next protected gate.
