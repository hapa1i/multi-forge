"""B1: the isolated reviewer dropped user settings credentials, including sidecar helpers."""

import json
import os
import sys

import pytest

from forge.core.reactive.reviewer_settings import (
    auth_settings_descriptor,
    inherited_auth_settings,
)
from forge.core.reactive.watchdog import run_guarded

pytestmark = pytest.mark.regression


def test_user_auth_settings_survive_without_customizations(tmp_path):
    (tmp_path / ".claude").mkdir()
    settings = {
        "apiKeyHelper": "/trusted/helper",
        "env": {
            "ANTHROPIC_API_KEY": "synthetic-settings-key",
            "ANTHROPIC_BASE_URL": "http://wrong",
            "NODE_OPTIONS": "evil",
        },
        "hooks": {"PreToolUse": ["evil"]},
        "permissions": {"defaultMode": "bypassPermissions"},
    }
    (tmp_path / ".claude/settings.json").write_text(json.dumps(settings))
    env = {"HOME": str(tmp_path)}
    selected = inherited_auth_settings(env, cwd=str(tmp_path), direct=True)
    assert selected == {"apiKeyHelper": "/trusted/helper"}
    assert env == {"HOME": str(tmp_path), "ANTHROPIC_API_KEY": "synthetic-settings-key"}
    with auth_settings_descriptor(selected) as (args, descriptors):
        assert "synthetic-settings-key" not in " ".join(args)
        result = run_guarded(
            [sys.executable, "-I", "-c", "import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text())", args[1]],
            input="",
            cwd=str(tmp_path),
            env=dict(os.environ),
            timeout=5,
            pass_fds=descriptors,
        )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == selected
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


def test_explicit_child_credentials_and_route_win_settings(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/settings.json").write_text(
        json.dumps({"env": {"ANTHROPIC_API_KEY": "old", "ANTHROPIC_BASE_URL": "http://old"}})
    )
    env = {"HOME": str(tmp_path), "ANTHROPIC_API_KEY": "selected", "ANTHROPIC_BASE_URL": "http://selected"}
    inherited_auth_settings(env, cwd=str(tmp_path), direct=False)
    assert env["ANTHROPIC_API_KEY"] == "selected" and env["ANTHROPIC_BASE_URL"] == "http://selected"


def test_trusted_checkout_cannot_replace_user_auth_helper(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude/settings.json").write_text(json.dumps({"apiKeyHelper": "/trusted/user-helper"}))
    project = tmp_path / "project"
    (project / ".claude").mkdir(parents=True)
    (project / ".git").mkdir()
    (home / ".claude.json").write_text(json.dumps({"projects": {str(project): {"hasTrustDialogAccepted": True}}}))
    settings = project / ".claude/settings.local.json"
    settings.write_text(json.dumps({"apiKeyHelper": "./planted-helper", "env": {"ANTHROPIC_API_KEY": "project-key"}}))
    with pytest.raises(ValueError, match="outside the supervised checkout"):
        inherited_auth_settings({"HOME": str(home)}, cwd=str(project), direct=True)
    settings.write_text(json.dumps({"env": {"ANTHROPIC_API_KEY": "project-key"}}))
    env = {"HOME": str(home)}
    assert inherited_auth_settings(env, cwd=str(project), direct=True) == {"apiKeyHelper": "/trusted/user-helper"}
    assert env["ANTHROPIC_API_KEY"] == "project-key"


def test_auth_settings_fifo_is_refused_without_reading(tmp_path):
    (tmp_path / ".claude").mkdir()
    os.mkfifo(tmp_path / ".claude/settings.json")
    with pytest.raises(ValueError, match="regular file"):
        inherited_auth_settings({"HOME": str(tmp_path)}, cwd=str(tmp_path), direct=True)
