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
	uv run pytest tests/test_mcp_compact.py tests/test_cli.py::test_package_scripts_keep_mcp_and_add_cli tests/test_cli.py::test_mcp_tool_surface_is_search_first_with_compact_metadata tests/test_cli.py::test_mcp_workflow_guidance_is_available_on_demand
	uv run xray --version && uv run xray explore . --max-depth 1

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
