"""Tests for policy check helpers (PreToolUse hook).

Covers: _build_action_context, _persist_policy_state.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from forge.cli.hooks.policy import (
    _build_action_context,
    _persist_policy_state,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(name: str = "test-session") -> MagicMock:
    m = MagicMock()
    m.name = name
    return m


class TestBuildActionContext:
    """Test _build_action_context() payload parsing."""

    def test_write_payload(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        data: dict = {
            "tool_input": {
                "file_path": str(tmp_path / "src" / "main.py"),
                "content": "print('hello')",
            }
        }
        result = _build_action_context(data, "Write", _make_manifest())
        assert result is not None
        assert result.tool_name == "Write"
        assert result.event == "PreToolUse.Write"
        assert result.new_content == "print('hello')"
        assert result.target_path == "src/main.py"

    def test_edit_payload_uses_new_string(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        data = {
            "tool_input": {
                "file_path": str(tmp_path / "file.py"),
                "old_string": "old",
                "new_string": "new code here",
            }
        }
        result = _build_action_context(data, "Edit", _make_manifest())
        assert result is not None
        assert result.new_content == "new code here"

    def test_tool_input_not_dict_returns_none(self) -> None:
        data = {"tool_input": "not a dict"}
        result = _build_action_context(data, "Write", _make_manifest())
        assert result is None

    def test_missing_tool_input_returns_context_with_none_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        data: dict = {"tool_input": {}}
        result = _build_action_context(data, "Write", _make_manifest())
        assert result is not None
        assert result.target_path is None

    def test_path_field_fallback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to 'path' when 'file_path' is missing."""
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        data = {"tool_input": {"path": str(tmp_path / "readme.md")}}
        result = _build_action_context(data, "Write", _make_manifest())
        assert result is not None
        assert result.target_path == "readme.md"

    def test_absolute_path_normalized_relative(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        data = {"tool_input": {"file_path": str(tmp_path / "deep" / "nested" / "file.py")}}
        result = _build_action_context(data, "Write", _make_manifest())
        assert result is not None
        assert result.target_path == "deep/nested/file.py"

    def test_path_outside_cwd_kept_as_is(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Path that can't be made relative to cwd is kept as absolute."""
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path / "subdir")
        data = {"tool_input": {"file_path": "/completely/different/path.py"}}
        result = _build_action_context(data, "Write", _make_manifest())
        assert result is not None
        assert result.target_path == "/completely/different/path.py"

    def test_content_exactly_5000_chars_no_truncation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        content = "x" * 5000
        data = {"tool_input": {"file_path": "f.py", "content": content}}
        result = _build_action_context(data, "Write", _make_manifest())
        assert result is not None
        assert len(result.new_content) == 5000
        assert "truncated" not in result.new_content

    def test_content_5001_chars_truncated(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        content = "x" * 5001
        data = {"tool_input": {"file_path": "f.py", "content": content}}
        result = _build_action_context(data, "Write", _make_manifest())
        assert result is not None
        assert "truncated" in result.new_content
        assert len(result.new_content) < 5001 + 50  # truncation marker overhead

    def test_empty_content_treated_as_falsy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty string content is falsy, so truncation is skipped."""
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        data = {"tool_input": {"file_path": "f.py", "content": ""}}
        result = _build_action_context(data, "Write", _make_manifest())
        assert result is not None
        # Empty string is passed through to ActionContext (no truncation applied)
        assert result.new_content == ""

    def test_non_string_target_path_treated_as_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        data = {"tool_input": {"file_path": 12345}}
        result = _build_action_context(data, "Write", _make_manifest())
        assert result is not None
        assert result.target_path is None

    def test_session_name_from_manifest(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        manifest = _make_manifest("my-session")
        data = {"tool_input": {"file_path": "f.py"}}
        result = _build_action_context(data, "Write", manifest)
        assert result is not None
        assert result.session_name == "my-session"


class TestPersistPolicyState:
    """Test _persist_policy_state() manifest updates."""

    def _make_engine(self, state: dict | None = None, policies: list | None = None) -> MagicMock:
        engine = MagicMock()
        engine.get_collected_state.return_value = state or {}
        engine.policies = policies or []
        return engine

    def _make_effective(self, bundles: list | None = None) -> MagicMock:
        eff = MagicMock()
        if bundles is not None:
            eff.policy.bundles = bundles
        else:
            eff.policy = None
        return eff

    def _make_result(self) -> MagicMock:
        return MagicMock()

    @patch("forge.policy.store.build_policy_state_update")
    def test_writes_policy_to_manifest(self, mock_build: MagicMock) -> None:
        """_persist_policy_state calls store.update with a mutate function."""
        mock_build.return_value = {
            "forge_version": "0.1.0",
            "bundles": ["default"],
            "rules_active": ["tdd"],
            "decisions": [{"action": "allow"}],
            "policy_states": {},
        }
        store = MagicMock()
        _persist_policy_state(
            store=store,
            engine=self._make_engine(),
            result=self._make_result(),
            effective=self._make_effective(bundles=["default"]),
            context_summary="test context",
        )
        store.update.assert_called_once()
        # Verify the mutate callable was passed
        call_kwargs = store.update.call_args[1]
        assert "mutate" in call_kwargs
        assert callable(call_kwargs["mutate"])

    @patch("forge.policy.store.build_policy_state_update")
    def test_mutate_sets_confirmed_fields(self, mock_build: MagicMock) -> None:
        """The mutate function sets confirmed_at and confirmed_by."""
        from forge.core.state import now_iso
        from forge.session.models import SessionState

        mock_build.return_value = {
            "forge_version": "0.1.0",
            "bundles": [],
            "rules_active": [],
            "decisions": [],
            "policy_states": {},
        }
        store = MagicMock()
        _persist_policy_state(
            store=store,
            engine=self._make_engine(),
            result=self._make_result(),
            effective=self._make_effective(bundles=[]),
            context_summary="ctx",
        )

        mutate_fn = store.update.call_args[1]["mutate"]

        state = SessionState(
            schema_version=3,
            name="test",
            created_at=now_iso(),
            last_accessed_at=now_iso(),
        )
        mutate_fn(state)

        assert state.confirmed.confirmed_by == "hook:policy-check"
        assert state.confirmed.confirmed_at is not None

    @patch("forge.policy.store.build_policy_state_update")
    def test_mutate_passes_existing_state(self, mock_build: MagicMock) -> None:
        """Existing policy state from manifest is forwarded to build_policy_state_update."""
        from forge.core.state import now_iso
        from forge.session.models import PolicyConfirmed, SessionState

        mock_build.return_value = {
            "forge_version": "0.1.0",
            "bundles": [],
            "rules_active": [],
            "decisions": [],
            "policy_states": {"tdd": {"passed": True}},
        }
        store = MagicMock()
        _persist_policy_state(
            store=store,
            engine=self._make_engine(),
            result=self._make_result(),
            effective=self._make_effective(bundles=[]),
            context_summary="ctx",
        )

        mutate_fn = store.update.call_args[1]["mutate"]

        state = SessionState(
            schema_version=3,
            name="test",
            created_at=now_iso(),
            last_accessed_at=now_iso(),
        )
        state.confirmed.policy = PolicyConfirmed(
            forge_version="0.0.9",
            bundles=["old"],
            rules_active=["old_rule"],
            decisions=[{"old": True}],
            policy_states={"old_policy": {"v": 1}},
        )
        mutate_fn(state)

        # build_policy_state_update should have been called with existing state
        call_args = mock_build.call_args
        existing = call_args[1].get("existing_state") if call_args[1] else call_args[0][2]
        assert existing is not None

    @patch("forge.policy.store.build_policy_state_update")
    def test_mutate_rejects_non_session_state(self, mock_build: MagicMock) -> None:
        """Mutate function raises TypeError for wrong type."""
        mock_build.return_value = {
            "forge_version": "0.1.0",
            "bundles": [],
            "rules_active": [],
            "decisions": [],
            "policy_states": {},
        }
        store = MagicMock()
        _persist_policy_state(
            store=store,
            engine=self._make_engine(),
            result=self._make_result(),
            effective=self._make_effective(bundles=[]),
            context_summary="ctx",
        )

        mutate_fn = store.update.call_args[1]["mutate"]
        with pytest.raises(TypeError, match="Expected SessionState"):
            mutate_fn("not a session state")
