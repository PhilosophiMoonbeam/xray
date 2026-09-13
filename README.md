# XRAY - Agent-Centric Code Intelligence CLI and MCP Server

[![Python](https://img.shields.io/badge/Python-3.10+-green)](https://python.org)
[![MCP](https://img.shields.io/badge/MCP-Compatible-purple)](https://modelcontextprotocol.io)
[![ast-grep](https://img.shields.io/badge/Powered_by-ast--grep-orange)](https://ast-grep.github.io)

XRAY 1.0.0 gives coding agents bounded repository discovery, source capture, and
reviewed structural changes without a language-server process. Use the
handwritten `xray` shell CLI or run `xray-mcp` for an MCP-capable assistant.
The [architecture contract](ARCHITECTURE.md) owns complete interfaces, bounds,
containment, storage, mutation safety, and synchronized change obligations;
this file keeps practical product workflows. [`PROJECT.md`](PROJECT.md) is the
current mode and scoped command catalog. Adoption and next-major packets remain
historical evidence unless a named Enterprise/Certification milestone is
explicitly activated.

## Current operations

Exactly eleven repository operations are enabled:

- `map` lists a bounded, explicitly rooted namespace without source bodies.
- `find` locates declarations by name or qualified identity and returns typed
  symbol references.
- `interface` reads bounded signatures, observed imports/exports, or docs.
- `read` captures one to eight exact source targets with bounded context and
  snapshot-bound continuation.
- `search` finds literal text, explicit-language structural patterns, or one
  contained rule/config input.
- `impact` reports exact unresolved occurrences for one captured reference.
- `capabilities` reports version, languages, dependency health, and operations.
- `change_plan`, `change_refine`, `change_verify`, and `change_apply` form one
  reviewed lifecycle; only `change_apply` mutates source.

Progressive discovery is optional. A known file can go directly to `interface`
or `read`; a known declaration can go from one `find` result to `interface`,
`read`, or `impact`; a known expression can go directly to `search`. The
[workflow and limitation guide](src/xray/guidance.md) is also published at the
MCP resource `xray://workflow`.

CLI-only `xray skill install` installs the bundled agent skill and is not an MCP
operation. No compatibility aliases or alternate operation routes are exposed.

## Quick start

All source operations require an explicit existing repository root:

```bash
ROOT=/absolute/path/to/repository

uv run xray capabilities "$ROOT" --detail detail
uv run xray map "$ROOT" --focus src/xray --depth 1 --limit 20
uv run xray find "$ROOT" XRayIndexer --match exact --language python --limit 1
uv run xray interface "$ROOT" src/xray/cli.py --sections symbols --member-depth 1
uv run xray read "$ROOT" src/xray/cli.py --line 1 --end-line 20 --context-lines 2
uv run xray search "$ROOT" --literal 'raise ValueError' --path src/xray --limit 20
```

`ROOT` must be a directory. Source, rule, config, and typed-reference paths are
contained repository-relative POSIX paths. `capabilities` also has a rootless
catalog/health form and never infers a root from the current directory.

A declaration reference is the handoff between operations; preserve its complete
JSON object:

```bash
symbol=$(uv run xray find "$ROOT" XRayIndexer --match exact \
  --path src/xray/core/indexer.py --language python --limit 1 \
  | jq -c '.data.items[0].ref')
uv run xray impact "$ROOT" --ref-json "$symbol" --mode syntax --limit 20
uv run xray interface "$ROOT" --ref-json "$symbol" --sections symbols
uv run xray read "$ROOT" --ref-json "$symbol"
```

## Install

XRAY requires Python 3.10+. Runtime dependencies are `fastmcp>=3.4.7,<4`,
`ast-grep-cli>=0.45.1,<0.46`, `ast-grep-py>=0.45.1,<0.46`,
`thefuzz>=0.20.0`, `pydantic>=2,<3`, `pathspec>=0.12,<1`, and `pyyaml>=6,<7`.
The aligned `ast-grep` executable and Python package are supplied by those
requirements; no separate ast-grep installation is normally needed.

```bash
# Install an explicitly selected trusted local checkout.
XRAY=/absolute/path/to/xray
uv tool install "$XRAY"
xray capabilities
xray skill install --user
xray-mcp
```

The local bootstrap script accepts only an explicitly selected checkout:

```bash
bash /absolute/path/to/xray/install.sh
bash /trusted/script/install.sh --checkout /absolute/path/to/xray
```

Without `--checkout`, the physically resolved local script selects its checkout.
With it, the supplied existing directory is selected. The script may bootstrap
`uv` and dependencies and replace the uv-managed tool, but never fetches XRAY
source through Git or the network. Remote one-line XRAY installation is
deferred. Piped, sourced, ambient-cwd, and invalid-source invocations fail
before installation.

`uninstall.sh` retains its separate legacy behavior: it uninstalls uv and
recursively deletes `$HOME/.xray`; it is not an inverse for the selected checkout.

`uv tool install` has no XRAY post-install hook. Install the skill explicitly
for a user or one repository:

```bash
xray skill install --user
xray skill install --project /absolute/path/to/project
```

Both scopes install `xray-cli` below `.agents/skills/`. Matching files are
no-ops; divergent files require explicit `--force`; symlinked targets fail.
On Linux, installation uses pinned descriptor-relative no-follow operations and
no-clobber publication/restoration. Caught race, I/O, or cleanup failures return
errors and may retain private recovery material; interruption is not crash-atomic
and hostile same-UID-writer isolation is not promised.

For a checkout under development:

```bash
uv sync --dev
uv run xray capabilities
uv run xray map . --depth 1 --limit 20
uv run xray read . src/xray/cli.py --line 1 --end-line 2
uv run xray-mcp
```

The package exposes `xray` (`xray.cli:main`) and `xray-mcp`
(`xray.mcp_server:main`).

## CLI reference

The handwritten grammar is:

```text
xray map ROOT [options]
xray find ROOT QUERY [options]
xray interface ROOT TARGET [options]
xray read ROOT TARGET --line 1 [options]
xray search ROOT [options]
xray impact ROOT --ref-json JSON [options]
xray change plan|refine|verify|apply ROOT [options]
xray capabilities [ROOT] [options]
xray skill install --user | --project ROOT [--force]
```

`capabilities` is the only rootless repository form. JSON is the default
semantic output and uses the `xray.v1` envelope; `--format text` is a deliberately
lossy terminal view and `--pretty` changes only JSON indentation. Successful
operations exit `0`; malformed or invalid requests exit `2`; stale, containment,
operational, analysis, resource, and mutation failures exit `1` with typed
error, coverage, and mutation fields.

Common bounded controls include repeated `--path`, `--glob`, and language
filters; `--limit`, `--max-bytes`, `--timeout-seconds`, `--cursor`,
`--cache auto|off`, `--format`, and `--pretty`. Operation-specific controls
are listed by `xray COMMAND --help`; the architecture file records their
invariants. Map depth is `0..64` or explicit `all`.

### Discovery and capture

```bash
xray map "$ROOT" --focus src/xray --depth 2 --context ancestors --limit 100
xray find "$ROOT" XRayIndexer --match name --path src/xray --language python
xray interface "$ROOT" src/xray/cli.py --sections symbols --member-depth 1 --documentation
xray read "$ROOT" src/xray/cli.py --line 1 --end-line 30 --context-lines 2
xray search "$ROOT" --pattern 'raise $E' --lang python --path src/xray --detail detail
xray impact "$ROOT" --ref-json "$symbol" --mode lexical --limit 100
xray capabilities "$ROOT" --detail detail
```

`map` returns namespace entries, not bodies. `find` accepts name, exact, or
fuzzy matching and returns complete references. `interface` accepts one
contained file or exact reference and reports observed syntax, not module
resolution; a declaration includes `disclosure.clipped` when its displayed
signature or documentation was shortened. `read` accepts a location,
source/symbol/occurrence reference, or a JSON batch of one to eight targets.
`impact` uses syntax or explicit lexical name evidence and remains unresolved.
Literal search is exact, case-sensitive UTF-8 text; pattern search requires one
explicit language: Python, JavaScript, TypeScript, or Go. Parser or source
limitations appear in `coverage`, not as a silent query change.

### Contained rule and config search

A standalone rule is a self-contained YAML file supplied with `--rule`:

```yaml
# ROOT/rules/no-foo.yml
id: no-foo-call
language: Python
rule:
  pattern: foo($A)
```

A config supplied with `--config` is one contained YAML document whose complete
top-level mapping is a nonempty `ruleDirs` string list:

```yaml
# ROOT/sgconfig.yml
ruleDirs:
  - rules
```

Config directories are relative to the config file, remain inside `ROOT`, and
must contain rule files. Unknown keys, multiple documents, empty rule sets,
directory input, symlinks, ambient configuration, custom grammars, and external
dependencies are rejected. XRAY does not load ancestor configuration or provide
a rule-development wrapper; use upstream ast-grep for broader authoring.

## Guarded changes

The change lifecycle has one mutation boundary:

1. `change plan` captures one complete `xray.change.v1` artifact.
2. Review the complete JSON plan, every affected-file diff, and every `edit_id`.
3. Optionally `change refine` to select edits or `change verify` to recheck.
4. `change apply` independently validates the artifact and a separate expected
   SHA-256 digest before writing.

Planning, refinement, and verification do not write. Apply repeats guards and
never trusts a previous verify result. A changed source, selection,
configuration, policy, toolchain, candidate set, range, mode, preimage,
postimage, syntax result, or file mode makes a plan stale.

### Pattern plan and apply

```bash
ROOT=/absolute/path/to/repository
xray change plan "$ROOT" \
  --pattern 'foo($A)' --replacement 'bar($A)' --lang python \
  --path src --max-candidates 100 --max-files 20 > plan-response.json
jq -e '.ok == true and .data.plan.plan_schema == "xray.change.v1"' \
  plan-response.json >/dev/null
jq '.data.plan' plan-response.json > plan.json

# Review all affected-file diffs and edit IDs before this command.
EXPECTED_DIGEST=$(jq -r '.plan_digest' plan.json)
xray change apply "$ROOT" --plan-file plan.json \
  --expected-digest "$EXPECTED_DIGEST"
```

Pattern sources require `--pattern`, `--replacement`, and `--lang` (`python`,
`javascript`, `typescript`, or `go`). Rule changes use exactly one of `--rule`
and `--config`, then the same review and apply workflow:

```bash
xray change plan "$ROOT" --rule rules/foo.yml --path sample.js > plan-response.json
# Or: xray change plan "$ROOT" --config sgconfig.yml --path sample.js > plan-response.json
jq '.data.plan' plan-response.json > plan.json
EXPECTED_DIGEST=$(jq -r '.plan_digest' plan.json)
xray change apply "$ROOT" --plan-file plan.json --expected-digest "$EXPECTED_DIGEST"
```

Rule/config files remain contained YAML inputs. Plan bounds include candidate,
file, and complete-artifact byte limits. Only planning accepts dirty-file or
new-parser-error acknowledgements; they become digest-bound plan fields. A
complete plan includes root, selection, input manifest, bounds, edits,
preimages/postimages, diffs, baseline, eligibility, acknowledgements, and
canonical `plan_digest`. `--plan-file -` accepts JSON on standard input.

Refinement emits a new complete plan and digest; edit IDs are unique sorted
values, and an empty selection is explicitly inapplicable. Verify is read-only,
returns `ready: true`, and accepts no acknowledgement override. Apply stages
postimages, checks file modes and preimages immediately before each replacement,
then checks bytes and syntax. Caught failures attempt conflict-preserving
rollback but multi-file apply is not atomic. Errors expose mutation state:
`not_applied`, `rolled_back`, `partially_applied`, or `indeterminate` with the
corresponding rollback status. Interruption, SIGKILL, or power loss can leave
partial files and no JSON result; inspect files and restore a known baseline.
There is no journal or background restoration service.

## MCP usage

XRAY uses FastMCP's standard stdio transport:

```bash
uv run xray-mcp       # source checkout
xray-mcp              # installed tool
```

A client initially sees exactly `search_tools` and `call_tool`. Discover a
complete closed contract, then pass its exact `name` and `arguments` to
`call_tool`:

```python
from fastmcp import Client
from xray.mcp_server import mcp

ROOT = "/absolute/path/to/repository"

async with Client(mcp) as client:
    tools = await client.list_tools()
    assert [tool.name for tool in tools] == ["search_tools", "call_tool"]
    await client.call_tool(
        "search_tools", {"mode": "exact", "query": "search", "max_bytes": 16384}
    )
    result = await client.call_tool(
        "call_tool",
        {
            "name": "search",
            "arguments": {
                "root": ROOT,
                "query": {"source": {"kind": "literal", "text": "TODO"}},
                "page": {"limit": 20, "max_bytes": 16384},
            },
        },
    )
```

Discovery supports `intent`, `exact`, and `catalog` modes. Continue a paged
request with its opaque cursor and unchanged mode/query. Operation arguments
mirror typed CLI requests, but never contain an embedded operation selector or
custom protocol envelope. Tool errors remain typed errors, not empty results.
The operation catalog and mutation classes are the same as the CLI; only
`change_apply` is guarded mutation. Standard resources are:

- `xray://workflow`
- prompt `xray_discovery_plan`
- `skill://xray-progressive-discovery/SKILL.md`
- `skill://xray-progressive-discovery/{path*}`

The MCP guarded lifecycle is `change_plan`, external review, then
`change_apply`; `change_refine` and `change_verify` are optional between them.
A change call carries a complete plan and separate expected digest:

```python
planned = await client.call_tool(
    "call_tool",
    {"name": "change_plan", "arguments": change_plan_arguments},
)
plan = planned.structured_content["data"]["plan"]
digest = plan["plan_digest"]
await client.call_tool(
    "call_tool",
    {
        "name": "change_apply",
        "arguments": {"root": ROOT, "query": {"plan": plan, "expected_digest": digest}},
    },
)
```

Use the complete schema returned by `search_tools`; do not infer omitted fields.

## Supported source and limitations

Source analysis supports Python, JavaScript, TypeScript, and Go. All operations
are bounded by page, byte, target, selection, timeout, or plan controls. Roots
and targets remain contained; cursors and references bind the captured snapshot
and require a fresh request after source changes. Invalid input, unsupported
syntax, containment violations, stale identity, and dependency failures are
typed errors. Non-text or NUL-bearing source is reported through coverage.

Impact is intentionally name-based and unresolved: `name_occurrences` evidence
is not a caller/dependent graph, alias resolver, type system, or semantic rename.
Search reports match evidence and optional verified detail, not behavior or
repository-wide semantic completeness. XRAY does not provide a language server,
type-aware dependency graph, daemon, project database, automatic commits, or
background recovery service. YAML is accepted only as selected rule/config
input and is never product output.

## Package resources

The wheel includes:

- `xray/guidance.md`, used by `xray://workflow`;
- `xray/skills/xray-progressive-discovery/SKILL.md` and its template;
- `xray/agent_skills/xray-cli/SKILL.md` and `agents/openai.yaml`, used by skill
  installation.

The repository skill under `skills/xray-cli/` and packaged copy are byte-
identical. Packaging checks verify resource paths, both console scripts, clean
imports, wheel/sdist metadata, and installed skill files.

## Architecture and development

The [architecture map](ARCHITECTURE.md) records component ownership, dependency
direction, interface invariants, cache and concurrency limits, mutation safety,
package compatibility, test ownership, and synchronized change edges. Product
source and owner tests define observable behavior; examples and audit reports
are not alternate contracts. [`PROJECT.md`](PROJECT.md) lists available
focused, static, packaging, CLI, MCP, and optional broad commands.

For routine Sprint work, select the narrowest checks covering the changed path:

```bash
uv sync --dev
uv run pytest <affected tests>
uv run ruff check <changed paths>
uv run xray <changed operation> <explicit small root>
```

When MCP or shared behavior changes, launch `uv run xray-mcp` as a real
standard-stdio child, initialize it, list the two adapter tools, and call the
changed operation through a throwaway client. An in-process client test or an
idle process does not replace this proof. Run packaging checks for packaging
changes. `uv run pytest`, whole-repository static checks, and `make qualify` are
explicit broad or Enterprise checks, not automatic routine gates.
