"""Real-codex end-to-end smoke for the shadow-curation codex arm (epic consumer_lanes T6b).

Spawns the host ``codex exec`` binary ONCE through the full shadow-curation codex arm that the
hermetic unit tests can only mock: ``read_fresh_codex_preflight`` (cached) ->
``prepare_codex_request`` -> ``CodexHeadlessInvoker`` -> real ``codex exec`` (read-only) ->
``persist_curation_report`` -> the invoker's ``emit_codex_usage`` + upstream row. CLAUDE.md mandates
an integration test for any path that spawns a real subprocess.

Billed: one small inlined curation prompt, ``read-only`` sandbox (no writes). Never skips -- fails
loudly if codex is not installed/authenticated (the project's no-skip policy). Shared codex-auth,
preflight, and git-root fixtures live in ``conftest.py``.

Run via: ``./scripts/test-integration.sh tests/integration/session/test_shadow_curation_codex_smoke.py -v``
or ``uv run pytest -m slow tests/integration/session/test_shadow_curation_codex_smoke.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.core.runtime.codex_preflight import CodexPreflight
from forge.core.telemetry.upstream import read_upstream_outcomes
from forge.core.usage.ledger import read_usage_events
from forge.session.models import LaneRecord
from forge.session.shadow_curation import ShadowEntry, run_shadow_curation

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_CODEX_LANE_RECORD = LaneRecord("codex", "chatgpt", "gpt-5-codex")


def test_shadow_curation_codex_arm_real_dispatch(
    codex_ready_cached: CodexPreflight, codex_git_forge_root: Path
) -> None:
    """run_shadow_curation on the codex lane spawns real codex, persists a report from its stdout,
    fires the freeze hook, and emits exactly one runtime=codex/subscription_quota usage event (and no
    upstream-outcome row, since that log is failure-biased and this run succeeds)."""
    tmp_path = codex_git_forge_root

    entries = [
        ShadowEntry(
            official="docs/notes.md",
            shadow_path=".forge/memory/shadow_docs_notes.md",
            strategy="generic",
            session="smoke",
            forge_root=str(tmp_path),
            content="- [ ] Cache the codex preflight read so the hot path avoids a ~20s codex doctor.",
        )
    ]
    freeze_calls: list[int] = []

    result = run_shadow_curation(
        session_name="codex-curation-smoke",
        forge_root=tmp_path,
        official_path="docs/notes.md",
        official_content="# Notes\n\nExisting guidance, with no preflight-caching note yet.\n",
        shadow_entries=entries,
        lane_record=_CODEX_LANE_RECORD,
        timeout_seconds=180,
        on_dispatch=lambda: freeze_calls.append(1),
    )

    # Real codex produced a report from its stdout; the freeze fired on the real dispatch.
    assert result.success, f"error={result.error!r} stdout={result.stdout[:300]!r}"
    assert result.report_path is not None and result.report_path.exists()
    assert result.report_path.read_text(encoding="utf-8").strip()
    assert result.error is None
    assert freeze_calls == [1]

    # Exactly one usage event for this run, on the codex lane + subscription billing (auto-emitted
    # by the invoker, NOT the claude-arm emitter).
    events = read_usage_events(command="curation", session="codex-curation-smoke")
    assert len(events) == 1, events
    event = events[0]
    assert event.runtime == "codex"
    assert event.billing_mode == "subscription_quota"
    assert event.route == "codex_exec"

    # No upstream-outcome row on SUCCESS: should_record_upstream_outcome() is failure-biased
    # (a success persists only under upstream_event_volume="all"). The pinned
    # operation="memory.shadow_curation" that would label the row on a failure is covered by the unit
    # tests (the Attribution + the claude-path failure row); forcing a real codex failure here to
    # exercise it would be flaky and burn quota.
    assert read_upstream_outcomes(session="codex-curation-smoke", command="curation") == []
