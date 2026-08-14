import json
from pathlib import Path

import pytest

from xray import cli
from xray.skill_installer import CLI_SKILL_FILES, install_cli_skill

ROOT = Path(__file__).parents[1]
SOURCE_SKILL = ROOT / "skills" / "xray-cli"


def assert_exact_skill(target: Path) -> None:
    files = {path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()}
    assert files == set(CLI_SKILL_FILES)
    for relative in CLI_SKILL_FILES:
        assert (target / relative).read_bytes() == (SOURCE_SKILL / relative).read_bytes()


def test_user_install_is_exact_and_idempotent(tmp_path):
    first = install_cli_skill(home=tmp_path)
    target = tmp_path / ".agents" / "skills" / "xray-cli"

    assert first.scope == "user"
    assert first.target == str(target)
    assert first.changed is True
    assert first.replaced is False
    assert_exact_skill(target)

    second = install_cli_skill(home=tmp_path)

    assert second.changed is False
    assert second.replaced is False
    assert_exact_skill(target)


def test_divergent_install_requires_force_and_replaces_exactly(tmp_path):
    target = tmp_path / ".agents" / "skills" / "xray-cli"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("local changes", encoding="utf-8")
    (target / "unexpected.txt").write_text("remove me", encoding="utf-8")

    with pytest.raises(ValueError, match=r"differs.*--force"):
        install_cli_skill(home=tmp_path)

    assert (target / "SKILL.md").read_text(encoding="utf-8") == "local changes"
    result = install_cli_skill(home=tmp_path, force=True)

    assert result.changed is True
    assert result.replaced is True
    assert_exact_skill(target)


def test_project_install_rejects_symlinked_agents_directory(tmp_path):
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (project / ".agents").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="must not contain symlinks"):
        install_cli_skill(project_root=project)

    assert list(outside.iterdir()) == []


def test_failed_forced_swap_restores_divergent_target(tmp_path, monkeypatch):
    target = tmp_path / ".agents" / "skills" / "xray-cli"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("keep this", encoding="utf-8")
    original_replace = Path.replace

    def fail_stage_swap(path: Path, destination: Path):
        if path.name.startswith(".xray-skill-stage-") and destination == target:
            raise OSError("simulated swap failure")
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", fail_stage_swap)

    with pytest.raises(OSError, match="simulated swap failure"):
        install_cli_skill(home=tmp_path, force=True)

    assert (target / "SKILL.md").read_text(encoding="utf-8") == "keep this"
    assert not list(target.parent.glob(".xray-skill-*"))


def test_project_cli_installs_exact_skill_and_reports_json(tmp_path, capsys):
    project = tmp_path / "project"
    project.mkdir()

    assert cli.main(["skill", "install", "--project", str(project)]) == 0

    output = json.loads(capsys.readouterr().out)
    target = project / ".agents" / "skills" / "xray-cli"
    assert output == {
        "action": "install",
        "changed": True,
        "command": "skill",
        "files": ["SKILL.md", "agents/openai.yaml"],
        "ok": True,
        "replaced": False,
        "schema_version": "xray.cli.v1",
        "scope": "project",
        "target": str(target),
        "warnings": [],
    }
    assert_exact_skill(target)


def test_project_cli_reports_divergence_as_validation_error(tmp_path, capsys):
    project = tmp_path / "project"
    target = project / ".agents" / "skills" / "xray-cli"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("local changes", encoding="utf-8")

    assert cli.main(["skill", "install", "--project", str(project)]) == 2

    error = json.loads(capsys.readouterr().err)
    assert error["command"] == "skill"
    assert "--force" in error["error"]
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "local changes"
