# XRAY Agent Routing

Use the most specific bundled role listed by the active OMP runtime:

| Core role | Use |
|---|---|
| `task` | General implementation, debugging, repair, and slice-local technical design when no specialist fits. |
| `sonic` | Strictly mechanical edits or data collection with complete instructions. |
| `scout` | Fast, read-only research inside the repository. |
| `reviewer` | Read-only code-quality and correctness review when independent scrutiny matches the risk. |
| `security-reviewer` | Read-only vulnerability review when the changed trust boundary warrants it. |

Additional bundled roles, including closer roles exposed by the runtime, are
part of the same stock inventory. Use them when their runtime description is a
closer match; do not require repository registration or a version-specific role
list. Role choice grants no additional delivery, write, credential, or
protected-resource authority.

## Planner use and blueprint reuse

Classify the next decision under [Agent operations](agent-operations.md)'s
P1–P4 taxonomy. Use the designated deep-design planner only when an
operations trigger requires a fresh or materially changed blueprint, a
stubborn blocker decision, or missing load-bearing semantics. An accepted
blueprint remains authoritative until a real P1–P4 trigger invalidates it.
Main and implementers resolve routine known work and implementation-local
design within that blueprint.

A new session, assignment boundary, first failed repair, ordinary understood
check failure, merge conflict, or restatement request does not trigger
planning. Research and review do not become required stages merely because a
planner was used. Main checks the planner's result once and requests a
specific correction only for a material defect; there is no
planner–reviewer–planner approval carousel.

If the planner capability is unavailable, report the gap and continue work
covered by an accepted blueprint or known solution. Never silently replace it
with a general agent or a model selector.

## Conditional role use

Use `task` or the closest implementation specialist for substantial leaf work,
focused debugging, or a disjoint vertical slice. Agents own
implementation-local design inside the accepted blueprint. Main may directly
investigate, reproduce, repair, integrate, or verify a bounded known solution
when dispatch would add overhead without useful parallelism or expertise; this
does not make Main the default architect. Sonic receives complete instructions
only.

Use `scout` for independent repository discovery that will genuinely shorten
the critical path or spare an expensive scan. Use a suitable available
specialist for external, dependency, or security research. Small lookups
belong inline. Research returns facts and implications, not a competing
blueprint and not an obligatory pre-planner stage.

Use `reviewer` when independent correctness or compatibility scrutiny
materially reduces risk, and `security-reviewer` when identity, authorization,
sensitive-disclosure, trust-boundary, or protected-action changes warrant it.
One risk-matched review at the integrated boundary is preferable to repeated
leaf reviews. Review is not a default gate; a local finding returns directly
to execution, and only a P1–P4 decision returns to the planner. Any
qualification-required independent review remains a separate qualification
obligation until its governing contract is reconciled.

Follow [Agent operations](agent-operations.md) for dispatch, rolling-frontier
coordination, shared-checkout ownership, verification, and recovery. Stock
role permissions remain authoritative; assignment wording cannot turn a
read-only role into a writer.

## Runtime and model selection

Use the designated planning capability when exposed by the runtime; do not
treat a model selector as an agent name. If that capability is unavailable,
report the gap as described above rather than inventing a role. Repository
skills and verification requirements apply inside assignments. Advisor work is
optional and never an approval stage.

Bundled definitions own each agent's tools, spawn permissions, and runtime
behavior. Global model-role selectors are separate from bundled agent names:
they select the model used for a native role, not a repository-defined agent.
The `plan` role selects the model for native planning mode; it does not
automatically dispatch a planner. Advisor assignment is independent from
advisor activation. The project does not require enabling an advisor.

Do not reproduce or freeze stock routing choices in project configuration,
per-task model overrides, or effort hints. The active profile and runtime
determine stock behavior in effect; an empty project mapping does not assert
unchanged defaults. Isolation and other capability choices are global.

The project validator checks only the empty project layer and that an OMP CLI
export contains the required bundled-role inventory. It does not discover the
effective runtime, resolve model roles, or check provider or model health.
Diagnose the installed CLI or active profile rather than creating a project
alias or silently routing specialist work to a different role.

Agent operations owns delegation, shared-checkout coordination, verification,
and durable backlog handling. Role choice grants no additional delivery or
protected-resource authority.
