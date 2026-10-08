"""Real Claude auth-setting inference and old-runtime admission in disposable Linux homes."""

import json
import os

import pytest

from tests.fixtures.docker import ContainerLike
from tests.integration.docker.conftest import setup_real_claude

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


@pytest.mark.parametrize("source", ["helper", "settings-env"])
def test_inherited_auth_settings_can_complete_read_only_review(forge_workspace: ContainerLike, source: str):
    setup_real_claude(forge_workspace, session_name="inherit-auth")
    key = os.environ.get("ANTHROPIC_API_KEY")
    assert key, "Inherited-auth integration requires an explicit Anthropic API credential"
    assert forge_workspace.write_file("/tmp/.reviewer-test-key", key, mode=0o600).returncode == 0
    script = r"""import json, os, tempfile
from pathlib import Path
from forge.core.reactive.session_runner import run_claude_session
root=Path(tempfile.mkdtemp(prefix="inherit-review-"))
key=Path("/tmp/.reviewer-test-key").read_text()
for name in list(os.environ):
    if name.startswith(("ANTHROPIC_", "CLAUDE_CODE_", "FORGE_SUBPROCESS_")):
        os.environ.pop(name)
os.environ.update(HOME=str(root), FORGE_HOME=str(root/".forge"), FORGE_DEPTH="0")
os.environ.pop("CLAUDE_CONFIG_DIR", None)
(root/".claude").mkdir()
helper=root/"auth-helper"
helper.write_text("#!/bin/sh\necho called >> " + str(root/"helper-called") + "\nprintf '%s\\n' \"$AUTH_FIXTURE_KEY\"\n")
helper.chmod(0o700)
os.environ["AUTH_FIXTURE_KEY"]=key
source=SOURCE
auth={"apiKeyHelper":str(helper)} if source=="helper" else {"env":{"ANTHROPIC_API_KEY":key}}
auth["hooks"]={"SessionStart":[{"hooks":[{"type":"command", "command":"touch " + str(root/"hook-fired")}]}]}
(root/".claude/settings.json").write_text(json.dumps(auth))
result=run_claude_session("Reply exactly: auth-ok", model="haiku", direct=True, read_only=True, cwd=str(root), timeout_seconds=40)
assert result.success, result.error or result.stderr
assert "auth-ok" in result.stdout
assert not (root/"hook-fired").exists()
if source=="helper":
    assert (root/"helper-called").exists()
print(json.dumps({"source":source, "review_completed":result.success, "hooks_ran":False}))
""".replace("SOURCE", repr(source))
    assert forge_workspace.write_file("/tmp/reviewer-auth.py", script, mode=0o600).returncode == 0
    result = forge_workspace.exec("/forge/.venv/bin/python /tmp/reviewer-auth.py", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1])["review_completed"]


def test_old_blocking_pin_refuses_without_inference(forge_workspace: ContainerLike):
    installed = forge_workspace.exec(
        "npm install --prefix /tmp/old-reviewer @anthropic-ai/claude-code@2.1.245", timeout=120
    )
    assert installed.returncode == 0, installed.stderr
    version = forge_workspace.exec("/tmp/old-reviewer/node_modules/.bin/claude --version", timeout=20)
    assert version.returncode == 0 and version.stdout.startswith("2.1.245"), version.stdout + version.stderr
    script = r"""import json, os, tempfile
from forge.core.reactive.session_runner import run_claude_session
home=tempfile.mkdtemp(prefix="old-reviewer-home-")
os.environ.update(HOME=home, FORGE_HOME=home+"/.forge", PATH="/tmp/old-reviewer/node_modules/.bin:"+os.environ["PATH"])
result=run_claude_session("must not infer", read_only=True, direct=True)
assert not result.dispatched and "claude update" in result.error, result
print(json.dumps({"dispatched":result.dispatched, "actionable":True}))
"""
    assert forge_workspace.write_file("/tmp/old-reviewer.py", script, mode=0o600).returncode == 0
    result = forge_workspace.exec("/forge/.venv/bin/python /tmp/old-reviewer.py", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
