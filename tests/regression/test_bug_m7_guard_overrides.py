"""Regression tests for M7: %guard commands must write overrides, not mutate intent.

Bug: UserPromptSubmit %guard enable/disable mutated SessionState.intent.policy in-place.
Fix: %guard writes SessionState.overrides.policy instead, preserving intent as the baseline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.hooks import hooks
from forge.session import SessionStore, create_session_state
from forge.session.models import PolicyIntent

pytestmark = pytest.mark.regression


def _make_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SessionStore:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORGE_SESSION", "test-session")
    return SessionStore(str(tmp_path), "test-session")


def test_guard_enable_sets_overrides_not_intent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """%guard enable tdd sets overrides.policy and preserves intent.policy."""
    store = _make_store(tmp_path, monkeypatch)
    manifest = create_session_state(
        "test-session",
        proxy_template="test-family",
        proxy_base_url="http://localhost:8080",
    )
    store.write(manifest)

    runner = CliRunner()
    payload = {"prompt": "%guard enable tdd", "transcript_path": ""}
    result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out["decision"] == "block"

    updated = store.read()
    policy_overrides = updated.overrides.get("policy", {})
    assert policy_overrides["enabled"] is True
    assert policy_overrides["bundles"] == ["tdd"]
    assert policy_overrides["fail_mode"] == "open"

    assert updated.intent.policy is None or updated.intent.policy.enabled is None


def test_guard_disable_preserves_intent_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """%guard disable after baseline intent preserves intent and sets overrides.enabled=False."""
    store = _make_store(tmp_path, monkeypatch)
    manifest = create_session_state(
        "test-session",
        proxy_template="test-family",
        proxy_base_url="http://localhost:8080",
    )
    manifest.intent.policy = PolicyIntent(enabled=True, bundles=["tdd"], fail_mode="open")
    store.write(manifest)

    runner = CliRunner()
    payload = {"prompt": "%guard disable", "transcript_path": ""}
    runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

    updated = store.read()
    assert updated.overrides.get("policy", {}).get("enabled") is False
    assert updated.intent.policy == PolicyIntent(enabled=True, bundles=["tdd"], fail_mode="open")
