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
    assert "Agent(type=Explore, description=Inspect transfer fidelity, prompt=" in content
    assert "SendMessage(recipient=reviewer, summary=Transfer findings, content=" in content
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
    assert "Agent(type=Explore" in child
    assert "SendMessage(recipient=reviewer" in child
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
            "content": [{"type": "tool_result", "content": [{"type": "text", "text": "Late transfer finding"}]}],
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
