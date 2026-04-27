"""Docker-based E2E tests for `forge handoff run`.

Tests the full chain inside a Docker container with real filesystem:
CLI → SessionStore → effective intent → path validation → prompt → claude -p.

The mock claude binary captures both args and stdin (the prompt), so we can
verify the exact prompt content sent to the agent.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict

import pytest

from forge.session.models import (
    DesignatedDoc,
    HandoffConfig,
    MemoryIntent,
    create_session_state,
)
from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SESSION_NAME = "handoff-test"
PROXY_TEMPLATE = "test-template"
PROXY_URL = "http://localhost:8084"
TRANSCRIPT_REL = ".forge/artifacts/handoff-test/transcripts/uuid-123.jsonl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_manifest(
    *,
    handoff_enabled: bool = True,
    min_turns: int = 1,
    mode: str = "augment",
    designated_docs: list[DesignatedDoc] | None = None,
) -> dict:
    """Build a session manifest dict with handoff config."""
    manifest = create_session_state(
        SESSION_NAME,
        proxy_template=PROXY_TEMPLATE,
        proxy_base_url=PROXY_URL,
    )
    manifest.intent.memory = MemoryIntent(
        auto_update=HandoffConfig(
            enabled=handoff_enabled,
            mode=mode,
            min_turns=min_turns,
        ),
        designated_docs=designated_docs or [],
    )
    return asdict(manifest)


def _build_transcript(turn_count: int = 10) -> str:
    """Build a JSONL transcript string with the given number of turns."""
    lines = []
    for i in range(turn_count):
        lines.append(
            json.dumps(
                {
                    "requestId": f"req-{i}",
                    "timestamp": f"2026-01-01T00:0{i % 10}:00Z",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": f"turn {i}"}],
                    },
                }
            )
        )
        lines.append(
            json.dumps(
                {
                    "requestId": f"req-{i}",
                    "timestamp": f"2026-01-01T00:0{i % 10}:01Z",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": f"response {i}"}],
                    },
                }
            )
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHandoffRunMultiDoc:
    """E2E: forge handoff run with designated_docs."""

    def _setup_session(
        self,
        workspace: ContainerLike,
        *,
        manifest_dict: dict | None = None,
        target_files: dict[str, str] | None = None,
    ) -> None:
        """Create session manifest, transcript, and optional target files."""
        # Write manifest
        manifest = manifest_dict or _build_manifest()
        workspace.mkdir(f"/workspace/.forge/sessions/{SESSION_NAME}", parents=True)
        workspace.write_json(
            f"/workspace/.forge/sessions/{SESSION_NAME}/forge.session.json",
            manifest,
        )

        # Write transcript
        transcript_path = f"/workspace/{TRANSCRIPT_REL}"
        workspace.exec(f"mkdir -p $(dirname {transcript_path})")
        workspace.write_file(transcript_path, _build_transcript())

        # Write target doc files (for non-creatable strategies)
        if target_files:
            for path, content in target_files.items():
                workspace.exec(f"mkdir -p $(dirname /workspace/{path})")
                workspace.write_file(f"/workspace/{path}", content)

    def _run_handoff(self, workspace: ContainerLike, timeout: int = 30) -> int:
        """Run forge handoff run and return exit code."""
        result = workspace.exec(
            f"cd /workspace && forge handoff run "
            f"--session-name {SESSION_NAME} "
            f"--worktree-path /workspace "
            f"--transcript-rel {TRANSCRIPT_REL} "
            f"--timeout {timeout}",
            timeout=timeout + 10,
        )
        return result.returncode

    def test_multi_doc_prompt_sent_to_claude(
        self,
        mock_claude_workspace: ContainerLike,
        claude_capture_file: Callable[[str], str],
        claude_invocations: Callable[[], list[str]],
    ) -> None:
        """Full chain: manifest with designated_docs → multi-doc prompt to claude -p."""
        self._setup_session(
            mock_claude_workspace,
            manifest_dict=_build_manifest(
                designated_docs=[
                    DesignatedDoc(path="docs/checklist.md", strategy="checklist"),
                    DesignatedDoc(path="docs/changelog.md", strategy="changelog"),
                    DesignatedDoc(path=".forge/memory/project-state.md", strategy="project-state"),
                ],
            ),
            target_files={
                "docs/checklist.md": "# Checklist\n- [ ] task 1\n",
                "docs/changelog.md": "# Change Log\n## 2026-01-01\nInitial.\n",
                ".forge/memory/project-state.md": "# Project State\n",
            },
        )

        exit_code = self._run_handoff(mock_claude_workspace)
        assert exit_code == 0

        # Verify claude -p was invoked
        invocations = claude_invocations()
        assert any("claude -p" in inv for inv in invocations), f"Expected claude -p call, got: {invocations}"

        # Verify the prompt contains all three docs with correct strategies
        prompt = claude_capture_file("/tmp/claude_stdin_*.log")
        assert "docs/checklist.md" in prompt
        assert "docs/changelog.md" in prompt
        assert ".forge/memory/project-state.md" in prompt
        assert "Mark completed tasks" in prompt  # checklist strategy
        assert "accomplishments" in prompt  # changelog strategy

    def test_no_designated_docs_skips_cleanly(
        self,
        mock_claude_workspace: ContainerLike,
        claude_invocations: Callable[[], list[str]],
    ) -> None:
        """No designated_docs → exit 0, no claude -p call (nothing to update)."""
        self._setup_session(mock_claude_workspace, manifest_dict=_build_manifest())

        exit_code = self._run_handoff(mock_claude_workspace)
        assert exit_code == 0

        invocations = claude_invocations()
        assert not any("claude -p" in inv for inv in invocations)

    def test_missing_docs_filtered(
        self,
        mock_claude_workspace: ContainerLike,
        claude_capture_file: Callable[[str], str],
    ) -> None:
        """Docs that don't exist on disk are filtered from the prompt."""
        self._setup_session(
            mock_claude_workspace,
            manifest_dict=_build_manifest(
                designated_docs=[
                    DesignatedDoc(path="docs/nonexistent.md", strategy="checklist"),
                    DesignatedDoc(path="docs/checklist.md", strategy="checklist"),
                ],
            ),
            target_files={
                "docs/checklist.md": "# Checklist\n",
            },
            # Note: docs/nonexistent.md NOT created — should be filtered
        )

        exit_code = self._run_handoff(mock_claude_workspace)
        assert exit_code == 0

        prompt = claude_capture_file("/tmp/claude_stdin_*.log")
        assert "docs/checklist.md" in prompt
        assert "docs/nonexistent.md" not in prompt

    def test_no_file_creation_for_missing_docs(
        self,
        mock_claude_workspace: ContainerLike,
        claude_invocations: Callable[[], list[str]],
    ) -> None:
        """Missing docs are skipped — no directory creation, no claude -p call."""
        self._setup_session(
            mock_claude_workspace,
            manifest_dict=_build_manifest(
                designated_docs=[
                    DesignatedDoc(path=".forge/memory/project-state.md", strategy="project-state"),
                ],
            ),
        )

        # Verify directory doesn't exist
        check = mock_claude_workspace.exec("test -d /workspace/.forge/memory && echo yes || echo no")
        assert "no" in check.stdout

        exit_code = self._run_handoff(mock_claude_workspace)
        assert exit_code == 0

        # Directory still should NOT exist (no file creation)
        check = mock_claude_workspace.exec("test -d /workspace/.forge/memory && echo yes || echo no")
        assert "no" in check.stdout

        # No claude -p call (all docs missing)
        invocations = claude_invocations()
        assert not any("claude -p" in inv for inv in invocations)

    def test_review_only_mode(
        self,
        mock_claude_workspace: ContainerLike,
        claude_capture_file: Callable[[str], str],
    ) -> None:
        """Review-only mode → prompt says 'Do NOT modify any files'."""
        self._setup_session(
            mock_claude_workspace,
            manifest_dict=_build_manifest(
                mode="review-only",
                designated_docs=[
                    DesignatedDoc(path="docs/state.md", strategy="project-state"),
                ],
            ),
            target_files={
                "docs/state.md": "# State\n",
            },
        )

        exit_code = self._run_handoff(mock_claude_workspace)
        assert exit_code == 0

        prompt = claude_capture_file("/tmp/claude_stdin_*.log")
        assert "Do NOT modify any files" in prompt

    def test_shadow_doc_prompt(
        self,
        mock_claude_workspace: ContainerLike,
        claude_capture_file: Callable[[str], str],
    ) -> None:
        """Shadow doc: prompt reads official doc first, proposes changes to shadow."""
        self._setup_session(
            mock_claude_workspace,
            manifest_dict=_build_manifest(
                designated_docs=[
                    DesignatedDoc(
                        path=".forge/memory/suggested.md",
                        strategy="suggested",
                        shadows="STANDARDS.md",
                    ),
                ],
            ),
            target_files={
                ".forge/memory/suggested.md": "# Suggested\n",
                "STANDARDS.md": "# Standards\n",
            },
        )

        exit_code = self._run_handoff(mock_claude_workspace)
        assert exit_code == 0

        prompt = claude_capture_file("/tmp/claude_stdin_*.log")
        assert "proposes changes to `STANDARDS.md`" in prompt
        assert "Read the OFFICIAL document" in prompt


class TestHandoffRunDisabled:
    """E2E: forge handoff run when handoff is disabled or not configured."""

    def _setup_session(self, workspace: ContainerLike, manifest_dict: dict) -> None:
        """Create session manifest and transcript."""
        workspace.mkdir(f"/workspace/.forge/sessions/{SESSION_NAME}", parents=True)
        workspace.write_json(
            f"/workspace/.forge/sessions/{SESSION_NAME}/forge.session.json",
            manifest_dict,
        )
        transcript_path = f"/workspace/{TRANSCRIPT_REL}"
        workspace.exec(f"mkdir -p $(dirname {transcript_path})")
        workspace.write_file(transcript_path, _build_transcript())

    def test_disabled_exits_clean(
        self,
        mock_claude_workspace: ContainerLike,
        claude_invocations: Callable[[], list[str]],
    ) -> None:
        """Handoff enabled=false → exit 0, no claude -p call."""
        self._setup_session(
            mock_claude_workspace,
            _build_manifest(handoff_enabled=False),
        )

        result = mock_claude_workspace.exec(
            f"cd /workspace && forge handoff run "
            f"--session-name {SESSION_NAME} "
            f"--worktree-path /workspace "
            f"--transcript-rel {TRANSCRIPT_REL}"
        )
        assert result.returncode == 0

        invocations = claude_invocations()
        assert not any("claude -p" in inv for inv in invocations)

    def test_missing_session_exits_clean(
        self,
        mock_claude_workspace: ContainerLike,
        claude_invocations: Callable[[], list[str]],
    ) -> None:
        """Missing session manifest → exit 0, no claude -p call."""
        # Don't create any manifest — just the transcript
        workspace = mock_claude_workspace
        transcript_path = f"/workspace/{TRANSCRIPT_REL}"
        workspace.exec(f"mkdir -p $(dirname {transcript_path})")
        workspace.write_file(transcript_path, _build_transcript())

        result = workspace.exec(
            f"cd /workspace && forge handoff run "
            f"--session-name nonexistent-session "
            f"--worktree-path /workspace "
            f"--transcript-rel {TRANSCRIPT_REL}"
        )
        assert result.returncode == 0

        invocations = claude_invocations()
        assert not any("claude -p" in inv for inv in invocations)

    def test_below_min_turns_skips(
        self,
        mock_claude_workspace: ContainerLike,
        claude_invocations: Callable[[], list[str]],
    ) -> None:
        """Session below min_turns → exit 0, no claude -p call."""
        self._setup_session(
            mock_claude_workspace,
            _build_manifest(min_turns=100),  # transcript has 10 turns
        )

        result = mock_claude_workspace.exec(
            f"cd /workspace && forge handoff run "
            f"--session-name {SESSION_NAME} "
            f"--worktree-path /workspace "
            f"--transcript-rel {TRANSCRIPT_REL}"
        )
        assert result.returncode == 0

        invocations = claude_invocations()
        assert not any("claude -p" in inv for inv in invocations)
