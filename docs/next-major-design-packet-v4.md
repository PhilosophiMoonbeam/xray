# XRAY Next-Major Design Packet — Applicability Qualification Delta

Version: 4
Decision Bead: `xray-5e7.32`
Parent Bead: `xray-5e7`
Status: FROZEN AUTHORIZED DELTA — QUALIFICATION PENDING
Decision date: 2026-09-11
Implementation: Authorized under `xray-5e7`; not implemented or qualified by this packet

## Outcome and scope

This repository-owned v4 delta makes qualification applicability-first. The user
selected broad characterization: the two V3-A comparative token predicates remain
measured and reported in full, but a false legacy cost predicate alone does not
reject an otherwise qualified product. This is documentation and qualification
method authority, not product implementation, acceptance, or protected-delivery
approval.

V4-A supersedes only V3-A's acceptance use of (1) matched median total-token
reduction of at least 35% and (2) every eligible transport/task p95 total-token
move of at most 5%. It also supersedes inherited D13/I5/G8 and stop/completion
wording only where that wording would reject the product solely because either
predicate is false. V3-A otherwise remains effective; V3-B and V3-C, v2 F1/F2
and remaining F3, every unaffected D01–D14 obligation, and adoption Design
Packet v2 remain authoritative. No product schema, default, safety rule, or
resource limit changes.

Qualification remains pending until the complete candidate, method, and all
inherited gates pass on one unchanged candidate. A valid complete characterization
may say either token predicate is false; missing, malformed, duplicate, or
reclassified evidence still blocks. Candidate work remains independent of native
baseline support. Current `PROJECT.md`, `ARCHITECTURE.md`, source, tests, and
`Status: READY` describe current behavior and do not claim I5 acceptance.

## Authority and provenance

| Authority | Role |
|---|---|
| [Next-major v1](next-major-design-packet-v1.md) and [companion](next-major-design-packet-v1.sha256) | Immutable D01–D14 design and exact-byte evidence. |
| [Next-major v2](next-major-design-packet-v2.md) and [companion](next-major-design-packet-v2.sha256) | Immutable F1–F3 delta and exact-byte evidence. |
| [Next-major v3](next-major-design-packet-v3.md) and [companion](next-major-design-packet-v3.sha256) | Immutable V3-A/B/C delta and exact-byte evidence. |
| [Adoption v1](adoption-design-packet-v1.md) and [companion](adoption-design-packet-v1.sha256) | Frozen historical harness authority. |
| [Adoption v2](adoption-design-packet-v2.md) | Current harness authority; this product delta does not replace it. |
| [PROJECT.md](../PROJECT.md) and [ARCHITECTURE.md](../ARCHITECTURE.md) | Current operating, component, compatibility, and delivery authority. |
| [Repository Language Standard](repository-language-standard.md) | Vocabulary, strength, literal preservation, and evidence rules. |
| `agent://ApplicabilityDeltaArchitect` | Binding source for the selected applicability interpretation. |

Applicable user and governing authority controls first. The user authorized this
local delta and selected broad characterization. The tracked decision is Bead
`xray-5e7.32`, under parent `xray-5e7`; root owns Bead creation, mutation,
closure, adjudication, and integration, while child writers do not mutate or
synchronize tracker state. This packet records that authority and does not itself
close the Bead.

The preserved qualification starting evidence is the native-support inventory
with SHA-256 `2704fd527ce9438de9b08d35ed79baeb925bc628a29dd293eca96cafbb0b1c94`
and `qualification/v3-diagnostic-corrected/diagnostic-report.json`. Those roots
are evidence, not alternate authority, and remain unchanged. Their historical
failed C14 characterization remains failed; it may be cited with scope and
identity, never relabeled or backdated.

V4 controls the named V4-A acceptance interpretation; v3 controls its other
terms, then v2 and inherited v1 terms. Reports, session artifacts, scorers, and
method code implement or evidence the contract, not override it. The packet and
companion are local, uncommitted artifacts. Implementation, documentation
acceptance, or passing local qualification grants no commit, push, merge,
release, publication, deployment, GitHub mutation, Beads remote synchronization,
or remote-install endpoint authority.

## Frozen applicability delta

### V4-A — Comparative token results are mandatory characterizations, not acceptance gates

Only the acceptance role changes. Both legacy predicates, their thresholds,
formulas, populations, native recipes, gold, client exposure, and encodings stay
mandatory and must be completely reported. A false numeric result is valid
characterization; an undefined denominator, missing ledger, failed required slot,
malformed output, duplicate key, unsupported reclassification, or incomplete
gold is not a characterization and blocks I5.

For `e` in `{cl100k_base,o200k_base}`, define
`C(V)=json.dumps(V, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)`
with no framing LF and `A_e(V)=len(encoding_e.encode(C(V), disallowed_special=()))`.
`V` is the entire CLI semantic JSON value or MCP `result.structuredContent`,
including established root/scope/provenance, complete data or references,
coverage, total, and cursor. This semantic atomic measure excludes only CLI
framing LF and outer MCP framing/mirror duplication; actual exposure still
charges those events.

For every actual exposure event `j`, let `x_j` be its complete UTF-8 text,
`d_j` its direction, and `exposed_j` its recorded exposure; let
`b_e(j)=len(encoding_e.encode(x_j, disallowed_special=()))`. For trial `k`,
`I_e(k)=Σ b_e(j)` over exposed request events,
`O_e(k)=Σ b_e(j)` over exposed response and stderr events, and
`T_e(k)=I_e(k)+O_e(k)`. Count each exposed event exactly once, with identity,
order, direction, exposure, raw bytes, SHA-256, byte count, and task/request
binding. Include initialization, schemas, tools/list, discovery, complete
frames, structured content, mirrors, IDs, progress, retries/errors, submitted
plans, repeated source, commands, stdout, and stderr actually exposed.
Semantic and actual ledgers are parallel, not additive; unexposed diagnostics
remain separate and exposed stderr cannot be hidden. Cache preparation outside a
measured client workflow is a recorded precondition and is charged if exposed.

For nonempty `n`, `P_p(x)=sort(x)[ceil(p*n)-1]`; report p50, p95, and maximum,
and use the ordinary arithmetic median, including the two-central-value average
for even populations. Freeze the exact native eligibility matrix:
`M={cli,mcp}×{C01,…,C09,C11,C12,C14,C15}`, so `|M|=26`, and
`K=M×{disabled,cold,warm,cleared,corrupt}×{1,…,20}`, so `|K|=2600`.
Each key has exactly one candidate and one native baseline trial, complete gold,
and valid ledgers. Candidate completion independently remains
C01–C15 × 2 transports × 5 states × 20 repetitions = 3000 complete trials,
including native-unsupported C10 and C13.

For each `k∈K` and encoding, require positive baseline totals and
`r_e(k)=1−T_candidate,e(k)/T_baseline,e(k)`. Report
`R_e=median_arithmetic({r_e(k):k∈K})` and
`meets_legacy_threshold=(R_e≥0.35)`. For each `m=(transport,task)∈M`, report
candidate/baseline p50, p95, and maximum and
`G_e(m)=P95(T_candidate,e over K_m)/P95(T_baseline,e over K_m)−1`, with
`meets_legacy_threshold=(G_e(m)≤0.05)`. Report all 26 cells for both encodings,
including failures, and transport/state distributions. Characterization is
complete only with the frozen matrix, exact 2600-key bijection, both encodings,
all gold, complete ledgers, every statistic, and no undefined denominator. The
Boolean predicate results do not decide product acceptance; completeness does.
A declared-supported baseline failure is a failed expected pair, never a new
unsupported classification.

Retain V3-A Q07 and context accounting exactly. Per transport, the 2400 logical
first-call slots are find 800, interface 400, read 800, impact 200, search 100,
and map 100; choose the designated first call, never first success or a
continuation. Under each encoding require
`P95(A_e(V_slot))≤cap`: map/find/interface 3000, impact/search 2500, and read
3500. Missing or failed slots fail completeness; cheap errors cannot replace
success, and transports are not pooled. C13's first page remains depth 2,
limit 100, `max_bytes=16384`, without changing D07's 8192-byte map default;
C10–C12 retain explicit limit 40. For C09 use `python/owners.py` lines 24
through exclusive line 28, context 0, `include_enclosing=false`, and exact
bytes; C14 consumes its returned enclosing reference; C08 validates qualified
members; C15 compares complete import/export populations including an empty
section; C10–C12 follow continuations to completion.

For each transport and encoding require
`P95(O_candidate,e over exactly 1400 C01–C15-except-C13 trials)≤16000`.
C13 alone is exempt from this output cap, never from its complete workflow:
all 100 trials per transport enumerate exactly 50,001 rows once, exhaust
advancing cursors, retain navigation-only meaning and D07 bounds/deadline, and
report calls/pages, I/O and total tokens, semantic/actual bytes, latency,
source/namespace work, peak RSS, states, encodings, and three G3 traversal
witnesses.

Q08 remains an acceptance gate. Completed-task latency is the monotonic
end-to-end interval from the workflow's first client action through its final
result, including required startup, initialization, discovery, continuations,
and handoffs. For every `m∈M`, require
`P95(L_candidate over K_m)≤1.10×P95(L_baseline over K_m)`. Retain the focused
CLI cold C03–C09 measurement (7 tasks × 2 versions × 3 repetitions = 42 rows
in each latency, separate RSS, and calibrated source-trace set), but use the
same complete recipes and gold as the full run. For focused task `q`,
`B_v(q,r)=sum of positive actual source-read syscall return bytes` attributed
to the measured process and descendants in frozen source roots; count rereads,
including hashing, and require
`median_arithmetic(B_candidate(q,*))≤0.50×median_arithmetic(B_baseline(q,*))`.
A missing or zero denominator is unresolved, not a pass. Keep PID+FD/inline-path
attribution, parser identity, RSS/resource limits, namespace work, admission,
deadlines, and failure behavior; V4 adds no RSS ceiling.

The successor method must begin from the preserved inventory and corrected
diagnostic, use genuinely state-aware full recipes for all five states, and use
native operation names and decoders for baselines. It must replace the incorrect
per-cell assertion `len(candidate_values)==20` with exact-key validation and
`len(STATES)×PAIRED_REPETITIONS=100` values per `(transport,task,encoding)` cell;
a length check alone is insufficient. It must replace abbreviated Q08 recipes
and candidate-shaped `ok`/`structuredContent` baseline decoding with complete
recipes, complete gold, native decoders, and full Q08 scoring. The I5 scorer must
score all 3000 candidate successes, the frozen baseline matrix, Q07, completed
output, Q08, correctness, safety, actionability, resources, and G1–G8.

I5 remains whole-product acceptance only after Q01–Q03 identity, method, corpus,
and population binding; Q04's initial two-tool schema overhead ≤1000 tokens and
default successful discovery value ≤1200 tokens within its default 4096-byte
bound; Q05's 110 frozen non-template intents (≥105 top-one, ≥109 top-three,
≥109 valid first calls after one discovery at `limit=3,max_bytes=16384`); Q07;
Q08; valid handoffs; ordinary two-call reviewed plan/apply; and all safety and
resource checks pass. G1 actual transport/schema/error parity, G2 captured truth
and containment, G3 canonical complete paging, G4 bounded admission/resource
failure, G5 cache truth and handoffs, G6 labeled language/name/config evidence,
G7 complete guarded plans/apply/rollback, and G8 guidance/catalog/deletion/
installation plus project gates remain required. The v4 exception is limited to
the two false token predicates.

## Transformation evidence

| Source or defect | V4 result |
|---|---|
| V3-A matched median and every-cell p95 token predicates | V4-A keeps exact measurements and changes only their acceptance role to complete characterization. |
| V3-A atomic/event accounting, Q07, C13 output exemption, `M/K`, and candidate population | Retained verbatim in meaning, including 3000 candidates, 2600 pairs, both encodings, and actual exposure. |
| Native-support inventory `2704fd…` and corrected diagnostic | Preserved starting evidence for a successor method; neither is rewritten or treated as qualification. |
| Incorrect 20-vs-100 cell assertion, disabled-only templates, abbreviated Q08 recipes, and candidate-shaped baseline decoder | State-aware full recipes, native decoders, exact-key 100-value cells, complete Q08, and full I5 scorer. |
| Inherited D13/I5/G8 stop wording | Scoped only where a complete valid token characterization is numerically false; all other gates still stop qualification. |

The reverse trace is closed: no product schema, default, safety, resource limit,
installer, guidance surface, frozen packet, companion, adoption authority, or
external evidence root changes. V4-A does not turn a failed historical result
into a pass, erase exposure, shrink pages, omit C13, or waive Q04/Q05/Q07/Q08,
handoffs, plans, correctness, actionability, resources, or G1–G8.

## Documentation verification

The packet has exactly these six H2 sections in order, one V4-A normative home,
local links for every repository authority, and no embedded self-digest. Before
the companion is generated, verify exact UTF-8 bytes, LF endings, no trailing
whitespace, one final LF, section/header/status/link validity, and the unchanged
bytes of next-major v1–v3 packet/companion files plus both adoption pairs. The
companion is exactly lowercase SHA-256, two ASCII spaces, the repository-relative
packet path, and one final LF.

Run only the scoped proof required for this documentation closure:

```text
uv run python .codex/validate_agents.py --self-test
uv run python .codex/validate_agents.py
sha256sum --check --strict docs/adoption-design-packet-v1.sha256 docs/adoption-design-packet-v2.sha256 docs/next-major-design-packet-v1.sha256 docs/next-major-design-packet-v2.sha256 docs/next-major-design-packet-v3.sha256 docs/next-major-design-packet-v4.sha256
```

The validator must enforce all six packet pairs (next-major v1–v4 and adoption
v1–v2), exact companion bytes, manifest registration, hygiene, and unchanged
budgets: PROJECT ≤1800/14000, ARCHITECTURE ≤2500/20000, this evidence
≤1800/13000, validator ≤1800/21000, Python automation ≤35000 bytes, and the
manifest's existing ceiling. These checks are documentation evidence, not
product or qualification proof.

## Stop conditions and completion

Stop before companion generation if V4-A's scope changes, the user/Bead
authority is unclear, any frozen packet or companion or external evidence root
drifts, a link or section is missing, a formula/threshold/population is altered,
the method inventory or corrected diagnostic is unavailable, or any encoding,
LF, whitespace, budget, or validator check fails. Stop qualification for any
missing/invalid ledger, duplicate or reclassified key, incomplete candidate or
C13 traversal, unsupported state-aware recipe, wrong decoder, failed Q04/Q05/Q07/
Q08/correctness/safety/actionability/resource/G gate, or failed unchanged
candidate. Do not stop solely for a complete false `R_e` or `G_e(m)` predicate.

Completion means this six-section packet, exact companion, local links, evidence
trace, registry, and scoped checks pass. It does not implement XRAY, qualify the
product by itself, mutate or close Bead `xray-5e7.32`, create a commit, or grant
protected delivery. Root alone may adjudicate, integrate, run final
qualification, and change readiness; commit, push, merge, release, publication,
deployment, remote mutation, and Beads synchronization remain separately
authorized.
