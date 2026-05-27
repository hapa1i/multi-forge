"""Best-effort real-Claude memory smoke tests.

These tests exercise the new memory/passport flows through real ``claude -p``
inside Docker. Assertions stay deliberately narrow: they verify subprocess
success, report persistence, and no unwanted official-doc mutation, not exact
LLM prose.
"""

from __future__ import annotations

import json
import os

import pytest

from tests.fixtures.docker import ContainerLike
from tests.integration.docker.conftest import setup_real_claude

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_in,
    pytest.mark.slow,
]


@pytest.fixture(scope="module", autouse=True)
def _require_anthropic_api_key() -> None:
    """Fail loudly if API key is missing (never skip tests policy)."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.fail("ANTHROPIC_API_KEY not set. Add it to your environment/.env and re-run integration tests.")


def _write_api_key_file(workspace: ContainerLike) -> None:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    result = workspace.exec(f"cat > /tmp/.anthropic_key << 'KEY_EOF'\n{api_key}\nKEY_EOF")
    if result.returncode != 0:
        pytest.fail(f"Failed to write API key: {result.stderr}")


def _run_with_anthropic_key(
    workspace: ContainerLike,
    command: str,
    *,
    timeout: int = 180,
) -> tuple[int, str, str]:
    """Run a command with ANTHROPIC_API_KEY sourced from a temp file."""
    _write_api_key_file(workspace)
    try:
        result = workspace.exec(
            f"export ANTHROPIC_API_KEY=$(cat /tmp/.anthropic_key) && {command}",
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    finally:
        workspace.exec("rm -f /tmp/.anthropic_key")


def _write_transcript(workspace: ContainerLike, rel_path: str) -> None:
    transcript = "\n".join(
        [
            json.dumps(
                {
                    "requestId": "memory-1",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": "We fixed flaky memory documentation setup."}],
                    },
                }
            ),
            json.dumps(
                {
                    "requestId": "memory-1",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "The fix was to use forge memory track idempotently."}],
                    },
                }
            ),
            json.dumps(
                {
                    "requestId": "memory-2",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": "Please capture that for future sessions."}],
                    },
                }
            ),
        ]
    )
    workspace.exec(f"mkdir -p /workspace/$(dirname {rel_path})")
    workspace.write_file(f"/workspace/{rel_path}", transcript + "\n")


class TestRealClaudeMemory:
    """Release-validation smoke tests for memory flows that spawn real Claude."""

    def test_real_handoff_review_only_smoke(self, forge_workspace: ContainerLike) -> None:
        session_name = "real-memory-handoff"
        transcript_rel = f".forge/artifacts/{session_name}/transcripts/real-memory.jsonl"
        setup_real_claude(forge_workspace, session_name=session_name)

        forge_workspace.exec("mkdir -p /workspace/docs")
        forge_workspace.write_file(
            "/workspace/docs/state.md",
            "# State\n\nExisting notes stay untouched during review-only.\n",
        )
        _write_transcript(forge_workspace, transcript_rel)

        for command in (
            "cd /workspace && forge memory track docs/state.md --as project-state",
            f"cd /workspace && forge memory enable --review-only --session {session_name}",
            f"cd /workspace && forge session set --session {session_name} memory.auto_update.min_turns 1",
        ):
            result = forge_workspace.exec(command)
            assert result.returncode == 0, result.stderr

        official_before = forge_workspace.read_file("/workspace/docs/state.md")

        exit_code, stdout, stderr = _run_with_anthropic_key(
            forge_workspace,
            "cd /workspace && forge handoff run "
            f"--session-name {session_name} "
            "--worktree-path /workspace "
            f"--transcript-rel {transcript_rel} "
            "--timeout 120",
            timeout=150,
        )
        assert exit_code == 0, f"stdout={stdout[:500]!r}\nstderr={stderr[:500]!r}"

        official_after = forge_workspace.read_file("/workspace/docs/state.md")
        assert official_after == official_before

        report_result = forge_workspace.exec(
            f"ls -1 /workspace/.forge/artifacts/{session_name}/handoff/review-*.md | tail -n 1"
        )
        assert report_result.returncode == 0, report_result.stderr
        report_path = report_result.stdout.strip()
        assert report_path
        report = forge_workspace.read_file(report_path)
        assert f"# Handoff Agent Report -- {session_name}" in report
        assert "**Mode**: review-only" in report

        show_result = forge_workspace.exec(f"cd /workspace && forge session handoff show {session_name} --latest")
        assert show_result.returncode == 0, show_result.stderr
        assert "Handoff Agent Report" in show_result.stdout

    def test_real_shadow_curation_smoke(self, forge_workspace: ContainerLike) -> None:
        session_name = "real-memory-curation"
        official_path = "docs/official.md"
        shadow_path = ".forge/memory/suggested_official.md"
        setup_real_claude(forge_workspace, session_name=session_name)

        forge_workspace.exec("mkdir -p /workspace/docs")
        forge_workspace.write_file(
            f"/workspace/{official_path}",
            "# Official Notes\n\n- Existing standard: keep docs concise.\n",
        )

        track_result = forge_workspace.exec(
            "cd /workspace && forge memory track "
            f"{official_path} --propose --shadow {shadow_path} --session {session_name}"
        )
        assert track_result.returncode == 0, track_result.stderr

        forge_workspace.write_file(
            f"/workspace/{shadow_path}",
            "- [ ] Add that memory setup should prefer `forge memory track` over raw JSON "
            "(source: integration smoke)\n",
        )
        official_before = forge_workspace.read_file(f"/workspace/{official_path}")

        exit_code, stdout, stderr = _run_with_anthropic_key(
            forge_workspace,
            "cd /workspace && forge memory shadows review "
            f"--for {official_path} --curate --json --session {session_name}",
            timeout=180,
        )
        assert exit_code == 0, f"stdout={stdout[:500]!r}\nstderr={stderr[:500]!r}"

        payload = json.loads(stdout)
        assert payload["success"] is True
        assert payload["official"] == official_path
        assert payload["shadow_count"] == 1
        assert payload["report_path"]
        assert forge_workspace.file_exists(payload["report_path"])

        official_after = forge_workspace.read_file(f"/workspace/{official_path}")
        assert official_after == official_before

        report = forge_workspace.read_file(payload["report_path"])
        assert f"# Shadow Curation Report -- {session_name}" in report
        assert f"**Official doc**: {official_path}" in report
