# Example Beads DAG

This example is non-authoritative. Dependencies represent required results, not
priority, hierarchy, or scheduling preference.

```text
feature epic (coordination only)
|
+-- A: freeze and implement shared contract
    |
    +-- B: update client one -------+
    +-- C: update client two -------+--> E: cross-layer qualification
    +-- D: update visual consumer --+
    +-- F: operator documentation
```

After creating the issues, add only these blocking edges:

```bash
bd dep add B A
bd dep add C A
bd dep add D A
bd dep add F A
bd dep add E B
bd dep add E C
bd dep add E D
```

Implement A first because it owns the interface. After root integrates A, B,
C, D, and F can proceed when their write sets and resources are disjoint. Root
integrates their artifacts serially, then runs E in an exclusive candidate
worktree.

Do not chain independent siblings to manufacture a wave. Formatter changes,
fixture corrections, deterministic feedback, and bounded review repairs remain
inside the Bead whose acceptance requires them.
