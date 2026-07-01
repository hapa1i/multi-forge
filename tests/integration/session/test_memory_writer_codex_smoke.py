"""Real-codex end-to-end smoke for the memory-writer codex augment arm (epic consumer_lanes T6c).

Spawns the host ``codex exec`` binary ONCE through the full augment arm the hermetic unit tests can
only mock: ``read_fresh_codex_preflight`` (cached) -> ``prepare_codex_request`` (sandbox
``workspace-write``) -> ``CodexHeadlessInvoker`` -> real ``codex exec`` -> edits the designated doc
in place + ``_persist_review_report`` -> the invoker's ``emit_codex_usage``. Proves the D1=A
acceptance: codex under ``workspace-write`` actually WRITES a repo file (the epic's first
write-granting lane) -- the Phase 0 probe's finding, now exercised through the shipped arm.

Billed: one small augment prompt, ``workspace-write`` sandbox (edits one stub doc under tmp).
``review-only`` is unit-covered and shares the ``read-only`` shape already E2E'd by
``test_shadow_curation_codex_smoke.py``. Never skips (no-skip policy). Shared codex-auth, preflight,
and git-root fixtures live in ``conftest.py``.

Run via: ``./scripts/test-integration.sh tests/integration/session/test_memory_writer_codex_smoke.py -v``
or ``uv run pytest -m slow tests/integration/session/test_memory_writer_codex_smoke.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.core.runtime.codex_preflight import CodexPreflight
from forge.core.telemetry.upstream import read_upstream_outcomes
from forge.core.usage.ledger import read_usage_events
from forge.session.memory_writer import memory_report_dir, run_memory_writer
from forge.session.models import DesignatedDoc, LaneRecord, MemoryWriterConfig

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_CODEX_LANE_RECORD = LaneRecord("codex", "chatgpt", "gpt-5-codex")
_SESSION = "codex-mw-smoke"
_TRANSCRIPT_REL = f".forge/artifacts/{_SESSION}/transcripts/uuid-smoke.jsonl"


def _write_transcript(path: Path) -> None:
    """A minimal 2-turn transcript carrying one clear, memory-worthy decision to capture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    turns = [
        {
            "requestId": "r1",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "We decided the codex memory-writer lane runs under workspace-write."}
                ],
            },
        },
        {
            "requestId": "r1",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Noted: workspace-write is the first write-granting Forge lane."}],
            },
        },
        {
            "requestId": "r2",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "Record that decision in the project state doc."}],
            },
        },
    ]
    path.write_text("\n".join(json.dumps(t) for t in turns) + "\n", encoding="utf-8")


def test_memory_writer_codex_augment_real_write(codex_ready_cached: CodexPreflight, codex_git_forge_root: Path) -> None:
    """augment on the codex lane spawns real codex under workspace-write, actually EDITS the
    designated doc in place (D1=A acceptance), persists a review report, fires the freeze hook, and
    emits exactly one runtime=codex/subscription_quota usage event -- with no upstream-outcome row on
    success (the outcome log is failure-biased, T6b/T6c)."""
    forge_root = codex_git_forge_root
    _write_transcript(forge_root / _TRANSCRIPT_REL)

    doc = forge_root / "docs" / "state.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    stub = "# Project State\n\n(no entries yet)\n"
    doc.write_text(stub, encoding="utf-8")
    freeze_calls: list[int] = []

    result = run_memory_writer(
        session_name=_SESSION,
        forge_root=forge_root,
        transcript_snapshot_rel=_TRANSCRIPT_REL,
        config=MemoryWriterConfig(enabled=True, min_turns=1, mode="augment"),
        designated_docs=[DesignatedDoc(path="docs/state.md", strategy="project-state")],
        lane_record=_CODEX_LANE_RECORD,
        timeout_seconds=240,
        on_dispatch=lambda: freeze_calls.append(1),
    )

    assert result is True
    assert freeze_calls == [1]

    # D1=A acceptance: codex under workspace-write actually wrote the in-project doc (auto-approved).
    after = doc.read_text(encoding="utf-8")
    assert after != stub, "codex did not modify the designated doc under workspace-write"
    assert after.strip(), "codex left the designated doc empty"

    # Both modes persist stdout to a review report (parity with the claude arm).
    reports = list(memory_report_dir(forge_root, _SESSION).glob("review-*.md"))
    assert reports, "no review report persisted"

    # Exactly one usage event on the codex lane + subscription billing (invoker auto-emit, not the
    # claude-arm emitter).
    events = read_usage_events(command="memory-writer", session=_SESSION)
    assert len(events) == 1, events
    event = events[0]
    assert event.runtime == "codex"
    assert event.billing_mode == "subscription_quota"
    assert event.route == "codex_exec"

    # No upstream-outcome row on SUCCESS: record_upstream_operation is failure-biased, so both arms
    # (claude's manual record, codex's invoker row) write nothing here under default volume.
    assert read_upstream_outcomes(session=_SESSION, command="memory-writer") == []
