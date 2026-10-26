"""Claude canonicalizes anonymous settings descriptors into unreadable deleted paths."""

import json
import os
import shlex
import sys

import pytest

from forge.core.reactive.reviewer_settings import project_auth_settings
from forge.core.reactive.watchdog import run_guarded

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("token", ["synthetic-key", "key with 'quotes' and $dollars; $(not-a-command)"])
def test_helper_executes_without_a_settings_path_or_secret_in_argv(tmp_path, token):
    existing_files = set(tmp_path.iterdir())
    helper = f"printf '%s\\n' {shlex.quote(token)}"
    original_env = dict(os.environ, FORGE_REVIEWER_API_KEY_HELPER="stale helper")
    settings = {"apiKeyHelper": helper}
    projected, child_env = project_auth_settings(settings, original_env)
    args = ["--settings", json.dumps(projected)]
    assert helper not in " ".join(args)
    assert token not in " ".join(args)
    assert original_env["FORGE_REVIEWER_API_KEY_HELPER"] == "stale helper"
    assert settings == {"apiKeyHelper": helper}
    # Match Claude's two settings-input forms, including canonicalization of
    # file paths. Its auth helper runs in a shell with the reviewer's environment.
    consumer = """
import json, pathlib, subprocess, sys
argument = sys.argv[1]
payload = argument if argument.startswith('{') else pathlib.Path(argument).resolve(strict=True).read_text()
settings = json.loads(payload)
result = subprocess.run(settings['apiKeyHelper'], shell=True, text=True, capture_output=True)
sys.stdout.write(result.stdout)
sys.stderr.write(result.stderr)
raise SystemExit(result.returncode)
"""
    result = run_guarded(
        [sys.executable, "-I", "-c", consumer, args[1]],
        input="",
        env=child_env,
        cwd=str(tmp_path),
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == token + "\n"
    assert set(tmp_path.iterdir()) == existing_files


@pytest.mark.parametrize("settings", [{}, {"apiKeyHelper": ""}])
def test_absent_or_empty_helper_stays_disabled(settings):
    projected, child_env = project_auth_settings(settings, {})
    if projected:
        assert projected == {"apiKeyHelper": ""}
        assert child_env["FORGE_REVIEWER_API_KEY_HELPER"] == ""
    else:
        assert child_env == {}
