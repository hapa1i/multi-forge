"""Tests for session models and factory functions."""

from __future__ import annotations

import pytest

from forge.core.state import now_iso
from forge.session.models import (
    INDEX_VERSION,
    SCHEMA_VERSION,
    DesignatedDoc,
    LaunchIntent,
    MemoryIntent,
    MemoryWriterConfig,
    ProxyIntent,
    SessionConfirmed,
    SessionIndex,
    SessionIndexEntry,
    SessionIntent,
    SessionState,
    SidecarLaunchIntent,
    VerificationConfig,
    VerificationConfirmed,
    Worktree,
    create_session_state,
)

# NOTE: Comprehensive timestamp tests are in tests/src/core/state/test_timestamps.py
# These tests use now_iso/parse_iso from core.state to verify integration with session models.


class TestWorktree:
    """Test Worktree dataclass."""

    def test_create_worktree(self) -> None:
        """Create a Worktree with all fields."""
        wt = Worktree(path="/path/to/worktree", branch="feature-auth", is_worktree=True)
        assert wt.path == "/path/to/worktree"
        assert wt.branch == "feature-auth"
        assert wt.is_worktree is True

    def test_default_is_worktree(self) -> None:
        """is_worktree defaults to False — caller must explicitly set True for real worktrees."""
        wt = Worktree(path="/path", branch="main")
        assert wt.is_worktree is False


class TestProxyIntent:
    """Test ProxyIntent dataclass."""

    def test_create_proxy_intent(self) -> None:
        """Create a ProxyIntent with required fields."""
        proxy = ProxyIntent(template="litellm-gemini", base_url="http://localhost:8084")
        assert proxy.template == "litellm-gemini"
        assert proxy.base_url == "http://localhost:8084"


class TestSessionIntent:
    """Test SessionIntent dataclass."""

    def test_default_values(self) -> None:
        """SessionIntent should have sensible defaults."""
        intent = SessionIntent()
        assert intent.agent == "claude-code"
        assert intent.proxy is None
        assert intent.launch is None
        assert intent.system_prompt is None
        assert intent.memory is None
        assert intent.policy is None
        assert intent.verification is None

    def test_with_proxy(self) -> None:
        """SessionIntent can include proxy configuration."""
        proxy = ProxyIntent(template="test", base_url="http://test")
        intent = SessionIntent(proxy=proxy)
        assert intent.proxy is not None
        assert intent.proxy.template == "test"


class TestSessionConfirmed:
    """Test SessionConfirmed dataclass."""

    def test_default_values(self) -> None:
        """SessionConfirmed should have empty defaults."""
        confirmed = SessionConfirmed()
        assert confirmed.claude_session_id is None
        assert confirmed.transcript_path is None
        assert confirmed.latest_plan_path is None
        assert confirmed.artifacts == {}
        assert confirmed.confirmed_at is None
        assert confirmed.confirmed_by is None

    def test_with_values(self) -> None:
        """SessionConfirmed can hold session data."""
        confirmed = SessionConfirmed(
            claude_session_id="uuid-1234",
            transcript_path="/path/to/transcript.jsonl",
            confirmed_at="2024-12-17T10:30:00",
            confirmed_by="hook:SessionStart",
        )
        assert confirmed.claude_session_id == "uuid-1234"


class TestLaunchIntent:
    """Test launch intent dataclasses."""

    def test_default_host_launch(self) -> None:
        """LaunchIntent defaults to host mode without sidecar config."""
        launch = LaunchIntent()
        assert launch.mode == "host"
        assert launch.sidecar is None

    def test_sidecar_launch_config(self) -> None:
        """SidecarLaunchIntent stores raw mount specs and image override."""
        sidecar = SidecarLaunchIntent(
            mounts=["/data:/mnt/data:ro"],
            image="forge-sidecar:test",
        )
        launch = LaunchIntent(mode="sidecar", sidecar=sidecar)
        assert launch.mode == "sidecar"
        assert launch.sidecar is not None
        assert launch.sidecar.mounts == ["/data:/mnt/data:ro"]
        assert launch.sidecar.image == "forge-sidecar:test"

    def test_old_intent_without_launch_still_deserializes(self) -> None:
        """Older manifests without intent.launch should default to None."""
        import dacite

        intent = dacite.from_dict(
            SessionIntent,
            {
                "agent": "claude-code",
                "proxy": {"template": "test", "base_url": "http://test"},
            },
            config=dacite.Config(strict=True),
        )
        assert intent.launch is None


class TestSessionState:
    """Test SessionState dataclass."""

    def test_create_manifest(self) -> None:
        """Create a complete SessionState."""
        manifest = SessionState(
            schema_version=SCHEMA_VERSION,
            name="test-session",
            created_at="2024-12-17T10:00:00",
            last_accessed_at="2024-12-17T11:00:00",
        )
        assert manifest.schema_version == SCHEMA_VERSION
        assert manifest.name == "test-session"
        assert manifest.is_fork is False
        assert manifest.is_incognito is False
        assert manifest.intent is not None
        assert manifest.confirmed is not None


class TestSessionIndex:
    """Test SessionIndex dataclass."""

    def test_default_values(self) -> None:
        """SessionIndex should have sensible defaults."""
        index = SessionIndex()
        assert index.version == INDEX_VERSION
        assert index.sessions == {}

    def test_with_entries(self) -> None:
        """SessionIndex can hold multiple entries."""
        entry = SessionIndexEntry(
            worktree_path="/path/to/worktree",
            project_root="/path/to/project",
            last_accessed_at="2024-12-17T10:00:00",
        )
        index = SessionIndex(sessions={"test-session": entry})
        assert "test-session" in index.sessions
        assert index.sessions["test-session"].worktree_path == "/path/to/worktree"

    def test_index_entry_project_identity_fields(self) -> None:
        """SessionIndexEntry supports forge_root, checkout_root, relative_path."""
        entry = SessionIndexEntry(
            worktree_path="/path/to/worktree",
            project_root="/path/to/project",
            last_accessed_at="2024-12-17T10:00:00",
            forge_root="/path/to/worktree/subdir",
            checkout_root="/path/to/worktree",
            relative_path="subdir",
        )
        assert entry.forge_root == "/path/to/worktree/subdir"
        assert entry.checkout_root == "/path/to/worktree"
        assert entry.relative_path == "subdir"

    def test_index_entry_project_identity_defaults(self) -> None:
        """Identity fields default to empty string / '.' when not provided."""
        entry = SessionIndexEntry(
            worktree_path="/path/to/worktree",
            project_root="/path/to/project",
            last_accessed_at="2024-12-17T10:00:00",
        )
        assert entry.forge_root == ""
        assert entry.checkout_root == ""
        assert entry.relative_path == "."


class TestCreateSessionState:
    """Test create_session_state factory function."""

    # Default proxy values for tests (proxy is required in v1 manifests)
    DEFAULT_PROXY_TEMPLATE = "test-family"
    DEFAULT_PROXY_URL = "http://localhost:8080"

    def test_minimal_manifest(self) -> None:
        """Create manifest with required proxy fields."""
        manifest = create_session_state(
            "test-session",
            proxy_template=self.DEFAULT_PROXY_TEMPLATE,
            proxy_base_url=self.DEFAULT_PROXY_URL,
        )
        assert manifest.schema_version == SCHEMA_VERSION
        assert manifest.name == "test-session"
        assert manifest.parent_session is None
        assert manifest.is_fork is False
        assert manifest.is_incognito is False
        assert manifest.worktree is None
        # Proxy is now always set (required)
        assert manifest.intent.proxy is not None
        assert manifest.intent.proxy.template == self.DEFAULT_PROXY_TEMPLATE
        assert manifest.intent.proxy.base_url == self.DEFAULT_PROXY_URL
        assert manifest.confirmed.claude_session_id is None

    def test_timestamps_are_set(self) -> None:
        """Factory should set timestamps to now."""
        before = now_iso()
        manifest = create_session_state(
            "test-session",
            proxy_template=self.DEFAULT_PROXY_TEMPLATE,
            proxy_base_url=self.DEFAULT_PROXY_URL,
        )
        after = now_iso()

        # Timestamps should be between before and after
        assert before <= manifest.created_at <= after
        assert before <= manifest.last_accessed_at <= after
        assert manifest.created_at == manifest.last_accessed_at

    def test_with_proxy(self) -> None:
        """Create manifest with specific proxy configuration."""
        manifest = create_session_state(
            "test-session",
            proxy_template="litellm-gemini",
            proxy_base_url="http://localhost:8084",
        )
        assert manifest.intent.proxy is not None
        assert manifest.intent.proxy.template == "litellm-gemini"
        assert manifest.intent.proxy.base_url == "http://localhost:8084"

    def test_without_proxy_creates_direct_session(self) -> None:
        """Create manifest without proxy intent for direct/no-proxy sessions."""
        manifest = create_session_state("direct-session")
        assert manifest.intent.proxy is None

    def test_partial_proxy_configuration_is_rejected(self) -> None:
        """Factory should require complete proxy config when proxy intent is present."""
        with pytest.raises(ValueError, match="provided together"):
            create_session_state(
                "broken-session",
                proxy_template=self.DEFAULT_PROXY_TEMPLATE,
            )

    def test_with_worktree(self) -> None:
        """create_session_state sets is_worktree=False; manager sets True after creation."""
        manifest = create_session_state(
            "test-session",
            proxy_template=self.DEFAULT_PROXY_TEMPLATE,
            proxy_base_url=self.DEFAULT_PROXY_URL,
            worktree_path="/path/to/worktree",
            worktree_branch="feature/auth",
        )
        assert manifest.worktree is not None
        assert manifest.worktree.path == "/path/to/worktree"
        assert manifest.worktree.branch == "feature/auth"
        assert manifest.worktree.is_worktree is False

    def test_persists_launch_preferences(self) -> None:
        """create_session_state persists relaunch preferences in intent.launch."""
        manifest = create_session_state(
            "sidecar-session",
            proxy_template=self.DEFAULT_PROXY_TEMPLATE,
            proxy_base_url=self.DEFAULT_PROXY_URL,
            launch_mode="sidecar",
            sidecar_mounts=["/data:/mnt/data:ro"],
            sidecar_image="forge-sidecar:test",
        )
        assert manifest.intent.launch is not None
        assert manifest.intent.launch.mode == "sidecar"
        assert manifest.intent.launch.sidecar is not None
        assert manifest.intent.launch.sidecar.mounts == ["/data:/mnt/data:ro"]
        assert manifest.intent.launch.sidecar.image == "forge-sidecar:test"

    def test_worktree_branch_defaults_to_name(self) -> None:
        """Worktree branch defaults to session name if not specified."""
        manifest = create_session_state(
            "test-session",
            proxy_template=self.DEFAULT_PROXY_TEMPLATE,
            proxy_base_url=self.DEFAULT_PROXY_URL,
            worktree_path="/path",
        )
        assert manifest.worktree is not None
        assert manifest.worktree.branch == "test-session"

    def test_fork_configuration(self) -> None:
        """Create manifest for a forked session."""
        manifest = create_session_state(
            "fork-session",
            proxy_template=self.DEFAULT_PROXY_TEMPLATE,
            proxy_base_url=self.DEFAULT_PROXY_URL,
            parent_session="parent-session",
            is_fork=True,
        )
        assert manifest.is_fork is True
        assert manifest.parent_session == "parent-session"

    def test_incognito_configuration(self) -> None:
        """Create manifest for an incognito session."""
        manifest = create_session_state(
            "incognito-session",
            proxy_template=self.DEFAULT_PROXY_TEMPLATE,
            proxy_base_url=self.DEFAULT_PROXY_URL,
            is_incognito=True,
        )
        assert manifest.is_incognito is True

    def test_policy_intent_bundle_config_default(self) -> None:
        """PolicyIntent.bundle_config defaults to empty dict."""
        from forge.session.models import PolicyIntent

        policy = PolicyIntent()
        assert policy.bundle_config == {}
        assert isinstance(policy.bundle_config, dict)


class TestVerificationConfig:
    """Test VerificationConfig dataclass (Ralph-Wiggum pattern)."""

    def test_default_values(self) -> None:
        """VerificationConfig should have sensible defaults."""
        config = VerificationConfig()
        assert config.type == "completion_promise"
        assert config.promise is None
        assert config.max_iterations == 50
        assert config.max_minutes is None
        assert config.bypass is False
        assert config.on_incomplete == "block"
        assert config.re_inject_prompt is None

    def test_with_promise(self) -> None:
        """VerificationConfig can specify a completion promise."""
        config = VerificationConfig(
            promise="✓ COMPLETE",
            max_iterations=10,
            max_minutes=30,
        )
        assert config.promise == "✓ COMPLETE"
        assert config.max_iterations == 10
        assert config.max_minutes == 30

    def test_on_incomplete_modes(self) -> None:
        """VerificationConfig supports block/warn/allow modes."""
        for mode in ("block", "warn", "allow"):
            config = VerificationConfig(on_incomplete=mode)
            assert config.on_incomplete == mode

    def test_with_custom_re_inject_prompt(self) -> None:
        """VerificationConfig can specify custom re-inject prompt."""
        prompt = "Please complete the task and output ✓ COMPLETE"
        config = VerificationConfig(
            promise="✓ COMPLETE",
            re_inject_prompt=prompt,
        )
        assert config.re_inject_prompt == prompt

    def test_bypass_mode(self) -> None:
        """VerificationConfig bypass mode skips verification."""
        config = VerificationConfig(bypass=True)
        assert config.bypass is True


class TestVerificationConfirmed:
    """Test VerificationConfirmed dataclass (hook-owned runtime state)."""

    def test_default_values(self) -> None:
        """VerificationConfirmed should have empty defaults."""
        confirmed = VerificationConfirmed()
        assert confirmed.started_at is None
        assert confirmed.iterations == 0
        assert confirmed.last_result is None
        assert confirmed.last_error is None

    def test_with_values(self) -> None:
        """VerificationConfirmed can track runtime state."""
        confirmed = VerificationConfirmed(
            started_at="2024-12-17T10:00:00Z",
            iterations=3,
            last_result="failed",
            last_error="Promise not found in assistant message",
        )
        assert confirmed.started_at == "2024-12-17T10:00:00Z"
        assert confirmed.iterations == 3
        assert confirmed.last_result == "failed"
        assert confirmed.last_error == "Promise not found in assistant message"

    def test_result_types(self) -> None:
        """VerificationConfirmed supports various result types."""
        result_types = [
            "passed",
            "failed",
            "warned",
            "max_iterations",
            "max_minutes",
            "bypassed",
            "error",
        ]
        for result in result_types:
            confirmed = VerificationConfirmed(last_result=result)
            assert confirmed.last_result == result


class TestSessionIntentWithVerification:
    """Test SessionIntent with verification configuration."""

    def test_default_no_verification(self) -> None:
        """SessionIntent should have no verification by default."""
        intent = SessionIntent()
        assert intent.verification is None

    def test_with_verification(self) -> None:
        """SessionIntent can include verification configuration."""
        verification = VerificationConfig(promise="✓ DONE", max_iterations=5)
        intent = SessionIntent(verification=verification)
        assert intent.verification is not None
        assert intent.verification.promise == "✓ DONE"
        assert intent.verification.max_iterations == 5


class TestSessionConfirmedWithVerification:
    """Test SessionConfirmed with verification state."""

    def test_default_no_verification(self) -> None:
        """SessionConfirmed should have no verification state by default."""
        confirmed = SessionConfirmed()
        assert confirmed.verification is None

    def test_with_verification_state(self) -> None:
        """SessionConfirmed can track verification runtime state."""
        verification = VerificationConfirmed(
            started_at="2024-12-17T10:00:00Z",
            iterations=2,
            last_result="failed",
        )
        confirmed = SessionConfirmed(verification=verification)
        assert confirmed.verification is not None
        assert confirmed.verification.iterations == 2
        assert confirmed.verification.last_result == "failed"


class TestMemoryWriterConfig:
    """Test MemoryWriterConfig dataclass."""

    def test_default_values(self) -> None:
        """MemoryWriterConfig should have sensible defaults."""
        config = MemoryWriterConfig()
        assert config.enabled is False
        assert config.mode == "augment"
        assert config.proxy is None
        assert config.direct is False
        assert config.min_turns == 5

    def test_custom_values(self) -> None:
        """MemoryWriterConfig can be fully customized."""
        config = MemoryWriterConfig(
            enabled=True,
            mode="review-only",
            proxy="litellm-haiku",
            direct=False,
            min_turns=3,
        )
        assert config.enabled is True
        assert config.mode == "review-only"
        assert config.proxy == "litellm-haiku"
        assert config.min_turns == 3


class TestMemoryIntentWithHandoff:
    """Test MemoryIntent with auto_update (MemoryWriterConfig) field."""

    def test_default_no_auto_update(self) -> None:
        """MemoryIntent should have no auto_update by default."""
        memory = MemoryIntent()
        assert memory.auto_update is None

    def test_with_auto_update(self) -> None:
        """MemoryIntent can include handoff agent configuration."""
        handoff = MemoryWriterConfig(enabled=True, min_turns=3)
        memory = MemoryIntent(auto_update=handoff)
        assert memory.auto_update is not None
        assert memory.auto_update.enabled is True
        assert memory.auto_update.min_turns == 3

    def test_dacite_round_trip_with_auto_update(self) -> None:
        """MemoryIntent with auto_update survives dacite serialization."""
        from dataclasses import asdict

        import dacite

        memory = MemoryIntent(
            auto_recall=True,
            auto_update=MemoryWriterConfig(enabled=True, mode="review-only"),
        )
        data = asdict(memory)
        restored = dacite.from_dict(MemoryIntent, data, config=dacite.Config(strict=True))
        assert restored.auto_recall is True
        assert restored.auto_update is not None
        assert restored.auto_update.enabled is True
        assert restored.auto_update.mode == "review-only"

    def test_dacite_round_trip_without_auto_update(self) -> None:
        """MemoryIntent without auto_update survives dacite serialization."""
        from dataclasses import asdict

        import dacite

        memory = MemoryIntent(strategy="full")
        data = asdict(memory)
        restored = dacite.from_dict(MemoryIntent, data, config=dacite.Config(strict=True))
        assert restored.auto_update is None
        assert restored.strategy == "full"

    def test_dacite_from_dict_missing_auto_update(self) -> None:
        """Old manifests without auto_update should deserialize correctly."""
        import dacite

        # Simulates an old manifest that doesn't have the auto_update field
        data = {
            "auto_recall": False,
            "tags": [],
            "strategy": "summary",
            "max_chars": 6000,
            "generated_file": None,
        }
        restored = dacite.from_dict(MemoryIntent, data, config=dacite.Config(strict=True))
        assert restored.auto_update is None


class TestDesignatedDoc:
    """Test DesignatedDoc dataclass."""

    def test_default_values(self) -> None:
        """DesignatedDoc should default to 'generic' strategy and no shadows."""
        doc = DesignatedDoc(path="docs/foo.md")
        assert doc.path == "docs/foo.md"
        assert doc.strategy == "generic"
        assert doc.shadows is None

    def test_custom_values(self) -> None:
        """DesignatedDoc can be fully customized."""
        doc = DesignatedDoc(path=".forge/memory/project-state.md", strategy="project-state")
        assert doc.path == ".forge/memory/project-state.md"
        assert doc.strategy == "project-state"

    def test_shadow_doc(self) -> None:
        """DesignatedDoc with shadows field for shadow/propose mode."""
        doc = DesignatedDoc(
            path=".forge/memory/shadow_standards.md",
            strategy="generic",
            shadows="docs/developer/coding-standards.md",
        )
        assert doc.shadows == "docs/developer/coding-standards.md"
        assert doc.strategy == "generic"

    def test_path_is_relative(self) -> None:
        """Path should be worktree-relative, not absolute."""
        doc = DesignatedDoc(path="docs/checklist.md")
        from pathlib import Path

        assert not Path(doc.path).is_absolute()


class TestConstants:
    """Test module constants."""

    def test_schema_version(self) -> None:
        """SCHEMA_VERSION should be 1 for the first OSS manifest format."""
        assert SCHEMA_VERSION == 1

    def test_index_version(self) -> None:
        """INDEX_VERSION should be 1."""
        assert INDEX_VERSION == 1
