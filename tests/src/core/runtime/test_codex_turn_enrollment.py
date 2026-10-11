"""Enrollment requires the complete event set from one admitted measured turn."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from forge.core.runtime import codex_turn_enrollment as enrollment
from forge.install.codex_hooks import get_builtin_codex_entries, render_codex_block
from tests.fixtures.stop_review import THREAD


@pytest.fixture
def probe(tmp_path: Path, monkeypatch):
    codex = tmp_path / "codex"
    codex.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex))
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge"))
    monkeypatch.setenv("FORGE_SESSION", "forge-enroll-probe")
    monkeypatch.setenv("FORGE_FORGE_ROOT", str(tmp_path))
    monkeypatch.setenv(enrollment.PROBE_ENV, "a" * 32)
    monkeypatch.setattr(enrollment, "stop_review_supported", lambda env: True)
    binary = tmp_path / "native-codex"
    binary.write_bytes(b"test binary")
    identity = {
        "executable": str(binary),
        "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "version": "0.162.1",
    }
    monkeypatch.setenv(enrollment.CODEX_EXECUTOR_IDENTITY_VAR, json.dumps(identity))
    (codex / "config.toml").write_text(render_codex_block(get_builtin_codex_entries()))
    data = {"cwd": str(tmp_path), "session_id": THREAD, "turn_id": "01900001-0000-7000-8000-000000000001"}
    return tmp_path, identity, data


def observe_all(probe):
    root, identity, data = probe
    for event in enrollment.EVENTS:
        assert enrollment.observe(dict(data, hook_event_name=event))


def test_missing_then_complete_observations_and_binary_replacement(probe) -> None:
    root, identity, data = probe
    assert enrollment.observe(dict(data, hook_event_name="UserPromptSubmit"))
    assert not enrollment.publish(root, "a" * 32)
    observe_all(probe)
    assert enrollment.publish(root, "a" * 32)
    assert enrollment.verified(identity) and enrollment.verified()
    Path(identity["executable"]).write_bytes(b"replacement")
    assert not enrollment.verified()


def test_mixed_turns_and_inherited_identity_are_not_enrollment(probe, monkeypatch) -> None:
    root, identity, data = probe
    observe_all(probe)
    enrollment.observe(dict(data, hook_event_name="Stop", turn_id="01900001-0000-7000-8000-000000000002"))
    assert not enrollment.publish(root, "a" * 32)
    monkeypatch.setattr(enrollment, "stop_review_supported", lambda env: False)
    assert not enrollment.observe(dict(data, hook_event_name="Stop"))
    assert not enrollment.receipt_path().exists()


def test_trust_or_definition_change_invalidates_receipt(probe) -> None:
    root, identity, _ = probe
    observe_all(probe)
    assert enrollment.publish(root, "a" * 32)
    config = root / "codex/config.toml"
    config.write_text(config.read_text() + '\n[hooks.state]\ntrusted_hash = "changed"\n')
    assert not enrollment.verified(identity)
    rows = [replace(e, timeout=5) if e.event == "Stop" else e for e in get_builtin_codex_entries()]
    config.write_text(render_codex_block(tuple(rows)))
    with pytest.raises(ValueError, match="60-second"):
        enrollment.config_identity()
