---
name: xray-cli
description: "Use XRAY for bounded discovery and reviewed structural change workflows."
---

# XRAY CLI

Use `xray` with an explicit `ROOT`. The operation catalog has exactly eleven
repository operations: `map`, `find`, `interface`, `read`, `search`, `impact`,
`change_plan`, `change_refine`, `change_verify`, `change_apply`, and
`capabilities`. The seven inspection operations (`map`, `find`, `interface`,
`read`, `search`, `impact`, `capabilities`) plus `change_plan`, `change_refine`,
and `change_verify` are read-only. `change_apply` is the only guarded
source-mutating operation. `skill install` is separate CLI-only administration.

## Choose an entry point

Progressive discovery is optional. Start with the operation that matches the
known information:

- `map` lists a bounded namespace without reading source bodies.
- `find` locates a declaration by name or qualified identity and returns a typed
  symbol reference.
- `interface` reads bounded signatures, imports, exports, or documentation for
  one file or exact symbol.
- `read` captures exact source locations or trusted typed references.
- `search` handles exact literal text, an explicit-language structural pattern,
  or one contained rule/config input.
- `impact` reports exact unresolved occurrences for one captured declaration
  reference.
- `capabilities` reports health, languages, and enabled-operation summaries.

A known declaration needs no map tour: use `find`, then `interface`, `read`, or
`impact`. A known file can go directly to `interface` or `read`, and a known
expression can go directly to `search`. Pass each complete typed reference
unchanged; do not reconstruct it or turn its relative path into an absolute
path.

Every repository command takes an explicit `ROOT`. Paths and references are
contained repository-relative POSIX paths. JSON is the semantic contract;
`--format text` is a lossy terminal view and `--pretty` changes only indentation.
Invalid input, stale identity/cursors, unsupported files/configuration,
containment violations, dependency failures, and response bounds are typed
errors, not empty success results.

## Inspect a repository

```bash
xray capabilities ROOT --detail detail
xray map ROOT --focus src/xray --depth 1 --limit 20 --max-bytes 16384
xray find ROOT XRayIndexer --match exact --language python --limit 1 --max-bytes 16384
xray interface ROOT src/xray/cli.py --sections symbols --member-depth 1
xray read ROOT src/xray/cli.py --line 1 --end-line 20 --context-lines 2
xray search ROOT --literal 'raise ValueError' --path src/xray --limit 20
```

`map` options include `--focus PATH`, `--depth N|all` (`0..64`),
`--context none|ancestors`, `--exclusions default|none`, `--cursor TOKEN`,
`--limit N` (`1..1000`), `--max-bytes N`, `--timeout-seconds N`,
`--cache auto|off`, `--format json|text`, and `--pretty`.

`find ROOT QUERY` uses `--match name|exact|fuzzy` (default `name`) and accepts
repeatable `--path PATH`, `--glob PATTERN`, `--language LANGUAGE`, `--kinds
KIND`, and `--visibility public|private|unknown`, plus the common paging and
execution options. The complete reference is at `.data.items[0].ref`; keep it
intact for `interface`, `read`, or `impact`. A reference binds root, relative
path, byte range, file digest, and analyzer identity.

`interface` accepts exactly one contained file or one JSON reference:

```bash
xray interface ROOT src/xray/cli.py --sections symbols --member-depth 1
xray interface ROOT --ref-json JSON --sections symbols --member-depth 1
xray interface ROOT --ref-file FILE --sections symbols --member-depth 1
```

Use `--sections symbols|imports|exports`, `--member-depth 0|1`,
`--documentation`, `--kinds KIND`, and `--visibility VALUE`, together with
bounded paging and execution controls. A symbol target is bounded to its owner
and does not add siblings. `--ref-file -` reads JSON from standard input.

`read` accepts one location, reference, or a JSON target array of one to eight:

```bash
xray read ROOT src/xray/cli.py --line 1 --end-line 20 --context-lines 2
xray read ROOT --ref-json '{"kind":"location","path":"src/xray/cli.py","line":1}'
xray read ROOT --ref-file reference.json
xray read ROOT --targets-file targets.json --max-lines 32
```

A location requires one-based `--line`; `--end-line` and `--column` are
optional. Use `--targets-file -` for standard input. Controls include
`--context-lines 0..10`, `--include-enclosing`/`--no-enclosing`, `--cursor
TOKEN`, `--max-bytes N`, `--max-lines 1..256`, `--source-bytes 1..32768`,
`--timeout-seconds N`, `--cache auto|off`, `--format json|text`, and `--pretty`.

## Search and contained rules

Search requires exactly one source form: `--literal`, `--pattern` plus `--lang`,
`--rule`, or `--config`:

```bash
xray search ROOT --literal 'raise ValueError' --path src/xray --limit 20
xray search ROOT --pattern 'raise $E' --lang python --path src/xray --detail detail
xray search ROOT --rule rules/no-foo.yml --detail detail
xray search ROOT --config sgconfig.yml
```

Literal search is exact, case-sensitive UTF-8 text with non-overlapping
occurrences. Pattern search is structural and requires one of `python`,
`javascript`, `typescript`, or `go`; an invalid pattern is an error and is not
reinterpreted as literal text. `--detail summary` is the default; `detail` adds
only verified named captures. Selection and paging controls are `--path PATH`,
`--glob PATTERN`, `--language LANGUAGE`, `--exclusions default|none`,
`--detail summary|detail`, `--cursor TOKEN`, `--limit N` (`1..1000`),
`--max-bytes N`, `--timeout-seconds N`, `--cache auto|off`, `--format json|text`,
and `--pretty`. `--lang` applies only to `--pattern`.

A standalone `--rule FILE` is a self-contained `.yml` or `.yaml` file and may
contain one or more rule documents. A `--config FILE` is one contained YAML
document whose complete top-level mapping is exactly a nonempty `ruleDirs`
string list. Each directory is relative to the config file, remains inside
`ROOT`, and is recursively enumerated for YAML rules in canonical path order.
Symlinks, unknown keys, multiple documents, empty rule sets, directory input,
implicit environment or ancestor configuration, custom grammars, and external
dependencies are rejected.

## Report unresolved impact

Impact requires exactly one complete reference from `find`:

```bash
symbol=$(xray find ROOT XRayIndexer --match exact --language python --limit 1 \
  | jq -c '.data.items[0].ref')
xray impact ROOT --ref-json "$symbol" --mode syntax --limit 100
xray impact ROOT --ref-json "$symbol" --mode lexical --limit 100
```

Syntax evidence is the default; lexical mode is explicit exact spelling with
identifier boundaries. Impact data is always unresolved `name_occurrences`
evidence. It does not establish callers, dependents, aliases, a dependency
graph, or resolved relationships.

## Plan, review, and apply a guarded change

The change lifecycle has one grammar for pattern and contained rule/config
sources:

```text
xray change plan|refine|verify|apply ROOT [options]
```

Only `plan`, `refine`, and `verify` are non-mutating. `apply` alone may write
repository source. The canonical workflow is exactly two product calls:

1. `change plan` builds a complete `xray.change.v1` JSON plan.
2. After reviewing that complete artifact, `change apply` receives the artifact
   and a separate expected digest.

`refine` and `verify` are optional calls between those two calls. Apply repeats
every guard and does not rely on a previous verify result.

### Pattern source

A pattern plan requires all of `--pattern PATTERN`, `--replacement TEXT`, and
`--lang LANGUAGE`. The language is `python`, `javascript`, `typescript`, or
`go`. Save the complete plan object, review every diff and edit ID, and pass an
independently retained digest to apply:

```bash
ROOT=/absolute/path/to/repository
xray change plan "$ROOT" \
  --pattern 'foo($A)' --replacement 'bar($A)' --lang python \
  --path src --max-candidates 100 --max-files 20 \
  > plan-response.json
jq -e '.ok == true and .op == "change_plan" and (.data.plan.plan_schema == "xray.change.v1")' \
  plan-response.json >/dev/null
jq '.data.plan' plan-response.json > plan.json

# Review plan.json, including every affected-file diff and edit ID.
EXPECTED_DIGEST=$(jq -r '.plan_digest' plan.json)
xray change apply "$ROOT" --plan-file plan.json \
  --expected-digest "$EXPECTED_DIGEST"
```

`--plan-file FILE` reads one complete plan object; `--plan-file -` reads that
JSON object from standard input. A success envelope from `change_plan` or
`change_refine` is accepted as a transport convenience, but extracting
`.data.plan` keeps the complete artifact explicit. `--expected-digest` is a
separate required argument. Apply never infers, changes, or overrides it.

Plan selection controls are repeatable `--path PATH`, `--glob PATTERN`, and
`--language LANGUAGE`, plus `--exclusions default|none`. Hard plan bounds are
`--max-candidates N` (`1..1000`), `--max-files N` (`1..100`), and `--max-bytes N`
(`4096..262144`). Plan-only acknowledgements are `--allow-dirty-affected` and
`--allow-new-parse-errors`; they become plan fields and cannot be supplied or
overridden by refine, verify, or apply.

### Rule/config source

A rule plan uses `--rule FILE` or `--config FILE`, never both. For example:

```yaml
# ROOT/rules/foo.yml
id: foo-call
language: JavaScript
rule:
  pattern: foo()
fix: bar()
```

```yaml
# ROOT/config.yml
ruleDirs:
  - rules
```

The same two-call review workflow applies:

```bash
xray change plan "$ROOT" --rule rules/foo.yml --path sample.js > plan-response.json
# Or: xray change plan "$ROOT" --config config.yml --path sample.js > plan-response.json
jq '.data.plan' plan-response.json > plan.json
EXPECTED_DIGEST=$(jq -r '.plan_digest' plan.json)
xray change apply "$ROOT" --plan-file plan.json --expected-digest "$EXPECTED_DIGEST"
```

There is no literal change source. Rule/config input remains contained and
self-contained; no ambient project configuration is loaded.

### Refine and verify

Refine selects reviewed `edit_id` digests and emits a new complete plan. It
never writes source. Review the new artifact and use its new digest:

```bash
jq -r '.edits[].edit_id' plan.json
xray change refine "$ROOT" --plan-file plan.json \
  --edit-id "$(jq -r '.edits[0].edit_id' plan.json)" \
  > refined-response.json
jq '.data.plan' refined-response.json > reviewed-plan.json
```

`--edit-id` may repeat, but IDs must be unique and sorted. Omitting all IDs
emits a complete inapplicable plan; an unknown ID is an error.

Verify is an optional non-mutating recheck:

```bash
REVIEWED_DIGEST=$(jq -r '.plan_digest' reviewed-plan.json)
xray change verify "$ROOT" --plan-file reviewed-plan.json \
  --expected-digest "$REVIEWED_DIGEST"
xray change apply "$ROOT" --plan-file reviewed-plan.json \
  --expected-digest "$REVIEWED_DIGEST"
```

`verify` returns `ready: true` and the digest without writing source. Verify and
apply accept no acknowledgement flags. A source, selection, configuration,
policy, toolchain, candidate, range, mode, preimage, postimage, syntax, or file
mode change makes the reviewed plan stale.

### Plan and mutation contract

A complete plan contains its `xray.change.v1` schema, root identity, selection,
source, captured input manifest, bounds, chosen edits, affected-file preimages
and postimages, diffs, baseline, acknowledgements, eligibility, and canonical
lowercase SHA-256 `plan_digest`. The digest covers the complete plan except its
own field. Plan, refine, and verify do not change repository source.

Before the first write, apply stages and verifies every postimage. It checks
exclusive regular-file targets, modes, and preimages immediately before each
replacement, then checks postimage bytes, modes, and syntax. These checks do
not make a multi-file apply atomic; another process can race between checks or
after a write.

Every recognized `change_apply` error has a top-level `mutation` object. Its
state pairs are:

- `not_applied` / `not_attempted`: no target write occurred;
- `rolled_back` / `succeeded`: all changed targets were verified restored after
  a caught failure;
- `partially_applied` / `failed`: restoration failed or an independent third
  value was preserved;
- `indeterminate` / `failed`: final bytes could not be established.

The optional `mutation.plan_digest` appears only after supplied digest
validation and is the only mutation location for that digest. Caught failures
attempt conflict-preserving rollback, but it is best-effort. SIGKILL, power
loss, process termination, or an equivalent interruption can leave partial
files and produce no JSON result. Inspect actual files and restore from the
caller's known baseline when necessary. XRAY provides no journal, transaction
identifier, or background restoration service.

CLI exits are `0` for success, `2` for malformed or invalid input/plan, and `1`
for stale input, containment, operational, resource, analysis, or mutation
failure. Keep the typed `error.code`, `error.action`, and `mutation` result.

## MCP handoff

FastMCP initially exposes exactly two adapter tools: `search_tools` and
`call_tool`. The eleven operation names are discovered contracts, not additional
registered tools. Use `search_tools` in `intent` (default), `exact`, or
`catalog` mode; request a complete contract and continue a cursor only with the
same mode and query.

```python
from fastmcp import Client
from xray.mcp_server import mcp

ROOT = "/absolute/path/to/repository"

async with Client(mcp) as client:
    tools = await client.list_tools()
    assert [tool.name for tool in tools] == ["search_tools", "call_tool"]
    contract = await client.call_tool(
        "search_tools", {"mode": "exact", "query": "change_plan", "max_bytes": 16384}
    )
```

Invoke the published operation through `call_tool` with exactly `name` and
`arguments`. The operation argument object contains `root`, `query`, optional
page controls, and optional execution controls, but never an `op` field. MCP
roots are normalized absolute paths; target paths remain repository-relative.
Use the complete closed schema returned by `search_tools`.

The canonical MCP two-call workflow mirrors the CLI:

```python
change_plan_arguments = {
    "root": ROOT,
    "query": {
        "source": {
            "kind": "pattern",
            "pattern": "foo($A)",
            "replacement": "bar($A)",
            "language": "python",
        },
        "selection": {"paths": ["sample.py"], "exclusions": "default"},
        "bounds": {"max_candidates": 100, "max_files": 20, "max_bytes": 32768},
    },
}
planned = await client.call_tool(
    "call_tool", {"name": "change_plan", "arguments": change_plan_arguments}
)
reviewed_plan = planned.structured_content["data"]["plan"]
# Save and review every file diff and edit ID; retain this digest independently.
reviewed_digest = reviewed_plan["plan_digest"]
applied = await client.call_tool(
    "call_tool",
    {
        "name": "change_apply",
        "arguments": {
            "root": ROOT,
            "query": {"plan": reviewed_plan, "expected_digest": reviewed_digest},
        },
    },
)
```

Optional refinement calls `change_refine` with
`{"plan": reviewed_plan, "edit_ids": [...]}` and then reviews the emitted
complete plan. Optional verification calls `change_verify` with
`{"plan": reviewed_plan, "expected_digest": reviewed_digest}`. Both are
non-mutating; apply repeats their guards. A rule source is
`{"kind":"rule","input":{"kind":"rule","path":"rules/foo.yml"}}`
or the same shape with input kind `config`.

Discovery reports `mutation: "guarded_mutation"` only for `change_apply`; the
other ten operations report `mutation: "read_only"`. The adapter `call_tool` is
annotated conservatively as destructive because it can select `change_apply`.
FastMCP returns the semantic result in `structured_content` and sets its error
flag for typed failures; never turn an error into an empty result.

For static client configuration, use only the generator's local checkout
(`local_python` or `source`) and installed (`installed_script`) stdio routes.
Unsupported transports are rejected rather than emitted as configuration.

## CLI-only skill installation

```bash
xray skill install --user
xray skill install --project ROOT
xray skill install --project ROOT --force
```

Project installation uses `ROOT/.agents/skills/xray-cli`; divergent existing
files require `--force`, and symlinked targets are rejected. Installation is not
discoverable through MCP.

After installation or a forced replacement, reload the agent integration or
start a new session so it reads the installed skill; a running session does not
automatically reload changed skill files. Installation preserves the current
eleven-operation, two-tool contract and does not add legacy aliases.

## Install from a local checkout

Use the local script or an explicitly selected checkout:

```bash
bash /absolute/path/to/xray/install.sh
bash /trusted/script/install.sh --checkout /absolute/path/to/xray
```

Without `--checkout`, the physically resolved local script selects its checkout.
With it, the supplied existing directory is selected. The script validates the
local source before bootstrapping `uv`, installs the absolute checkout, and never
selects XRAY source from ambient `cwd`, Git, or a remote endpoint. Remote
one-line XRAY installation is deferred; piped and sourced execution is
unsupported. The script is not a sandbox, so trust and stabilize the checkout.

On Linux, skill installation pins existing parents and uses descriptor-relative
no-follow operations with no-clobber publication/restoration. Caught identity,
I/O, restoration, or cleanup failures return an error and may retain private
recovery material. Interruption is not crash-atomic, and hostile same-UID-writer
isolation is not promised.

## Scope limits

XRAY supports bounded source and declaration analysis for Python, JavaScript,
TypeScript, and Go. It is not a language server, type resolver, dependency
query graph, or unbounded repository service. Cursors and typed references bind
to captured source; restart after a source change or stale-reference error.
Syntax evidence is not compilation, type validity, or proof of behavior.
