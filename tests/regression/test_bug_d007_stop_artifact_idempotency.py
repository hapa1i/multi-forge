"""Regression for D007: Stop appended duplicate transcript records and clobbered malformed state.

The Stop artifact copy is UUID-idempotent on disk, but its manifest writer used an
append-only helper that grew ``confirmed.artifacts.transcripts`` on every Stop and
replaced a non-list durable value with a fresh list.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.hooks import hooks
from forge.session import SessionStore, create_session_state

pytestmark = pytest.mark.regression


def _store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SessionStore:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge-home"))
    monkeypatch.setenv("FORGE_SESSION", "artifact-session")
    monkeypatch.setenv("FORGE_FORGE_ROOT", str(tmp_path))
    store = SessionStore(str(tmp_path), "artifact-session")
    store.write(create_session_state("artifact-session", worktree_path=str(tmp_path)))
    return store


def _invoke_stop(transcript: Path, session_id: str) -> dict[str, object]:
    result = CliRunner().invoke(
        hooks,
        ["stop"],
        input=json.dumps(
            {
                "hook_event_name": "Stop",
                "session_id": session_id,
                "transcript_path": str(transcript),
            }
        ),
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_repeated_stop_refreshes_one_record_without_losing_distinct_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    distinct = {
        "captured_at": "2026-08-05T00:00:00Z",
        "reason": "rollover",
        "source_path": "/tmp/distinct.jsonl",
        "session_id": "distinct-uuid",
        "copied_path": ".forge/artifacts/artifact-session/transcripts/distinct-uuid.jsonl",
        "copied": True,
    }
    state = store.read()
    state.confirmed.artifacts["transcripts"] = [distinct]
    store.write(state)

    transcript = tmp_path / "active.jsonl"
    transcript.write_text("first\n", encoding="utf-8")
    assert _invoke_stop(transcript, "active-uuid")["success"] is True

    transcript.write_text("second\n", encoding="utf-8")
    assert _invoke_stop(transcript, "active-uuid")["success"] is True

    entries = store.read().confirmed.artifacts["transcripts"]
    assert isinstance(entries, list)
    assert [entry["session_id"] for entry in entries] == ["distinct-uuid", "active-uuid"]
    active = entries[-1]
    assert active["reason"] == "stop"
    assert (tmp_path / active["copied_path"]).read_text(encoding="utf-8") == "second\n"


@pytest.mark.parametrize(
    "malformed",
    [{"unexpected": "mapping"}, None],
    ids=["mapping", "null"],
)
def test_stop_surfaces_non_list_transcript_state_without_clobbering_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, malformed: object
) -> None:
    store = _store(tmp_path, monkeypatch)
    state = store.read()
    state.confirmed.artifacts["transcripts"] = malformed
    store.write(state)

    transcript = tmp_path / "active.jsonl"
    transcript.write_text("content\n", encoding="utf-8")
    output = _invoke_stop(transcript, "active-uuid")

    assert output["action"] == "partial"
    assert output["manifest_updated"] is False
    assert "confirmed.artifacts.transcripts" in str(output["manifest_error"])
    assert "Forge left it unchanged" in str(output["manifest_error"])
    assert store.read().confirmed.artifacts["transcripts"] == malformed
