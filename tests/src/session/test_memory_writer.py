"""Tests for the memory writer core module.

Covers: turn counting, prompt building, proxy resolution, writer invocation,
multi-doc strategies, shadow/propose mode, containment guard.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from forge.core.reactive.session_runner import SessionResult
from forge.core.telemetry.upstream import read_upstream_outcomes
from forge.session.memory_writer import (
    _dedupe_specs,
    _stdout_indicates_permission_denied,
    _validate_designated_docs,
    build_multi_doc_prompt,
    count_conversation_turns,
    resolve_writer_base_url,
    run_memory_writer,
)
from forge.session.models import DesignatedDoc, MemoryWriterConfig
from forge.session.passport import (
    STRATEGY_INSTRUCTIONS,
    Passport,
    PassportUpdate,
    ResolvedDocSpec,
    read_passport,
    resolve_doc_spec,
    resolve_passport_source,
    write_passport,
)

DOC_STRATEGIES = STRATEGY_INSTRUCTIONS


def _resolve_docs(docs: list[DesignatedDoc]) -> list[ResolvedDocSpec]:
    """Convert DesignatedDocs to ResolvedDocSpecs (passport-less fallback)."""
    return [resolve_doc_spec(doc, None) for doc in docs]


# ---------------------------------------------------------------------------
# Transcript fixtures
# ---------------------------------------------------------------------------


def _write_transcript(path: Path, entries: list[dict]) -> Path:
    """Write entries as JSONL to a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return path


def _make_newer_entry(request_id: str, role: str, text: str = "hello", timestamp: str = "") -> dict:
    """Create a newer-format transcript entry (requestId + message.role)."""
    return {
        "requestId": request_id,
        "timestamp": timestamp,
        "message": {
            "role": role,
            "content": [{"type": "text", "text": text}],
        },
    }


def _make_older_entry(entry_type: str, text: str = "hello") -> dict:
    """Create an older-format transcript entry (type field)."""
    return {"type": entry_type, "text": text}


# ---------------------------------------------------------------------------
# count_conversation_turns
# ---------------------------------------------------------------------------


class TestCountConversationTurns:
    """Tests for counting conversation turns in transcript files."""

    def test_empty_file(self, tmp_path: Path) -> None:
        """Empty transcript returns 0 turns."""
        path = _write_transcript(tmp_path / "t.jsonl", [])
        assert count_conversation_turns(path) == 0

    def test_missing_file(self, tmp_path: Path) -> None:
        """Missing transcript file returns 0 turns."""
        assert count_conversation_turns(tmp_path / "nonexistent.jsonl") == 0

    def test_newer_format_single_turn(self, tmp_path: Path) -> None:
        """Single user+assistant pair counts as 1 turn."""
        entries = [
            _make_newer_entry("req-1", "user", "hello"),
            _make_newer_entry("req-1", "assistant", "hi there"),
        ]
        path = _write_transcript(tmp_path / "t.jsonl", entries)
        assert count_conversation_turns(path) == 1

    def test_newer_format_multi_turn(self, tmp_path: Path) -> None:
        """Multiple request groups each count as a turn."""
        entries = [
            _make_newer_entry("req-1", "user"),
            _make_newer_entry("req-1", "assistant"),
            _make_newer_entry("req-2", "user"),
            _make_newer_entry("req-2", "assistant"),
            _make_newer_entry("req-3", "user"),
            _make_newer_entry("req-3", "assistant"),
        ]
        path = _write_transcript(tmp_path / "t.jsonl", entries)
        assert count_conversation_turns(path) == 3

    def test_newer_format_assistant_only_not_counted(self, tmp_path: Path) -> None:
        """Request groups with only assistant messages don't count."""
        entries = [
            _make_newer_entry("req-1", "user"),
            _make_newer_entry("req-1", "assistant"),
            # req-2 has only assistant (e.g., tool result without user prompt)
            _make_newer_entry("req-2", "assistant"),
        ]
        path = _write_transcript(tmp_path / "t.jsonl", entries)
        assert count_conversation_turns(path) == 1

    def test_older_format_counts_human_entries(self, tmp_path: Path) -> None:
        """Older format counts entries with type='human'."""
        entries = [
            _make_older_entry("human"),
            _make_older_entry("ai"),
            _make_older_entry("human"),
            _make_older_entry("ai"),
        ]
        path = _write_transcript(tmp_path / "t.jsonl", entries)
        assert count_conversation_turns(path) == 2

    def test_older_format_no_human_entries(self, tmp_path: Path) -> None:
        """Older format with no human entries returns 0."""
        entries = [
            _make_older_entry("ai"),
            _make_older_entry("tool"),
        ]
        path = _write_transcript(tmp_path / "t.jsonl", entries)
        assert count_conversation_turns(path) == 0


# ---------------------------------------------------------------------------
# DOC_STRATEGIES
# ---------------------------------------------------------------------------


class TestDocStrategies:
    """Tests for the per-doc strategy constants."""

    def test_all_built_in_strategies_defined(self) -> None:
        """All built-in strategies have instruction text.

        Intentionally exact (not subset): forces conscious strategy additions
        and ensures removed strategies don't linger.
        """
        expected = {
            "project-state",
            "checklist",
            "changelog",
            "generic",
        }
        assert set(DOC_STRATEGIES.keys()) == expected

    def test_strategies_are_non_empty_strings(self) -> None:
        """Each strategy instruction is a non-empty string."""
        for name, instruction in DOC_STRATEGIES.items():
            assert isinstance(instruction, str), f"{name} is not a string"
            assert len(instruction) > 0, f"{name} is empty"

    def test_no_remove_instructions(self) -> None:
        """Strategy instructions must not encourage destructive edits."""
        for name, instruction in DOC_STRATEGIES.items():
            lower = instruction.lower()
            assert "remove them" not in lower, f"{name} contains 'remove them'"
            assert "delete" not in lower, f"{name} contains 'delete'"


# ---------------------------------------------------------------------------
# build_multi_doc_prompt
# ---------------------------------------------------------------------------


class TestBuildMultiDocPrompt:
    """Tests for multi-doc prompt construction."""

    def test_contains_all_doc_paths(self) -> None:
        """Prompt lists all designated document paths."""
        docs = [
            DesignatedDoc(path="docs/checklist.md", strategy="checklist"),
            DesignatedDoc(path="docs/changelog.md", strategy="changelog"),
        ]
        prompt = build_multi_doc_prompt(
            session_name="test",
            transcript_path="/abs/path/t.jsonl",
            docs=_resolve_docs(docs),
        )
        assert "docs/checklist.md" in prompt
        assert "docs/changelog.md" in prompt

    def test_checklist_strategy_content(self) -> None:
        """Checklist strategy includes mark-completed instruction."""
        docs = [DesignatedDoc(path="docs/checklist.md", strategy="checklist")]
        prompt = build_multi_doc_prompt(
            session_name="test",
            transcript_path="/abs/path/t.jsonl",
            docs=_resolve_docs(docs),
        )
        assert "Mark completed tasks" in prompt
        assert "Do NOT remove" in prompt

    def test_changelog_strategy_content(self) -> None:
        """Changelog strategy includes add-accomplishments instruction."""
        docs = [DesignatedDoc(path="docs/log.md", strategy="changelog")]
        prompt = build_multi_doc_prompt(
            session_name="test",
            transcript_path="/abs/path/t.jsonl",
            docs=_resolve_docs(docs),
        )
        assert "accomplishments" in prompt
        assert "Do NOT modify or remove" in prompt

    def test_generic_strategy_content(self) -> None:
        """Generic strategy includes read-and-add instruction."""
        docs = [DesignatedDoc(path="docs/notes.md", strategy="generic")]
        prompt = build_multi_doc_prompt(
            session_name="test",
            transcript_path="/abs/path/t.jsonl",
            docs=_resolve_docs(docs),
        )
        assert "NEW information" in prompt

    def test_unknown_strategy_falls_back_to_generic(self) -> None:
        """Unknown strategy name uses generic instructions without crashing."""
        docs = [DesignatedDoc(path="docs/foo.md", strategy="unknown-strategy")]
        prompt = build_multi_doc_prompt(
            session_name="test",
            transcript_path="/abs/path/t.jsonl",
            docs=_resolve_docs(docs),
        )
        assert "NEW information" in prompt
        assert "docs/foo.md" in prompt

    def test_review_only_mode(self) -> None:
        """Review-only mode instructs no file modifications."""
        docs = [DesignatedDoc(path="docs/foo.md")]
        prompt = build_multi_doc_prompt(
            session_name="test",
            transcript_path="/abs/path/t.jsonl",
            mode="review-only",
            docs=_resolve_docs(docs),
        )
        assert "Do NOT modify any files" in prompt

    def test_contains_session_info(self) -> None:
        """Prompt includes session name and transcript path."""
        docs = [DesignatedDoc(path="docs/foo.md")]
        prompt = build_multi_doc_prompt(
            session_name="my-session",
            transcript_path="/abs/path/t.jsonl",
            docs=_resolve_docs(docs),
        )
        assert "my-session" in prompt
        assert "/abs/path/t.jsonl" in prompt

    def test_multiple_strategies_combined(self) -> None:
        """Multiple docs with different strategies all appear in prompt."""
        docs = [
            DesignatedDoc(path=".forge/memory/project-state.md", strategy="project-state"),
            DesignatedDoc(path="docs/checklist.md", strategy="checklist"),
            DesignatedDoc(path="docs/changelog.md", strategy="changelog"),
        ]
        prompt = build_multi_doc_prompt(
            session_name="test",
            transcript_path="/abs/path/t.jsonl",
            docs=_resolve_docs(docs),
        )
        assert ".forge/memory/project-state.md" in prompt
        assert "docs/checklist.md" in prompt
        assert "docs/changelog.md" in prompt

    def test_global_rule_allows_per_file_edits(self) -> None:
        """Global prompt rule defers to per-file instructions (no contradiction)."""
        docs = [DesignatedDoc(path="docs/checklist.md", strategy="checklist")]
        prompt = build_multi_doc_prompt(
            session_name="test",
            transcript_path="/abs/path/t.jsonl",
            docs=_resolve_docs(docs),
        )
        assert "Only ADD information" not in prompt
        assert "per-file instructions" in prompt or "minimal edits" in prompt

    # Shadow/propose mode (Mode 2)

    def test_shadow_prompt_includes_official_doc(self) -> None:
        """Shadow doc prompt references the official document path."""
        docs = [
            DesignatedDoc(
                path=".forge/memory/shadow_standards.md",
                strategy="generic",
                shadows="docs/developer/coding_standards.md",
            )
        ]
        prompt = build_multi_doc_prompt(
            session_name="test",
            transcript_path="/abs/path/t.jsonl",
            docs=_resolve_docs(docs),
        )
        assert "docs/developer/coding_standards.md" in prompt
        assert ".forge/memory/shadow_standards.md" in prompt

    def test_shadow_prompt_reads_official_first(self) -> None:
        """Shadow doc prompt instructs reading the official doc first."""
        docs = [
            DesignatedDoc(
                path=".forge/memory/shadow.md",
                strategy="generic",
                shadows="OFFICIAL.md",
            )
        ]
        prompt = build_multi_doc_prompt(
            session_name="test",
            transcript_path="/abs/path/t.jsonl",
            docs=_resolve_docs(docs),
        )
        assert "Read the OFFICIAL document at `OFFICIAL.md` first" in prompt

    def test_direct_doc_no_shadow_section(self) -> None:
        """Non-shadow doc has no 'proposes changes to' text."""
        docs = [DesignatedDoc(path="docs/checklist.md", strategy="checklist")]
        prompt = build_multi_doc_prompt(
            session_name="test",
            transcript_path="/abs/path/t.jsonl",
            docs=_resolve_docs(docs),
        )
        assert "proposes changes to" not in prompt

    def test_mixed_shadow_and_direct(self) -> None:
        """Prompt handles both shadow and direct docs in one invocation."""
        docs = [
            DesignatedDoc(path="docs/checklist.md", strategy="checklist"),
            DesignatedDoc(
                path=".forge/memory/shadow.md",
                strategy="generic",
                shadows="STANDARDS.md",
            ),
        ]
        prompt = build_multi_doc_prompt(
            session_name="test",
            transcript_path="/abs/path/t.jsonl",
            docs=_resolve_docs(docs),
        )
        # Direct doc: no shadow language
        assert "docs/checklist.md" in prompt
        assert "Mark completed tasks" in prompt
        # Shadow doc: has shadow language
        assert "proposes changes to `STANDARDS.md`" in prompt
        assert "Read the OFFICIAL document" in prompt

    def test_shadow_prompt_includes_liberal_framing(self) -> None:
        """Shadow docs include liberal suggestion framing."""
        docs = [
            DesignatedDoc(
                path=".forge/memory/shadow.md",
                strategy="generic",
                shadows="OFFICIAL.md",
            ),
        ]
        prompt = build_multi_doc_prompt(
            session_name="test",
            transcript_path="/abs/path/t.jsonl",
            docs=_resolve_docs(docs),
        )
        assert "Propose additions as `- [ ]` checkboxes" in prompt
        assert "self-prune" in prompt.lower()

    def test_direct_doc_no_liberal_framing(self) -> None:
        """Direct docs do NOT include liberal suggestion framing."""
        docs = [DesignatedDoc(path="docs/checklist.md", strategy="checklist")]
        prompt = build_multi_doc_prompt(
            session_name="test",
            transcript_path="/abs/path/t.jsonl",
            docs=_resolve_docs(docs),
        )
        assert "Propose additions as `- [ ]` checkboxes" not in prompt


# ---------------------------------------------------------------------------
# resolve_writer_base_url
# ---------------------------------------------------------------------------


def _unresolved_result():
    """RoutingResult with no base_url (unresolved)."""
    from forge.core.reactive.routing import RoutingResult

    return RoutingResult(
        base_url=None,
        proxy_id=None,
        template=None,
        source="unresolved",
        route=None,
        credential=None,
    )


def _resolved_result(base_url: str = "http://proxy:8080"):
    """RoutingResult with a resolved base_url."""
    from forge.core.reactive.routing import RoutingResult

    return RoutingResult(
        base_url=base_url,
        proxy_id="my-proxy",
        template="litellm-openai",
        source="preferred_proxy",
        route=None,
        credential=None,
    )


class TestResolveHandoffBaseUrl:
    """Tests for proxy base URL resolution via shared resolver."""

    def test_proxy_id_takes_priority(self) -> None:
        """When proxy_id resolves via shared resolver, it takes priority."""
        with patch(
            "forge.session.memory_writer.resolve_subprocess_routing",
            return_value=_resolved_result("http://proxy-from-registry:8080"),
        ):
            result = resolve_writer_base_url(
                proxy_id="my-proxy",
                confirmed_proxy_base_url="http://session-proxy:8084",
                env_base_url="http://env-proxy:8085",
            )
        assert result == "http://proxy-from-registry:8080"

    def test_confirmed_proxy_over_env(self) -> None:
        """When no proxy_id, confirmed proxy URL is used over env."""
        result = resolve_writer_base_url(
            proxy_id=None,
            confirmed_proxy_base_url="http://session-proxy:8084",
            env_base_url="http://env-proxy:8085",
        )
        assert result == "http://session-proxy:8084"

    def test_env_fallback(self) -> None:
        """When no proxy_id or confirmed proxy, uses env ANTHROPIC_BASE_URL."""
        result = resolve_writer_base_url(
            proxy_id=None,
            confirmed_proxy_base_url=None,
            env_base_url="http://env-proxy:8085",
        )
        assert result == "http://env-proxy:8085"

    def test_none_when_no_sources(self) -> None:
        """Returns None when all sources are empty (Anthropic direct)."""
        result = resolve_writer_base_url(
            proxy_id=None,
            confirmed_proxy_base_url=None,
            env_base_url=None,
        )
        assert result is None

    def test_proxy_id_lookup_failure_falls_through(self) -> None:
        """When proxy_id lookup fails, falls through to confirmed proxy."""
        with patch(
            "forge.session.memory_writer.resolve_subprocess_routing",
            return_value=_unresolved_result(),
        ):
            result = resolve_writer_base_url(
                proxy_id="nonexistent-proxy",
                confirmed_proxy_base_url="http://session-proxy:8084",
                env_base_url=None,
            )
        assert result == "http://session-proxy:8084"

    def test_proxy_miss_prefers_confirmed_proxy_over_ambient_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ambient ANTHROPIC_BASE_URL must not beat the session's confirmed proxy."""
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://ambient-env-proxy:8080")

        result = resolve_writer_base_url(
            proxy_id="definitely-missing-proxy-for-handoff-test",
            confirmed_proxy_base_url="http://session-proxy:8084",
            env_base_url="http://ambient-env-proxy:8080",
        )

        assert result == "http://session-proxy:8084"

    def test_subprocess_proxy_used_before_confirmed_proxy(self) -> None:
        """Persisted subprocess proxy is tried before falling back to the session proxy."""
        with patch(
            "forge.session.memory_writer.resolve_subprocess_routing",
            return_value=_resolved_result("http://subprocess-proxy:8080"),
        ) as mock_resolver:
            result = resolve_writer_base_url(
                proxy_id=None,
                subprocess_proxy="openrouter-subprocess",
                confirmed_proxy_base_url="http://session-proxy:8084",
                env_base_url=None,
            )

        assert result == "http://subprocess-proxy:8080"
        mock_resolver.assert_called_once_with(
            preferred_proxy="openrouter-subprocess",
            require_route=False,
            use_environment=False,
        )

    def test_config_proxy_takes_priority_over_subprocess_proxy(self) -> None:
        """Handoff-specific proxy remains the highest-priority handoff route."""
        with patch(
            "forge.session.memory_writer.resolve_subprocess_routing",
            return_value=_resolved_result("http://handoff-config-proxy:8080"),
        ) as mock_resolver:
            result = resolve_writer_base_url(
                proxy_id="handoff-config-proxy",
                subprocess_proxy="openrouter-subprocess",
                confirmed_proxy_base_url="http://session-proxy:8084",
            )

        assert result == "http://handoff-config-proxy:8080"
        mock_resolver.assert_called_once_with(
            preferred_proxy="handoff-config-proxy",
            require_route=False,
            use_environment=False,
        )

    def test_subprocess_proxy_miss_falls_back_to_confirmed_proxy(self) -> None:
        """Async handoff remains best-effort if the subprocess proxy is unavailable."""
        with patch(
            "forge.session.memory_writer.resolve_subprocess_routing",
            return_value=_unresolved_result(),
        ):
            result = resolve_writer_base_url(
                proxy_id=None,
                subprocess_proxy="missing-subprocess-proxy",
                confirmed_proxy_base_url="http://session-proxy:8084",
            )

        assert result == "http://session-proxy:8084"

    def test_direct_short_circuits_all_resolution(self) -> None:
        """direct=True should return None regardless of other sources."""
        result = resolve_writer_base_url(
            proxy_id="my-proxy",
            confirmed_proxy_base_url="http://session-proxy:8084",
            env_base_url="http://env-proxy:8085",
            direct=True,
        )
        assert result is None

    def test_delegates_to_shared_resolver(self) -> None:
        """Verifies resolve_subprocess_routing is called with correct params."""
        with patch(
            "forge.session.memory_writer.resolve_subprocess_routing",
            return_value=_resolved_result(),
        ) as mock_resolver:
            resolve_writer_base_url(proxy_id="my-proxy")
        mock_resolver.assert_called_once_with(
            preferred_proxy="my-proxy",
            require_route=False,
            use_environment=False,
        )


# ---------------------------------------------------------------------------
# run_memory_writer
# ---------------------------------------------------------------------------


class TestRunHandoffAgent:
    """Tests for the main agent invocation function."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        """Create a minimal workspace with real git repo."""
        import subprocess as sp

        sp.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        sp.run(
            ["git", "config", "user.email", "test@test.com"],
            capture_output=True,
            check=True,
            cwd=str(tmp_path),
        )
        sp.run(
            ["git", "config", "user.name", "Test"],
            capture_output=True,
            check=True,
            cwd=str(tmp_path),
        )
        # Create transcript
        transcript_rel = ".forge/artifacts/test/transcripts/uuid-123.jsonl"
        transcript_abs = tmp_path / transcript_rel
        entries = [_make_newer_entry(f"req-{i}", "user") for i in range(10)] + [
            _make_newer_entry(f"req-{i}", "assistant") for i in range(10)
        ]
        _write_transcript(transcript_abs, entries)
        # Create a default designated doc so basic tests have something to update
        (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / "state.md").write_text("# State\n")
        return tmp_path

    def _default_docs(self) -> list[DesignatedDoc]:
        return [DesignatedDoc(path="docs/state.md", strategy="project-state")]

    def test_skips_below_min_turns(self, workspace: Path) -> None:
        """Sessions below min_turns threshold are skipped (returns True)."""
        transcript_rel = ".forge/artifacts/test/transcripts/short.jsonl"
        transcript_abs = workspace / transcript_rel
        entries = [
            _make_newer_entry("req-1", "user"),
            _make_newer_entry("req-1", "assistant"),
            _make_newer_entry("req-2", "user"),
            _make_newer_entry("req-2", "assistant"),
        ]
        _write_transcript(transcript_abs, entries)

        config = MemoryWriterConfig(enabled=True, min_turns=5)
        result = run_memory_writer(
            session_name="test",
            forge_root=workspace,
            transcript_snapshot_rel=transcript_rel,
            config=config,
            designated_docs=self._default_docs(),
        )
        assert result is True  # Skip is not a failure
        outcomes = read_upstream_outcomes(session="test", command="memory-writer")
        assert len(outcomes) == 1
        assert outcomes[0].status == "skipped"
        assert outcomes[0].reason_code == "below_min_turns"

    @patch("forge.session.memory_writer.is_claude_available", return_value=False)
    def test_returns_false_when_claude_not_available(self, mock_claude: MagicMock, workspace: Path) -> None:
        """Returns False when claude CLI is not in PATH."""
        config = MemoryWriterConfig(enabled=True, min_turns=1)
        result = run_memory_writer(
            session_name="test",
            forge_root=workspace,
            transcript_snapshot_rel=".forge/artifacts/test/transcripts/uuid-123.jsonl",
            config=config,
            designated_docs=self._default_docs(),
        )
        assert result is False

    def _run_with_mock_claude(
        self,
        workspace: Path,
        mock_run: MagicMock,
        *,
        project_root: Path | None = None,
        **kwargs: object,
    ) -> bool:
        """Helper: run_memory_writer with mocked claude."""
        root = project_root if project_root is not None else workspace
        with patch("forge.session.memory_writer.is_claude_available", return_value=True):
            return run_memory_writer(
                session_name=kwargs.get("session_name", "test"),  # type: ignore[arg-type]
                forge_root=root,
                transcript_snapshot_rel=kwargs.get(
                    "transcript_snapshot_rel",
                    ".forge/artifacts/test/transcripts/uuid-123.jsonl",
                ),  # type: ignore[arg-type]
                config=kwargs.get("config", MemoryWriterConfig(enabled=True, min_turns=1)),  # type: ignore[arg-type]
                base_url=kwargs.get("base_url"),  # type: ignore[arg-type]
                timeout_seconds=kwargs.get("timeout_seconds", 300),  # type: ignore[arg-type]
                designated_docs=kwargs.get("designated_docs", self._default_docs()),  # type: ignore[arg-type]
            )

    def test_invokes_claude_p_with_correct_args(self, workspace: Path) -> None:
        """Verifies run_claude_session is called with correct prompt, cwd, and timeout."""
        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="", returncode=0)

            result = self._run_with_mock_claude(
                workspace,
                mock_run,
                timeout_seconds=120,
            )

            assert result is True
            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            assert "test" in args[0]  # prompt is first positional arg
            assert kwargs["cwd"] == str(workspace)
            assert kwargs["timeout_seconds"] == 120

    def test_failed_subprocess_preserves_zero_latency(self, workspace: Path) -> None:
        """A real 0.0ms duration is telemetry, not absence."""
        cost = MagicMock()
        cost.duration_ms = 0.0
        mock_result = SessionResult(
            stdout="",
            stderr="",
            returncode=1,
            error="failed",
            run_id="run_mw",
            parent_run_id="run_parent",
            root_run_id="run_root",
        )
        with (
            patch("forge.session.memory_writer.is_claude_available", return_value=True),
            patch("forge.session.memory_writer.run_claude_session", return_value=mock_result),
            patch("forge.core.reactive.cost_tracking.track_verb_cost") as mock_cost,
        ):
            mock_cost.return_value.__enter__.return_value = cost
            result = run_memory_writer(
                session_name="test",
                forge_root=workspace,
                transcript_snapshot_rel=".forge/artifacts/test/transcripts/uuid-123.jsonl",
                config=MemoryWriterConfig(enabled=True, min_turns=1),
                designated_docs=self._default_docs(),
            )

        assert result is False
        outcomes = read_upstream_outcomes(session="test", command="memory-writer")
        assert len(outcomes) == 1
        assert outcomes[0].status == "error"
        assert outcomes[0].latency_ms == 0.0

    def test_stamps_provider_trace_identity_env(self, workspace: Path) -> None:
        """Phase 1: the writer tags its spawn with the session name + memory_writer role."""
        from forge.core.reactive.env import FORGE_COMMAND_VAR, FORGE_SESSION_VAR

        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="", returncode=0)

            self._run_with_mock_claude(workspace, mock_run, session_name="my-session")

            _, kwargs = mock_run.call_args
            assert kwargs["extra_env"][FORGE_SESSION_VAR] == "my-session"
            assert kwargs["extra_env"][FORGE_COMMAND_VAR] == "memory_writer"

    def test_sets_base_url_when_provided(self, workspace: Path) -> None:
        """Passes base_url to run_claude_session when provided."""
        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="", returncode=0)

            self._run_with_mock_claude(
                workspace,
                mock_run,
                base_url="http://my-proxy:8084",
            )

            _, kwargs = mock_run.call_args
            assert kwargs["base_url"] == "http://my-proxy:8084"

    def test_no_base_url_when_none(self, workspace: Path) -> None:
        """Does not set base_url when not provided."""
        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="", returncode=0)

            self._run_with_mock_claude(workspace, mock_run, base_url=None)

            _, kwargs = mock_run.call_args
            assert kwargs.get("base_url") is None

    def test_handles_timeout(self, workspace: Path) -> None:
        """Returns False when claude -p times out."""
        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(
                stdout="",
                stderr="",
                returncode=-1,
                timed_out=True,
                error="Timed out after 300s",
            )
            result = self._run_with_mock_claude(workspace, mock_run)
            assert result is False

    def test_handles_nonzero_exit(self, workspace: Path) -> None:
        """Returns False when claude -p exits with non-zero code."""
        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="error", returncode=1)

            result = self._run_with_mock_claude(workspace, mock_run)
            assert result is False

    def test_no_fallback_when_no_designated_docs(self, workspace: Path) -> None:
        """Empty/None designated_docs returns True without calling subprocess."""
        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="", returncode=0)

            result = self._run_with_mock_claude(workspace, mock_run, designated_docs=None)

            assert result is True
            mock_run.assert_not_called()

    def test_no_fallback_when_empty_designated_docs(self, workspace: Path) -> None:
        """Empty list returns True without calling subprocess."""
        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="", returncode=0)

            result = self._run_with_mock_claude(workspace, mock_run, designated_docs=[])

            assert result is True
            mock_run.assert_not_called()

    def test_transcript_path_absolute_in_prompt(self, workspace: Path) -> None:
        """Transcript path in prompt is absolute (not repo-relative)."""
        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="", returncode=0)

            self._run_with_mock_claude(workspace, mock_run)

            args, _ = mock_run.call_args
            prompt = args[0]
            # Transcript path should be absolute (starts with /)
            assert str(workspace) in prompt

    def test_rejects_unsafe_transcript_path(self, workspace: Path) -> None:
        """Transcript path with unsafe characters is rejected."""
        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="", returncode=0)

            result = self._run_with_mock_claude(
                workspace,
                mock_run,
                transcript_snapshot_rel=".forge/artifacts/t.jsonl`\nINJECT",
            )

            assert result is False
            mock_run.assert_not_called()

    def test_rejects_traversal_transcript_path(self, workspace: Path) -> None:
        """Transcript path with ../ traversal is rejected."""
        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="", returncode=0)

            result = self._run_with_mock_claude(
                workspace,
                mock_run,
                transcript_snapshot_rel="../../etc/passwd",
            )

            assert result is False
            mock_run.assert_not_called()

    def test_returns_false_when_transcript_missing(self, workspace: Path) -> None:
        """Returns False when transcript file doesn't exist on disk."""
        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="", returncode=0)

            result = self._run_with_mock_claude(
                workspace,
                mock_run,
                transcript_snapshot_rel=".forge/artifacts/nonexistent.jsonl",
            )

            assert result is False
            mock_run.assert_not_called()

    def test_rejects_unknown_mode(self, workspace: Path) -> None:
        """Unknown config.mode is rejected (not silently treated as review-only)."""
        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="", returncode=0)

            result = self._run_with_mock_claude(
                workspace,
                mock_run,
                config=MemoryWriterConfig(enabled=True, min_turns=1, mode="review_only"),
            )

            assert result is False
            mock_run.assert_not_called()

    def test_persists_review_file_in_augment_mode(self, workspace: Path) -> None:
        """Augment mode writes a review file under artifacts/<session>/handoff/."""
        from forge.session.memory_writer import memory_report_dir

        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(
                stdout="Applied: docs/state.md\n- Added handoff notes\n",
                stderr="",
                returncode=0,
            )
            result = self._run_with_mock_claude(workspace, mock_run, session_name="my-sess")

        assert result is True
        files = list(memory_report_dir(workspace, "my-sess").iterdir())
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "Memory Writer Report -- my-sess" in content
        assert "**Mode**: augment" in content
        assert "Applied: docs/state.md" in content
        assert files[0].name.startswith("review-")
        assert files[0].name.endswith(".md")

    def test_persists_review_file_in_review_only_mode(self, workspace: Path) -> None:
        """Review-only mode persists the would-have-been-applied output."""
        from forge.session.memory_writer import memory_report_dir

        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(
                stdout="Would add: 'New decision recorded' to docs/state.md\n",
                stderr="",
                returncode=0,
            )
            result = self._run_with_mock_claude(
                workspace,
                mock_run,
                session_name="my-sess",
                config=MemoryWriterConfig(enabled=True, min_turns=1, mode="review-only"),
            )

        assert result is True
        files = list(memory_report_dir(workspace, "my-sess").iterdir())
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "**Mode**: review-only" in content
        assert "Would add" in content

    def test_review_file_not_written_on_run_failure(self, workspace: Path) -> None:
        """Failed agent run (non-zero exit) skips the review file."""
        from forge.session.memory_writer import memory_report_dir

        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="boom", returncode=1)
            result = self._run_with_mock_claude(workspace, mock_run, session_name="my-sess")

        assert result is False
        assert not memory_report_dir(workspace, "my-sess").exists()


# ---------------------------------------------------------------------------
# _validate_designated_docs
# ---------------------------------------------------------------------------


class TestValidateDesignatedDocs:
    """Tests for the containment guard + strategy consistency checks."""

    def test_accepts_valid_relative_paths(self, tmp_path: Path) -> None:
        """Valid worktree-relative paths pass through."""
        docs = [
            DesignatedDoc(path="docs/checklist.md"),
            DesignatedDoc(path=".forge/memory/project-state.md"),
        ]
        result = _validate_designated_docs(docs, tmp_path)
        assert len(result) == 2

    def test_rejects_absolute_paths(self, tmp_path: Path) -> None:
        """Absolute paths are rejected."""
        docs = [DesignatedDoc(path="/etc/passwd")]
        result = _validate_designated_docs(docs, tmp_path)
        assert len(result) == 0

    def test_rejects_traversal_paths(self, tmp_path: Path) -> None:
        """Paths with ../ traversal that escape worktree are rejected."""
        docs = [DesignatedDoc(path="../../etc/passwd")]
        result = _validate_designated_docs(docs, tmp_path)
        assert len(result) == 0

    def test_mixed_valid_and_invalid(self, tmp_path: Path) -> None:
        """Only valid paths are retained; invalid paths are filtered out."""
        docs = [
            DesignatedDoc(path="docs/good.md"),
            DesignatedDoc(path="/absolute/bad.md"),
            DesignatedDoc(path="../../escape/bad.md"),
            DesignatedDoc(path=".forge/memory/good.md"),
        ]
        result = _validate_designated_docs(docs, tmp_path)
        assert len(result) == 2
        assert result[0].path == "docs/good.md"
        assert result[1].path == ".forge/memory/good.md"

    def test_nested_relative_path_within_root(self, tmp_path: Path) -> None:
        """Nested path that stays within worktree is accepted."""
        docs = [DesignatedDoc(path="docs/../docs/checklist.md")]
        result = _validate_designated_docs(docs, tmp_path)
        assert len(result) == 1

    def test_rejects_prefix_sibling_directory(self, tmp_path: Path) -> None:
        """Path in a sibling directory whose name shares a prefix is rejected.

        Tests the classic str.startswith() footgun: /repo/root2/file
        starts with /repo/root as a string but is NOT contained within it.
        """
        sibling = tmp_path.parent / (tmp_path.name + "2")
        sibling.mkdir(exist_ok=True)
        docs = [DesignatedDoc(path=f"../{sibling.name}/evil.md")]
        result = _validate_designated_docs(docs, tmp_path)
        assert len(result) == 0

    def test_rejects_path_with_backticks(self, tmp_path: Path) -> None:
        """Paths with backticks are rejected (prompt injection via markdown)."""
        docs = [DesignatedDoc(path="docs/a.md`\nINJECT")]
        result = _validate_designated_docs(docs, tmp_path)
        assert len(result) == 0

    def test_rejects_path_with_newlines(self, tmp_path: Path) -> None:
        """Paths with newlines are rejected (prompt injection)."""
        docs = [DesignatedDoc(path="docs/a.md\n## Ignore above")]
        result = _validate_designated_docs(docs, tmp_path)
        assert len(result) == 0

    def test_rejects_path_with_control_chars(self, tmp_path: Path) -> None:
        """Paths with control characters are rejected."""
        docs = [DesignatedDoc(path="docs/a\x00b.md")]
        result = _validate_designated_docs(docs, tmp_path)
        assert len(result) == 0

    def test_valid_path_with_hyphens_dots_underscores(self, tmp_path: Path) -> None:
        """Normal path characters (hyphens, dots, underscores) are accepted."""
        docs = [DesignatedDoc(path="docs/my-file_v2.0.md")]
        result = _validate_designated_docs(docs, tmp_path)
        assert len(result) == 1

    # Shadow path validation

    def test_validates_shadows_path_traversal(self, tmp_path: Path) -> None:
        """Traversal in shadows paths is rejected."""
        docs = [
            DesignatedDoc(
                path=".forge/memory/shadow.md",
                strategy="generic",
                shadows="../../etc/passwd",
            )
        ]
        result = _validate_designated_docs(docs, tmp_path)
        assert len(result) == 0

    def test_validates_shadows_path_absolute(self, tmp_path: Path) -> None:
        """Absolute shadows paths are rejected."""
        docs = [
            DesignatedDoc(
                path=".forge/memory/shadow.md",
                strategy="generic",
                shadows="/etc/passwd",
            )
        ]
        result = _validate_designated_docs(docs, tmp_path)
        assert len(result) == 0

    def test_validates_shadows_path_unsafe_chars(self, tmp_path: Path) -> None:
        """Unsafe characters in shadows paths are rejected."""
        docs = [
            DesignatedDoc(
                path=".forge/memory/shadow.md",
                strategy="generic",
                shadows="STANDARDS`\nINJECT.md",
            )
        ]
        result = _validate_designated_docs(docs, tmp_path)
        assert len(result) == 0

    def test_valid_shadow_doc(self, tmp_path: Path) -> None:
        """Valid shadow + shadows combination passes."""
        docs = [
            DesignatedDoc(
                path=".forge/memory/shadow_standards.md",
                strategy="generic",
                shadows="docs/developer/coding_standards.md",
            )
        ]
        result = _validate_designated_docs(docs, tmp_path)
        assert len(result) == 1

    # Strategy consistency

    def test_rejects_self_shadowing(self, tmp_path: Path) -> None:
        """path == shadows is rejected (redundant self-reference)."""
        docs = [
            DesignatedDoc(
                path="docs/standards.md",
                strategy="generic",
                shadows="docs/standards.md",
            )
        ]
        result = _validate_designated_docs(docs, tmp_path)
        assert len(result) == 0

    def test_rejects_empty_shadows_unconditionally(self, tmp_path: Path) -> None:
        """Empty shadows string is rejected regardless of passport existence."""
        docs = [DesignatedDoc(path="doc.md", strategy="generic", shadows="")]
        result = _validate_designated_docs(docs, tmp_path)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Permission-denied detection (QA-038)
# ---------------------------------------------------------------------------


class TestPermissionDeniedDetection:
    """Regression for QA-040: handoff should detect permission-denied stdout."""

    @pytest.mark.parametrize(
        "stdout",
        [
            "I need write permission to modify the file.",
            "I don't have access to edit files in this environment.",
            "I require write permissions to update the document.",
            "I'm not allowed to write or modify files directly.",
            "I cannot write files without the appropriate permissions.",
        ],
    )
    def test_detects_permission_denied(self, stdout):
        assert _stdout_indicates_permission_denied(stdout) is True

    @pytest.mark.parametrize(
        "stdout",
        [
            "Updated docs/state.md with session takeaways.",
            "I wrote the debugging notes to the designated doc.",
            "",
            "No changes needed for this session.",
        ],
    )
    def test_passes_normal_output(self, stdout):
        assert _stdout_indicates_permission_denied(stdout) is False

    def _make_workspace(self, tmp_path):
        import subprocess as sp

        sp.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        sp.run(["git", "config", "user.email", "t@t"], capture_output=True, check=True, cwd=str(tmp_path))
        sp.run(["git", "config", "user.name", "T"], capture_output=True, check=True, cwd=str(tmp_path))
        transcript_rel = ".forge/artifacts/test/transcripts/t.jsonl"
        entries = [_make_newer_entry(f"r-{i}", r) for i in range(5) for r in ("user", "assistant")]
        _write_transcript(tmp_path / transcript_rel, entries)
        (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / "state.md").write_text("# State\n")
        return transcript_rel

    def test_run_handoff_returns_false_on_permission_denied(self, tmp_path):
        """run_memory_writer returns False when Claude can't write in augment mode."""
        transcript_rel = self._make_workspace(tmp_path)
        mock_result = SessionResult(
            stdout="I need write permission to modify docs/state.md.",
            stderr="",
            returncode=0,
        )
        config = MemoryWriterConfig(enabled=True, min_turns=1, mode="augment")
        with (
            patch("forge.session.memory_writer.is_claude_available", return_value=True),
            patch("forge.session.memory_writer.run_claude_session", return_value=mock_result),
        ):
            result = run_memory_writer(
                session_name="test",
                forge_root=tmp_path,
                transcript_snapshot_rel=transcript_rel,
                config=config,
                designated_docs=[DesignatedDoc(path="docs/state.md", strategy="project-state")],
            )
        assert result is False

    def test_review_only_mode_ignores_permission_patterns(self, tmp_path):
        """review-only mode should not false-fail on 'cannot modify files' responses."""
        transcript_rel = self._make_workspace(tmp_path)
        mock_result = SessionResult(
            stdout="I cannot modify files in this mode. Here are the changes I would make...",
            stderr="",
            returncode=0,
        )
        config = MemoryWriterConfig(enabled=True, min_turns=1, mode="review-only")
        with (
            patch("forge.session.memory_writer.is_claude_available", return_value=True),
            patch("forge.session.memory_writer.run_claude_session", return_value=mock_result),
        ):
            result = run_memory_writer(
                session_name="test",
                forge_root=tmp_path,
                transcript_snapshot_rel=transcript_rel,
                config=config,
                designated_docs=[DesignatedDoc(path="docs/state.md", strategy="project-state")],
            )
        assert result is True


# ---------------------------------------------------------------------------
# run_memory_writer with designated_docs
# ---------------------------------------------------------------------------


class TestRunHandoffAgentMultiDoc:
    """Tests for run_memory_writer with designated_docs."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        """Create a minimal workspace with transcript."""
        import subprocess as sp

        sp.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        sp.run(
            ["git", "config", "user.email", "test@test.com"],
            capture_output=True,
            check=True,
            cwd=str(tmp_path),
        )
        sp.run(
            ["git", "config", "user.name", "Test"],
            capture_output=True,
            check=True,
            cwd=str(tmp_path),
        )
        transcript_rel = ".forge/artifacts/test/transcripts/uuid-123.jsonl"
        transcript_abs = tmp_path / transcript_rel
        entries = [_make_newer_entry(f"req-{i}", "user") for i in range(10)] + [
            _make_newer_entry(f"req-{i}", "assistant") for i in range(10)
        ]
        _write_transcript(transcript_abs, entries)
        return tmp_path

    def _run_with_mock_claude(
        self,
        workspace: Path,
        mock_run: MagicMock,
        *,
        project_root: Path | None = None,
        **kwargs: object,
    ) -> bool:
        """Helper: run_memory_writer with mocked claude."""
        root = project_root if project_root is not None else workspace
        with patch("forge.session.memory_writer.is_claude_available", return_value=True):
            return run_memory_writer(
                session_name=kwargs.get("session_name", "test"),  # type: ignore[arg-type]
                forge_root=root,
                transcript_snapshot_rel=kwargs.get(
                    "transcript_snapshot_rel",
                    ".forge/artifacts/test/transcripts/uuid-123.jsonl",
                ),  # type: ignore[arg-type]
                config=kwargs.get("config", MemoryWriterConfig(enabled=True, min_turns=1)),  # type: ignore[arg-type]
                base_url=kwargs.get("base_url"),  # type: ignore[arg-type]
                timeout_seconds=kwargs.get("timeout_seconds", 300),  # type: ignore[arg-type]
                designated_docs=kwargs.get("designated_docs"),  # type: ignore[arg-type]
            )

    def test_uses_multi_doc_prompt_when_designated_docs_provided(self, workspace: Path) -> None:
        """When designated_docs is non-empty, uses build_multi_doc_prompt."""
        (workspace / "docs").mkdir(parents=True, exist_ok=True)
        (workspace / "docs" / "checklist.md").write_text("# Checklist\n")
        (workspace / "docs" / "changelog.md").write_text("# Change Log\n")
        docs = [
            DesignatedDoc(path="docs/checklist.md", strategy="checklist"),
            DesignatedDoc(path="docs/changelog.md", strategy="changelog"),
        ]
        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="", returncode=0)
            self._run_with_mock_claude(workspace, mock_run, designated_docs=docs)

            args, _ = mock_run.call_args
            prompt = args[0]
            assert "docs/checklist.md" in prompt
            assert "docs/changelog.md" in prompt
            assert "Mark completed tasks" in prompt

    def test_skips_missing_docs(self, workspace: Path) -> None:
        """Docs whose files don't exist on disk are filtered out."""
        # Only create one of the two files
        (workspace / "docs").mkdir(parents=True, exist_ok=True)
        (workspace / "docs" / "checklist.md").write_text("# Checklist\n")
        docs = [
            DesignatedDoc(path="docs/checklist.md", strategy="checklist"),
            DesignatedDoc(path="docs/missing_checklist.md", strategy="checklist"),
        ]
        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="", returncode=0)
            self._run_with_mock_claude(workspace, mock_run, designated_docs=docs)

            args, _ = mock_run.call_args
            prompt = args[0]
            assert "docs/checklist.md" in prompt
            assert "docs/missing_checklist.md" not in prompt

    def test_no_file_creation_for_project_state(self, workspace: Path) -> None:
        """project-state doc that doesn't exist is skipped (no mkdir, no creation)."""
        docs = [DesignatedDoc(path=".forge/memory/project-state.md", strategy="project-state")]
        memory_dir = workspace / ".forge" / "memory"
        assert not memory_dir.exists()

        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="", returncode=0)
            result = self._run_with_mock_claude(workspace, mock_run, designated_docs=docs)

            # Returns True (skip) and does NOT call subprocess (no docs ready)
            assert result is True
            mock_run.assert_not_called()
            # No directory created
            assert not memory_dir.exists()

    def test_containment_guard_rejects_traversal(self, workspace: Path) -> None:
        """Traversal paths in designated_docs are rejected; returns True (skip)."""
        docs = [DesignatedDoc(path="../../etc/passwd")]
        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="", returncode=0)
            result = self._run_with_mock_claude(workspace, mock_run, designated_docs=docs)

            assert result is True
            mock_run.assert_not_called()

    def test_forge_root_cwd_used_for_subprocess(self, workspace: Path) -> None:
        """cwd in run_claude_session uses forge_root."""
        (workspace / "docs").mkdir(parents=True, exist_ok=True)
        (workspace / "docs" / "checklist.md").write_text("# Checklist\n")

        docs = [DesignatedDoc(path="docs/checklist.md", strategy="checklist")]
        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="", returncode=0)
            self._run_with_mock_claude(workspace, mock_run, designated_docs=docs)

            _, call_kwargs = mock_run.call_args
            assert call_kwargs["cwd"] == str(workspace)

    def test_doc_existence_checked_against_forge_root(self, workspace: Path) -> None:
        """File existence check uses forge_root — doc missing under forge_root is skipped."""
        # Remove the default checklist file created by workspace fixture
        checklist = workspace / "docs" / "checklist.md"
        if checklist.exists():
            checklist.unlink()

        docs = [DesignatedDoc(path="docs/checklist.md", strategy="checklist")]
        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="", returncode=0)
            result = self._run_with_mock_claude(workspace, mock_run, designated_docs=docs)

            # Doc doesn't exist under forge_root → skipped → no subprocess
            assert result is True
            mock_run.assert_not_called()

    def test_skips_shadow_doc_when_official_missing(self, workspace: Path) -> None:
        """Shadow doc is skipped when the official doc (shadows target) doesn't exist."""
        # Create the shadow doc but NOT the official doc
        (workspace / ".forge" / "memory").mkdir(parents=True, exist_ok=True)
        (workspace / ".forge" / "memory" / "shadow.md").write_text("# Shadow\n")
        # STANDARDS.md does NOT exist

        docs = [
            DesignatedDoc(
                path=".forge/memory/shadow.md",
                strategy="generic",
                shadows="STANDARDS.md",
            )
        ]
        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="", returncode=0)
            result = self._run_with_mock_claude(workspace, mock_run, designated_docs=docs)

            # Official doc missing → shadow skipped → no subprocess
            assert result is True
            mock_run.assert_not_called()

    def test_shadow_doc_included_when_both_exist(self, workspace: Path) -> None:
        """Shadow doc is included when both shadow and official docs exist."""
        # Create both the shadow doc and the official doc
        (workspace / ".forge" / "memory").mkdir(parents=True, exist_ok=True)
        (workspace / ".forge" / "memory" / "shadow.md").write_text("# Shadow\n")
        (workspace / "STANDARDS.md").write_text("# Standards\n")

        docs = [
            DesignatedDoc(
                path=".forge/memory/shadow.md",
                strategy="generic",
                shadows="STANDARDS.md",
            )
        ]
        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="", stderr="", returncode=0)
            self._run_with_mock_claude(workspace, mock_run, designated_docs=docs)

            args, _ = mock_run.call_args
            prompt = args[0]
            assert "shadow.md" in prompt
            assert "STANDARDS.md" in prompt
            assert "proposes changes to" in prompt


# ---------------------------------------------------------------------------
# Passport ownership-split integration tests
# ---------------------------------------------------------------------------


def _write_passport_to_doc(path: Path, **update_kwargs: object) -> None:
    """Write a passport with given update fields to a markdown file."""
    passport = Passport(
        version=1,
        intent="Test doc",
        update=PassportUpdate(**update_kwargs),  # type: ignore[arg-type]
    )
    write_passport(path, passport)


class TestPassportOwnershipSplit:
    """Prove that the manifest is just participation state and passport changes
    take effect at stop time without re-running ``forge memory track``."""

    def test_passport_strategy_overrides_manifest(self, tmp_path: Path) -> None:
        """Passport strategy wins over DesignatedDoc.strategy."""
        doc_path = tmp_path / "docs" / "changelog.md"
        doc_path.parent.mkdir(parents=True)
        doc_path.write_text("# Changelog\n")
        _write_passport_to_doc(doc_path, strategy="changelog")

        doc = DesignatedDoc(path="docs/changelog.md", strategy="generic")
        passport = read_passport(tmp_path / resolve_passport_source(doc))
        spec = resolve_doc_spec(doc, passport)

        prompt = build_multi_doc_prompt(
            session_name="test",
            transcript_path="/t.jsonl",
            docs=[spec],
        )
        assert "accomplishments" in prompt
        assert "NEW information" not in prompt

    def test_edited_passport_changes_strategy(self, tmp_path: Path) -> None:
        """Editing a passport's strategy changes the handoff prompt without re-track."""
        doc_path = tmp_path / "docs" / "notes.md"
        doc_path.parent.mkdir(parents=True)
        doc_path.write_text("# Notes\n")
        _write_passport_to_doc(doc_path, strategy="changelog")

        doc = DesignatedDoc(path="docs/notes.md", strategy="generic")

        # First read: changelog strategy
        passport = read_passport(tmp_path / resolve_passport_source(doc))
        spec = resolve_doc_spec(doc, passport)
        prompt1 = build_multi_doc_prompt(session_name="test", transcript_path="/t.jsonl", docs=[spec])
        assert "accomplishments" in prompt1

        # Edit passport to checklist
        _write_passport_to_doc(doc_path, strategy="checklist")

        # Second read: checklist strategy (no re-track)
        passport2 = read_passport(tmp_path / resolve_passport_source(doc))
        spec2 = resolve_doc_spec(doc, passport2)
        prompt2 = build_multi_doc_prompt(session_name="test", transcript_path="/t.jsonl", docs=[spec2])
        assert "Mark completed tasks" in prompt2
        assert "accomplishments" not in prompt2

    def test_edited_passport_shadow_path_changes_write_target(self, tmp_path: Path) -> None:
        """Editing shadow_path in passport changes the effective write target."""
        official = tmp_path / "docs" / "impl_notes.md"
        official.parent.mkdir(parents=True)
        official.write_text("# Notes\n")

        old_shadow = tmp_path / ".forge" / "memory" / "old_shadow.md"
        old_shadow.parent.mkdir(parents=True)
        old_shadow.write_text("")

        new_shadow = tmp_path / ".forge" / "memory" / "new_shadow.md"
        new_shadow.write_text("")

        _write_passport_to_doc(
            official,
            strategy="generic",
            mode="shadow-only",
            shadow_path=".forge/memory/old_shadow.md",
        )

        doc = DesignatedDoc(
            path=".forge/memory/old_shadow.md",
            strategy="generic",
            shadows="docs/impl_notes.md",
        )
        passport = read_passport(tmp_path / resolve_passport_source(doc))
        spec = resolve_doc_spec(doc, passport)
        assert spec.write_path == ".forge/memory/old_shadow.md"

        # Edit passport to new shadow path
        _write_passport_to_doc(
            official,
            strategy="generic",
            mode="shadow-only",
            shadow_path=".forge/memory/new_shadow.md",
        )
        passport2 = read_passport(tmp_path / resolve_passport_source(doc))
        spec2 = resolve_doc_spec(doc, passport2)
        assert spec2.write_path == ".forge/memory/new_shadow.md"

    def test_passport_context_in_prompt(self, tmp_path: Path) -> None:
        """Full passport contract (intent, captures, excludes, approval) in prompt."""
        doc_path = tmp_path / "docs" / "notes.md"
        doc_path.parent.mkdir(parents=True)
        doc_path.write_text("# Notes\n")

        passport = Passport(
            version=1,
            intent="Durable implementation memory",
            captures=["stable decisions", "invariants"],
            excludes=["raw summaries"],
            update=PassportUpdate(
                strategy="generic",
                instruction="Be concise and cite sources",
                approval="human-promoted",
                compact_when="over 200 lines",
            ),
        )
        write_passport(doc_path, passport)

        doc = DesignatedDoc(path="docs/notes.md")
        p = read_passport(tmp_path / resolve_passport_source(doc))
        spec = resolve_doc_spec(doc, p)
        prompt = build_multi_doc_prompt(session_name="test", transcript_path="/t.jsonl", docs=[spec])
        assert "Durable implementation memory" in prompt
        assert "stable decisions" in prompt
        assert "raw summaries" in prompt
        assert "human-promoted" in prompt
        assert "Be concise and cite sources" in prompt
        assert "over 200 lines" in prompt


class TestShadowFilePassportConflict:
    """Official doc passport is authoritative; shadow file passport is ignored."""

    def test_official_doc_passport_wins(self, tmp_path: Path) -> None:
        official = tmp_path / "docs" / "impl_notes.md"
        official.parent.mkdir(parents=True)
        official.write_text("# Notes\n")
        _write_passport_to_doc(official, strategy="changelog")

        shadow = tmp_path / ".forge" / "memory" / "shadow.md"
        shadow.parent.mkdir(parents=True)
        shadow.write_text("# Shadow\n")
        _write_passport_to_doc(shadow, strategy="checklist")

        doc = DesignatedDoc(
            path=".forge/memory/shadow.md",
            strategy="generic",
            shadows="docs/impl_notes.md",
        )
        source = resolve_passport_source(doc)
        assert source == "docs/impl_notes.md"

        passport = read_passport(tmp_path / source)
        spec = resolve_doc_spec(doc, passport)
        assert "accomplishments" in spec.strategy_instruction


class TestWriterFiltering:
    """Writer authorization in run_memory_writer()."""

    def _make_workspace(self, tmp_path: Path) -> Path:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / ".forge" / "artifacts" / "test-session" / "handoff").mkdir(parents=True)
        transcript = workspace / ".forge" / "artifacts" / "test-session" / "transcript.jsonl"
        transcript.write_text(
            "\n".join(
                json.dumps(
                    {
                        "requestId": f"req-{i}",
                        "message": {"role": r, "content": [{"text": "x"}]},
                    }
                )
                for i, r in enumerate(["user", "assistant"] * 6)  # 6 turns, above min_turns
            )
        )
        return workspace

    def test_unauthorized_session_skipped(self, tmp_path: Path) -> None:
        workspace = self._make_workspace(tmp_path)
        doc_path = workspace / "docs" / "changelog.md"
        doc_path.parent.mkdir(parents=True)
        doc_path.write_text("# Log\n")
        _write_passport_to_doc(doc_path, strategy="changelog", writers="planner")

        config = MemoryWriterConfig(enabled=True, mode="augment", min_turns=1)
        docs = [DesignatedDoc(path="docs/changelog.md", strategy="changelog")]

        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="done", stderr="", returncode=0)
            run_memory_writer(
                session_name="executor",
                forge_root=workspace,
                transcript_snapshot_rel=".forge/artifacts/test-session/transcript.jsonl",
                config=config,
                designated_docs=docs,
            )
            mock_run.assert_not_called()

    def test_authorized_session_proceeds(self, tmp_path: Path) -> None:
        workspace = self._make_workspace(tmp_path)
        doc_path = workspace / "docs" / "changelog.md"
        doc_path.parent.mkdir(parents=True)
        doc_path.write_text("# Log\n")
        _write_passport_to_doc(doc_path, strategy="changelog", writers="planner")

        config = MemoryWriterConfig(enabled=True, mode="augment", min_turns=1)
        docs = [DesignatedDoc(path="docs/changelog.md", strategy="changelog")]

        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="done", stderr="", returncode=0)
            with patch("forge.session.memory_writer.is_claude_available", return_value=True):
                run_memory_writer(
                    session_name="planner",
                    forge_root=workspace,
                    transcript_snapshot_rel=".forge/artifacts/test-session/transcript.jsonl",
                    config=config,
                    designated_docs=docs,
                )
            mock_run.assert_called_once()


class TestMalformedPassportSkipped:
    """Malformed passport skips the doc, doesn't abort the whole handoff."""

    def test_bad_passport_skipped_good_doc_proceeds(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / ".forge" / "artifacts" / "sess" / "handoff").mkdir(parents=True)
        transcript = workspace / ".forge" / "artifacts" / "sess" / "transcript.jsonl"
        transcript.write_text(
            "\n".join(
                json.dumps(
                    {
                        "requestId": f"req-{i}",
                        "message": {"role": r, "content": [{"text": "x"}]},
                    }
                )
                for i, r in enumerate(["user", "assistant"] * 6)
            )
        )

        # Bad passport doc
        bad_doc = workspace / "docs" / "bad.md"
        bad_doc.parent.mkdir(parents=True)
        bad_doc.write_text("---\nforge_memory:\n  version: 99\n  intent: T\n---\n# Bad\n")

        # Good doc (no passport)
        good_doc = workspace / "docs" / "good.md"
        good_doc.write_text("# Good doc\n")

        config = MemoryWriterConfig(enabled=True, mode="augment", min_turns=1)
        docs = [
            DesignatedDoc(path="docs/bad.md", strategy="generic"),
            DesignatedDoc(path="docs/good.md", strategy="generic"),
        ]

        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="done", stderr="", returncode=0)
            with patch("forge.session.memory_writer.is_claude_available", return_value=True):
                run_memory_writer(
                    session_name="test-session",
                    forge_root=workspace,
                    transcript_snapshot_rel=".forge/artifacts/sess/transcript.jsonl",
                    config=config,
                    designated_docs=docs,
                )
            mock_run.assert_called_once()
            prompt = mock_run.call_args[0][0]
            assert "good.md" in prompt
            assert "bad.md" not in prompt


class TestPassportLessDocsWork:
    """Docs without passport frontmatter work identically to pre-passport behavior."""

    def test_no_passport_uses_designated_doc_strategy(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / ".forge" / "artifacts" / "sess" / "handoff").mkdir(parents=True)
        transcript = workspace / ".forge" / "artifacts" / "sess" / "transcript.jsonl"
        transcript.write_text(
            "\n".join(
                json.dumps(
                    {
                        "requestId": f"req-{i}",
                        "message": {"role": r, "content": [{"text": "x"}]},
                    }
                )
                for i, r in enumerate(["user", "assistant"] * 6)
            )
        )

        doc = workspace / "docs" / "changelog.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("# Changelog\nNo passport here.\n")

        config = MemoryWriterConfig(enabled=True, mode="augment", min_turns=1)
        docs = [DesignatedDoc(path="docs/changelog.md", strategy="changelog")]

        with patch("forge.session.memory_writer.run_claude_session") as mock_run:
            mock_run.return_value = SessionResult(stdout="done", stderr="", returncode=0)
            with patch("forge.session.memory_writer.is_claude_available", return_value=True):
                run_memory_writer(
                    session_name="test-session",
                    forge_root=workspace,
                    transcript_snapshot_rel=".forge/artifacts/sess/transcript.jsonl",
                    config=config,
                    designated_docs=docs,
                )
            mock_run.assert_called_once()
            prompt = mock_run.call_args[0][0]
            assert "accomplishments" in prompt
            assert "changelog.md" in prompt


# ---------------------------------------------------------------------------
# _dedupe_specs
# ---------------------------------------------------------------------------


class TestDedupeSpecs:
    """A doc that enters the run twice and resolves to the same write path must
    collapse to one spec (no duplicate prompt sections / double-write)."""

    def _shadow_only_passport(self) -> Passport:
        return Passport(
            version=1,
            intent="x",
            update=PassportUpdate(
                strategy="generic",
                mode="shadow-only",
                writers="all-sessions",
                inherit_on_fork=True,
                shadow_path=".forge/memory/sug_x.md",
            ),
        )

    def test_distinct_targets_kept(self) -> None:
        a = resolve_doc_spec(DesignatedDoc(path="docs/a.md", strategy="generic"), None)
        b = resolve_doc_spec(DesignatedDoc(path="docs/b.md", strategy="generic"), None)
        assert len(_dedupe_specs([a, b])) == 2


# ---------------------------------------------------------------------------
# Per-caller reasoning effort
# ---------------------------------------------------------------------------


class TestMemoryWriterEffort:
    """config.effort is forwarded to run_claude_session as reasoning_effort."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        """Workspace with a real git repo, transcript, and a designated doc."""
        import subprocess as sp

        sp.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        sp.run(
            ["git", "config", "user.email", "test@test.com"],
            capture_output=True,
            check=True,
            cwd=str(tmp_path),
        )
        sp.run(
            ["git", "config", "user.name", "Test"],
            capture_output=True,
            check=True,
            cwd=str(tmp_path),
        )
        transcript_rel = ".forge/artifacts/test/transcripts/uuid-123.jsonl"
        entries = [_make_newer_entry(f"req-{i}", "user") for i in range(10)] + [
            _make_newer_entry(f"req-{i}", "assistant") for i in range(10)
        ]
        _write_transcript(tmp_path / transcript_rel, entries)
        (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / "state.md").write_text("# State\n")
        return tmp_path

    def test_effort_forwarded_to_run_claude_session(self, workspace: Path) -> None:
        """A config built with effort='high' passes reasoning_effort='high'."""
        config = MemoryWriterConfig(enabled=True, min_turns=1, effort="high")
        with (
            patch("forge.session.memory_writer.is_claude_available", return_value=True),
            patch("forge.session.memory_writer.run_claude_session") as mock_run,
        ):
            mock_run.return_value = SessionResult(stdout="", stderr="", returncode=0)
            result = run_memory_writer(
                session_name="test",
                forge_root=workspace,
                transcript_snapshot_rel=".forge/artifacts/test/transcripts/uuid-123.jsonl",
                config=config,
                designated_docs=[DesignatedDoc(path="docs/state.md", strategy="project-state")],
            )

        assert result is True
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["reasoning_effort"] == "high"
