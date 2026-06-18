"""Tests for forge.session.transfer module."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from forge.core.transcript import parse_jsonl_transcript, truncate
from forge.session.models import SessionState
from forge.session.transfer import (
    AI_CURATION_MODEL,
    AI_CURATION_PROVIDER,
    MAX_TRANSCRIPT_CHARS,
    ResumeStrategy,
    _build_frontmatter,
    _citation_is_grounded,
    _format_transcript_for_llm,
    _generate_ai_curated_context,
    _generate_minimal_context,
    _generate_structured_context,
    _resolve_plan_content,
    _validate_decision_citations,
    assemble_transfer_context,
    estimate_transcript_tokens,
    parse_transfer_frontmatter,
    resolve_lineage,
)

# -----------------------------------------------------------------------------
# Test fixtures
# -----------------------------------------------------------------------------


def _fake_completion(text: str, *, usage: dict[str, int] | None = None) -> Any:
    """Stand-in for the ``CompletionResponse`` returned by ``SyncAdapter.complete``.

    ``_call_llm_for_curation`` reads ``.text`` (parsed for JSON) and ``.usage`` (for ledger
    attribution); a bare ``MagicMock`` would return non-str/non-dict for those, so build an
    explicit object.
    """
    return SimpleNamespace(
        text=text,
        usage=usage if usage is not None else {"prompt_tokens": 120, "completion_tokens": 60},
    )


@pytest.fixture
def sample_transcript(tmp_path: Path) -> Path:
    """Create a sample transcript JSONL file."""
    transcript = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps(
            {
                "requestId": "r1",
                "timestamp": "2025-01-15T10:00:00Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "Hello, please help me."}],
                },
            }
        ),
        json.dumps(
            {
                "requestId": "r1",
                "timestamp": "2025-01-15T10:00:01Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I'll help you with that."},
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "Read",
                            "input": {"file_path": "/path/to/file.py"},
                        },
                    ],
                },
            }
        ),
        json.dumps(
            {
                "requestId": "r1",
                "timestamp": "2025-01-15T10:00:02Z",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "t1",
                            "content": "file contents here",
                        },
                    ],
                },
            }
        ),
        json.dumps(
            {
                "requestId": "r1",
                "timestamp": "2025-01-15T10:00:03Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I see the file. Let me update it."},
                    ],
                },
            }
        ),
    ]
    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return transcript


@pytest.fixture
def empty_transcript(tmp_path: Path) -> Path:
    """Create an empty transcript file."""
    transcript = tmp_path / "empty.jsonl"
    transcript.write_text("", encoding="utf-8")
    return transcript


@pytest.fixture
def malformed_transcript(tmp_path: Path) -> Path:
    """Create a transcript with malformed entries."""
    transcript = tmp_path / "malformed.jsonl"
    lines = [
        "not valid json",
        json.dumps({"requestId": "r1", "timestamp": "2025-01-15T10:00:00Z"}),  # Missing message
        json.dumps(
            {
                "requestId": "r2",
                "timestamp": "2025-01-15T10:00:01Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Valid entry"}],
                },
            }
        ),
    ]
    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return transcript


# -----------------------------------------------------------------------------
# Test truncate
# -----------------------------------------------------------------------------


class TestTruncate:
    """Tests for truncate helper (forge.core.transcript)."""

    def test_short_string_unchanged(self) -> None:
        """Short strings should not be truncated."""
        assert truncate("hello", 10) == "hello"

    def test_exact_length_unchanged(self) -> None:
        """String exactly at limit should not be truncated."""
        assert truncate("hello", 5) == "hello"

    def test_long_string_truncated(self) -> None:
        """Long strings should be truncated with ellipsis."""
        result = truncate("hello world", 5)
        assert result == "hello..."
        assert len(result) == 8  # 5 chars + "..."

    def test_empty_string(self) -> None:
        """Empty string should remain empty."""
        assert truncate("", 10) == ""

    def test_unicode_preserved(self) -> None:
        """Unicode characters should be preserved (string slice, not bytes)."""
        # 5 chars including unicode
        result = truncate("héllo wörld", 5)
        assert result == "héllo..."


# -----------------------------------------------------------------------------
# Test estimate_transcript_tokens
# -----------------------------------------------------------------------------


class TestEstimateTranscriptTokens:
    """Tests for estimate_transcript_tokens."""

    def test_estimates_from_file_size(self, sample_transcript: Path) -> None:
        """Should estimate tokens as file_size / 4."""
        file_size = sample_transcript.stat().st_size
        expected = file_size // 4
        assert estimate_transcript_tokens(sample_transcript) == expected

    def test_estimate_multiplier(self, sample_transcript: Path) -> None:
        """Model-specific tokenizer multipliers adjust the heuristic estimate."""
        file_size = sample_transcript.stat().st_size
        expected = int((file_size // 4) * 1.35)
        assert estimate_transcript_tokens(sample_transcript, multiplier=1.35) == expected

    def test_empty_file(self, empty_transcript: Path) -> None:
        """Empty file should return 0 tokens."""
        assert estimate_transcript_tokens(empty_transcript) == 0


# -----------------------------------------------------------------------------
# Test parse_jsonl_transcript
# -----------------------------------------------------------------------------


class TestParseTranscript:
    """Tests for parse_jsonl_transcript (forge.core.transcript)."""

    def test_parses_valid_entries(self, sample_transcript: Path) -> None:
        """Should parse all valid entries from transcript."""
        entries = parse_jsonl_transcript(sample_transcript)
        assert len(entries) == 4

    def test_skips_malformed_json(self, malformed_transcript: Path) -> None:
        """Should skip malformed JSON lines without failing."""
        entries = parse_jsonl_transcript(malformed_transcript)
        # Only the valid entry with message should be parsed
        assert len(entries) == 1

    def test_sorts_by_timestamp(self, sample_transcript: Path) -> None:
        """Entries should be sorted by timestamp."""
        entries = parse_jsonl_transcript(sample_transcript)
        timestamps = [e.get("timestamp", "") for e in entries]
        assert timestamps == sorted(timestamps)

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """Missing file should return empty list."""
        nonexistent = tmp_path / "nonexistent.jsonl"
        entries = parse_jsonl_transcript(nonexistent)
        assert entries == []


# -----------------------------------------------------------------------------
# Test resolve_lineage
# -----------------------------------------------------------------------------


def _mock_session(parent: str | None) -> Any:
    """Create a mock object with parent_session attribute for testing resolve_lineage.

    Uses a simple namespace object since resolve_lineage only accesses .parent_session.
    Cast is used at call site to satisfy type checker.
    """
    return type("MockSession", (), {"parent_session": parent})()


class TestResolveLineage:
    """Tests for resolve_lineage."""

    def test_single_parent(self) -> None:
        """depth=1 should return just the parent."""

        def mock_get_session(name: str) -> SessionState | None:
            return None

        lineage = resolve_lineage("parent", depth=1, get_session=mock_get_session)
        assert lineage == ["parent"]

    def test_multiple_ancestors(self) -> None:
        """Should traverse ancestry chain up to depth."""
        # Mock session states with parent chain
        sessions: dict[str, Any] = {
            "child": _mock_session("parent"),
            "parent": _mock_session("grandparent"),
            "grandparent": _mock_session(None),
        }

        # Cast needed: mock objects have .parent_session but aren't SessionState
        get_session = cast("type[SessionState | None]", lambda name: sessions.get(name))

        lineage = resolve_lineage("child", depth=3, get_session=get_session)
        assert lineage == ["child", "parent", "grandparent"]

    def test_stops_at_missing_parent(self) -> None:
        """Should stop when parent's session doesn't exist."""
        # The lineage includes 'child', then 'nonexistent' is added because
        # child.parent_session points to it, but we can't go further because
        # nonexistent returns None from get_session

        def _get(name: str) -> Any:
            if name == "child":
                return _mock_session("nonexistent")
            return None

        get_session = cast("type[SessionState | None]", _get)

        lineage = resolve_lineage("child", depth=5, get_session=get_session)
        # Includes child, then nonexistent (we still add it to lineage)
        # but can't traverse further since get_session(nonexistent) is None
        assert lineage == ["child", "nonexistent"]

    def test_respects_depth_limit(self) -> None:
        """Should stop at depth limit even if more ancestors exist."""
        sessions: dict[str, Any] = {
            "a": _mock_session("b"),
            "b": _mock_session("c"),
            "c": _mock_session("d"),
            "d": _mock_session(None),
        }

        get_session = cast("type[SessionState | None]", lambda name: sessions.get(name))

        lineage = resolve_lineage("a", depth=2, get_session=get_session)
        assert lineage == ["a", "b"]


# -----------------------------------------------------------------------------
# Test _generate_minimal_context
# -----------------------------------------------------------------------------


class TestGenerateMinimalContext:
    """Tests for _generate_minimal_context."""

    def test_includes_parent_name(self) -> None:
        """Should include parent session name."""
        content = _generate_minimal_context(
            parent_name="test-parent",
            lineage=["test-parent"],
            artifacts_path=None,
            proxy_template=None,
        )
        assert "test-parent" in content
        assert "# Session Context: test-parent" in content

    def test_includes_lineage(self) -> None:
        """Should include lineage chain."""
        content = _generate_minimal_context(
            parent_name="child",
            lineage=["child", "parent", "grandparent"],
            artifacts_path=None,
            proxy_template=None,
        )
        assert "child ← parent ← grandparent" in content

    def test_includes_artifacts_path(self) -> None:
        """Should include artifacts path when provided."""
        content = _generate_minimal_context(
            parent_name="test",
            lineage=["test"],
            artifacts_path=".forge/artifacts/test/transcripts/abc.jsonl",
            proxy_template=None,
        )
        assert ".forge/artifacts/test/transcripts/abc.jsonl" in content

    def test_includes_proxy_template(self) -> None:
        """Should include proxy template when provided."""
        content = _generate_minimal_context(
            parent_name="test",
            lineage=["test"],
            artifacts_path=None,
            proxy_template="litellm-gemini",
        )
        assert "litellm-gemini" in content


# -----------------------------------------------------------------------------
# Test _generate_structured_context
# -----------------------------------------------------------------------------


class TestGenerateStructuredContext:
    """Tests for _generate_structured_context."""

    def test_includes_conversation_summary(self, sample_transcript: Path) -> None:
        """Should include conversation summary section."""
        content, warnings = _generate_structured_context(
            parent_name="test",
            lineage=["test"],
            transcript_path=sample_transcript,
            artifacts_path=None,
            proxy_template=None,
            latest_plan_path=None,
        )
        assert "## Conversation Summary" in content
        assert warnings == []

    def test_truncates_messages(self, tmp_path: Path) -> None:
        """Should truncate long messages."""
        long_message = "x" * 1000
        transcript = tmp_path / "long.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "requestId": "r1",
                    "timestamp": "2025-01-15T10:00:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": long_message}],
                    },
                }
            ),
            encoding="utf-8",
        )

        content, warnings = _generate_structured_context(
            parent_name="test",
            lineage=["test"],
            transcript_path=transcript,
            artifacts_path=None,
            proxy_template=None,
            latest_plan_path=None,
        )
        # Message should be truncated (500 chars + "...")
        assert long_message not in content
        assert "..." in content

    def test_includes_tool_summaries(self, sample_transcript: Path) -> None:
        """Should include tool call summaries."""
        content, warnings = _generate_structured_context(
            parent_name="test",
            lineage=["test"],
            transcript_path=sample_transcript,
            artifacts_path=None,
            proxy_template=None,
            latest_plan_path=None,
        )
        assert "Read" in content
        assert "/path/to/file.py" in content

    def test_warns_when_transcript_missing(self, tmp_path: Path) -> None:
        """Should warn when transcript doesn't exist."""
        nonexistent = tmp_path / "nonexistent.jsonl"
        content, warnings = _generate_structured_context(
            parent_name="test",
            lineage=["test"],
            transcript_path=nonexistent,
            artifacts_path=None,
            proxy_template=None,
            latest_plan_path=None,
        )
        assert "*Transcript not available.*" in content
        assert len(warnings) == 1
        assert "not found" in warnings[0]

    def test_handles_requestless_legacy_entries_with_message_content(self, tmp_path: Path) -> None:
        """Request-less legacy entries should still produce a structured turn."""
        transcript = tmp_path / "legacy-message.jsonl"
        transcript.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "user",
                            "timestamp": "2025-01-15T10:00:00Z",
                            "message": {"content": [{"type": "text", "text": "hello from parent"}]},
                        }
                    ),
                    json.dumps(
                        {
                            "type": "assistant",
                            "timestamp": "2025-01-15T10:00:01Z",
                            "message": {"content": [{"type": "text", "text": "hi from assistant"}]},
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        content, warnings = _generate_structured_context(
            parent_name="legacy-message",
            lineage=["legacy-message"],
            transcript_path=transcript,
            artifacts_path=None,
            proxy_template=None,
            latest_plan_path=None,
        )

        assert "### Turn 1" in content
        assert "**User**: hello from parent" in content
        assert "**Assistant**: hi from assistant" in content
        assert "*No conversation content found.*" not in content
        assert warnings == []

    def test_handles_older_text_only_entries_without_request_id(self, tmp_path: Path) -> None:
        """Older text-only transcript entries should still be summarized."""
        transcript = tmp_path / "legacy-text.jsonl"
        transcript.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "human",
                            "timestamp": "2025-01-15T10:00:00Z",
                            "text": "legacy hello",
                        }
                    ),
                    json.dumps(
                        {
                            "type": "ai",
                            "timestamp": "2025-01-15T10:00:01Z",
                            "text": "legacy response",
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        content, warnings = _generate_structured_context(
            parent_name="legacy-text",
            lineage=["legacy-text"],
            transcript_path=transcript,
            artifacts_path=None,
            proxy_template=None,
            latest_plan_path=None,
        )

        assert "### Turn 1" in content
        assert "**User**: legacy hello" in content
        assert "**Assistant**: legacy response" in content
        assert "*No conversation content found.*" not in content
        assert warnings == []


# -----------------------------------------------------------------------------
# Test ResumeStrategy enum
# -----------------------------------------------------------------------------


class TestResumeStrategy:
    """Tests for ResumeStrategy enum."""

    def test_values(self) -> None:
        """Should have expected values."""
        assert ResumeStrategy.MINIMAL.value == "minimal"
        assert ResumeStrategy.STRUCTURED.value == "structured"
        assert ResumeStrategy.FULL.value == "full"
        assert ResumeStrategy.AI_CURATED.value == "ai-curated"

    def test_from_string(self) -> None:
        """Should be constructible from string."""
        assert ResumeStrategy("minimal") == ResumeStrategy.MINIMAL
        assert ResumeStrategy("structured") == ResumeStrategy.STRUCTURED
        assert ResumeStrategy("full") == ResumeStrategy.FULL
        assert ResumeStrategy("ai-curated") == ResumeStrategy.AI_CURATED

    def test_invalid_raises(self) -> None:
        """Invalid values should raise ValueError."""
        with pytest.raises(ValueError):
            ResumeStrategy("invalid")


# -----------------------------------------------------------------------------
# Test with fixture file
# -----------------------------------------------------------------------------


class TestWithFixtureFile:
    """Tests using the shared transcript fixture file."""

    @pytest.fixture
    def fixture_transcript(self) -> Path:
        """Return path to the shared fixture file."""
        return Path(__file__).parent.parent.parent / "fixtures" / "transcript_sample.jsonl"

    def test_parses_fixture(self, fixture_transcript: Path) -> None:
        """Should parse the shared fixture file."""
        # Fixture is committed - fail if missing (catches packaging/path issues)
        assert fixture_transcript.exists(), f"Fixture file not found at {fixture_transcript}"

        entries = parse_jsonl_transcript(fixture_transcript)
        assert len(entries) == 10  # 10 entries in fixture

    def test_structured_context_from_fixture(self, fixture_transcript: Path) -> None:
        """Should generate structured context from fixture."""
        # Fixture is committed - fail if missing (catches packaging/path issues)
        assert fixture_transcript.exists(), f"Fixture file not found at {fixture_transcript}"

        content, warnings = _generate_structured_context(
            parent_name="fixture-test",
            lineage=["fixture-test"],
            transcript_path=fixture_transcript,
            artifacts_path=".forge/artifacts/fixture-test/transcripts/abc.jsonl",
            proxy_template="litellm-gemini",
            latest_plan_path=".claude/plans/my-plan.md",
        )

        # Check key elements
        assert "# Session Context: fixture-test" in content
        assert "litellm-gemini" in content
        assert "## Conversation Summary" in content
        assert "## Artifacts" in content
        assert ".claude/plans/my-plan.md" in content


# -----------------------------------------------------------------------------
# Test _format_transcript_for_llm
# -----------------------------------------------------------------------------


class TestFormatTranscriptForLLM:
    """Tests for transcript formatting with input bounding."""

    def test_formats_entries_correctly(self, sample_transcript: Path) -> None:
        """Should format transcript entries as [ROLE] text lines."""
        entries = parse_jsonl_transcript(sample_transcript)
        formatted, was_truncated, emitted_turns = _format_transcript_for_llm(entries)

        assert "[USER]" in formatted or "[ASSISTANT]" in formatted
        assert was_truncated is False
        # emitted_turns is the set of citable anchors used to validate decision citations.
        assert len(emitted_turns) >= 1

    def test_respects_max_chars_limit(self, tmp_path: Path) -> None:
        """Should truncate transcript at MAX_TRANSCRIPT_CHARS."""
        # Create large transcript that exceeds limit
        large_transcript = tmp_path / "large.jsonl"
        entries = [
            json.dumps(
                {
                    "requestId": f"r{i}",
                    "timestamp": f"2025-01-{(i % 28) + 1:02d}T10:00:00Z",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": "x" * 1000}],
                    },
                }
            )
            for i in range(100)  # 100 entries × 1000 chars = ~100K chars
        ]
        large_transcript.write_text("\n".join(entries), encoding="utf-8")

        parsed = parse_jsonl_transcript(large_transcript)
        formatted, was_truncated, _ = _format_transcript_for_llm(parsed)

        # Should be truncated and include marker
        assert was_truncated is True
        assert "...(transcript truncated for length)" in formatted
        assert len(formatted) <= MAX_TRANSCRIPT_CHARS + 100  # +100 for marker

    def test_empty_entries_returns_empty(self) -> None:
        """Empty entries should return empty string and no truncation."""
        formatted, was_truncated, emitted_turns = _format_transcript_for_llm([])
        assert formatted == ""
        assert was_truncated is False
        assert emitted_turns == set()


# -----------------------------------------------------------------------------
# Test _generate_ai_curated_context
# -----------------------------------------------------------------------------


class TestDecisionCitationValidation:
    """Unit tests for citation grounding (no LLM)."""

    @pytest.mark.parametrize(
        "citation,emitted_turns,grounded",
        [
            ("turn 2", {1, 2, 3}, True),
            ("turn 3", {1, 2, 3}, True),
            ("turn 4", {1, 2, 3}, False),  # out of range
            ("turn 0", {1, 2, 3}, False),  # turns are 1-indexed
            ("turn 1", set(), False),  # unknown range -> not trusted
            ("turn 2", {1, 3}, False),  # SPARSE: turn 2 was skipped (never emitted) -> fabricated
            ("[turn 2]", {1, 2, 3}, True),  # bracketed form
            ("src/forge/session/transfer.py:80", {1, 2, 3}, True),
            ("src/forge/session/transfer.py:80-95", {1, 2, 3}, True),  # line range
            ("README.md", {1, 2, 3}, True),
            ("because the user asked", {1, 2, 3}, False),  # prose
            ("earlier in the session", {1, 2, 3}, False),
        ],
    )
    def test_citation_is_grounded(self, citation: str, emitted_turns: set[int], grounded: bool) -> None:
        assert _citation_is_grounded(citation, emitted_turns) is grounded

    def test_blanks_ungrounded_keeps_text(self) -> None:
        """An ungrounded citation is blanked; the decision text is preserved."""
        decisions = [{"text": "Keep this", "citation": "turn 99"}]
        sanitized, warnings = _validate_decision_citations(decisions, emitted_turns={1, 2})
        assert sanitized[0]["text"] == "Keep this"
        assert sanitized[0]["citation"] == ""
        assert len(warnings) == 1

    def test_grounded_citation_untouched(self) -> None:
        decisions = [{"text": "Keep", "citation": "turn 1"}]
        sanitized, warnings = _validate_decision_citations(decisions, emitted_turns={1, 2})
        assert sanitized[0]["citation"] == "turn 1"
        assert warnings == []

    def test_non_list_and_string_items_pass_through(self) -> None:
        """Non-list input and bare-string items are returned unchanged, no error."""
        assert _validate_decision_citations(None, emitted_turns={1, 2}) == (None, [])
        sanitized, warnings = _validate_decision_citations(["plain decision"], emitted_turns={1, 2})
        assert sanitized == ["plain decision"]
        assert warnings == []

    def test_missing_citation_not_flagged(self) -> None:
        """A decision with no citation is fine -- it claims no provenance to fake."""
        decisions = [{"text": "No cite here"}]
        sanitized, warnings = _validate_decision_citations(decisions, emitted_turns={1, 2})
        assert sanitized[0]["text"] == "No cite here"
        assert warnings == []


class TestTargetRuntimeRelabel:
    """Slice 5d: ``target_runtime`` threads to frontmatter + Runtime Hints. The claude
    (default) variant renders byte-identically to pre-5d output -- a relabel, not a
    schema change."""

    _CURATED = {
        "goal": "Ship the Codex bridge",
        "decisions": [{"text": "One run tree across runtimes", "citation": "turn 1"}],
        "current_state": "Mid-implementation",
        "files": ["src/forge/core/invoker/codex.py"],
        "open_questions": ["Sandbox default?"],
    }

    def _curated_body(self, sample_transcript: Path, target_runtime: str) -> str:
        from unittest.mock import MagicMock, patch

        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = _fake_completion(json.dumps(self._CURATED))
        with (
            patch("forge.core.llm.SyncAdapter", return_value=mock_adapter),
            patch("forge.core.llm.get_client"),
        ):
            content, _warnings, schema = _generate_ai_curated_context(
                parent_name="p",
                lineage=["p"],
                transcript_path=sample_transcript,
                artifacts_path=None,
                proxy_template=None,
                latest_plan_path=None,
                target_runtime=target_runtime,
            )
        assert schema == "full"
        return content

    def _frontmatter(self, target_runtime: str | None) -> dict:
        kwargs: dict[str, Any] = dict(
            parent_name="p",
            strategy="ai-curated",
            schema="full",
            depth=1,
            lineage=["p"],
            transcript_artifact=None,
            token_estimate=None,
        )
        if target_runtime is not None:
            kwargs["target_runtime"] = target_runtime
        fm, _, _ = parse_transfer_frontmatter(_build_frontmatter(**kwargs))
        assert fm is not None
        return fm

    def test_frontmatter_default_is_claude(self) -> None:
        fm = self._frontmatter(None)
        assert fm["target_runtime"] == "claude"
        assert fm["schema_version"] == 1

    def test_frontmatter_codex_keeps_schema_version(self) -> None:
        fm = self._frontmatter("codex")
        assert fm["target_runtime"] == "codex"
        assert fm["schema_version"] == 1  # relabel, never a schema bump

    def test_runtime_hints_claude_is_the_historical_single_line(self, sample_transcript: Path) -> None:
        body = self._curated_body(sample_transcript, "claude")
        assert "Target runtime: claude." in body
        assert "codex exec" not in body  # no Codex guidance leaks into the claude variant

    def test_runtime_hints_codex_names_codex_idioms(self, sample_transcript: Path) -> None:
        body = self._curated_body(sample_transcript, "codex")
        assert "Target runtime: codex." in body
        assert "codex exec" in body
        assert "sandbox" in body.lower()

    def test_only_runtime_hints_differ_between_variants(self, sample_transcript: Path) -> None:
        claude_body = self._curated_body(sample_transcript, "claude")
        codex_body = self._curated_body(sample_transcript, "codex")
        # Section skeleton (## headers) is identical across variants.
        claude_headers = [ln for ln in claude_body.splitlines() if ln.startswith("## ")]
        codex_headers = [ln for ln in codex_body.splitlines() if ln.startswith("## ")]
        assert claude_headers == codex_headers
        # Everything before Runtime Hints (Decisions, Files, citations) is byte-identical.
        assert claude_body.split("## Runtime Hints")[0] == codex_body.split("## Runtime Hints")[0]

    @pytest.mark.parametrize(
        "strategy",
        [ResumeStrategy.MINIMAL, ResumeStrategy.STRUCTURED, ResumeStrategy.FULL],
    )
    def test_compatibility_fallback_codex_body_gets_runtime_hints(
        self, tmp_path: Path, strategy: ResumeStrategy
    ) -> None:
        from forge.session.models import create_session_state

        result = assemble_transfer_context(
            parent_name="parent",
            parent_state=create_session_state(name="parent", worktree_path=str(tmp_path)),
            forge_root=tmp_path,
            strategy=strategy,
            depth=1,
            get_session=lambda _: None,
            target_runtime="codex",
        )
        assert result.context_file is not None
        frontmatter, body, warning = parse_transfer_frontmatter(result.context_file.read_text())
        assert warning is None
        assert frontmatter is not None
        assert frontmatter["schema"] == "compatibility-fallback"
        assert frontmatter["target_runtime"] == "codex"
        assert "## Runtime Hints" in body
        assert "codex exec" in body
        assert "sandbox" in body.lower()


class TestAICuratedStrategy:
    """Tests for AI-curated strategy with mocked LLM."""

    def test_ai_curated_renders_schema_sections(self, sample_transcript: Path) -> None:
        """AI-curated should call the LLM and render the structured schema sections."""
        from unittest.mock import MagicMock, patch

        curated = {
            "goal": "Refactor the transfer subsystem",
            "decisions": [{"text": "Use child-agnostic frontmatter", "citation": "turn 1"}],
            "current_state": "Schema landed",
            "files": ["src/forge/session/transfer.py:80 - schema enum"],
            "open_questions": ["Do we change the default strategy?"],
        }
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = _fake_completion(json.dumps(curated))

        # Patch at source module since lazy import is used
        with (
            patch("forge.core.llm.SyncAdapter", return_value=mock_adapter),
            patch("forge.core.llm.get_client") as mock_get_client,
        ):
            content, warnings, schema = _generate_ai_curated_context(
                parent_name="test-parent",
                lineage=["test-parent"],
                transcript_path=sample_transcript,
                artifacts_path=None,
                proxy_template=None,
                latest_plan_path=None,
            )

        mock_get_client.assert_called_once_with(AI_CURATION_MODEL, provider=AI_CURATION_PROVIDER)
        mock_adapter.complete.assert_called_once()
        # Full 8-section schema: sections 1-7 live in the snapshot body.
        assert schema == "full"
        for header in (
            "## Goal / Current Task",
            "## Decisions",
            "## Current State",
            "## Relevant Files",
            "## Open Questions",
            "## Runtime Hints",
        ):
            assert header in content, header
        # Decision text and its grounded (in-range) citation are rendered.
        assert "Use child-agnostic frontmatter" in content
        assert "turn 1" in content
        # Model attribution + security warning.
        assert f"{AI_CURATION_MODEL} via {AI_CURATION_PROVIDER}" in content
        assert any("for processing" in w for w in warnings)

    def test_ai_curated_strips_ungrounded_citations(self, sample_transcript: Path) -> None:
        """Fabricated citations are dropped (decision text kept) and warned about.

        The fixture yields a single turn, so ``turn 99`` is out of range and a
        prose citation is not a turn/file ref -- both must be stripped. A valid
        ``turn 1`` and a ``file:line`` citation must survive.
        """
        from unittest.mock import MagicMock, patch

        curated = {
            "goal": "Goal",
            "decisions": [
                {"text": "Fabricated turn decision", "citation": "turn 99"},
                {"text": "Vague decision", "citation": "because the user said so"},
                {"text": "Grounded turn decision", "citation": "turn 1"},
                {"text": "Grounded file decision", "citation": "src/forge/session/transfer.py:80"},
            ],
            "current_state": "State",
            "files": [],
            "open_questions": [],
        }
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = _fake_completion(json.dumps(curated))

        with (
            patch("forge.core.llm.SyncAdapter", return_value=mock_adapter),
            patch("forge.core.llm.get_client"),
        ):
            content, warnings, schema = _generate_ai_curated_context(
                parent_name="p",
                lineage=["p"],
                transcript_path=sample_transcript,
                artifacts_path=None,
                proxy_template=None,
                latest_plan_path=None,
            )

        assert schema == "full"
        # All decision text survives; only the false provenance is removed.
        for text in ("Fabricated turn decision", "Vague decision", "Grounded turn decision"):
            assert text in content
        assert "turn 99" not in content
        assert "because the user said so" not in content
        # Grounded citations are preserved verbatim.
        assert "turn 1" in content
        assert "src/forge/session/transfer.py:80" in content
        # Each dropped citation is surfaced as a warning (not silent).
        dropped = [w for w in warnings if "ungrounded citation" in w]
        assert len(dropped) == 2

    def test_ai_curated_fallback_on_llm_error(self, sample_transcript: Path) -> None:
        """Should fall back to structured on LLM error."""
        from unittest.mock import MagicMock, patch

        mock_adapter = MagicMock()
        mock_adapter.complete.side_effect = Exception("API timeout")

        # Patch at source module since lazy import is used
        with (
            patch("forge.core.llm.SyncAdapter", return_value=mock_adapter),
            patch("forge.core.llm.get_client"),
        ):
            content, warnings, schema = _generate_ai_curated_context(
                parent_name="test",
                lineage=["test"],
                transcript_path=sample_transcript,
                artifacts_path=None,
                proxy_template=None,
                latest_plan_path=None,
            )

        # Fallback to structured marks the body as a compatibility fallback.
        assert schema == "compatibility-fallback"
        assert any("using structured" in w.lower() for w in warnings)
        # Structured output has Conversation Summary section
        assert "Conversation Summary" in content

    def test_ai_curated_no_transcript_uses_minimal(self) -> None:
        """Should use minimal strategy if no transcript."""
        content, warnings, schema = _generate_ai_curated_context(
            parent_name="test",
            lineage=["test"],
            transcript_path=None,
            artifacts_path=None,
            proxy_template=None,
            latest_plan_path=None,
        )

        # Fallback to minimal marks the body as a compatibility fallback.
        assert schema == "compatibility-fallback"
        assert any("using minimal" in w.lower() for w in warnings)
        # Minimal output has Lineage section
        assert "## Lineage" in content

    def test_ai_curated_empty_transcript_uses_minimal(self, tmp_path: Path) -> None:
        """Should use minimal strategy if transcript is empty."""
        empty_transcript = tmp_path / "empty.jsonl"
        empty_transcript.write_text("", encoding="utf-8")

        content, warnings, schema = _generate_ai_curated_context(
            parent_name="test",
            lineage=["test"],
            transcript_path=empty_transcript,
            artifacts_path=None,
            proxy_template=None,
            latest_plan_path=None,
        )

        # Fallback to minimal marks the body as a compatibility fallback.
        assert schema == "compatibility-fallback"
        assert any("using minimal" in w.lower() for w in warnings)

    def test_transcript_truncation_adds_warning(self, tmp_path: Path) -> None:
        """Should warn when transcript is truncated."""
        from unittest.mock import MagicMock, patch

        # Create oversized transcript
        large_transcript = tmp_path / "large.jsonl"
        entries = [
            json.dumps(
                {
                    "requestId": f"r{i}",
                    "timestamp": f"2025-01-{(i % 28) + 1:02d}T10:00:00Z",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": "x" * 1000}],
                    },
                }
            )
            for i in range(100)  # Exceeds MAX_TRANSCRIPT_CHARS
        ]
        large_transcript.write_text("\n".join(entries), encoding="utf-8")

        # Mock LLM (patch at source module since lazy import is used)
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = _fake_completion(json.dumps({"goal": "g", "current_state": "s"}))

        with (
            patch("forge.core.llm.SyncAdapter", return_value=mock_adapter),
            patch("forge.core.llm.get_client"),
        ):
            content, warnings, schema = _generate_ai_curated_context(
                parent_name="test",
                lineage=["test"],
                transcript_path=large_transcript,
                artifacts_path=None,
                proxy_template=None,
                latest_plan_path=None,
            )

        # Should have truncation warning
        assert any("truncated" in w.lower() for w in warnings)
        # But should still succeed with the full curated schema
        assert schema == "full"
        assert "## Goal / Current Task" in content


class TestResolvePlanContent:
    """Tests for _resolve_plan_content plan resolution."""

    def test_approved_snapshot_preferred(self, tmp_path: Path) -> None:
        """Approved plan snapshot wins over latest_plan_path."""
        # Create snapshot (repo-root-relative)
        snapshot_dir = tmp_path / ".forge" / "artifacts" / "planner" / "plans"
        snapshot_dir.mkdir(parents=True)
        snapshot = snapshot_dir / "plan_20260325.md"
        snapshot.write_text("# The Approved Plan\nStep 1: do the thing")

        # Create a different file at latest_plan_path
        draft = tmp_path / ".claude" / "plans" / "draft.md"
        draft.parent.mkdir(parents=True)
        draft.write_text("# Draft (should not be used)")

        confirmed = cast(
            Any,
            type(
                "C",
                (),
                {
                    "artifacts": {
                        "plans": [
                            {
                                "kind": "approved",
                                "snapshot_path": ".forge/artifacts/planner/plans/plan_20260325.md",
                            }
                        ]
                    },
                    "latest_plan_path": ".claude/plans/draft.md",
                },
            )(),
        )

        result = _resolve_plan_content(confirmed, tmp_path)
        assert result is not None
        assert "The Approved Plan" in result
        assert "Draft" not in result

    def test_latest_plan_path_fallback(self, tmp_path: Path) -> None:
        """Falls back to latest_plan_path when no approved snapshots exist."""
        plan_file = tmp_path / ".claude" / "plans" / "my-plan.md"
        plan_file.parent.mkdir(parents=True)
        plan_file.write_text("# Fallback Plan")

        confirmed = cast(
            Any,
            type(
                "C",
                (),
                {
                    "artifacts": {},
                    "latest_plan_path": ".claude/plans/my-plan.md",
                },
            )(),
        )

        # latest_plan_path resolves against parent_worktree_root
        result = _resolve_plan_content(confirmed, Path("/nonexistent"), parent_worktree_root=tmp_path)
        assert result is not None
        assert "Fallback Plan" in result

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        """Returns None when plan files don't exist on disk."""
        confirmed = cast(
            Any,
            type(
                "C",
                (),
                {
                    "artifacts": {"plans": [{"kind": "approved", "snapshot_path": "nonexistent.md"}]},
                    "latest_plan_path": "also-nonexistent.md",
                },
            )(),
        )

        result = _resolve_plan_content(confirmed, tmp_path)
        assert result is None

    def test_no_plan_at_all(self) -> None:
        """Returns None when no plan path is configured."""
        confirmed = cast(
            Any,
            type(
                "C",
                (),
                {
                    "artifacts": {},
                    "latest_plan_path": None,
                },
            )(),
        )

        result = _resolve_plan_content(confirmed, Path("/tmp"))
        assert result is None


class TestInlinePlan:
    """Tests for inline_plan parameter in assemble_transfer_context and strategy generators."""

    def _make_parent_state(self, tmp_path: Path, *, with_plan: bool = False) -> SessionState:
        """Create a minimal parent SessionState for testing."""
        from forge.session.models import create_session_state

        state = create_session_state(
            name="parent",
            worktree_path=str(tmp_path),
        )
        if with_plan:
            plan_dir = tmp_path / ".forge" / "artifacts" / "parent" / "plans"
            plan_dir.mkdir(parents=True)
            plan_file = plan_dir / "plan_test.md"
            plan_file.write_text("# Test Plan\n\n1. Do X\n2. Do Y")
            state.confirmed.artifacts["plans"] = [
                {"kind": "approved", "snapshot_path": ".forge/artifacts/parent/plans/plan_test.md"}
            ]
        return state

    def test_inline_plan_false_shows_path_only(self, tmp_path: Path) -> None:
        """Default inline_plan=False shows path reference, not content."""
        state = self._make_parent_state(tmp_path, with_plan=True)
        state.confirmed.latest_plan_path = ".claude/plans/draft.md"

        result = assemble_transfer_context(
            parent_name="parent",
            parent_state=state,
            forge_root=tmp_path,
            strategy=ResumeStrategy.STRUCTURED,
            depth=1,
            get_session=lambda _: None,
            inline_plan=False,
        )
        content = result.context_file.read_text() if result.context_file else ""
        assert "## Approved Plan" not in content
        assert "Test Plan" not in content

    def test_inline_plan_true_includes_content(self, tmp_path: Path) -> None:
        """inline_plan=True inlines the approved plan content."""
        state = self._make_parent_state(tmp_path, with_plan=True)

        result = assemble_transfer_context(
            parent_name="parent",
            parent_state=state,
            forge_root=tmp_path,
            strategy=ResumeStrategy.STRUCTURED,
            depth=1,
            get_session=lambda _: None,
            inline_plan=True,
        )
        content = result.context_file.read_text() if result.context_file else ""
        assert "## Approved Plan" in content
        assert "Do X" in content
        assert "Do Y" in content

    def test_inline_plan_missing_file_warns(self, tmp_path: Path) -> None:
        """inline_plan=True with missing plan file adds warning."""
        state = self._make_parent_state(tmp_path, with_plan=False)
        state.confirmed.latest_plan_path = "nonexistent/plan.md"

        result = assemble_transfer_context(
            parent_name="parent",
            parent_state=state,
            forge_root=tmp_path,
            strategy=ResumeStrategy.STRUCTURED,
            depth=1,
            get_session=lambda _: None,
            inline_plan=True,
        )
        assert any("not found" in w.lower() for w in result.warnings)

    def test_inline_plan_no_plan_configured_warns(self, tmp_path: Path) -> None:
        """inline_plan=True with no plan path at all still warns."""
        state = self._make_parent_state(tmp_path, with_plan=False)

        result = assemble_transfer_context(
            parent_name="parent",
            parent_state=state,
            forge_root=tmp_path,
            strategy=ResumeStrategy.STRUCTURED,
            depth=1,
            get_session=lambda _: None,
            inline_plan=True,
        )
        assert any("not found" in w.lower() for w in result.warnings)
        assert any("no plan path" in w.lower() for w in result.warnings)

    def test_inline_plan_two_root_resolution(self, tmp_path: Path) -> None:
        """Approved snapshot resolves against project_root; latest_plan_path against worktree root."""
        # project_root (main repo) has the approved snapshot
        main_repo = tmp_path / "main"
        main_repo.mkdir()
        snapshot_dir = main_repo / ".forge" / "artifacts" / "parent" / "plans"
        snapshot_dir.mkdir(parents=True)
        (snapshot_dir / "plan.md").write_text("# From Main Repo Snapshot")

        # parent worktree is a different directory
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        state = self._make_parent_state(worktree, with_plan=False)
        state.confirmed.artifacts["plans"] = [
            {"kind": "approved", "snapshot_path": ".forge/artifacts/parent/plans/plan.md"}
        ]

        result = assemble_transfer_context(
            parent_name="parent",
            parent_state=state,
            forge_root=main_repo,
            parent_worktree_root=worktree,
            strategy=ResumeStrategy.STRUCTURED,
            depth=1,
            get_session=lambda _: None,
            inline_plan=True,
        )
        content = result.context_file.read_text() if result.context_file else ""
        assert "From Main Repo Snapshot" in content

    def test_inline_plan_fallback_uses_worktree_root(self, tmp_path: Path) -> None:
        """latest_plan_path fallback resolves against parent_worktree_root, not project_root."""
        main_repo = tmp_path / "main"
        main_repo.mkdir()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        plan_file = worktree / ".claude" / "plans" / "draft.md"
        plan_file.parent.mkdir(parents=True)
        plan_file.write_text("# Plan From Worktree")

        state = self._make_parent_state(worktree, with_plan=False)
        state.confirmed.latest_plan_path = ".claude/plans/draft.md"

        result = assemble_transfer_context(
            parent_name="parent",
            parent_state=state,
            forge_root=main_repo,
            parent_worktree_root=worktree,
            strategy=ResumeStrategy.STRUCTURED,
            depth=1,
            get_session=lambda _: None,
            inline_plan=True,
        )
        content = result.context_file.read_text() if result.context_file else ""
        assert "Plan From Worktree" in content

    def test_inline_plan_with_full_strategy(self, tmp_path: Path) -> None:
        """inline_plan works with full strategy too."""
        state = self._make_parent_state(tmp_path, with_plan=True)

        result = assemble_transfer_context(
            parent_name="parent",
            parent_state=state,
            forge_root=tmp_path,
            strategy=ResumeStrategy.FULL,
            depth=1,
            get_session=lambda _: None,
            inline_plan=True,
        )
        content = result.context_file.read_text() if result.context_file else ""
        assert "## Approved Plan" in content
        assert "Do X" in content

    def test_inline_plan_with_minimal_strategy(self, tmp_path: Path) -> None:
        """inline_plan works with minimal strategy."""
        state = self._make_parent_state(tmp_path, with_plan=True)

        result = assemble_transfer_context(
            parent_name="parent",
            parent_state=state,
            forge_root=tmp_path,
            strategy=ResumeStrategy.MINIMAL,
            depth=1,
            get_session=lambda _: None,
            inline_plan=True,
        )
        content = result.context_file.read_text() if result.context_file else ""
        assert "## Approved Plan" in content
        assert "Do X" in content

    def test_inline_plan_with_ai_curated_strategy(self, tmp_path: Path) -> None:
        """inline_plan works with ai-curated strategy (falls back to structured on LLM error)."""
        state = self._make_parent_state(tmp_path, with_plan=True)

        # AI curation will fail (no LLM configured), falling back to structured
        result = assemble_transfer_context(
            parent_name="parent",
            parent_state=state,
            forge_root=tmp_path,
            strategy=ResumeStrategy.AI_CURATED,
            depth=1,
            get_session=lambda _: None,
            inline_plan=True,
        )
        content = result.context_file.read_text() if result.context_file else ""
        # Plan should be inlined regardless of which strategy runs
        assert "## Approved Plan" in content
        assert "Do X" in content


class TestTransferFrontmatter:
    """The child-agnostic YAML frontmatter contract on every strategy."""

    def _parent(self, tmp_path: Path) -> SessionState:
        from forge.session.models import create_session_state

        return create_session_state(name="parent", worktree_path=str(tmp_path))

    @pytest.mark.parametrize(
        "strategy",
        [ResumeStrategy.MINIMAL, ResumeStrategy.STRUCTURED, ResumeStrategy.FULL],
    )
    def test_compatibility_fallback_frontmatter(self, tmp_path: Path, strategy: ResumeStrategy) -> None:
        """Non-curated strategies carry frontmatter + a compatibility-fallback marker."""
        result = assemble_transfer_context(
            parent_name="parent",
            parent_state=self._parent(tmp_path),
            forge_root=tmp_path,
            strategy=strategy,
            depth=2,
            get_session=lambda _: None,
        )
        assert result.context_file is not None
        frontmatter, body, warning = parse_transfer_frontmatter(result.context_file.read_text())

        assert warning is None
        assert frontmatter is not None
        assert frontmatter["schema_version"] == 1
        assert frontmatter["parent"] == "parent"
        assert frontmatter["strategy"] == strategy.value
        assert frontmatter["schema"] == "compatibility-fallback"
        assert frontmatter["depth"] == 2
        assert frontmatter["target_runtime"] == "claude"
        # The human-readable body is preserved beneath the frontmatter.
        assert body.lstrip().startswith("# Session Context")

    def test_unknown_target_runtime_rejected(self, tmp_path: Path) -> None:
        """Internal boundary: assemble validates against TRANSFER_TARGET_RUNTIMES (the
        single source the ops layer and the CLI Choice also consume)."""
        with pytest.raises(ValueError, match="Unknown target runtime 'gemini'"):
            assemble_transfer_context(
                parent_name="parent",
                parent_state=self._parent(tmp_path),
                forge_root=tmp_path,
                strategy=ResumeStrategy.MINIMAL,
                depth=1,
                get_session=lambda _: None,
                target_runtime="gemini",
            )

    def test_frontmatter_has_no_child_field(self, tmp_path: Path) -> None:
        """A child: field would break the byte-for-byte generated->child copy."""
        result = assemble_transfer_context(
            parent_name="parent",
            parent_state=self._parent(tmp_path),
            forge_root=tmp_path,
            strategy=ResumeStrategy.MINIMAL,
            depth=1,
            get_session=lambda _: None,
        )
        assert result.context_file is not None
        frontmatter, _, _ = parse_transfer_frontmatter(result.context_file.read_text())
        assert frontmatter is not None
        assert "child" not in frontmatter

    def test_generated_and_child_are_byte_identical(self, tmp_path: Path) -> None:
        """ensure_child copies generated.md verbatim -- the durability invariant."""
        from forge.session.prev_sessions import child_path, generated_path

        result = assemble_transfer_context(
            parent_name="parent",
            parent_state=self._parent(tmp_path),
            forge_root=tmp_path,
            strategy=ResumeStrategy.STRUCTURED,
            depth=1,
            get_session=lambda _: None,
            child_name="kid",
        )
        generated = generated_path(tmp_path, "parent")
        child = child_path(tmp_path, "parent", "kid")
        assert generated.read_bytes() == child.read_bytes()
        assert result.context_file == child

    def test_parse_frontmatter_degrades_on_malformed_yaml(self) -> None:
        """Malformed frontmatter never raises: warn + return the body (system boundary)."""
        frontmatter, body, warning = parse_transfer_frontmatter("---\n::: not yaml :::\n---\nbody text")
        assert frontmatter is None
        assert warning is not None
        assert "body text" in body

    def test_parse_frontmatter_without_frontmatter(self) -> None:
        frontmatter, body, warning = parse_transfer_frontmatter("# Just a body\nno frontmatter here")
        assert frontmatter is None
        assert warning is None
        assert "Just a body" in body


class TestCurationUsageEmission:
    """Slice 5e: the ai-curated curation ``core.llm`` call is attributed to the usage
    ledger (closing a prior gap) -- but only under an ambient run identity, so a normal
    resume outside a Forge run tree stays silent."""

    _CURATED = {
        "goal": "g",
        "decisions": [],
        "current_state": "s",
        "files": [],
        "open_questions": [],
    }

    def _run_curation(self, sample_transcript: Path) -> None:
        from unittest.mock import MagicMock, patch

        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = _fake_completion(
            json.dumps(self._CURATED), usage={"prompt_tokens": 321, "completion_tokens": 12}
        )
        with (
            patch("forge.core.llm.SyncAdapter", return_value=mock_adapter),
            patch("forge.core.llm.get_client"),
        ):
            _content, _warnings, schema = _generate_ai_curated_context(
                parent_name="p",
                lineage=["p"],
                transcript_path=sample_transcript,
                artifacts_path=None,
                proxy_template=None,
                latest_plan_path=None,
            )
        assert schema == "full"

    def test_emits_one_core_llm_event_under_run_identity(
        self, sample_transcript: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from forge.core.usage.ledger import read_usage_events

        monkeypatch.setenv("FORGE_RUN_ID", "run_root")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_root")
        monkeypatch.setenv("FORGE_SESSION", "planner")
        monkeypatch.delenv("FORGE_PARENT_RUN_ID", raising=False)

        self._run_curation(sample_transcript)

        events = [e for e in read_usage_events() if e.command == "transfer-curate"]
        assert len(events) == 1, events
        e = events[0]
        assert e.route == "core_llm"
        assert e.runtime == "forge_cli"  # Forge core invoking core.llm, not Claude Code
        assert e.reporter == "provider"
        assert e.session == "planner"
        assert (e.run_id, e.root_run_id) == ("run_root", "run_root")
        assert e.input_tokens == 321  # provider tokens flow through
        assert e.cost_micro_usd is None  # the core.llm helper computes no $ figure

    def test_no_event_without_run_identity(self, sample_transcript: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from forge.core.usage.ledger import read_usage_events

        monkeypatch.delenv("FORGE_RUN_ID", raising=False)
        monkeypatch.delenv("FORGE_ROOT_RUN_ID", raising=False)

        self._run_curation(sample_transcript)

        assert [e for e in read_usage_events() if e.command == "transfer-curate"] == []

    def test_parse_failure_still_emits_error_event(
        self, sample_transcript: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A successful ``.complete()`` whose output is unparseable spent real tokens;
        the spend is attributed with ``status="error"`` BEFORE the structured fallback
        (the team-supervisor emit-before-success-gate precedent)."""
        from unittest.mock import MagicMock, patch

        from forge.core.usage.ledger import read_usage_events

        monkeypatch.setenv("FORGE_RUN_ID", "run_root")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_root")
        monkeypatch.delenv("FORGE_PARENT_RUN_ID", raising=False)

        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = _fake_completion(
            "definitely not json", usage={"prompt_tokens": 222, "completion_tokens": 9}
        )
        with (
            patch("forge.core.llm.SyncAdapter", return_value=mock_adapter),
            patch("forge.core.llm.get_client"),
        ):
            _content, warnings, schema = _generate_ai_curated_context(
                parent_name="p",
                lineage=["p"],
                transcript_path=sample_transcript,
                artifacts_path=None,
                proxy_template=None,
                latest_plan_path=None,
            )

        # The fallback still happens (unusable result), but the spend is not lost.
        assert schema == "compatibility-fallback"
        assert any("using structured" in w.lower() for w in warnings)
        events = [e for e in read_usage_events() if e.command == "transfer-curate"]
        assert len(events) == 1, events
        e = events[0]
        assert e.status == "error"
        assert e.failure_type == "unparseable_output"
        assert e.input_tokens == 222  # provider tokens attributed despite the bad output
        from forge.core.telemetry.upstream import read_upstream_outcomes

        outcomes = read_upstream_outcomes(command="transfer-curate")
        assert len(outcomes) == 1
        assert outcomes[0].operation == "transfer.curate"
        assert outcomes[0].status == "error"
        assert outcomes[0].reason_code == "unparseable_output"
