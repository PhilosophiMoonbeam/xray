from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from xray import skill_installer
from xray.skill_installer import CLI_SKILL_FILES, install_cli_skill

ROOT = Path(__file__).parents[1]
SOURCE_SKILL = ROOT / "skills" / "xray-cli"


def run_cli(*arguments: object, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    child_env = os.environ.copy()
    source_path = str(ROOT / "src")
    child_env["PYTHONPATH"] = source_path + os.pathsep + child_env.get("PYTHONPATH", "")
    if env:
        child_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "xray.cli", *(str(argument) for argument in arguments)],
        cwd=ROOT,
        env=child_env,
        text=True,
        capture_output=True,
        check=False,
    )


def assert_exact_skill(target: Path) -> None:
    files = {path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()}
    assert files == set(CLI_SKILL_FILES)
    for relative in CLI_SKILL_FILES:
        assert (target / relative).read_bytes() == (SOURCE_SKILL / relative).read_bytes()


def test_user_install_is_exact_and_idempotent(tmp_path: Path) -> None:
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


def test_divergent_install_requires_force_and_replaces_exactly(tmp_path: Path) -> None:
    target = tmp_path / ".agents" / "skills" / "xray-cli"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("local changes", encoding="utf-8")
    (target / "unexpected.txt").write_text("remove me", encoding="utf-8")

    with pytest.raises(ValueError, match=r"differs.*--force"):
        install_cli_skill(home=tmp_path)
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "local changes"

    result = install_cli_skill(home=tmp_path, force=True)
    assert result.changed is True and result.replaced is True
    assert_exact_skill(target)


def test_project_install_rejects_symlinked_destination_components(tmp_path: Path) -> None:
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (project / ".agents").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="must not contain symlinks"):
        install_cli_skill(project_root=project)
    assert list(outside.iterdir()) == []


def test_project_cli_returns_closed_administrative_success(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    result = run_cli("skill", "install", "--project", project)
    assert result.returncode == 0
    assert result.stderr == ""
    value = json.loads(result.stdout)
    target = project / ".agents" / "skills" / "xray-cli"
    assert value == {
        "data": {
            "changed": True,
            "files": ["SKILL.md", "agents/openai.yaml"],
            "replaced": False,
            "scope": "project",
            "target": str(target),
        },
        "ok": True,
        "op": "skill_install",
        "schema": "xray.v1",
    }
    assert_exact_skill(target)

    repeated = run_cli("skill", "install", "--project", project)
    assert repeated.returncode == 0
    repeated_value = json.loads(repeated.stdout)
    assert repeated_value["data"]["changed"] is False
    assert repeated_value["data"]["replaced"] is False


def test_project_cli_maps_divergence_to_shared_invalid_request_error(tmp_path: Path) -> None:
    project = tmp_path / "project"
    target = project / ".agents" / "skills" / "xray-cli"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("local changes", encoding="utf-8")

    result = run_cli("skill", "install", "--project", project)

    assert result.returncode == 2
    assert result.stderr == ""
    value = json.loads(result.stdout)
    assert value["schema"] == "xray.v1"
    assert value["ok"] is False
    assert value["op"] == "skill_install"
    assert value["error"]["code"] == "invalid_request"
    assert "--force" in value["error"]["message"]
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "local changes"


def test_skill_install_rejects_removed_or_extra_forms() -> None:
    removed = run_cli("skill", "remove")
    extra = run_cli("skill", "install", "--format", "text")

    assert removed.returncode == 2
    assert json.loads(removed.stdout)["error"]["code"] == "invalid_request"
    assert extra.returncode == 2
    assert json.loads(extra.stdout)["error"]["code"] == "invalid_request"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO support is required")
def test_special_file_is_not_opened_during_divergence_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / ".agents" / "skills" / "xray-cli"
    target.mkdir(parents=True)
    os.mkfifo(target / "SKILL.md")

    real_open = skill_installer.os.open

    def observe_open(path: Any, *args: Any, **kwargs: Any) -> int:
        if path == "SKILL.md" and kwargs.get("dir_fd") is not None:
            raise AssertionError("inspection opened a special file")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(skill_installer.os, "open", observe_open)
    with pytest.raises(ValueError, match=r"differs.*--force"):
        install_cli_skill(home=tmp_path)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO support is required")
def test_force_replacement_removes_special_entries_without_opening_them(tmp_path: Path) -> None:
    target = tmp_path / ".agents" / "skills" / "xray-cli"
    target.mkdir(parents=True)
    os.mkfifo(target / "SKILL.md")

    result = install_cli_skill(home=tmp_path, force=True)

    assert result.changed is True
    assert result.replaced is True
    assert_exact_skill(target)


def test_publication_no_replace_preserves_competing_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_rename = skill_installer._rename_noreplace
    competed = False

    def compete(source_fd: int, source_name: str, destination_fd: int, destination_name: str) -> None:
        nonlocal competed
        if source_name == "stage" and destination_name == "xray-cli" and not competed:
            competitor = tmp_path / ".agents" / "skills" / "xray-cli"
            competitor.mkdir()
            (competitor / "keep.txt").write_text("competitor", encoding="utf-8")
            competed = True
        real_rename(source_fd, source_name, destination_fd, destination_name)

    monkeypatch.setattr(skill_installer, "_rename_noreplace", compete)
    with pytest.raises(OSError):
        install_cli_skill(home=tmp_path)

    competitor = tmp_path / ".agents" / "skills" / "xray-cli"
    assert (competitor / "keep.txt").read_text(encoding="utf-8") == "competitor"
    assert not list((tmp_path / ".agents" / "skills").glob(".xray-skill-stage-*"))


def test_publish_failure_restores_the_complete_original_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / ".agents" / "skills" / "xray-cli"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("original", encoding="utf-8")
    (target / "unexpected.txt").write_text("preserve", encoding="utf-8")
    before = {path.relative_to(target).as_posix(): path.read_bytes() for path in target.rglob("*") if path.is_file()}
    real_rename = skill_installer._rename_noreplace

    def fail_publish(source_fd: int, source_name: str, destination_fd: int, destination_name: str) -> None:
        if source_name == "stage" and destination_name == "xray-cli":
            raise OSError(errno.EIO, "injected publication failure")
        real_rename(source_fd, source_name, destination_fd, destination_name)

    monkeypatch.setattr(skill_installer, "_rename_noreplace", fail_publish)
    with pytest.raises(OSError):
        install_cli_skill(home=tmp_path, force=True)

    after = {path.relative_to(target).as_posix(): path.read_bytes() for path in target.rglob("*") if path.is_file()}
    assert after == before
    assert not list((tmp_path / ".agents" / "skills").glob(".xray-skill-stage-*"))


def test_staging_write_failure_leaves_divergent_target_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / ".agents" / "skills" / "xray-cli"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("original", encoding="utf-8")

    def fail_write(descriptor: int, content: object) -> int:
        del descriptor, content
        raise OSError(errno.EIO, "injected staging failure")

    monkeypatch.setattr(skill_installer.os, "write", fail_write)
    with pytest.raises(OSError, match="staging"):
        install_cli_skill(home=tmp_path, force=True)

    assert (target / "SKILL.md").read_text(encoding="utf-8") == "original"
    assert not list((tmp_path / ".agents" / "skills").glob(".xray-skill-stage-*"))


def test_cleanup_failure_reports_installed_target_and_retains_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_cleanup = skill_installer._cleanup_tree

    def fail_workspace_cleanup(parent_fd: int, name: str, snapshot: Any = None) -> None:
        if name.startswith(".xray-skill-stage-"):
            raise OSError(errno.EIO, "injected cleanup failure")
        real_cleanup(parent_fd, name, snapshot)

    monkeypatch.setattr(skill_installer, "_cleanup_tree", fail_workspace_cleanup)
    with pytest.raises(OSError, match=r"installed.*cleanup"):
        install_cli_skill(home=tmp_path)

    target = tmp_path / ".agents" / "skills" / "xray-cli"
    assert_exact_skill(target)
    assert list((tmp_path / ".agents" / "skills").glob(".xray-skill-stage-*"))


def test_parent_substitution_before_publication_does_not_touch_outside_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel.txt").write_text("unchanged", encoding="utf-8")
    real_rename = skill_installer._rename_noreplace
    swapped = False

    visible = tmp_path / ".agents"
    hidden = tmp_path / ".agents-hidden"

    def swap_parent(source_fd: int, source_name: str, destination_fd: int, destination_name: str) -> None:
        nonlocal swapped
        if source_name == "stage" and destination_name == "xray-cli" and not swapped:
            visible.rename(hidden)
            visible.symlink_to(outside, target_is_directory=True)
            swapped = True
        real_rename(source_fd, source_name, destination_fd, destination_name)

    monkeypatch.setattr(skill_installer, "_rename_noreplace", swap_parent)
    with pytest.raises(OSError):
        install_cli_skill(home=tmp_path)

    assert visible.is_symlink()
    assert (outside / "sentinel.txt").read_text(encoding="utf-8") == "unchanged"
    assert not (outside / "skills").exists()


def test_target_bound_is_rejected_before_destination_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    huge_root = Path("/" + "r" * 4095)
    monkeypatch.setattr(skill_installer, "_existing_directory", lambda path, label: huge_root)
    real_mkdir = skill_installer.os.mkdir
    mkdir_calls = 0

    def observe_mkdir(*args: Any, **kwargs: Any) -> Any:
        nonlocal mkdir_calls
        mkdir_calls += 1
        return real_mkdir(*args, **kwargs)

    monkeypatch.setattr(skill_installer.os, "mkdir", observe_mkdir)
    with pytest.raises(ValueError, match="4096"):
        install_cli_skill(home=tmp_path)

    assert mkdir_calls == 0


def test_target_substitution_during_cleanup_cannot_report_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel.txt").write_text("unchanged", encoding="utf-8")
    visible_target = tmp_path / ".agents" / "skills" / "xray-cli"
    real_cleanup = skill_installer._cleanup_tree
    swapped = False

    def swap_target(parent_fd: int, name: str, snapshot: Any = None) -> None:
        nonlocal swapped
        if name.startswith(".xray-skill-stage-") and not swapped:
            old_target = visible_target.with_name("installed-before-race")
            visible_target.rename(old_target)
            visible_target.symlink_to(outside, target_is_directory=True)
            swapped = True
        real_cleanup(parent_fd, name, snapshot)

    monkeypatch.setattr(skill_installer, "_cleanup_tree", swap_target)
    with pytest.raises(OSError, match=r"installed.*cleanup"):
        install_cli_skill(home=tmp_path)

    assert visible_target.is_symlink()
    assert (outside / "sentinel.txt").read_text(encoding="utf-8") == "unchanged"
