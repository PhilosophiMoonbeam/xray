# Agent Instructions

## Beads

This repo uses Beads for durable task tracking. Use the `beads` skill and `bd prime` for current workflow context.

## Skills and Delegation

Use the `find-docs` skill (Context7 / `ctx7`) whenever work depends on current library, framework, SDK, CLI, cloud, or version-specific behavior. Use the `playwright-cli` skill for browser automation, UI inspection, interaction tests, screenshots, console/network checks, and Playwright verification.

Prefer dynamic subagents for nontrivial work that can be split into independent research, verification, or disjoint implementation scopes. Give each subagent clear ownership and integrate results without creating overlapping write sets.

## GitHub CLI

When GitHub remote operations are in scope and authorized, prefer `gh` for PRs, reviews, Actions, releases, repo metadata, and GitHub issues. Use `git` for local repository state. Do not commit, push, merge, or mutate remotes unless explicitly instructed.

## Python

Use `uv` for all Python-related commands, including running modules, scripts, tests, package installs, and temporary tool dependencies. Prefer forms such as `uv run python ...`, `uv run pytest`, `uv run --with pytest pytest`, and `uv tool install ...`.

## Non-Interactive Shell Commands

**ALWAYS use non-interactive flags** with file operations to avoid hanging on confirmation prompts.

Shell commands like `cp`, `mv`, and `rm` may be aliased to include `-i` (interactive) mode on some systems, causing the agent to hang indefinitely waiting for y/n input.

**Use these forms instead:**
```bash
# Force overwrite without prompting
cp -f source dest           # NOT: cp source dest
mv -f source dest           # NOT: mv source dest
rm -f file                  # NOT: rm file

# For recursive operations
rm -rf directory            # NOT: rm -r directory
cp -rf source dest          # NOT: cp -r source dest
```

**Other commands that may prompt:**
- `scp` - use `-o BatchMode=yes` for non-interactive
- `ssh` - use `-o BatchMode=yes` to fail instead of prompting
- `apt-get` - use `-y` flag
- `brew` - use `HOMEBREW_NO_AUTO_UPDATE=1` env var
