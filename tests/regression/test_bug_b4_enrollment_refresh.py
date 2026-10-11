"""B4: codex_enrollment deleted good receipts and fingerprinted unrelated preferences."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from forge.core.ops import codex_enrollment as operation
from forge.core.runtime import codex_turn_enrollment as enrollment
from forge.install.codex_hooks import get_builtin_codex_entries, render_codex_block
from tests.src.core.ops.test_codex_enrollment import _fake_result, _preflight

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("mode", ["failed", "incomplete", "exception"])
def test_probe_failure_preserves_existing_receipt(tmp_path: Path, monkeypatch, mode: str) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text('{"existing": "verified receipt"}')
    original = receipt.read_bytes()
    monkeypatch.setattr(enrollment, "receipt_path", lambda: receipt)
    callback = Mock(return_value=_fake_result(returncode=1 if mode == "failed" else 0))
    if mode == "exception":
        callback.side_effect = OSError("probe could not launch")
    monkeypatch.setattr("forge.core.invoker.CodexHeadlessInvoker.run", callback)
    try:
        operation._run_probe_turn(_preflight(), timeout_seconds=10)
    except OSError:
        assert mode == "exception"
    assert receipt.read_bytes() == original


def test_receipt_ignores_preferences_but_binds_hook_definitions_and_trust(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    config = tmp_path / "config.toml"
    hooks = render_codex_block(get_builtin_codex_entries())
    config.write_text(hooks)
    before = enrollment.config_identity()
    config.write_text(
        'model = "gpt-test"\nmodel_reasoning_effort = "low"\n'
        + hooks
        + '\n[tui]\nnotifications = false\n[mcp_servers.local]\ncommand = "example"\n'
    )
    assert enrollment.config_identity() == before
    config.write_text(config.read_text() + '\n[hooks.state]\ntrusted_hash = "new"\n')
    assert enrollment.config_identity() != before
    config.write_text(hooks + "\n[features]\nhooks = false\n")
    assert enrollment.config_identity() != before


def test_failed_atomic_publication_retains_previous_receipt(tmp_path: Path, monkeypatch) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text("old proof")
    monkeypatch.setattr(enrollment, "receipt_path", lambda: receipt)
    monkeypatch.setattr(enrollment, "config_identity", lambda: {"sha256": "test"})
    rows = tmp_path / ".forge/stop-enrollment"
    rows.mkdir(parents=True)
    for event in enrollment.EVENTS:
        (rows / f"{event}.json").write_text(
            json.dumps({"event": event, "nonce": "a" * 32, "config": {"sha256": "test"}})
        )
    monkeypatch.setattr("forge.core.state.io.os.replace", Mock(side_effect=OSError("disk failure")))
    assert not enrollment.publish(tmp_path, "a" * 32)
    assert receipt.read_text() == "old proof"
