"""M2: transfer summaries dropped list-form results and unlabeled delegation inputs."""

import json
from pathlib import Path

import pytest

from forge.session.transfer import _generate_full_context, _generate_structured_context

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("strategy", ["structured", "full"])
def test_transfer_retains_delegation_and_list_form_results(strategy):
    transcript = Path(__file__).resolve().parents[1] / "fixtures" / "transcript_delegation.jsonl"
    generate = _generate_structured_context if strategy == "structured" else _generate_full_context
    content, warnings = generate(
        parent_name="parent",
        lineage=["parent"],
        transcript_path=transcript,
        artifacts_path=None,
        proxy_template=None,
        latest_plan_path=None,
    )

    assert "[result: The parser preserves the first finding.\nThe second finding follows the image.]" in content
    assert "SU1BR0VfUEFZTE9BRA==" not in content
    if strategy == "full":
        assert (
            "Agent(type=Explore, description=Inspect transfer fidelity, prompt=Check list-form tool results" in content
        )
        assert "SendMessage(recipient=reviewer, summary=Transfer findings, content=Keep both text blocks" in content
        assert "[result: Message delivered.]" in content
    else:
        assert "Agent(" not in content
        assert "SendMessage(" not in content
        assert "Message delivered." not in content
    assert "Preserve the review note." in content
    assert warnings == []


@pytest.mark.parametrize("block_list", [False, True], ids=["string", "block-list"])
def test_supported_results_do_not_hide_neighboring_user_text(tmp_path, block_list):
    result = [{"type": "text", "text": "Worker finding"}] if block_list else "Worker finding"
    transcript = tmp_path / "mixed.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "agent-review", "content": result},
                        {"type": "text", "text": "Preserve this user note"},
                    ],
                }
            }
        )
        + "\n"
    )
    content, warnings = _generate_structured_context("parent", ["parent"], transcript, None, None, None)
    assert "**User**: Preserve this user note" in content
    assert "[result: Worker finding]" in content
    assert warnings == []
