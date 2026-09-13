# XRAY Progressive Discovery

Use the current XRAY MCP surface for bounded repository inspection and reviewed
structural changes. Progressive discovery is optional: start with `map`, `find`,
`interface`, `read`, `search`, `impact`, or a guarded change operation when the
needed input is already known.

The operation catalog has exactly eleven repository operations:
`capabilities`, `find`, `impact`, `interface`, `map`, `read`, `search`,
`change_plan`, `change_refine`, `change_verify`, and `change_apply`. The seven
inspection operations (`capabilities`, `find`, `impact`, `interface`, `map`,
`read`, `search`) plus `change_plan`, `change_refine`, and `change_verify` are
read-only. `change_apply` is the only guarded source-mutating operation.

## Choose an entry point

- `map` lists a bounded namespace without reading source bodies.
- `find` locates a declaration by name or qualified identity and returns a typed
  symbol reference.
- `interface` reads bounded signatures, imports, exports, or documentation for
  one file or exact symbol reference.
- `read` captures exact source locations or trusted typed references.
- `search` searches exact literal text, an explicit-language structural pattern,
  or one contained rule/config input.
- `impact` reports exact unresolved occurrences for one captured declaration
  reference with explicit syntax or lexical evidence.
- `capabilities` reports health, languages, and enabled-operation summaries.

A known declaration needs no namespace tour: use `find`, then `interface`,
`read`, or `impact`. A known expression goes directly to `search`. Pass every
complete typed reference unchanged; its root identity, relative path, byte
range, file digest, and analyzer identity are bound to the captured source.

## Standard MCP discovery and calls

FastMCP initially exposes exactly two adapter tools: `search_tools` and
`call_tool`. The eleven operation names are discovered contracts, not additional
registered tools. Use the standard client methods `list_tools()` and
`call_tool(name, arguments)`.

```python
from fastmcp import Client
from xray.mcp_server import mcp

ROOT = "/absolute/path/to/repository"

async with Client(mcp) as client:
    tools = await client.list_tools()
    assert [tool.name for tool in tools] == ["search_tools", "call_tool"]
    contract = await client.call_tool(
        "search_tools",
        {"mode": "exact", "query": "search", "max_bytes": 16384},
    )
    result = await client.call_tool(
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
- `catalog` pages the enabled operation catalog.

Intent and catalog requests accept bounded `limit`, `max_bytes`, and opaque
`cursor` values. Continue a cursor only with the same mode and query. Exact
requests use one enabled name and `max_bytes`; request enough bytes for the
complete contract, such as `16384`. The names are exactly
`capabilities`, `find`, `impact`, `interface`, `map`, `read`, `search`,
`change_plan`, `change_refine`, `change_verify`, and `change_apply`.

Invoke only the published contract. `call_tool` has exactly `name` and
`arguments`; the operation argument object contains `root`, `query`, optional
page controls, and optional execution controls, but never an `op` field. MCP
roots are normalized absolute paths and target paths are contained
repository-relative POSIX paths. Use the complete closed schema returned by
`search_tools`. FastMCP returns typed errors in the normal result object; never
turn an error into an empty result.

## Search and rule inputs

The `search` query has exactly one source branch:

```python
literal_arguments = {
    "root": ROOT,
    "query": {"source": {"kind": "literal", "text": "TODO"}, "detail": "summary"},
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

Literal search is exact, case-sensitive UTF-8 text with non-overlapping
occurrences. Pattern search requires one explicit `language` of `python`,
`javascript`, `typescript`, or `go`. `detail: "summary"` is the default;
`detail: "detail"` adds verified named captures. A rule input is either one
contained self-contained `.yml`/`.yaml` file (`input.kind: "rule"`) or one
contained config file (`input.kind: "config"`). A config is exactly one YAML
document with a nonempty `ruleDirs` string list. Each listed directory is
relative to the config file, remains inside `ROOT`, and is recursively
enumerated for YAML rules in canonical path order. Symlinks, unknown keys,
multiple documents, empty rule sets, directory input, ambient configuration,
custom grammars, and external dependencies are rejected.

## Operation query shapes

These are canonical starting shapes. Every operation has its complete published
schema and closed arguments; `root` is absolute and target paths are contained
repository-relative POSIX paths:

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

`find` returns its complete symbol reference in
`structured_content["data"]["items"][0]["ref"]`; pass it unchanged to
`interface`, `read`, or `impact`. Impact is name-based and unresolved. Its
`name_occurrences` evidence does not establish callers, dependents, aliases, a
dependency graph, or resolved relationships.

## Plan, review, and apply a guarded change

The guarded change operation set uses one lifecycle for structural patterns and
contained rule/config inputs. Only `change_apply` writes repository source.
The canonical workflow is exactly two product calls:

1. Call `change_plan` and save the complete `xray.change.v1` plan object as JSON.
2. Review every file diff and edit ID, then call `change_apply` with that same
   complete plan and a separately supplied expected digest.

`change_refine` and `change_verify` are optional calls between those two calls.
They do not write source. Apply repeats every guard and does not rely on an
earlier verify result.

### Pattern plan and apply

A pattern source requires `pattern`, `replacement`, and explicit `language`:

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
plan = planned.structured_content["data"]["plan"]
# Save plan as JSON and review every diff and edit ID.
reviewed_plan = plan
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

The expected digest is a separate required argument. It must be retained or
recomputed by the caller from the reviewed plan; `change_apply` never infers,
changes, or overrides it. A complete plan contains root identity, selection,
source, captured input manifest, bounds, chosen edits, affected-file preimages
and postimages, diffs, baseline, acknowledgements, eligibility, and canonical
lowercase SHA-256 `plan_digest`.

Plan selection may include `paths`, ordered `globs`, `languages`, and
`exclusions`. Bounds are `max_candidates` (`1..1000`), `max_files` (`1..100`),
and `max_bytes` (`4096..262144`), with fixed file/image limits enforced by the
service. Plan acknowledgements are `dirty_affected` and `new_parse_errors`;
the CLI flags `--allow-dirty-affected` and `--allow-new-parse-errors` set them.
They are part of the complete plan and cannot be added or changed by refine,
verify, or apply.

### Rule plan and apply

A rule source has the same two-call lifecycle. Use either a standalone rule or a
closed config input:

```python
rule_plan_arguments = {
    "root": ROOT,
    "query": {
        "source": {
            "kind": "rule",
            "input": {"kind": "rule", "path": "rules/foo.yml"},
        },
        "selection": {"paths": ["sample.js"], "exclusions": "default"},
    },
}
rule_planned = await client.call_tool(
    "call_tool", {"name": "change_plan", "arguments": rule_plan_arguments}
)
rule_plan = rule_planned.structured_content["data"]["plan"]
# Review rule_plan, retain rule_plan["plan_digest"], then call change_apply.
```

A config input uses `input.kind: "config"` and a contained config path. Rule
and config files are captured into the plan manifest; no ambient project
configuration is loaded.

### Optional refine and verify

Refine accepts a complete plan and sorted, unique `edit_ids`, then emits a new
complete plan. An empty selection is a complete inapplicable plan; an unknown ID
is an error. Review the new artifact and retain its new digest:

```python
change_refine_arguments = {
    "root": ROOT,
    "query": {
        "plan": reviewed_plan,
        "edit_ids": [reviewed_plan["edits"][0]["edit_id"]],
    },
}
refined = await client.call_tool(
    "call_tool", {"name": "change_refine", "arguments": change_refine_arguments}
)
reviewed_plan = refined.structured_content["data"]["plan"]
reviewed_digest = reviewed_plan["plan_digest"]
```

Verify is an optional non-mutating guard check:

```python
review = await client.call_tool(
    "call_tool",
    {
        "name": "change_verify",
        "arguments": {
            "root": ROOT,
            "query": {"plan": reviewed_plan, "expected_digest": reviewed_digest},
        },
    },
)
```

A successful verify returns `ready: true` and the plan digest. Both verify and
apply require the complete plan plus expected digest and accept no acknowledgement
override. Apply repeats all guards even after verify succeeds.

### Mutation states and interruption limits

The adapter marks `call_tool` conservatively as destructive because it can
select `change_apply`. Discovery marks only `change_apply` as
`mutation: "guarded_mutation"`; the other ten operations are
`mutation: "read_only"`.

Every recognized `change_apply` failure carries a top-level `mutation` object.
Its state pairs are:

- `not_applied` / `not_attempted`: no target write occurred;
- `rolled_back` / `succeeded`: all changed targets were verified restored after
  a caught failure;
- `partially_applied` / `failed`: restoration failed or an independently
  changed third value was preserved;
- `indeterminate` / `failed`: final bytes could not be established.

The optional `mutation.plan_digest` appears only after supplied digest
validation and is the only mutation location for that digest. Before each write
XRAY checks the target's exclusive regular-file status, mode, and preimage; it
checks postimage bytes, mode, and syntax after each replacement. These checks do
not make a multi-file apply atomic, and another process can race between checks
or after a write. Caught failures attempt conflict-preserving rollback, but it
is best-effort.

SIGKILL, power loss, process termination, or an equivalent interruption can
leave partial files and produce no JSON result. Inspect actual files and restore
from the caller's known baseline when necessary. XRAY has no journal,
transaction identifier, or background restoration service. A typed MCP error is
not a successful empty result; preserve its `error.code`, `error.action`, and
mutation state.

## Current boundaries

XRAY captures bounded source and declaration data for Python, JavaScript,
TypeScript, and Go. It is not a language server, type resolver, dependency
graph, or unbounded repository query service. Cursors and typed references bind
to captured source; restart after a source change or stale-reference error.
Parser limitations, unsupported syntax, non-text input, and partial coverage
remain explicit in the result. Syntax evidence is not compilation, type
validity, or proof of behavior.

The authoritative workflow and limitation reference is `xray://workflow`.
CLI-only skill installation is not a callable MCP operation.

Static client configuration is limited to local checkout or installed stdio
routes; unsupported transports are rejected rather than emitted.

After installing or force-replacing the CLI skill, reload the agent integration
or start a new session; a running session does not automatically reload changed
skill files.
