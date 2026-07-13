"""Unit tests for `forge extension doctor` install diagnosis.

Covers install-kind classification, PATH reachability, the D2 minimal-PATH
probe, and the CLI leaf's JSON/human output. Detection seams (`argv0`, `which`,
`environ`, `editable`) are injected so tests never depend on how the test
runner itself was installed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.extensions import extensions
from forge.install.doctor import (
    EDITABLE_INSTALL_COMMANDS,
    GLOBAL_INSTALL_COMMANDS,
    MINIMAL_PATH,
    PATH_SETUP_COMMANDS,
    diagnose_install,
    is_editable_install,
)
from forge.install.hook_dispatcher import install_hook_dispatcher


def _fake_which(bindir_to_forge: dict[str, str]) -> Callable[..., str | None]:
    """Return a `shutil.which` stand-in.

    `bindir_to_forge` maps a directory string that may appear in the search PATH
    to the launcher path returned when that dir is present -- so the same fake
    answers both the full-PATH and minimal-PATH probes by substring match.
    """

    def _which(cmd: str, path: str | None = None) -> str | None:
        assert cmd == "forge"
        search = path or ""
        for bindir, forge_path in bindir_to_forge.items():
            if bindir and bindir in search:
                return forge_path
        return None

    return _which


def test_global_install_on_local_bin(tmp_path: Path) -> None:
    home = tmp_path
    bindir = home / ".local" / "bin"
    bindir.mkdir(parents=True)
    forge = bindir / "forge"
    environ = {"HOME": str(home), "PATH": f"{bindir}:/usr/bin:/bin"}
    which = _fake_which({str(bindir): str(forge)})

    diag = diagnose_install(argv0="/opt/pytest", which=which, environ=environ, editable=False)

    assert diag.install_kind == "global"
    assert diag.forge_path == str(forge)
    assert diag.on_path is True
    # ~/.local/bin is absent from the launchd minimal PATH -- expected, not a fault.
    assert diag.on_path_minimal is False
    assert diag.advice is None


def test_editable_install_labeled_editable(tmp_path: Path) -> None:
    venv_bin = tmp_path / "repo" / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    forge = venv_bin / "forge"
    environ = {"HOME": str(tmp_path), "PATH": f"{venv_bin}:/usr/bin"}
    which = _fake_which({str(venv_bin): str(forge)})

    diag = diagnose_install(which=which, environ=environ, editable=True)

    assert diag.install_kind == "editable"
    assert diag.forge_path == str(forge)
    assert diag.on_path is True
    assert diag.advice is not None
    # Contributor fix, not the released wheel (which would shadow the checkout).
    assert "editable launcher" in diag.advice
    assert "do not infer this checkout's venv" in diag.advice
    assert diag.advice_commands == EDITABLE_INSTALL_COMMANDS


def test_editable_with_global_launcher_clears_advice(tmp_path: Path) -> None:
    """setup.sh --local is itself an editable install -- its launcher must clear the tip.

    PATH puts the checkout venv first (the ``uv run forge extension doctor``
    case), so the clear keys on the launcher's existence in a global bin dir,
    not on PATH resolution order -- mirroring the dispatcher's fallback. The
    contract is reachability, not provenance: any executable launcher counts
    (hence the arbitrary stub), because it means hooks resolve.
    """
    venv_bin = tmp_path / "repo" / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    venv_forge = venv_bin / "forge"
    global_bin = tmp_path / ".local" / "bin"
    global_bin.mkdir(parents=True)
    launcher = global_bin / "forge"
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)
    environ = {"HOME": str(tmp_path), "PATH": f"{venv_bin}:/usr/bin"}
    which = _fake_which({str(venv_bin): str(venv_forge)})

    diag = diagnose_install(which=which, environ=environ, editable=True)

    assert diag.install_kind == "editable"  # kind stays truthful
    assert diag.advice is None  # contributor end state -- no self-repeating tip
    assert diag.advice_commands == ()


def test_editable_with_recorded_custom_launcher_clears_advice(tmp_path: Path) -> None:
    """A custom launcher recorded in runtime.json is also a durable resolver target.

    The dispatcher tries the recorded launcher before known locations, so a
    valid custom launcher outside the global bin dirs must clear the tip too.
    """
    venv_bin = tmp_path / "repo" / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    venv_forge = venv_bin / "forge"
    custom = tmp_path / "opt" / "bin" / "forge"
    custom.parent.mkdir(parents=True)
    custom.write_text("#!/bin/sh\n")
    custom.chmod(0o755)
    environ = {"HOME": str(tmp_path), "PATH": f"{venv_bin}:/usr/bin"}
    which = _fake_which({str(venv_bin): str(venv_forge)})

    diag = diagnose_install(which=which, environ=environ, editable=True, recorded_launcher=str(custom))

    assert diag.install_kind == "editable"
    assert diag.advice is None
    assert diag.advice_commands == ()


def test_venv_only_not_on_path_advises_global(tmp_path: Path) -> None:
    venv = tmp_path / "proj" / ".venv"
    venv_bin = venv / "bin"
    venv_bin.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /usr\n")  # marks this as a real venv bin
    forge = venv_bin / "forge"
    environ = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}  # forge NOT on PATH
    which = _fake_which({})  # never resolves forge

    diag = diagnose_install(argv0=str(forge), which=which, environ=environ, editable=False)

    assert diag.install_kind == "venv"
    assert diag.forge_path == str(forge)  # falls back to the running launcher (argv0)
    assert diag.on_path is False
    assert diag.on_path_minimal is False
    assert diag.advice is not None
    assert "global tool" in diag.advice
    assert diag.advice_commands == GLOBAL_INSTALL_COMMANDS


def test_global_installed_but_off_path_advises_path_setup(tmp_path: Path) -> None:
    """The 'just ran uv tool install, PATH not wired' case: fix PATH, do not reinstall."""
    home = tmp_path
    bindir = home / ".local" / "bin"
    bindir.mkdir(parents=True)
    forge = bindir / "forge"
    environ = {"HOME": str(home), "PATH": "/usr/bin:/bin"}  # ~/.local/bin NOT on PATH
    which = _fake_which({})  # forge not resolvable on the current PATH
    # Off PATH, the user invokes the launcher by its full path -> that is argv0.
    diag = diagnose_install(argv0=str(forge), which=which, environ=environ, editable=False)

    assert diag.install_kind == "global"
    assert diag.on_path is False
    assert diag.forge_path == str(forge)
    assert diag.advice is not None
    assert "not on your PATH" in diag.advice
    assert "global tool" not in diag.advice  # must NOT tell an installed user to reinstall
    assert diag.advice_commands == PATH_SETUP_COMMANDS


@pytest.mark.parametrize("env_var", [None, "XDG_BIN_HOME", "PIPX_BIN_DIR", "UV_TOOL_BIN_DIR"])
def test_global_tool_layouts_resolve_global(tmp_path: Path, env_var: str | None) -> None:
    """uv tool (~/.local/bin) and pipx/XDG override dirs both classify as global."""
    home = tmp_path
    environ: dict[str, str] = {"HOME": str(home)}
    if env_var is None:
        bindir = home / ".local" / "bin"
    else:
        bindir = tmp_path / "custom" / "bin"
        environ[env_var] = str(bindir)
    bindir.mkdir(parents=True)
    forge = bindir / "forge"
    environ["PATH"] = f"{bindir}:/usr/bin"
    which = _fake_which({str(bindir): str(forge)})

    diag = diagnose_install(which=which, environ=environ, editable=False)

    assert diag.install_kind == "global"
    assert diag.forge_path == str(forge)


def test_unknown_when_forge_not_found() -> None:
    environ = {"HOME": "/home/u", "PATH": "/usr/bin:/bin"}
    which = _fake_which({})
    # Bare argv0 (no path separator) is not a usable launcher path.
    diag = diagnose_install(argv0="forge", which=which, environ=environ, editable=False)

    assert diag.install_kind == "unknown"
    assert diag.forge_path is None
    assert diag.on_path is False
    assert diag.advice is not None


def test_minimal_path_probe_flags_gui_launch_gap(tmp_path: Path) -> None:
    """D2 evidence: forge on the user PATH but absent from the launchd minimal PATH."""
    bindir = tmp_path / ".local" / "bin"
    bindir.mkdir(parents=True)
    forge = bindir / "forge"
    environ = {"HOME": str(tmp_path), "PATH": f"{bindir}:/usr/bin"}
    which = _fake_which({str(bindir): str(forge)})

    diag = diagnose_install(which=which, environ=environ, editable=False)

    assert diag.on_path is True
    assert diag.on_path_minimal is False


def test_minimal_path_probe_true_when_in_system_bin() -> None:
    """The probe genuinely reflects PATH contents: a system-bin forge is reachable."""
    environ = {"HOME": "/home/u", "PATH": "/usr/local/bin:/usr/bin:/bin"}
    # /usr/bin is on BOTH the full PATH and the minimal PATH.
    which = _fake_which({"/usr/bin": "/usr/bin/forge"})
    assert "/usr/bin" in MINIMAL_PATH  # guards the fixture's premise

    diag = diagnose_install(which=which, environ=environ, editable=False)

    assert diag.on_path is True
    assert diag.on_path_minimal is True


def test_doctor_json_shape_is_stable() -> None:
    runner = CliRunner()
    result = runner.invoke(extensions, ["doctor", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert set(data) == {
        "install_kind",
        "forge_path",
        "on_path",
        "on_path_minimal",
        "advice",
        "hook_dispatcher",
        "runtime_hooks",
        "project_registry",
        "project_compatibility",
    }
    assert isinstance(data["on_path"], bool)
    assert isinstance(data["on_path_minimal"], bool)
    assert data["install_kind"] in {"global", "editable", "venv", "unknown"}
    assert set(data["hook_dispatcher"]) == {
        "path",
        "status",
        "installed_version",
        "expected_version",
        "installed_source_sha256",
        "expected_source_sha256",
        "metadata_path",
        "metadata_status",
        "forge_binary_path",
        "dev_override",
        "advice",
    }
    assert set(data["hook_dispatcher"]["dev_override"]) == {
        "present",
        "value",
        "target",
        "valid",
        "effective",
        "advice",
    }
    assert data["hook_dispatcher"]["dev_override"] == {
        "present": False,
        "value": None,
        "target": None,
        "valid": False,
        "effective": False,
        "advice": None,
    }
    assert set(data["runtime_hooks"]) == {
        "scopes",
        "double_fire_risk",
        "cleanup_required",
        "legacy_registrations",
    }
    assert set(data["project_registry"]) == {
        "path",
        "status",
        "enrolled_count",
        "stale_roots",
        "error",
        "advice",
    }
    assert set(data["project_compatibility"]) == {
        "path",
        "state",
        "compatible",
        "required_forge",
        "running_forge",
        "reason",
        "degraded",
    }


def test_doctor_human_output_names_install_kind() -> None:
    runner = CliRunner()
    result = runner.invoke(extensions, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "Install kind" in result.output
    assert "On PATH" in result.output
    assert "Hook dispatcher" in result.output
    assert "Dev override" in result.output
    assert "this doctor process" in result.output
    assert "Project registry" in result.output
    assert "Project compatibility" in result.output


def test_doctor_human_output_escapes_dev_override_markup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global_forge = tmp_path / "global" / "forge"
    global_forge.parent.mkdir(parents=True)
    global_forge.write_text("#!/bin/sh\n", encoding="utf-8")
    global_forge.chmod(0o755)
    checkout = tmp_path / "[red]checkout"
    dev_forge = checkout / ".venv" / "bin" / "forge"
    dev_forge.parent.mkdir(parents=True)
    dev_forge.write_text("#!/bin/sh\n", encoding="utf-8")
    dev_forge.chmod(0o755)
    install_hook_dispatcher(forge_binary_path=global_forge)
    monkeypatch.setenv("FORGE_DEV", str(checkout))

    result = CliRunner().invoke(extensions, ["doctor"])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    override_index = next(index for index, line in enumerate(lines) if "Dev override:" in line)
    target_index = next(index for index, line in enumerate(lines) if "Dev target:" in line)
    valid_index = next(index for index, line in enumerate(lines) if "Dev valid:" in line)
    assert "[red]checkout" in "".join(lines[override_index:target_index])
    assert "[red]checkout" in "".join(lines[target_index:valid_index])


def test_doctor_json_reports_valid_dev_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    global_forge = tmp_path / "global" / "forge"
    global_forge.parent.mkdir(parents=True)
    global_forge.write_text("#!/bin/sh\n", encoding="utf-8")
    global_forge.chmod(0o755)
    checkout = tmp_path / "checkout"
    dev_forge = checkout / ".venv" / "bin" / "forge"
    dev_forge.parent.mkdir(parents=True)
    dev_forge.write_text("#!/bin/sh\n", encoding="utf-8")
    dev_forge.chmod(0o755)
    install_hook_dispatcher(forge_binary_path=global_forge)
    monkeypatch.setenv("FORGE_DEV", str(checkout))

    result = CliRunner().invoke(extensions, ["doctor", "--json"])

    assert result.exit_code == 0, result.output
    override = json.loads(result.output)["hook_dispatcher"]["dev_override"]
    assert override == {
        "present": True,
        "value": str(checkout),
        "target": str(dev_forge),
        "valid": True,
        "effective": True,
        "advice": None,
    }


def test_doctor_json_reports_invalid_dev_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    global_forge = tmp_path / "global" / "forge"
    global_forge.parent.mkdir(parents=True)
    global_forge.write_text("#!/bin/sh\n", encoding="utf-8")
    global_forge.chmod(0o755)
    install_hook_dispatcher(forge_binary_path=global_forge)
    checkout = tmp_path / "missing-checkout"
    monkeypatch.setenv("FORGE_DEV", str(checkout))

    result = CliRunner().invoke(extensions, ["doctor", "--json"])

    assert result.exit_code == 0, result.output
    override = json.loads(result.output)["hook_dispatcher"]["dev_override"]
    assert override["present"] is True
    assert override["value"] == str(checkout)
    assert override["target"] == str(checkout / ".venv" / "bin" / "forge")
    assert override["valid"] is False
    assert override["effective"] is False
    assert "missing or not executable" in override["advice"]


def test_is_editable_install_returns_bool() -> None:
    # Env-independent contract: never raises, always a bool.
    assert isinstance(is_editable_install(), bool)
