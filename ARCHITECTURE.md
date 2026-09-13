# XRAY Architecture

This file governs XRAY boundaries, dependency direction, public interfaces,
compatibility, storage, and mutation. XRAY 1.0.0 is a Python 3.10+ CLI and
FastMCP stdio server; the multi-agent harness is development infrastructure,
not runtime. `PROJECT.md` selects Development Sprint by default or an
explicitly activated named Enterprise/Certification milestone. Adoption and
next-major packets and companions remain preserved historical evidence; their
procedures apply only to the named milestone selected by PROJECT. Current
contract sections describe implemented behavior, not qualification or delivery
approval. Product examples/workflows remain in [README.md](README.md) and
packaged [guidance](src/xray/guidance.md); this file owns the complete contract.

## System boundaries

```text
shell agents/scripts                    MCP-capable clients
          |                                      |
          v                                      v
 src/xray/cli.py                    src/xray/mcp_server.py
          +--------------------------+
                       v
        models.py + presentation.py + operations.py
                       v
      repository.py + indexer.py + ast_grep.py + replacement.py
                       v
       contained files, optional cache, bounded subprocesses
```

Adapters call public models, presentation, operations, and core services; core
code never imports adapters, installers, skills, reports, tests, or harness
assets. Presentation serializes core values but does not analyze repositories.
Distribution and guidance wrap adapters without becoming their dependencies.
The MCP process opens no listening service; each operation captures its own
root and separate processes share no state.

## XRAY 1.0.0 current contract

The public repository-operation catalog has exactly eleven names:
`capabilities`, `find`, `impact`, `interface`, `map`, `read`, `search`,
`change_plan`, `change_refine`, `change_verify`, and `change_apply`. The first
ten are read-only; only `change_apply` may write repository source. CLI-only
`skill install` is administrative and is not an MCP operation.

Every operation returns the unified `xray.v1` envelope with typed data,
coverage, provenance, and errors. Every change plan is a complete
`xray.change.v1` artifact containing captured inputs, source and selection
identity, bounds, edits, preimages, postimages, diffs, eligibility,
acknowledgements, and canonical SHA-256 `plan_digest`. JSON is the semantic
contract; terminal text is deliberately lossy.

The CLI requires an explicit `ROOT` for repository operations. Its grammar is
`map`, `find`, `interface`, `read`, `impact`, `search`,
`change plan|refine|verify|apply`, `capabilities`, and `skill install`.
`map` navigates, `find` returns complete typed references, `interface` and
`read` consume contained targets, `impact` reports unresolved name
occurrences, and `search` accepts one literal, pattern, rule, or closed config.
There is no automatic root inference, compatibility alias, hidden envelope, or
silent reinterpretation of invalid input.

FastMCP uses standard stdio. Initial `list_tools()` exposes exactly
`search_tools` and `call_tool`; discovery publishes closed call-ready contracts
for the same eleven names, and `call_tool.name` carries the selected operation
outside its closed `arguments` object. Arguments contain no embedded selector.
`xray://workflow`, prompt `xray_discovery_plan`, the packaged skill resource,
and its template are standard MCP guidance surfaces.

All source, rule, config, and typed-reference paths are contained by the
explicit root and are repository-relative POSIX paths. YAML is selected
ast-grep rule/config input only, never product output. Limits, cursors, cache
identity, guarded apply, packaging, and deferred crash/race behavior are
specified in the owning sections below; README supplies usable commands.

## Component and ownership map

| Component | Owned paths | Responsibility and interface | May depend on |
|---|---|---|---|
| CLI adapter | `src/xray/cli.py`, `xray` entry point | Handwritten grammar, validation, JSON/text presentation, and exit mapping. | models, presentation, operations, skill installer |
| MCP adapter | `src/xray/mcp_server.py`, `xray-mcp` entry point | FastMCP stdio, two tools, discovery, resources, prompt, progress, and bounded admission. | models, presentation, operations, FastMCP |
| Application operations | `src/xray/operations.py` | Eleven-operation registry, typed dispatch, capability catalog, intent ranking, and error boundary. | models, presentation, repository, replacement |
| Public models | `src/xray/models.py` | Closed `xray.v1` requests/results, `xray.change.v1` plans, references, coverage, limits, errors, and mutation state. | Pydantic, standard library |
| Presentation | `src/xray/presentation.py` | Canonical JSON, plan/catalog digests, bounded fitting, and cursor validation; no analysis. | public/core value shapes |
| Repository capture | `src/xray/core/repository.py`, `indexer.py` | Root normalization, ignore/exclusion policy, manifest, declarations, bounded reads, and snapshot identity. | filesystem, Git, pathspec, ast-grep boundary |
| Analysis boundary | `src/xray/core/ast_grep.py` | Bounded ast-grep execution, match normalization, validation, and operational errors. | ast-grep executable, subprocess APIs |
| Guarded change service | `src/xray/core/replacement.py` | Complete pattern/rule plans, digest/preimage checks, staged postimages, writes, syntax, and rollback state. | repository, ast-grep, filesystem |
| Cache service | `src/xray/core/cache.py` | Optional content-keyed derived artifacts, private atomic files, fixed ceilings, and performance-only failure. | filesystem, canonical JSON |
| MCP config generator | `mcp-config-generator.py` | Prints supported client JSON; never edits client files or invokes XRAY. | static data, JSON, current path |
| Package and entry points | `pyproject.toml`, `src/xray/__init__.py` | Version `1.0.0`, Python `>=3.10`, dependencies, package data, and two scripts. | setuptools metadata |
| Skill installer | `src/xray/skill_installer.py`, `src/xray/agent_skills/` | User/project skill install; matching files no-op, divergence needs `--force`, symlinks fail, caught swaps restore. | standard library, filesystem |
| Install lifecycle | `install.sh`, `uninstall.sh` | Explicit local-checkout/uv-tool lifecycle; no XRAY source selection through Git or network. | uv, shell |
| Repository CLI skill | `skills/xray-cli/`, packaged copy | Teaches current CLI, bounds, references, containment, paging, and guarded changes; copies are byte-identical. | public CLI contract |
| Workflow skill | `src/xray/skills/xray-progressive-discovery/` | Progressive discovery resource and template. | public MCP contract |
| Tests and fixtures | `tests/`, `test_samples/` | Observable adapter, schema, containment, bounds, cache, change, packaging, and concurrency evidence. | public behavior |
| Audit reports | `.reports/` | Point-in-time observations only; never current authority. | observed artifacts |
| Development harness | `AGENTS.md`, `PROJECT.md`, this file, `TEMPLATE_MANIFEST.md`, `docs/`, `.codex/`, `.agents/`, `Makefile` | Readiness, agent policy, recovery, adoption, and gates; product source does not import it. | repository policy/tools |

Product owners control `src/xray`, packaging, installers, configuration, skills,
and product documentation. Engine owners control capture, containment, cache,
subprocess, and mutation mechanics. Adapters may shape their surfaces but may
not change shared engine semantics; harness owners may strengthen gates but may
not redefine product APIs or schemas.

## CLI contract

Repository commands take `ROOT` followed by their target/query. `capabilities`
may also run rootless for a catalog/health result. The command matrix is the
public shape; exhaustive examples and option spelling are in README and the
CLI skill.

| Command | Required input | Result |
|---|---|---|
| `map ROOT` | optional focus | Bounded namespace entries, no source bodies. |
| `find ROOT QUERY` | name or qualified identity | Ordered declarations with complete typed references. |
| `interface ROOT TARGET` | contained file or typed reference | Bounded declarations, observed import/export syntax, optional docs. |
| `read ROOT TARGET` | location/reference or one-to-eight-target batch | Exact bounded source slices and optional enclosing references. |
| `impact ROOT` | complete captured reference | Exact unresolved name occurrences with evidence and coverage. |
| `search ROOT` | exactly one literal, language pattern, rule, or config | Bounded occurrences, verified captures, and coverage. |
| `change plan\|refine\|verify\|apply ROOT` | pattern or contained rule/config plus bounds | Complete reviewed plan; only `apply` writes. |
| `capabilities [ROOT]` | optional root and detail | Version, language, dependency, and operation health. |
| `skill install` | user or project scope | CLI-only administrative result. |

Selection, focus, language, visibility, exclusion, cache, timeout, page, byte,
source, target, candidate, file, and output controls are positive bounded
values owned by each command. `map` depth is `0..64` or explicit `all`; output
is JSON by default with `schema: "xray.v1"`, while text is lossy. Success exits
`0`, invalid input exits `2`, and stale, containment, operational, analysis,
resource, or mutation failures exit `1`; typed error, coverage, and mutation
fields explain failures rather than an empty success.

## MCP contract and intentional surface differences

`search_tools` supports intent, exact-name, and catalog modes with bounded
pages and opaque catalog cursors. Exact discovery returns a complete closed
argument schema. `call_tool` receives the selected name and that closed object;
FastMCP carries structured results and typed tool errors in its normal result
shape. Only `change_apply` is marked `mutation: "guarded_mutation"`; the other
ten are `mutation: "read_only"`. The adapter is conservatively annotated
because one selected name can mutate.

The MCP names, result meanings, limits, containment, and safety equal the CLI.
MCP-only surfaces are the workflow resource, discovery prompt, packaged skill,
progress, annotations, and cancellation. CLI-only surfaces are shell exits,
lossy formatting, stdin conveniences, and skill administration. No custom
JSON-RPC frame, duplicate operation tools, second schema, or operation field
inside `arguments` is supported.

## Bounds, containment, and cursors

The root must be an existing directory. Parent traversal, outside absolute
paths, symlink escapes, unsupported files, invalid POSIX forms, and uncontained
selection paths fail before capture. Selection uses contained repeated paths,
ordered globs, language filters, and explicit default/disabled exclusions.
Rule admission accepts a standalone YAML rule or one YAML `ruleDirs` mapping;
unknown keys, multiple documents, directories, symlinks, ambient configuration,
custom grammars, and external dependencies are rejected.

Every operation publishes positive limits for pages, bytes, targets, candidates,
files, output, and time. Read accepts one to eight targets; change plans bound
candidates, files, and complete artifact bytes. Dirty-file and new-parser-error
acknowledgements are plan-creation fields and are digest-bound.

Opaque cursors bind operation, normalized root, query, selection, projection,
captured snapshot, and analyzer/toolchain identity. A caller may change page
size, but not bound identity; source/config/policy edits require a new request.
Cursor state has no process-local offset side channel, expiry assumption, or
unbounded session. Response fitting reserves schema, coverage, safety, and
continuation fields before optional display values; an indivisible record or
schema that cannot fit returns a typed budget error.

## Analysis and mutation semantics

`map` is navigation-only: contained files/directories and bounded namespace
metadata, with focus-relative traversal and root-relative reported depth.
`find` matches names or qualified identities and returns a reference binding root,
relative path, byte range, source digest, and analyzer identity. That reference
is the only exact declaration handoff to `interface`, `read`, or `impact`.

`interface` returns bounded declarations, observed import/re-export syntax, and
optional documentation without bodies or module-resolution claims. A clipped
declaration signature or documentation field is identified by
`disclosure.clipped`; the exact reference remains unchanged. `read` returns
exact bytes and line/byte ranges for locations, source, occurrence, or symbol
references, optionally with enclosing identity. `search` accepts exactly one
literal, explicit-language ast-grep pattern, self-contained rule, or closed
`ruleDirs` config; detail adds only verified named captures and reports partial
coverage when limits prevent complete evidence.

`impact` is intentionally unresolved and name-based. Syntax and lexical modes
report exact spelling occurrences and evidence, not callers, dependents, alias
following, type resolution, dependency graphs, or semantic rename behavior.
Parser, unsupported-syntax, non-text, and NUL limitations are coverage, never a
silent mode change.

The lifecycle is one guarded `xray.change.v1` flow. Plan captures the complete
artifact; refine emits a new complete artifact; verify rechecks without writes;
apply independently verifies supplied digest, root/source identity, selection,
file modes, preimages, postimages, syntax, and bounds before each write. The
digest covers canonical root, selection, source/input manifest, bounds, edits,
preimages, postimages, diffs, eligibility, acknowledgements, and all fields
except the digest itself.

Apply stages postimages, checks exclusive regular files, modes, preimages,
postimage bytes, and syntax before/after replacements. Caught failures attempt
conflict-preserving rollback and report authoritative mutation state, but
multi-file apply is not atomic. Races can occur between checks or after writes;
interruption, power loss, or termination can leave partial files and no result.
The caller inspects the worktree and restores a known baseline. XRAY creates no
automatic commits, journal, durable plan, transaction identifier, or background
recovery service.

## Runtime state and resources

XRAY captures on demand from the explicit root. It is not a daemon, project
database, language-server client, type resolver, or unbounded query service.
Optional `DerivedCache` stores only content-derived artifacts below the
platform cache directory (typically `~/.cache/xray/derived` on Linux), using
private atomic files and fixed disk, artifact, payload, age, and memory limits.
Lifecycle eviction runs once at an owning operation boundary rather than on
each artifact access; capacity checks still precede growing writes. Eviction,
corruption, or deletion changes performance, never source identity, plan
eligibility, or semantic truth.

Each rooted operation constructs its own indexer. The MCP adapter rejects
overlapping same-root work before execution and admits independent roots within
the active-operation ceiling; it retains no indexer cache and opens no listener.
Ast-grep and other subprocesses use bounded wrappers. Executable availability,
stdout/stderr, source bytes, file counts, response bytes, and deadlines are
checked at their owning boundary. Operational failures remain typed errors; no
environment variable silently raises a hard limit or creates another contract.

## Distribution and package compatibility

`pyproject.toml` owns version `1.0.0`, Python `>=3.10`, FastMCP, ast-grep,
Pydantic, fuzzy-search, pathspec, and YAML rule-input dependencies. Setuptools
package data includes workflow guidance, progressive discovery, and the CLI
skill plus metadata. The distribution exposes exactly `xray` and `xray-mcp`.
Wheel/sdist metadata, initializer, CLI version, and lockfile must agree; package
gates build both artifacts, verify resources/scripts, install a clean wheel, and
prove removed inactive assets are absent.

`uv tool install` performs no XRAY post-install hook. `xray skill install
--user` or `--project ROOT` retains F3: matching files are a no-op, divergence
needs `--force`, and symlinks fail. Pending v3 specifies Linux
descriptor-relative no-follow operations and `renameat2` no-replace
publication/restoration; caught identity, restoration, or cleanup failures
return I/O errors and may retain private recovery material. It promises neither
crash atomicity nor hostile-writer isolation. `install.sh` accepts only an
explicit local checkout (invoked script or `--checkout DIRECTORY`), may
bootstrap uv/dependencies, replace the uv tool, and update `PATH`; it never
clones, pulls, deletes, or selects XRAY source through Git/network. Remote
one-line installation is deferred. `uninstall.sh` remains the legacy
`$HOME/.xray` deletion path. The config generator prints client JSON only;
stdio cannot become an HTTP/deployment surface by environment.

## Verification and evidence boundaries

Focused tests own the corresponding contracts: `test_cli.py`,
`test_structural_commands.py`, and `test_models.py` cover grammar, envelope,
containment, bounds, cursors, and change requests; `test_mcp_compact.py` covers
standard discovery/calls, resources, annotations, progress, cache parity, and
concurrency; `test_ast_grep.py` covers subprocess normalization and failures;
`test_indexer.py`, `test_repository.py`, and `test_replacement.py` cover
capture, content cache, identity, plans, staged writes, and rollback.

`test_packaging.py` owns release metadata, dependency bounds, scripts, package
data, installed imports, installers, and generated configurations. It also
proves inactive assets and removed current routes do not return. Fixtures cover
Python, JavaScript, TypeScript, and Go and are not shipped product data.

Routine Sprint work selects changed-path tests, relevant type or static checks,
and a real focused CLI process or standard-stdio MCP child for each affected
transport. An in-process MCP client or an idle server is not transport proof.
Governance-only edits do not require product checks when product behavior is
unchanged. The command catalog in `PROJECT.md` lists optional broad checks;
none activates Enterprise/Certification.

The readiness validator requires one `Status: READY`, substantive required
sections, no placeholders, architecture minimum size and contract markers, no
current legacy surfaces, matching release identity, and absent inactive assets.
The Makefile composes available focused/static/full/package/MCP/CLI, harness,
readiness, and cleanliness gates; it does not make every gate a routine
requirement. Transformation evidence and packet digests preserve historical
adoption/qualification claims and are not regenerated by routine edits.

## Synchronized change edges

These updates are one logical change even when paths have different owners:

- CLI commands, options, envelopes, exits, or defaults update the CLI,
  models/presentation, README, both CLI skill copies, focused tests, and MCP
  mapping.
- MCP discovery, tools, annotations, resources, prompts, or concurrency update
  the MCP adapter, workflow skill, README, MCP tests, and smoke/config guidance.
- Core capture, containment, bounds, cache, cursor, result, or mutation changes
  update the owning service, both adapters, models/presentation, annotations,
  tests, and risk evidence.
- Version, dependency, Python-floor, entry-point, or package-data changes update
  metadata, initializer, lockfile, installers, packaging tests, README,
  architecture, and affected smoke gates.
- Asset deletion requires runtime/package-consumer inventory, wheel/sdist
  absence assertions, and current-doc cleanup.
- Harness authority, role, recovery, or gate changes update the affected
  PROJECT/AGENTS policy, `.codex`/`.agents` configuration, validator, standards,
  applicability links, and current evidence. Frozen packets, companions, and
  byte-invariant examples remain unchanged unless their explicitly activated
  Enterprise/Certification contract authorizes a material boundary change.

No descriptive example, audit report, generated snippet, or copied skill changes
behavior alone. Product source and owner tests define observable behavior; this
map describes only behavior implemented and verified.
