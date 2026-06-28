"""Tests for policy check helpers (PreToolUse hook).

Covers: ClaudeHookAdapter.build_contexts, _persist_policy_state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from forge.cli.hooks.policy import (
    ClaudeHookAdapter,
    _persist_policy_state,
)
from forge.policy.types import ActionContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(name: str = "test-session") -> MagicMock:
    m = MagicMock()
    m.name = name
    return m


def _build_one(data: dict, tool_name: str, manifest: MagicMock) -> ActionContext | None:
    """Unwrap the at-most-one context a Claude adapter yields ([] -> None)."""
    contexts = ClaudeHookAdapter().build_contexts(data, tool_name, manifest)
    assert len(contexts) <= 1
    return contexts[0] if contexts else None


class TestBuildActionContext:
    """Test ClaudeHookAdapter.build_contexts() payload parsing."""

    def test_write_payload(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        data: dict = {
            "tool_input": {
                "file_path": str(tmp_path / "src" / "main.py"),
                "content": "print('hello')",
            }
        }
        result = _build_one(data, "Write", _make_manifest())
        assert result is not None
        assert result.origin == "claude_code"  # adapter tags the action's origin
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
        result = _build_one(data, "Edit", _make_manifest())
        assert result is not None
        assert result.new_content == "new code here"

    def test_tool_input_not_dict_returns_none(self) -> None:
        data = {"tool_input": "not a dict"}
        result = _build_one(data, "Write", _make_manifest())
        assert result is None

    def test_missing_tool_input_returns_context_with_none_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        data: dict = {"tool_input": {}}
        result = _build_one(data, "Write", _make_manifest())
        assert result is not None
        assert result.target_path is None

    def test_path_field_fallback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to 'path' when 'file_path' is missing."""
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        data = {"tool_input": {"path": str(tmp_path / "readme.md")}}
        result = _build_one(data, "Write", _make_manifest())
        assert result is not None
        assert result.target_path == "readme.md"

    def test_absolute_path_normalized_relative(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        data = {"tool_input": {"file_path": str(tmp_path / "deep" / "nested" / "file.py")}}
        result = _build_one(data, "Write", _make_manifest())
        assert result is not None
        assert result.target_path == "deep/nested/file.py"

    def test_path_outside_cwd_kept_as_is(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Path that can't be made relative to cwd is kept as absolute."""
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path / "subdir")
        data = {"tool_input": {"file_path": "/completely/different/path.py"}}
        result = _build_one(data, "Write", _make_manifest())
        assert result is not None
        assert result.target_path == "/completely/different/path.py"

    def test_content_exactly_5000_chars_no_truncation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        content = "x" * 5000
        data = {"tool_input": {"file_path": "f.py", "content": content}}
        result = _build_one(data, "Write", _make_manifest())
        assert result is not None
        assert result.new_content is not None
        assert len(result.new_content) == 5000
        assert "truncated" not in result.new_content

    def test_content_5001_chars_truncated(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        content = "x" * 5001
        data = {"tool_input": {"file_path": "f.py", "content": content}}
        result = _build_one(data, "Write", _make_manifest())
        assert result is not None
        assert result.new_content is not None
        assert "truncated" in result.new_content
        assert len(result.new_content) < 5001 + 50  # truncation marker overhead

    def test_empty_content_treated_as_falsy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty string content is falsy, so truncation is skipped."""
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        data = {"tool_input": {"file_path": "f.py", "content": ""}}
        result = _build_one(data, "Write", _make_manifest())
        assert result is not None
        # Empty string is passed through to ActionContext (no truncation applied)
        assert result.new_content == ""

    def test_non_string_target_path_treated_as_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        data = {"tool_input": {"file_path": 12345}}
        result = _build_one(data, "Write", _make_manifest())
        assert result is not None
        assert result.target_path is None

    def test_session_name_from_manifest(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        manifest = _make_manifest("my-session")
        data = {"tool_input": {"file_path": "f.py"}}
        result = _build_one(data, "Write", manifest)
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


class TestSupervisorLaneBindingFreeze:
    """T1b: the locked post-eval _mutate freezes the supervisor consumer-lane binding, write-if-absent."""

    _BUILD_RETURN = {
        "forge_version": "0.1.0",
        "bundles": [],
        "rules_active": [],
        "decisions": [],
        "policy_states": {},
    }

    def _effective(self, *, resume_id: str | None = "planner", suspended: bool = False) -> MagicMock:
        eff = MagicMock()
        eff.policy.bundles = []
        eff.policy.supervisor.resume_id = resume_id
        eff.policy.supervisor.suspended = suspended
        return eff

    def _state(self) -> Any:
        from forge.core.state import now_iso
        from forge.session.models import SessionState

        return SessionState(schema_version=1, name="t", created_at=now_iso(), last_accessed_at=now_iso())

    def _run_mutate(self, state: Any, effective: MagicMock) -> None:
        engine = MagicMock()
        engine.get_collected_state.return_value = {}
        store = MagicMock()
        _persist_policy_state(
            store=store, engine=engine, result=MagicMock(), effective=effective, context_summary="ctx"
        )
        store.update.call_args[1]["mutate"](state)

    @patch("forge.policy.store.build_policy_state_update")
    def test_configured_supervisor_freezes_default_binding(self, mock_build: MagicMock) -> None:
        """A configured supervisor with no intent override freezes the default lane (source='default')."""
        from forge.policy.semantic.supervisor import SUPERVISOR_CONSUMER
        from forge.session.models import LaneRecord

        mock_build.return_value = self._BUILD_RETURN
        state = self._state()
        self._run_mutate(state, self._effective())

        assert state.confirmed.consumer_lanes is not None
        binding = state.confirmed.consumer_lanes.supervisor
        assert binding is not None
        assert binding.source == "default"
        d = SUPERVISOR_CONSUMER.default_lane
        assert binding.lane == LaneRecord(d.runtime_id, d.backend_id, d.model)

    @patch("forge.policy.store.build_policy_state_update")
    def test_suspended_supervisor_does_not_freeze(self, mock_build: MagicMock) -> None:
        """A suspended supervisor is not dispatched, so no binding is frozen."""
        mock_build.return_value = self._BUILD_RETURN
        state = self._state()
        self._run_mutate(state, self._effective(suspended=True))
        assert state.confirmed.consumer_lanes is None

    @patch("forge.policy.store.build_policy_state_update")
    def test_no_supervisor_does_not_freeze(self, mock_build: MagicMock) -> None:
        """A policy run with no configured supervisor (resume_id None) freezes nothing."""
        mock_build.return_value = self._BUILD_RETURN
        state = self._state()
        self._run_mutate(state, self._effective(resume_id=None))
        assert state.confirmed.consumer_lanes is None

    @patch("forge.policy.store.build_policy_state_update")
    def test_freeze_is_write_if_absent(self, mock_build: MagicMock) -> None:
        """An existing binding (e.g. a prior codex freeze) is never overwritten by a later default run."""
        from forge.session.models import (
            ConsumerLaneBinding,
            ConsumerLaneConfirmed,
            LaneRecord,
        )

        mock_build.return_value = self._BUILD_RETURN
        state = self._state()
        frozen = ConsumerLaneBinding(
            lane=LaneRecord("codex", "chatgpt", "gpt-5-codex"), source="intent", resolved_at="2020-01-01T00:00:00Z"
        )
        state.confirmed.consumer_lanes = ConsumerLaneConfirmed(supervisor=frozen)
        self._run_mutate(state, self._effective())
        assert state.confirmed.consumer_lanes.supervisor is frozen

    def test_register_injects_bound_lane_from_intent(self) -> None:
        """register_supervisor_and_restore reads the manifest binding and injects it into the policy."""
        from forge.cli.hooks.policy import register_supervisor_and_restore
        from forge.session.models import ConsumerLaneIntent, LaneRecord

        eff = self._effective()
        eff.policy.supervisor.cascade = False
        eff.policy.supervisor.throttle_seconds = 30
        manifest = self._state()
        manifest.intent.consumer_lanes = ConsumerLaneIntent(supervisor=LaneRecord("codex", "chatgpt", "gpt-5-codex"))

        engine = MagicMock()
        register_supervisor_and_restore(engine, eff, manifest)

        registered = engine.register.call_args[0][0]
        assert registered._lane_record == LaneRecord("codex", "chatgpt", "gpt-5-codex")
