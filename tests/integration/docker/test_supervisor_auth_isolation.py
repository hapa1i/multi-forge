"""Auth-location probes use only synthetic credentials in a disposable Linux HOME."""

import json
import os
import shlex

import pytest

from tests.fixtures.docker import ContainerLike
from tests.integration.docker.conftest import setup_real_claude

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]

_PROBE = r"""import json, os, subprocess, tempfile
from pathlib import Path
from forge.core.reactive.supervisor_auth import READ_ONLY_FLAGS, subscription_environment
from forge.core.reactive.session_runner import run_claude_session

root = Path(tempfile.mkdtemp(prefix="b1-auth-"))
os.environ.update(HOME=str(root), FORGE_HOME=str(root / ".forge"))
os.environ.pop("CLAUDE_CONFIG_DIR", None)
(root / ".claude").mkdir()
(root / ".claude.json").write_text(json.dumps({"oauthAccount":{"organizationType":"claude_max"}}))
project = root / "project"
(project / ".claude").mkdir(parents=True)
subprocess.run(["git", "init", "-q", str(project)], check=True)
# Trust this disposable project: an untrusted-settings skip would prove nothing.
config = json.loads((root / ".claude.json").read_text())
config["projects"] = {str(project): {"hasTrustDialogAccepted":True}}
(root / ".claude.json").write_text(json.dumps(config))
helper = root / "helper"
helper.write_text("#!/bin/sh\necho invoked >> " + str(root / "helper-count") + "\necho synthetic-helper-key\n")
helper.chmod(0o700)
settings = {"apiKeyHelper":str(helper), "env":{"ANTHROPIC_API_KEY":"synthetic-settings-key"}}
for p in (root / ".claude/settings.json", project / ".claude/settings.json", project / ".claude/settings.local.json"):
    p.write_text(json.dumps(settings))
(root / ".forge").mkdir()
(root / ".forge/credentials.yaml").write_text("anthropic_api_key: synthetic-forge-key\n")
(project / ".env").write_text("ANTHROPIC_API_KEY=synthetic-dotenv-key\n")
from dotenv import load_dotenv
load_dotenv(project / ".env", override=True)

def status(env, flags):
    p = subprocess.run(["claude", *flags, "auth", "status", "--json"], env=env, cwd=project, text=True, capture_output=True, timeout=20)
    raw = json.loads(p.stdout)
    return {k:raw.get(k) for k in ("loggedIn","authMethod","apiProvider","apiKeySource")}

control = status(dict(os.environ), [])
assert control["loggedIn"] is True and control["authMethod"] in {"api_key", "api_key_helper"}, control
selectors = {
 "ANTHROPIC_API_KEY":"synthetic-key", "ANTHROPIC_AUTH_TOKEN":"synthetic-bearer",
 "CLAUDE_CODE_OAUTH_TOKEN":"synthetic-oauth", "ANTHROPIC_PROFILE":"synthetic",
 "ANTHROPIC_FEDERATION_RULE_ID":"synthetic", "ANTHROPIC_ORGANIZATION_ID":"synthetic",
 "CLAUDE_CODE_USE_BEDROCK":"1", "CLAUDE_CODE_USE_VERTEX":"1", "CLAUDE_CODE_USE_FOUNDRY":"1",
 "ANTHROPIC_BASE_URL":"http://127.0.0.1:9", "FORGE_SUBPROCESS_BASE_URL":"http://127.0.0.1:9",
 "FORGE_SUBPROCESS_PROXY":"synthetic", "HTTPS_PROXY":"http://127.0.0.1:9"
}
os.environ.update(selectors)
clean = subscription_environment()
assert set(selectors).isdisjoint(clean)
clean_status = status(clean, READ_ONLY_FLAGS)
assert clean_status["loggedIn"] is False, clean_status
result = run_claude_session("must never infer", direct=True, read_only=True, subscription_only=True, cwd=str(project), timeout_seconds=30)
assert not result.dispatched and result.child_billing_mode is None
rows = [{"case":"missing-login-with-competing-selectors-and-trusted-settings", "refused":True}]
for relative, content in (
 (".config/anthropic/active_config", "default"),
 (".config/anthropic/configs/default.json", '{}'),
 (".claude/remote-settings.json", '{"env":{"ANTHROPIC_BASE_URL":"http://127.0.0.1:9"}}'),
):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    result = run_claude_session("must never infer", direct=True, read_only=True, subscription_only=True, cwd=str(project), timeout_seconds=30)
    assert not result.dispatched, relative
    rows.append({"case":relative,"refused":True})
    path.unlink()
managed = Path("/etc/claude-code/managed-settings.json")
managed.parent.mkdir(parents=True, exist_ok=True)
assert not managed.exists()
try:
    managed.write_text('{"env":{"ANTHROPIC_BASE_URL":"http://127.0.0.1:9"}}')
    result = run_claude_session("must never infer", direct=True, read_only=True, subscription_only=True, cwd=str(project), timeout_seconds=30)
    assert not result.dispatched and "managed" in result.error
    rows.append({"case":"managed-gateway","refused":True})
finally:
    managed.unlink()
assert not (root / "helper-count").exists()
# Inherit mode must retain user/sidecar authentication without loading hooks or
# permissions. The helper settings travel on an anonymous inherited descriptor.
from forge.core.reactive.reviewer_settings import inherited_auth_settings, auth_settings_descriptor
from forge.core.reactive.watchdog import run_guarded
for p in (project / ".claude/settings.json", project / ".claude/settings.local.json"):
    p.unlink()
(root / ".claude/settings.json").write_text(json.dumps({"apiKeyHelper":str(helper), "hooks":{"SessionStart":[]}}))
inherited = dict(clean)
selected = inherited_auth_settings(inherited, cwd=str(project), direct=False)
assert selected == {"apiKeyHelper":str(helper)}
with auth_settings_descriptor(selected) as (args, descriptors):
    result = run_guarded(["claude", *READ_ONLY_FLAGS, *args, "auth", "status", "--json"], input="", env=inherited, cwd=str(project), timeout=20, pass_fds=descriptors)
assert result.returncode == 0, result.stderr
inherited_status = json.loads(result.stdout)
assert inherited_status["authMethod"] == "api_key_helper", inherited_status
rows.append({"case":"inherited-user-or-sidecar-helper", "authMethod":inherited_status["authMethod"]})
version = subprocess.check_output(["claude", "--version"], text=True).strip()
print(json.dumps({"platform":"linux", "claude_version":version, "synthetic_only":True, "control":control, "clean":clean_status, "rows":rows, "helper_invocations":0}))
"""


@pytest.mark.parametrize("legacy_metadata", [True, False])
def test_disposable_auth_location_matrix(forge_workspace: ContainerLike, legacy_metadata: bool):
    # An explicit compatibility run may select an older supported reviewer when
    # the host-matched Linux binary cannot start on the container architecture.
    if version := os.environ.get("FORGE_AUTH_TEST_CLAUDE_VERSION"):
        package = shlex.quote("@anthropic-ai/claude-code@" + version)
        installed = forge_workspace.exec(f"npm install --prefix /tmp/auth-reviewer {package}", timeout=120)
        assert installed.returncode == 0, installed.stderr
        selected = forge_workspace.exec(
            "ln -sfn /tmp/auth-reviewer/node_modules/.bin/claude /usr/local/bin/claude-real"
        )
        assert selected.returncode == 0, selected.stderr
    setup_real_claude(forge_workspace, session_name="auth-matrix")
    probe = (
        _PROBE
        if legacy_metadata
        else _PROBE.replace('"organizationType":"claude_max"', '"billingType":"stripe_subscription"')
    )
    written = forge_workspace.write_file("/tmp/b1-auth-matrix.py", probe, mode=0o600)
    assert written.returncode == 0, written.stderr
    result = forge_workspace.exec("/forge/.venv/bin/python /tmp/b1-auth-matrix.py", timeout=100)
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout.strip().splitlines()[-1])
    assert evidence["helper_invocations"] == 0
    print(json.dumps(evidence))
