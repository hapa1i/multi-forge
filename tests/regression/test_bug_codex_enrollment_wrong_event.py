"""Regression: --verify-enrollment used event-agnostic registration identity.

Bug: ``_read_user_scope_registration`` checked
``cmd in read_codex_registration().commands_registered`` -- the event-AGNOSTIC
``_collect_commands`` reporting set. A ``forge hook codex-session-start`` registered under
the WRONG event (e.g. PreToolUse) then read as "registered", so the probe burned a real
``codex exec`` turn and the advice misdiagnosed a wrong-event entry as "not trust-enrolled".

Fix: ``codex_registration_pairs`` (event-aware ``(event, command)``) in
install/codex_hooks.py; ``_read_user_scope_registration`` checks ``("SessionStart", cmd)``.
"""

from __future__ import annotations

import pytest

import forge.install.codex_hooks as ch
from forge.install.codex_hooks import codex_registration_pairs

pytestmark = pytest.mark.regression

_CMD = "forge hook codex-session-start"


def _write_registration(path, event: str) -> None:
    path.write_text(f'[[hooks.{event}]]\n[[hooks.{event}.hooks]]\ntype = "command"\ncommand = "{_CMD}"\ntimeout = 60\n')


def test_registration_pairs_are_event_aware(tmp_path) -> None:
    cfg = tmp_path / "config.toml"
    _write_registration(cfg, "PreToolUse")  # registered, but under the wrong event
    pairs = codex_registration_pairs(cfg)
    assert ("PreToolUse", _CMD) in pairs
    assert ("SessionStart", _CMD) not in pairs


def test_registration_pairs_missing_or_invalid_config_is_empty(tmp_path) -> None:
    assert codex_registration_pairs(tmp_path / "absent.toml") == set()
    bad = tmp_path / "bad.toml"
    bad.write_text("definitely = = not [[[ valid toml")
    assert codex_registration_pairs(bad) == set()


def test_wrong_event_registration_not_counted_as_enrolled(tmp_path, monkeypatch) -> None:
    from forge.core.ops.codex_enrollment import _read_user_scope_registration

    cfg = tmp_path / "config.toml"
    _write_registration(cfg, "PreToolUse")
    monkeypatch.setattr(ch, "get_codex_config_path", lambda _scope: cfg)
    _path, registered = _read_user_scope_registration()
    assert registered is False


def test_correct_event_registration_is_counted_as_enrolled(tmp_path, monkeypatch) -> None:
    from forge.core.ops.codex_enrollment import _read_user_scope_registration

    cfg = tmp_path / "config.toml"
    _write_registration(cfg, "SessionStart")
    monkeypatch.setattr(ch, "get_codex_config_path", lambda _scope: cfg)
    _path, registered = _read_user_scope_registration()
    assert registered is True
