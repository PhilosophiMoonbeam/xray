.PHONY: setup validate-fast validate-static validate-full validate-package validate-smoke validate-cleanliness validate-product validate-agent-config codex-doctor validate-agent-recipe validate-harness validate-project-readiness validate qualify clean-checkout

.NOTPARALLEL:

setup:
	uv sync --dev

validate-fast:
	uv run pytest tests/test_models.py tests/test_ast_grep.py

validate-static:
	uv run ruff format --check .
	uv run ruff check .
	uv run pyright
	uv run vulture

validate-full:
	uv run pytest

validate-package:
	uv run pytest tests/test_packaging.py
	uv build

validate-smoke:
	uv run pytest tests/test_mcp_compact.py::test_standard_tools_list_has_exactly_two_raw_adapter_tools tests/test_mcp_compact.py::test_discovery_publishes_complete_enabled_contract_and_seek_cursor tests/test_cli.py::test_help_and_version_are_handwritten_surfaces tests/test_cli.py::test_removed_commands_are_not_legacy_aliases tests/test_cli.py::test_removed_discovery_options_reject
	uv run xray --version && uv run xray map . --depth 1

validate-cleanliness:
	git diff --check && git status --porcelain=v1 --untracked-files=all

validate-product: validate-fast validate-static validate-full validate-package validate-smoke

validate-agent-config:
	uv run python .codex/session_start.py --self-test
	uv run python .codex/validate_agents.py --self-test
	uv run python .codex/validate_agents.py

codex-doctor:
	codex --strict-config doctor --summary --no-color

validate-agent-recipe: validate-agent-config codex-doctor
	git diff --check

validate-harness: validate-agent-recipe

validate-project-readiness:
	uv run python .codex/validate_project_readiness.py

validate: validate-product validate-harness validate-cleanliness

qualify: validate validate-project-readiness

clean-checkout: setup qualify
