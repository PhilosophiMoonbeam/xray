"""Safe installation of XRAY's bundled shell-agent skill."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path
from uuid import uuid4

CLI_SKILL_NAME = "xray-cli"
CLI_SKILL_FILES = ("SKILL.md", "agents/openai.yaml")


class SkillInstallError(RuntimeError):
    """Operational failure after a skill installation was requested."""


@dataclass(frozen=True)
class SkillInstallResult:
    """Machine-readable result for one skill installation."""

    scope: str
    target: str
    changed: bool
    replaced: bool
    files: tuple[str, ...] = CLI_SKILL_FILES

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _bundled_files() -> dict[str, bytes]:
    root = resources.files("xray").joinpath("agent_skills").joinpath(CLI_SKILL_NAME)
    bundled: dict[str, bytes] = {}
    for relative in CLI_SKILL_FILES:
        resource = root
        for component in Path(relative).parts:
            resource = resource.joinpath(component)
        if not resource.is_file():
            raise RuntimeError(f"bundled skill is incomplete: missing {relative}")
        bundled[relative] = resource.read_bytes()
    return bundled


def _existing_directory(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {path}")
    if not path.exists():
        raise ValueError(f"{label} does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"{label} is not a directory: {path}")
    return path.resolve(strict=True)


def _reject_symlink_components(root: Path, components: tuple[str, ...]) -> None:
    current = root
    for component in components:
        current /= component
        if current.is_symlink():
            raise ValueError(f"skill install path must not contain symlinks: {current}")
        if current.exists() and not current.is_dir():
            raise ValueError(f"skill install path component is not a directory: {current}")


def _target_matches(target: Path, bundled: dict[str, bytes]) -> bool:
    allowed_directories = {Path(relative).parent.as_posix() for relative in CLI_SKILL_FILES}
    allowed_directories.discard(".")
    seen_files: set[str] = set()
    seen_directories: set[str] = set()
    for candidate in target.rglob("*"):
        relative = candidate.relative_to(target).as_posix()
        if candidate.is_symlink():
            raise ValueError(f"installed skill must not contain symlinks: {candidate}")
        if candidate.is_dir():
            seen_directories.add(relative)
        elif candidate.is_file():
            seen_files.add(relative)
        else:
            return False
    if seen_files != set(bundled) or seen_directories != allowed_directories:
        return False
    return all((target / relative).read_bytes() == content for relative, content in bundled.items())


def _stage_skill(parent: Path, bundled: dict[str, bytes]) -> Path:
    stage = Path(tempfile.mkdtemp(prefix=".xray-skill-stage-", dir=parent))
    for relative, content in bundled.items():
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    return stage


def install_cli_skill(
    *,
    project_root: str | Path | None = None,
    home: str | Path | None = None,
    force: bool = False,
) -> SkillInstallResult:
    """Install the bundled CLI skill user-wide or below one project root."""
    if project_root is None:
        root = _existing_directory(Path.home() if home is None else Path(home).expanduser(), "user home")
        scope = "user"
    else:
        if home is not None:
            raise ValueError("home cannot be combined with project_root")
        root = _existing_directory(Path(project_root).expanduser(), "project root")
        scope = "project"

    components = (".agents", "skills", CLI_SKILL_NAME)
    _reject_symlink_components(root, components)
    parent = root.joinpath(*components[:-1])
    target = parent / CLI_SKILL_NAME
    parent.mkdir(parents=True, exist_ok=True)
    if parent.resolve(strict=True) != parent:
        raise ValueError(f"skill install parent escaped its root: {parent}")

    bundled = _bundled_files()
    if target.exists():
        if not target.is_dir():
            raise ValueError(f"skill target is not a directory: {target}")
        if _target_matches(target, bundled):
            return SkillInstallResult(scope=scope, target=str(target), changed=False, replaced=False)
        if not force:
            raise ValueError(f"skill target differs from the bundled skill; review it or rerun with --force: {target}")

    stage = _stage_skill(parent, bundled)
    backup: Path | None = None
    installed_stage = False
    replaced = target.exists()
    try:
        if replaced:
            backup = parent / f".xray-skill-backup-{uuid4().hex}"
            target.replace(backup)
        stage.replace(target)
        installed_stage = True
    except Exception:
        if installed_stage and target.exists():
            shutil.rmtree(target)
        if backup is not None and backup.exists():
            backup.replace(target)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)

    if backup is not None:
        shutil.rmtree(backup)
    return SkillInstallResult(scope=scope, target=str(target), changed=True, replaced=replaced)
