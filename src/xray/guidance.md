# XRAY progressive discovery

This is the authoritative workflow and limitations reference for the current
XRAY slice. The operation catalog has exactly eleven repository operations:
`capabilities`, `find`, `impact`, `interface`, `map`, `read`, `search`,
`change_plan`, `change_refine`, `change_verify`, and `change_apply`.
`map`, `find`, `interface`, `read`, `search`, `impact`, `capabilities`,
`change_plan`, `change_refine`, and `change_verify` are read-only.
`change_apply` is the only guarded source-mutating operation. `xray skill
install` remains a CLI-only administrative operation and is not an MCP
operation.

## Choose a direct entry point

Progressive discovery is optional. Start with the operation that matches the
information already available:

- Use `map` when the namespace or a bounded path is unfamiliar. It returns
  contained files and directories without reading source bodies.
- Use `find` when you know a declaration name or qualified identity. It returns
  canonical declaration items and typed symbol references.
- Use `interface` when you know a file or symbol reference and need bounded
  signatures, imports, exports, or declaration documentation.
- Use `read` when you know an exact location or trusted typed reference and need
  source text.
- Use `search` for exact literal text, an explicit-language structural pattern,
  or one contained rule/config input.
- Use `impact` after `find` when you need exact unresolved occurrences of one
  captured declaration name.
- Use `capabilities` to check the current version, supported languages,
  dependency health, and enabled-operation summaries.

A known declaration name needs no namespace tour: one `find` request followed by
one `interface` request yields the declaration signature and members, while one
`find` followed by one `read` request yields its body. A known expression can go
directly to `search`; a known symbol reference can go directly to `impact`. A
known file can enter with `interface` or `read`. Pass every complete typed
reference returned by XRAY to the next operation unchanged; do not reconstruct
it or turn its relative path into an absolute path.

Every result is bounded and uses the `xray.v1` envelope. JSON output carries
`schema`, `ok`, `op`, typed `data`, `coverage`, and provenance or error fields.
Text output is a deliberately lossy presentation for terminals.

## Shared request and result rules

Set an explicit repository root. The shell adapter normalizes `ROOT`; all
source paths, rule paths, config paths, and references inside requests remain
repository-relative POSIX paths. A path must stay inside `ROOT`, contain no
parent traversal, and not escape through a symlink. `capabilities` may omit
`ROOT` for a rootless catalog and health check; it never infers one from the
working directory.

Selection is explicit with contained `--path` values, ordered `--glob` values,
`--language` values, and `--exclusions default|none`. Collection operations use
an opaque cursor bound to the root, semantic query, selection, captured source
snapshot, and toolchain. Continue a page only with the same query and selection.
A changed source or stale reference requires a fresh request.

The JSON result is the semantic contract. `--format text` changes only the
terminal presentation, and `--pretty` changes only JSON indentation. Invalid
input, unsupported files, containment violations, invalid patterns or rules,
unsupported configuration, dependency failures, stale identity, stale cursors,
and response bounds are typed errors rather than empty success results.

## CLI workflow

```bash
ROOT=/absolute/path/to/repository

# Optional namespace entry when the path is unfamiliar.
uv run xray map "$ROOT" --focus src/xray --depth 1 --limit 20 --format json

# Known declaration: keep the complete reference for interface, read, or impact.
symbol=$(uv run xray find "$ROOT" XRayIndexer --match exact \
  --path src/xray/core/indexer.py --language python --limit 1 \
  | jq -c '.data.items[0].ref')
uv run xray interface "$ROOT" --ref-json "$symbol" --sections symbols --member-depth 1
uv run xray read "$ROOT" --ref-json "$symbol"
uv run xray impact "$ROOT" --ref-json "$symbol" --mode syntax --limit 20
```

The commands above are independent entry choices: `map` is not required before
`find`, `interface`, `read`, `search`, or `impact`.

### `map`

Map the explicitly rooted namespace without source bodies. The default focus is
`ROOT` and the default depth is two.

```bash
uv run xray map ROOT [options]
```

Options are `--focus PATH` (repeatable), `--depth N|all` (`0..64`), `--context
none|ancestors`, `--exclusions default|none`, `--cursor TOKEN`, `--limit N`
(`1..1000`), `--max-bytes N`, `--timeout-seconds N`, `--cache auto|off`,
`--format json|text`, and `--pretty`.

### `find`

Find declarations by name or qualified identity. The positional query is
required and `--match name` is the default.

```bash
uv run xray find ROOT QUERY [options]
```

Use `--match name|exact|fuzzy`. Selection filters are repeatable: `--path PATH`,
`--glob PATTERN`, `--language LANGUAGE`, `--kinds KIND`, and `--visibility
public|private|unknown`. Use `--exclusions default|none`, `--cursor TOKEN`,
`--limit N` (`1..100`), `--max-bytes N`, `--timeout-seconds N`, `--cache auto|off`,
`--format json|text`, and `--pretty`.

The result contains a complete typed symbol reference at
`.data.items[0].ref`. Keep that JSON object intact for a follow-up interface,
read, or impact request. A reference binds its root, relative path, byte range,
file digest, and analyzer identity.

### `interface`

Read one bounded interface from a contained file or one exact symbol reference.

```bash
uv run xray interface ROOT FILE [options]
uv run xray interface ROOT --ref-json JSON [options]
uv run xray interface ROOT --ref-file FILE [options]
```

Use exactly one file target or one JSON reference form. Options are
`--sections symbols|imports|exports` (repeatable), `--member-depth 0|1`,
`--documentation`, `--kinds KIND`, `--visibility public|private|unknown`,
`--cursor TOKEN`, `--limit N` (`1..200`), `--max-bytes N`,
`--timeout-seconds N`, `--cache auto|off`, `--format json|text`, and `--pretty`.
A symbol-target interface is bounded to that owner and does not add sibling
declarations. When a displayed signature or documentation field is clipped,
the declaration lists it in `disclosure.clipped`; its exact reference is
unchanged. `--ref-file -` reads one JSON reference from standard input.

### `read`

Read one exact location or typed reference, or a JSON batch of one to eight
contained targets.

```bash
uv run xray read ROOT TARGET --line 1 [--end-line N] [--column N] [options]
uv run xray read ROOT --ref-json JSON [options]
uv run xray read ROOT --ref-file FILE [options]
uv run xray read ROOT --targets-file FILE [options]
```

`TARGET` is a repository-relative POSIX path and requires one-based `--line`;
`--end-line` and `--column` are optional. JSON targets may be location, source,
symbol, or occurrence references returned by a trusted producer.
`--targets-file -` reads a JSON array from standard input. Read controls are
`--context-lines N` (`0..10`), `--include-enclosing` (default),
`--no-enclosing`, `--cursor TOKEN`, `--max-bytes N`, `--max-lines N` (`1..256`),
`--source-bytes N` (`1..32768`), `--timeout-seconds N`, `--cache auto|off`,
`--format json|text`, and `--pretty`.

### `search`

Search captured supported-source text with exactly one source form:
`--literal`, `--pattern` plus `--lang`, `--rule`, or `--config`.

```bash
uv run xray search ROOT --literal 'raise ValueError' --path src/xray --limit 20
uv run xray search ROOT --pattern 'raise $E' --lang python --path src/xray --detail detail
uv run xray search ROOT --rule rules/no-foo.yml --detail detail
uv run xray search ROOT --config sgconfig.yml
```

Literal search is exact, case-sensitive UTF-8 text matching, including
newlines, with non-overlapping occurrences. It is not a regular-expression or
fuzzy search. Pattern search is an ast-grep structural query and requires one
explicit language: `python`, `javascript`, `typescript`, or `go`. An invalid
pattern is an `invalid_pattern` error; XRAY does not reinterpret it as literal
text.

`--detail summary` is the default. Summary items contain an occurrence
reference, location, and matched text; rule matches also contain `rule_id`.
`--detail detail` adds only verified named captures and may include disclosure
when an optional capture value is clipped. Search coverage identifies whether
the basis is `literal_occurrences`, `pattern_matches`, or `rule_diagnostics`.

Search selection and paging controls are `--path PATH`, `--glob PATTERN`,
`--language LANGUAGE`, `--exclusions default|none`, `--detail summary|detail`,
`--cursor TOKEN`, `--limit N` (`1..1000`), `--max-bytes N`,
`--timeout-seconds N`, `--cache auto|off`, `--format json|text`, and `--pretty`.
`--lang` applies only to `--pattern`; rule languages come from the rule input.

#### Contained rule and config inputs

A standalone rule is a self-contained `.yml` or `.yaml` file supplied with
`--rule`. It may contain one or more rule documents. Keep all rule content in
that file; no project configuration is loaded implicitly.

```yaml
# ROOT/rules/no-foo.yml
id: no-foo-call
language: Python
rule:
  pattern: foo($A)
```

A config supplied with `--config` is one contained `.yml` or `.yaml` document
whose complete top-level mapping is exactly a nonempty `ruleDirs` string list.
Each directory is resolved relative to the config file's parent, must remain
inside `ROOT`, and is recursively enumerated for `.yml` and `.yaml` rules in
canonical path order. For example:

```yaml
# ROOT/sgconfig.yml
ruleDirs:
  - rules
```

The `ruleDirs` directory must contain at least one rule file. Symlinks in the
configuration or its rule membership are rejected. Unknown top-level keys,
multiple config documents, empty directories, directory input in place of a
file, implicit environment or ancestor configuration, custom grammars, and
external configuration dependencies are unsupported. Use a standalone
self-contained rule, the closed `ruleDirs` form, XRAY selection options, or the
upstream ast-grep tool for broader rule authoring.

### `impact`

Report occurrences of one exact captured symbol reference. Supply exactly one
`--ref-json` or `--ref-file`; `--ref-file -` reads JSON from standard input.
There is no manual name target.

```bash
uv run xray impact ROOT --ref-json "$symbol" --mode syntax \
  --path src/xray --language python --limit 100
uv run xray impact ROOT --ref-json "$symbol" --mode lexical --limit 100
```

`--mode syntax` is the default. It reports exact identifier-spelling
occurrences with syntax evidence when the parser data is available and
classifies them as `definition`, `import`, `call`, `read`, `comment`, `string`,
or `unknown`. `--mode lexical` is an explicit exact-spelling search with
identifier-boundary rules; its items use `kind: text` and `evidence: lexical`.
The selected mode is never changed automatically. Syntax or parser limitations
appear in `coverage` and do not become a different query.

Impact data always states `basis: name_occurrences` and `resolution: unresolved`.
Each item has a directly readable occurrence reference, byte-precise location,
text, evidence, and optional enclosing or import details. Only the selected
declaration's defining-name token is omitted; recursive calls and other
same-name occurrences remain eligible.

Impact selection and paging controls are `--path PATH`, `--glob PATTERN`,
`--language LANGUAGE`, `--exclusions default|none`, `--mode syntax|lexical`,
`--cursor TOKEN`, `--limit N` (`1..1000`), `--max-bytes N`,
`--timeout-seconds N`, `--cache auto|off`, `--format json|text`, and `--pretty`.

Impact does not resolve an occurrence to the target definition. It does not
claim dependents, callers, alias following, a dependency graph, or resolved
relationships. Import details report observed module and spelling fields only;
aliases are not followed.

### `change plan|refine|verify|apply`

The change service has one complete lifecycle for a structural pattern or a
contained rule/config input. `change_plan`, `change_refine`, and
`change_verify` never write repository source. Only `change_apply` can write
source files.

The canonical workflow has two product calls:

1. **Plan:** build a complete `xray.change.v1` plan and save its JSON artifact.
2. **Review and apply:** inspect the complete artifact and invoke `change_apply`
   with that artifact plus an independently retained `plan_digest`.

Refinement and verification are optional calls between planning and applying.
They never replace review. Apply repeats every guard and never relies on an
earlier verify result.

#### CLI plan and apply

Every change command takes an explicit `ROOT`, followed by its leaf and options:

```bash
ROOT=/absolute/path/to/repository

xray change plan "$ROOT" \
  --pattern 'foo($A)' --replacement 'bar($A)' --lang python \
  --path src --max-candidates 100 --max-files 20 \
  > plan-response.json
jq -e '.ok == true and .op == "change_plan" and (.data.plan.plan_schema == "xray.change.v1")' \
  plan-response.json >/dev/null
jq '.data.plan' plan-response.json > plan.json

# Review plan.json, including every file diff and edit ID.
EXPECTED_DIGEST=$(jq -r '.plan_digest' plan.json)
xray change apply "$ROOT" --plan-file plan.json \
  --expected-digest "$EXPECTED_DIGEST"
```

`--plan-file FILE` reads one complete `xray.change.v1` plan. Use
`--plan-file -` to read that JSON object from standard input. A current
`change_plan` or `change_refine` success envelope is accepted as a transport
convenience, but writing `.data.plan` to a file makes the complete artifact
explicit and reviewable. The apply argument is deliberately separate:
the caller must supply the reviewed plan's lowercase SHA-256 `plan_digest` as
`--expected-digest`; apply never infers or overrides it.

The pattern source requires all three flags:
`--pattern PATTERN`, `--replacement TEXT`, and `--lang LANGUAGE`. The language
must be `python`, `javascript`, `typescript`, or `go`. A literal is not a
change source. A rule source uses exactly one of `--rule FILE` or
`--config FILE`; both paths are contained repository-relative YAML files.

The optional plan controls are `--path PATH`, `--glob PATTERN`,
`--language LANGUAGE`, `--exclusions default|none`, `--max-candidates N`,
`--max-files N`, and `--max-bytes N`. Candidate, file, and response bounds are
hard limits. The only plan acknowledgements are `--allow-dirty-affected` and
`--allow-new-parse-errors`. They become fields in the plan and cannot be added,
removed, or changed by refine, verify, or apply.

#### Optional refine and verify

Refine selects a subset of the plan's complete, canonical `edit_id` values and
emits another complete plan. It does not edit source:

```bash
jq -r '.edits[].edit_id' plan.json
xray change refine "$ROOT" --plan-file plan.json \
  --edit-id "$(jq -r '.edits[0].edit_id' plan.json)" \
  > refined-response.json
jq '.data.plan' refined-response.json > reviewed-plan.json
```

Edit IDs must be unique, sorted digests. An empty selection emits a complete
inapplicable plan; an unknown ID is an error. Review the newly emitted plan,
not the superseded plan, and use its new digest.

Verify is an optional non-mutating guard check:

```bash
REVIEWED_DIGEST=$(jq -r '.plan_digest' reviewed-plan.json)
xray change verify "$ROOT" --plan-file reviewed-plan.json \
  --expected-digest "$REVIEWED_DIGEST"
xray change apply "$ROOT" --plan-file reviewed-plan.json \
  --expected-digest "$REVIEWED_DIGEST"
```

`verify` returns `ready: true` and the reviewed digest without writing source.
Both `verify` and `apply` require the complete plan and an independent expected
digest. Neither leaf accepts acknowledgement flags. A changed source,
configuration, policy, selection, toolchain, candidate set, range, mode,
preimage, postimage, syntax evidence, or file mode makes the plan stale.

#### Rule/config plan example

A standalone rule is self-contained. A config is one YAML document whose
complete top-level mapping is a nonempty `ruleDirs` string list; each listed
directory is relative to the config file, contained by `ROOT`, and must contain
at least one YAML rule. No ambient configuration is loaded.

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

Use either source form, then the same review and apply calls:

```bash
xray change plan "$ROOT" --rule rules/foo.yml --path sample.js > plan-response.json
# or: xray change plan "$ROOT" --config config.yml --path sample.js > plan-response.json
jq '.data.plan' plan-response.json > plan.json
EXPECTED_DIGEST=$(jq -r '.plan_digest' plan.json)
xray change apply "$ROOT" --plan-file plan.json --expected-digest "$EXPECTED_DIGEST"
```

Unknown keys, multiple YAML documents, empty rule directories, directory input,
symlinks, implicit ancestor/environment configuration, custom grammars, and
external rule dependencies are rejected. Search and change use the same
contained rule/config admission.

#### Change results, errors, and interruption limits

Each complete plan includes its root identity, selection, source, captured input
manifest, bounds, chosen edits, affected-file preimages/postimages, diffs,
baseline, acknowledgements, eligibility, and `plan_digest`. The digest covers
the canonical complete plan except its own digest field. A plan is not an
instruction to apply a different or newly collected match set.

Before applying, XRAY stages and verifies every postimage, then checks each
target is an exclusive regular file with the planned mode and preimage. It
checks postimage bytes, mode, and syntax after each replacement. Apply is not a
multi-file atomic transaction; another process can race between checks or after
a write.

Every recognized `change_apply` error carries a top-level `mutation` object.
Before the first target write, it is
`state: "not_applied"` with `rollback_status: "not_attempted"`. For a caught
failure after writes, the result is one of:

- `state: "rolled_back"`, `rollback_status: "succeeded"` when all changed
  targets are verified restored;
- `state: "partially_applied"`, `rollback_status: "failed"` when restoration
  fails or an independently changed third value is preserved;
- `state: "indeterminate"`, `rollback_status: "failed"` when final bytes cannot
  be established.

The optional `mutation.plan_digest` appears only after the supplied digest has
been validated. It is the only mutation location for that digest.

Caught failures attempt conflict-preserving rollback; this is best-effort and
does not create an atomic guarantee. SIGKILL, power loss, process termination,
or an equivalent interruption can leave partial files and produce no JSON
result at all. Inspect the actual files and restore them from the caller's
known baseline when necessary. There is no journal, transaction identifier, or
background restoration service.

CLI exits are `0` for success, `2` for malformed/invalid input or plan, and `1`
for stale input, containment, operational, resource, analysis, or mutation
failure. The JSON `error.code`, `error.action`, and `mutation` state are the
authoritative result; do not treat a failed operation as an empty success.

### `capabilities`

Report the current catalog and health. A rootless check never infers a root from
the current working directory; supplying `ROOT` checks that explicit
repository.

```bash
uv run xray capabilities
uv run xray capabilities ROOT --detail detail
```

Options are `--detail summary|detail`, `--timeout-seconds N`, `--cache auto|off`,
`--format json|text`, and `--pretty`. Detail mode lists all eleven enabled
repository operations and their mutation class. The rootless form reports the
catalog and available dependencies; a rooted form also reports
repository-dependent health.

## MCP discovery and calls

XRAY uses FastMCP's standard client surface. `list_tools()` initially returns
exactly two adapter tools: `search_tools` and `call_tool`. Repository operations
are not registered as separate MCP tools. Discover a complete call-ready
contract with `search_tools`, then invoke its published operation name through
`call_tool`; do not add an `op` field inside `arguments`.

The standard Python client can enter directly at a known operation:

```python
from fastmcp import Client
from xray.mcp_server import mcp

ROOT = "/absolute/path/to/repository"

async with Client(mcp) as client:
    tools = await client.list_tools()
    assert [tool.name for tool in tools] == ["search_tools", "call_tool"]

    search_contract = await client.call_tool(
        "search_tools",
        {"mode": "exact", "query": "search", "max_bytes": 16384},
    )
    search_result = await client.call_tool(
        "call_tool",
        {
            "name": "search",
            "arguments": {
                "root": ROOT,
                "query": {
                    "source": {"kind": "literal", "text": "TODO"},
                    "selection": {"paths": ["."], "languages": ["python"]},
                    "detail": "summary",
                },
                "page": {"limit": 20, "max_bytes": 16384},
            },
        },
    )
```

`search_tools` supports three modes:

- `intent` (the default) searches by natural-language intent;
- `exact` selects one enabled operation name and returns its complete schema;
- `catalog` pages the enabled catalog.

Intent and catalog requests accept optional `limit`, `max_bytes`, and opaque
`cursor` values. Continue a page only with the same mode and query. Exact
requests use one enabled operation name and `max_bytes`; request enough bytes
for the complete contract, such as `16384`. The enabled names are exactly
`capabilities`, `find`, `impact`, `interface`, `map`, `read`, `search`,
`change_plan`, `change_refine`, `change_verify`, and `change_apply`.

The operation call arguments mirror the CLI request models. Search source forms
are represented as follows:

```python
literal_arguments = {
    "root": ROOT,
    "query": {
        "source": {"kind": "literal", "text": "TODO"},
        "detail": "summary",
    },
}
pattern_arguments = {
    "root": ROOT,
    "query": {
        "source": {"kind": "pattern", "pattern": "foo($A)", "language": "python"},
        "detail": "detail",
    },
}
rule_arguments = {
    "root": ROOT,
    "query": {
        "source": {"kind": "rule", "input": {"kind": "rule", "path": "rules/no-foo.yml"}},
    },
}
config_arguments = {
    "root": ROOT,
    "query": {
        "source": {"kind": "rule", "input": {"kind": "config", "path": "sgconfig.yml"}},
    },
}
search_result = await client.call_tool(
    "call_tool", {"name": "search", "arguments": literal_arguments}
)
```

Use the complete contract returned by `search_tools`; replace `literal_arguments`
with the selected closed argument object. FastMCP carries structured operation
results and tool-error results in its normal result object. Never turn a tool
error into an empty result.

Impact takes the complete symbol reference returned by `find`:

```python
found = await client.call_tool(
    "call_tool",
    {
        "name": "find",
        "arguments": {
            "root": ROOT,
            "query": {"text": "XRayIndexer", "match": "exact"},
            "page": {"limit": 1, "max_bytes": 16384},
        },
    },
)
target = found.structured_content["data"]["items"][0]["ref"]
impact_result = await client.call_tool(
    "call_tool",
    {
        "name": "impact",
        "arguments": {
            "root": ROOT,
            "query": {"target": target, "mode": "syntax"},
            "page": {"limit": 100, "max_bytes": 16384},
        },
    },
)
```

For direct operation query shapes, `root` is normalized and absolute and all
target paths are contained repository-relative POSIX paths. Operation argument
objects are closed and contain no `op` field:

```python
map_arguments = {
    "root": ROOT,
    "query": {"focus": ["src/xray"], "depth": 1, "context": "none"},
}
find_arguments = {
    "root": ROOT,
    "query": {"text": "XRayIndexer", "match": "exact"},
}
interface_arguments = {
    "root": ROOT,
    "query": {
        "target": {"kind": "file", "path": "src/xray/cli.py"},
        "sections": ["symbols"],
        "member_depth": 1,
    },
}
read_arguments = {
    "root": ROOT,
    "query": {
        "targets": [{"kind": "location", "path": "src/xray/cli.py", "line": 1}]
    },
}
impact_arguments = {
    "root": ROOT,
    "query": {"target": target, "mode": "syntax"},
}
capabilities_arguments = {"query": {"detail": "detail"}}
```

Change arguments use the same closed `root`/`query` shape:

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
change_refine_arguments = {
    "root": ROOT,
    "query": {
        "plan": reviewed_plan,
        "edit_ids": [reviewed_plan["edits"][0]["edit_id"]],
    },
}
change_review_arguments = {
    "root": ROOT,
    "query": {
        "plan": reviewed_plan,
        "expected_digest": reviewed_plan["plan_digest"],
    },
}
```

The canonical MCP two-call change is `change_plan`, followed by external review
and `change_apply` with the complete reviewed plan and independently retained
digest:

```python
planned = await client.call_tool(
    "call_tool", {"name": "change_plan", "arguments": change_plan_arguments}
)
plan = planned.structured_content["data"]["plan"]
# Save plan as JSON, review every file and edit, and retain its digest.
reviewed_plan = plan
reviewed_digest = reviewed_plan["plan_digest"]
applied = await client.call_tool(
    "call_tool",
    {
        "name": "change_apply",
        "arguments": {
            "root": ROOT,
            "query": {
                "plan": reviewed_plan,
                "expected_digest": reviewed_digest,
            },
        },
    },
)
```

Optional MCP refinement emits a new complete plan and therefore requires review
of that new artifact and its new digest:

```python
refined = await client.call_tool(
    "call_tool",
    {"name": "change_refine", "arguments": change_refine_arguments},
)
reviewed_plan = refined.structured_content["data"]["plan"]
```

Optional verification uses the same `change_review_arguments` shape with
`"name": "change_verify"`; it is non-mutating, and `change_apply` repeats its
guards. Change operation arguments contain no acknowledgement override. A rule
source uses `{"kind": "rule", "input": {"kind": "rule", "path": "rules/foo.yml"}}`
or the same shape with `"kind": "config"`.

For each shape, call the published operation as follows:

```python
result = await client.call_tool(
    "call_tool",
    {"name": "map", "arguments": map_arguments},
)
```

Replace `map` and `map_arguments` with the selected enabled name and its
complete contract. The operation name belongs in `call_tool.name`; the
operation arguments contain `root`, `query`, optional page controls, and
optional execution controls, but never `op`.

MCP returns the same semantic JSON value as the CLI. `change_apply` is the only
discovered operation with `mutation: "guarded_mutation"`; the other ten use
`mutation: "read_only"`. The adapter's `call_tool` annotation is conservative:
it is marked destructive because the selected operation may be `change_apply`.
Always inspect `structured_content`, honor `is_error`, and preserve typed errors.

For static client configuration, use only the generator's local checkout
(`local_python` or `source`) and installed (`installed_script`) stdio routes.
Unsupported transports are rejected rather than emitted as configuration.

## CLI-only administration

`xray skill install` installs the packaged `xray-cli` skill under
`.agents/skills/xray-cli`. The default is the current user's home; use
`--project ROOT` for one repository. Existing divergent files are preserved
unless `--force` is supplied, and symlinked paths are rejected.

```bash
uv run xray skill install --user
uv run xray skill install --project ROOT
uv run xray skill install --project ROOT --force
```

After installation or a forced replacement, reload the agent integration or
start a new session so it reads the installed skill; a running session does not
automatically reload changed skill files. Installation preserves the current
eleven-operation, two-tool contract and does not add legacy aliases.

To install XRAY itself, invoke the local checkout script or select one
explicitly:

```bash
bash /absolute/path/to/xray/install.sh
bash /trusted/script/install.sh --checkout /absolute/path/to/xray
```

The script validates the local source before bootstrapping `uv`, then installs
that absolute checkout. It does not select XRAY source from ambient `cwd`, Git,
or a remote endpoint; remote one-line XRAY installation is deferred. Piped or
sourced execution is unsupported. The script is not a sandbox: trust the
selected checkout and keep it stable during installation.

On Linux, skill installation pins existing parents and uses descriptor-relative
no-follow operations with no-clobber publication and restoration. A caught
identity, I/O, restoration, or cleanup failure returns an error and may retain
private recovery material. Interruption is not crash-atomic, and hostile
same-UID-writer isolation is not promised.

Installation success and error payloads use `schema: "xray.v1"` on the CLI only.
The command is not discoverable through `search_tools` and must not be sent
through `call_tool`.

## Limits and current scope
XRAY captures bounded source slices and declaration metadata for Python,
JavaScript, TypeScript, and Go. It is not a language server, type resolver,
dependency graph, or unbounded repository query service. All eleven operations
publish bounded page, byte, target, selection, or plan controls through their
CLI help and MCP contracts. Cursors and typed references are bound to the
captured source snapshot; restart the request after a source change or
stale-reference error.

Literal, pattern, rule, config, and impact inputs are analyzed only from the
explicit captured selection. Non-text or NUL-bearing source is reported through
partial coverage instead of being presented as exact text. A parser limitation
or unsupported syntax is reported in coverage; it does not silently change the
requested operation or mode.

Impact is intentionally name-based and unresolved. Its `name_occurrences`
basis reports exact spelling evidence, not resolved callers, dependents,
aliases, or a graph. Search captures match evidence and verified optional detail;
it does not claim behavior, type resolution, or repository-wide semantic
completeness.

The same guide is available as the `xray://workflow` MCP resource. FastMCP also
exposes the packaged progressive-discovery skill resource and template.
