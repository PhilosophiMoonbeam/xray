# Example Component Instructions

This filename is not discovered automatically. Copy it to
`<component>/AGENTS.md` only when the component needs closer rules. Root
instructions continue to apply unless this file explicitly overrides them.

## Ownership

- Own `component/src/`, `component/tests/`, and `component/README.md`.
- Change shared contracts only through a root-allocated contract Bead.
- Change generated files only through their generator.

## Commands

Run from `component/`:

```bash
<targeted test command>
<lint command>
<type command>
<build command>
<generated-file cleanliness command>
```

## Invariants

- <public behavior or compatibility rule>
- <identity or authorization rule>
- <storage or migration rule>
- <failure or observability rule>

## Review

- Flag <unsafe behavior> because <impact>; require <safe path>.
- Require <specific test> when <specific behavior> changes.
