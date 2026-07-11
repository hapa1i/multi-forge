"""Best-effort tests with real Claude Code.

These tests actually run `claude --print "task"` inside the Docker container
to verify hook integration with real Claude Code. Requires ANTHROPIC_API_KEY.

IMPORTANT: These tests are best-effort supplementary tests:
- `claude --print` may not fire all hooks (design doc warns about UserPromptSubmit)
- Tests use NARROW assertions (field presence, not content)
- Don't rely on these for blocking CI - they're for release validation

Skip conditions:
- No ANTHROPIC_API_KEY env var set
- Docker not available

Cost considerations:
- Use minimal prompts (--print mode, simple tasks)
- Limited to essential hook verification tests

Placement: tests/integration/docker/ per testing_guidelines.md
Run: uv run pytest tests/integration/docker/test_real_claude_hooks.py -v -m slow
"""

from __future__ import annotations

import json
import os

import pytest

from tests.fixtures.docker import ContainerLike
from tests.integration.docker.conftest import run_claude_print, setup_real_claude

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


def _setup_real_claude(workspace: ContainerLike) -> None:
    """Delegate to shared helper (kept for backward compatibility within this file)."""
    setup_real_claude(workspace, session_name="real-claude-test")


def _run_claude_print(workspace: ContainerLike, prompt: str, timeout: int = 60) -> tuple[int, str, str]:
    """Delegate to shared helper (kept for backward compatibility within this file)."""
    return run_claude_print(workspace, prompt, session_name="real-claude-test", timeout=timeout)


class TestRealClaudeHooks:
    """Best-effort tests with real Claude Code.

    These verify hook firing but use NARROW assertions:
    - Don't assert on transcript content (non-deterministic)
    - Only assert on manifest field presence/updates
    - Accept that some hooks may not fire in --print mode
    """

    def test_migration_uses_user_dispatcher_after_project_cleanup(
        self,
        forge_workspace: ContainerLike,
    ) -> None:
        """A cleaned legacy root reaches real Claude hooks from user scope only."""

        legacy = {
            "hooks": {
                "SessionStart": [{"hooks": [{"type": "command", "command": "forge hook session-start"}]}],
                "Stop": [{"hooks": [{"type": "command", "command": "forge hook stop"}]}],
            }
        }
        forge_workspace.write_file("/workspace/.claude/settings.json", json.dumps(legacy))
        cleanup = forge_workspace.exec("cd /workspace && forge extension cleanup-project --yes")
        assert cleanup.returncode == 0, f"Migration failed: {cleanup.stderr}"

        scope_check = forge_workspace.exec("""
            /forge/.venv/bin/python - <<'PY'
import json
from pathlib import Path

project = json.loads(Path('/workspace/.claude/settings.json').read_text())
user = json.loads((Path.home() / '.claude' / 'settings.json').read_text())
assert 'hooks' not in project
assert user['hooks']['SessionStart']
assert user['hooks']['Stop']
PY
            """)
        assert scope_check.returncode == 0, f"Scope verification failed: {scope_check.stderr}"

        restored = forge_workspace.exec("""
            if [ -f /usr/local/bin/claude-real ]; then
                mv /usr/local/bin/claude-real /usr/local/bin/claude
            fi
            """)
        assert restored.returncode == 0, f"Failed to restore Claude: {restored.stderr}"
        session = forge_workspace.exec("cd /workspace && forge session start --no-launch real-claude-test")
        assert session.returncode == 0, f"Failed to create migrated session: {session.stderr}"

        _exit_code, stdout, _stderr = _run_claude_print(
            forge_workspace,
            prompt="Say just the word migrated",
            timeout=30,
        )

        manifest_result = forge_workspace.exec("cat /workspace/.forge/sessions/real-claude-test/forge.session.json")
        manifest = json.loads(manifest_result.stdout)
        confirmed = manifest.get("confirmed", {})
        assert (
            confirmed.get("claude_session_id") is not None
        ), f"Migrated SessionStart hook did not run. Claude output: {stdout[:500]}..."
        assert (
            confirmed.get("transcript_path") is not None
        ), f"Migrated Stop hook did not run. Claude output: {stdout[:500]}..."

    def test_session_start_hook_sets_session_id(self, forge_workspace: ContainerLike) -> None:
        """After claude --print, manifest should have claude_session_id set.

        Note: We don't assert the specific value, just that the hook ran.
        If SessionStart hook fires, it will update confirmed.claude_session_id.
        """
        _setup_real_claude(forge_workspace)

        # Read manifest before claude run
        before_result = forge_workspace.exec("cat /workspace/.forge/sessions/real-claude-test/forge.session.json")
        manifest_before = json.loads(before_result.stdout)
        session_id_before = manifest_before.get("confirmed", {}).get("claude_session_id")

        # Run claude --print with minimal prompt
        exit_code, stdout, stderr = _run_claude_print(
            forge_workspace,
            prompt="Say just the word hello",
            timeout=30,
        )

        # We don't assert on claude exit code - it might timeout or have other issues
        # What matters is whether the hook fired

        # Read manifest after claude run
        after_result = forge_workspace.exec("cat /workspace/.forge/sessions/real-claude-test/forge.session.json")
        manifest_after = json.loads(after_result.stdout)
        session_id_after = manifest_after.get("confirmed", {}).get("claude_session_id")

        # NARROW assertion: session_id should be set (hook ran)
        # We don't check if it changed - just that it's set
        assert session_id_after is not None, (
            f"SessionStart hook should set claude_session_id. "
            f"Before: {session_id_before}, After: {session_id_after}. "
            f"Claude output: {stdout[:500]}..."
        )

    def test_stop_hook_records_transcript_path(self, forge_workspace: ContainerLike) -> None:
        """After claude --print exits, manifest should have transcript_path.

        Note: We don't verify transcript content, just that Stop hook ran.
        If Stop hook fires, it will update confirmed.transcript_path.
        """
        _setup_real_claude(forge_workspace)

        # Read manifest before claude run
        before_result = forge_workspace.exec("cat /workspace/.forge/sessions/real-claude-test/forge.session.json")
        manifest_before = json.loads(before_result.stdout)
        transcript_before = manifest_before.get("confirmed", {}).get("transcript_path")

        # Run claude --print with minimal prompt
        exit_code, stdout, stderr = _run_claude_print(
            forge_workspace,
            prompt="Say just the word goodbye",
            timeout=30,
        )

        # Read manifest after claude run
        after_result = forge_workspace.exec("cat /workspace/.forge/sessions/real-claude-test/forge.session.json")
        manifest_after = json.loads(after_result.stdout)
        transcript_after = manifest_after.get("confirmed", {}).get("transcript_path")

        # NARROW assertion: transcript_path should be set (hook ran)
        # Note: This may fail if Stop hook doesn't fire in --print mode
        # That's expected - this is a best-effort test
        assert transcript_after is not None, (
            f"Stop hook should set transcript_path. "
            f"Before: {transcript_before}, After: {transcript_after}. "
            f"Claude output: {stdout[:500]}..."
        )
