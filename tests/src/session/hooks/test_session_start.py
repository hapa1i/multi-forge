"""Tests for SessionStart hook handler."""

from __future__ import annotations

import os
import time
from multiprocessing import Process
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from forge.session import (
    IndexStore,
    SessionStore,
    create_session_state,
)
from forge.session.active import ActiveSessionStore
from forge.session.config import LAUNCH_MODE_HOST
from forge.session.hooks import (
    ENV_FORK_NAME,
    ENV_SESSION,
    HookInput,
    HookResult,
    ResolutionContext,
    handle_session_start,
    parse_hook_input,
    resolve_session_name,
)


def _hold_lock(lock_path: str, hold_s: float) -> None:
    import fcntl

    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        Path(f"{lock_path}.ready").write_text("1")
        time.sleep(hold_s)


# Test constants
DEFAULT_PROXY_TEMPLATE = "test-family"
DEFAULT_PROXY_URL = "http://localhost:8080"


@pytest.fixture
def temp_worktree(tmp_path: Path) -> Path:
    """Create a temporary worktree directory with .claude folder."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    return tmp_path


@pytest.fixture
def temp_index(tmp_path: Path) -> IndexStore:
    """Create a temporary index store."""
    index_path = tmp_path / "index.json"
    return IndexStore(index_path)


@pytest.fixture
def sample_manifest(temp_worktree: Path) -> None:
    """Create a sample manifest in the temp worktree."""
    manifest = create_session_state(
        "test-session",
        proxy_template=DEFAULT_PROXY_TEMPLATE,
        proxy_base_url=DEFAULT_PROXY_URL,
    )
    manifest.confirmed.claude_session_id = "original-uuid-123"
    store = SessionStore(str(temp_worktree), "test-session")
    store.write(manifest)


class TestResolveSessionName:
    """Tests for resolve_session_name()."""

    def test_resolve_priority_1_fork_env(self, temp_worktree: Path, temp_index: IndexStore) -> None:
        """FORGE_FORK_NAME env var should have highest priority."""
        with patch.dict(os.environ, {ENV_FORK_NAME: "fork-name", ENV_SESSION: "session-name"}):
            ctx = resolve_session_name("startup", "uuid-123", temp_worktree, temp_index)

        assert ctx.resolved
        assert ctx.session_name == "fork-name"
        assert ctx.resolution_method == "fork_env"

    def test_resolve_priority_2_session_env(self, temp_worktree: Path, temp_index: IndexStore) -> None:
        """FORGE_SESSION env var should be second priority."""
        with patch.dict(os.environ, {ENV_SESSION: "session-name"}, clear=False):
            # Ensure FORGE_FORK_NAME is not set
            env = os.environ.copy()
            env.pop(ENV_FORK_NAME, None)
            with patch.dict(os.environ, env, clear=True):
                with patch.dict(os.environ, {ENV_SESSION: "session-name"}):
                    ctx = resolve_session_name("startup", "uuid-123", temp_worktree, temp_index)

        assert ctx.resolved
        assert ctx.session_name == "session-name"
        assert ctx.resolution_method == "session_env"

    def test_resolve_priority_3_uuid_lookup(self, temp_worktree: Path, temp_index: IndexStore) -> None:
        """UUID lookup should be third priority (after env vars)."""
        # Add session to index with a UUID
        temp_index.add_session("uuid-session", str(temp_worktree), str(temp_worktree), claude_session_id="uuid-123")

        # Clear env vars
        with patch.dict(os.environ, {}, clear=True):
            ctx = resolve_session_name("compact", "uuid-123", temp_worktree, temp_index)

        assert ctx.resolved
        assert ctx.session_name == "uuid-session"
        assert ctx.resolution_method == "uuid_lookup"

    def test_no_dir_scan_fallback(self, temp_worktree: Path, temp_index: IndexStore) -> None:
        """Without env var or UUID in index, resolution fails (no CWD scan)."""
        # Create a session manifest with a known UUID directly in the per-session dir
        manifest = create_session_state(
            "scanned-session",
            proxy_template=DEFAULT_PROXY_TEMPLATE,
            proxy_base_url=DEFAULT_PROXY_URL,
        )
        manifest.confirmed.claude_session_id = "uuid-scan-456"
        store = SessionStore(str(temp_worktree), "scanned-session")
        store.write(manifest)

        # Clear env vars, don't add to index — no CWD scan means this won't resolve
        with patch.dict(os.environ, {}, clear=True):
            ctx = resolve_session_name("compact", "uuid-scan-456", temp_worktree, temp_index)

        assert not ctx.resolved
        assert ctx.session_name is None
        assert len(ctx.errors) > 0

    def test_resolve_fails_when_not_found(self, temp_worktree: Path, temp_index: IndexStore) -> None:
        """Resolution should fail gracefully when session not found."""
        with patch.dict(os.environ, {}, clear=True):
            ctx = resolve_session_name("compact", "unknown-uuid", temp_worktree, temp_index)

        assert not ctx.resolved
        assert ctx.session_name is None
        assert len(ctx.errors) > 0


class TestHandleSessionStart:
    """Tests for handle_session_start()."""

    def test_handle_startup_no_proxy_env_does_not_capture_started_with_proxy(
        self, temp_worktree: Path, temp_index: IndexStore, sample_manifest: None
    ) -> None:
        """No ANTHROPIC_BASE_URL should not populate confirmed.started_with_proxy."""
        hook_input = HookInput(
            session_id="new-uuid-456",
            transcript_path="/path/to/transcript.jsonl",
            source="startup",
        )

        with patch.dict(os.environ, {"FORGE_SESSION": "test-session"}, clear=True):
            result = handle_session_start(hook_input, temp_worktree, temp_index)

        assert result.success

        store = SessionStore(str(temp_worktree), "test-session")
        manifest = store.read()
        assert manifest.confirmed.started_with_proxy is None

    def test_handle_startup_any_base_url_captures_started_with_proxy(
        self, temp_worktree: Path, temp_index: IndexStore, sample_manifest: None
    ) -> None:
        """Any ANTHROPIC_BASE_URL should populate confirmed.started_with_proxy.

        Bug fix: Previously only localhost URLs were captured, but this
        was overly restrictive - remote proxies, Docker hostnames, etc. were missed.
        """
        hook_input = HookInput(
            session_id="new-uuid-456",
            transcript_path="/path/to/transcript.jsonl",
            source="startup",
        )

        with patch.dict(
            os.environ,
            {
                "FORGE_SESSION": "test-session",
                "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
            },
            clear=True,
        ):
            result = handle_session_start(hook_input, temp_worktree, temp_index)

        assert result.success

        store = SessionStore(str(temp_worktree), "test-session")
        manifest = store.read()
        assert manifest.confirmed.started_with_proxy is not None
        assert manifest.confirmed.started_with_proxy.base_url == "https://api.anthropic.com"

    def test_handle_startup_updates_active_registry_uuid(
        self, temp_worktree: Path, temp_index: IndexStore, sample_manifest: None, tmp_path: Path
    ) -> None:
        """SessionStart should reconcile the runtime registry UUID too."""
        active_store = ActiveSessionStore(tmp_path / "active.json")
        active_store.upsert_session(
            "test-session",
            worktree_path=str(temp_worktree),
            launch_mode=LAUNCH_MODE_HOST,
            launcher_pid=os.getpid(),
        )

        hook_input = HookInput(
            session_id="new-uuid-456",
            transcript_path="/path/to/transcript.jsonl",
            source="startup",
        )

        with patch.dict(os.environ, {"FORGE_SESSION": "test-session"}, clear=True):
            with patch("forge.session.active.get_active_index_path", return_value=tmp_path / "active.json"):
                result = handle_session_start(hook_input, temp_worktree, temp_index)

        assert result.success
        entry = active_store.get_session("test-session")
        assert entry is not None
        assert entry.claude_session_id == "new-uuid-456"

    def test_handle_startup_skips_when_manifest_lock_contended(
        self, temp_worktree: Path, temp_index: IndexStore, sample_manifest: None
    ) -> None:
        """Hook should fail-open (skip) when manifest lock is contended."""
        store = SessionStore(str(temp_worktree), "test-session")
        lock_path = store.manifest_path.parent / f"{store.manifest_path.name}.lock"

        proc = Process(target=_hold_lock, args=(str(lock_path), 0.5))
        proc.start()

        ready_path = Path(f"{lock_path}.ready")

        try:
            deadline = time.monotonic() + 2.0
            while not ready_path.exists():
                if time.monotonic() >= deadline:
                    raise RuntimeError("child process did not acquire lock in time")
                time.sleep(0.01)

            hook_input = HookInput(
                session_id="new-uuid-456",
                transcript_path="/path/to/transcript.jsonl",
                source="startup",
            )

            with patch.dict(os.environ, {"FORGE_SESSION": "test-session"}, clear=True):
                result = handle_session_start(hook_input, temp_worktree, temp_index)

            assert result.success
            assert result.error == "skip_lock_contended"

        finally:
            proc.join(timeout=2.0)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=2.0)

    def test_handle_startup_sets_confirmed_fields(
        self, temp_worktree: Path, temp_index: IndexStore, sample_manifest: None
    ) -> None:
        """startup source should set confirmed fields."""
        hook_input = HookInput(
            session_id="new-uuid-456",
            transcript_path="/path/to/transcript.jsonl",
            source="startup",
        )

        # Mock registry to resolve proxy_id from base_url
        mock_entry = type(
            "ProxyEntry",
            (),
            {
                "proxy_id": "proxy_test",
                "template": "litellm-openai",
                "base_url": "http://localhost:8084",
                "port": 8084,
            },
        )()

        with (
            patch.dict(
                os.environ,
                {
                    "FORGE_SESSION": "test-session",
                    "ANTHROPIC_BASE_URL": "http://localhost:8084",
                    "ACTIVE_TEMPLATE": "litellm-openai",
                },
                clear=True,
            ),
            patch("forge.proxy.proxies.ProxyRegistryStore") as mock_store_cls,
        ):
            mock_store_cls.return_value.find_by_base_url.return_value = mock_entry
            result = handle_session_start(hook_input, temp_worktree, temp_index)

        assert result.success
        assert result.session_name == "test-session"

        # Verify manifest was updated
        store = SessionStore(str(temp_worktree), "test-session")
        manifest = store.read()
        assert manifest.confirmed.transcript_path == "/path/to/transcript.jsonl"
        assert manifest.confirmed.confirmed_by == "hook:SessionStart:startup"
        assert manifest.confirmed.confirmed_at is not None

        assert manifest.confirmed.started_with_proxy is not None
        assert manifest.confirmed.started_with_proxy.base_url == "http://localhost:8084"
        assert manifest.confirmed.started_with_proxy.port == 8084
        assert manifest.confirmed.started_with_proxy.template == "litellm-openai"
        assert manifest.confirmed.started_with_proxy.proxy_id == "proxy_test"

    def test_handle_session_not_found(self, temp_worktree: Path, temp_index: IndexStore) -> None:
        """Should return error when session cannot be resolved."""
        hook_input = HookInput(
            session_id="unknown-uuid",
            transcript_path="/path/to/transcript.jsonl",
            source="startup",
        )

        with patch.dict(os.environ, {}, clear=True):
            result = handle_session_start(hook_input, temp_worktree, temp_index)

        assert not result.success
        assert result.error == "session_not_found"

    def test_handle_manifest_not_found(self, temp_worktree: Path, temp_index: IndexStore) -> None:
        """Should return error when manifest doesn't exist."""
        hook_input = HookInput(
            session_id="uuid-123",
            transcript_path="/path/to/transcript.jsonl",
            source="startup",
        )

        with patch.dict(os.environ, {"FORGE_SESSION": "nonexistent-session"}, clear=True):
            result = handle_session_start(hook_input, temp_worktree, temp_index)

        assert not result.success
        assert result.error == "manifest_not_found"

    def test_handle_name_mismatch_is_not_found(
        self, temp_worktree: Path, temp_index: IndexStore, sample_manifest: None
    ) -> None:
        """With per-session dirs, wrong name → different directory → not found."""
        # Persist a different name than what's in the manifest.
        # With per-session directories, "different-session" looks in
        # sessions/different-session/ which is empty — manifest_not_found.
        hook_input = HookInput(
            session_id="uuid-123",
            transcript_path="/path/to/transcript.jsonl",
            source="startup",
        )

        with patch.dict(os.environ, {"FORGE_SESSION": "different-session"}, clear=True):
            result = handle_session_start(hook_input, temp_worktree, temp_index)

        assert not result.success
        assert result.error == "manifest_not_found"

    def test_handle_echoes_input_fields(
        self, temp_worktree: Path, temp_index: IndexStore, sample_manifest: None
    ) -> None:
        """Result should echo input fields for debugging."""
        hook_input = HookInput(
            session_id="uuid-123",
            transcript_path="/path/to/transcript.jsonl",
            source="resume",
        )

        with patch.dict(os.environ, {"FORGE_SESSION": "test-session"}, clear=True):
            result = handle_session_start(hook_input, temp_worktree, temp_index)

        assert result.received_session_id == "uuid-123"
        assert result.received_transcript_path == "/path/to/transcript.jsonl"
        assert result.received_source == "resume"

    def test_handle_compact_tracks_rollover_artifact(
        self, temp_worktree: Path, temp_index: IndexStore, sample_manifest: None
    ) -> None:
        """compact should snapshot the previous transcript and record it in artifacts."""
        previous_transcript = temp_worktree / "previous.jsonl"
        previous_transcript.write_text('{"type":"assistant"}\n', encoding="utf-8")

        store = SessionStore(str(temp_worktree), "test-session")

        def _set_previous_transcript(manifest) -> None:
            manifest.confirmed.transcript_path = str(previous_transcript)

        store.update(timeout_s=5.0, mutate=_set_previous_transcript)

        hook_input = HookInput(
            session_id="new-uuid-456",
            transcript_path="/path/to/new-transcript.jsonl",
            source="compact",
        )

        with patch.dict(os.environ, {"FORGE_SESSION": "test-session"}, clear=True):
            result = handle_session_start(hook_input, temp_worktree, temp_index)

        assert result.success

        manifest = store.read()
        transcripts = manifest.confirmed.artifacts.get("transcripts")
        assert isinstance(transcripts, list)
        assert len(transcripts) == 1
        assert transcripts[0]["reason"] == "rollover"
        assert transcripts[0]["session_id"] == "original-uuid-123"
        assert transcripts[0]["source_path"] == str(previous_transcript)
        assert transcripts[0]["copied_path"] == ".forge/artifacts/test-session/transcripts/original-uuid-123.jsonl"

        rollover_copy = (
            temp_worktree / ".forge" / "artifacts" / "test-session" / "transcripts" / "original-uuid-123.jsonl"
        )
        assert rollover_copy.exists()

    def _seed_supervisor_degrade(self, store: SessionStore) -> None:
        """Seed a sticky codex degrade marker into the manifest (under the store lock)."""
        from forge.policy.supervisor_lane_degrade import set_supervisor_degrade
        from forge.session.models import LaneRecord

        codex = LaneRecord("codex", "chatgpt", "gpt-5-codex")
        store.update(
            timeout_s=5.0,
            mutate=lambda m: set_supervisor_degrade(
                m, from_lane=codex, to_lane=None, reason="subscription_exhausted", at="2026-06-30T00:00:00Z"
            ),
        )

    def test_resume_clears_supervisor_degrade(
        self, temp_worktree: Path, temp_index: IndexStore, sample_manifest: None
    ) -> None:
        """T7: resume is a fresh process re-entry, so the sticky codex degrade is cleared --
        the weekly quota may have refilled, so let the next check re-probe codex."""
        from forge.policy.supervisor_lane_degrade import is_supervisor_degraded

        store = SessionStore(str(temp_worktree), "test-session")
        self._seed_supervisor_degrade(store)
        assert is_supervisor_degraded(store.read()) is True  # precondition

        hook_input = HookInput(
            session_id="new-uuid-456",
            transcript_path="/path/to/transcript.jsonl",
            source="resume",
        )
        with patch.dict(os.environ, {"FORGE_SESSION": "test-session"}, clear=True):
            result = handle_session_start(hook_input, temp_worktree, temp_index)

        assert result.success
        assert is_supervisor_degraded(store.read()) is False

    def test_compact_preserves_supervisor_degrade(
        self, temp_worktree: Path, temp_index: IndexStore, sample_manifest: None
    ) -> None:
        """T7: compact fires mid-sitting (quota unchanged), so the degrade stays sticky --
        re-arming codex here would just exhaust and re-degrade (flap)."""
        from forge.policy.supervisor_lane_degrade import is_supervisor_degraded

        store = SessionStore(str(temp_worktree), "test-session")
        self._seed_supervisor_degrade(store)

        hook_input = HookInput(
            session_id="new-uuid-456",
            transcript_path="/path/to/new-transcript.jsonl",
            source="compact",
        )
        with patch.dict(os.environ, {"FORGE_SESSION": "test-session"}, clear=True):
            result = handle_session_start(hook_input, temp_worktree, temp_index)

        assert result.success
        assert is_supervisor_degraded(store.read()) is True

    def test_handle_compact_tracks_rollover_artifact_in_resolved_forge_root(
        self, temp_worktree: Path, temp_index: IndexStore, sample_manifest: None, tmp_path: Path
    ) -> None:
        """compact should write rollover artifacts under the resolved forge_root, not the caller CWD."""
        previous_transcript = temp_worktree / "previous.jsonl"
        previous_transcript.write_text('{"type":"assistant"}\n', encoding="utf-8")

        nested_forge_root = temp_worktree / "nested-project"
        nested_forge_root.mkdir(parents=True)

        nested_store = SessionStore(str(nested_forge_root), "test-session")
        base_store = SessionStore(str(temp_worktree), "test-session")
        manifest = base_store.read()
        manifest.forge_root = str(nested_forge_root)
        nested_store.write(manifest)

        temp_index.add_session(
            "test-session",
            str(temp_worktree),
            str(temp_worktree),
            claude_session_id="original-uuid-123",
            forge_root=str(nested_forge_root),
            checkout_root=str(temp_worktree),
            relative_path="nested-project",
        )

        def _set_previous_transcript(state) -> None:
            state.confirmed.transcript_path = str(previous_transcript)

        nested_store.update(timeout_s=5.0, mutate=_set_previous_transcript)

        hook_input = HookInput(
            session_id="new-uuid-456",
            transcript_path="/path/to/new-transcript.jsonl",
            source="compact",
        )

        off_root_cwd = tmp_path / "outside"
        off_root_cwd.mkdir()

        with patch.dict(
            os.environ,
            {ENV_SESSION: "test-session", "FORGE_FORGE_ROOT": str(nested_forge_root)},
            clear=True,
        ):
            result = handle_session_start(hook_input, off_root_cwd, temp_index)

        assert result.success

        updated = nested_store.read()
        transcripts = updated.confirmed.artifacts.get("transcripts")
        assert isinstance(transcripts, list)
        assert transcripts[0]["copied_path"] == ".forge/artifacts/test-session/transcripts/original-uuid-123.jsonl"

        nested_copy = (
            nested_forge_root / ".forge" / "artifacts" / "test-session" / "transcripts" / "original-uuid-123.jsonl"
        )
        assert nested_copy.exists()
        assert not (
            off_root_cwd / ".forge" / "artifacts" / "test-session" / "transcripts" / "original-uuid-123.jsonl"
        ).exists()

        assert updated.confirmed.transcript_path == "/path/to/new-transcript.jsonl"
        assert updated.confirmed.claude_session_id == "new-uuid-456"


class TestParseHookInput:
    """Tests for parse_hook_input()."""

    def test_parse_valid_input(self) -> None:
        """Should parse valid input correctly."""
        data: dict[str, Any] = {
            "session_id": "uuid-123",
            "transcript_path": "/path/to/file.jsonl",
            "source": "startup",
        }

        result = parse_hook_input(data)

        assert result is not None
        assert result.session_id == "uuid-123"
        assert result.transcript_path == "/path/to/file.jsonl"
        assert result.source == "startup"

    def test_parse_all_sources(self) -> None:
        """Should accept all valid source values."""
        for source in ["startup", "resume", "compact", "clear"]:
            data: dict[str, Any] = {
                "session_id": "uuid",
                "transcript_path": "/path",
                "source": source,
            }
            result = parse_hook_input(data)
            assert result is not None
            assert result.source == source

    def test_parse_missing_session_id(self) -> None:
        """Should return None if session_id missing."""
        data: dict[str, Any] = {
            "transcript_path": "/path",
            "source": "startup",
        }
        assert parse_hook_input(data) is None

    def test_parse_missing_transcript_path(self) -> None:
        """Should return None if transcript_path missing."""
        data: dict[str, Any] = {
            "session_id": "uuid",
            "source": "startup",
        }
        assert parse_hook_input(data) is None

    def test_parse_missing_source(self) -> None:
        """Should return None if source missing."""
        data: dict[str, Any] = {
            "session_id": "uuid",
            "transcript_path": "/path",
        }
        assert parse_hook_input(data) is None

    def test_parse_invalid_source(self) -> None:
        """Should return None if source is invalid."""
        data: dict[str, Any] = {
            "session_id": "uuid",
            "transcript_path": "/path",
            "source": "invalid",
        }
        assert parse_hook_input(data) is None

    def test_parse_non_string_session_id(self) -> None:
        """Should return None if session_id is not a string."""
        data: dict[str, Any] = {
            "session_id": 123,
            "transcript_path": "/path",
            "source": "startup",
        }
        assert parse_hook_input(data) is None


class TestHookResult:
    """Tests for HookResult.to_dict()."""

    def test_to_dict_success(self) -> None:
        """to_dict() should include all non-None fields."""
        result = HookResult(
            success=True,
            session_name="my-session",
            message="Reconciled",
            received_session_id="uuid-123",
        )

        d = result.to_dict()

        assert d["success"] is True
        assert d["session_name"] == "my-session"
        assert d["message"] == "Reconciled"
        assert d["received_session_id"] == "uuid-123"
        assert "error" not in d
        assert "received_transcript_path" not in d

    def test_to_dict_error(self) -> None:
        """to_dict() should include error field when present."""
        result = HookResult(
            success=False,
            error="session_not_found",
            message="Could not find session",
        )

        d = result.to_dict()

        assert d["success"] is False
        assert d["error"] == "session_not_found"
        assert d["message"] == "Could not find session"
        assert "session_name" not in d


class TestResolutionContext:
    """Tests for ResolutionContext."""

    def test_resolved_true_when_name_set(self) -> None:
        """resolved should be True when session_name is set."""
        ctx = ResolutionContext(session_name="test", resolution_method="session_env")
        assert ctx.resolved is True

    def test_resolved_false_when_name_none(self) -> None:
        """resolved should be False when session_name is None."""
        ctx = ResolutionContext()
        assert ctx.resolved is False

    def test_errors_default_empty(self) -> None:
        """errors should default to empty list."""
        ctx = ResolutionContext()
        assert ctx.errors == []


class TestHookIndexSync:
    """Tests for UUID index sync after hook reconciliation."""

    def test_hook_syncs_uuid_to_index(
        self, temp_worktree: Path, temp_index: IndexStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SessionStart hook should sync the new UUID to the global index."""
        # Create manifest with pre-seeded UUID
        manifest = create_session_state(
            "sync-test",
            proxy_template=DEFAULT_PROXY_TEMPLATE,
            proxy_base_url=DEFAULT_PROXY_URL,
        )
        manifest.confirmed.claude_session_id = "pre-seeded-uuid"
        store = SessionStore(str(temp_worktree), "sync-test")
        store.write(manifest)

        # Add to index with pre-seeded UUID
        temp_index.add_session(
            "sync-test",
            worktree_path=str(temp_worktree),
            project_root=str(temp_worktree),
            claude_session_id="pre-seeded-uuid",
        )

        monkeypatch.setenv(ENV_SESSION, "sync-test")
        monkeypatch.setenv("FORGE_FORGE_ROOT", str(temp_worktree))

        hook_input = HookInput(
            session_id="hook-uuid-456",
            transcript_path="/tmp/transcript.jsonl",
            source="startup",
        )

        result = handle_session_start(hook_input, temp_worktree, index_store=temp_index)
        assert result.success is True

        # Manifest should have hook UUID
        updated = store.read()
        assert updated.confirmed.claude_session_id == "hook-uuid-456"

        # Index should also have hook UUID (synced)
        found = temp_index.find_session_by_uuid("hook-uuid-456")
        assert found is not None
        assert found[0] == "sync-test"  # display name

        # Old pre-seeded UUID should no longer resolve
        assert temp_index.find_session_by_uuid("pre-seeded-uuid") is None
