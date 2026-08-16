"""Tests for session context introspection ops."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from forge.config.loader import write_proxy_instance_config
from forge.config.schema import ProxyInstanceConfig, TierModels
from forge.core.ops import context as context_module
from forge.core.ops import session_context as session_context_module
from forge.core.ops.session_context import (
    BindingLookupError,
    SessionContext,
    SessionContextError,
    _model_to_family,
    collect_bound_codex_threads,
    collect_bound_uuids,
    detect_model_family,
    extract_field,
    get_session_context,
    resolve_session_identifier,
)
from forge.core.state.exceptions import StateCorruptedError, StateUnreadableError
from forge.session import (
    ForgeSessionError,
    IndexStore,
    SessionStore,
    create_session_state,
)
from forge.session.exceptions import AmbiguousSessionError
from forge.session.models import CodexConfirmed, PolicyIntent, StartedWithProxy
from forge.session.store import get_manifest_path
from tests.fixtures.session_state import publish_session


@pytest.fixture
def resolution_seams(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Isolate the name, UUID-index, and manifest-scan resolution stages."""
    manager = MagicMock()
    index = MagicMock()
    manifest_scan = MagicMock()

    monkeypatch.setattr(session_context_module, "SessionManager", lambda: manager)
    monkeypatch.setattr(session_context_module, "IndexStore", lambda: index)
    monkeypatch.setattr(session_context_module, "scan_manifests_for_uuid", manifest_scan)
    monkeypatch.setattr(context_module, "find_forge_root", lambda _path: Path("/scoped-project"))

    return manager, index, manifest_scan


class TestModelToFamily:
    """Unit tests for vendor prefix → family normalization."""

    def test_openai_prefixed(self):
        assert _model_to_family("openai/gpt-5.5") == "openai"

    def test_vertex_ai_prefixed(self):
        assert _model_to_family("vertex_ai/gemini-3.1-pro-preview") == "gemini"

    def test_vertex_ai_beta_prefixed(self):
        assert _model_to_family("vertex_ai_beta/gemini-3.1-pro") == "gemini"

    def test_anthropic_prefixed(self):
        assert _model_to_family("anthropic/claude-opus-4-6") == "anthropic"

    def test_bare_gpt(self):
        assert _model_to_family("gpt-5.5") == "openai"

    def test_bare_claude(self):
        assert _model_to_family("claude-opus-4-6") == "anthropic"

    def test_bare_gemini(self):
        assert _model_to_family("gemini-3.1-pro-preview") == "gemini"

    def test_bare_o_series(self):
        assert _model_to_family("o3-mini") == "openai"
        assert _model_to_family("o4-mini") == "openai"

    def test_unknown_defaults_to_anthropic(self):
        assert _model_to_family("unknown-model-9000") == "anthropic"


class TestDetectModelFamily:
    """Tests for template → family detection."""

    def test_none_template_returns_anthropic(self):
        assert detect_model_family(None) == "anthropic"

    def test_litellm_openai_template(self):
        result = detect_model_family("litellm-openai")
        assert result == "openai"

    def test_litellm_gemini_template(self):
        result = detect_model_family("litellm-gemini")
        assert result == "gemini"

    def test_litellm_anthropic_template(self):
        result = detect_model_family("litellm-anthropic")
        assert result == "anthropic"

    def test_unknown_template_returns_anthropic(self):
        result = detect_model_family("nonexistent-template-xyz")
        assert result == "anthropic"


class TestExtractField:
    """Tests for dotted field extraction from dicts."""

    def test_top_level(self):
        assert extract_field({"model_family": "openai"}, "model_family") == "openai"

    def test_nested(self):
        data = {"proxy": {"template": "litellm-openai"}}
        assert extract_field(data, "proxy.template") == "litellm-openai"

    def test_deeply_nested(self):
        data = {"policy": {"bundles": ["tdd"]}}
        assert extract_field(data, "policy.bundles") == ["tdd"]

    def test_missing_key_raises(self):
        with pytest.raises(KeyError):
            extract_field({"a": 1}, "b")

    def test_missing_nested_key_raises(self):
        with pytest.raises(KeyError):
            extract_field({"proxy": {"template": "x"}}, "proxy.missing")


class TestSessionContextDataclass:
    """Tests for SessionContext serialization."""

    def test_to_dict_roundtrip(self):
        ctx = SessionContext(
            session_name="test-session",
            model_family="openai",
        )
        data = ctx.to_dict()
        assert data["session_name"] == "test-session"
        assert data["model_family"] == "openai"
        assert data["launchability"] == "unknown"
        assert data["recorded_worktree_path"] is None
        assert "main_model" in data
        assert "model_profile" not in data
        assert data["proxy"]["is_direct"] is True
        # Verify JSON serializable
        json.dumps(data)

    def test_to_dict_with_proxy(self):
        from forge.core.ops.session_context import ProxyContext

        ctx = SessionContext(
            session_name="proxied",
            model_family="gemini",
            proxy=ProxyContext(
                template="litellm-gemini",
                base_url="http://localhost:8084",
                proxy_id="litellm-gemini",
                is_direct=False,
            ),
            models={"haiku": "vertex_ai/gemini-2.5-flash", "opus": "vertex_ai/gemini-3.1-pro"},
        )
        data = ctx.to_dict()
        assert data["proxy"]["template"] == "litellm-gemini"
        assert data["proxy"]["is_direct"] is False
        assert data["models"]["opus"] == "vertex_ai/gemini-3.1-pro"


class TestResolveSessionIdentifier:
    """Tests for session resolution logic."""

    def test_no_session_raises(self, monkeypatch):
        monkeypatch.delenv("FORGE_SESSION", raising=False)
        with pytest.raises(SessionContextError, match="No session found.*Use --session <name>"):
            resolve_session_identifier(None)

    def test_unknown_name_and_uuid_raises(self):
        with pytest.raises(SessionContextError, match="tried as name and UUID"):
            resolve_session_identifier("nonexistent-session-xyz-000")

    def test_not_found_name_reaches_uuid_lookup_without_duplicate_retry(self, resolution_seams) -> None:
        manager, index, manifest_scan = resolution_seams
        manager.get_session_entry.side_effect = ForgeSessionError("not found")
        index.find_session_by_uuid.return_value = ("uuid-owner", "/uuid-root")

        assert resolve_session_identifier("session-or-uuid") == ("uuid-owner", "/uuid-root")
        assert manager.get_session_entry.call_args_list == [
            call("session-or-uuid", forge_root="/scoped-project"),
            call("session-or-uuid"),
        ]
        index.find_session_by_uuid.assert_called_once_with("session-or-uuid")
        manifest_scan.assert_not_called()

    def test_not_found_uuid_reaches_manifest_fallback(self, resolution_seams) -> None:
        manager, index, manifest_scan = resolution_seams
        manager.get_session_entry.side_effect = ForgeSessionError("not found")
        index.find_session_by_uuid.return_value = None
        manifest_scan.return_value = ("manifest-owner", "/manifest-root")

        assert resolve_session_identifier("session-or-uuid") == ("manifest-owner", "/manifest-root")
        assert manager.get_session_entry.call_args_list == [
            call("session-or-uuid", forge_root="/scoped-project"),
            call("session-or-uuid"),
        ]
        index.find_session_by_uuid.assert_called_once_with("session-or-uuid")
        manifest_scan.assert_called_once_with("session-or-uuid")

    @pytest.mark.parametrize("error_type", [StateCorruptedError, StateUnreadableError])
    def test_unscoped_index_state_errors_propagate(self, resolution_seams, error_type) -> None:
        manager, index, manifest_scan = resolution_seams
        manager.get_session_entry.side_effect = [
            ForgeSessionError("scoped miss"),
            error_type("/index.json", "cannot read"),
        ]

        with pytest.raises(error_type, match="index.json"):
            resolve_session_identifier("session-or-uuid")

        assert manager.get_session_entry.call_args_list == [
            call("session-or-uuid", forge_root="/scoped-project"),
            call("session-or-uuid"),
        ]
        index.find_session_by_uuid.assert_not_called()
        manifest_scan.assert_not_called()

    def test_unscoped_ambiguity_propagates_without_uuid_fallback(self, resolution_seams) -> None:
        manager, index, manifest_scan = resolution_seams
        manager.get_session_entry.side_effect = [
            ForgeSessionError("scoped miss"),
            AmbiguousSessionError("shared", ["/one", "/two"]),
        ]

        with pytest.raises(AmbiguousSessionError) as exc_info:
            resolve_session_identifier("shared")

        assert exc_info.value.forge_roots == ["/one", "/two"]
        assert manager.get_session_entry.call_args_list == [
            call("shared", forge_root="/scoped-project"),
            call("shared"),
        ]
        index.find_session_by_uuid.assert_not_called()
        manifest_scan.assert_not_called()


class TestGetSessionContext:
    """Tests for the full context builder (requires a session on disk)."""

    def test_no_session_falls_back_to_env_context(self, monkeypatch):
        monkeypatch.delenv("FORGE_SESSION", raising=False)
        monkeypatch.delenv("ACTIVE_TEMPLATE", raising=False)
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        ctx = get_session_context(None)
        assert ctx.session_name == "(unknown)"
        assert ctx.proxy.is_direct is True
        assert ctx.model_family == "anthropic"

    def test_no_session_with_direct_model_env_returns_main_model(self, monkeypatch):
        monkeypatch.delenv("FORGE_SESSION", raising=False)
        monkeypatch.delenv("ACTIVE_TEMPLATE", raising=False)
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        monkeypatch.setenv("ANTHROPIC_MODEL", "opus")
        monkeypatch.setenv("ANTHROPIC_DEFAULT_OPUS_MODEL", "claude-opus-4-8")

        ctx = get_session_context(None)

        assert ctx.proxy.is_direct is True
        assert ctx.model_family == "anthropic"
        assert ctx.main_model == "claude-opus-4-8"

    def test_no_session_ignores_stale_direct_model_default_without_tier(self, monkeypatch):
        monkeypatch.delenv("FORGE_SESSION", raising=False)
        monkeypatch.delenv("ACTIVE_TEMPLATE", raising=False)
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
        monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-6")

        ctx = get_session_context(None)

        assert ctx.proxy.is_direct is True
        assert ctx.model_family == "anthropic"
        assert ctx.main_model is None

    def test_no_session_with_proxy_env_returns_family(self, monkeypatch):
        monkeypatch.delenv("FORGE_SESSION", raising=False)
        monkeypatch.setenv("ACTIVE_TEMPLATE", "litellm-openai")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:8085")
        ctx = get_session_context(None)
        assert ctx.proxy.template == "litellm-openai"
        assert ctx.proxy.base_url == "http://localhost:8085"
        assert ctx.proxy.is_direct is False

    def test_explicit_nonexistent_session_raises(self, monkeypatch):
        """Explicit bad session should raise even when env vars are set."""
        monkeypatch.setenv("ACTIVE_TEMPLATE", "litellm-openai")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:8085")
        with pytest.raises(SessionContextError, match="No session found"):
            get_session_context("nonexistent-xyz-000")

    def test_resolved_session_with_corrupt_manifest_raises(self, monkeypatch):
        """Session resolves via $FORGE_SESSION but manifest read fails."""
        from unittest.mock import patch

        from forge.session import ForgeSessionError

        monkeypatch.setenv("FORGE_SESSION", "corrupt-session")

        # resolve_session_identifier succeeds (returns the name)
        # but get_session raises ForgeSessionError
        with (
            patch(
                "forge.core.ops.session_context.resolve_session_identifier",
                return_value=("corrupt-session", None),
            ),
            patch("forge.core.ops.session_context.SessionManager") as mock_mgr_cls,
        ):
            mock_mgr_cls.return_value.get_session.side_effect = ForgeSessionError("manifest corrupted")
            with pytest.raises(SessionContextError, match="manifest corrupted"):
                get_session_context()

    def test_forge_session_env_binds_to_correct_proxy_context(self, tmp_path: Path, monkeypatch):
        """FORGE_SESSION env var resolves to the correct session with proxy metadata.

        This is the binding chain that forge claude launch --proxy relies on:
        set FORGE_SESSION=<name> → get_session_context(None) → correct proxy/family.
        """
        worktree = tmp_path / "repo"
        worktree.mkdir()

        state = create_session_state(
            "proxy-session",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(worktree),
        )
        state.confirmed.started_with_proxy = StartedWithProxy(
            base_url="http://localhost:8085",
            template="litellm-openai",
        )

        publish_session(IndexStore(), state, worktree)

        monkeypatch.setenv("FORGE_SESSION", "proxy-session")

        ctx = get_session_context(None)
        assert ctx.session_name == "proxy-session"
        assert ctx.proxy.template == "litellm-openai"
        assert ctx.proxy.base_url == "http://localhost:8085"
        assert ctx.proxy.is_direct is False

    def test_direct_session_returns_stored_main_model(self, tmp_path: Path, monkeypatch):
        worktree = tmp_path / "repo"
        worktree.mkdir()

        state = create_session_state(
            "direct-session",
            worktree_path=str(worktree),
            direct_model="claude-opus-4-8",
        )

        publish_session(IndexStore(), state, worktree)

        monkeypatch.setenv("FORGE_SESSION", "direct-session")

        ctx = get_session_context(None)
        data = ctx.to_dict()
        assert ctx.proxy.is_direct is True
        assert ctx.model_family == "anthropic"
        assert ctx.main_model == "claude-opus-4-8"
        assert ctx.recorded_worktree_path == str(worktree)
        assert ctx.launchability == "launchable"
        assert data["main_model"] == "claude-opus-4-8"

    def test_uuid_resolution_falls_back_to_manifest_scan_when_index_is_stale(self, tmp_path: Path):
        worktree = tmp_path / "repo"
        worktree.mkdir()

        state = create_session_state("test-session", worktree_path=str(worktree))
        state.confirmed.claude_session_id = "old-uuid"

        store = SessionStore(str(worktree), "test-session")
        publish_session(IndexStore(), state, worktree)

        def mutate(manifest):
            manifest.confirmed.claude_session_id = "new-uuid"

        store.update(timeout_s=5.0, mutate=mutate)

        result = resolve_session_identifier("new-uuid")
        assert result[0] == "test-session"
        assert result[1] == str(worktree)  # forge_root preserved from manifest scan

    def test_prefers_proxy_instance_models_over_template_defaults(self, tmp_path: Path):
        worktree = tmp_path / "repo"
        worktree.mkdir()

        proxy_config = ProxyInstanceConfig(
            proxy_format=1,
            template="litellm-openai",
            template_digest="digest",
            provider="litellm",
            proxy_endpoint="http://localhost:9999",
            port=9999,
            upstream_base_url="http://upstream.example",
            tiers=TierModels(
                haiku="vertex_ai/gemini-2.5-flash",
                sonnet="vertex_ai/gemini-3.1-pro",
                opus="vertex_ai/gemini-3.1-pro",
            ),
        )
        write_proxy_instance_config("proxy-1", proxy_config)

        state = create_session_state(
            "proxied-session",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:9999",
            worktree_path=str(worktree),
        )
        state.confirmed.started_with_proxy = StartedWithProxy(
            base_url="http://localhost:9999",
            proxy_id="proxy-1",
            template="litellm-openai",
        )

        publish_session(IndexStore(), state, worktree)

        ctx = get_session_context("proxied-session")

        assert ctx.model_family == "gemini"
        assert ctx.models == {
            "haiku": "vertex_ai/gemini-2.5-flash",
            "sonnet": "vertex_ai/gemini-3.1-pro",
            "opus": "vertex_ai/gemini-3.1-pro",
        }

    def test_policy_context_uses_effective_overrides(self, tmp_path: Path):
        worktree = tmp_path / "repo"
        worktree.mkdir()

        state = create_session_state("policy-session", worktree_path=str(worktree))
        state.intent.policy = PolicyIntent(enabled=False, bundles=["tdd"], fail_mode="open")
        state.overrides = {
            "policy": {
                "enabled": True,
                "bundles": ["coding_standards"],
                "fail_mode": "closed",
            }
        }

        publish_session(IndexStore(), state, worktree)

        ctx = get_session_context("policy-session")

        assert ctx.policy.enabled is True
        assert ctx.policy.bundles == ["coding_standards"]
        assert ctx.policy.fail_mode == "closed"


class TestBindingCollectionFailsClosed:
    """A binding Forge cannot read is unknown, never "free".

    These collectors decide whether `forge session adopt` may bind a conversation.
    Swallowing a read error reports the same thing as an absent binding, which lets
    one conversation bind to two sessions -- the invariant adoption exists to hold.
    """

    def _corrupt_manifest(self, worktree: Path, name: str) -> None:
        state = create_session_state(name=name, worktree_path=str(worktree))
        publish_session(IndexStore(), state, worktree)
        get_manifest_path(worktree, name).write_text("{ not json", encoding="utf-8")

    def test_unreadable_manifest_stops_a_uuid_lookup(self, tmp_path: Path) -> None:
        self._corrupt_manifest(tmp_path, "broken")

        with pytest.raises(BindingLookupError, match="broken"):
            collect_bound_uuids(str(tmp_path))

    def test_unreadable_manifest_stops_a_codex_thread_lookup(self, tmp_path: Path) -> None:
        self._corrupt_manifest(tmp_path, "broken")

        with pytest.raises(BindingLookupError, match="broken"):
            collect_bound_codex_threads(str(tmp_path))

    def test_a_project_with_no_sessions_is_not_an_error(self, tmp_path: Path) -> None:
        """Absent is genuinely empty; only unreadable is unknown."""
        assert collect_bound_uuids(str(tmp_path)) == {}
        assert collect_bound_codex_threads(str(tmp_path)) == {}


class TestCrossProjectManifestVisibility:
    """Session names are project-scoped, so a bare name cannot dedupe manifest reads.

    Regression: both collectors skipped a current-root manifest whose *name* had
    already been seen in any other project, hiding that project's orphan binding
    and letting the same conversation bind twice.
    """

    _UUID_A = "aaaa1111-2222-3333-4444-555566667777"
    _UUID_B = "bbbb1111-2222-3333-4444-555566667777"
    _THREAD_A = "019f0b65-b51c-7683-99c7-bb48107faaaa"
    _THREAD_B = "019f0b65-b51c-7683-99c7-bb48107fbbbb"

    def _session(self, root: Path, uuid: str, thread: str, *, indexed: bool) -> None:
        root.mkdir(parents=True, exist_ok=True)
        state = create_session_state(name="same", worktree_path=str(root))
        state.confirmed.claude_session_id = uuid
        state.confirmed.codex = CodexConfirmed(thread_id=thread, rollout_path="/x", rollout_source="adopted")
        if indexed:
            publish_session(IndexStore(), state, root)
        else:
            # The second project intentionally contributes a manifest-only
            # binding, which the global collector must not hide.
            SessionStore(str(root), "same").write(state)

    @pytest.fixture
    def two_projects(self, tmp_path: Path) -> Path:
        """Project A indexed, project B an orphan manifest -- both named `same`."""
        self._session(tmp_path / "a", self._UUID_A, self._THREAD_A, indexed=True)
        self._session(tmp_path / "b", self._UUID_B, self._THREAD_B, indexed=False)
        return tmp_path / "b"

    def test_another_project_cannot_hide_this_one_s_uuid(self, two_projects: Path) -> None:
        assert self._UUID_B in collect_bound_uuids(str(two_projects))

    def test_another_project_cannot_hide_this_one_s_codex_thread(self, two_projects: Path) -> None:
        assert self._THREAD_B in collect_bound_codex_threads(str(two_projects))
