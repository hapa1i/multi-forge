"""B2: refuse missing or stale fixture auth before model launch."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess

import pytest

from tests.fixtures.codex_probe import PROBES, load_script

pytestmark = pytest.mark.regression


def test_missing_login_refuses_before_model_launch_or_quota_reservation(tmp_path, monkeypatch):
    runtime = load_script("probe-runtime")
    login = load_script("probe-home").prepare_home(tmp_path / "codex-home")
    binary = tmp_path / "codex"
    binary.write_text('#!/bin/sh\necho "Not logged in" >&2\nexit 1\n')
    binary.chmod(0o700)
    identity = tmp_path / "identity.json"
    identity.write_text(
        json.dumps({"retained_path": str(binary), "sha256": hashlib.sha256(binary.read_bytes()).hexdigest()})
    )
    for name in os.environ:
        if name.endswith("API_KEY") or name in {"CODEX_ACCESS_TOKEN", "OPENAI_BASE_URL"}:
            monkeypatch.delenv(name)
    monkeypatch.setenv("CODEX_HOME", str(login))
    monkeypatch.setenv("PROBE_TURN_CEILING", "10")
    with pytest.raises(ValueError, match="ChatGPT login is unavailable"):
        runtime.codex_exec(identity, ["exec", "Reply OK"])
    assert not (tmp_path / "turns.jsonl").exists()


def test_shell_probe_auth_rejects_not_logged_in_even_with_exit_zero(tmp_path):
    login = load_script("probe-home").prepare_home(tmp_path / "codex-home")
    (login / "auth.json").write_text('{"fixture": "stale"}')
    binary = tmp_path / "bin"
    binary.mkdir()
    codex = binary / "codex"
    codex.write_text('#!/bin/sh\necho "Not logged in"\n')
    codex.chmod(0o700)
    env = dict(
        os.environ,
        PATH=str(binary) + os.pathsep + os.environ["PATH"],
        PROBE_CODEX_HOME=str(login),
        CODEX_HOOKS_CAPTURE_DIR=str(tmp_path / "captures"),
    )
    result = subprocess.run(
        ["/bin/bash", "-c", 'source "$1/lib.sh"; fixture_init auth; probe_auth', "probe", str(PROBES)],
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode != 0
    assert "Stop; no auth fallback" in result.stderr
