"""Container-boundary coverage for the Wave 8 Batch 3 policy CLI contracts."""

from __future__ import annotations

import json
import shlex

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


def test_policy_check_rejects_ambiguous_content_sources(
    mock_claude_workspace: ContainerLike,
) -> None:
    result = mock_claude_workspace.exec(
        "cd /workspace && printf '%s' '+++ b/README.md\n+changed\n' "
        "| forge policy check --bundle tdd --file README.md --diff"
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "Options --file and --diff cannot be used together" in result.stderr


def test_policy_check_evaluates_every_file_in_diff(
    mock_claude_workspace: ContainerLike,
) -> None:
    diff = (
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1 +1,2 @@\n"
        " # Test workspace\n"
        "+Harmless documentation.\n"
        "diff --git a/src/main.py b/src/main.py\n"
        "--- /dev/null\n"
        "+++ b/src/main.py\n"
        "@@ -0,0 +1 @@\n"
        "+if TYPE_CHECKING:\n"
    )
    result = mock_claude_workspace.exec(
        "cd /workspace && printf '%s' "
        f"{shlex.quote(diff)} | forge policy check --bundle coding_standards --diff --json"
    )

    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["files_checked"] == 2
    assert any(violation["file_path"] == "src/main.py" for violation in payload["violations"])


def test_missing_supervisor_enabling_actions_fail(
    mock_claude_workspace: ContainerLike,
) -> None:
    created = mock_claude_workspace.exec("cd /workspace && forge session start worker --no-proxy --no-launch")
    assert created.returncode == 0, created.stderr

    for command in (
        "forge policy supervisor on --session worker",
        "forge policy supervisor cascade on --session worker",
    ):
        result = mock_claude_workspace.exec(f"cd /workspace && {command}")
        assert result.returncode == 1
        assert result.stdout == ""
        assert "No supervisor configured" in result.stderr
        assert "forge policy supervisor set <target>" in result.stderr


def test_direct_policy_check_accepts_the_shared_bundle_vocabulary(
    mock_claude_workspace: ContainerLike,
) -> None:
    payload = json.dumps({"prompt": "%policy check --bundle tdd", "transcript_path": ""})
    result = mock_claude_workspace.exec(f"cd /workspace && printf '%s' '{payload}' | forge hook user-prompt-submit")

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "decision": "block",
        "passed": True,
        "reason": "No unstaged changes to check.",
    }


@pytest.mark.parametrize("surface", ["terminal", "direct", "raw"])
def test_policy_disable_revokes_jev_and_reset_recovery_works(
    mock_claude_workspace: ContainerLike, surface: str
) -> None:
    created = mock_claude_workspace.exec("cd /workspace && forge session start consent-worker --no-proxy --no-launch")
    assert created.returncode == 0, created.stderr
    result = mock_claude_workspace.exec(f"""cd /forge && uv run python - <<'PY'
import json
import os
import re
import shlex
import subprocess
from copy import deepcopy
from forge.policy.rule_pack.consent import BUNDLE_NAME, build_acknowledgment, has_acknowledgment
from forge.session import SessionStore
from forge.session.effective import compute_effective_intent
from forge.session.models import PolicyIntent

os.chdir('/workspace')
os.environ['FORGE_SESSION'] = 'consent-worker'
os.environ['FORGE_FORGE_ROOT'] = '/workspace'
os.environ['COLUMNS'] = '500'
store = SessionStore('/workspace', 'consent-worker')
state = store.read()
config = {{'pack_version': 'candidate-1', 'model': 'typesafe/jev-1.13'}}
config['acknowledgment'] = build_acknowledgment(state, config, acknowledge_paid_data_sharing=True)
state.intent.policy = PolicyIntent(
    enabled=True, bundles=['tdd', BUNDLE_NAME],
    bundle_config={{'tdd': {{'strict': False}}, BUNDLE_NAME: config}},
)
state.overrides = {{
    'policy': {{'enabled': True, 'bundle_config': {{BUNDLE_NAME: deepcopy(config)}}, 'fail_mode': 'closed'}},
    'memory': {{'auto_recall': False}},
}}
store.write(state)

def run(args, payload=None):
    return subprocess.run(['forge', *args], input=payload, capture_output=True, text=True)

surface = '{surface}'
if surface == 'direct':
    disabled = run(['hook', 'user-prompt-submit'], json.dumps({{'prompt': '%policy disable', 'transcript_path': ''}}))
    assert json.loads(disabled.stdout)['reason'] == 'Policy enforcement disabled'
elif surface == 'terminal':
    disabled = run(['policy', 'disable', '--session', 'consent-worker'])
else:
    disabled = run(['session', 'set', 'policy.enabled', 'false', '--session', 'consent-worker'])
assert disabled.returncode == 0, disabled.stderr
state = store.read()
assert not compute_effective_intent(state).policy.enabled
assert not has_acknowledgment(state, state.intent.policy.bundle_config[BUNDLE_NAME])
assert 'acknowledgment' not in state.overrides['policy']['bundle_config'][BUNDLE_NAME]
assert state.intent.policy.bundle_config['tdd'] == {{'strict': False}}
assert state.overrides['memory'] == {{'auto_recall': False}}
assert state.overrides['policy']['fail_mode'] == 'closed'

reset = run(['session', 'reset', '--session', 'consent-worker'])
if surface == 'terminal':
    assert reset.returncode == 0, reset.stderr
else:
    assert reset.returncode == 1
    assert 'activation is not available' in reset.stderr
    commands = [shlex.split(command) for command in re.findall(r"'(forge [^']+)'", reset.stderr)]
    assert commands == [
        ['forge', 'policy', 'disable', '--session', 'consent-worker'],
        ['forge', 'session', 'reset', '--session', 'consent-worker'],
    ], repr(reset.stderr)
    for command in commands:
        recovered = run(command[1:])
        assert recovered.returncode == 0, recovered.stderr
state = store.read()
assert state.overrides == {{}}
assert not state.intent.policy.enabled
assert not has_acknowledgment(state, state.intent.policy.bundle_config[BUNDLE_NAME])
print('disable-recovery-ok')
PY""")
    assert result.returncode == 0, result.stderr
    assert "disable-recovery-ok" in result.stdout
