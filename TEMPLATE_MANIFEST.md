# Maintained Harness Paths

This is a short inventory, not a portable profile or synchronization protocol.
Update only paths affected by the requested change. Native OMP configuration is
the current harness surface; frozen adoption and qualification records are
preserved history, not current runtime or authority.

## Maintained current paths

| Paths | Purpose |
|---|---|
| `.omp/config.yml` | Intentionally empty project layer; the active OMP profile and runtime own bundled-agent behavior and global task defaults. |
| `.omp/AGENTS.md`, `AGENTS.md`, `PROJECT.md` | Native startup imports, repository guidance, project facts, mode, commands, and authority. |
| `.omp/APPEND_SYSTEM.md` | Planner/Main allocation only; preserves the bundled base prompt, worker roles, permissions, tools, and safety controls. |
| `.omp/validate.py` | Lightweight native configuration and bundled-role inventory check behind `make validate-agent-recipe`. |
| `.omp/validate_project_readiness.py` | Factual readiness check behind `make validate-project-readiness`; it does not impose prose-size quotas. |
| `Makefile` | Maintained non-interactive harness and product command entrypoints; the native harness checks are the two targets above. |
| `.agents/skills/beads/` and `CONTINUE.md` | Durable backlog/recovery guidance and current handoff; Main owns tracker mutation. |
| `docs/agent-operations.md`, `docs/agent-model-routing.md` | Main orchestration, planner triggers, stock-role selection, delegation, recovery, and delivery boundaries. |
| `docs/implementation-standard.md`, `docs/repository-language-standard.md` | Implementation, focused proof, completion, and owned-prose guidance. |
| `docs/ADAPTATION.md`, `TEMPLATE_MANIFEST.md`, `README.md` | Harness maintenance, maintained-path inventory, and concise development links. |
| `ARCHITECTURE.md` | Product interfaces, compatibility, storage, containment, mutation, and current change policy. |

The repository has no custom OMP role files, aliases, model/effort/reasoning
overrides, hooks, retry routes, or SDK qualification evaluator. The installed
OMP CLI supplies the core bundled `task`, `sonic`, `scout`, `reviewer`, and
`security-reviewer` roles; additional bundled roles remain available without a
repository registration. OMP installation, version selection, profile settings,
and effective routing are user-level concerns. The repository neither installs
nor pins the OMP CLI.

## History, not current runtime

Preserve these frozen records and their exact-byte companions. They document
past adoption or proposed qualification decisions; they do not select the
current mode, supply runtime roles, authorize work, or prove I5 acceptance.

| Paths | Classification |
|---|---|
| `docs/adoption-design-packet-v1.md` and `.sha256` | Frozen historical adoption evidence |
| `docs/adoption-design-packet-v2.md` and `.sha256` | Frozen historical harness evidence |
| `docs/next-major-design-packet-v1.md` and `.sha256` | Frozen future-design history |
| `docs/next-major-design-packet-v2.md` and `.sha256` | Frozen future-design history |
| `docs/next-major-design-packet-v3.md` and `.sha256` | Frozen qualification-method history |
| `docs/next-major-design-packet-v4.md` and `.sha256` | Frozen qualification-applicability history |
| `docs/instruction-transformation-evidence.md`, `examples/*.md` | Historical, non-authoritative transformation and reference evidence |

Do not rewrite, regenerate, re-hash, or resurrect these records for routine
Development Sprint work. Rejected findings remain truthful, and a historical
packet, report, example, or tracker record cannot activate paused/deactivated
I5 qualification.

## Preserve-state exclusions

These are not harness reset or synchronization surfaces:

- application source, tests, samples, installers, package resources, skills,
  reports, and generated product evidence;
- repository identity and history in `.git/`, existing dirty work, and Beads
  data, backups, databases, interactions, hooks, and history;
- credentials, provider sessions, user-level OMP state, and external/shared
  resources.

Preserve them in place. Never transplant recipe `.git/` or tracker state,
create a replacement Beads store, or add automatic startup synchronization.
Harness maintenance grants no credentials, production or destructive access,
remote-Git or Beads-remote authority, commit/push/merge, release, publication,
deployment, or other protected delivery authority.
