"""Derivation refusals retain repair guidance after the CLI's initial parent read."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest

from forge.cli.session_lifecycle import _resume_fresh
from forge.cli.session_resume_modes import _resume_fresh_native, _resume_fresh_rewind
from forge.session import SessionManager, create_session_state
from forge.session.exceptions import (
    ForgeSessionError,
    ManifestCorruptedError,
    ManifestValidationError,
)


@pytest.mark.parametrize("mode", ["native", "rewind", "transfer"])
@pytest.mark.parametrize(
    "error",
    [
        ManifestCorruptedError("/project/.forge/sessions/parent/forge.session.json", "unknown override field"),
        ManifestCorruptedError(
            "/project/.forge/sessions/parent/forge.session.json",
            "unsupported schema version. Delete this session and recreate it.",
        ),
        ManifestValidationError("/project/.forge/sessions/parent/forge.session.json", ["schema_version"]),
    ],
)
def test_strict_manager_reread_failure_only_offers_repair(
    mode: str,
    error: ForgeSessionError,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The first CLI read succeeded, but the manager's authoritative read must
    # still use derivation recovery if the stored parent has since changed.
    state = create_session_state("parent", worktree_path="/project")
    manager = Mock(spec=SessionManager)
    manager.resume_session.side_effect = error
    monkeypatch.setenv("COLUMNS", "500")
    monkeypatch.setattr("forge.cli.session_resume_modes._resolve_context_limit", lambda _: 1000)
    monkeypatch.setattr("forge.cli.session_lifecycle._resolve_context_limit", lambda _: 1000)
    monkeypatch.setattr("forge.cli.session_lifecycle._resume_token_estimate_multiplier", lambda **_: 1.0)
    common: dict[str, Any] = {
        "manager": manager,
        "parent": "parent",
        "parent_state": state,
        "child_name": "child",
        "routing": None,
        "direct": True,
    }

    with pytest.raises(SystemExit) as caught:
        if mode == "native":
            _resume_fresh_native(**common)
        elif mode == "rewind":
            _resume_fresh_rewind(**common, drop_last=1)
        else:
            _resume_fresh(**common, strategy="structured", depth=1)

    assert caught.value.code == 1
    manager.resume_session.assert_called_once()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "/project/.forge/sessions/parent/forge.session.json" in captured.err
    assert "Repair" in captured.err and "restore" in captured.err
    assert "delete" not in captured.err.lower()
    assert "reset" not in captured.err.lower()
    assert "forge clean" not in captured.err
