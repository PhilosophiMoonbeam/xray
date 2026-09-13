import importlib.metadata
import importlib.resources
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
EXPECTED_VERSION = "1.0.0"
CLI_SKILL_FILES = (Path("SKILL.md"), Path("agents/openai.yaml"))
RESOURCE_FILES = (
    Path("guidance.md"),
    Path("skills/xray-progressive-discovery/SKILL.md"),
    Path("agent_skills/xray-cli/SKILL.md"),
    Path("agent_skills/xray-cli/agents/openai.yaml"),
)


def _read_package_resource(relative: Path) -> bytes:
    resource = importlib.resources.files("xray")
    for component in relative.parts:
        resource = resource.joinpath(component)
    return resource.read_bytes()


def _build_wheel(output_dir: Path) -> Path:
    output_dir.mkdir()
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(output_dir), str(ROOT)],
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = tuple(output_dir.glob("*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def _build_sdist(output_dir: Path) -> Path:
    output_dir.mkdir()
    subprocess.run(
        ["uv", "build", "--sdist", "--out-dir", str(output_dir), str(ROOT)],
        check=True,
        capture_output=True,
        text=True,
    )
    sdists = tuple(output_dir.glob("*.tar.gz"))
    assert len(sdists) == 1
    return sdists[0]


def _assert_current_guidance(guidance: bytes) -> None:
    text = guidance.decode("utf-8")
    assert "xray.v1" in text
    assert "xray.change.v1" in text
    for removed in (
        "explore_repo",
        "find_symbol",
        "read_symbol",
        "symbol_at",
        "scan_rules",
        "rewrite_pattern",
        "plan_replacement",
        "xray.cli.v2",
        "xray.replace.v2",
        "lsp_config.json",
    ):
        assert removed not in text


def test_importable_package_resources_are_complete():
    package_root = importlib.resources.files("xray")
    for relative in RESOURCE_FILES:
        resource = package_root
        for component in relative.parts:
            resource = resource.joinpath(component)
        assert resource.is_file(), relative
        assert resource.read_bytes(), relative


def test_repository_and_packaged_cli_skill_are_byte_identical():
    repository_root = ROOT / "skills" / "xray-cli"
    packaged_root = ROOT / "src" / "xray" / "agent_skills" / "xray-cli"

    repository_files = {path.relative_to(repository_root) for path in repository_root.rglob("*") if path.is_file()}
    packaged_files = {path.relative_to(packaged_root) for path in packaged_root.rglob("*") if path.is_file()}
    assert repository_files == packaged_files == set(CLI_SKILL_FILES)

    for relative in CLI_SKILL_FILES:
        assert (repository_root / relative).read_bytes() == (packaged_root / relative).read_bytes()


def test_built_wheel_and_sdist_publish_release_metadata_and_current_assets(tmp_path: Path):
    assert importlib.metadata.version("xray") == EXPECTED_VERSION
    wheel = _build_wheel(tmp_path / "wheel")
    sdist = _build_sdist(tmp_path / "sdist")
    assert wheel.name.startswith(f"xray-{EXPECTED_VERSION}-")
    assert sdist.name.startswith(f"xray-{EXPECTED_VERSION}.")

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        entry_points_name = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        metadata = archive.read(metadata_name).decode("utf-8")
        entry_points = archive.read(entry_points_name).decode("utf-8")
        assert f"\nVersion: {EXPECTED_VERSION}\n" in metadata
        assert "xray = xray.cli:main" in entry_points
        assert "xray-mcp = xray.mcp_server:main" in entry_points
        assert not any(name.endswith("lsp_config.json") for name in names)
        _assert_current_guidance(archive.read("xray/guidance.md"))

    with tarfile.open(sdist, "r:gz") as archive:
        names = set(archive.getnames())
        assert not any(name.endswith("src/xray/lsp_config.json") for name in names)
        pyproject_name = next(name for name in names if name.endswith("/pyproject.toml"))
        pyproject = archive.extractfile(pyproject_name)
        assert pyproject is not None
        pyproject_text = pyproject.read().decode("utf-8")
        assert f'version = "{EXPECTED_VERSION}"' in pyproject_text
        assert 'xray = "xray.cli:main"' in pyproject_text
        assert 'xray-mcp = "xray.mcp_server:main"' in pyproject_text


def test_built_wheel_contains_resources_and_imports_from_clean_target(tmp_path: Path):
    wheel = _build_wheel(tmp_path / "wheel")
    package_prefix = "xray/"

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        expected_names = {package_prefix + relative.as_posix() for relative in RESOURCE_FILES}
        assert expected_names <= names
        assert not any(name.endswith("lsp_config.json") for name in names)
        _assert_current_guidance(archive.read("xray/guidance.md"))
        for relative in RESOURCE_FILES:
            assert archive.read(package_prefix + relative.as_posix()) == _read_package_resource(relative)

    install_root = tmp_path / "installed"
    subprocess.run(
        ["uv", "pip", "install", "--no-deps", "--target", str(install_root), str(wheel)],
        check=True,
        capture_output=True,
        text=True,
    )
    script = """
import importlib.metadata
import importlib.resources
import xray

root = importlib.resources.files("xray")
for relative in ("guidance.md", "skills/xray-progressive-discovery/SKILL.md", "agent_skills/xray-cli/SKILL.md", "agent_skills/xray-cli/agents/openai.yaml"):
    resource = root
    for component in relative.split("/"):
        resource = resource.joinpath(component)
    assert resource.is_file(), relative
    assert resource.read_bytes(), relative
assert xray.__version__ == "1.0.0"
assert importlib.metadata.version("xray") == "1.0.0"
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(install_root)
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True, env=environment)


def _make_checkout(path: Path, *, with_script: bool = True) -> Path:
    path.mkdir(parents=True)
    (path / "pyproject.toml").write_text(
        '[project]\nname = "xray"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    (path / "src" / "xray").mkdir(parents=True)
    (path / "src" / "xray" / "__init__.py").write_text("__version__ = '1.0.0'\n", encoding="utf-8")
    if with_script:
        script = path / "install.sh"
        shutil.copy2(ROOT / "install.sh", script)
        script.chmod(0o755)
    return path


def _fake_toolchain(tmp_path: Path, *, old_xray: bool = False) -> tuple[dict[str, str], Path, Path, Path, Path]:
    commands = tmp_path / "commands"
    commands.mkdir()
    tool_bin = tmp_path / "uv tools with spaces"
    tool_bin.mkdir()
    uv_log = tmp_path / "uv.log"
    xray_log = tmp_path / "xray.log"
    old_log = tmp_path / "old-xray.log"
    home = tmp_path / "home"
    home.mkdir()

    uv_script = f"""#!/bin/sh
set -eu
log={shlex.quote(str(uv_log))}
tool_bin={shlex.quote(str(tool_bin))}
printf 'cwd=%s\\n' "$PWD" >> "$log"
printf 'argv=' >> "$log"
for arg do printf '<%s>' "$arg" >> "$log"; done
printf '\\n' >> "$log"
printf 'selectors=%s|%s|%s\\n' "${{UV_WORKING_DIR-}}" "${{UV_PROJECT-}}" "${{UV_CONFIG_FILE-}}" >> "$log"
if [ "${{FAKE_UV_MODE:-ok}}" = install-fail ]; then
    case " $* " in
        *" tool install "*) exit 17 ;;
    esac
fi
if [ "${{1:-}}" = "--no-config" ]; then shift; fi
if [ "${{1:-}}" = "--directory" ]; then shift 2; fi
[ "${{1:-}}" = "tool" ] || exit 18
shift
case "${{1:-}}" in
    install)
        cat > "$tool_bin/xray" <<'XRAY'
#!/bin/sh
set -eu
log={shlex.quote(str(xray_log))}
printf 'argv=' >> "$log"
for arg do printf '<%s>' "$arg" >> "$log"; done
printf '\\n' >> "$log"
if [ "${{1:-}}" = "--version" ]; then
    printf '%s\\n' "${{FAKE_XRAY_VERSION:-xray 1.0.0}}"
    exit 0
fi
if [ "${{1:-}}" = "map" ]; then
    [ "${{FAKE_XRAY_MAP_FAIL:-0}}" != 1 ]
    exit $?
fi
exit 0
XRAY
        chmod +x "$tool_bin/xray"
        cat > "$tool_bin/xray-mcp" <<'MCP'
#!/bin/sh
exit 0
MCP
        chmod +x "$tool_bin/xray-mcp"
        if [ "${{FAKE_UV_MODE:-ok}}" = missing-entry-point ]; then
            rm -f "$tool_bin/xray-mcp"
        fi
        ;;
    update-shell)
        ;;
    dir)
        [ "${{2:-}}" = "--bin" ] || exit 19
        printf '%s\\n' "$tool_bin"
        ;;
    *) exit 20 ;;
esac
"""
    uv = commands / "uv"
    uv.write_text(uv_script, encoding="utf-8")
    uv.chmod(0o755)

    for command in ("git", "curl"):
        marker = tmp_path / f"{command}.log"
        wrapper = commands / command
        wrapper.write_text(
            f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {shlex.quote(str(marker))}\nexit 99\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)

    path_entries = [str(commands)]
    if old_xray:
        old_bin = tmp_path / "old-bin"
        old_bin.mkdir()
        old = old_bin / "xray"
        old.write_text(
            f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {shlex.quote(str(old_log))}\nprintf 'xray 0.0.0\\n'\n",
            encoding="utf-8",
        )
        old.chmod(0o755)
        path_entries.insert(0, str(old_bin))
    path_entries.append(os.environ["PATH"])

    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            "PATH": os.pathsep.join(path_entries),
            "UV_WORKING_DIR": str(tmp_path / "ambient"),
            "UV_PROJECT": str(tmp_path / "ambient" / "pyproject.toml"),
            "UV_CONFIG_FILE": str(tmp_path / "ambient" / "uv.toml"),
        }
    )
    return environment, uv_log, xray_log, old_log, home


def _run_install(
    script: Path,
    *arguments: str,
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(script), *arguments],
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_install_script_selects_only_explicit_local_checkout_and_uv_bin(tmp_path: Path) -> None:
    trusted = _make_checkout(tmp_path / "trusted checkout")
    ambient = _make_checkout(tmp_path / "ambient project")
    selected = _make_checkout(tmp_path / "selected checkout with spaces")
    (ambient / "ambient-marker").write_text("unchanged\n", encoding="utf-8")
    before_trusted = (trusted / "pyproject.toml").read_bytes()
    environment, uv_log, xray_log, old_log, home = _fake_toolchain(tmp_path, old_xray=True)
    environment["XRAY_INSTALL_FORCE"] = "1"

    first = _run_install(trusted / "install.sh", cwd=ambient, environment=environment)
    assert first.returncode == 0, first.stderr
    second = _run_install(
        trusted / "install.sh",
        cwd=ambient,
        environment=environment,
        *("--checkout", str(selected)),
    )
    assert second.returncode == 0, second.stderr

    log = uv_log.read_text(encoding="utf-8")
    assert f"<{trusted.resolve()}>" in log
    assert f"<{selected.resolve()}>" in log
    assert "tool><install><--force>" in log
    assert "tool><run>" not in log
    assert "selectors=||" in log
    assert all(f"cwd={path.resolve()}" in log for path in (trusted, selected))
    xray_calls = xray_log.read_text(encoding="utf-8")
    assert f"<map><{trusted.resolve()}><--depth><1>" in xray_calls
    assert f"<map><{selected.resolve()}><--depth><1>" in xray_calls
    assert not old_log.exists()
    assert not (tmp_path / "git.log").exists()
    assert not (tmp_path / "curl.log").exists()
    assert (ambient / "ambient-marker").read_text(encoding="utf-8") == "unchanged\n"
    assert (trusted / "pyproject.toml").read_bytes() == before_trusted
    assert not (home / ".xray").exists()


def test_install_script_rejects_pipe_source_invalid_args_and_invalid_checkout_before_uv(
    tmp_path: Path,
) -> None:
    trusted = _make_checkout(tmp_path / "trusted")
    ambient = _make_checkout(tmp_path / "ambient")
    missing = tmp_path / "missing"
    standalone = tmp_path / "standalone.sh"
    shutil.copy2(ROOT / "install.sh", standalone)
    standalone.chmod(0o755)
    environment, uv_log, _xray_log, _old_log, _home = _fake_toolchain(tmp_path, old_xray=True)

    cases: list[subprocess.CompletedProcess[str]] = [
        subprocess.run(
            ["bash"],
            input=(ROOT / "install.sh").read_text(encoding="utf-8"),
            cwd=ambient,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        ),
        subprocess.run(
            ["bash", "/dev/stdin"],
            input=(ROOT / "install.sh").read_text(encoding="utf-8"),
            cwd=ambient,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        ),
        subprocess.run(
            ["bash", "-c", f"source {shlex.quote(str(trusted / 'install.sh'))}"],
            cwd=ambient,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        ),
        _run_install(trusted / "install.sh", "--unknown", cwd=ambient, environment=environment),
        _run_install(
            trusted / "install.sh",
            "--checkout",
            str(trusted),
            "--checkout",
            cwd=ambient,
            environment=environment,
        ),
        _run_install(trusted / "install.sh", "--checkout", cwd=ambient, environment=environment),
        _run_install(
            trusted / "install.sh",
            "--checkout",
            str(missing),
            cwd=ambient,
            environment=environment,
        ),
        _run_install(standalone, cwd=ambient, environment=environment),
    ]
    assert all(result.returncode != 0 for result in cases)
    assert not uv_log.exists()
    assert not (tmp_path / "git.log").exists()
    assert not (tmp_path / "curl.log").exists()

    help_result = _run_install(trusted / "install.sh", "--help", cwd=ambient, environment=environment)
    assert help_result.returncode == 0
    assert "Usage:" in help_result.stdout
    assert not uv_log.exists()


def test_install_script_keeps_no_change_behavior_and_does_not_delete_home_source(tmp_path: Path) -> None:
    trusted = _make_checkout(tmp_path / "trusted")
    ambient = _make_checkout(tmp_path / "ambient")
    environment, uv_log, _xray_log, old_log, home = _fake_toolchain(tmp_path, old_xray=True)
    environment.pop("XRAY_INSTALL_FORCE", None)
    sentinel = home / ".xray"
    sentinel.mkdir()
    (sentinel / "keep.txt").write_text("keep\n", encoding="utf-8")

    result = _run_install(trusted / "install.sh", cwd=ambient, environment=environment)

    assert result.returncode == 0
    assert "Set XRAY_INSTALL_FORCE=1" in result.stdout
    assert not uv_log.exists()
    assert not old_log.exists()
    assert (sentinel / "keep.txt").read_text(encoding="utf-8") == "keep\n"


def test_install_script_reports_uv_and_post_install_failures(tmp_path: Path) -> None:
    trusted = _make_checkout(tmp_path / "trusted")
    environment, _uv_log, _xray_log, old_log, _home = _fake_toolchain(tmp_path, old_xray=True)
    environment["XRAY_INSTALL_FORCE"] = "1"

    for updates in (
        {"FAKE_XRAY_VERSION": "xray 9.9.9"},
        {"FAKE_UV_MODE": "missing-entry-point"},
        {"FAKE_XRAY_MAP_FAIL": "1"},
        {"FAKE_UV_MODE": "install-fail"},
    ):
        environment.pop("FAKE_XRAY_VERSION", None)
        environment.pop("FAKE_UV_MODE", None)
        environment.pop("FAKE_XRAY_MAP_FAIL", None)
        environment.update(updates)
        result = _run_install(trusted / "install.sh", cwd=tmp_path, environment=environment)
        assert result.returncode != 0, (updates, result.stdout, result.stderr)

    assert not old_log.exists()


def test_install_script_bootstraps_uv_only_after_source_validation(tmp_path: Path) -> None:
    trusted = _make_checkout(tmp_path / "trusted")
    standalone = tmp_path / "standalone.sh"
    shutil.copy2(ROOT / "install.sh", standalone)
    standalone.chmod(0o755)
    environment, uv_log, _xray_log, _old_log, home = _fake_toolchain(tmp_path)
    commands = tmp_path / "commands"
    uv_source = tmp_path / "bootstrap-uv"
    shutil.copy2(commands / "uv", uv_source)
    (commands / "uv").unlink()
    curl_marker = tmp_path / "curl.log"
    (commands / "curl").write_text(
        f"#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> {shlex.quote(str(curl_marker))}\n"
        f"printf '%s\\n' 'mkdir -p \"$HOME/.local/bin\"'\n"
        f"printf '%s\\n' 'cp -f -- {shlex.quote(str(uv_source))} \"$HOME/.local/bin/uv\"'\n",
        encoding="utf-8",
    )
    (commands / "curl").chmod(0o755)

    environment["PATH"] = os.pathsep.join((str(commands), os.defpath))
    invalid = _run_install(standalone, cwd=tmp_path, environment=environment)
    assert invalid.returncode != 0
    assert not curl_marker.exists()
    assert not (home / ".local" / "bin" / "uv").exists()

    environment["XRAY_INSTALL_FORCE"] = "1"
    valid = _run_install(trusted / "install.sh", cwd=tmp_path, environment=environment)
    assert valid.returncode == 0, valid.stderr
    assert "https://astral.sh/uv/install.sh" in curl_marker.read_text(encoding="utf-8")
    assert uv_log.exists()
