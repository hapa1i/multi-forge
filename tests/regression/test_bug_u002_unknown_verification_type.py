"""Regression for U002: legacy unknown verification types must be visible and fail open.

Root cause: the Stop verifier returned an unconditional allow for every unknown
``verification.type`` without a diagnostic or non-passing result, making stale or
hand-edited configuration indistinguishable from successful verification.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.cli.hooks.verification import _run_verification_check
from forge.session import SessionStore, create_session_state
from forge.session.models import VerificationConfig

pytestmark = pytest.mark.regression


def test_legacy_unknown_verification_type_is_visible_nonpassing_fail_open(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = create_session_state("legacy-verification", worktree_path=str(tmp_path))
    manifest.intent.verification = VerificationConfig(type="custom_command")
    store = SessionStore(str(tmp_path), manifest.name)
    store.write(manifest)
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("", encoding="utf-8")

    allow, message = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)

    assert allow is True and message is None
    diagnostic = capsys.readouterr().err
    assert "unknown legacy verification.type" in diagnostic.lower()
    assert "custom_command" in diagnostic
    confirmed = store.read().confirmed.verification
    assert confirmed is not None
    assert confirmed.last_result == "misconfigured"
    assert confirmed.last_result != "passed"
