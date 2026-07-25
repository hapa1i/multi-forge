"""Tests for read-only policy queries."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from forge.policy.queries import RESUME_ID_UUID_RE, read_scoped_supervisor_target

_LOWER_UUID = "12345678-1234-1234-1234-123456789abc"
_UPPER_UUID = "ABCDEF12-ABCD-ABCD-ABCD-ABCDEF123456"


@pytest.mark.parametrize("resume_id", [_LOWER_UUID, _UPPER_UUID])
def test_resume_id_uuid_matcher_accepts_canonical_forms(resume_id: str) -> None:
    assert RESUME_ID_UUID_RE.fullmatch(resume_id) is not None


@pytest.mark.parametrize(
    "resume_id",
    [
        "12345678123412341234123456789abc",
        "{12345678-1234-1234-1234-123456789abc}",
        "12345678-1234-1234-1234-123456789abz",
    ],
)
def test_resume_id_uuid_matcher_rejects_noncanonical_forms(resume_id: str) -> None:
    assert RESUME_ID_UUID_RE.fullmatch(resume_id) is None


@patch("forge.session.manager.SessionManager")
def test_read_scoped_target_uses_reverse_lookup_for_uuid(mock_manager_cls: MagicMock) -> None:
    state = MagicMock()
    manager = mock_manager_cls.return_value
    manager.index_store.find_session_by_uuid.return_value = ("planner", "/repo")
    manager.get_session.return_value = state

    result = read_scoped_supervisor_target(_LOWER_UUID, "/supervisor", "/fallback")

    assert result is state
    manager.index_store.find_session_by_uuid.assert_called_once_with(_LOWER_UUID)
    manager.get_session.assert_called_once_with("planner", forge_root="/repo")


@patch("forge.session.manager.SessionManager")
def test_read_scoped_target_treats_noncanonical_uuid_as_session_name(mock_manager_cls: MagicMock) -> None:
    state = MagicMock()
    manager = mock_manager_cls.return_value
    manager.get_session.return_value = state
    compact = "12345678123412341234123456789abc"

    result = read_scoped_supervisor_target(compact, "/supervisor", "/fallback")

    assert result is state
    manager.index_store.find_session_by_uuid.assert_not_called()
    manager.get_session.assert_called_once_with(compact, forge_root="/supervisor")
