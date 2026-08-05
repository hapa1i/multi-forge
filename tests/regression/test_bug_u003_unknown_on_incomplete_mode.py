"""Regression for U003: legacy unknown incomplete modes must not become blocks.

Root cause: the Stop verifier handled only ``warn`` and ``allow`` explicitly, so
every other ``on_incomplete`` string fell through to the blocking branch. Legacy
or hand-edited values could therefore acquire enforcement semantics by accident.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.cli.hooks.verification import _run_verification_check
from forge.session import SessionStore, create_session_state
from forge.session.models import VerificationConfig

pytestmark = pytest.mark.regression


def test_legacy_unknown_on_incomplete_is_visible_nonpassing_fail_open(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = create_session_state("legacy-verification", worktree_path=str(tmp_path))
    manifest.intent.verification = VerificationConfig(
        type="completion_promise",
        promise="COMPLETE",
        on_incomplete="re_inject",
    )
    store = SessionStore(str(tmp_path), manifest.name)
    store.write(manifest)
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("", encoding="utf-8")

    allow, message = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)

    assert allow is True and message is None
    diagnostic = capsys.readouterr().err
    assert "unknown legacy verification.on_incomplete" in diagnostic.lower()
    assert "re_inject" in diagnostic
    confirmed = store.read().confirmed.verification
    assert confirmed is not None
    assert confirmed.last_result == "misconfigured"
    assert confirmed.last_result != "passed"
