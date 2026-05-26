"""Regression test: repeated Stop events must refresh the session transcript artifact.

Bug: Claude's Stop hook can fire multiple times for the same session UUID as a
conversation progresses. Forge wrote transcript artifacts to a UUID-named path
with `overwrite=False`, so the first-turn snapshot stayed frozen forever.

Walkthrough impact: section 10 rebuilt the search index from
`.forge/artifacts/.../transcripts/<uuid>.jsonl`, but that file only contained
the initial "hello!" turn and not the later guard demo content.

Fix: refresh the transcript artifact on repeated Stop/StopFailure captures so
manual rebuilds and async indexing see the latest session content.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.hooks import hooks
from forge.cli.main import main
from forge.session import SessionStore, create_session_state

pytestmark = pytest.mark.regression


def _append_text_entry(path: Path, *, role: str, text: str, timestamp: str) -> None:
    entry = {
        "type": role,
        "timestamp": timestamp,
        "message": {
            "role": role,
            "content": [{"type": "text", "text": text}],
        },
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def test_rebuild_index_sees_latest_turn_after_repeated_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Later turns must overwrite the earlier artifact snapshot for the same UUID."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()

    monkeypatch.chdir(project)
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge-home"))
    monkeypatch.setenv("FORGE_SESSION", "walkthrough-demo")

    session_name = "walkthrough-demo"
    session_id = "uuid-walkthrough-123"

    manifest = create_session_state(
        session_name,
        proxy_template="litellm-openai",
        proxy_base_url="http://localhost:8086",
    )
    store = SessionStore(str(project), session_name)
    store.write(manifest)

    transcript = project / "live-transcript.jsonl"
    _append_text_entry(
        transcript,
        role="user",
        text="hello!",
        timestamp="2026-03-20T17:28:09.134Z",
    )
    _append_text_entry(
        transcript,
        role="assistant",
        text="Hi! What do you want to work on?",
        timestamp="2026-03-20T17:28:13.115Z",
    )

    state = store.read()
    state.confirmed.transcript_path = str(transcript)
    state.confirmed.claude_session_id = session_id
    store.write(state)

    runner = CliRunner()
    payload = {
        "hook_event_name": "Stop",
        "transcript_path": str(transcript),
        "session_id": session_id,
    }

    first = runner.invoke(hooks, ["stop"], input=json.dumps(payload))
    assert first.exit_code == 0, first.output

    _append_text_entry(
        transcript,
        role="user",
        text="Create a new file src/greeting.py with a function that returns a greeting string with a rocket emoji",
        timestamp="2026-03-20T17:30:00.000Z",
    )
    _append_text_entry(
        transcript,
        role="assistant",
        text="I cannot add an emoji here because the guard blocks it, but I can help with a compliant greeting.",
        timestamp="2026-03-20T17:30:05.000Z",
    )

    second = runner.invoke(hooks, ["stop"], input=json.dumps(payload))
    assert second.exit_code == 0, second.output

    artifact = project / ".forge" / "artifacts" / session_name / "transcripts" / f"{session_id}.jsonl"
    assert artifact.is_file()
    artifact_text = artifact.read_text(encoding="utf-8")
    assert "emoji" in artifact_text
    assert "greeting.py" in artifact_text

    rebuilt = runner.invoke(main, ["search", "rebuild-index"])
    assert rebuilt.exit_code == 0, rebuilt.output
    assert "Indexed 1 transcripts." in rebuilt.output

    searched = runner.invoke(main, ["search", "query", "emoji"])
    assert searched.exit_code == 0, searched.output
    data = json.loads(searched.output)
    assert data["total_results"] == 1
    assert data["results"][0]["session_name"] == session_name
