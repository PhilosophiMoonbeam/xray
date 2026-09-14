# XRAY Repository Language Standard

Write direct, concise instructions and technical prose. State the actor,
required outcome, and important conditions when they are not obvious. Keep each
rule in its owning document and link to it elsewhere instead of copying it.
Use examples to illustrate policy, not to introduce hidden requirements.

Distinguish requirements from preferences and permissions. Use `must`, `should`,
and `may` consistently; do not strengthen a preference or silently remove an
authority boundary during editing. Prefer clear headings and short paragraphs
over rigid templates or size targets.

Use `Main` for the coordinating agent, stock role names for workers, `goal` and
`todo` for session work, and `Bead` for a durable backlog item. A dependency
means an outcome actually requires another outcome. Evidence is an observed
result or cited source, not an approval. Protected approval belongs to the
human or policy controlling that action, not to a model family.

Preserve XRAY's literal product content: `uv` commands, `xray` and `xray-mcp`
entry points, CLI and MCP operation names, JSON schemas and fields, explicit
root terminology, paths, identifiers, external names, quotations, and
supported behavior. YAML-shaped assignment examples are descriptive harness
notation; YAML remains selected rule/config input and is never XRAY product
output. Do not rewrite generated, vendored, third-party, or tracker-internal
text as prose cleanup. Avoid unrelated application changes.

State security, authorization, containment, persistent-data, mutation, and
delivery boundaries exactly. Do not let a role, example, check, or evidence
claim grant protected authority. Keep one current workflow authority:
agent-operations owns orchestration, dispatch, verification, recovery, and
handoff; this standard governs language only.

Review changed meaning and references. A substantial authorized policy change
should briefly explain intentional removals and remaining boundaries; it needs
no transformation maps, word or byte budgets, artifact hashes, count reports,
or duplicate validation report. Git history preserves superseded wording.
