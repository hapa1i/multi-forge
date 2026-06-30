"""Real-codex end-to-end smoke for the shadow-curation codex arm (epic consumer_lanes T6b).

Spawns the host ``codex exec`` binary ONCE through the full shadow-curation codex arm that the
hermetic unit tests can only mock: ``read_fresh_codex_preflight`` (cached) ->
``prepare_codex_request`` -> ``CodexHeadlessInvoker`` -> real ``codex exec`` (read-only) ->
``persist_curation_report`` -> the invoker's ``emit_codex_usage`` + upstream row. CLAUDE.md mandates
an integration test for any path that spawns a real subprocess.

Billed: one small inlined curation prompt, ``read-only`` sandbox (no writes). Never skips -- fails
loudly if codex is not installed/authenticated (the project's no-skip policy).

Run via: ``./scripts/test-integration.sh tests/integration/session/test_shadow_curation_codex_smoke.py -v``
or ``uv run pytest -m slow tests/integration/session/test_shadow_curation_codex_smoke.py``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from forge.core.runtime.codex_preflight import CodexPreflight, preflight_codex
from forge.core.runtime.codex_preflight_cache import write_codex_preflight_cache
from forge.core.telemetry.upstream import read_upstream_outcomes
from forge.core.usage.ledger import read_usage_events
from forge.session.models import LaneRecord
from forge.session.shadow_curation import ShadowEntry, run_shadow_curation

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_CODEX_LANE_RECORD = LaneRecord("codex", "chatgpt", "gpt-5-codex")

# Captured at import time -- BEFORE the autouse ``isolate_codex_home`` fixture overrides CODEX_HOME --
# so we can restore the host's real codex auth store for the real ``codex exec`` run.
_REAL_CODEX_HOME = os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")


@pytest.fixture
def real_codex_home(monkeypatch: pytest.MonkeyPatch) -> str:
    """Restore the host CODEX_HOME so codex sees the real ChatGPT login.

    The autouse ``isolate_codex_home`` fixture repoints CODEX_HOME at an empty temp dir (to keep
    installer tests off the real ``~/.codex``). A real ``codex exec`` on a ChatGPT subscription
    (``codex_store`` auth) needs the host store, so restore the import-time value for both the
    ``codex doctor`` probe and the spawned ``codex exec``. Without this, auth falls back to env-only
    and the probe reports "requires CODEX_API_KEY" even on a logged-in machine.
    """
    auth = Path(_REAL_CODEX_HOME) / "auth.json"
    if not auth.is_file():
        pytest.fail(f"no codex auth at {auth}. Run 'codex login --device-auth' (ChatGPT) or set CODEX_API_KEY.")
    monkeypatch.setenv("CODEX_HOME", _REAL_CODEX_HOME)
    return _REAL_CODEX_HOME


def _require_codex_ready_cached() -> CodexPreflight:
    """Live preflight (fail loud if not ready), then seed the cache the arm actually reads.

    The codex arm reads ``read_fresh_codex_preflight()`` (the cache), not the live probe -- and the
    autouse ``isolate_forge_home`` fixture points FORGE_HOME at a fresh temp dir, so the cache is
    empty until we write it here. codex auth lives in ``$CODEX_HOME`` (default ``~/.codex``), which
    FORGE_HOME isolation does not touch, so the real ChatGPT login is still used.
    """
    pf = preflight_codex()
    if not pf.ready:
        pytest.fail(f"codex not ready ({pf.blocking_reason}). Install + authenticate codex, then re-run.")
    write_codex_preflight_cache(pf)
    return pf


def _init_git_repo(path: Path) -> None:
    """codex exec refuses to run outside a git repo; a real forge_root is always one."""
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "smoke@test.local"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "smoke"], cwd=path, check=True)


def test_shadow_curation_codex_arm_real_dispatch(real_codex_home: str, tmp_path: Path) -> None:
    """run_shadow_curation on the codex lane spawns real codex, persists a report from its stdout,
    fires the freeze hook, and emits exactly one runtime=codex/subscription_quota usage event (and no
    upstream-outcome row, since that log is failure-biased and this run succeeds)."""
    _require_codex_ready_cached()
    _init_git_repo(tmp_path)

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
