# XRAY Next-Major Design Packet — Fidelity Delta

Version: 2
Decision Bead: `xray-5e7.1`
Parent Bead: `xray-5e7`
Status: FROZEN DESIGN — NOT IMPLEMENTED
Decision date: 2026-09-10
Historical product base: `01d195486fd7f38d54f718735f44ac6301b88689`
Current runtime contract: XRAY 0.11.4
Implementation: Authorized under `xray-5e7`; not implemented by this packet

## Outcome and scope

This packet is the active version-2 fidelity delta for the next-major design. It
restores the already-selected call-ready catalog, standard FastMCP semantics,
and a closed administrative result for the retained CLI-only skill installer.
It is a documentation artifact, not product implementation, qualification, or
protected-delivery approval. Version 1 and its companion remain immutable
historical evidence; the version-1 digest is
`c860367da05d61069726b9d4fe7d79e030031dfcc16990a786d2062d28ed7331`.

This packet supersedes version 1 only for F1–F3 and their named dependent
decisions and gates. Every unaffected D01–D14 decision, interface, invariant,
compatibility boundary, resource rule, ownership rule, rollback rule, frozen
threshold, and limitation is inherited explicitly. Within F1–F3, this packet
replaces conflicting version-1 text; it never requires a session URI to recover
selected meaning. The seven capability families and eleven repository
operations remain unchanged:
`map`, `find`, `interface`, `read`, `impact`, `search`, `change_plan`,
`change_refine`, `change_verify`, `change_apply`, and `capabilities`.

Python 3.10+, the `xray` and `xray-mcp` entry points, handwritten CLI, stdio
MCP, JSON and `jq` workflows, repository containment, captured-byte analysis,
all existing future bounds, clean-major deletion, and the no-journal,
no-recovery-operation, no-daemon, no-task-service, no-protocol-replacement,
no-compatibility-layer, and no-installer-redesign boundaries remain unchanged.
I1–I4 are unshipped candidate increments; no later operation is advertised or
stubbed. Whole-product acceptance is at I5. XRAY 0.11.4 remains current runtime
authority until I5 acceptance. Implementation is authorized under `xray-5e7`,
but this packet grants no protected delivery authority.

The only corrections in this delta are complete call-ready
`OperationContract`/`SchemaDocument` publication, standard FastMCP discovery,
invocation, framing, resources, prompts, progress, cancellation, and error
mapping, and a separate closed administrative success/error result for
`skill_install`. All other version-1 decisions inherit without alteration.

## Authority and provenance

The authority set is linked locally from this packet:

| Authority | Role |
|---|---|
| [Version-1 packet](next-major-design-packet-v1.md) | Immutable next-major design and the inherited D01–D14 contract. |
| [Version-1 companion](next-major-design-packet-v1.sha256) | Immutable lowercase SHA-256 evidence for version 1. |
| [PROJECT.md](../PROJECT.md) | Current readiness, ownership, commands, compatibility, and delivery authority. |
| [ARCHITECTURE.md](../ARCHITECTURE.md) | Current component, interface, compatibility, storage, and mutation authority. |
| [Repository Language Standard](repository-language-standard.md) | Required vocabulary, strength, literal preservation, and transformation evidence. |
| [Adoption Design Packet v2](adoption-design-packet-v2.md) | Current harness adoption authority; this product delta does not replace it. |
| [Version-2 companion](next-major-design-packet-v2.sha256) | Exact lowercase SHA-256 companion generated only after this packet is final. |

The decision is Bead `xray-5e7.1`, under parent Bead `xray-5e7`. The binding
technical source is FinalArchitect's closed F1–F3 adjudication, corroborated by
the frozen packet's D02, D03, D05, D07, D10–D13, the current FastMCP and MCP
artifacts, and the inspected CLI and skill-installer paths. The historical
packet's base identity is `01d195486fd7f38d54f718735f44ac6301b88689`; that
identity is provenance, not a claim that the current working tree is clean.

Precedence is: applicable user or governing authority; the binding Chief
delta over the initial Chief packet where they conflict; FinalArchitect's
adjudication for F1–F3; ValuePlanner's critique and evidence without silent
override; and this repository-owned packet for the selected F1–F3 meaning.
A later authorized design delta must name the affected decision and gate; it
may not silently change a frozen threshold or boundary. This packet supersedes
version 1 as active next-major authority only for F1–F3 and their named
dependent decisions and gates. Version 1 remains immutable historical evidence.
XRAY 0.11.4 remains current runtime authority until complete implementation
passes I5. Implementation is authorized under `xray-5e7`; this artifact is not
implementation, qualification, or protected-delivery approval.

The packet's shared notation retains version-1 D03 unless a correction below
says otherwise: `Digest` is 64 lowercase hexadecimal SHA-256 characters;
canonical JSON uses UTF-8, sorted object keys, compact separators, no ordinary
Unicode ASCII escaping, and one final LF only for CLI framing; all modeled
objects are closed; Boolean integers, NaN, floats, null-as-omission, implicit
coercion, and unspecified fields are forbidden. Repository `Error`,
`RepositoryProvenance`, `Root`, operation query branches, result shapes, plan
shapes, bounds, and error details remain the exact version-1 D03/D04/D07/D09
contracts except where F1–F3 explicitly replace them. No session URI is needed
to reconstruct that inheritance.

## Frozen fidelity corrections

The following three findings are the only normative homes for this delta. Each
other section references F1, F2, or F3 and does not publish a competing schema.

### F1 — OperationContract optional-root and complete call-ready input-schema contradiction

F1 replaces the conflicting version-1 D03 `OperationContract` and capabilities
operation element, and the version-1 D10 wire-catalog wording that allowed
symbolic schema names instead of a complete callable schema. The selected typed
request semantics remain unchanged.

**Closed catalog types.** The exact types are:

- `Operation = map | find | interface | read | impact | search | change_plan | change_refine | change_verify | change_apply | capabilities`.
- `MutationClass = read_only | guarded_mutation`.
- `OperationArguments` is the selected operation's closed version-1 `Request`
  with only `op` removed. It retains `root`, `query`, applicable `page`, and
  `execution` with every existing operation-specific constraint. It adds no
  wrapper and no transport-specific budget field.
- `OperationSummary = {name:Operation,description:string,mutation:MutationClass}`.
- `OperationContract = {name:Operation,description:string,mutation:MutationClass,input_schema:SchemaDocument}`.
- `SchemaDocument` is a complete JSON Schema Draft 2020-12 document whose root
  validates `OperationArguments` for exactly one operation.
- `CatalogProvenance = {catalog:Digest,query?:Digest}`. `query` is required on
  successful `search_tools` and omitted on `capabilities`; this replaces the
  incompatible version-1 catalog-provenance branch. Repository provenance is
  otherwise unchanged.

`OperationSummary` and `OperationContract` are closed objects. Every
`description` is one nonempty sentence, contains no newline, and is at most
256 UTF-8 bytes. Only `change_apply` has `mutation=guarded_mutation`; every
other repository operation has `mutation=read_only`. `capabilities` permits
both an absent `root` and an explicit valid `root`. Every other repository
operation schema requires `root`. There is no separate required/forbidden
root enum in the public catalog.

Each `input_schema` contains every required argument, accepted branch, default,
allowed value, applicable bound, and operation-specific prohibition. `query`
remains required as in the version-1 `Request`; rootless capabilities therefore
uses `arguments={query:{}}`. `Request.root` is the normalized absolute root at
the core/MCP boundary. The CLI may accept a relative root only as shell input
and normalizes it before constructing that request. Change operations continue
to forbid `page`. Response budgets stay in their existing operation request
homes, such as `page.max_bytes` or `PlanBounds.max_bytes`; there is no
`call_tool.max_bytes`.

`capabilities` detail contains `operations:OperationSummary[]`, sorted by
operation name using UTF-8 byte order, exactly one summary for each implemented
repository operation and eleven at final I5. Summary capabilities omit
`operations`. Capabilities do not duplicate eleven full schemas. The ordinary
Python `OperationSpec` owns typed models, handlers, description, canonical CLI
spelling, and contract-bearing metadata. Its public projection is exactly
`OperationContract`; internal CLI spelling and result-model references do not
create public fields.

**SchemaDocument.** The document has `"$schema":"https://json-schema.org/draft/2020-12/schema"`, an optional `$defs`, and only the allowed SchemaDocument or SchemaNode keywords below. The root schema is an object. Allowed SchemaNode keywords are:

`$ref`, `type`, `properties`, `required`, `additionalProperties`, `const`,
`enum`, `anyOf`, `oneOf`, `items`, `prefixItems`, `minItems`, `maxItems`,
`uniqueItems`, `minLength`, `maxLength`, `pattern`, `minimum`, `maximum`,
`description`, and `default`.

The only instance types are `object`, `array`, `string`, `integer`, and
`boolean`. References are local `#/$defs/...` references, all resolvable in
the same document; external URLs, unresolved symbolic names, schema fetches,
and cyclic definitions are forbidden. Canonical future bounds are 14,336
UTF-8 bytes for the document, 64 definitions, depth 64, and 2,048 JSON nodes.
Every modeled instance object is closed. The opaque initial
`call_tool.arguments` carrier is the explicit transport-publication exception
in F2; it is validated against the selected closed operation before execution.

Canonicalization sorts and deduplicates `required` arrays by UTF-8 string
order, sorts and deduplicates `enum`, `anyOf`, and `oneOf` branches by their
full canonical JSON value, preserves `prefixItems` order and actual default
semantics, and sorts object keys through the shared canonical serializer.
Describe UTF-8 byte bounds, absolute and contained path rules, byte-boundary agreement, and cross-field constraints that this subset cannot express in the applicable schema descriptions. Enforce those constraints at the same typed request boundary. JSON Schema `maxLength` is not a UTF-8-byte measure, and no second schema DSL is introduced.

The complete contract plus its envelope must fit discovery's existing 16,384-
byte hard ceiling. If it cannot fit a caller's smaller budget, return
`budget_too_small` with `minimum_bytes` when calculable; never remove a required
constraint. The catalog identity is exactly
`SHA256(canonical_json(['xray.catalog.v1',contracts,discovery_artifact]))`,
where `contracts` is the complete `OperationContract` array sorted by name and
`discovery_artifact` is the SHA-256 of the exact installed `operations.py`
bytes. The small catalog and deterministic discovery-ranking implementation and
metadata are owned there. Changing callable constraints, ranking inputs, or
ranking code changes catalog identity. Compute this immutable identity once per
loaded artifact, not once per repository query.

The rejected alternatives are a three-value root metadata enum, symbolic
`query_schema`/`result_schema` names requiring a second fetch or registry,
eleven duplicated full schemas in capabilities or initial `tools/list`, a
plugin registry, a JSON-operation DSL, and independently handwritten CLI/MCP
contract tables. F1's sole replacements are the closed types and complete
`SchemaDocument` above.

### F2 — custom two-method JSON-RPC framing contradicts retained standard FastMCP resources/prompts/progress/cancellation

F2 replaces version-1 D03 custom `SearchToolsRequest`, `SearchToolMatch`,
`SearchToolsResult`, `CallToolRequest`, custom frame/result aliases, version-1
D05 catalog-cursor interpretation where necessary, and version-1 D10 wording
that made `search_tools`/`call_tool` the only protocol methods or implied a
transport-specific invocation budget. Standard FastMCP and standard MCP SDK
semantics are retained.

**Closed discovery and invocation schemas.** The exact discovery request is:

`SearchToolsRequest = {mode?:'intent',query:nonempty_string,limit?:int[1,10],max_bytes?:int[4096,16384],cursor?:string} | {mode:'exact',query:Operation,max_bytes?:int[4096,16384]} | {mode:'catalog',limit?:int[1,10],max_bytes?:int[4096,16384],cursor?:string}`.

The exact successful discovery value is:

`SearchToolsSuccess = {schema:'xray.v1',ok:true,op:'search_tools',provenance:{catalog:Digest,query:Digest},data:{best?:OperationContract,alternatives:OperationSummary[]},page:{total:int>=0,next_cursor?:string},coverage:{state:'complete',basis:'capabilities'}}`.

The exact repository invocation request is
`CallToolRequest = {name:Operation,arguments:OperationArguments}`. The exact
catalog checkpoint is `CatalogCursor = base64url_without_padding(canonical_json({version:1,op:'search_tools',catalog:Digest,query:Digest,after:Operation}))`, with a maximum encoded length of 4,096 bytes. The shared error operation discriminator is
`ErrorOperation = Operation | search_tools | call_tool | skill_install`;
`skill_install` is CLI-only under F3 and is never an MCP invocation.

All request branches are closed. `mode` defaults to `intent`, `limit` to 3,
and `max_bytes` to 4,096. An intent query is nonempty after normalization and
is 1–1,024 UTF-8 bytes. `exact` forbids `limit` and `cursor`; `catalog` forbids
`query`. The former argument keys `pattern`, `intent`, `operation`, and
`detail`, and the former mode values `regex`, `search`, `enumerate`, and
`detail`, are not accepted. The mode value `intent` remains valid and is the
default. Normalize intent by casefolding, replacing underscore with a space,
splitting on whitespace, and joining tokens with one ASCII space; do not add
Unicode normalization. Exact mode uses the exact canonical operation name.
Catalog mode uses the empty string as normalized query.

The query digest is
`SHA256(canonical_json(['xray.mcp.search_tools.v1',mode,normalized_query,catalog]))`.
`limit`, `max_bytes`, and `cursor` are excluded. Rank the complete finite
catalog deterministically before paging. Retain the selected calibrated
intent-ranking approach, canonical name tie-break, `change_plan` preference
for ordinary change intent, and explicit apply discovery. Do not publish
scores, tags, or explanation traces.

Every nonempty page starts with one complete `best` contract. Remaining
returned candidates are `alternatives` summaries; a default search has at most
two alternative records, and the limit counts `best` plus alternatives. Exact
mode returns one best, no alternatives, total 1, and no cursor. An empty intent
result has no best, `alternatives=[]`, total 0, complete capabilities coverage,
and no cursor. Catalog enumeration is in canonical operation-name order.
`page.total` is exact for the full selected catalog or ranked candidate set,
never the page. Fit the best contract and complete envelope before adding whole
alternatives; an insufficient budget is `budget_too_small`, not a summary-only
success. A later page again supplies its first remaining contract in full.

A cursor seeks after the last actually returned operation, including a summary
alternative. A caller may change positive page size or byte budget. Validate
current catalog and query before seeking: a changed catalog is `stale_cursor`,
a changed mode or query is `cursor_query_mismatch`, and a nonexistent
checkpoint is `invalid_cursor`. Exact-name discovery of an unknown or removed
operation returns `unknown_operation`; no legacy exact-name backdoor remains.

The initial MCP descriptor publishes the two-field `call_tool` shape with
`name` and an opaque JSON-object `arguments` carrier; it does not inline all
eleven operation schemas. Once `name` is recognized, validate `arguments`
against that operation's complete closed schema without coercion, normalize to
`{op:name,...arguments}`, and reject `arguments.op`, unknown fields,
irrelevant controls, invalid integers, Boolean integers, and null-as-omission.
Recognize a supplied `change_apply` name before validating its remaining
arguments so every recognized change-apply failure retains mandatory top-level
R04 `mutation`. Return the selected core semantic result unchanged: do not add
`kind`, `value`, a transport-success wrapper, or a second budget wrapper. A
malformed routing request before operation recognition uses `op=call_tool`;
recognized-operation errors use that operation; discovery errors use
`op=search_tools`. Unknown or removed names are `unknown_operation`. Neither
`skill_install` nor any retired operation is present in repository invocation
or discovery.

**Shared domain errors.** F2 and F3 use the version-1 `xray.v1` error contract
with the corrected operation union:

`Error = {schema:'xray.v1',ok:false,op?:ErrorOperation,root?:Root,error:{code:ErrorCode,message:string,at?:string,action?:RecoveryAction,details?:ErrorDetails},mutation?:ChangeApplyMutation,provenance?:EstablishedProvenance}`.

Errors contain no data, page, success coverage, or success-shaped fallback.
`op`, `root`, and provenance appear only when established. The exact error-code
set is `invalid_request`, `unknown_operation`, `path_outside_root`, `not_found`,
`excluded_input`, `unsupported_file`, `unsupported_configuration`,
`invalid_pattern`, `invalid_rule`, `invalid_encoding`, `invalid_reference`,
`stale_reference`, `invalid_cursor`, `cursor_query_mismatch`, `stale_cursor`,
`source_changed`, `dependency_unavailable`, `io_error`, `timeout`,
`execution_limit`, `analysis_limit`, `budget_too_small`, `invalid_plan`,
`plan_drift`, `plan_inapplicable`, `mutation_conflict`, `apply_failed`, and
`internal_error`. `RecoveryAction` is one of `correct_input`,
`refresh_reference`, `restart_query`, `narrow_query`, `install_dependency`,
`inspect_worktree`, or `report_bug`; at most one action appears, with no
retryability Boolean, next-action list, automatic retry, or action graph.

`ChangeApplyMutation = {state:MutationFailureState,rollback_status:RollbackStatus,plan_digest?:Digest}`. `RollbackStatus` is
`not_attempted | succeeded | failed`; `MutationFailureState` is
`not_applied | rolled_back | partially_applied | indeterminate`. The invariants
are `not_applied` iff `not_attempted`, `rolled_back` iff `succeeded`,
`partially_applied` iff `failed` with known remaining changes, and
`indeterminate` iff `failed` when final bytes cannot be established. Before the
first target write, every recognized `change_apply` failure has
`state=not_applied` and `rollback_status=not_attempted`. Verified restoration is
`rolled_back`/`succeeded`; failed restoration with known remaining changes is
`partially_applied`/`failed`; inability to establish final bytes is
`indeterminate`/`failed`. `plan_digest` appears only after supplied digest
validation. For recognized `change_apply`, `error.details.plan_digest` is
forbidden, including in a plan-kind detail; only `mutation.plan_digest` may
contain it. There is no `rollback_evidence` field.

**Standard FastMCP contract.** Retain FastMCP and the standard MCP SDK; the
declared dependency remains `fastmcp>=3.4.7,<4`, with inspected lock versions
FastMCP 3.4.7 and MCP 1.28.1. `tools/list` exposes exactly two tools,
`search_tools` and `call_tool`; repository operations are dispatched by the
ordinary XRAY catalog, not registered as hidden MCP tools. Calls use standard
MCP `tools/call`, for example:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"call_tool","arguments":{"name":"capabilities","arguments":{"query":{}}}}}
```

Discovery also uses `tools/call`, for example:

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_tools","arguments":{"mode":"exact","query":"read"}}}
```

For semantic value `V`, the standard `CallToolResult` has
`structuredContent=V`, `content=[{type:'text',text:canonical_json(V)}]`, and
`isError=(V.ok==false)`. Text has no CLI framing LF. Required protocol text
mirrors that same value and is not a second independently interpreted semantic
result. FastMCP owns initialization, request IDs, JSON-RPC envelopes, standard
protocol errors, stdio framing, negotiated metadata, resource and prompt
methods, progress, and cancellation. D03's closed XRAY objects and no-float or
no-null rules do not redefine standard MCP protocol values.

The retained standard methods and notifications are:
`initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call`,
`resources/list`, `resources/templates/list`, `resources/read`, `prompts/list`,
`prompts/get`, `notifications/progress`, and `notifications/cancelled`. This is
a retained required surface, not a replacement closed JSON-RPC allowlist.
`search_tools` and `call_tool` are tool names, not JSON-RPC methods. No
background-task, HTTP, or recovery service is introduced. Retained addresses
are `xray://workflow`, `xray_discovery_plan`,
`skill://xray-progressive-discovery/SKILL.md`, and
`skill://xray-progressive-discovery/{path*}`.

Malformed JSON-RPC, unavailable protocol methods, and unknown outer MCP tool
names use standard framework protocol behavior; they are not fabricated XRAY
repository results. After the XRAY `call_tool` discriminator is recognized,
domain failures use the shared Error and R04 rules. Initial annotations are:

| Tool | `readOnlyHint` | `destructiveHint` | `idempotentHint` | `openWorldHint` |
|---|---:|---:|---:|---:|
| `search_tools` | true | false | true | false |
| `call_tool` | false | true | false | false |

`call_tool` is conservatively destructive because it can apply source changes;
the selected operation's mutation class is carried by discovery, not guessed
from intent. Use FastMCP's public Tool extension point to receive the raw
argument mapping and perform strict XRAY validation before coercive function
binding. One thin Tool adapter class with two registered instances belongs in
`mcp_server.py`. Set `strict_input_validation=False` so generic framework
validation cannot replace a recognized-operation error; this delegates domain
validation to the strict XRAY boundary and does not omit validation.

Use the existing FastMCP server with `strict_input_validation=False`,
`dereference_schemas=False`, and `tasks=False`. Preserve ordinary
resource/prompt registration. Do not replace private handlers, write a custom
JSON-RPC parser, or fork the protocol. Use supported ToolResult
`content`, `structured_content`, and `is_error` fields, whose wire names are
`content`, `structuredContent`, and `isError`; do not construct an additional
XRAY result wrapper. Retain every D07 request, semantic-response, error,
execution, admission, and concurrency ceiling. Protocol mirroring and framing
are separately measured overhead, not permission to ignore admission bounds.
Failure to prove the actual framework path blocks its implementation gate; it
does not silently change a bound.

The removed XRAY-owned protocol types and restrictions are `McpRequestId` as
an XRAY-owned restriction, `SearchToolMatch`, `SearchToolsCallResult`, the
custom `CallToolResult` wrapper, `McpRequestFrame`, `McpResponseFrame`, and the
custom closed protocol-error frame and two-method allowlist. Rejected
alternatives are a handwritten two-method JSON-RPC server, unreachable
standard methods documented beside a FastMCP replacement, coercive binding or
generic framework text for recognized `change_apply` failures, and invisible
registration of legacy or future tools hidden only from discovery.

### F3 — retained CLI-only skill install lacks a closed replacement after xray.cli.v1 deletion

F3 completes the retained CLI-only administration that version-1 D02 and D11
preserve while replacing the deleted `xray.cli.v1` envelope. It changes no
analysis operation, MCP surface, source-change plan, or installer transaction
mechanics.

The exact handwritten grammar is
`xray skill install [--user | --project ROOT] [--force] [--pretty]`. Default
scope remains user, default output remains JSON, and existing flag semantics
and destination selection remain. The closed success value is:

`AdministrativeSuccess = {schema:'xray.v1',ok:true,op:'skill_install',data:{scope:'user'|'project',target:string,changed:bool,replaced:bool,files:['SKILL.md','agents/openai.yaml']}}`.

All objects are closed. `target` is the existing normalized absolute
installation destination, represented once; it is neither `RelPath` nor
repository `Root`. `files` preserves the existing fixed bundle order.
`replaced=true` implies `changed=true`. An idempotent matching installation
returns `changed=false` and `replaced=false`. No `schema_version`, `command`,
`action`, `warnings`, `root`, top-level `scope`, `provenance`, `page`,
`coverage`, or `mutation` appears. This is a separate administrative result,
not a twelfth repository `Operation` or execute request; it is absent from
`OperationContract`, `capabilities.operations`, discovery, and MCP `call_tool`.
Installer staging, symlink checks, divergent-content refusal, force behavior,
idempotence, ordinary restoration, and package-file identity remain existing
installer responsibilities. No new mutation engine or source-change plan is
introduced.

After the CLI administrative leaf is recognized, failures use the shared
`xray.v1 Error` with `op=skill_install`. Administrative errors forbid
repository `root`, repository provenance, and apply-only `mutation`. Invalid
arguments, divergent-content refusal, unsafe destination validation, and target
path-bound rejection use `invalid_request` and exit 2. Operational filesystem
or installation failures use `io_error` and exit 1. Unexpected implementation
failures use `internal_error` and exit 1. Successful installation, including
no-change idempotence, uses exit 0. `skill_install_failed` and the old CLI
envelope are not alternate public contracts. The result does not claim
source-change transaction or crash-recovery guarantees.

Administrative bounds are a success value of 65,536 bytes, an error value of
4,096 bytes, an error message of 512 UTF-8 bytes, and a prospective absolute
target of 4,096 UTF-8 bytes. Validate the prospective absolute target's UTF-8
length in the existing destination-owning installer function after resolution
and before creating destination parents or staging. Do not duplicate path
resolution in the CLI. The fixed result shape fits the success ceiling. Add no
`max_bytes`, paging, timeout, or retry flag.

Ownership is:

| Owner | Exact responsibility |
|---|---|
| `models.py` and `presentation.py` | `AdministrativeSuccess`, `ErrorOperation`, and canonical bounded serialization. |
| `cli.py` | Handwritten grammar, result mapping, shared error classification, and exit codes. |
| `skill_installer.py` | Existing mechanics plus the pre-write target-bound check in the existing destination owner; no staging or rollback rewrite. |
| `tests/` | Migrate supported installer and CLI consumer assertions; retain only observable contracts and plausible regressions. |
| Guidance | Update affected installed and repository CLI-skill examples in the implementation slice, not in this documentation artifact. |

Rejected alternatives are retaining `xray.cli.v1` solely for administration,
adding skill installation to MCP or a repository-analysis operation, adding an
administrative JSON-operation DSL, and changing installer mechanics merely to
match the repository change-plan subsystem.

## Transformation evidence

This delta records both directions of the exact F1–F3 transformation. A
source edge names the prior proposition or inspected evidence; a result edge
names its sole version-2 replacement. The tables are complete for these three
findings and deliberately do not reopen unrelated version-1 decisions.

**Source → result map.**

| Finding and exact title | Source edge | Sole result edge |
|---|---|---|
| F1 — OperationContract optional-root and complete call-ready input-schema contradiction | Version-1 D03 OperationContract and capabilities shape; version-1 D10 complete callable-schema requirement; earlier R01 final adjudication. | F1 closed `OperationContract`, `OperationSummary`, `OperationArguments`, `SchemaDocument`, optional-root capabilities rule, and catalog identity. Decisions D02, D03, D10; gates G1, G8, DOC-1, SEM-1. |
| F2 — custom two-method JSON-RPC framing contradicts retained standard FastMCP resources/prompts/progress/cancellation | Version-1 D03 custom frames and discovery/invocation shapes; version-1 D05 catalog cursor; version-1 D10 retained FastMCP surfaces; earlier R06 final adjudication; `src/xray/mcp_server.py:428-473`; installed FastMCP Tool/ToolResult and MCP request types. | F2 standard `tools/call` over FastMCP, closed discovery schemas, catalog cursor, standard result mapping, resources/prompts/progress/cancellation, and strict raw validation. Decisions D03, D05, D07, D10, D13; gates G1, G3, G4, G8, DOC-1, SEM-1. |
| F3 — retained CLI-only skill install lacks a closed replacement after xray.cli.v1 deletion | Version-1 D02 retained CLI-only administration; version-1 D11 global old-schema deletion and installer retention; `src/xray/cli.py:1366-1384`; `src/xray/skill_installer.py` `SkillInstallResult` and `install_cli_skill`. | F3 closed `AdministrativeSuccess`, shared `Error`/`skill_install` mapping, four bounds, and destination-owner validation. Decisions D02, D03, D07, D10, D11, D12, D13; gates G1, G4, G8, DOC-1, SEM-1. |

**Result → source map.**

| Result edge | Source edge closed |
|---|---|
| F1 complete call-ready `SchemaDocument` and `OperationContract`; root optional only for capabilities; `OperationSummary` detail; immutable catalog identity. | Replaces D03 catalog representation and D10 symbolic or incomplete callable-schema publication; preserves typed D02/D03 requests, operation set, and limits. |
| F2 `SearchToolsRequest`, `SearchToolsSuccess`, `CallToolRequest`, `CatalogCursor`, shared error operation, and discovery/invocation rules. | Replaces D03 custom request/result/frame aliases and D05 cursor interpretation where changed; preserves D03 semantic operation values and D05 deterministic paging intent. |
| F2 FastMCP `tools/list`/`tools/call`, standard MCP framing, resource/template/prompt methods, progress, cancellation, annotations, raw validation, and ToolResult mapping. | Replaces D03 two-method JSON-RPC allowlist and D10 custom framing wording; preserves D10 FastMCP and auxiliary-address intent. |
| F3 `AdministrativeSuccess`, `skill_install` shared errors, bounds, and destination-owner check. | Replaces D03 administrative omission, D07 administrative bound omission, D10 administrative presentation omission, and D11 CLI-v1 migration omission; preserves D02 CLI-only grammar and D11 installer mechanics. |

**Vocabulary and removal ledger.** Each changed public name has one
replacement; unrelated occurrences are not rewritten.

| Removed or changed term | Sole replacement and reason |
|---|---|
| Catalog `operation` field | `name`; the operation discriminator is named consistently with the standard tool call. |
| `source_mutating` | `guarded_mutation`; only `change_apply` mutates and every mutation is guarded. |
| Symbolic `query_schema` and `result_schema` fields | Complete `SchemaDocument` in `input_schema`; callers must have a valid first call without a second fetch. |
| OperationContract `cli`, `root`, `query_schema`, `query_presence`, `page`, `execution`, and `result_schema` metadata | Removed public metadata; applicable constraints remain in the real typed input schema or authored CLI grammar. |
| Custom `SearchToolMatch`, `SearchToolsCallResult`, `CallToolResult`, `McpRequestFrame`, `McpResponseFrame`, `McpRequestId` restriction, and protocol-error frame | Standard FastMCP/MCP Tool, ToolResult, JSON-RPC, and framework protocol behavior. |
| JSON-RPC methods named `search_tools` and `call_tool` | Standard `tools/call` with registered tool names `search_tools` and `call_tool`; standard auxiliary methods remain reachable. |
| `call_tool.max_bytes` and transport-specific invocation budget | Existing operation response-budget homes, such as `page.max_bytes` and `PlanBounds.max_bytes`; no duplicate wrapper. |
| Old `xray.cli.v1` administrative envelope and `skill_install_failed` | `AdministrativeSuccess` and shared `xray.v1 Error` with `invalid_request`, `io_error`, or `internal_error`. |
| Administrative top-level `scope`, `root`, `provenance`, `page`, `coverage`, `mutation`, warnings, command, action, or schema-version fields | Closed `AdministrativeSuccess.data` with one `target`, `scope`, `changed`, `replaced`, and fixed `files`; admin errors forbid repository/apply-only fields. |
| Eleven duplicated full schemas in capabilities or initial tools/list | One complete contract returned by progressive discovery and one summary per capability; no second schema registry. |

Version-1 DELTA01–DELTA08 and D01–D14 homes remain historical and inherited;
this packet does not edit, renumber, or duplicate them as new decisions. The
standard FastMCP correction does not add a protocol, background task, HTTP, or
recovery service. Deterministic source/result traces, catalog and packet digest
checks, and byte-preservation checks prove artifact closure only; they do not
prove semantic preservation, upstream runtime behavior, implementation,
qualification, approval, or release readiness.

## Documentation verification

The documentation closure for `xray-5e7.1` requires the exact version-2 packet,
its post-finalization companion, both active authority links, the source and
reverse trace tables above, and semantic acceptance of every F1–F3 literal.
It does not require product tests on unchanged product code. The documentation
writer owns only these four synchronized paths: this packet, its companion,
`PROJECT.md`, and `ARCHITECTURE.md`. I0 product-proof writers do not overlap
those paths.

Before writing, record SHA-256 values for `PROJECT.md`, `ARCHITECTURE.md`, the
version-1 packet and companion, and both adoption packet/companion pairs. After
replacing each exact four-line active paragraph, substituting the old paragraph
back must reproduce the corresponding authority file's pre-write bytes.
Version-1 next-major and both adoption proof pairs must remain byte-identical.
The active links must select this packet, while current-runtime and harness
bodies remain unchanged. The packet must have the exact header, six ordered H2
sections, exactly one normative F1–F3 home with the exact titles, local links,
UTF-8/LF bytes, no CR, and no trailing whitespace. Generate the companion only
after the final packet bytes using exactly one lowercase SHA-256 line, two ASCII
spaces, `docs/next-major-design-packet-v2.md`, and one final LF.

The phase and gate delta is:

- **I0:** `xray-5e7.2` proves the pinned upstream Tool extension, strict raw
  argument path, standard ToolResult mirroring, resources/prompts, and
  framework progress, cancellation, and admission behavior. `xray-5e7.3` owns
  measured baseline evidence. These lanes are independent after this contract
  freezes.
- **I1:** Land shared contracts, the exact-read vertical slice, two thin MCP
  Tool adapters, and the administrative envelope cutover. Verify only
  genuinely implemented operations in the unshipped candidate; do not
  advertise later operations.
- **I2–I4:** Continue the existing dependency order. `indexer.py` retains one
  writer; no phase becomes a partial release.
- **I5:** Accept the complete eleven-operation repository contract, retained
  standard MCP auxiliary surfaces, and CLI-only administration together. Run
  final whole-product qualification on one unchanged integrated artifact.

**G1 additions:** For every final operation, consume the discovered complete
`input_schema` and execute a valid request without a second schema fetch;
exercise rootless and explicit-root capabilities and reject missing root for
repository operations; compare actual CLI semantic values with standard MCP
`structuredContent` and canonical text, including strict-validation errors and
recognized malformed-`change_apply` errors; exercise skill-install success and
failure through the real CLI and confirm no old schema or administrative MCP
invocation.

**G3 additions:** Page catalog and intent discovery through changing positive
limits and byte budgets; confirm exact totals and seeking after the last
returned best or alternative; exercise empty intent results, stale catalog,
query mismatch, and invalid catalog checkpoints.

**G4 additions:** Confirm actual request and error admission through standard
MCP, not a mock protocol; prove complete schema fitting and deterministic
`budget_too_small` without omitted constraints; exercise the administrative
destination bound before any destination write.

**G8 additions:** Require exactly two initial MCP tools, complete catalog
generation, standard resource/template/prompt reachability, and no callable
hidden legacy tool; keep existing initial-metadata and discovery-token targets,
with full schema publication as progressive disclosure rather than permission
to raise budgets; verify installed/repository skill-copy parity and real
installer idempotence, divergent refusal, force replacement, and error exits;
validate canonical `OperationContract` generation under randomized source
enumeration, with all final eleven operations callable and no deleted schema or
operation remaining.

The contract lane owns `models.py`, `presentation.py`, `operations.py`, complete
schemas, immutable catalog identity, and deterministic ranking. The MCP lane
owns `mcp_server.py` and MCP-owned behavior tests. The CLI-installer lane owns
`cli.py`, the narrow installer-bound change, and consumer tests. The guidance
lane owns repository and packaged CLI-skill copies together. Root owns Beads,
serial integration, final qualification, artifact acceptance, and protected
delivery boundaries. These future ownership assignments authorize no
implementation in this documentation freeze.

The exact documentation proof commands are `sha256sum --check --strict
docs/next-major-design-packet-v2.sha256` and the corresponding unchanged
version-1/adoption companion checks. An authorized root or writer may use an
offline no-sync `uv` Python one-off for exact header, section, link,
paragraph-restoration, trace, encoding, and count checks; no permanent script
is added. No formatter, linter, build, or project test is part of this
packet's closure.

## Stop conditions and completion

Stop before digest generation if any of these occurs:

- An exact F1–F3 selection is replaced by a different technical option without
  a new authorized design delta.
- A historical packet or companion changes, an adoption proof pair changes, an
  unrelated current-runtime or harness body changes, or an active authority
  link still selects version 1.
- A digest is fabricated, computed before final packet bytes, embedded
  self-referentially, or treated as proof of semantics or runtime behavior.
- A complete contract cannot satisfy the unchanged discovery hard bound, or
  actual upstream behavior cannot meet the frozen strict-error or standard
  protocol boundary. The corresponding implementation gate stops; the
  specification's budgets do not silently change.
- The unrelated pre-existing harness byte-budget failure is silently waived or
  repaired inside this bounded documentation change.

`xray-5e7.1` is complete only when the exact packet, companion, active links,
UTF-8/LF and whitespace invariants, source/reverse trace closure, F1–F3 schema
review, and semantic fidelity are accepted; the version-1 and adoption proof
pairs remain byte-identical; and the four-path ownership boundary is proven.
The final evidence records per-file UTF-8 bytes, `text.split()` word counts,
SHA-256 values, command exits, and semantic acceptance. Documentation
completion does not complete product implementation, demonstrate runtime
compatibility, qualify tokenizer or performance targets, approve protected
delivery, mutate or close the Bead, create a commit, or authorize a release.
A passing documentation gate grants no qualification, publication, deployment,
remote mutation, or protected-delivery authority.
