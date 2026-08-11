"""Regression guard for the rejected D033 escape-hatch claim."""

from __future__ import annotations

import json
from pathlib import Path

import dacite
import pytest
from click.testing import CliRunner

from forge.cli.hooks.commands import hooks
from forge.session.effective import compute_effective_intent
from forge.session.models import VerificationConfig, create_session_state
from forge.session.store import SessionStore

pytestmark = pytest.mark.regression


def test_d033_cancel_verification_survives_malformed_unrelated_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The escape hatch falls back to raw intent when effective intent is malformed."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORGE_SESSION", "test-session")
    (tmp_path / ".claude").mkdir()

    manifest = create_session_state("test-session")
    manifest.intent.verification = VerificationConfig(promise="done", bypass=False)
    manifest.overrides = {"memory": {"tags": "not-a-list"}}
    with pytest.raises(dacite.DaciteError):
        compute_effective_intent(manifest, strict=False)

    store = SessionStore(str(tmp_path), "test-session")
    store.write(manifest)

    result = CliRunner().invoke(
        hooks,
        ["user-prompt-submit"],
        input=json.dumps({"prompt": "%cancel-verification"}),
    )

    assert result.exit_code == 0
    assert result.exception is None
    assert "bypass enabled" in json.loads(result.output)["reason"].lower()
    assert store.read().overrides["verification"]["bypass"] is True
