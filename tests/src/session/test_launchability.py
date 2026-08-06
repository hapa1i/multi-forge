"""Tests for derived session launchability and checkout guards."""

from pathlib import Path

import pytest

from forge.session.exceptions import SessionWorktreeMissingError
from forge.session.launchability import derive_launchability, require_session_worktree


def test_missing_worktree_becomes_launchable_when_path_reappears(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"

    assert derive_launchability(checkout) == "missing_worktree"

    checkout.mkdir()

    assert derive_launchability(checkout) == "launchable"
    assert require_session_worktree("demo", checkout, action="resume") == checkout


def test_checkout_guard_names_path_and_supported_recovery(tmp_path: Path) -> None:
    checkout = tmp_path / "deleted-worktree"

    with pytest.raises(SessionWorktreeMissingError) as exc_info:
        require_session_worktree("demo", checkout, action="fork")

    message = str(exc_info.value)
    assert "cannot fork session 'demo'" in message
    assert str(checkout) in message
    assert "Recreate the checkout" in message
    assert "forge session delete demo" in message


def test_regular_file_at_recorded_path_is_not_launchable(tmp_path: Path) -> None:
    checkout = tmp_path / "not-a-checkout"
    checkout.write_text("occupied")

    assert derive_launchability(checkout) == "missing_worktree"
    with pytest.raises(SessionWorktreeMissingError):
        require_session_worktree("demo", checkout, action="launch")


def test_legacy_manifest_without_recorded_worktree_keeps_cwd_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    assert derive_launchability(None) == "unknown"
    assert require_session_worktree("legacy", None, action="launch") == tmp_path
