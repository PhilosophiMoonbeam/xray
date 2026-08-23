# XRAY 0.11.3 Agent-First Shakedown Handoff

## Outcome

This report converts an installed-product shakedown against FastMS365 into
bounded XRAY repair recommendations. It separates confirmed contract defects
from agent-facing design issues that require an explicit product decision.

The shakedown exercised XRAY `0.11.3` at FastMS365 Git SHA
`7521253ede147b8d30896307cca969053b38f051`. Source inspection for this handoff
used XRAY Git SHA `7c5f7d0146ab4dfe99aba0dc164368ae5f4fc391`.

No FastMS365 product defect was confirmed. Temporary replacement fixtures were
removed, and the FastMS365 worktree was clean after the run.

## Recommended implementation order

1. Correct CLI exit classification for invalid ast-grep input.
2. Freeze and implement exact-class interface semantics.
3. Add an unambiguous rollback state to compact v3 and MCP output.
4. Correct exact-symbol legacy-projection error messages.
5. Make interface warnings page-relevant.
6. Make rule-scan selection visible and controllable.
7. Synchronize both CLI skills, public documentation, capabilities, and tests.

Items 1 and 4 are adapter repairs. Items 2, 3, 5, and 6 change public
semantics or output and require synchronized contract decisions before
implementation.

## 1. Invalid ast-grep input uses the wrong exit class

Priority: P1. This breaks scripts and agents that distinguish invalid requests
from operational failures through XRAY's documented exit classes.

### Evidence

The public contract states:

```text
0 = success
1 = command failure
2 = parse or validation failure
```

Both of these invalid inputs emitted a typed ast-grep parse diagnostic but
exited `1`:

```bash
uv run xray search ROOT -p 'except Exception: pass' -l python --path src --limit 20
uv run xray rules check ROOT --rule PATH_TO_CONTAINED_NON_YAML_FILE
```

The first response reported `Cannot parse query as a valid pattern`. The second
reported `Fail to parse yaml as RuleConfig`.

`src/xray/cli.py::main` maps every `AstGrepError` to exit `1`. The ast-grep
boundary does not preserve whether the subprocess failure represents invalid
caller input or an execution/runtime failure.

### Recommendation

Introduce a typed validation failure at `src/xray/core/ast_grep.py`, such as an
`AstGrepValidationError` subclass or an error category carried by
`AstGrepError`. Classify invalid pattern, invalid rule, and invalid test
configuration failures as validation errors. Preserve exit `1` for missing
executables, timeouts, output-bound failures, I/O failures, and unexpected
subprocess failures.

Map the validation subtype to:

```json
{
  "ok": false,
  "error": {
    "code": "invalid_request",
    "message": "..."
  }
}
```

and CLI exit `2`. If a more specific stable error code is preferred, define it
once in the public contract and use it consistently across search and rule
commands.

Do not classify failures only by matching English stderr fragments in the CLI
adapter. Normalize ast-grep exit evidence at the subprocess boundary and add
fixtures for the installed ast-grep version's invalid-input results.

### Acceptance evidence

- Invalid structural pattern exits `2` with compact v3, compact v2, and text
  output.
- Invalid rule YAML exits `2` for `rules check` and `rules explain`.
- Missing ast-grep, timeout, and output-bound failures continue to exit `1`.
- MCP returns `isError: true` with the same normalized error category.
- `capabilities` and both CLI skills describe the implemented exit taxonomy.

Primary paths: `src/xray/core/ast_grep.py`, `src/xray/cli.py`,
`src/xray/mcp_server.py`, `tests/test_ast_grep.py`, `tests/test_cli.py`, and
rule-command tests.

## 2. Exact class handoff discards the class interface

Priority: P2. The result is internally consistent with the current 0.11.3
contract, but it is surprising for an agent following the packaged skill's
`find -> interface` handoff.

### Evidence

Reproduction against FastMS365:

```bash
uv run xray find . MicrosoftGraphService --limit 1 \
  | jq -c '.symbols[0]' \
  | uv run xray interface . --symbol-file - --member-depth 2 --max-members 50
```

The command exited `0` and returned:

```json
{
  "exact_symbol_selected": true,
  "completeness": {"complete": true, "reasons": []},
  "symbols": [{"name": "MicrosoftGraphService", "members": []}]
}
```

File/name interface selection found 32 members for the same class.

The cause is explicit in
`src/xray/core/indexer.py::XRayIndexer.read_interface_structured`:
`select_member` returns every directly matched item with `members: []`.
Current architecture says exact-symbol input selects only the found symbol's
owner/member path, so this is a product-design issue rather than an accidental
regression.

### Recommendation

Freeze the following semantics:

- An exact top-level container symbol, such as a class, interface, or struct,
  returns that container with members bounded by `member_depth` and
  `max_members`.
- An exact member returns only its owner path and selected member. It does not
  expose sibling members.
- An exact non-container top-level symbol returns that symbol without invented
  children.
- Completeness reflects member and depth truncation for an exact container.

This preserves the privacy and token benefit of exact member selection while
making exact class selection useful for interface discovery.

If the current semantics must remain, update both skills immediately to direct
agents to file/name interface selection for class outlines and reserve exact
handoffs for member selection. Do not continue reporting an empty exact class
as complete without explaining that the class body was intentionally omitted.

### Acceptance evidence

- Exact Python class selection returns bounded direct methods and fields.
- Exact JavaScript/TypeScript class and Go container selection follow the same
  container rule where the inventory exposes members.
- Exact method selection returns its owner chain and no siblings.
- `max_members=0`, depth limits, and pagination report truthful completeness.
- CLI compact v3 and MCP structured interface have equivalent semantics.
- v2 and full/v1 behavior changes only if explicitly authorized.

Primary paths: `src/xray/core/indexer.py`, `src/xray/cli.py`,
`src/xray/mcp_server.py`, `src/xray/presentation.py`, `tests/test_cli.py`,
`tests/test_mcp_compact.py`, `README.md`, and both CLI skill copies.

## 3. Rollback output represents “not attempted” as success

Priority: P2. A successful apply currently returns the misleading pair
`rollback_attempted: false` and `rollback_succeeded: true`.

### Evidence

The guarded one-edit apply returned:

```json
{
  "rollback_attempted": false,
  "rollback_count": 0,
  "rollback_succeeded": true
}
```

`src/xray/core/indexer.py::_apply_prepared_replacement` hard-codes this result
on success. Capabilities and skills tell agents to branch on
`rollback_attempted` first, which prevents a correctness error only when the
agent remembers the special interpretation.

The architecture explicitly preserves the legacy Boolean, so changing it
directly requires a compatibility decision.

### Recommendation

Add a single authoritative state in compact v3 and MCP results:

```json
{"rollback_status": "not_attempted"}
```

The allowed values should be `not_attempted`, `succeeded`, and `failed`.
Derive `rollback_attempted`, `rollback_succeeded`, and `rollback_count` from
the same internal result rather than constructing partially independent fields.

Retain the legacy Boolean fields in projections that require compatibility.
For compact v3, either retain them temporarily beside `rollback_status` with a
documented removal boundary or authorize `rollback_succeeded: null` when no
attempt occurred. Do not change `true` to `false`; both Boolean values imply an
attempt when read without the companion field.

### Acceptance evidence

- Successful apply reports `rollback_status: not_attempted`.
- Failure before the first replacement reports `not_attempted`.
- Successful restoration after partial replacement reports `succeeded`.
- Incomplete restoration reports `failed` with exact counts and paths.
- CLI and MCP outputs share the same enum and derived legacy values.
- Capabilities describe the enum and remove the need for interpretation-order
  metadata once compatibility permits.

Primary paths: `src/xray/core/indexer.py`, `src/xray/models.py`,
`src/xray/presentation.py`, `src/xray/cli.py`, `src/xray/mcp_server.py`,
`tests/test_structural_commands.py`, `tests/test_cli.py`, and MCP tests.

## 4. Exact-symbol full-detail errors identify the wrong option

Priority: P3. This is an adapter message defect that increases recovery cost.

### Evidence

An exact-symbol `interface --detail full` request exits `2` with:

```text
Exact-symbol interface selection is unavailable with --schema v2.
```

The caller selected `--detail full`; the error envelope uses the full/v1 schema.
`src/xray/cli.py::handle_interface` combines `args.detail == "full"` and
`args.schema != "v3"` under one hard-coded schema-v2 message.

### Recommendation

Report the actual incompatible projection:

- `--detail full`: exact-symbol selection is unavailable in the full/v1
  interface projection; use compact v3 or select a file.
- `--schema v2`: exact-symbol selection is unavailable in compact v2; use
  compact v3 or select a file.

Reject contradictory option combinations during argument validation when
possible, before repository indexing begins.

### Acceptance evidence

- Each unsupported projection names the option the caller supplied.
- Compact JSON keeps exit `2`, `invalid_request`, the leaf command, and a
  specific recovery action.
- Tests cover `--detail full`, `--schema v2`, and combined options.

Primary paths: `src/xray/cli.py` and `tests/test_cli.py`.

## 5. Interface continuation repeats warnings for other pages

Priority: P3. The behavior is truthful at file scope but noisy and ambiguous at
page scope.

### Evidence

Page two of a bounded interface request repeated member-truncation warnings for
symbols from page one and later pages. The CLI computes and bounds all symbols
inside `read_interface_structured`, then paginates them in
`src/xray/cli.py::handle_interface`. The warnings remain global after the
symbol page changes.

### Recommendation

Separate page-local completeness from file-wide inspection metadata. Preferred
v3 shape:

```json
{
  "completeness": {
    "complete": false,
    "reasons": ["page_truncated", "member_truncated"]
  },
  "warnings": ["Members for 'CurrentPageClass' truncated at 3 of 8."],
  "global_warnings": ["Additional symbols have bounded members on other pages."]
}
```

If adding `global_warnings` is too costly, retain only warnings whose symbol is
present on the returned page and add one aggregate warning for omitted pages.
Do not parse symbol names back out of English warning strings in presentation;
carry typed warning metadata from the indexer.

### Acceptance evidence

- Page warnings cite only returned symbols.
- Completeness remains false when omitted pages contain bounded members.
- Changing the positive page size does not duplicate or lose warnings.
- CLI and MCP use the same typed warning projection.

Primary paths: `src/xray/core/indexer.py`, `src/xray/presentation.py`,
`src/xray/cli.py`, `src/xray/mcp_server.py`, and pagination tests.

## 6. Rule scans silently omit hidden paths

Priority: P3. The observed behavior can hide test fixtures or policy files from
an agent without exposing the selection rule.

### Evidence

`rules check` returned zero matches for a valid rule whose only target was in a
hidden `.xray-shakedown/` directory. An explicitly scoped structural search of
that directory returned both matches. Moving the same fixture to visible
`xray_shakedown/` made `rules check` return both matches.

This may be inherited ast-grep selection rather than an XRAY engine defect, but
XRAY currently does not report the exclusion or offer a rule-check scope that
makes the difference obvious.

### Recommendation

First freeze whether rule commands follow repository ignore policy, ast-grep
defaults, or explicit XRAY path scopes. Then choose one of these agent-visible
contracts:

1. Add repeatable contained `--path` and `--glob` scopes to `rules check` and
   the corresponding MCP tool, including an explicit hidden-path policy.
2. Preserve whole-root scanning but report effective selection/exclusion policy
   in compact output and `rules explain`.

The first option is more composable and aligns rule inspection with structural
search and guarded replacement. Whichever option is chosen, explicit contained
hidden paths should either scan or fail with a precise unsupported-selection
error; zero matches should not conceal the decision.

### Acceptance evidence

- Visible and hidden fixture behavior is covered in Git and non-Git roots.
- Explicit contained scope has deterministic behavior.
- Parent traversal and symlink escapes remain rejected.
- `rules check`, `rules explain`, MCP rule tools, documentation, and skills
  describe the same selection policy.

Primary paths: `src/xray/core/indexer.py`, `src/xray/core/ast_grep.py`,
`src/xray/cli.py`, `src/xray/mcp_server.py`, rule tests, `README.md`, and both
CLI skills.

## Skill and documentation synchronization

The repository skill at `skills/xray-cli/` and the distributable copy at
`src/xray/agent_skills/xray-cli/` must remain byte-identical. After product
repairs:

- state the implemented exit classification;
- explain exact container versus exact member interface behavior;
- teach `rollback_status` as the primary field if adopted;
- describe effective rule scopes and hidden-path behavior; and
- keep JSON and `jq` workflows unchanged.

Update the packaged MCP progressive-discovery skill when shared semantics or
MCP result interpretation changes. Packaging tests should continue proving
that the installed CLI skill matches the repository copy.

## Proposed work decomposition

Use one frozen design decision before concurrent implementation because exact
interface semantics, rollback compatibility, typed warnings, and rule scopes
move public contracts.

After that decision, the work can be split into dependency-ordered leaves:

1. Ast-grep error taxonomy and CLI/MCP exit/error mapping.
2. Exact interface selection and typed completeness warnings.
3. Rollback result model and projections.
4. Rule selection/scoping contract.
5. Synchronized README, capabilities, and skill updates.
6. Fixed-artifact counterexample review after deterministic gates.

Do not split tests from their owning behavior repairs. Each implementation leaf
should include focused regression tests and its affected documentation edge.

## Required verification

Run focused tests while implementing, then qualify one unchanged final
artifact with:

```bash
uv run pytest tests/test_models.py tests/test_ast_grep.py
uv run pytest tests/test_cli.py tests/test_structural_commands.py
uv run pytest tests/test_mcp_compact.py
uv run pytest tests/test_packaging.py
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run vulture
uv run pytest
uv build
uv run xray --version
uv run xray explore . --max-depth 1
git diff --check
git status --porcelain=v1 --untracked-files=all
```

The final status may contain this explicitly requested untracked handoff until
the receiving agent removes or archives it. No report result authorizes commit,
push, merge, release, publication, or Beads synchronization.
