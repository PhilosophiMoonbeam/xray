# XRAY Next-Major Design Packet — Qualification and Installation Delta

Version: 3
Decision Bead: `xray-5e7.31`
Parent Bead: `xray-5e7`
Status: FROZEN AUTHORIZED DELTA — IMPLEMENTATION AND QUALIFICATION PENDING
Decision date: 2026-09-11
Implementation: Authorized under `xray-5e7`; not implemented or qualified by this packet

## Outcome and scope

This packet is a compact, repository-owned v3 delta. It authorizes only V3-A
qualification accounting, V3-B descriptor-relative skill installation, and V3-C
explicit-local-checkout bootstrap selection. It is not implementation,
qualification, acceptance, or protected-delivery approval.

This version supersedes v1/v2 only for V3-A, V3-B, and V3-C and their named
dependent gates. V3-A replaces D13 atomic operation token accounting/ceilings,
the completed-context exemption, and matched-baseline population rules. V3-B
replaces the installer-mechanics restriction in D10–D12/D14 and v2 F3 only for
descriptor-relative installation. V3-C replaces retained bootstrap mechanics
only for explicit local checkout selection. All other decisions and thresholds
are inherited unchanged. Version 1, version 2, and their companions remain
immutable. Adoption Design Packet v2 remains harness authority.

`PROJECT.md` and `ARCHITECTURE.md` describe the current product and components;
`Status: READY` records harness adoption, not pending XRAY product qualification.
Qualification remains pending until the complete revised contract passes on the
final unchanged candidate. No packet wording claims implemented success.

## Authority and provenance

| Authority | Role or frozen evidence |
|---|---|
| [Version-1 packet](next-major-design-packet-v1.md) | Immutable next-major design and inherited D01–D14 contract; packet SHA-256 `c860367da05d61069726b9d4fe7d79e030031dfcc16990a786d2062d28ed7331`. |
| [Version-1 companion](next-major-design-packet-v1.sha256) | Immutable companion bytes; file SHA-256 `36d7dcde77216ff820e35f003ea45cb233cff8dfe8989d32e8dc05518d125334`. |
| [Version-2 packet](next-major-design-packet-v2.md) | Active v2 F1–F3 authority except where this named delta controls; packet SHA-256 `726e371d0d244a25df164f9b2e1729c1b6f62d0cdf1317840d9e150e1f83a80d`. |
| [Version-2 companion](next-major-design-packet-v2.sha256) | Immutable companion bytes; file SHA-256 `51f7ff99b175e7d6b0265fa872ed40876933d6931e690bcda049a861a1698f8c`. |
| [Adoption Design Packet v2](adoption-design-packet-v2.md) | Current harness adoption authority; this product delta does not replace it. |
| [PROJECT.md](../PROJECT.md), [ARCHITECTURE.md](../ARCHITECTURE.md) | Current operating, component, compatibility, and delivery descriptions. |
| [Repository Language Standard](repository-language-standard.md) | Required vocabulary, strength, literal preservation, and transformation evidence. |
| `agent://AuthorizedDeltaArchitect` | Binding architectural source for this exact V3-A/V3-B/V3-C selection. |

The tracked decision is Bead `xray-5e7.31`, under parent Bead `xray-5e7`,
claimed in progress with user authorization. The binding method and security
work may use a successor evidence subtree under the preserved `xray-5e7`
qualification root; sealed v1/v2 evidence is not overwritten.

Applicable user and governing authority controls. For the three named changes,
this v3 delta controls over conflicting v2/v1 text and superseded
qualification-method interpretations. Elsewhere v2 F1–F3 controls over v1,
and unaffected v1 decisions remain inherited qualification obligations.
`PROJECT.md` and `ARCHITECTURE.md` own current operating/component descriptions;
those descriptions, package version, tests, and `Status: READY` do not waive
inherited qualification gates. Reports, session artifacts, and scorers are
evidence or implementations of the contract, not alternate authority.

This packet and its companion are local, uncommitted artifacts unless the user
separately authorizes committing them. Implementation, documentation
acceptance, and passing local qualification grant no commit, push, merge,
publication, release, deployment, GitHub mutation, or Beads remote
synchronization authority. Remote one-line XRAY installation is deferred; no
canonical remote distribution endpoint is selected by this delta.

## Frozen authorized deltas

### V3-A — D13 qualification accounting, population, and output context

For `e` in `{cl100k_base,o200k_base}`, let
`C(V)=json.dumps(V, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)`
with no framing LF, and `A_e(V)=len(encoding_e.encode(C(V), disallowed_special=()))`.
`V` is the complete CLI JSON semantic value or standard-MCP
`result.structuredContent`, including root/scope/provenance, complete data or
refs, coverage, total, and cursor. Exclude only CLI framing LF and outer MCP
result/JSON-RPC/text-mirror duplication from this atomic measure. The F2 mirror
remains required exactly; actual exposures remain cumulatively charged.

Q07 uses these inclusive p95 ceilings under both encodings: `map 3000`,
`find 3000`, `interface 3000`, `impact 2500`, `search 2500`, and `read 3500`.
The 3000 ceiling applies uniformly to map, find, and interface; it is p95, not
a maximum or runtime token limit. For `n>0`,
`P95(x)=sort(x)[ceil(0.95*n)-1]`. Report p50, p95, and maximum. Freeze one
logical first-call slot per operation inside each complete task trial; a
continuation is not a second first-call sample. Score CLI and MCP separately
under both encodings; do not pool transports.

The first-call slots are: find `C01–C08`; interface `C01,C02,C08,C15`; read
`C01,C03,C04,C05,C06,C07,C09,C14`; impact `C01,C02`; search `C14`; and map
`C13`. Per transport, the expected counts are find 800, interface 400, read
800, impact 200, search 100, map 100, total 2400. Run 100 repetitions of every
task per transport, 20 each disabled/cold/warm/cleared/corrupt. C09's spurious
find sample is removed; its read remains. C13 retains its qualification
first-page witness (depth 2, limit 100, max_bytes 16384), which does not change
D07's 8192-byte map default. C10–C12 retain explicit limit 40 and remain in
complete-task accounting. Continuations and extra calls remain cumulative.
Missing or failed required slots fail population completeness; a cheap error
cannot replace a success sample.

For a validated ordered ledger of actual client-exposed events, tokenize each
complete event once: `I_e` is request/input, `O_e` is response/output, and
`T_e=I_e+O_e`. Boundaries come from recorded exposure, not favorable splitting.
Include exposed CLI commands, stdout, stderr, MCP initialization and schemas,
tools/list, discovery, complete frames, structured content, canonical mirror,
IDs, notifications/progress, retries/errors, repeated source, and submitted
plans. Every event needs identity/order, direction, exposure flag, raw bytes,
digest, byte count, and task/request association. Semantic and actual-frame
tokens are parallel measurements, not additive fragments.

Candidate completion remains C01–C15 × 100 repetitions × 2 transports = 3000
complete trials, irrespective of baseline support. Before comparative
measurement, freeze native-baseline recipes and an eligibility matrix at
`(transport,task)` with objective/gold hash, native operation sequence, raw
witness, support classification, and precise reason. Let `M` be the frozen
transport/task pairs whose native recipe completes the same objective and gold
with retained safety meaning. The exact paired keys are
`K=M × {disabled,cold,warm,cleared,corrupt} × {1,...,20}`; required paired
count is `100*|M|`, not a hard-coded denominator. Each key needs exactly one
candidate and one baseline trial, complete gold, and a valid ledger.

For each `k∈K` and encoding, require
`median(1-T_candidate,e(k)/T_baseline,e(k)) >= 0.35`; use the ordinary arithmetic
median for an even population and report transport/state distributions. For
each eligible transport/task, require candidate p95 total tokens over its 100
paired keys `<=1.05*` the baseline p95. A baseline-native unsupported task is
characterization, not a zero-token comparator; C13 is excluded from `M` only
for its native exhaustive-cursor capability. Failure, timeout, missing evidence,
or malformed output for a declared-supported task is a failed expected pair,
not a later unsupported reclassification. An empty matched set is blocked.

Independently of `M`, for each transport and encoding require
`P95(O_candidate,e)` `<=16000` over the 1400 candidate completed trials for
C01–C15 except C13, all five states, and 20 repetitions. `O` is output-only
actual exposure, not total or semantic-only output. The complete C13 50,001-row
traversal is exempt from this cap only and is reported separately: all 100
scheduled trials per transport, every canonical row exactly once, advancing and
exhausted cursors, no source-body substitute, and retained D07 limits/deadline.
Its first map call remains in Q07; calls/pages, I/O/total tokens, semantic and
actual bytes, latency, source/namespace work, peak RSS, states, encodings, and
three G3 traversal witnesses remain mandatory. The exemption applies to the
entire exhaustive workflow, not a selected prefix.

Use native baseline operation names and decoding; delete any legacy unsupported
predicate based on missing candidate `ok`/`structuredContent`. C09 reads
`python/owners.py` lines 24 through exclusive line 28, context 0,
`include_enclosing=false`, comparing exact bytes. C14 consumes a returned
enclosing reference to obtain its short body; C08 validates the qualified
member interface; C15 compares complete import/export populations including an
empty section; C10–C12 follow continuations to complete their requested
population. The scorer uses all 3000 candidate successes, the frozen baseline
matrix, and output-only context; Q07 uses logical slots rather than a
first-success or filename heuristic. Q04, Q05, Q08, handoffs, plans, safety,
G1–G8, and every inherited limit remain unchanged.

### V3-B — Descriptor-relative CLI skill installation

Retain `install_cli_skill(*, project_root=None, home=None, force=False)`,
`SkillInstallResult` and `as_dict`, CLI grammar, normalized absolute target
`ROOT/.agents/skills/xray-cli`, fixed files `SKILL.md` and
`agents/openai.yaml`, and all F3 result/error/byte rules. No repository
operation, administrative wrapper, new flag, journal, or recovery service is
introduced.

The qualified path is Linux with Python 3.10+. Use descriptor-relative
`os.open/fstat/stat/scandir/mkdir/read/write/unlink/rmdir`; Python 3.10
`shutil.rmtree` has no `dir_fd`, and `/proc/self/fd` pathname reopening is
forbidden. Preflight required descriptor APIs/flags and Linux `renameat2` with
`RENAME_NOREPLACE`; use a narrow stdlib-ctypes wrapper with explicit signature,
errno propagation, and basename-only arguments. Unavailable primitives fail
closed as `OSError`; no syscall-number table, generic backend, dependency,
unsafe fallback, or lock subsystem is authorized.

1. Preserve home/project selection, expansion, mutual exclusion, existing-root
   and supplied-root symlink rejection. Validate UTF-8/NUL, target bounds, and
   open every resolved absolute-root component with
   `O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`, retaining `(st_dev,st_ino,type)`.
2. Walk `.agents` and `skills` relative to pinned descriptors. Existing entries
   are real no-follow directories matching identity; missing entries are mkdir,
   reopen, and verify, with EEXIST races re-admitted only after checking. Keep
   parent modes and revalidate ancestor bindings before phase transitions.
3. Inspect `xray-cli` by descriptor-relative no-follow scandir/stat/open. Reject
   every symlink even with force; special files are divergent and never streams.
   Compare the exact set and bounded expected regular-file bytes. A stable exact
   match is `changed=false,replaced=false`; divergence without force is
   `ValueError` and untouched. Capture the admitted target identity.
4. Create one exclusive random `.xray-skill-stage-*` workspace under pinned
   `skills`, then `stage` and, when needed, `previous`. The staged public root
   remains mode 0700. Build the exact bundle with
   `O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW`, complete writes, and verification;
   do not eagerly read arbitrary divergent large files.
5. For force, revalidate the chain and admitted target immediately before moving
   it to `previous` with no-replace rename. If a different object moved, do not
   delete or publish it; restore only into an absent target or preserve it and
   fail.
6. Revalidate and publish `stage` with `RENAME_NOREPLACE`. Set state flags after
   successful syscalls and before fallible verification. Verify published inode,
   exact bytes, and held ancestors. Fresh install is changed/not-replaced;
   accepted forced replacement is changed/replaced.
7. On caught pre-commit failure, move only an identity/content-matching
   published target to a private abort name. Restore `previous` only into an
   absent destination with no-replace. Occupied or changed destinations retain
   recoverable material and return `OSError`; no concurrent object is overwritten.
8. After verified commit, clean only descriptor-owned backup/workspace objects,
   bottom-up, checking each child before descent/removal. Cleanup conflict or
   failure preserves material and returns `io_error` distinguishing installed-
   but-cleanup-failed from restored/installation-failed. Close all descriptors.

Static invalid input, unsafe pre-existing destination, divergence without force,
and target-bound failure remain `ValueError`/invalid-request. Runtime identity
drift, occupied publication/restoration, unavailable primitives, I/O, cleanup,
and restoration failure remain `OSError`/io_error; unexpected errors remain
internal_error. The repair blocks symlink redirection but does not promise
hostile same-UID-writer isolation, privileged mount isolation, relocation of
open directories, or atomic multi-step installation. SIGKILL/power loss may
leave the target absent, installed, or private stage/previous material; no
journal, detector, automatic cleanup, or recovery promise is added.

### V3-C — Explicit-local-checkout bootstrap

The grammar is `bash /trusted/xray/install.sh [--checkout DIRECTORY]`; `--help`
is the only other accepted option. Without `--checkout`, the physically
resolved local script supplies the source checkout. With it, the explicitly
supplied existing directory supplies the source. There is no positional or
ambient-cwd fallback.

Parse before side effects; require a real local script file and reject
duplicate, missing, unknown, sourced, piped, stdin, process-substitution,
`/dev/fd`, `/proc/*/fd`, and `/dev/stdin` sources. Resolve the local script and
selected checkout physically with quoted paths and `--` separators. Require
the selected directory and package/source markers as sanity checks only; they
do not authenticate a publisher, URL, Git remote, tag, version string, or cwd
name. Change to that checkout before uv/bootstrap.
Remove ambient project discovery, preliminary project-aware `uv run python`,
`CURRENT_GIT_ROOT`/`SKIP_CLONE`, Git rev-parse/pull/clone, checkout creation,
`~/.xray` source selection/deletion, and XRAY download/reclone behavior.

Preserve installed/reinstall behavior and `XRAY_INSTALL_FORCE=1`. An optional
uv prerequisite bootstrap runs only after explicit source selection; qualification
provisions uv and performs no network action. Install the absolute selected
source with `uv --no-config --directory "$INSTALL_DIR" tool install --force
"$INSTALL_DIR"`, clearing `UV_WORKING_DIR`, `UV_PROJECT`, and
`UV_CONFIG_FILE`; do not use `uv run`, editable installation, or `.`. Retain
`uv tool update-shell` and current-process `PATH`, resolve the actual tool
executable directory with `uv --no-config --directory "$INSTALL_DIR" tool dir
--bin`, and verify `xray`/`xray-mcp` there rather than an earlier PATH binary.
Use the installed `xray` for the exact `xray 1.0.0` and
`xray map "$INSTALL_DIR" --depth1` smoke. Print explicit-root quick-start
commands and preserve package metadata; remote distribution identity remains
deferred. The script is not a sandbox: users trust and keep the selected
checkout stable. Leave `uninstall.sh` unchanged, including its separate legacy
`~/.xray` deletion behavior.

## Transformation evidence

The following compact source→result rows are the complete v3 transformation;
each V3-A/B/C rule has one normative home above.

| Source edge | Result edge |
|---|---|
| D13 atomic accounting, old operation ceilings, completed-context interpretation, and matched-baseline population; historical token proof | V3-A complete semantic atomic formula, uniform dual-encoding Q07 ceilings, logical slots, frozen native eligibility matrix, exact `M/K`, and C13-only completed-output exemption. |
| v2 F3 and D10–D12/D14 installer-mechanics restriction | V3-B descriptor-pinned no-follow inspection, no-replace publication/restoration, preserved F3 API/errors/bytes, and explicit crash/manual-recovery boundary. |
| S08 / XRAY-SEC-008: “Skill installer containment checks are vulnerable to ancestor-symlink swaps” | V3-B pinned ancestor identities and descriptor-relative every-sink operations; no unsafe pathname fallback. |
| S09 / XRAY-SEC-009: “Bootstrap installer executes the ambient project without proving it is XRAY” | V3-C explicit local script or `--checkout` source authority, pre-side-effect validation, no ambient project/Git checkout selection, and deferred remote installation. |

| Result edge | Source edge closed or retained |
|---|---|
| V3-A atomic/full-exposure ledger, Q07/Q06/output formulas, native recipes, and failure rules | Replaces only the named D13 accounting, completed-output, and matched-population interpretations; retains D03/D05/D07/F2, all actual exposures, C13 traversal, and inherited gates. |
| V3-B descriptor-relative Linux installer mechanics | Replaces the conflicting pathname-only installer mechanics while retaining F3 public grammar, fixed bundle, no-op, force, errors, bounds, and byte rules. |
| V3-B S08 closure boundary | Closes the ancestor-symlink redirection authority conflict without promising hostile-writer or crash atomicity. |
| V3-C S09 closure boundary | Closes ambient-source confusion by explicit local selection; leaves remote identity, release, and one-line distribution policy deferred. |

V1/v2 packets and all adoption proof pairs remain historical/frozen artifacts;
this delta does not renumber or duplicate unrelated decisions. The revised
method does not turn old failed measurements into new passes: preserved raw
evidence may support diagnostics only, while final qualification binds native
recipes, the frozen matrix, complete candidate trials, and the unchanged
candidate. S08/S09 remain pending until their actual installer evidence closes.

## Documentation verification

The documentation owner changes only this packet, its companion, `PROJECT.md`,
and `ARCHITECTURE.md`. The current docs link this pending packet, retain
adoption v2 authority, describe current behavior without acceptance claims, and
remove the contradictory ambient/Git installer description. V3-A, V3-B, and
V3-C are each defined once; other sections trace or verify them only.

| File | Final `text.split()` words | Final UTF-8 bytes |
|---|---:|---:|
| `docs/next-major-design-packet-v3.md` | 2755 | 22015 |
| `PROJECT.md` | 1790 | 13932 |
| `ARCHITECTURE.md` | 2496 | 19760 |

The final proof must use exact UTF-8 bytes with LF line endings, no CR, no
trailing whitespace, and one final LF. It must verify local links, exactly six
H2 sections, the title/status/header, one normative home per V3-A/B/C, all
source↔result rows, the size ceilings (at most 3000 `text.split()` words and
24000 UTF-8 bytes), and no embedded self-digest. It must run strict companion
checks for v1, v2, v3, and both adoption packet pairs, then compare frozen v1/v2
packet and companion bytes with their pre-edit digests. The v3 companion is
written only after the final packet bytes as one lowercase SHA-256, two ASCII
spaces, `docs/next-major-design-packet-v3.md`, and one final LF.

This packet proof is not product proof. No formatter, linter, build, project-wide
test, home-directory installation, Git/network checkout, payload run, commit,
push, merge, release, publication, deployment, GitHub mutation, or Beads
remote synchronization is authorized by this documentation closure.

## Stop conditions and completion

Stop before companion generation if an exact V3-A/B/C selection changes without
a new authorized delta; a frozen v1/v2 packet or companion changes; an adoption
proof pair changes; a current authority link omits v3; a digest is fabricated,
precomputed, embedded, or treated as semantic/runtime proof; or a size,
encoding, LF, whitespace, link, trace, or count check fails.

Stop qualification if the complete revised contract has a failed required slot,
missing ledger, malformed event, incomplete C13 traversal, absent matched
denominator, native-baseline recipe error, unsupported platform primitive, or
failed unchanged Q04/Q05/Q08/G1–G8 obligation. Do not reclassify a supported
failure, erase overhead, shrink pages, omit safety fields, waive C13, or claim a
passing engine review is I5 acceptance. Preserve the failure and exact evidence.

This documentation freeze is complete only when the exact six-section packet,
companion, links, UTF-8/LF and whitespace invariants, source/reverse trace,
V3-A/B/C semantic review, per-file counts, and old frozen-pair identities pass,
with the four-path ownership boundary proven. Completion does not complete
implementation or qualification, demonstrate runtime compatibility, authorize
protected delivery, mutate or close the Bead, create a commit, or authorize a
release. A passing documentation gate grants no qualification, publication,
deployment, remote mutation, or protected-delivery authority.
