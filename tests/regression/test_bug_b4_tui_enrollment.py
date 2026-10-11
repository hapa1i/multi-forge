"""Codex's TUI notice counter must not invalidate otherwise identical hook enrollment."""

import hashlib
import json
from pathlib import Path

import pytest

from forge.core.runtime import codex_turn_enrollment as enrollment
from forge.install.codex_hooks import get_builtin_codex_entries, render_codex_block

pytestmark = pytest.mark.regression


def test_tui_counter_preserves_receipt_but_runtime_settings_invalidate_it(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge"))
    config = tmp_path / "codex/config.toml"
    config.parent.mkdir()
    hooks = render_codex_block(get_builtin_codex_entries())
    config.write_text(hooks + '\n[tui.model_availability_nux]\n"gpt-6.1-sol" = 2\n')
    binary = tmp_path / "codex-fixture"
    binary.write_bytes(b"hermetic fake executable")
    identity = {
        "executable": str(binary),
        "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "version": "0.162.1",
    }
    receipt = enrollment.receipt_path()
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps({"schema": 1, "events": list(enrollment.EVENTS), "config": enrollment.config_identity(), **identity})
    )
    assert enrollment.verified(identity)
    config.write_text(hooks + '\n[tui.model_availability_nux]\n"gpt-6.1-sol" = 3\n')
    assert enrollment.verified(identity)
    config.write_text(config.read_text() + "\n[features]\nhooks = false\n")
    assert not enrollment.verified(identity)
