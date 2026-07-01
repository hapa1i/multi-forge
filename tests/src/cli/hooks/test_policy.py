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

    def _run_mutate(self, state: Any, effective: MagicMock, supervisor_lane: Any = None, result: Any = None) -> None:
        engine = MagicMock()
        engine.get_collected_state.return_value = {}
        store = MagicMock()
        _persist_policy_state(
            store=store,
            engine=engine,
            result=result if result is not None else MagicMock(),
            effective=effective,
            context_summary="ctx",
            supervisor_lane=supervisor_lane,
        )
        store.update.call_args[1]["mutate"](state)

    @staticmethod
    def _exhausted_result() -> MagicMock:
        """A composite decision carrying the supervisor subscription-exhaustion failure."""
        result = MagicMock()
        result.decisions = [MagicMock(failure_type="subscription_exhausted")]
        return result

    @patch("forge.policy.store.build_policy_state_update")
    def test_configured_supervisor_on_default_does_not_freeze(self, mock_build: MagicMock) -> None:
        """A configured supervisor running on its default lane freezes nothing (MEDIUM contract).

        supervisor_lane is None (no explicit choice), so confirmed stays empty and the lane is
        still re-pinnable -- immutability protects an explicit choice, not the default.
        """
        mock_build.return_value = self._BUILD_RETURN
        state = self._state()
        self._run_mutate(state, self._effective())  # supervisor_lane defaults to None (ran on default)
        assert state.confirmed.consumer_lanes is None

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
        """An existing binding is never overwritten by a later check dispatching the same lane."""
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
        # Dispatch matches the frozen lane (read_bound_lane is confirmed-first -> codex), so the
        # stale-write guard passes and ensure's write-if-absent runs: the prior binding wins, never
        # rewritten (the 2020 resolved_at survives, proving identity).
        self._run_mutate(state, self._effective(), supervisor_lane=LaneRecord("codex", "chatgpt", "gpt-5-codex"))
        assert state.confirmed.consumer_lanes.supervisor is frozen

    @patch("forge.policy.store.build_policy_state_update")
    def test_stale_lane_dropped_when_bound_lane_changed(self, mock_build: MagicMock) -> None:
        """Stale-write guard (supersedes P2a): a concurrent set/remove that changes the bound lane
        between dispatch and the under-lock freeze drops the stale dispatched lane.

        ``supervisor_lane`` (codex) is what dispatched, but the fresh manifest no longer dispatches it
        (here it has no consumer_lanes -> default), so the freeze is skipped. This is the seam that
        stops a removed/re-pointed lane from being resurrected by a long in-flight check.
        """
        from forge.session.models import LaneRecord

        mock_build.return_value = self._BUILD_RETURN
        codex = LaneRecord("codex", "chatgpt", "gpt-5-codex")
        state = self._state()  # fresh manifest dispatches the default; codex was the stale dispatch
        self._run_mutate(state, self._effective(), supervisor_lane=codex)

        # read_bound_lane(state) is None (default) != codex -> nothing frozen.
        assert state.confirmed.consumer_lanes is None

    @patch("forge.policy.store.build_policy_state_update")
    def test_default_run_does_not_lock_out_later_pin(self, mock_build: MagicMock) -> None:
        """Lock-out regression (MEDIUM): a supervisor that first ran on its default lane must still
        accept a later explicit pin. The default run freezes nothing, so the next run on an injected
        lane freezes normally -- an early default check never locks the user into the default.
        """
        from forge.session.models import ConsumerLaneIntent, LaneRecord

        mock_build.return_value = self._BUILD_RETURN
        codex = LaneRecord("codex", "chatgpt", "gpt-5-codex")
        state = self._state()

        # First check ran on the default (no injected lane) -> nothing frozen, lane stays re-pinnable.
        # Capture into a throwaway local so the `is None` assertion doesn't narrow the attribute
        # expression itself (the second _run_mutate repopulates it, but mypy can't see that).
        self._run_mutate(state, self._effective())
        after_default = state.confirmed.consumer_lanes
        assert after_default is None

        # The user then pins codex (intent), and a later check dispatches + freezes it. The fresh
        # manifest dispatches codex, so the stale-write guard passes.
        state.intent.consumer_lanes = ConsumerLaneIntent(supervisor=codex)
        self._run_mutate(state, self._effective(), supervisor_lane=codex)
        confirmed = state.confirmed.consumer_lanes
        assert confirmed is not None
        assert confirmed.supervisor is not None
        assert confirmed.supervisor.lane == codex

    def test_register_injects_and_returns_bound_lane(self) -> None:
        """register_supervisor_and_restore reads the manifest binding, injects it, and returns it."""
        from forge.cli.hooks.policy import register_supervisor_and_restore
        from forge.session.models import ConsumerLaneIntent, LaneRecord

        eff = self._effective()
        eff.policy.supervisor.cascade = False
        eff.policy.supervisor.throttle_seconds = 30
        manifest = self._state()
        codex = LaneRecord("codex", "chatgpt", "gpt-5-codex")
        manifest.intent.consumer_lanes = ConsumerLaneIntent(supervisor=codex)

        engine = MagicMock()
        returned = register_supervisor_and_restore(engine, eff, manifest)

        registered = engine.register.call_args[0][0]
        assert registered._lane_record == codex  # injected into the policy
        assert returned == codex  # and returned for the caller to thread into the freeze

    # --- T7 sticky degrade (write + read), folded into the same locked _mutate as the freeze ---

    @staticmethod
    def _fresh_build_return() -> dict[str, Any]:
        # A NEW dict (with a fresh policy_states) per call: the degrade write mutates
        # policy_states in place, so a shared class-attribute dict would leak the marker
        # across tests. Production `build_policy_state_update` already returns a fresh dict.
        return {"forge_version": "0.1.0", "bundles": [], "rules_active": [], "decisions": [], "policy_states": {}}

    @patch("forge.policy.store.build_policy_state_update")
    def test_codex_exhaustion_writes_degrade_marker(self, mock_build: MagicMock) -> None:
        """A subscription-exhaustion failure on the bound codex lane persists the degrade overlay."""
        from forge.policy.supervisor_lane_degrade import (
            is_supervisor_degraded,
            read_supervisor_degrade,
        )
        from forge.session.models import ConsumerLaneIntent, LaneRecord

        mock_build.return_value = self._fresh_build_return()
        codex = LaneRecord("codex", "chatgpt", "gpt-5-codex")
        state = self._state()
        state.intent.consumer_lanes = ConsumerLaneIntent(supervisor=codex)  # read_bound_lane -> codex
        self._run_mutate(state, self._effective(), supervisor_lane=codex, result=self._exhausted_result())

        assert is_supervisor_degraded(state) is True
        marker = read_supervisor_degrade(state)
        assert marker is not None
        assert marker["from_lane"] == {"runtime_id": "codex", "backend_id": "chatgpt", "model": "gpt-5-codex"}
        assert marker["reason"] == "subscription_exhausted"

    @patch("forge.policy.store.build_policy_state_update")
    def test_non_exhaustion_failure_writes_no_degrade(self, mock_build: MagicMock) -> None:
        """A non-exhaustion supervisor failure (e.g. subprocess_error) writes no degrade marker."""
        from forge.policy.supervisor_lane_degrade import is_supervisor_degraded
        from forge.session.models import ConsumerLaneIntent, LaneRecord

        mock_build.return_value = self._fresh_build_return()
        codex = LaneRecord("codex", "chatgpt", "gpt-5-codex")
        state = self._state()
        state.intent.consumer_lanes = ConsumerLaneIntent(supervisor=codex)
        result = MagicMock()
        result.decisions = [MagicMock(failure_type="subprocess_error")]
        self._run_mutate(state, self._effective(), supervisor_lane=codex, result=result)
        assert is_supervisor_degraded(state) is False

    @patch("forge.policy.store.build_policy_state_update")
    def test_degrade_write_dropped_when_bound_lane_changed(self, mock_build: MagicMock) -> None:
        """Stale-write guard: exhaustion, but the fresh manifest no longer dispatches codex (a
        concurrent remove/re-pin) -- the degrade write is dropped, mirroring the freeze guard."""
        from forge.policy.supervisor_lane_degrade import is_supervisor_degraded
        from forge.session.models import LaneRecord

        mock_build.return_value = self._fresh_build_return()
        codex = LaneRecord("codex", "chatgpt", "gpt-5-codex")
        state = self._state()  # no binding -> read_bound_lane is the default (None) != codex
        self._run_mutate(state, self._effective(), supervisor_lane=codex, result=self._exhausted_result())
        assert is_supervisor_degraded(state) is False

    @patch("forge.policy.store.build_policy_state_update")
    def test_non_codex_lane_never_degrades(self, mock_build: MagicMock) -> None:
        """Defensive gate: even an (impossible) exhaustion tagged on a claude lane writes no degrade."""
        from forge.policy.supervisor_lane_degrade import is_supervisor_degraded
        from forge.session.models import ConsumerLaneIntent, LaneRecord

        mock_build.return_value = self._fresh_build_return()
        claude_max = LaneRecord("claude_code", "claude-max", "opus")
        state = self._state()
        state.intent.consumer_lanes = ConsumerLaneIntent(supervisor=claude_max)
        self._run_mutate(state, self._effective(), supervisor_lane=claude_max, result=self._exhausted_result())
        assert is_supervisor_degraded(state) is False

    def test_register_injects_default_lane_when_degraded(self) -> None:
        """Read side: a degraded session overrides the bound codex lane to None (default claude)."""
        from forge.cli.hooks.policy import register_supervisor_and_restore
        from forge.policy.supervisor_lane_degrade import set_supervisor_degrade
        from forge.session.models import ConsumerLaneIntent, LaneRecord

        eff = self._effective()
        eff.policy.supervisor.cascade = False
        eff.policy.supervisor.throttle_seconds = 30
        manifest = self._state()
        codex = LaneRecord("codex", "chatgpt", "gpt-5-codex")
        manifest.intent.consumer_lanes = ConsumerLaneIntent(supervisor=codex)
        set_supervisor_degrade(manifest, from_lane=codex, to_lane=None, reason="subscription_exhausted", at="t")

        engine = MagicMock()
        returned = register_supervisor_and_restore(engine, eff, manifest)

        assert returned is None  # degraded -> default lane, not the frozen codex binding
        registered = engine.register.call_args[0][0]
        assert registered._lane_record is None
        # The codex binding itself is untouched (still observable in `lane show`).
        from forge.policy.semantic.supervisor import SUPERVISOR_CONSUMER
        from forge.session.consumer_lanes import read_bound_lane

        assert read_bound_lane(manifest, SUPERVISOR_CONSUMER) == codex

    @patch("forge.policy.store.build_policy_state_update")
    def test_exhaustion_write_then_register_injects_default(self, mock_build: MagicMock) -> None:
        """End-to-end sticky on ONE manifest: write side then read side. An exhausting check persists
        the marker (the freeze-lock _mutate); the NEXT registration reads it and injects None (default
        claude), proving the write and read agree on the overlay key + shape -- the cross-seam contract
        the two separate write/read tests don't exercise."""
        from forge.cli.hooks.policy import register_supervisor_and_restore
        from forge.policy.supervisor_lane_degrade import is_supervisor_degraded
        from forge.session.models import ConsumerLaneIntent, LaneRecord

        mock_build.return_value = self._fresh_build_return()
        codex = LaneRecord("codex", "chatgpt", "gpt-5-codex")
        state = self._state()
        state.intent.consumer_lanes = ConsumerLaneIntent(supervisor=codex)

        # Check N: codex exhausts -> the degrade marker is written.
        self._run_mutate(state, self._effective(), supervisor_lane=codex, result=self._exhausted_result())
        assert is_supervisor_degraded(state) is True

        # Check N+1: registration on the same manifest now resolves to the default claude lane.
        eff = self._effective()
        eff.policy.supervisor.cascade = False
        eff.policy.supervisor.throttle_seconds = 30
        returned = register_supervisor_and_restore(MagicMock(), eff, state)
        assert returned is None

    @patch("forge.policy.semantic.supervisor.resolve_supervisor_lane", side_effect=RuntimeError("catalog drift"))
    @patch("forge.policy.store.build_policy_state_update")
    def test_degrade_write_survives_default_resolution_failure(
        self, mock_build: MagicMock, _mock_resolve: MagicMock
    ) -> None:
        """Fail-open: the only fallible op in the degrade write -- resolving the default lane for the
        audit-only ``to_lane`` -- is guarded. If it raises (drifted default catalog), the marker is
        still written with ``to_lane=None`` and the hook never crashes; routing is by None regardless."""
        from forge.policy.supervisor_lane_degrade import (
            is_supervisor_degraded,
            read_supervisor_degrade,
        )
        from forge.session.models import ConsumerLaneIntent, LaneRecord

        mock_build.return_value = self._fresh_build_return()
        codex = LaneRecord("codex", "chatgpt", "gpt-5-codex")
        state = self._state()
        state.intent.consumer_lanes = ConsumerLaneIntent(supervisor=codex)
        self._run_mutate(state, self._effective(), supervisor_lane=codex, result=self._exhausted_result())

        assert is_supervisor_degraded(state) is True  # degraded despite the resolution failure
        marker = read_supervisor_degrade(state)
        assert marker is not None and marker["to_lane"] is None
