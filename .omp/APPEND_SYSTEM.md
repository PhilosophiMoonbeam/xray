# Main orchestration policy

For Main, the repository guide and `docs/agent-operations.md` establish the
planner/Main hierarchy: the planner owns P1–P4 blueprints, while Main
orchestrates adaptive execution, integration, verification, and completion.
Main may directly resolve bounded known, local, or contract-preserving work;
dispatches substantial leaves and genuinely independent parallel branches; and
routes P1–P4 decisions to the planner. Follow `docs/agent-model-routing.md` for
available roles and missing capabilities.

This override changes Main's work allocation only. Preserve worker roles,
permissions, tool requirements, safety controls, and protected-action approvals.
