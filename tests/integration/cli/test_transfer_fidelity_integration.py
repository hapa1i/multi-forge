"""Exercise transfer regeneration, review and fresh launch with native tool-result shapes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]

FORGE = (
    "cd /workspace && PYTHON_DOTENV_DISABLED=1 ANTHROPIC_API_KEY=sk-ant-fixture " "EDITOR=/tmp/fidelity-editor forge "
)


@pytest.mark.parametrize("strategy", ["structured", "full"])
def test_transfer_fidelity_reaches_reviewed_child(mock_claude_workspace: ContainerLike, strategy: str) -> None:
    workspace = mock_claude_workspace
    transcript = (Path(__file__).resolve().parents[2] / "fixtures" / "transcript_delegation.jsonl").read_text()
    written = workspace.write_file("/workspace/delegation.jsonl", transcript)
    assert written.returncode == 0, written.stderr
    published = workspace.exec("""cd /forge && PYTHON_DOTENV_DISABLED=1 /forge/.venv/bin/python - <<'PY'
from forge.session import IndexStore
from forge.session.models import create_session_state
from tests.fixtures.session_state import publish_session

state = create_session_state("fidelity-parent", worktree_path="/workspace")
state.confirmed.claude_session_id = "00000000-0000-4000-8000-000000000001"
state.confirmed.confirmed_by = "hook:SessionStart:startup"
state.confirmed.transcript_path = "/workspace/delegation.jsonl"
publish_session(IndexStore(), state, "/workspace", forge_root="/workspace")
PY""")
    assert published.returncode == 0, published.stdout + published.stderr
    editor = workspace.write_file("/tmp/fidelity-editor", '#!/bin/sh\nprintf "\\nReviewed transfer.\\n" >> "$1"\n')
    assert editor.returncode == 0, editor.stderr
    executable = workspace.exec("chmod +x /tmp/fidelity-editor")
    assert executable.returncode == 0, executable.stderr

    regenerated = workspace.exec(FORGE + f"session transfer regenerate fidelity-parent --strategy {strategy}")
    assert regenerated.returncode == 0, regenerated.stdout + regenerated.stderr
    shown = workspace.exec(FORGE + "session transfer show fidelity-parent --json")
    assert shown.returncode == 0, shown.stdout + shown.stderr
    content = json.loads(shown.stdout)["content"]
    assert "Preserve the review note." in content
    assert "[result: The parser preserves the first finding.\nThe second finding follows the image.]" in content
    if strategy == "full":
        assert "Agent(type=Explore, description=Inspect transfer fidelity, prompt=" in content
        assert "SendMessage(recipient=reviewer, summary=Transfer findings, content=" in content
    else:
        assert "Agent(" not in content
        assert "SendMessage(" not in content
    assert "SU1BR0VfUEFZTE9BRA==" not in content

    resumed = workspace.exec(
        FORGE + f"session resume fidelity-parent --fresh --review --strategy {strategy} --child-name fidelity-child",
        timeout=30,
    )
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    child_path = "/workspace/.forge/prev_sessions/fidelity-parent/children/fidelity-child.md"
    child = workspace.read_file(child_path)
    assert "Preserve the review note." in child
    assert "[result: The parser preserves the first finding.\nThe second finding follows the image.]" in child
    if strategy == "full":
        assert "Agent(type=Explore" in child
        assert "SendMessage(recipient=reviewer" in child
    else:
        assert "Agent(" not in child
        assert "SendMessage(" not in child
    assert "SU1BR0VfUEFZTE9BRA==" not in child
    launch_path = "/workspace/.forge/launch-context/fidelity-child.md"
    assert f"--append-system-prompt-file {launch_path}" in workspace.read_file("/tmp/claude_invocations.log")
    launch = workspace.read_file(launch_path)
    assert "The second finding follows the image." in launch
    assert "Reviewed transfer." in launch

    edited = workspace.exec(FORGE + "session transfer edit fidelity-parent --child fidelity-child")
    assert edited.returncode == 0, edited.stdout + edited.stderr
    child_view = workspace.exec(FORGE + "session transfer show fidelity-parent --child fidelity-child --json")
    assert child_view.returncode == 0, child_view.stdout + child_view.stderr
    assert "Reviewed transfer." in json.loads(child_view.stdout)["content"]

    late_result = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {"type": "text", "text": "Additional review note"},
                {"type": "tool_result", "content": [{"type": "text", "text": "Late transfer finding"}]},
            ],
        },
    }
    updated = workspace.write_file("/workspace/delegation.jsonl", transcript + json.dumps(late_result) + "\n")
    assert updated.returncode == 0, updated.stderr
    regenerated = workspace.exec(FORGE + f"session transfer regenerate fidelity-parent --strategy {strategy}")
    assert regenerated.returncode == 0, regenerated.stdout + regenerated.stderr
    difference = workspace.exec(FORGE + "session transfer diff fidelity-parent --child fidelity-child")
    assert difference.returncode == 0, difference.stdout + difference.stderr
    assert "Late transfer finding" in difference.stdout
    assert workspace.read_file(child_path) == child


def test_tool_heavy_structured_transfer_launches_on_linux(clean_workspace: ContainerLike) -> None:
    result = clean_workspace.exec(r"""cd /forge && PYTHON_DOTENV_DISABLED=1 /forge/.venv/bin/python - <<'CHECK'
import json
import os
from pathlib import Path

from forge.core.ops.codex_bridge import compose_codex_interactive_context
from forge.core.reactive.env import RunIdentity
from forge.core.runtime.codex_preflight import CodexPreflight
from forge.session.codex_invoke import invoke_codex_interactive
from forge.session.transfer import _generate_structured_context
from tests.fixtures.transcript_delegation import tool_heavy_transcript

transcript = Path('/workspace/busy.jsonl')
transcript.write_text('\n'.join(json.dumps(entry) for entry in tool_heavy_transcript()))
content, warnings = _generate_structured_context('parent', ['parent'], transcript, None, None, None)
assert not warnings
prompt = compose_codex_interactive_context(content)

bin_dir = Path('/workspace/fidelity-bin')
bin_dir.mkdir()
shim = bin_dir / 'codex'
shim.write_text('''#!/bin/sh
if [ "$1" = "--version" ]; then
    echo 'codex-cli 0.161.0'
    exit 0
fi
printf '%s' "$3" > /workspace/codex-prompt.txt
''')
shim.chmod(0o755)
os.environ['PATH'] = str(bin_dir) + os.pathsep + os.environ['PATH']
preflight = CodexPreflight(
    installed=True, version='0.161.0', version_ok=True,
    auth_method='chatgpt_tokens', auth_source='codex_store', billing_mode='subscription_quota',
    ready=True, blocking_reason=None, hook_seam='enrollment_gated',
    proxy_responses='native_direct', doctor_status='ok',
)
code = invoke_codex_interactive(
    preflight=preflight, session_name='fidelity-child', forge_root='/workspace', cwd='/workspace',
    run_identity=RunIdentity(run_id='run_aaaaaaaaaaaa', parent_run_id=None, root_run_id='run_aaaaaaaaaaaa'),
    initial_prompt=prompt,
)
assert code == 0
assert Path('/workspace/codex-prompt.txt').read_text() == prompt
assert 'Review complete' in prompt
assert 'raw output' not in prompt
CHECK""")
    assert result.returncode == 0, result.stdout + result.stderr
