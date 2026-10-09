"""B2: baseline stages must refuse enrolled homes and discard stale hook configuration."""

from __future__ import annotations

import os
import subprocess

import pytest

from tests.fixtures.codex_probe import PROBES, load_script

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("enrolled,override", [(False, False), (True, False), (True, True)])
def test_baseline_reset_preserves_auth_and_invalidates_enrollment_only_with_override(tmp_path, enrolled, override):
    login = load_script("probe-home").prepare_home(tmp_path / "codex-home")
    (login / "auth.json").write_text('{"fixture": "refreshed"}')
    (login / "config.toml").write_text('stale_trust = "previous-stage"\n')
    (login / "hooks.json").write_text('{"hooks": "deleted-hook-script"}')
    capture = tmp_path / "captures"
    fixture = capture / "fixture"
    fixture.mkdir(parents=True)
    sentinel = fixture / "ENROLLED"
    if enrolled:
        sentinel.write_text("enrolled fixture\n")
    previous = capture / "baseline"
    previous.mkdir()
    (previous / "prior-result").write_text("preserve evidence")
    control = tmp_path / "control.json"
    control.write_text('{"mode": "previous"}')
    binary = tmp_path / "bin"
    binary.mkdir()
    (binary / "codex").write_text("#!/bin/sh\nexit 91\n")
    (binary / "codex").chmod(0o700)
    env = {
        "PATH": str(binary) + os.pathsep + os.environ["PATH"],
        "HOME": str(tmp_path),
        "PROBE_CODEX_HOME": str(login),
        "CODEX_HOOKS_CAPTURE_DIR": str(capture),
        "PROBE_CONTROL": str(control),
        "PROBE_RESET_ENROLLED": "1" if override else "0",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    result = subprocess.run(
        ["/bin/bash", "-c", 'source "$1/lib.sh"; probe_init baseline', "probe", str(PROBES)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert (login / "auth.json").read_text() == '{"fixture": "refreshed"}'
    if enrolled and not override:
        assert result.returncode != 0
        assert "PROBE_RESET_ENROLLED=1" in result.stderr
        assert sentinel.read_text() == "enrolled fixture\n"
        assert (login / "config.toml").read_text() == 'stale_trust = "previous-stage"\n'
        assert (login / "hooks.json").is_file()
        assert (previous / "prior-result").read_text() == "preserve evidence"
        assert control.read_text() == '{"mode": "previous"}'
        assert not (capture / "archive").exists()
    else:
        assert result.returncode == 0, result.stderr
        assert not sentinel.exists()
        assert not (login / "hooks.json").exists()
        assert (login / "config.toml").read_text() == 'cli_auth_credentials_store = "file"\n[features]\nhooks = true\n'
        assert len(list((capture / "archive").glob("*/prior-result"))) == 1


def test_configuration_reset_unlinks_symlinks_without_changing_their_targets(tmp_path):
    login = load_script("probe-home").prepare_home(tmp_path / "codex-home")
    foreign = tmp_path / "foreign-config"
    foreign.write_text("untouched")
    (login / "config.toml").unlink()
    (login / "config.toml").symlink_to(foreign)
    (login / "hooks.json").symlink_to(foreign)
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            'source "$1/lib.sh"; CODEX_HOME="$2"; probe_reset_config',
            "probe",
            str(PROBES),
            str(login),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert foreign.read_text() == "untouched"
    assert not (login / "config.toml").is_symlink()
    assert not (login / "hooks.json").exists()
