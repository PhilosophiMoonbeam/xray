# XRAY Next-Major Design Packet

Version: 1
Decision Bead: `xray-txd`
Status: FROZEN DESIGN — NOT IMPLEMENTED
Decision date: 2026-09-10
Base commit: `01d195486fd7f38d54f718735f44ac6301b88689`
Current runtime contract: XRAY 0.11.4
Implementation: Future work requiring separate authorization

This packet freezes the next-major design only. It does not implement that design, replace XRAY 0.11.4 runtime authority, or supersede adoption Design Packet v2. Implementation and protected delivery actions require separate authorization.

## Outcome and scope

The governing outcome is the smallest sufficient, directly usable code evidence for an agent's next decision. The future product will provide bounded evidence, reproducible input identity, honest limitations, and a reviewed structural-change path without requiring an agent to traverse an imposed discovery ceremony.

Progressive disclosure is an optional set of entry points, not a mandatory command funnel. A known location can go directly to `read`; a known name can use `find` and then `interface` or `read`; a known expression or literal can use `search` and then `read`; an unknown area can use `map`. A normal change can obtain a complete plan and later apply that reviewed artifact in two product calls. An unfamiliar operation may use MCP discovery, but known operations require no discovery or preflight call.

This packet and its exact-byte companion are documentation artifacts. The coordinated freeze also has two link-only authority insertions: one in `PROJECT.md` and one in `ARCHITECTURE.md`. Those insertions only distinguish this future design from current authority. This work changes no executable product behavior, caller, package metadata, test, skill, installer, harness rule, tracker state, commit, or remote state.

The next major retains Python 3.10+, the `xray` and `xray-mcp` entry points, handwritten CLI presentation, stdio MCP, JSON and `jq` workflows, explicit repository containment, and optional expendable caches. It remains a local bounded tool rather than a service or project database.

The next major does not provide YAML product output. YAML remains contained ast-grep rule or configuration input. Rule authoring and rule testing remain expert ast-grep work rather than XRAY public operations. The design does not add a language server, type-aware dependency or rename graph, daemon, project database, arbitrary command runner, automatic commits, hidden plan store, durable source-generation store, mutation journal, recovery service, or cross-process transactional isolation.

CLI and MCP share operation semantics, defaults, hard limits, identities, data, and errors. Only explicitly listed transport mechanics differ. Cache warmth, eviction, corruption, and process history cannot change a successful semantic result. A source digest identifies captured bytes, not an atomic filesystem instant. A plan digest identifies reviewed artifact bytes, not approval. Syntax evidence is not compilation, type validity, semantic identity, or semantic equivalence.

All numbers in the future contract are labeled as frozen future thresholds, schema bounds, or phase identifiers. Repository observations, current-version statements, and source line ranges are historical or inspected evidence; they are not future measurements. No number in this packet claims an executed benchmark, runtime qualification, approval, or release.

## Authority and provenance

The current authority set is linked from this packet using paths relative to `docs/`:

| Authority | Role in this packet |
|---|---|
| [README.md](../README.md) | Current product commands, output, installation, and user-facing behavior. |
| [PROJECT.md](../PROJECT.md) | Current project readiness, ownership, canonical commands, compatibility, and delivery authority. |
| [ARCHITECTURE.md](../ARCHITECTURE.md) | Current component boundaries, interfaces, compatibility, storage, and mutation authority. |
| [Repository Language Standard](repository-language-standard.md) | Required vocabulary, strength, literal preservation, and transformation-evidence rules. |
| [Adoption Design Packet v2](adoption-design-packet-v2.md) | Current harness adoption authority; it is not replaced by this product design. |
| [Packet companion](next-major-design-packet-v1.sha256) | Exact lowercase SHA-256 companion for this packet's final UTF-8 bytes. |

The named base identity is `01d195486fd7f38d54f718735f44ac6301b88689`. Architecture inspection observed `.git/HEAD` pointing to `refs/heads/main`, that reference matching the supplied base, and `pyproject.toml` declaring version `0.11.4`. Those observations establish neither working-tree cleanliness nor equality of every inspected working byte with the base. This packet therefore treats repository paths and section or line ranges as evidence locators, not as an assertion that the working tree was pristine.

The source lineage is:

| Source | Provenance role | Durability rule |
|---|---|---|
| `agent://ChiefArchitect` | Initial technical proposal and its rejected or superseded alternatives. | This URI is a literal provenance locator only. The selected contract below contains the required meaning without session recovery. |
| `agent://ValuePlanner` | Critique, evidence, counterexamples, and proposals considered during adjudication. | The selected disposition is encoded below; ValuePlanner is not a second normative contract. |
| `local://chief-final-delta.md` | Binding eight-bullet delta from the initial Chief proposal. | Its eight material changes are copied into the source inventory and D02, D09, D10, D11, and D12. |
| `agent://FinalArchitect` | Final technical adjudication and closed D01–D14 contract. | This packet records the adjudication as repository-owned prose; its session availability is not required. |
| `agent://ArtifactPlanner` | Packet format, evidence, and deterministic documentation-check contract. | It governs encoding and proof shape, not technical choices. |

Precedence is explicit: applicable user or governing authority controls; the binding Chief delta controls over the initial Chief packet where they conflict; FinalArchitect's final adjudication closes remaining design choices; ValuePlanner supplies critique, evidence, and proposals without silently overriding selected decisions. A later authorized design delta must identify the affected decision and gate rather than silently changing a frozen threshold or boundary.

The inspected repository evidence is:

| Evidence ID | Repository locator at the named base | Material observation and limit |
|---|---|---|
| E001 | `README.md:1-11,120-220` | Current product identity, CLI quick start, current command names, and current output examples. These are current 0.11.4 behavior, not future examples. |
| E002 | `PROJECT.md:3,22-38,39-45,107-118,182-208` | `Status: READY`, current architecture path, integration authority, delivery rules, compatibility, rollback, and evidence ownership. |
| E003 | `ARCHITECTURE.md:1-8,9-35,37-89` | Current architecture authority, system boundary, and explicit XRAY 0.11.4 contract. |
| E004 | `docs/adoption-design-packet-v2.md:1-20,83-116,131-160` | Active harness adoption authority and its unchanged scope. |
| E005 | `pyproject.toml:project metadata` | Historical inspected package version `0.11.4`; no future package release is implied. |
| E006 | `src/xray/core/indexer.py:293-303` | Current `last_*` side channels are initialized separately; this motivates one future execute boundary. |
| E007 | `src/xray/presentation.py:144-190` | Current presentation reconstructs completeness from warning and projection fields; this motivates strict future result unions. |
| E008 | `src/xray/core/indexer.py:3003-3070,3158-3220` | Current snapshot, manifest, and inventory work are separate; this motivates captured-read-set identity. |
| E009 | `src/xray/presentation.py:193-252`; `src/xray/core/ast_grep.py:116-214` | Current offset or shortened-fingerprint continuation and arrival-order capping motivate future seek paging. |
| E010 | `src/xray/core/indexer.py:2668-2704,2818-2882` | Current handoff identity and inventory validation differ; this motivates one SourceRef resolver and direct reads. |
| E011 | `src/xray/core/indexer.py:3371-3680`; `src/xray/core/ast_grep.py:80-235` | Current fallbacks, broad skipping, late output checks, unbounded queues, and whole-stderr accumulation motivate typed bounded failure. |
| E012 | `src/xray/core/indexer.py:1179-1537,1630-1793`; `README.md` mutation limitations | Current guarded paths are valuable, while legacy mutation bypasses review and interruption guarantees are limited. |
| E013 | `src/xray/mcp_server.py:126-425`; `src/xray/cli.py:175-330` | Current MCP metadata overlap and CLI map/member amplification motivate one bounded catalog and global interface pages. |
| E014 | `src/xray/core/indexer.py:589-628`; `tests/test_structural_commands.py:91-96` | Current rule/config forwarding and `ruleDirs` fixture are evidence for, not proof of, the narrower future configuration grammar. |
| E015 | `TEMPLATE_MANIFEST.md`; `.codex/validate_agents.py`; `.codex/validate_project_readiness.py` | Existing manifest and validators serve harness adoption and do not automatically cover this new product packet. |
| E016 | `docs/adoption-design-packet-v1.sha256`; `docs/adoption-design-packet-v2.sha256` | Existing digest convention is lowercase SHA-256, two ASCII spaces, repository-relative path, and final LF. |
| E017 | `AGENTS.md`; `PROJECT.md:46-69` | Current ownership, concurrency, and canonical command rules remain authoritative during this freeze. |
| E018 | `ARCHITECTURE.md:91-180` | Historical 0.10.0 sections preserve chronology; they do not override the current 0.11.4 section. |

The final packet digest is intentionally not embedded in this file. The companion is generated only after the packet is complete. A digest identifies exact bytes; it does not prove source provenance, semantic preservation, human review, implementation, or approval.

## Frozen next-major decisions

The decisions in this section are the normative future design. They describe an unimplemented contract and never redefine current XRAY 0.11.4 behavior. Each decision has one stable home. Cross-references point back to the home rather than restating a rule with different strength.

### D01 — Mission and non-negotiable boundaries

The next major's mission is to give a coding agent the smallest sufficient, directly usable code evidence for its next decision, with bounded cost, reproducible input identity, honest limitations, and a reviewed structural-change path.

The future boundaries are:

- Progressive disclosure supplies optional entry points, not a mandatory `map` to `find` to `interface` to `impact` tour.
- A known location uses `read`; a known name uses `find` followed by `interface` or `read`; a known expression or literal uses `search` followed by `read`; an unknown area uses `map`.
- Python 3.10+, `xray`, `xray-mcp`, stdio MCP, JSON, `jq`, explicit repository containment, and optional expendable caches remain supported.
- No YAML product output exists. YAML is limited to contained ast-grep rule or supported project-configuration input.
- No language server, type-aware dependency or rename graph, daemon, project database, arbitrary command runner, automatic commit, hidden plan store, durable source-generation store, mutation journal, recovery service, or cross-process transactional-isolation subsystem is added.
- CLI and MCP have identical semantic contracts, including defaults, limits, identity, result data, coverage, and error meaning. Transport differences are limited to D10.
- Cache warmth, eviction, corruption, and process history never change successful semantic results.
- A source digest identifies captured bytes and consumed metadata, not an atomic filesystem instant. A plan digest identifies complete reviewed artifact bytes, not approval.
- Syntax evidence is not compilation, type validity, semantic identity, or semantic equivalence.

The future implementation must preserve explicit containment, JSON-first output, bounded execution, and honest failure. This packet does not make any of those future operations callable now.

### D02 — Canonical public families and operation surface

The future product has exactly seven public capability families, plus `capabilities` as support:

1. `map`
2. `find`
3. `interface`
4. `read`
5. `impact`
6. `search`
7. `change`

The canonical operation inventory is `map`, `find`, `interface`, `read`, `impact`, `search`, `change_plan`, `change_refine`, `change_verify`, `change_apply`, and `capabilities`. The first six CLI families use their names directly. CLI change uses `change plan|refine|verify|apply`; core and MCP use flat `change_*` names. `capabilities` keeps its spelling. MCP `search_tools` and `call_tool` are transport discovery, not additional analysis families. `skill install` remains CLI-only administration.

The following are future illustrations, not executable XRAY 0.11.4 commands:

```text
xray map ROOT --focus src/pkg
xray find ROOT Qualified.name
xray interface ROOT src/pkg/file.py
xray interface ROOT --ref-json "$ref"
xray read ROOT src/pkg/file.py --line 150
xray read ROOT --ref-json "$ref"
xray read ROOT --targets-file targets.json
xray impact ROOT --ref-json "$ref"
xray search ROOT --literal 'error message'
xray search ROOT --pattern 'old($A)' --lang python
xray search ROOT --rule rules/no-old.yml
xray search ROOT --config sgconfig.yml
xray change plan ROOT --pattern 'old($A)' --replacement 'new($A)' --lang python
xray change apply ROOT --plan-file plan.json --expected-digest "$reviewed_digest"
```

Every repository operation takes an explicit `ROOT`. CLI relative roots are resolved by its shell adapter; MCP roots are absolute paths. Neither transport infers a root from Git, `abs_path`, or a reference. `capabilities` may be rootless; a rootless call has no repository authority.

Reference ingestion uses `--ref-json` or `--ref-file FILE`, where `-` means standard input. `read` additionally accepts `--targets-file FILE` containing its bounded target array. A command accepts exactly one target-input form. Natural positional and flag forms normalize to the same typed request as MCP. No public generic JSON-operation DSL or generated CLI is introduced.

Pattern search and pattern change require explicit canonical language `python`, `javascript`, `typescript`, or `go`. There is no silent language inference and no invalid-pattern-to-literal fallback. Literal search is exact, case-sensitive UTF-8 text matching, including newlines, with non-overlapping matches. It is not regex, fuzzy text search, a ripgrep clone, or a change source.

`find` retains deterministic existing name-quality classes internally but removes public scores, confidence, and `--min-score`. `match=name` is the default and excludes fuzzy-only candidates. `match=exact` selects exact case-sensitive name or qualified identity. `match=fuzzy` explicitly permits weak fuzzy candidates. Results contain one `match_kind`. Existing calibrated integer ranking remains internal and toolchain-bound, with a final case-sensitive total tie-break.

`interface` accepts one file or one exact symbol. File sections are `symbols`, `imports`, and `exports`; `symbols` is the default. A symbol target permits `symbols` only. Dependencies and exports are observed syntax, not module resolution or a public-visibility synonym. For a file target, `kinds` and `visibility` are applied to the complete declaration population before member disclosure; only matching declarations and their requested direct members are eligible. Exact targets reject those filters. Interface emits a flat source-ordered declaration stream under one global page budget. Member depth is 0 or 1, with default 1. Deeper containers carry `expandable=true` and their exact reference; querying that reference discloses the next level. There is no `max-members` amplification and no unbounded recursive expansion.

An exact container, including a nested container, returns itself and requested direct members. An exact non-container member returns itself and a compact owner chain without siblings. Owner identity is the complete chain. `read` accepts one to eight targets in one request. Each target is a `SourceRef`, `OccurrenceRef`, or explicit contained location. `read` supplies optional enclosing-symbol information directly: it is enabled by default, computed once per original target before any merge, and never represented as one ambiguous owner for a merged chunk. Public `symbol_at` disappears.

`change_plan`, `change_refine`, and `change_verify` are read-only. `change_apply` alone mutates product source. Refinement and verification are optional. Apply never relies on an earlier verify result and always repeats its guards. The full lifecycle is D09.

### D03 — Exact wire schemas, identity, serialization, and errors

The notation below is normative for the future contract. A `?` means an omitted optional field. `|` is a tagged union. Arrays preserve declared order unless a schema says they are canonically sorted. Every object is closed. There are no unspecified extra fields, implicit coercions, Boolean-as-integer values, NaN, floats, or null-as-omission.

Serialized JSON uses UTF-8, sorted object keys, compact separators, no ASCII escaping of ordinary Unicode, and exactly one final LF only in CLI framing. Digests exclude that framing LF. MCP protocol framing is transport overhead and is not part of the semantic JSON value.

All numeric constraints in this decision are frozen future schema bounds. `Digest` is exactly 64 lowercase hexadecimal SHA-256 characters. `RelPath` is a contained repository-relative POSIX path with no empty path, NUL, `..` component, absolute form, Unicode normalization, or symlink escape. `.` is permitted for a root or directory scope, not for a file reference. Path UTF-8 input is at most 4096 bytes. Unsupported filesystem names fail explicitly.

`Root` is `{path: normalized_absolute_path, id: Digest}`. Its `id` is `SHA256(canonical_json(['xray.root.v1', path]))`, binding the local root namespace rather than a permanent inode identity.

`Range` is `{start:{byte:int>=0,line:int>=1,column:int>=1},end:{byte:int>=0,line:int>=1,column:int>=1}}`. The end is exclusive. Columns count UTF-8 bytes from the line start, one-based. Bytes are authoritative and all coordinates agree with captured bytes. LF establishes a line boundary; CRLF bytes remain intact.

`SourceRef` is `{kind:'source',root_id:Digest,path:RelPath,file_digest:Digest,start:int>=0,end:int>=start}|SymbolSourceRef`; the source branch forbids `symbol_id` and `analyzer_id`, while the symbol branch is exactly `SymbolSourceRef`. Both branches require UTF-8-boundary offsets inside the captured file, and their root and file digests must match the current captured request.

`OccurrenceRef` is `{kind:'occurrence',root_id:Digest,path:RelPath,file_digest:Digest,start:int>=0,end:int>=start,occurrence_id:Digest}`. `occurrence_id` is `SHA256(canonical_json(['xray.occurrence.v1',path,file_digest,start,end]))`. It identifies a readable source occurrence, not target binding or rule identity. Distinct rules may share the same occurrence reference.

`symbol_id` is `SHA256(canonical_json(['xray.symbol.v1',file_digest,analyzer_id,language,kind,full_owner_chain,name,start,end]))`. The per-file declaration artifact owns these values. `SymbolSourceRef` is the strict symbol branch above; display text never substitutes for either identity.

`LocationTarget` is `{kind:'location',path:RelPath,line:int>=1,end_line?:int>=line,column?:int>=1}`. An absent `end_line` selects through EOF, subject to page bounds. `column` is a one-based UTF-8-byte column and must be a character boundary. A location does not implicitly expand to an enclosing body.

`ReadTarget` is `SourceRef | OccurrenceRef | LocationTarget`.

`Selection` is `{paths:RelPath[],globs?:string[],languages?:Language[],exclusions:'default'|'none'}`. `paths` defaults to `['.']`; path sets are sorted and deduplicated; `languages` use the fixed `Language` order and are deduplicated; ordered globs retain application order but exact duplicate globs are rejected. Empty optional arrays are omitted in results. An absent language filter has the operation-specific domain in D04.

`Disclosure` is `{clipped:('signature'|'documentation'|'text'|'captures')[]}`. It appears only when optional display fields are clipped. It never permits clipping an identity, edit manifest, diff, or required schema.
`Operation` is the finite union `'map'|'find'|'interface'|'read'|'impact'|'search'|'change_plan'|'change_refine'|'change_verify'|'change_apply'|'capabilities'`; no other analysis operation name is accepted. `Language` is `'python'|'javascript'|'typescript'|'go'`, and `Visibility` is `'public'|'private'|'unknown'`.

`CatalogOperation` is `Operation|'search_tools'`; `call_tool` is an MCP transport method and is not a catalog operation. `OperationContract` is `{operation:Operation,cli:string[1,128],description:string[1,256],mutation:'read_only'|'source_mutating',root:'required'|'forbidden',query_schema:'map'|'find'|'interface'|'read'|'impact'|'search'|'change_plan'|'change_refine'|'change_verify'|'change_apply'|'capabilities',query_presence:'required',page:'optional'|'forbidden',execution:'optional',result_schema:'map'|'find'|'interface'|'read'|'impact'|'search'|'change_plan'|'change_refine'|'change_verify'|'change_apply'|'capabilities'}`. The description is one sentence with no newline; `query_schema`, `result_schema`, root/page presence and mutation agree with the matching D03 operation row. The contract's arguments are exactly the closed `Request` fields and the named query schema, not an opaque or extensible schema language. A capabilities detail catalog contains exactly one contract per `Operation`, in canonical operation order, with no duplicates.

`ResponseLimit` is `{operation:CatalogOperation,default_bytes:int>=4096,hard_bytes:int>=default_bytes,default_items?:int>=1,hard_items?:int>=default_items,item_mode:'count'|'targets'|'none'}`. `LimitCatalog` is `{schema:'xray.limits.v1',responses:ResponseLimit[12],capture:{source_files:20000,source_bytes:268435456,file_bytes:10485760},namespace:{entries:100000,path_bytes:16777216},analysis:{find_declarations:100000,find_candidates_per_file:10000,window_files:1000,window_source_bytes:52428800,window_raw_candidates:10000,overflow_sentinel:1},configuration:{files:1024,file_bytes:1048576,total_bytes:8388608,yaml_depth:64,nodes:100000},executor:{stdout_bytes:16777216,stderr_bytes:65536,queued_bytes:262144,default_timeout_seconds:30,hard_timeout_seconds:120,git_timeout_seconds:5,children_per_operation:1},concurrency:{mcp_operations:4,mcp_per_root:1},storage:{temporary_bytes:335544320,mutation_bytes:209715200,cache_disk_bytes:536870912,cache_artifact_bytes:16777216,cache_payload_bytes:67108864,root_handles:32},mutation:{affected_file_bytes:10485760,total_preimage_bytes:52428800,total_postimage_bytes:52428800},request:{json_bytes:1048576,cursor_bytes:4096,discovery_intent_bytes:1024},display:{read_lines_default:64,read_lines_hard:256,read_source_bytes_default:8192,read_source_bytes_hard:32768,context_lines:10,signature_bytes:2048,documentation_bytes:512,occurrence_text_bytes:512,capture_records:16,transformed_text_bytes:512}}`. `responses` has exactly one entry for each `CatalogOperation`, sorted by the canonical order `search_tools,capabilities,map,find,interface,read,impact,search,change_plan,change_refine,change_verify,change_apply`; its values are the D07 table (discovery 4096/16384 with default three records and hard ten; capabilities 4096/65536 with no item count; map 8192/65536 with 100/1000; find 6144/65536 with 10/100; interface 8192/65536 with 20/200; read 12288/65536 with target mode and no item count; search and impact 8192/65536 with 20/1000; plan and refine 32768/262144 with 100/1000; verify and apply 8192/65536 with no item count). Every hard value is fixed by D07, no caller or environment override raises it, and nested objects have no extra fields.

`ToolchainManifest` is `{schema:'xray.toolchain.v1',xray_revision:string[1,128],xray_artifact:Digest,ast_grep:{version:string[1,128],artifact:Digest},ast_grep_py:{version:string[1,128],artifact:Digest},python_ast:{version:string[1,128],artifact:Digest},grammars:[{language:Language,version:string[1,128],artifact:Digest}][0..4],ranking:Digest,selection:Digest,parser:Digest}`. The grammar array is sorted by `language`, has no duplicate language, and contains every grammar used by the request. All strings are nonempty UTF-8 and all objects are closed. The repository `toolchain` digest is `SHA256(canonical_json(['xray.toolchain.v1',ToolchainManifest]))`; the manifest has no self-digest field, and output-affecting revisions or artifacts cannot be omitted.

`ChangeSource` is `{kind:'pattern',pattern:nonempty_string[1,8192 UTF-8 bytes],replacement:string[0,8192 UTF-8 bytes],language:Language}|{kind:'rule',input:RuleInput}`. `kind` is the discriminator; pattern input requires the explicit language and valid replacement rendering, while rule input uses the closed `RuleInput` contract in D04. No literal change source exists.

`RepositoryProvenance` is `{kind:'repository',consistency:'captured_read_set',query:Digest,selection:Digest,snapshot:Digest,toolchain:Digest}`. `CatalogProvenance` is `{kind:'catalog',catalog:Digest}`. `EstablishedProvenance` is `RepositoryProvenance|CatalogProvenance`; `Provenance` is the same closed union for successful responses. A repository variant is emitted only after all four component digests and the captured-read-set consistency are established; a catalog variant is emitted only for rootless capabilities or MCP discovery. Partial progress omits provenance rather than inventing optional or stale fields. The root is carried separately by ordinary repository envelopes and by a complete `ChangePlan`.

`SymbolSourceRef` is `{kind:'symbol',root_id:Digest,path:RelPath,file_digest:Digest,start:int>=0,end:int>=start,symbol_id:Digest,analyzer_id:Digest}`. Its `kind` is fixed, offsets are UTF-8 boundaries for the captured file, and the tuple resolves to exactly one declaration in the canonical per-file artifact. `root_id` and `file_digest` must match the captured request; owner-chain identity is inside `symbol_id`, never inferred from display text.

`FindRowId` is `SHA256(canonical_json(['xray.find.row.v1',path,start,end,symbol_id]))`, where `path` is the contained relative path and the offsets and `symbol_id` come from the returned declaration. It is unique within a complete find population; a collision or non-unique row is an analysis error, not a seek tie.

A request is `{op:Operation,root?:string,query:OperationQuery,page?:PageRequest,execution?:{timeout_seconds:int[1,120],cache:'auto'|'off'}}`. The frozen future default is `timeout_seconds=30` and `cache=auto`; these are future thresholds, not current behavior. Root is absent only for rootless `capabilities`. `page` is forbidden for change operations. The defaulted and normalized semantic query is hashed rather than redundantly echoed. Page controls and timeout or cache controls are not semantic query identity.

`PageRequest` is `{limit?:positive_int,max_bytes?:int,cursor?:string,max_lines?:positive_int,source_bytes?:positive_int}`. `max_lines` and `source_bytes` are read-only controls; `limit` is collection-only. D07 defines bounds. Irrelevant fields are rejected.

The future operation query unions are:

| Operation | Closed query |
|---|---|
| `map` | `{focus?:RelPath[],depth?:int>=0|'all',context?:'none'|'ancestors',exclusions?:'default'|'none'}`. Defaults are `focus=['.']`, `depth=2`, `context=none`, `exclusions=default`. Numeric depth has frozen future maximum 64; `all` is explicit and remains subject to namespace admission. |
| `find` | `{text:nonempty_string,selection?:Selection,match?:'name'|'exact'|'fuzzy',kinds?:string[],visibility?:('public'|'private'|'unknown')[]}`. Default match is `name`. Kind strings must be in the capability catalog. |
| `interface` | `{target:{kind:'file',path:RelPath}|SymbolSourceRef,sections?:('symbols'|'imports'|'exports')[],member_depth?:0|1,documentation?:bool,kinds?:string[],visibility?:Visibility[]}`. Defaults are `symbols`, member depth 1 and documentation false. For a file target, `kinds` and `visibility` filter the complete declaration population before member disclosure; only filtered declarations and their requested direct members are eligible, and filtering never occurs after expansion. Exact targets reject both filters. |
| `read` | `{targets:ReadTarget[1..8],context_lines?:int[0,10],include_enclosing?:bool}`. Defaults are context lines 0 and enclosing true. All targets are captured and validated before a successful batch result. With `include_enclosing=true`, each original target receives exactly one per-target `Enclosing` value; `false` omits those values. Exact symbol targets report that validated symbol as `found`. Location and occurrence targets choose the narrowest enclosing supported declaration containing the original target interval, breaking equal-span ties by the smallest canonical `symbol_id`. A merged source chunk never supplies one owner for multiple targets: its per-target values remain separate, and an unresolved owner is `none`, `unsupported`, or `unavailable` as defined below. Optional enrichment failure is explicit and does not fail the source read, except timeout, I/O, or malformed execution, which fail the operation. |
| `impact` | `{target:SymbolSourceRef,selection?:Selection,mode?:'syntax'|'lexical'}`. Default mode is syntax. There is no manual name-only target or alias-following option. |
| `search` | `{selection?:Selection,detail?:'summary'|'detail',source:{kind:'pattern',pattern:string,language:Language}|{kind:'literal',text:string}|{kind:'rule',input:RuleInput}}`. Default detail is summary. `RuleInput` is `{kind:'rule'|'config',path:RelPath}` and neither accepts a directory. |
| `change_plan` | `{selection?:Selection,source:{kind:'pattern',pattern:string,replacement:string,language:Language}|{kind:'rule',input:RuleInput},bounds?:PlanBounds,acknowledgements?:Acknowledgements}`. Literal changes are unsupported. |
| `change_refine` | `{plan:ChangePlan,edit_ids:Digest[]}`. IDs are sorted and deduplicated. An empty selection produces an explicitly inapplicable complete plan. Unknown IDs fail. |
| `change_verify` | `{plan:ChangePlan,expected_digest:Digest}`. There is no field or acknowledgement override. |
| `change_apply` | `{plan:ChangePlan,expected_digest:Digest}`. There is no field or acknowledgement override. |
| `capabilities` | `{detail?:'summary'|'detail'}`. Summary is default. Root-dependent health is checked only when a root is supplied. |

A repository success is `{schema:'xray.v1',ok:true,op:Operation,root?:Root,scope?:Selection,provenance:Provenance,data:OperationData,page?:PageResult,coverage:Coverage}`. Ordinary repository responses require root, scope, and repository provenance. `change_plan` and `change_refine` use one explicit plan-response exception: `{schema:'xray.v1',ok:true,op:'change_plan'|'change_refine',data:{plan:ChangePlan},coverage:Coverage}` omits envelope `root`, `scope`, and `provenance`; the complete `data.plan` is self-contained and carries the sole Root, Selection, and RepositoryProvenance. No other operation may omit required repository identity. Rootless `capabilities` uses catalog provenance. There is no generic warnings array, returned count, `truncated`, `total_exact`, lower-bound total, duplicated query, or arbitrary diagnostics dictionary.

`Provenance` is the closed `RepositoryProvenance|CatalogProvenance` union defined above. Ordinary repository envelopes carry the repository variant once beside their root and scope; rootless `capabilities` carries the catalog variant. The plan-response exception carries repository provenance only inside its self-contained `ChangePlan`. Detailed component identities are available through capability detail; standalone references retain only their necessary root digest.

`PageResult` is `{next_cursor?:string,total?:int>=0}` and appears only for pageable results. A future `total`, when emitted, is exact for the full normalized requested collection, not the page or a seen prefix. It is emitted for fully materialized `find`, `interface`, and catalog collections and for an admitted `map` namespace. Streaming `search` and `impact` omit it consistently. `read` has a page object but no total. Missing `next_cursor` means traversal of the requested result or source population is exhausted; it does not imply complete language or semantic analysis.

`Coverage` is `{state:'complete'|'partial',basis:'namespace'|'supported_declarations'|'source_bytes'|'pattern_matches'|'rule_diagnostics'|'literal_occurrences'|'name_occurrences'|'change_guards'|'capabilities',reasons?:CoverageReason[]}`. `complete` forbids reasons; `partial` requires a nonempty canonically sorted list. `CoverageReason` is `{code:'scan_pending'|'unsupported_syntax'|'parse_diagnostics'|'non_text_input'|'enclosing_unavailable'|'capture_unverified',path?:RelPath,count?:positive_int}`. Repeated reasons aggregate by code and path. If the bounded reason catalog would exceed the response, return `analysis_limit` rather than silently lose coverage. A requested depth, section, or filter is scope, not incompleteness. Ordinary paging of an analyzed collection does not make coverage partial.

An error is `{schema:'xray.v1',ok:false,op?:Operation|'search_tools'|'call_tool',root?:Root,error:{code:ErrorCode,message:string,at?:string,action?:RecoveryAction,details?:ErrorDetails},mutation?:ChangeApplyMutation,provenance?:EstablishedProvenance}`. Errors contain no data, page, success coverage, or success-shaped fallback. `op`, `root`, and provenance appear only when actually established. `mutation` appears exactly when a recognized `change_apply` operation fails: it is mandatory for every such error, including malformed argument, file-loading, plan, dependency, bound, and other pre-write rejections, and omitted for every other operation. It is a top-level sibling of `error`, `root`, and `provenance`; `error.details` remains the ordinary code-specific `ErrorDetails` union and is never replaced with mutation state. If no plan digest was validated, `mutation.plan_digest` is omitted. Error messages are at most 512 UTF-8 bytes. Error JSON is at most 4096 bytes; optional context is omitted deterministically to meet that bound. There is no traceback or prose-only success-shaped failure.

The future error codes are exactly:

`invalid_request`, `unknown_operation`, `path_outside_root`, `not_found`, `excluded_input`, `unsupported_file`, `unsupported_configuration`, `invalid_pattern`, `invalid_rule`, `invalid_encoding`, `invalid_reference`, `stale_reference`, `invalid_cursor`, `cursor_query_mismatch`, `stale_cursor`, `source_changed`, `dependency_unavailable`, `io_error`, `timeout`, `execution_limit`, `analysis_limit`, `budget_too_small`, `invalid_plan`, `plan_drift`, `plan_inapplicable`, `mutation_conflict`, `apply_failed`, and `internal_error`.

`RecoveryAction` is one of `correct_input`, `refresh_reference`, `restart_query`, `narrow_query`, `install_dependency`, `inspect_worktree`, or `report_bug`. At most one action appears. There is no retryability Boolean, next-action list, automatic retry, or action graph.

`ChangeApplyMutation` is `{state:MutationFailureState,rollback_status:RollbackStatus,plan_digest?:Digest}`, where `plan_digest` appears only after the supplied plan digest has been validated. Its invariant is `not_applied` ⇔ `not_attempted`; `rolled_back` ⇔ `succeeded`; `partially_applied` ⇔ `failed` with known remaining changes; and `indeterminate` ⇔ `failed` when final bytes cannot be established. Before the first target write, every recognized `change_apply` failure has `state=not_applied` and `rollback_status=not_attempted`. Verified restoration of all changed targets is `rolled_back`/`succeeded`; failed restoration with known remaining changes is `partially_applied`/`failed`; inability to establish final bytes is `indeterminate`/`failed`. `ErrorDetails` is `{kind:'bound',bound:string,limit:int,observed?:int,minimum_bytes?:int}|{kind:'dependency',dependency:string}|{kind:'stale',changed:'source'|'selection'|'toolchain'|'root'}|{kind:'plan',plan_digest?:Digest,reason?:EligibilityReason}|{kind:'conflict',conflict_edit_ids?:Digest[1..8],additional_conflicts?:int>=1}`. Invalid, stale, containment, dependency, bound, plan, and conflict errors retain any applicable ordinary code-specific details; `ErrorDetails` has no `change_apply` branch and never carries mutation state or rollback status. Bounded `conflict_edit_ids` and `additional_conflicts` appear only in ordinary code-specific `conflict` details. A recognized `change_apply` error may still carry applicable ordinary details in `error.details`, but its authoritative mutation state and rollback status occur only in top-level `mutation`. `at` is an input JSON pointer or bounded contained path, never an arbitrary object.
For a recognized `change_apply` error, `error.details.plan_digest` is forbidden, including when `error.details.kind='plan'`; only `mutation.plan_digest` may contain the validated plan digest.

CLI exits are 0 for success, 2 for malformed or invalid request, unknown operation, invalid pattern, rule, encoding, reference, cursor, plan, or unsupported request or configuration, and 1 for stale input, containment, operational, resource, analysis, or mutation failure. `path_outside_root` uses exit 2 when rejecting the supplied path and exit 1 if containment changes during execution; the code remains the same. Removed operations are `unknown_operation`, not migration aliases.

`MCP returns the same semantic JSON value. `isError=true` exactly when `ok=false`. Required protocol text mirrors that JSON rather than creating an independent interpretation. The closed transport-only values and framing are as follows.
`McpRequestId` is `string[1,128]|int>=0` with Boolean integers forbidden. `SearchToolsRequest` is `{mode?:'search'|'enumerate'|'detail',intent?:nonempty_string[1,1024 UTF-8 bytes],operation?:Operation,limit?:int[1,10],cursor?:string,max_bytes?:int[4096,16384]}`. The default mode is `search`: it requires exactly one of `intent` or `operation`; `enumerate` forbids both; `detail` requires `operation` and forbids `intent` and `cursor`. A cursor continues only the same normalized search or enumeration query. `limit` and `max_bytes` are transport budget controls excluded from the query digest.
`SearchToolMatch` is `{role:'best',contract:OperationContract}|{role:'alternative',operation:Operation,description:string[1,256],mutation:'read_only'|'source_mutating'}|{role:'entry',contract:OperationContract}`. `SearchToolsResult` is `{catalog:Digest,query:Digest,items:SearchToolMatch[1..10],next_cursor?:string}`. A search has exactly one `best` first and at most two `alternative` records by default; enumeration and detail use `entry` records. Items have no duplicate operation and are ordered best, then alternatives by deterministic rank, or entries by canonical operation order. `query` is `SHA256(canonical_json(['xray.mcp.search_tools.v1',mode,intent?,operation?]))`; catalog identity is separate.
`CallToolRequest` is `{name:Operation,arguments:{root?:string,query:OperationQuery,page?:PageRequest,execution?:{timeout_seconds:int[1,120],cache:'auto'|'off'}},max_bytes?:int[4096,hard_bytes_for_name]}`. `name` is the discriminator and `arguments` contains no `op` or unknown field; its closed query branch is selected by `name`, root is required except for `capabilities`, and page is forbidden for change operations. `max_bytes` is a transport budget excluded from semantic query identity and may not exceed the matching `LimitCatalog` hard response value.
`SearchToolsCallResult` is `{kind:'search_tools',value:SearchToolsResult|Error,content:[{type:'text',text:string}],isError:bool}` and `CallToolResult` is `{kind:'call_tool',value:Success|Error,content:[{type:'text',text:string}],isError:bool}`. Each `content` array has exactly one text item whose text is the compact canonical JSON serialization of `value`; `isError` is false exactly for `SearchToolsResult` or `value.ok=true`. A complete best contract is reserved before fitting; an insufficient discovery budget returns `budget_too_small` rather than dropping constraints. `call_tool` normalizes the named request and invokes the same executor and operation hard limits; if the complete semantic value cannot fit `max_bytes`, it returns the typed `budget_too_small` error and no partial value. The error itself remains within the 4096-byte error ceiling.
`McpRequestFrame` is `{jsonrpc:'2.0',id:McpRequestId,method:'search_tools'|'call_tool',params:SearchToolsRequest|CallToolRequest}`; `method` selects the matching closed `params` branch and no other pairing is valid. A successful `McpResponseFrame` is `{jsonrpc:'2.0',id:McpRequestId,result:SearchToolsCallResult|CallToolResult}`. A framing or JSON-RPC failure is `{jsonrpc:'2.0',id:McpRequestId|null,error:{code:int[-32700,-32000],message:string[1,512],data?:{kind:'protocol',reason:'parse'|'invalid_request'|'method_not_found'|'invalid_params'|'internal'}}}`. Stdio is one UTF-8 newline-delimited JSON-RPC frame per line with no headers or extra fields; escaped newlines are permitted inside JSON strings, raw embedded newlines are not, and request/response payload bytes obey D07. Progress and cancellation notifications are transport-only and cannot alter the semantic result; no other callable MCP method exists.

The future operation data shapes are:

| Operation | Closed data shape |
|---|---|
| `map` | `{items:[{path:RelPath,kind:'file'|'directory'|'symlink',language?:Language,frontier?:true}]}`. A frontier marks an untraversed depth boundary, not a claim that children exist. Symlinks are navigation entries only and traversal never follows them. |
| `find` | `{items:[{ref:SymbolSourceRef,row_id:FindRowId,name:string,kind:string,qualified_name:string,location:Range,match_kind:'exact_qualified_name'|'exact_name'|'exact_path_context'|'normalized_name'|'prefix'|'token'|'fuzzy'}]}`. There are no signatures, docs, absolute paths, numeric score, or confidence. |
| `interface` | `{owners?:[{ref:SymbolSourceRef,name:string,kind:string}],items:[Declaration|Import|Export]}`. `Declaration={section:'symbols',ref:SymbolSourceRef,name:string,kind:string,qualified_name:string,signature:string,visibility:Visibility,parent_id?:Digest,expandable?:true,documentation?:string,disclosure?:Disclosure}`. `Import={section:'imports',ref:OccurrenceRef,module_text:string,imported_name?:string,local_name?:string}`. `Export={section:'exports',ref:OccurrenceRef,name?:string,module_text?:string,kind:'named'|'default'|'star'|'reexport'|'unknown'}`. Owners contain no repeated signatures or siblings. |
| `read` | `{items:[{targets:int[],ref:SourceRef,location:Range,source:string,enclosing?:{target:int,result:Enclosing}[]}]}`. `targets` indexes the original target array from zero. Returned source is exact bytes for `ref.start..ref.end`, decoded as UTF-8. If present, `enclosing` has exactly one entry for every target index in `targets`, in ascending target-index order; it is absent only when `include_enclosing=false`. `Enclosing` is `{state:'found',ref:SymbolSourceRef}|{state:'none'|'unsupported'}|{state:'unavailable',reason:'dependency_unavailable'|'unsupported_syntax'|'parse_diagnostics}`. |
| `search` | `{items:[{ref:OccurrenceRef,location:Range,text:string,rule_id?:string,captures?:Capture[],disclosure?:Disclosure}]}`. `Capture={name:string,kind:'single'|'multi'|'transformed',refs?:SourceRef[],text?:string}`. Only verified named nodes appear in `multi.refs`; transformed text never masquerades as a source slice. Summary omits captures; detail supplies bounded captures. |
| `impact` | `{target:SymbolSourceRef,basis:'name_occurrences',resolution:'unresolved',items:[{ref:OccurrenceRef,location:Range,kind:'definition'|'import'|'call'|'read'|'comment'|'string'|'text'|'unknown',evidence:'ast_syntax'|'lexical',text:string,enclosing?:Enclosing,import?:{module_text:string,imported_name?:string,local_name?:string},disclosure?:Disclosure}]}`. There is no resolved caller, dependent, or confidence field or graph. |
| `change_plan` and `change_refine` | `{plan:ChangePlan}`. The plan is a complete artifact and never an applicable partial plan. The full shape is D09. |
| `change_verify` | `{plan_digest:Digest,ready:true}`. A successful verify is a present guard result, not a reservation, approval, or permission to skip apply guards. |
| `change_apply` | `{plan_digest:Digest,state:'applied',rollback_status:'not_attempted'}`. Changed paths, counts, and edit identities remain derivable from the complete reviewed plan rather than being repeated. |
| `capabilities` | `{version:string,schema:'xray.v1',plan_schema:'xray.change.v1',healthy:bool,languages:Language[],dependencies:[{name:string,state:'available'|'missing'|'incompatible',version?:string}],operations?:OperationContract[],limits?:LimitCatalog,resources?:string[],toolchain?:ToolchainManifest}`. Summary omits operations, limits, resources, and toolchain. Detail supplies them within the capability bound. |

### D04 — Effective selection, capture, configuration, and provenance

A single future repository provider owns containment, canonical path normalization, Git-wildmatch ignore interpretation, named generated-state exclusions, effective scopes, manifests, and capture. No adapter or subprocess chooses a second population.

The default generated-exclusion policy retains the current `DEFAULT_EXCLUSIONS` set as a named versioned policy. `exclusions=none` disables that generated policy only; it does not disable repository ignore rules. `.git` internals are an unconditional safety exclusion. Explicit file targets override generated and repository-ignore exclusions except that unconditional safety exclusion. Language or type incompatibility is `unsupported_file`, not empty success. Explicit directory scopes make the named directory traversable even when hidden or ignored, while descendant ignore rules still apply. Ordered explicit globs are applied last and may exclude a named file, which returns `excluded_input`.

Global Git excludes, home-directory ignore configuration, implicit ancestor ast-grep configuration, environment-selected configuration, and subprocess-specific hidden rules cannot change XRAY selection. Relevant contained `.gitignore` files are captured and hashed. Git is optional dirty-baseline evidence for changes, not selection or snapshot truth.

`find`, `interface`, and syntax impact operate within the supported language and declaration profile. Pattern search uses its explicit language. Rule search uses each rule's language. Literal search and explicit lexical impact independently select regular text inputs. Non-UTF-8 or NUL-bearing files are excluded with `non_text_input` partial coverage rather than silently treated as exact empty. Exact read of such a file fails `invalid_encoding`.

Maps capture namespace metadata only at the requested horizon and do not hash file bodies. A symlink is a non-followed navigation entry. Source, configuration, and mutation targets reject symlink components. A hard-linked mutation target with link count other than one is rejected before staging to avoid changing its link contract.

**Captured-read-set contract.** Scope is normalized before source admission. The provider captures selected namespace, relevant ignore and configuration inputs, and exact source bytes using bounded chunked reads. It hashes bytes while capturing. An analyzer and projection consume captured bytes or a private temporary tree made from those bytes, never later live source.

A single-file `interface` or `read` captures only requested files and parser or selection prerequisites. An eight-target read captures each distinct file once. Broad inventory is not a reference-validation prerequisite. The manifest binds sorted relative path, byte size, and content digest. Metadata-only `map` binds path, kind, and selected namespace, not irrelevant file content. Mutation additionally binds modes and the selected candidate universe.

Capture compares file identity and stat observations around reads and selection namespace observations around enumeration. An observable change returns `source_changed` without automatic retry. These checks detect some races but do not claim that all files coexisted simultaneously. Source changed after capture cannot alter that operation's analysis. A fresh reference read validates against newly captured current bytes. A later cursor request reconstructs the selected manifest and rejects relevant drift. XRAY does not promise replay of old source that is no longer available.

The selection digest binds normalized selection, policy revision, relevant ignore or configuration bytes, and selected membership. The snapshot digest binds consumed bytes and metadata. The toolchain digest binds output-affecting XRAY revisions, ast-grep executable artifact and version, ast-grep-py or grammar artifact and version, Python AST runtime, name-ranking implementation, and selection or parser settings. The query digest binds canonical operation, normalized semantic query, projection, selection, snapshot, and toolchain. Root binding is separate. Page size, response or source byte limits, deadline, cache mode, transient paths, timestamps, and timings are excluded from query identity. Identical semantic inputs can therefore use different positive page sizes without a new query.

Stateless source freshness still reads and hashes selected bytes on continuation. Content caches eliminate repeated derivation, not this lower bound. Modification time is never proof of unchanged bytes.

**Closed configuration contract.** The future design retains contained standalone rule files and a deliberately closed XRAY-supported project-config subset. This resolves the upstream dependency inventory without supporting arbitrary external grammar or configuration loading.

A `RuleInput` of kind `rule` is a contained `.yml` or `.yaml` rule file with one or more rule documents. Inline rule-local utils, constraints, transforms, and fixes retain upstream ast-grep semantics. No project configuration is implicitly loaded.

A `RuleInput` of kind `config` is a contained `.yml` or `.yaml` file whose complete top-level mapping is exactly `{ruleDirs: nonempty list of contained directory paths}`. Paths resolve relative to the configuration's parent and remain inside `ROOT`. XRAY recursively enumerates `.yml` and `.yaml` rule files under those directories in canonical path order without following symlinks. It captures every selected rule byte and directory membership. An empty rule set fails `invalid_rule`.

Arbitrary `sgconfig` is not passed through. `utilDirs`, `customLanguages`, `languageGlobs`, `testConfigs`, external grammar libraries, unknown configuration keys, directory-as-config inference, environment-selected configuration, and ancestor discovery are `unsupported_configuration`. Users migrate to self-contained rules, the supported `ruleDirs` subset, XRAY scopes and language inputs, or direct ast-grep for broader rule development. This is an explicit major compatibility deletion, not an implementation fallback.

The future loader uses a bounded safe YAML input loader and declares PyYAML `>=6,<7` directly rather than relying on a transitive dependency. It rejects duplicate keys, custom tags, anchors or aliases, excessive nesting, and D07 input bounds before constructing unbounded objects. The loader classifies input and dependencies only. ast-grep remains matching, validation, and replacement-rendering authority. XRAY does not build a YAML rule evaluator.

Execution uses an explicitly isolated captured rule and configuration set and a sanitized configuration-bearing environment. No ambient project or home configuration is discovered. Rule-authored file and ignore restrictions remain match restrictions intersected with XRAY-selected files, not a second filesystem traversal authority.

Current evidence demonstrates rule and configuration path forwarding and an existing `ruleDirs` fixture at E014. The narrower accepted grammar is a selected future product contract, not current XRAY validation. Future upstream integration qualification must prove this boundary and may not silently expand it.

### D05 — Canonical ordering, seek paging, continuation, and coverage

All ordering and paging values below are frozen future behavior. Map ordering is the UTF-8 path-segment tuple, parent before descendants, with a fixed kind tie-break. It never uses locale or filesystem arrival order.

Find ordering is existing calibrated internal quality rank descending, match-kind precedence, qualified name with an explicit case-sensitive tie-break, relative path, start and end bytes, `symbol_id`, and `FindRowId`. Exact case-sensitive identity outranks merely normalized identity. Global ranking requires a complete admitted selected inventory, and every returned row has one unique path-qualified `FindRowId`.

Interface ordering is requested section order `symbols`, `imports`, `exports`; within a section it is source byte order, end byte, and stable identity. Owner context is not a separately paged result population.

Search and impact ordering is relative path UTF-8 order, start byte, end byte, rule ID for rules or fixed evidence-kind rank for impact, then stable normalized record digest. The same source occurrence under distinct rules remains distinct diagnostic evidence.

Read normalizes each target to a byte interval and computes any enclosing result against that original target before merging. It applies requested context once, merges overlapping and adjacent intervals in the same file, preserves first-target order between merged segments, and then advances bytes within the segment. `targets` indexes associate merged source with original requests; per-target enclosing values remain aligned to those indexes, so a merged chunk never carries one ambiguous owner. No source byte is emitted twice within a read continuation sequence.

The canonical executor processes files from the captured manifest in canonical path order. A file's candidates are completely collected within its unit bound, normalized, validated, and sorted before any candidate from that file is exposed. A cursor seeks to a file plus a within-file stable record identity, not an offset and limit re-execution of a repository prefix; the find rank checkpoint instead seeks after one unique `FindRowId` in the complete ranked population. A cold cache may reanalyze the current file; it does not justify re-executing all preceding files.

Find is the explicit full-population exception: it computes the complete bounded selected inventory before globally ranking and seeking after the last `FindRowId`. Interface is likewise a complete bounded per-file declaration artifact. Neither emits an arbitrary partially ranked prefix. Byte-identical files remain distinct because their path-qualified row IDs differ.

For search and impact, a deterministic per-call window may finish with zero rows and a strictly advancing cursor beyond inspected files. Coverage then reports `scan_pending`; zero rows are not exact zero unless the requested population is complete. When remaining candidate budget cannot complete the next file, the executor discards that unexposed file prefix and returns only prior complete-file evidence with a cursor at that file's beginning. If that file is first in a fresh window and cannot complete at the full unit cap, it fails `analysis_limit`. It never sorts or exposes a truncated file prefix.

Cache hits are charged the same logical file, byte, and candidate work for window boundaries as uncached extraction. Warmth cannot change pages or coverage. Timeout, malformed output, I/O failure, or invalid backend result returns an error rather than a timing-dependent successful prefix. Cursor arguments cannot increase a work cap. No cursor is emitted when no valid deterministic continuation exists. Every emitted cursor advances. An indivisible record that cannot fit the requested bytes returns `budget_too_small` rather than an empty looping page.

**Cursor schema.** A repository cursor is base64url without padding of canonical UTF-8 JSON, with a frozen future maximum of 4096 encoded bytes. It has no HMAC, secret, authentication, expiration, server-side handle, or cache-generation dependency. Its payload is `{version:1,op:Operation,root:Digest,query:Digest,selection:Digest,snapshot:Digest,toolchain:Digest,checkpoint:Checkpoint}`.

`Checkpoint` is `{kind:'file',index:int>=0,after?:Digest} | {kind:'rank',after:FindRowId} | {kind:'namespace',after?:Digest} | {kind:'read',segment:int>=0,byte:int>=0} | {kind:'interface',after?:Digest}`. File index references the canonical captured manifest; absence of `after` means that file's beginning. A `rank` checkpoint's `after` must equal exactly one returned `FindRowId`; other `after` values identify the last returned item in the appropriate complete canonical population, and absent values identify the beginning.

A rootless catalog cursor is `{version:1,op:'search_tools',catalog:Digest,query:Digest,after:canonical_operation_name}`.

The executor rejects noncanonical, malformed, oversized, unknown-field, Boolean-integer, bad digest, bad range, bad identity, and invalid checkpoint encodings. It verifies current query, root, reconstructed source, and toolchain identities before seeking. Wrong request and cursor pair returns `cursor_query_mismatch`. Changed selected source, configuration, or toolchain returns `stale_cursor`. A rank checkpoint with no exactly matching row, or a structurally invalid or nonexistent checkpoint, returns `invalid_cursor`; a non-unique `FindRowId` is an analysis failure rather than an arbitrary seek choice.

An unsigned cursor is untrusted input. It is not evidence that the server issued a position and provides no filesystem or mutation authority. The executor validates safety and correctness of the requested seek and makes no tamper-authentication claim.

### D06 — Optional derived content caches

Caching is optional and expendable. The future cache uses a per-user platform cache directory under an XRAY-specific root-ID namespace. It stores derived content-addressed files only. It has no Git requirement, SQLite or other database, server cursor store, retained raw source generations, or plan storage.

A key is SHA-256 over artifact schema and kind, source digest, language, analyzer or toolchain digest, and normalized query digest when the derived artifact is query-specific. One canonical per-file declaration artifact serves `find`, `interface`, enclosing lookup, and exact symbol validation. Python signature and documentation enrichment attaches to that identity rather than creating another extractor truth.

The frozen future cache thresholds are a 512 MiB disk ceiling for the namespace, a 16 MiB single-artifact ceiling, 64 MiB in-process derived serialized-payload accounting, at most 32 root handles, and a 30-day maximum age affecting eviction only. An artifact larger than the cache-entry ceiling remains uncached when analysis itself is valid within operation limits.

Future cache writes are atomic user-only writes with restrictive directories and files, symlink rejection, bounded decode, and closed-shape and digest validation. A corrupt entry is a cache miss. Active writes are excluded from cleanup. Eviction and cleanup use exact validated cache paths and never delete user source or another active worktree's temporary analysis.

The clean cutover does not read or migrate `symbols.json` or `inventory.json` in the old Git or modification-time namespace. Skeleton-only extraction and cache machinery is deleted. Old cache cleanup is optional exact-namespace administrative cleanup, not startup migration and not a correctness prerequisite.

The 64 MiB figure bounds accounted retained payload bytes, not total Python RSS or child-process memory. File, candidate, queue, temporary-storage, and execution limits separately bound working inputs. Future qualification measures peak RSS and does not claim an operating-system memory sandbox.

### D07 — Exact future defaults, hard budgets, accounting, and fitting

Every value in this decision is a selected future default or hard threshold. These values are not current measurements, implementation-tuning suggestions, or token limits. A material change requires an explicit design delta.

**Wire accounting.** Count UTF-8 bytes of the complete canonical semantic JSON value, including envelope, escaped source, references, coverage, and cursor. CLI framing LF and MCP protocol framing are separate transport overhead. JSON errors have a separate 4096-byte hard ceiling. A caller `max_bytes` must be at least 4096. Text and pretty renderings are lossy display renderings; their actual output also respects the operation's hard response ceiling.

**Response defaults and hard ceilings.** The table's `default_bytes`, `hard_bytes`, `default_items`, and `hard_items` are frozen future thresholds. An item entry described as a range is a count bound, not a guarantee that every page fills it.

| Operation | Default bytes | Hard bytes | Default items | Hard items |
|---|---:|---:|---|---:|
| MCP discovery | 4096 | 16384 | One call-ready best match plus at most two terse alternatives | 10 |
| capabilities | 4096 | 65536 | Concise health and support; detail is explicit | — |
| map | 8192 | 65536 | 100 | 1000 |
| find | 6144 | 65536 | 10 | 100 |
| interface | 8192 | 65536 | 20 | 200 |
| read | 12288 | 65536 | 1–8 targets under one shared source and response budget | — |
| search and impact | 8192 | 65536 | 20 | 1000 |
| change plan and refine | 32768 | 262144 | 100 candidates / 20 affected files | 1000 candidates / 100 affected files |
| change verify and apply | 8192 | 65536 | One compact guard or application result | — |

Read has a future default of 64 source lines and 8192 source bytes per page and hard limits of 256 lines and 32768 source bytes, shared across all targets. One long line may span pages at UTF-8 boundaries. `context_lines=0` is the default and 10 is the maximum; context is included once in normalized segment scope, not repeated per page.

Interface has member depth 1 by default and a hard member depth of 1. Deeper inspection uses exact container references. Documentation is false by default. This replaces multiplicative per-container member budgets with one global declaration page.

Optional display ceilings are 2048 UTF-8 bytes for a signature, 512 bytes for documentation, and 512 bytes for occurrence text. Detailed captures have at most 16 capture records per result, and each transformed display text is at most 512 bytes. Clipping is character-boundary-safe and recorded in `Disclosure`. Full readable identity remains intact. Plans, diffs, and manifests never use display clipping.

Maps default to depth 2 and no symbol skeletons, documentation, or signatures. Numeric maximum depth is 64. Explicit `depth=all` remains bounded by namespace admission.

Pattern, replacement, literal, and name-query strings each have an 8192-byte hard ceiling. MCP discovery intent has a 1024-byte hard ceiling. Request JSON is at most 1 MiB. Cursor encoding is at most 4096 bytes.

A plan `max_bytes` is a complete response and artifact bound, not a truncation threshold. There is no partial or truncated-review override.

**Admission and execution thresholds.** Source admission is at most 20,000 selected source files, 256 MiB captured source per query, and 10 MiB per file. File size is checked before allocation and enforced while streaming so growth cannot bypass admission.

A namespace-only map admits at most 100,000 selected entries and 16 MiB aggregate UTF-8 path bytes. Source-file admission does not reject a metadata map solely because it contains 50,000 entries. A focused query admits its own selected namespace.

Find's complete inventory admits at most 100,000 declarations overall and 10,000 candidates per file. Its complete-inventory exception may consume the admitted 20,000-file and 256 MiB query bounds; it is not constrained to a streaming window that could emit an incorrectly ranked prefix.

A search or impact work window admits at most 1000 files, 50 MiB analyzed source, and 10,000 raw candidates, charged before filtering. One additional candidate may be decoded only as a bounded overflow sentinel and is never returned. A file that cannot fit the full fresh unit cap fails `analysis_limit`. Rule and impact filters cannot evade the raw cap.

Canonical file extraction completes a file under its allocated remaining candidate budget or exposes none of that file. Previously completed files can be returned with continuation before the uncompleted file, as specified in D05.

Rule and configuration closure admits at most 1024 input files, 1 MiB per YAML file, 8 MiB total, 64 nested YAML levels, and 100,000 scalar or container nodes total. These are separate bounded prerequisites, not a way around source admission.

Each child has a 16 MiB stdout and 64 KiB stderr hard byte limit, enforced while reading. Future execution uses fixed-size chunks and bounded queues, with at most 256 KiB queued per child. It never accumulates whole stderr or allocates an arbitrary line before checking its size. A child is terminated and reaped on overflow or cancellation.

One operation deadline is 30 seconds by default and 120 seconds hard, including capture, extraction, subprocesses, syntax, and serialization. A Git dirty-baseline child has an additional maximum of 5 seconds. Deadline exhaustion is an error, not a successful partial page.

There is at most one child process per operation. MCP admits at most four active operations and one active operation per root. There is no unbounded task queue. Busy admission fails a bounded `execution_limit` response. This protects shared process memory without locking out editors or separate CLI processes.

Per-operation temporary materialization is bounded to 320 MiB, including captured source, configuration, and execution scratch. Change preparation additionally keeps preimages, postimages, and stages under a 200 MiB mutation-working-data ceiling. Allocation or disk-space failure is operational failure, not empty data.

Replacement source or preimage and postimage each obey 10 MiB per affected file and 50 MiB aggregate. Candidate, file, and review ceilings are the plan table's future bounds. Apply cannot change bound or acknowledgement fields.

The old `XRAY_AST_GREP_OUTPUT_LIMIT_CHARS`, `XRAY_AST_GREP_TIMEOUT_SECONDS`, and `XRAY_MCP_INDEXER_CACHE_LIMIT` environment contracts are removed in the clean cutover. Shared typed request and catalog limits own new behavior. No environment override raises a hard ceiling.

**Fitting.** Reserve the exact required envelope and coverage or cursor before greedily adding whole canonical records. Optional display strings may be clipped only at declared field ceilings with `Disclosure`. Required safety facts cannot be dropped to hit a target. If one indivisible required record or complete callable schema cannot fit a caller's chosen bytes, return `budget_too_small` with `minimum_bytes` when calculable. Never split a reference, omit a required input constraint, return invalid JSON, or emit an empty non-advancing cursor.

### D08 — Actionable impact evidence without semantic overclaim

Impact answers where the selected definition's spelling occurs within declared selected inputs. It does not resolve occurrences to that definition. `resolution='unresolved'` is fixed and explicit.

The exact target is validated through the same per-file `SourceRef` resolver used by `interface` and `read` before occurrence search. Syntax mode enumerates exact identifier-spelling occurrences and classifies them with parser or tree evidence. Comment and string spelling may be included with corresponding syntax context. A text-shaped name followed by `(` is not enough to claim an AST call.

Only the selected declaration's defining-name token is excluded. Its whole definition range is not excluded, so recursive calls and other uses inside the body remain evidence. Other same-name definitions remain classified definition occurrences.

Impact uses precise byte spans, directly readable `OccurrenceRef` values, and enclosing references from the same file artifact. Enclosing absence or unavailability is explicit and never requires a whole-repository follow-up index.

When an import occurrence is directly observed, impact returns `module_text`, `imported_name`, and `local_name` where available. It does not follow aliases, even within one file, and emits no local-alias relation. The design deliberately rejects initial optional alias expansion because its completeness burden is not justified for the minimum major.

Lexical mode is an explicit deterministic path, not a fallback after zero structural hits. It matches exact spelling with identifier-boundary checks using pinned Unicode identifier rules plus `$` for JavaScript and TypeScript. Lexical hits use `evidence=lexical` and `kind=text` unless directly classified by the requested syntax pipeline.

Parser-recovered and unsupported forms receive explicit partial coverage and unknown evidence where usable. A required parser that is missing or failing does not silently switch modes. Structural zero never triggers another backend. There is no stage graph, evidence ontology, cross-file resolution, confidence probability, behavioral-search claim, generated test recommendation, or semantic rename promise.

### D09 — Guarded change lifecycle and mutation limits

The future lifecycle is `change_plan` → optional `change_refine` → optional `change_verify` → `change_apply`. Plan, refine, and verify are read-only. Apply is the only product operation that mutates source. Two ordinary product calls suffice for a complete plan, review, and apply with an independently supplied digest. Apply reexecutes every guard regardless of earlier verification.

The complete future plan is `ChangePlan={plan_schema:'xray.change.v1',root:Root,selection:Selection,source:ChangeSource,provenance:RepositoryProvenance,inputs:InputManifest,bounds:PlanBounds,chosen:{kind:'all'}|{kind:'edits',ids:Digest[]},files:PlanFile[],edits:PlanEdit[],baseline:Baseline,acknowledgements:Acknowledgements,eligibility:{applicable:bool,reasons:EligibilityReason[]},plan_digest:Digest}`. Objects are closed and every digest-covered array follows the canonicalization ledger below. A plan has no timestamps, transaction IDs, previews, counters derivable from arrays, next-action prose, or hidden server fields. `change_plan` and `change_refine` return this complete artifact through the plan-response exception in D03; no identity is repeated in their envelope.

`PlanBounds={max_candidates:int[1,1000],max_files:int[1,100],max_bytes:int[4096,262144],max_file_bytes:10485760,max_total_preimage_bytes:52428800,max_total_postimage_bytes:52428800}`. Frozen future defaults are 100 candidates, 20 files, and 32768 bytes. Fixed safety fields cannot be raised by a caller.

`InputManifest={sources:[{path:RelPath,bytes:int>=0,sha256:Digest}],configuration:[{path:RelPath,bytes:int>=0,sha256:Digest}],policies:[{name:string,sha256:Digest}],toolchain:Digest}`. Sources include the entire selected candidate universe, not only affected files. Configuration includes relevant ignore, rule, or project-config closure; policy records identify fixed generated, selection, and analyzer policy. The complete manifest is digest-covered, sorted and duplicate-checked by the ledger below, and subject to the review-artifact ceiling; a broad plan that cannot carry it must narrow scope.

`PlanFile={path:RelPath,preimage_sha256:Digest,postimage_sha256:Digest,preimage_bytes:int>=0,postimage_bytes:int>=0,mode:int>=0,syntax_before:SyntaxEvidence,syntax_after:SyntaxEvidence,new_diagnostic_count:int>=0,diff:string}`. `files` are sorted by UTF-8 path with no duplicate path. `diff` is one complete deterministic unified diff with three context lines, relative `a/` and `b/` headers, no timestamps, preserved source line endings and an explicit no-final-newline marker where needed.

`PlanEdit={edit_id:Digest,path:RelPath,start:int>=0,end:int>=start,before_sha256:Digest,after_sha256:Digest,changed:bool}`. `edit_id` hashes the domain tag, relative path, file preimage hash, exact range, before hash and after hash. `edits` are sorted by `(path,start,end,edit_id)`; identical duplicate records are deduplicated before hashing, while incompatible edits at one range conflict. Overlapping edits are rejected.

`SyntaxEvidence={analyzer:Digest,language:Language,diagnostic_count:int>=0,fingerprint:Digest,diagnostics:[{range:Range,signature:Digest,text:string}]}`. Diagnostics are sorted by `(range.start.byte,range.end.byte,signature,text)` and exact duplicate records retain multiplicity because syntax comparison is a multiset. It contains at most 50 diagnostics and 200 UTF-8 display bytes per diagnostic. If complete syntax evidence cannot fit, return `analysis_limit`; unavailable or truncated syntax is not valid evidence.

The retained syntax comparison is a multiset method. Each parse `ERROR` signature binds language and exact ERROR-node text, not shifted location. New errors are positive multiset differences. Diagnostic fingerprint hashes sorted expanded signatures. This remains syntax evidence, not a semantic correctness proof.

`Baseline={kind:'git',dirty_affected:RelPath[]}|{kind:'unmanaged'}`. Git is optional. `dirty_affected` is sorted by UTF-8 path and deduplicated. An installed Git failure while obtaining a managed baseline is an error, not a clean baseline. Git HEAD is not source truth. The caller must keep a recoverable worktree under either baseline kind.

`Acknowledgements={dirty_affected:bool,new_parse_errors:bool}`. Both default false and are set only by explicit planning input before digest calculation. `EligibilityReason` is one of `no_candidates`, `no_changes`, `dirty_affected`, or `new_parse_errors`; `reasons` are unique and sorted by the fixed order `no_candidates,no_changes,dirty_affected,new_parse_errors`. `applicable=true` exactly when reasons is empty. Unsupported syntax, overlaps, incomplete candidate universe and exceeded bounds are errors rather than applicable plans with disclaimers.

`plan_digest` is SHA-256 over canonical JSON of the complete plan excluding only `plan_digest`. It covers input manifest, complete diffs, edits, bounds, baseline, acknowledgements, eligibility, and provenance. Verify and apply require complete artifact comparison and an independent `expected_digest`.
**Plan-array canonicalization.** Arrays reachable from `plan_digest` use no filesystem, Git, YAML, parser, or backend arrival order. `Selection.paths` are UTF-8 path-sorted and deduplicated; `Selection.languages` use the fixed `Language` order and are deduplicated; ordered `Selection.globs` retain declared application order but exact duplicate globs are rejected. `InputManifest.sources` and `configuration` are path-sorted with one record per path; `policies` are sorted by `(name UTF-8,sha256)` with one record per policy name, and conflicting digests for one name are invalid. `chosen.kind='edits'` IDs are ascending Digest order and deduplicated. `ChangePlan.files` are path-sorted and unique; `edits` use `(path,start,end,edit_id)` order after identical-record deduplication, with overlap/conflict rejection. Each `SyntaxEvidence.diagnostics` array uses the range/signature/text order above and retains exact duplicate multiplicity. `Baseline.dirty_affected` is path-sorted and deduplicated. `eligibility.reasons` uses the fixed enum order and no duplicates. These policies are part of the closed plan contract; a noncanonical or duplicate-bearing submitted plan is `invalid_plan`, never silently normalized during verify or apply.

Plan and refine must complete the selected candidate universe under admission and deadline limits. They cannot create an applicable partial plan. An oversized review fails through `execution_limit` or `budget_too_small` as appropriate. Refine reevaluates the original source, configuration, toolchain, and candidate universe, validates requested edit IDs, and emits a new complete plan and digest. It cannot rescue an oversized nonexistent plan.

Verify and apply validate schema, supplied digest, complete canonical plan, root, selection, configuration, toolchain, namespace and candidate membership, every selected source digest, affected modes, current dirty baseline, syntax evidence, edit ranges and applicability. An added matching file in the selected universe, changed relevant configuration or toolchain, or changed affected mode invalidates the plan. Unrelated edits outside the selected universe do not. Acknowledgement changes require re-planning; apply cannot infer them. The mutation guarantees below apply only under the caller-stability precondition.

Before the first target write, apply builds every postimage, verifies all stages, preserves modes, and revalidates containment and preimages. It stages in each target directory and verifies staged bytes and syntax. Immediately before each replacement it revalidates current preimage and containment. It replaces files in canonical path order and verifies final postimages, modes and syntax. Original bytes remain in bounded process-owned preparation state until completion.

On an ordinary caught failure, apply attempts rollback in reverse replacement order. It restores only a target whose observed bytes still equal XRAY's expected postimage and never overwrites an independently modified third value observed before restoration. It verifies restored bytes and modes. Missing, unreadable or conflicting paths produce a truthful failed or indeterminate outcome with the observed conflict evidence; this preservation rule does not claim protection from an unobserved forward race.

**Caller-stability precondition and race boundary.** From the first apply guard through final verification, the caller must keep every affected file and every ancestor directory from that file through `ROOT` stable and exclusively writable, including against other CLI processes. MCP per-root serialization prevents only its own overlapping operations. If that precondition is violated, a forward race between revalidation and replacement may write a concurrent value or an ancestor-namespace change may redirect path resolution; those outcomes are outside the guarantee and are not described as refusal or third-value protection. If a caught rollback later observes a third value before restoring a target, the rollback rule above still leaves that value untouched and reports the conflict. This design adds no cross-process isolation claim or mandatory interprocess-lock subsystem.

There is no `.xray/transactions` directory, durable backup journal, transaction ID, pending-transaction detector, `change_recover` operation, automatic restart recovery, or roll-forward machinery. Temporary stages are not a durable recovery promise. Interruption by SIGKILL, power loss, interpreter failure, or storage failure can leave a partial application and no JSON result. A later read cannot know whether a crash occurred and must not claim automatic recovery. The caller inspects every planned path and diff and restores from its own recovery baseline. A successful response means the running process verified completion, not power-loss durability.

`RollbackStatus` is `not_attempted | succeeded | failed`. `MutationFailureState` is `not_applied | rolled_back | partially_applied | indeterminate`. Success is state=`applied` and `rollback_status=not_attempted`. Every recognized `change_apply` error, including malformed input and any stale, containment, dependency, bound, plan or pre-write rejection, carries mandatory top-level `mutation` with authoritative state and rollback status; applicable conflict details retain only bounded `conflict_edit_ids` and `additional_conflicts`; if no plan digest was validated, `mutation.plan_digest` is omitted. Before the first target write, that mutation has `state=not_applied` and `rollback_status=not_attempted`. Verified restoration of all changed targets is `rolled_back`/`succeeded`. Failed restoration with known remaining changes is `partially_applied`/`failed`; inability to establish final bytes is `indeterminate`/`failed`. An unsuccessful or partial apply is never `ok=true`.

Deleted plan fields are `rollback_attempted`, `rollback_succeeded`, `rollback_count`, redundant applied, changed, or no-op counters, `transaction_id`, `recovery_required`, and derived compatibility summaries.

### D10 — Component ownership, CLI/MCP parity, and typed catalog

Future dependency direction is `CLI/MCP → operations.execute → strict models plus repository, analysis, and change services → bounded filesystem, executor, and cache primitives`. Presentation consumes immutable values only. Core never imports CLI, MCP, FastMCP, skills, docs, installers, reports, tests, or harness code.

| Future lane | Owned paths | Contract |
|---|---|---|
| Contract | `src/xray/models.py`, `src/xray/presentation.py`, `src/xray/operations.py` | Closed request, result, reference, error, and plan values; canonical serialization; output fitting; cursor codec; a small ordinary-Python `OperationSpec` table; and `execute(Request)->Result`. No plugin system, generic dependency container, or second schema language. |
| Repository/runtime | `src/xray/core/repository.py`, `src/xray/core/cache.py`, `src/xray/core/ast_grep.py` | Selection, capture, reference source resolution, optional derived cache, bounded subprocess ownership, and configuration dependency capture. Matching and rendering remain upstream authority. |
| Analysis | `src/xray/core/indexer.py` | Stateless map, declarations, find, interface, read, search, and impact orchestration. Retain this file while removing extracted responsibilities; do not perform a class-per-operation refactor. |
| Change | `src/xray/core/replacement.py` | Plan, refine, verify, apply preparation, guards, and ordinary staged writer. No journal or recovery component. It uses identical repository, declaration, syntax, and executor contracts. |
| CLI | `src/xray/cli.py` | Handwritten natural grammar, shell path, file, and stdin forms, JSON/text/pretty framing, and exits. It performs no snapshot, analysis, slicing, or independently chosen defaults. |
| MCP | `src/xray/mcp_server.py` | Stdio, search and call discovery, protocol result framing, annotations, progress, cancellation, and bounded admission. It performs no root inference, string-to-Boolean coercion, or stateful result side-channel reconstruction. |
| Guidance/distribution | `src/xray/guidance.md`, `skills/xray-cli/`, `src/xray/agent_skills/xray-cli/`, `src/xray/skills/xray-progressive-discovery/`, `README.md`, `pyproject.toml` | One short authored workflow and limitations source plus generated contract-bearing sections. Installer mechanics, entry points, Python floor, and resource addresses remain. The guidance writer owns both byte-identical CLI-skill copies. |

Given the same normalized repository request, root, captured inputs, toolchain and response budget, CLI and MCP return the identical semantic JSON value, including errors and coverage. CLI JSON success or error is one complete value on stdout and progress is on stderr. MCP's closed `search_tools`/`call_tool` request, result, error and newline framing are specified in D03; framing, required text mirroring, `isError`, annotations, progress and cancellation are intentional transport differences. CLI text and pretty output, files and stdin, CLI exits, MCP discovery resources/prompts and CLI-only skill administration do not form a second semantic API.

The finite `OperationSpec` is represented on the wire by the closed `OperationContract` and references existing typed models and handlers, canonical CLI spelling, one-sentence description, requiredness, defaults, bounds, result schema and mutation class. It derives only contract-bearing help fragments, MCP schemas and annotations, discovery, capabilities and generated guidance sections. The handwritten CLI remains handwritten. Strategy and caveats are authored once in `src/xray/guidance.md`; XRAY does not generate its entire README, architecture packet, harness or workflow from a DSL.

MCP initially exposes only the closed `search_tools` and `call_tool` transport methods. Discovery accepts natural intent or exact operation name, not regex. The default result contains one best `OperationContract` with its complete bounded callable argument schema and at most two terse name, description and mutation alternatives; it is sufficient for a valid first call. Exact-name discovery returns one complete contract. Catalog enumeration and detail use the explicit bounded modes in D03. Default discovery never requires summary to full to call, and ranking scores, tags and explanation traces are not routine output.

If a complete `OperationContract` exceeds the requested discovery budget, discovery returns `budget_too_small` rather than omitting required argument constraints. Operation contracts fit the future hard 16 KiB discovery bound. `call_tool` accepts only the closed named arguments in D03, applies the matching operation hard response bound, and returns a complete semantic `Success|Error` value; an insufficient call budget returns typed `budget_too_small` without a partial value. Natural change or rename intent ranks `change_plan` and describes structural replacement, not semantic rename safety. Explicit apply intent discovers `change_apply` with destructive annotation and the full reviewed-artifact requirement.

The future catalog preserves `xray://workflow`, `xray_discovery_plan`, `skill://xray-progressive-discovery/SKILL.md`, and the existing skill template address. Their content changes only during future implementation, never in this documentation freeze. Generated package data carries catalog and guidance identity once. Deterministic generation and installed, package, and repository copy parity are future gates, not runtime dependencies on `docs/`.

### D11 — Clean current-to-next-major migration and deletion matrix

The following matrix is the complete future disposition of named current surfaces. `Current` describes the 0.11.4 or historical compatibility surface observed in repository evidence. `Future disposition` is not current behavior. Unknown removed operations fail `unknown_operation`; no compatibility shim silently preserves them.

| Current surface | Future disposition |
|---|---|
| `xray`, `xray-mcp`, Python 3.10+, stdio MCP, JSON/jq, skill install, installers, and configuration generator | RETAIN. Change only necessary packaged guidance or direct dependency metadata; no service, HTTP, installer, or harness redesign. |
| `explore`, `explore_repo`, `map` alias, `invoked_as`, `include-symbols`, skeleton tree text, `strict-focus`, `include_root_context` | REPLACE with `map`, navigation-only metadata, first-class seek paging, focus descendants by default, optional ancestor chain, and sole item-limit spelling `--limit`. Remove aliases and duplicate tree or skeleton output. |
| `find_symbol`, scored symbol handoff, `abs_path`, `min_score`, `include_scores`, and confidence | MERGE into `find`, strict references, explicit root, match policy, and `match_kind`. `.data.items[N].ref` replaces `.symbols[N]`. Remove numeric and public compatibility fields and weak dictionary input. |
| `interface`, `read_interface`, `read_interface_structured`, unbounded legacy string or full output, and `max-members` | MERGE into `interface` with flat globally bounded declaration pages and exact nested identity. Optional text is rendering, not another tool. Recursive depth beyond one uses exact container requests. |
| `imports`, `file_imports`, `exports`, and `file_exports` | MERGE into optional `interface` file sections, retaining observed import and re-export syntax without module-resolution claims. |
| `read-symbol`, `read_symbol`, `symbol-at`, and `symbol_at` | MERGE reads into `read` with `SourceRef`, `OccurrenceRef`, and location targets, optional enclosing result, and eight-target global budgeting. Delete public `symbol_at` and its whole-repository inventory prerequisite. |
| `impact`, `what_breaks`, inferred root, high/medium/low confidence, hidden ripgrep, and Python fallback | REPLACE with `impact`, explicit root and exact target, unresolved name occurrences, exact spans, and explicit syntax or lexical mode. Delete fallback chain, confidence, and full-body exclusion. |
| `search_pattern`, `scan`, `scan_rules`, `check_rules`, and `rules check` | MERGE into `search` with explicit pattern, rule, and literal variants. Remove scan and rules-check duplicate entry points and all `--fix` search behavior. |
| `rules explain`, `explain_rules`, `rules test`, and `test_rules` | REMOVE from XRAY public product. Expert rule inspection and testing uses ast-grep directly. Retain validation diagnostics needed to execute selected rules; add no forwarding wrapper. |
| Arbitrary `sgconfig`, directory or environment or ancestor configuration, and custom grammar dependencies | REPLACE with contained standalone rule files or explicit closed `ruleDirs`-only config. Reject dependency-bearing configuration. Inline local rules remain supported. |
| `replace plan`, `refine`, `verify`, `apply`; `plan_replacement`, `refine_replacement`, `verify_replacement`, `apply_replacement`, and `apply_rule_fixes` | MERGE and rename to `change plan|refine|verify|apply` and flat MCP `change_*`. Separate verify is optional. Pattern and rule application have one guarded route. |
| `rewrite`, `rewrite_pattern`, `scan --fix`, direct mutation, and unsafe exact-name backdoors | DELETE. Unknown old operations fail. Migration guidance points to new planning, but no callable shim remains. |
| `xray.replace.v1`, `xray.replace.v2`, legacy-v2 plan reconstruction, truncated-review or no-op overrides, preview plus diff duplication, rollback aliases, and derived counters | REJECT or re-plan as `xray.change.v1`. Keep one complete diff and complete edit and input manifests. Remove overrides, reconstruction, next-action prose, old rollback aliases, and duplicate counters. |
| `xray.cli.v1`, `xray.cli.v2`, `xray.cli.v3`, `--schema`, `--detail full` raw compatibility, legacy strings or errors, and heterogeneous MCP envelopes | DELETE in the major cutover. `xray.v1` is the first unified transport-neutral contract, not a package release number. Selective bounded fields are disclosure, not old-schema compatibility. |
| Offset cursors, shortened fingerprints, `returned`, `total_exact`, `truncated`, and lower-bound totals | REJECT old cursors. Use full-bound seek cursors, optional exact totals, and separate coverage. Derive item count from items. No TTL or cache-expired cursor state. |
| `doctor`, `xray_capabilities`, aliases, regex tool discovery, summary or full duplication, and hidden legacy exact invocation | REPLACE with `capabilities` and search-first MCP call-ready best match. Delete regex discovery, duplicate metadata, and all legacy callable names. |
| Git or modification-time `symbols.json` and separate inventory caches, `last_*` metadata, adapter paging or normalization, and inactive `lsp_config.json` | DELETE or replace with content-derived per-file artifacts and atomic results. Remove inactive LSP asset after future dependency and package inventory proves no consumer. Do not migrate old cache contents. |
| `XRAY_AST_GREP_OUTPUT_LIMIT_CHARS`, `XRAY_AST_GREP_TIMEOUT_SECONDS`, and `XRAY_MCP_INDEXER_CACHE_LIMIT` | REMOVE as named environment contracts. Shared typed request and catalog limits and fixed cache ceilings replace them; no hidden ceiling override exists. |
| Initial `replace_recover`, `.xray/transactions`, durable backups, journal, transaction IDs, `recovery_required`, and crash-restart protocol | REJECT and defer. None exists in the selected schemas, components, phases, gates, or rollback plan. Crash inspection is not automatic recovery. |
| Current README, skills, `PROJECT.md`, `ARCHITECTURE.md` product bodies, and existing tests | INTENTIONALLY UNCHANGED by this documentation freeze. Future implementation migrates affected consumers, packaged copies, docs, and behavior tests in the corresponding slice. Tests that only pin deleted contracts or plumbing are removed rather than renamed into false guarantees. |

The migration is a clean major cutover. It does not retain aliases or old schema wrappers merely to ease implementation. Every future implementation phase must migrate every affected caller, command, tool, flag, skill, package or resource identifier, test, documentation copy, and obsolete internal route before its gate. This packet itself does not perform that migration.

### D12 — Future implementation phases, ownership, and rollback boundaries

The future phase DAG is `A0 authorized documentation freeze → I0 authorized baseline and contract qualification → I1 exact-read vertical slice → I2 navigation and declaration workflow → I3 search, impact, and configuration closure → I4 guarded change cutover → I5 final whole-product qualification`. CLI, MCP, and guidance preparation may run in parallel behind each frozen service contract. I2 and I3 core work are serialized because both own `indexer.py`. Pattern-change preparation may proceed after I1 repository and executor interfaces freeze, but I4 acceptance waits for I3 search and configuration semantics.

The phase contracts are:

| Phase | Future outcome and work | Gate | Rollback boundary |
|---|---|---|---|
| A0 | Self-contained frozen packet, companion digest, and two link-only authority insertions. Encode D01–D14 and traceability while preserving current runtime and harness bodies. | Documentation integrity, exact-byte digest, bidirectional traceability, no missing technical choice, and no changed current-runtime claim. | Remove only authorized packet, companion, and exact inserted paragraphs after preserving unrelated work. No product source, cache migration, or user mutation exists. |
| I0 | Separate implementation authorization and frozen current-base benchmark or proof corpus. Record actual 0.11.4 baseline, gold tasks, dependency artifacts, tokenizer assets, hardware, and transcripts. Qualify closed YAML/config and bounded executor integration against pinned upstream artifacts without broadening config. | Each accepted family has complete request, result, and recovery route; observations are separated from executed evidence. No implementation begins from an unmeasured regression or open schema option. | No product cutover. Preserve baseline evidence and current binary. |
| I1 | Actual CLI and stdio MCP direct, reference, and batched reads through one result and capture boundary. Contract lane lands models, serialization, cursor, and execute interfaces; repository lane captures; analysis lane supplies declaration identity and exact reads; adapters adopt the service. | G1, G2, G3, and G4: unchanged handoff, source race, nested identity, UTF-8 and long-line continuation, containment, and real transport equality. | Revert the whole unshipped vertical slice or restore its exact preintegration artifact. No user writes or durable state transition exists. |
| I2 | Useful map, find, interface, and read workflow with optional derived cache. Implement namespace map and frontiers, complete ranking, flat interface, imports and exports sections, and cached declaration artifacts; remove superseded machinery as callers migrate. | G2, G3, and G5: canonical pages, same-size and same-mtime edits, cache-off/cold/warm/corrupt/evicted parity, exact nested identity, known-symbol two-call task, and focused budgets. | Roll back the whole slice. Abandon only the new derived-cache namespace; do not erase source or unrelated old cache state. |
| I3 | One deterministic pattern, rule, and literal search plus honest actionable impact. Implement file-unit and window pipeline, closed rule config capture, named captures, lexical input classification, exact occurrence and enclosing output. Remove old scan, rules, and fallback routes. | G3, G4, and G6: randomized arrival, noisy prefixes, zero-row advancement, per-file cap, unknown-language text, rule membership and config drift, recursive uses, and unresolved same-name evidence. | Revert the read-only slice. Temporary capture and cache are disposable. No hidden query store or plan state exists to migrate. |
| I4 | One complete guarded pattern and rule change lifecycle on both transports. Implement `xray.change.v1`, complete diff, input and edit manifests, optional refine and verify, mandatory apply guards, staged writes, and caught-failure rollback. Remove direct mutation and old reconstruction. | G7: plan-only and verify no writes, all-field tampering, source/config/toolchain/mode/candidate drift, overlap, no-op, dirty and syntax acknowledgements, review bounds, real changes, caught failure, and interruption limitation. No restart-recovery gate or journal prerequisite exists. | Code rollback does not undo user edits. Preserve worktree bytes and caller recovery baseline; inspect all planned paths after interruption. No journal state exists to migrate or strand. Re-plan before a different binary or schema. |
| I5 | One coherent next-major product without shipped compatibility layer or stale authority. Finish deletion inventory, migrated tests, docs, skills, package data, inactive LSP removal, environment and projection alias removal, and accepted-product authority update only after implementation. | G1–G8 plus every current project canonical product, static, build, package, and live smoke gate on one unchanged integrated artifact. Complete token and work targets; no deleted operation discoverable or callable. | Restore accepted previous product artifact only after preserving independent user changes and new plan files. Old and new plans are not migrated; caller re-plans for restored binary. No commit, release, or remote authority follows. |

The contract lane exclusively owns `models.py`, `presentation.py`, and `operations.py` until interfaces freeze. Other lanes submit requested deltas rather than overlapping edits. After interfaces freeze, repository/runtime, CLI, MCP, and guidance paths are semantically parallelizable subject to actual writer and child ceilings. `indexer.py` is one analysis-owner write set; I2 and I3 are not independent writers merely because features differ. Serialize them or move a proven responsibility before allocating disjoint ownership. `replacement.py` is disjoint after repository, executor, and plan models freeze. No mutation-journal or recovery-test lane is allocated.

Each existing test file has one writer at a time. Behavior-owner tests use disjoint filenames or serial ownership. Guidance ownership controls repository and packaged CLI-skill copies together. Root integrates accepted artifacts and runs final project validation once. These future allocations do not authorize implementation under this packet.

### D13 — Future acceptance gates, counterexamples, and value thresholds

All gates in this decision are future acceptance evidence. None has run for this packet. Historical reports or architecture observations motivate the work but are not the current baseline, tokenizer results, benchmark success, or runtime qualification. A missed target or upstream prerequisite blocks its phase; it does not silently change a frozen budget, scope, or guarantee.

**Future gates.**

| Gate | Contract and required proof |
|---|---|
| G1 | Exercise actual `xray` CLI and `xray-mcp` stdio with equivalent normalized requests. Compare semantic JSON for every operation and representative errors, including CLI stdout and exit and MCP `isError`. Exercise the closed `OperationContract`, `LimitCatalog`, `ToolchainManifest`, reference, provenance, `ChangeSource` and plan-response contracts; MCP `search_tools`/`call_tool` request/result/error schemas and framing; and prove unknown fields, invalid integers and Booleans, invalid ranges, wrong-root references, old names, old schemas, old plans and unsafe aliases reject. Framework-only mock echo does not qualify. Every recognized `change_apply` error, including malformed argument, file-loading, plan, dependency, bound and other pre-write rejections, must expose mandatory top-level `mutation` with authoritative state and rollback status; applicable bounded `conflict_edit_ids` and `additional_conflicts` remain only in ordinary code-specific `ErrorDetails`, and an unvalidated plan digest is omitted from `mutation`.
| G2 | Analyze captured bytes while changing live files after capture and prove output and digests describe captured bytes. Exercise membership, configuration, ignore, toolchain, Git and non-Git changes, irrelevant out-of-scope edits, same-size and same-mtime rewrites, duplicate nested owner names, exact nested containers or members, and tampered identities. File-scoped read or interface cannot hash or parse another source file. |
| G3 | Randomize filesystem and backend arrival order and compare concatenated pages with one canonical reference population across changing positive limits and byte budgets. Include empty advancing windows, final empty traversal, large noisy filtered files, over-cap units, long Unicode lines, CRLF, no-final-newline source, overlapping eight-target reads with per-target enclosing values, and stale, malformed or oversized cursors. Include two byte-identical files whose matching declarations have identical offsets and symbol IDs; split pages across them and prove distinct path-qualified `FindRowId` checkpoints produce no repeated or omitted rows. Prove no repeated or omitted source bytes or rows and no unhonorable cursor.
| G4 | Use controlled child processes that overflow stdout or stderr, emit a huge unterminated line, produce malformed JSON or UTF-8, exit nonzero, or hang. Observe bounded queues, output bytes, child reaping, and typed failure rather than empty success. Exercise source, configuration, temporary-space, window, request-admission, and cache-hit budget charging. No cursor raises a hard bound. |
| G5 | Compare identical normalized requests with disabled, cold, warm, cleared, corrupt and evicted cache states and require identical successful semantic JSON. Same-size and same-mtime edits refresh truth. A known unique qualified definition is top one. Every valid emitted reference is accepted unchanged without reconstruction. Exercise file-interface `kinds`/`visibility` filtering before member disclosure, exact-target filter rejection, exact nested identity, and merged reads whose enclosing results remain per original target without an ambiguous owner. Known symbol signature or body takes at most two analysis calls; known location takes one read; up to eight short occurrence ranges expand in one bounded read.
| G6 | Use labeled Python, JavaScript, TypeScript, and Go fixtures containing recursive calls, same-name definitions, imports and local alias spellings, unresolved receivers, comments and strings, malformed syntax, and unknown-language text. When complete is claimed, exact-spelling occurrence coverage is 100% in the declared profile. No resolved dependent or alias-completeness claim appears. Test standalone rules and supported `ruleDirs`, added or deleted rule files, path and symlink escapes, config escapes, unsupported dependency keys, and ambient-config suppression. |
| G7 | Run actual small pattern and rule plans, refinements, verify and apply on both transports. Exercise all-plan-field tampering, old versions, changed tool, config, source, mode or candidate membership, dirty and parse-error acknowledgements, UTF-8 ranges, overlaps, no-op and zero candidates, full-review limits, independent digest, staged and postimage verification failure, final verification failure, caught rollback failure and third-value external conflicts. Regenerate complete plans with randomized filesystem, backend, Git and diagnostic arrival order and require identical canonical plan bytes and digest under the full array-order/duplicate ledger. Assert plan/refine use the self-contained response exception with no duplicated envelope identity, and every `change_apply` error carries state plus rollback evidence. Exercise the caller-stability precondition over affected files and their ancestor namespace; distinguish an unobserved forward race outside the guarantee from a caught rollback that observes and preserves a third value. Kill a subprocess after its first target replacement and inspect the worktree to demonstrate the documented partial-application limitation, not crash recovery.
| G8 | Run deterministic guidance and catalog generation, copy parity, installed examples, intent discovery corpus, complete operation/deletion inventory and token or work benchmarks. Compare repeated catalog generation under randomized operation enumeration and require byte-identical closed contracts and discovery framing. Exercise call-ready discovery and insufficient-budget errors without a second schema fetch, including exact `search_tools`/`call_tool` result/error mirroring. Root then runs unchanged-candidate project gates and live CLI or MCP workflow once. Keep tests only for observable contracts and plausible regressions; benchmark scaffolding is not production architecture.

**Counterexamples that must fail or remain explicit.**

| Counterexample | Required future result; prohibited claim |
|---|---|
| Live source changes after capture or a relevant file changes before continuation | `source_changed` or `stale_cursor`; never a successful result claiming an atomic snapshot. |
| Same-size and same-mtime rewrite | New content digest and changed semantic result or stale input; never modification-time equality as truth. |
| A file's candidate stream exceeds a work-window cap | `analysis_limit` when first or unfinishable, or prior complete-file rows with an advancing cursor; never a sorted truncated prefix or exact empty. |
| A bounded search window inspects files but finds no row | Advancing cursor with `coverage.state=partial` and `scan_pending` when continuation exists; never false complete zero. |
| Unsupported syntax, non-UTF-8, or NUL-bearing input | Typed unsupported or partial coverage; exact read fails `invalid_encoding`; never silent empty success. |
| A same-name function is not bound to the selected definition | `impact.resolution='unresolved'` with occurrence evidence; never resolved caller, dependent, confidence, or safe rename claim. |
| An import alias occurs | Direct import spelling evidence only; no alias-following or local-alias relation. |
| A nested container or member is requested | Exact owner-chain identity and direct-member result; no sibling flood or unbounded expansion. |
| A cursor has wrong request, changed source, malformed checkpoint, fabricated position or a non-unique row key | Typed cursor rejection; a `rank` checkpoint must name exactly one `FindRowId`, including when two byte-identical files have the same declaration offsets and symbol IDs; unsigned cursors grant no authority. |
| A plan has overlap, no changes, incomplete universe, new parse errors, dirty affected files, or oversized review | Typed invalid or inapplicable complete plan; no truncated-review or no-op override. |
| An apply artifact is altered, source/config/toolchain/mode drifts, or an external editor races with apply | Under the caller-stability precondition, apply refuses drift and does not apply a different reviewed artifact. A forward race that violates stable affected files or ancestor namespace is outside the guarantee and may overwrite a concurrent value or invalidate containment; a third value observed before caught rollback is preserved and reported, never overwritten. |
| A caught write fails after earlier files changed | Every returned `change_apply` error carries mandatory top-level `mutation` with authoritative state and rollback status. Applicable bounded conflict IDs remain in ordinary code-specific details. Reverse caught rollback reports truthful `rolled_back`, `partially_applied` or `indeterminate` and never `ok=true` for failure. |
| SIGKILL, power loss, interpreter failure, or storage failure interrupts apply | Worktree may be partial and has no JSON result; caller inspects and restores from its baseline. Never automatic recovery or durable-transaction claim. |
| Cache is corrupt, absent, evicted, warm, or disabled | Successful semantic JSON is identical; cache state cannot alter truth or coverage. |
| Discovery contract exceeds a caller budget | `budget_too_small`; never omit required constraints and call the response call-ready. |
| Old command, old schema, old cursor, regex discovery, or old mutation alias is requested | `unknown_operation` or typed invalid input; never a hidden compatibility wrapper. |

**Benchmark methodology and frozen future targets.** The implementation phase first freezes the actual 0.11.4 base, source fixture hashes, dependency and tool binaries, normalized task inputs, gold evidence, and current successful workflows. The corpus includes XRAY itself, Python, JavaScript, TypeScript, and Go fixtures, a 50,000-entry namespace, large and noisy same-name inputs, unsupported-language and text files, and Git and non-Git roots. The future workflow does not require a mandatory map merely to match an old recipe.

The future measurement uses offline `cl100k_base` and `o200k_base` through one pinned tiktoken release. I0 records the exact wheel and version and encoding-asset digests before measuring. Selected encodings and dual-encoding gates are fixed; the recorded artifact version is evidence, not a runtime dependency or architecture option.

Accounting counts complete cumulative request and response tokens, initially exposed MCP schemas, discovery responses, retries and invalid calls, repeated source, input plans submitted to verify and apply, and protocol text duplication actually exposed to the agent. It reports p50, p95, and maximum per operation and complete task separately for cold and warm workflows. It also measures canonical JSON bytes, tool calls, end-to-end latency, source bytes read or hashed, and peak RSS on pinned hardware.

For each representative request, the future qualification performs 100 repetitions split across disabled, cold, warm, cleared, and corrupt-cache states. Successful rooted semantic JSON must be byte-identical for identical inputs, toolchain, and budgets. Only transport progress and timing instrumentation outside semantic payloads may be excluded from determinism comparison; coverage and source identity are not excluded.

The following are frozen future acceptance targets, not measurements:

- Completed context tasks have at least 35% lower median cumulative input plus output tokens than the frozen current-base workflow under each encoding, with no more than 5% p95 token regression and no loss of gold evidence or safety disclosure.
- Default-call tokenizer p95 is at most 1500 tokens for map and find, 2500 for interface, impact, and search, and 3500 for read under each encoding. These are corpus gates, not runtime token limits and not a bytes-divided-by-four assertion.
- Default completed context workflow output p95 is at most 16,000 tokens, excluding an explicitly requested large complete change review. Total-task reduction still counts all normal request and response overhead.
- MCP initial `search_tools` and `call_tool` schema overhead is at most 1000 tokens, and default successful discovery response is at most 1200 tokens. A frozen non-template intent corpus achieves at least 95% top-one and 99% top-three operation selection and at least 99% valid first calls after one discovery response.
- No mandatory discovery or preflight exists for known operations. There is at most one discovery before the first unfamiliar operation and no summary-to-full prerequisite.
- 100% of valid returned definition, member, and occurrence handoffs are accepted without reconstruction on unchanged inputs. Stale, wrong-root, and invalid handoffs reject deterministically. Known name plus requested body or signature takes at most two analysis calls; known location takes one; up to eight short occurrence expansions take one batch read.
- An ordinary applicable change plan to reviewed apply uses two product calls. A representative plan with at most 10 short edits in at most 3 files fits at most 8000 tokens under each encoding without omitted review evidence. Larger plans remain subject to complete 32 KiB and 256 KiB byte bounds.
- Zero source bytes repeat across a continuation sequence. Repeated evidence tokens are below 10% across a typical find to interface/read to impact inspection, excluding mandatory small identity and coverage fields from that repetition ratio only.
- Matched completed-task p95 end-to-end latency regression is at most 10% on frozen hardware and corpus. Repeated focused workflows read or hash at least 50% fewer source bytes than the current baseline. Actual totals are reported rather than inferred from architecture.
- Every hard byte, admission and execution limit is exercised. Under the caller-stability precondition, no false exact-empty result, outside-root write or altered reviewed-artifact application and no inaccurate authoritative rollback outcome is accepted; races outside that precondition are measured only as the documented residual limitation.

A missed target blocks the owning phase. The implementation may not silently tune a budget, reduce evidence, omit a safety field, or fabricate a baseline. A new guarantee, stronger crash boundary, broader language or configuration surface, or retained legacy client requires a new authorized design delta.

### D14 — Residual risks, deferred boundaries, and authorization

The residual future risks and mitigations are:

| Risk | Severity and mitigation |
|---|---|
| Captured read set is mistaken for atomic repository history. | High. Keep the explicit consistency label, consumed-byte analysis, observable-race failure, and stale continuation. Never claim all files coexisted or old snapshots remain replayable. |
| Per-page capture and canonical file completion cost more I/O or latency than optimistic prefix scanning. | High. Scope first, use metadata-only map and per-file derived cache, make the complete-inventory exception explicit, and measure latency and I/O. Never use modification time or hidden persistent generations to meet targets. |
| Closed rule configuration breaks existing expert configurations. | High and intentional major break. Document standalone and supported `ruleDirs`, retain inline local rules, move expert tooling to ast-grep, reject unknown dependency fields before invocation, and do not leave configuration closure unresolved. |
| Strict references lose Python signature or documentation fidelity or misrepresent parser coverage. | High. Attach Python enrichment to canonical identity, expose supported profile and typed incompleteness, and exercise nested and unsupported forms. Do not substitute a different identity resolver silently. |
| Compact response budgets fit fewer records than nominal item defaults. | Medium. Document both ceilings, exact fitting, usable cursors, and `budget_too_small`. Item defaults are maxima, not promises to fill every page. Mandatory evidence is never dropped. |
| MCP best-match schema cannot meet discovery token gates. | Medium. Keep the selected small API and compact model-derived contract. Return one complete best match and terse alternatives. A hard-bound failure is honest; qualification cannot add a required second schema fetch. |
| Optional display clipping is mistaken for complete signatures or captures. | Medium. Use per-field ceilings and `Disclosure`; preserve exact source references. Plans, diffs, and manifests never clip. |
| Same-name, alias, or import evidence is marketed as semantic impact. | High. Fix unresolved resolution, label parser or lexical method, forbid alias following and confidence graphs, and require structural-rename counterexamples. |
| Process interruption or an independent editor leaves partial mutation. | High residual risk, explicitly retained. Require a caller recoverable baseline and a stability precondition covering every affected file and each ancestor directory through `ROOT`, complete guards, stage and postimage checks, conflict-preserving caught rollback, authoritative top-level `mutation` state/status and crash inspection. A forward race that violates stability is outside the guarantee; a third value actually observed before caught rollback remains protected. Add no mandatory journal or cross-process isolation claim. |
| Cache or input-loader abstractions become a framework or privacy store. | Medium. Keep three narrow ownership seams, optional derived artifacts, bounded user-only writes, no raw source history store, and a catalog limited to contract-bearing declarations. |
| Current and future authority blurs during authoring. | High. Keep the four-path freeze, exact status, link-only authority insertions, no current README or runtime change, embedded traceability, and future-only gates. |
| Historical or inspected evidence is presented as current executed proof. | High. Separate code observations, inference, historical byte reports, selected thresholds, and future baseline runs. Bind qualification to the unchanged actual candidate. |

The following work is deferred and is not an implementation prerequisite for this selected design:

- Durable mutation journals, recovery commands, automatic interruption detection or rollback, and stronger power-loss guarantees.
- Cross-process hostile-writer isolation, semantic rename and type resolution, cross-file alias or module graphs, behavior search, and test-selection intelligence.
- Persistent source generations, watchers, service or database deployment, cache-only handles, hidden plan storage, and paged review receipts.
- Generic batched operation orchestration. Only bounded source-target batching is included.
- Full arbitrary ast-grep project or custom-language configuration and public rule-development or testing tools.
- Generated CLI, plugin or operation DSL, whole-document or harness generation, installer redesign, CI or release work, and remote delivery.

No genuine user architecture decision blocks this selected minimum major. Implementation authorization, protected delivery, stronger crash guarantees, legacy-client retention, or custom-language requirements require new scope or risk authority. They are not unresolved implementation options in this packet. Actual runtime correctness, tokenizer measurements, performance, upstream integration, and final project gates remain intentionally unexecuted future prerequisites.

## Transformation evidence

This section records how source propositions became the closed future contract. The source inventory includes favorable proposals, rejected mechanisms, proposed numbers, compatibility promises, and evidence-only observations. A disposition is one of `retain`, `replace`, `merge`, `remove`, `defer`, or `evidence-only`. Source locators are provenance literals; the packet does not require their future availability.

**Source-to-result map.**

| Source ID | Source locator | Proposition | Disposition | Decision IDs | Reason |
|---|---|---|---|---|---|
| C001 | `agent://ChiefArchitect` | Make actionable code evidence bounded, reproducible, and safe for agent decisions. | retain | D01, D04, D05, D07, D08, D09 | This remains the mission and is made concrete by captured inputs, typed coverage, bounds, and guarded mutation. |
| C002 | `agent://ChiefArchitect` | Require a prescribed map-to-find-to-interface-to-impact discovery tour. | replace | D01, D02, D10 | Value and final adjudication select optional entry points; known targets use direct reads and ordinary change uses two calls. |
| C003 | `agent://ChiefArchitect` | Expose separate exploration, scan, interface, import/export, and symbol handoff routes. | merge | D02, D05, D11 | Seven families remove duplicate public concepts while retaining needed evidence in bounded sections and references. |
| C004 | `agent://ChiefArchitect` | Require a standalone exact-symbol intermediary or public `symbol_at` operation. | remove | D02, D03, D11 | Direct `read` accepts references and locations and supplies optional enclosing identity without a whole-repository inventory hop. |
| C005 | `agent://ChiefArchitect` | Treat impact as resolved caller or dependent evidence, with confidence or alias expansion. | remove | D08, D11, D13 | Parser and lexical occurrences remain useful, but binding is unresolved and no semantic rename claim is allowed. |
| C006 | `agent://ChiefArchitect` | Expose public rule explanation and rule testing routes and regex-style discovery. | remove | D02, D10, D11 | Expert rule work uses ast-grep directly; MCP discovery is exact or natural intent, not regex. |
| C007 | `agent://ChiefArchitect` | Forward broad ast-grep project configuration and external grammar dependencies. | replace | D04, D07, D11, D13 | A closed contained `ruleDirs` subset is selected, with explicit rejection of dependency-bearing configuration. |
| C008 | `agent://ChiefArchitect` | Require a durable journal, recovery route, transaction directory, and restart protocol for change. | remove | D09, D12, D14 | The binding delta removes this mechanism. Caught-failure rollback, caller baseline, and interruption limits remain explicit safety properties. |
| C009 | `agent://ChiefArchitect` | Permit direct rewrite or rule-fix mutation outside one reviewed lifecycle. | remove | D09, D11, D13 | Apply is the only mutation route and always verifies the complete reviewed artifact and guards. |
| C010 | `agent://ChiefArchitect` | Use offset or shortened-fingerprint continuation and cap arrival-order prefixes. | replace | D04, D05, D07, D11, D13 | Captured manifests, canonical complete file units and stateless seek cursors, including unique path-qualified `FindRowId` checkpoints, prevent false ordering and false empty results. |
| C011 | `agent://ChiefArchitect` | Use separate side-channel metadata and adapter-owned semantic pagination. | remove | D03, D05, D10, D11 | One execute boundary owns immutable typed result and coverage values. |
| C012 | `agent://ChiefArchitect` | Keep broad legacy schemas, aliases, compatibility fields, and duplicate summaries. | remove | D03, D10, D11 | The major is a clean unified `xray.v1` cutover rather than a compatibility layer. |
| C013 | `agent://ChiefArchitect` | Use Git or modification-time namespace caches and inventory prerequisites. | replace | D04, D06, D11 | Content-derived optional artifacts and captured manifests preserve truth without migrating old caches. |
| C014 | `agent://ChiefArchitect` | Multiply interface member limits per container and expose map skeletons or large independent limits. | replace | D02, D05, D07, D11 | One global declaration page and exact expandable containers bound disclosure. |
| C015 | `agent://ChiefArchitect` | Promise ordinary rollback as crash recovery or globally atomic mutation. | replace | D09, D13, D14 | Staged writes and caught rollback remain, with caller-stability-scoped guarantees, observed-third-value preservation and explicit power-loss/interruption limits. |
| C016 | `agent://ChiefArchitect` | Use a broad exception fallback or empty result when a backend exceeds output or fails. | remove | D05, D07, D08, D13 | Typed errors, bounded child I/O, and partial coverage prevent failure from becoming exact zero. |
| C017 | `agent://ChiefArchitect` | Generate a broad CLI, README, or harness from a generic operation DSL. | defer | D10, D12, D14 | A small typed catalog derives contract-bearing fragments only; grammar and strategy prose remain handwritten. |
| C018 | `agent://ChiefArchitect` | Retain all old operation names as migration aliases. | remove | D02, D11, D13 | Removed names fail `unknown_operation`; future callers migrate explicitly. |
| C019 | `agent://ChiefArchitect` | Use a full output or raw compatibility schema as a separate semantic API. | remove | D03, D10, D11 | JSON semantic data is one closed schema; display modes are lossy transport renderings. |
| C020 | `agent://ChiefArchitect` | Treat a successful syntax check or digest as proof of semantic equivalence or approval. | replace | D01, D09, D13, D14 | Syntax and digest meanings are narrowly stated; semantic review and future qualification remain separate. |
| V001 | `agent://ValuePlanner` | Known locations and exact references should be directly actionable, with bounded multi-target reads. | retain | D01, D02, D03, D05, D13 | Direct read, strict references, and one-to-eight target batching reduce unnecessary hops without opaque handles. |
| V002 | `agent://ValuePlanner` | Truthful empty and coverage semantics require captured bytes and a stable executed population. | retain | D04, D05, D07, D08, D13 | Captured read sets, file completion, partial coverage, and typed failure reject false exact zero. |
| V003 | `agent://ValuePlanner` | A mutex or pre-scan digest alone is insufficient for snapshot truth. | retain | D04, D05, D14 | The design detects observable races but does not claim atomic filesystem history. |
| V004 | `agent://ValuePlanner` | Seven conceptual families remove duplicate map, interface, import/export, and scan routes. | retain | D02, D10, D11 | The final family inventory and migration matrix make deletion explicit. |
| V005 | `agent://ValuePlanner` | Find should remove public calibration knobs and expose one match-quality explanation. | retain | D02, D03, D07, D11 | Match policy and one `match_kind` replace scores and confidence while internal deterministic ranking remains. |
| V006 | `agent://ValuePlanner` | Literal search is useful from error or configuration strings as an exact entry point. | retain | D02, D04, D05, D07, D08 | Exact case-sensitive non-overlapping UTF-8 literals share selection and occurrence bounds without regex or mutation. |
| V007 | `agent://ValuePlanner` | Public rule explain and test operations are outside the minimum mission. | retain | D02, D10, D11 | ast-grep remains the expert tool; XRAY retains only execution validation diagnostics. |
| V008 | `agent://ValuePlanner` | Verify should be optional while one guarded engine remains mandatory at apply. | retain | D09, D12, D13 | Apply repeats every guard and no journal or recovery service is required. |
| V009 | `agent://ValuePlanner` | Avoid a nine-service refactor and evidence graph or alias-resolution expansion. | retain | D08, D10, D12 | Ownership seams are narrow and no class-per-operation or semantic graph is introduced. |
| V010 | `agent://ValuePlanner` | Shared envelope provenance is preferable to a dossier repeated on every item. | retain | D03, D04, D05, D09 | Shared identity is in the ordinary envelope; the explicit plan/refine response exception instead makes the complete plan's root, selection and repository provenance the sole identity-bearing copy, while standalone refs carry only necessary identity. |
| V011 | `agent://ValuePlanner` | Avoid a universal error-planning or retry framework. | retain | D03, D05, D07 | One typed code, at most one mechanical action, and closed bounded details replace retry graphs. |
| V012 | `agent://ValuePlanner` | Discovery should return a complete callable best-match contract in one response. | retain | D02, D03, D07, D10, D13 | At most two terse alternatives are allowed; an oversized contract fails honestly. |
| V013 | `agent://ValuePlanner` | Contract-bearing metadata can support parity without wholesale generated documentation. | replace | D10, D12, D14 | A small typed catalog derives selected sections; authored strategy and caveats remain source text. |
| V014 | `agent://ValuePlanner` | Measure completed task tokens, calls, latency, I/O, and actionability rather than compression alone. | retain | D07, D13 | Future methodology measures both encodings and complete workflows, with no present benchmark claim. |
| V015 | `agent://ValuePlanner` | Smaller per-operation defaults reduce context amplification while hard bounds remain explicit. | retain | D07, D13 | Selected 8/6/8/12/8 KiB defaults and larger complete review ceilings are centralized. |
| V016 | `agent://ValuePlanner` | Continuations should repeat no source and keep repeated evidence below a bounded ratio. | retain | D05, D13 | Merged intervals and seek positions prohibit repeated source; the future ratio excludes only mandatory small identity and coverage fields. |
| V017 | `agent://ValuePlanner` | Parse-clean structural edits are not safe semantic rename and impact is not resolved dependency evidence. | retain | D08, D09, D13 | Unresolved impact and explicit structural-edit limitation are normative. |
| V018 | `agent://ValuePlanner` | Unsupported syntax and captured-input cost require empirical gates rather than optimistic promises. | retain | D04, D07, D13, D14 | Behavior and thresholds are frozen while measurements remain future prerequisites. |
| V019 | `agent://ValuePlanner` | Cross-machine byte identity, crash recovery, and broad configuration should not be implied by compact evidence. | retain | D01, D04, D09, D14 | The selected boundaries state non-atomic capture, no durable recovery mechanism, and closed config. |
| DELTA01 | `local://chief-final-delta.md` | Consolidate the public surface into seven families: map, find, interface, read, impact, search, and change, with capabilities as support. | replace | D02, D10, D11 | FinalArchitect adopts the seven-family inventory and removes duplicate public routes. |
| DELTA02 | `local://chief-final-delta.md` | Use CLI change plan, refine, verify, and apply and flat MCP `change_*` operations. | replace | D02, D09, D10, D11 | Transport names are normalized while lifecycle semantics remain shared and verify stays optional. |
| DELTA03 | `local://chief-final-delta.md` | Make search explicitly support pattern, rule, and literal variants. | replace | D02, D03, D04, D08, D11 | Typed source variants are selected; invalid inference, regex discovery, and literal mutation are removed. |
| DELTA04 | `local://chief-final-delta.md` | Remove public `symbol_at`; direct location reads provide enclosing-reference information. | remove | D02, D03, D05, D11 | Direct read is the smaller actionable handoff and removes an inventory prerequisite. |
| DELTA05 | `local://chief-final-delta.md` | Remove public rule explain/test and regex discovery. | remove | D02, D10, D11 | Expert ast-grep tooling and typed MCP discovery replace redundant XRAY routes. |
| DELTA06 | `local://chief-final-delta.md` | Do not require a mutation journal or recovery operation. | remove | D01, D09, D12, D14 | Caught rollback and caller recovery baseline remain; interruption is explicitly limited. |
| DELTA07 | `local://chief-final-delta.md` | Use unified future `xray.v1` and `xray.change.v1` schemas. | replace | D03, D09, D10, D11 | One closed transport-neutral contract and one complete change artifact replace heterogeneous legacy envelopes. |
| DELTA08 | `local://chief-final-delta.md` | Derive only contract-bearing catalog sections from typed metadata while keeping adapters and guidance strategy handwritten. | replace | D10, D12, D14 | The catalog is deliberately small and is not a plugin framework, DSL, generated CLI, or wholesale document generator. |
| F-D01 | `agent://FinalArchitect` | Freeze the evidence-first mission and retained safety, containment, JSON, non-LSP, and on-demand boundaries. | retain | D01 | Final adjudication closes the mission and non-goals. |
| F-D02 | `agent://FinalArchitect` | Freeze seven families, canonical names, natural forms, direct references, and removed duplicate routes. | retain | D02, D11 | Final public surface is closed and migration is explicit. |
| F-D03 | `agent://FinalArchitect` | Freeze strict schemas, reference identities, canonical serialization, coverage, cursors, errors and illustrative shapes. | retain | D03, D05, D07 | One execute boundary carries closed aliases, canonical row and array identities, per-target enrichment and authoritative top-level `mutation` error state/status in a bounded wire representation. |
| F-D04 | `agent://FinalArchitect` | Freeze captured-read-set selection, configuration closure, and non-atomic snapshot meaning. | retain | D04, D14 | The provider owns selection, capture, and provenance and states its race limits. |
| F-D05 | `agent://FinalArchitect` | Freeze canonical order, seek checkpoints, file completion, continuation and incomplete coverage semantics. | retain | D05, D13 | Paging uses complete file units, unique path-qualified find rows and deterministic merged-read target associations rather than ambiguous IDs or arrival prefixes. |
| F-D06 | `agent://FinalArchitect` | Freeze optional content cache identity, bounds, invalidation, and cache-authority limits. | retain | D06, D07, D13 | Derived cache is expendable and cannot alter successful semantic results. |
| F-D07 | `agent://FinalArchitect` | Freeze exact future defaults, hard limits, accounting, and typed bound failures. | retain | D07, D13 | Numbers are future thresholds with explicit fitting and admission behavior. |
| F-D08 | `agent://FinalArchitect` | Freeze unresolved syntax or lexical impact evidence, direct reads, recursive occurrences, and no semantic identity claim. | retain | D08, D13 | The design answers occurrence location honestly without pretending to resolve bindings. |
| F-D09 | `agent://FinalArchitect` | Freeze unified optional refine and verify lifecycle, mandatory apply guards, complete artifacts, caught rollback and interruption limitation. | retain | D09, D12, D13, D14 | Journal and automatic recovery assumptions remain removed; every recognized `change_apply` error carries mandatory top-level `mutation` state/status, stable-namespace scope limits forward-race claims and caught rollback preserves observed third values. |
| F-D10 | `agent://FinalArchitect` | Freeze CLI/MCP parity, handwritten adapters, typed catalog scope, and guidance ownership. | retain | D10, D12, D13 | Semantic parity is separated from intentional transport mechanics. |
| F-D11 | `agent://FinalArchitect` | Freeze clean current-to-future migration and deletion of aliases, old schemas, unsafe routes, old caches, and old limits. | retain | D11, D12, D13 | No compatibility shim or stale machinery remains in the future cutover. |
| F-D12 | `agent://FinalArchitect` | Freeze future phase order, ownership, serialization, parallelization, and rollback boundaries. | retain | D12, D13 | Work is allocated without inventing a journal lane or overlapping indexer writers. |
| F-D13 | `agent://FinalArchitect` | Freeze future gates, counterexamples, benchmark method, and value thresholds as unexecuted acceptance evidence. | retain | D13 | Targets are gates, not current benchmark claims. |
| F-D14 | `agent://FinalArchitect` | Freeze residual risks, deferred work, evidence prerequisites, and authorization boundaries with no unresolved architecture option. | retain | D14 | Only implementation and separately authorized stronger scope remain outside this packet. |
| E001 | `README.md:1-11,120-220` | Current user-facing product and command behavior exists under 0.11.4 authority. | evidence-only | D01, D02, D11 | The future packet must not present future commands as current. |
| E002 | `PROJECT.md:3,22-38,39-45,107-118,182-208` | Current readiness, ownership, canonical command, compatibility, and delivery authority remain active. | evidence-only | D01, D10, D12, D14 | Link-only future boundary preserves these bodies. |
| E003 | `ARCHITECTURE.md:1-8,9-35,37-89` | Current component, interface, storage, mutation, and XRAY 0.11.4 contract authority remains active. | evidence-only | D01, D10, D11, D14 | Future design is linked, not inserted into current contract sections. |
| E004 | `docs/adoption-design-packet-v2.md:1-20,83-116,131-160` | Harness adoption Design Packet v2 is current and must not be superseded by product design. | evidence-only | D01, D12, D14 | Authority boundary names it explicitly. |
| E005 | `pyproject.toml:project metadata` | Current inspected package version is 0.11.4. | evidence-only | D01, D11, D13 | It is historical current evidence, not a future release promise. |
| E006 | `src/xray/core/indexer.py:293-303` | Separate `last_*` side channels can decouple result truth from one operation. | evidence-only | D03, D10 | The future execute boundary removes adapter-owned side channels. |
| E007 | `src/xray/presentation.py:144-190` | Completeness reconstruction from warnings and projections can misstate bounded failure. | evidence-only | D03, D05, D08 | Closed result and coverage unions make state explicit. |
| E008 | `src/xray/core/indexer.py:3003-3070,3158-3220` | Current snapshot and inventory work are separate. | evidence-only | D04, D05 | Captured manifests combine consumed input identity without atomic-history claims. |
| E009 | `src/xray/presentation.py:193-252`; `src/xray/core/ast_grep.py:116-214` | Current continuation and arrival-order caps do not establish canonical seek position. | evidence-only | D05, D07 | Future checkpoints and file completion make continuation deterministic. |
| E010 | `src/xray/core/indexer.py:2668-2704,2818-2882` | Current handoff identity and inventory validation use different semantics. | evidence-only | D02, D03, D05 | One SourceRef resolver and direct read replace separate assumptions. |
| E011 | `src/xray/core/indexer.py:3371-3680`; `src/xray/core/ast_grep.py:80-235` | Current fallback, skipping, late limits, and unbounded stream handling can turn failure into empty evidence. | evidence-only | D05, D07, D08, D13 | Future bounded executor returns typed failure or explicit partial coverage. |
| E012 | `src/xray/core/indexer.py:1179-1537,1630-1793`; `README.md` mutation limitations | Guarded ordinary writes exist, while legacy mutation and interruption limits remain. | evidence-only | D09, D13, D14 | Future design consolidates guards and states caught rollback and crash limits. |
| E013 | `src/xray/mcp_server.py:126-425`; `src/xray/cli.py:175-330` | Current metadata overlap and independent member limits amplify context. | evidence-only | D02, D07, D10 | Future typed catalog and global budgets address the evidence problem. |
| E014 | `src/xray/core/indexer.py:589-628`; `tests/test_structural_commands.py:91-96` | Current rule forwarding and fixture provide source evidence for a future narrower configuration contract. | evidence-only | D04, D11, D13 | Future qualification must prove the selected grammar rather than infer it from current forwarding. |
| E015 | `TEMPLATE_MANIFEST.md`; `.codex/validate_agents.py`; `.codex/validate_project_readiness.py` | Existing manifest and validators do not automatically cover this new packet. | evidence-only | D10, D12, D14 | Standalone documentation checks are specified without changing harness validators. |
| E016 | `docs/adoption-design-packet-v1.sha256`; `docs/adoption-design-packet-v2.sha256` | Existing companion format establishes lowercase SHA-256, two spaces, relative path, and LF. | evidence-only | D03, D14 | The new companion follows the convention without changing old digests. |
| E017 | `AGENTS.md`; `PROJECT.md:46-69` | Current root ownership and disjoint-path rules constrain future implementation and this freeze. | evidence-only | D10, D12, D14 | No current authority or unrelated path is silently changed. |
| E018 | `ARCHITECTURE.md:91-180` | Historical 0.10.0 material preserves chronology but does not govern current behavior. | evidence-only | D01, D11, D14 | Future migration distinguishes historical evidence from current authority. |

**Removed and relocated propositions.** The following ledger makes every material deletion, merge, deferral, and override explicit.

| Source proposition | Action and authorizing decision | Retained safety or useful property |
|---|---|---|
| Mandatory discovery tour | Replaced by optional entry points under D01, D02, and F-D02. | Direct location, name, expression, and unknown-area workflows remain actionable. |
| Standalone `symbol_at` and whole-repository exact-read inventory | Removed under DELTA04, D02, D03, and D11. | Strict per-file references, direct read, and enclosing result remain. |
| Public rule explain/test and regex discovery | Removed under DELTA05, D02, D10, and D11. | ast-grep remains expert rule authority; MCP discovery remains bounded and call-ready. |
| Mandatory journal, recovery operation, transaction directory, restart recovery and crash protocol | Removed or deferred under DELTA06, D09, D12 and D14. | Complete plan, caller recovery baseline, stable affected files/ancestor namespace, exclusive editing, staged writes, caught-failure rollback and authoritative top-level `mutation` state/status remain. |
| Alias-following, confidence, resolved impact, and semantic rename implication | Removed under C005, V017, D08, and D13. | Exact occurrence spans, evidence method, recursive uses, and unresolved state remain. |
| Arbitrary project configuration and custom grammar loading | Replaced under C007, D04, D11, and D13. | Contained standalone rules, closed `ruleDirs`, inline local semantics, and explicit dependency failure remain. |
| Offset cursors, shortened fingerprints, and prefix sorting | Replaced under C010, D05, D07, and D13. | Canonical complete-file units, captured identity, seek checkpoints, and explicit partial coverage remain. |
| Direct rewrite and rule-fix mutation routes | Removed under C009, D09, D11, and D13. | One guarded apply route with complete review evidence remains. |
| Separate verify as a mandatory hop | Replaced under DELTA02, V008, D09, and D13. | Optional verify is useful; apply independently repeats every guard. |
| Large independent interface member pages and map symbol skeletons | Replaced under C014, V004, D02, D05, and D07. | Flat global pages and exact expandable containers preserve navigation and actionability. |
| Git/modification-time old caches and last-side-channel metadata | Replaced or removed under C011, C013, D03, D06, and D11. | Content-derived optional artifacts and one immutable result preserve reproducibility. |
| Larger initial default budget tier and token claims | Replaced by selected future values under V014, V015, D07, and D13. | Hard bounds and complete evidence remain; no current measurement is claimed. |
| Generic plugin, operation DSL, generated CLI, and wholesale documentation generation | Deferred under C017, DELTA08, D10, D12, and D14. | Small catalog derives contract-bearing sections while handwritten strategy remains owned. |

**Vocabulary changes.** Identifiers retain exact literal spelling where they name current or future APIs. The following are meaning changes, not style synonyms.

| Current identifier or meaning | Future identifier or meaning | Disposition |
|---|---|---|
| `explore`, `explore_repo`, `map` alias | `map` navigation-only family | Alias and skeleton semantics removed; current command remains current until future cutover. |
| `find_symbol`, scored `.symbols` | `find` with `.data.items[].ref` and `match_kind` | Strict reference replaces display dictionary and public score. |
| `interface`, `read_interface`, `read_interface_structured` | One flat `interface` operation | Global page and exact nested identity replace independent member amplification. |
| `imports`, `file_imports`, `exports`, `file_exports` | Optional `interface` sections | Observed syntax remains; resolution claim does not. |
| `read_symbol`, `symbol_at` | `read` with `SourceRef`, `OccurrenceRef`, or location | `symbol_at` is deleted, not aliased. |
| `impact`, `what_breaks` | `impact` with unresolved name occurrences | Evidence is not resolved dependency graph or semantic rename. |
| `search_pattern`, `scan`, `scan_rules` | `search` source variants `pattern`, `rule`, `literal` | Duplicate operations and mutation flag are removed. |
| `rules explain`, `rules test` | Direct ast-grep expert tooling | No XRAY public wrapper remains. |
| `replace`, `rewrite`, `apply_rule_fixes` | `change plan|refine|verify|apply` | One guarded lifecycle; direct mutation is deleted. |
| `xray.cli.v1/v2/v3` and heterogeneous envelopes | `xray.v1` | Future unified schema, not a package release number. |
| `xray.replace.v1/v2` | `xray.change.v1` | Complete plan artifact and digest; old reconstruction is rejected. |
| offset cursor and shortened fingerprint | full-bound seek cursor | Cursor binds operation, root, query, selection, snapshot, and toolchain. |
| `doctor`, `xray_capabilities` | `capabilities` | One support operation; old aliases are removed. |
| `returned`, `total_exact`, `truncated`, lower-bound total | `items`, optional exact `total`, and `coverage` | Truth state is typed and not inferred from a warning. |

**Size and comparison evidence.** The packet does not embed its own final digest, because that would make the proof circular. The authorized writer or root records final global and per-file `len(text.split())` word counts and UTF-8 byte counts externally from the same unchanged candidate. The same handoff records printed SHA-256 values and command results. Existing role files and role instructions are unchanged by this packet; their per-role change is zero. The new packet is added text, not compression of the current repository. Byte counts are not token measurements. No source hash is fabricated for a session artifact, and a hash of a tool-rendered excerpt is never substituted for exact source bytes.

The pre-write checkpoint must capture exact SHA-256 values for `PROJECT.md`, `ARCHITECTURE.md`, both existing adoption packets, and both existing adoption companions. After authorized link insertion, removing exactly the inserted paragraph must reproduce each authority file's pre-write bytes. Existing adoption packet and companion bytes must remain equal to their checkpoints. This packet's companion is generated only after the packet is final.

**Validation scenarios and disposition conflicts.**

| Scenario or conflict | Expected evidence and final disposition |
|---|---|
| Current README, PROJECT, ARCHITECTURE, or adoption authority is read as future behavior | The authority boundary and E001–E004 preserve current 0.11.4 and harness authority; future examples are explicitly labeled and no current body is rewritten here. |
| A future operation is shown as a current 0.11.4 command | Stop semantic review; D02 natural forms are future illustrations only, and D11 requires a clean future cutover. |
| A writer claims the base proves a clean working tree | Stop; the named base and observed ref are recorded separately from working-tree cleanliness. |
| A source URI disappears | Continue only if all adopted semantics, rationale, migrations, and evidence locators remain embedded. Session URIs are not dependencies. |
| Initial Chief requires journal or recovery while Value challenges it | DELTA06 and F-D09 supersede that requirement. No journal, recovery operation, or restart machinery appears in normative future contracts; caller baseline and caught rollback remain. |
| Initial Chief requires public rule tools or standalone symbol-at while Value proposes deletion | DELTA04 and DELTA05 and F-D02 close the choice: direct read and expert ast-grep replace those public routes. |
| Initial and Value budget proposals differ | V015 and F-D07 select the centralized smaller default tier while retaining complete hard review bounds. All values are future thresholds and require G8 measurement. |
| Optional verify could be mistaken for no apply checks | D09 makes apply-time guards mandatory and independent of verify; G7 proves this. |
| Captured read set could be marketed as atomic snapshot | D04 and D14 require `captured_read_set`, race errors, stale continuation, and explicit non-atomic limitations. |
| A digest or language check could be marketed as semantic approval | D01, D09, D13, and D14 separate byte identity, syntax evidence, semantic review, and authorization. |
| Existing adoption validators omit the new packet | E015 and the next section specify standalone documentation checks without changing validators. |

**Result-to-source map.** This reverse map is the exact decision-to-evidence closure. Every future decision has source IDs and at least one future gate. Documentation-only authority and provenance decisions use documentation or semantic-review gates rather than runtime qualification alone.

| Decision ID | Source IDs | Future gate IDs |
|---|---|---|
| D01 | C001, C002, C020, V002, V019, F-D01, E001, E002, E003, E004, E018 | G1, G8, DOC-1, SEM-1 |
| D02 | C002, C003, C004, C006, C014, C018, V001, V004, V005, V006, V007, V012, DELTA01, DELTA03, DELTA04, DELTA05, F-D02, E001, E010, E013 | G1, G2, G5, G6, G8, DOC-1, SEM-1 |
| D03 | C004, C011, C012, C019, V001, V005, V010, V011, DELTA03, DELTA04, DELTA07, F-D03, E006, E007, E009, E010, E016 | G1, G2, G3, G4, G5, G7, DOC-1, SEM-1 |
| D04 | C007, C010, C013, V002, V003, V006, V018, V019, DELTA03, F-D04, E008, E014 | G2, G3, G4, G6, G7, DOC-1, SEM-1 |
| D05 | C001, C003, C010, C011, C014, C016, V001, V002, V003, V006, V010, V016, DELTA03, DELTA04, F-D05, E006, E007, E008, E009, E010, E011 | G2, G3, G4, G5, G6, G7, DOC-1, SEM-1 |
| D06 | C013, V002, V010, V018, F-D06, E008, E015 | G4, G5, G8, DOC-1, SEM-1 |
| D07 | C001, C007, C010, C014, C016, C019, V005, V006, V011, V014, V015, V016, V018, DELTA03, F-D07, E009, E011, E013 | G1, G3, G4, G5, G7, G8, DOC-1, SEM-1 |
| D08 | C005, C016, V002, V006, V009, V017, V018, DELTA03, F-D08, E007, E011 | G2, G3, G4, G6, G7, DOC-1, SEM-1 |
| D09 | C008, C009, C015, C020, V008, V017, V019, DELTA02, DELTA06, DELTA07, F-D09, E012 | G1, G2, G4, G7, G8, DOC-1, SEM-1 |
| D10 | C003, C006, C011, C012, C017, C018, C019, V004, V007, V009, V010, V011, V012, V013, DELTA01, DELTA02, DELTA05, DELTA08, F-D10, E006, E013, E015, E017 | G1, G4, G8, DOC-1, SEM-1 |
| D11 | C003, C004, C005, C006, C007, C009, C010, C012, C013, C014, C018, C019, V004, V005, V006, V007, V017, DELTA01, DELTA02, DELTA03, DELTA04, DELTA05, DELTA07, F-D11, E001, E003, E005, E014, E018 | G1, G5, G6, G7, G8, DOC-1, SEM-1 |
| D12 | C008, C017, V008, V009, V013, V018, DELTA02, DELTA06, DELTA08, F-D12, E002, E017 | G7, G8, DOC-1, SEM-1 |
| D13 | C005, C007, C009, C010, C012, C015, C016, C020, V002, V005, V008, V014, V015, V016, V017, V018, DELTA03, DELTA06, F-D13, E005, E011, E012, E013, E014 | G1, G2, G3, G4, G5, G6, G7, G8, DOC-1, SEM-1 |
| D14 | C001, C005, C007, C008, C015, C017, C020, V003, V008, V013, V018, V019, DELTA06, DELTA08, F-D14, E002, E003, E004, E015, E017, E018 | G8, DOC-1, SEM-1 |

The source and reverse edge sets must compare equal after expanding decision references. A table check can prove ID shape and graph closure; it cannot prove that a writer discovered every material proposition. FinalArchitect and root semantic review remain necessary.

## Documentation verification

This section specifies future documentation-only evidence. It does not report executed checks. Deterministic integrity checks, human semantic review, and future runtime qualification are separate gates.

The companion has exactly this format, with no prose or second entry:

```text
<64 lowercase hexadecimal SHA-256 characters>  docs/next-major-design-packet-v1.md
```

The final line has one LF. The digest hashes exact packet bytes, including whitespace and final newline. There is no normalization, Markdown rendering, canonical-JSON conversion, or partial-body hashing. Any packet-byte change invalidates the companion and prior handoff evidence. Existing adoption companions remain unchanged. The new digest proves byte identity only.

After authorized writing, future integrity commands include:

```text
sha256sum --check --strict docs/next-major-design-packet-v1.sha256
sha256sum --check --strict docs/adoption-design-packet-v1.sha256 docs/adoption-design-packet-v2.sha256
```

Before authorized edits, the writer captures exact SHA-256 values with an offline, no-sync `uv` Python script for `PROJECT.md`, `ARCHITECTURE.md`, `docs/adoption-design-packet-v1.md`, its companion, `docs/adoption-design-packet-v2.md`, and its companion, in sorted path order. The output is preserved outside the repository. This packet does not claim that checkpoint command ran.

The exact future structure, byte, link, paragraph, and status check is:

```text
uv run --no-sync --offline python - <<'PY'
from pathlib import Path
import hashlib
import re

root = Path.cwd().resolve()
p = root / 'docs/next-major-design-packet-v1.md'
d = p.with_suffix('.sha256')
paragraph = (
    'The [next-major design packet](docs/next-major-design-packet-v1.md) freezes\n'
    'future design only. XRAY 0.11.4 remains the current runtime contract;\n'
    'implementation requires separate authorization. Harness authority remains\n'
    '[adoption Design Packet v2](docs/adoption-design-packet-v2.md).\n'
)
paths = [p, d, root / 'PROJECT.md', root / 'ARCHITECTURE.md']
for path in paths:
    b = path.read_bytes()
    t = b.decode('utf-8')
    assert b and b.endswith(b'\n'), f'{path}: final LF'
    assert b'\r' not in b, f'{path}: CR'
    assert all(x.rstrip(b' \t') == x for x in b.splitlines()), f'{path}: trailing whitespace'
    print(path.relative_to(root), 'words=', len(t.split()), 'bytes=', len(b), 'sha256=', hashlib.sha256(b).hexdigest())
expected = hashlib.sha256(p.read_bytes()).hexdigest() + '  docs/next-major-design-packet-v1.md\n'
assert d.read_bytes() == expected.encode('ascii'), 'digest format or bytes'
t = p.read_text(encoding='utf-8')
assert t.startswith(
    '# XRAY Next-Major Design Packet\n\n'
    'Version: 1\n'
    'Decision Bead: `xray-txd`\n'
    'Status: FROZEN DESIGN — NOT IMPLEMENTED\n'
    'Decision date: 2026-09-10\n'
    'Base commit: `01d195486fd7f38d54f718735f44ac6301b88689`\n'
    'Current runtime contract: XRAY 0.11.4\n'
    'Implementation: Future work requiring separate authorization\n'
), 'header'
assert re.findall(r'^## (.+)$', t, re.M) == [
    'Outcome and scope', 'Authority and provenance', 'Frozen next-major decisions',
    'Transformation evidence', 'Documentation verification', 'Stop conditions and completion'
], 'section order'
assert re.findall(r'^### (D\\d{2})\\b', t, re.M) == [f'D{i:02}' for i in range(1, 15)], 'decision homes'
for name, following in [('PROJECT.md', '## Integration branch'), ('ARCHITECTURE.md', '## System boundaries')]:
    a = (root / name).read_text(encoding='utf-8')
    assert a.count(paragraph) == 1, f'{name}: paragraph count'
    assert paragraph + '\n' + following in a, f'{name}: paragraph location'
    restored = a.replace(paragraph + '\n', '', 1).encode('utf-8')
    print(name, 'PREWRITE_RESTORED_SHA256=', hashlib.sha256(restored).hexdigest())
assert re.findall(r'^Status: (.+)$', (root / 'PROJECT.md').read_text(), re.M) == ['READY']
for owner, text in [(p, t), (root / 'PROJECT.md', paragraph), (root / 'ARCHITECTURE.md', paragraph)]:
    outside_fences = re.sub(r'^```[^\\n]*\\n.*?^```[^\\n]*$', '', text, flags=re.M | re.S)
    targets = re.findall(r'\\[[^]\\n]+\\]\\(([^)\\s]+)\\)', outside_fences)
    for target in targets:
        assert not any(c in target for c in ('#', '?', ':')), f'non-file link: {target}'
        resolved = (owner.parent / target).resolve()
        resolved.relative_to(root)
        assert resolved.is_file(), f'missing link: {owner}: {target}'
print('DOCUMENTATION_STRUCTURE_DIGEST_AND_LINK_CHECKS_OK')
PY
```

The script's `paragraph` is the exact future link-only paragraph required in both authority files. Removing exactly that paragraph plus its separating blank line must restore each pre-write byte checkpoint. `PROJECT.md` must still report `Status: READY`. The script checks the new packet's local file links and does not claim that external provenance locators are live resources.

The source-table check rejects duplicate source IDs, unsupported dispositions, absent locators, absent decision destinations, and replace, remove, or defer rows without reasons. The reverse table requires exactly D01 through D14, existing source IDs, and existing gate IDs. DELTA01 through DELTA08 must each occur exactly once in the source inventory. The expanded source and reverse edge sets must be equal. These deterministic checks do not prove proposition-inventory completeness or semantic preservation.

The future implementation inventory, migration matrix, schema examples, phase contracts, and gate references are checked against FinalArchitect's final D01–D14 handoff. Exact literal equality is mechanical; semantic completeness remains FinalArchitect and root review. The future writer may run `git diff --check -- docs/next-major-design-packet-v1.md docs/next-major-design-packet-v1.sha256 PROJECT.md ARCHITECTURE.md` after authorized writing, while the standalone byte check covers new untracked files that Git diff may omit.

No online link checking or remote access is required. External provenance URLs are citations, not locally verified live resources. The specified script covers new local links and assigned authority insertions, not every pre-existing Markdown link. No permanent verification script or test is added for this one-off documentation freeze. The existing adoption validator does not automatically validate this packet or its companion, and this packet does not modify that validator or its unrelated pre-existing budget mismatch.

The future handoff records exact final global and per-file words, UTF-8 bytes, SHA-256 values, command exit status, and semantic-review disposition outside this packet. It records role-file change as zero and does not convert bytes into token savings. It does not claim implementation, benchmark success, runtime qualification, approval, Bead closure, commit, or delivery authority.

## Stop conditions and completion

The documentation writer stops before digest generation when any of the following occurs:

- FinalArchitect's technical choice is missing, contradictory, or replaced by an unresolved option menu.
- A source proposition has no locator, disposition, reason when needed, or D01–D14 destination.
- A D01–D14 decision has no reverse source edge or future gate.
- A mandatory journal, recovery operation, automatic restart recovery, or contradictory crash guarantee appears anywhere in the normative packet.
- Optional verify is described as mandatory, or apply-time guards are weakened or made dependent on an earlier verify.
- A current 0.11.4 command, schema, compatibility promise, or harness authority is presented as future behavior or silently changed.
- A migration or deletion lacks its affected caller, command, tool, flag, schema, cursor, reference, plan, skill, package, resource, test, or obsolete machinery disposition.
- A captured-read-set digest is described as an atomic filesystem instant, a syntax result as semantic proof, an impact occurrence as resolved identity, or ordinary rollback as crash recovery.
- A numeric value lacks classification as a frozen future threshold, schema bound, phase identifier, or historical or inspected evidence.
- A local link, exact paragraph boundary, companion format, or final newline cannot be proved by the specified documentation checks.
- The packet changes after companion generation, the companion is stale, or a source hash is fabricated.
- An authority file's exact removal comparison does not restore its captured pre-write bytes, or unrelated user work is not preserved.

The A0 documentation artifact is complete only when all of these conditions hold:

1. The packet has the exact required header, current-versus-future boundary, six H2 sections in the specified order, and one D01–D14 home in order.
2. Every final technical choice, number, schema, operation, migration disposition, deletion, phase ownership, gate, counterexample, risk, and deferred boundary is encoded self-containedly.
3. Both source-to-result and result-to-source trace directions close, including all eight DELTA rows, removed or deferred propositions, vocabulary changes, conflicts, and limitations.
4. The packet and companion have exact UTF-8 bytes, final LF, and the required lowercase two-space digest format. The final digest is recorded externally rather than self-embedded.
5. The link-only authority paragraphs are each present exactly once at their assigned locations, and removal restores their pre-write bytes while `PROJECT.md` remains `Status: READY`.
6. Deterministic documentation checks have evidence, and FinalArchitect or root semantic review closes the completeness and meaning questions that a digest cannot prove.
7. The root accepts exactly the four-path coordinated documentation artifact without resetting unrelated work.

Documentation completion does not complete product implementation, demonstrate runtime compatibility, qualify tokenizer or performance targets, approve protected delivery, mutate or close the Bead, create a commit, or authorize a release. Those actions remain separately authorized future work.
