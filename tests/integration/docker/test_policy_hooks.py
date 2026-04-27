"""Docker-based tests for PolicyCheck and PreCompact hooks.

These tests verify hook behavior with complete filesystem and network isolation.
PolicyCheck tests TDD enforcement; PreCompact tests transcript capture before compaction.

Tests invoke `forge hook <name>` directly via container.exec() and verify:
- Exit codes (0 = allow, 2 = block for policy; 0 always for pre-compact)
- Manifest updates for policy and compaction state

Placement: tests/integration/docker/ per testing-guidelines.md
Run: uv run pytest tests/integration/docker/test_policy_hooks.py -v
"""

from __future__ import annotations

import json

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


# =============================================================================
# Helper Functions
# =============================================================================


def invoke_policy_check(
    workspace: ContainerLike,
    tool_name: str,
    file_path: str,
    content: str = "",
    session_name: str = "policy-test",
) -> tuple[int, str, str]:
    """Invoke forge hook policy-check and return (exit_code, stdout, stderr).

    Args:
        workspace: Container to execute in
        tool_name: "Write" or "Edit"
        file_path: Target file path (relative to /workspace)
        content: File content (for Write)
        session_name: Session name for FORGE_SESSION env var

    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": {
            "file_path": file_path,
            "content": content,
        },
    }
    payload_json = json.dumps(payload)
    # Use printf to avoid issues with special characters in content
    result = workspace.exec(
        f"cd /workspace && export FORGE_SESSION={session_name} && printf '%s' '{payload_json}' | forge hook policy-check"
    )
    return result.returncode, result.stdout, result.stderr


def invoke_precompact(
    workspace: ContainerLike,
    cwd: str = "/workspace",
    session_name: str = "precompact-test",
    session_id: str = "test-uuid-abc",
    transcript_path: str = "/tmp/test-transcript.jsonl",
) -> tuple[int, str, str]:
    """Invoke forge hook pre-compact and return (exit_code, stdout, stderr).

    Args:
        workspace: Container to execute in
        cwd: Working directory for the hook
        session_name: Session name for FORGE_SESSION env var
        session_id: Claude session UUID
        transcript_path: Path to transcript file

    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    payload = {
        "hook_event_name": "PreCompact",
        "session_id": session_id,
        "transcript_path": transcript_path,
        "cwd": cwd,
    }
    payload_json = json.dumps(payload)
    env_exports = f"export FORGE_SESSION={session_name}"
    result = workspace.exec(f"cd {cwd} && {env_exports} && printf '%s' '{payload_json}' | forge hook pre-compact")
    return result.returncode, result.stdout, result.stderr


def read_manifest(
    workspace: ContainerLike,
    path: str = "/workspace",
    session_name: str = "policy-test",
) -> dict:
    """Read and parse session manifest from container.

    Args:
        workspace: Container to execute in
        path: Base path containing .forge/sessions/<session_name>/forge.session.json
        session_name: Session name for per-session manifest path

    Returns:
        Parsed manifest dict
    """
    result = workspace.exec(f"cat {path}/.forge/sessions/{session_name}/forge.session.json")
    return json.loads(result.stdout)


# =============================================================================
# PolicyCheck Tests
# =============================================================================


class TestPolicyCheckDocker:
    """TDD policy enforcement tests with Docker isolation.

    These tests verify the hook adapter boundary - ensuring the hook correctly:
    - Parses PreToolUse events
    - Applies TDD policy rules
    - Returns appropriate exit codes
    - Updates manifest policy state
    """

    def test_blocks_impl_without_tests(self, policy_workspace: ContainerLike) -> None:
        """policy-check should block Write to src/ without prior test writes.

        Exit 2 + stderr contains 'tdd.tests-before-impl'
        """
        exit_code, stdout, stderr = invoke_policy_check(
            policy_workspace,
            tool_name="Write",
            file_path="src/foo.py",
            content="print('hello')",
        )

        assert exit_code == 2, f"Expected block (exit 2), got {exit_code}. stderr: {stderr}"
        assert "tdd.tests-before-impl" in stderr, f"Expected TDD rule ID in stderr, got: {stderr}"

    def test_allows_test_file_write(self, policy_workspace: ContainerLike) -> None:
        """policy-check should allow Write to tests/.

        Exit 0 + manifest.confirmed.policy.tests_touched updated
        """
        exit_code, stdout, stderr = invoke_policy_check(
            policy_workspace,
            tool_name="Write",
            file_path="tests/test_foo.py",
            content="def test_foo(): pass",
        )

        assert exit_code == 0, f"Expected allow (exit 0), got {exit_code}. stderr: {stderr}"

        # Verify manifest was updated (policy_states uses generic dict keyed by policy_id)
        manifest = read_manifest(policy_workspace)
        assert manifest["confirmed"]["policy"] is not None, "Policy state should be set"
        policy_states = manifest["confirmed"]["policy"].get("policy_states", {})
        tdd_state = policy_states.get("tdd.tests-before-impl", {})
        tests_touched = tdd_state.get("tests_touched", [])
        assert "tests/test_foo.py" in tests_touched, f"tests_touched should contain test file. Got: {tests_touched}"

    def test_allows_impl_after_test_write(self, policy_workspace: ContainerLike) -> None:
        """policy-check should allow impl Write after touching tests.

        Two-step: write test (exit 0), then write impl (exit 0)
        """
        # Step 1: Write test file
        exit_code1, _, stderr1 = invoke_policy_check(
            policy_workspace,
            tool_name="Write",
            file_path="tests/test_bar.py",
            content="def test_bar(): pass",
        )
        assert exit_code1 == 0, f"Test write should allow, got exit {exit_code1}. stderr: {stderr1}"

        # Step 2: Write impl file
        exit_code2, _, stderr2 = invoke_policy_check(
            policy_workspace,
            tool_name="Write",
            file_path="src/bar.py",
            content="print('bar')",
        )
        assert exit_code2 == 0, f"Impl write should allow after test, got exit {exit_code2}. stderr: {stderr2}"

    def test_fail_open_on_invalid_json(self, policy_workspace: ContainerLike) -> None:
        """policy-check should allow (fail-open) on invalid JSON input.

        Exit 0 + stdout empty (no JSON output)
        """
        result = policy_workspace.exec("cd /workspace && echo 'not valid json' | forge hook policy-check")

        assert result.returncode == 0, f"Invalid JSON should fail-open (exit 0), got {result.returncode}"
        assert result.stdout.strip() == "", f"Fail-open should produce no stdout, got: {result.stdout}"

    def test_fail_open_on_empty_stdin(self, policy_workspace: ContainerLike) -> None:
        """policy-check should allow (fail-open) on empty stdin.

        Exit 0 + stdout empty
        """
        result = policy_workspace.exec("cd /workspace && echo '' | forge hook policy-check")

        assert result.returncode == 0, f"Empty stdin should fail-open (exit 0), got {result.returncode}"
        assert result.stdout.strip() == "", f"Fail-open should produce no stdout, got: {result.stdout}"

    def test_fail_open_when_no_manifest(self, forge_workspace: ContainerLike) -> None:
        """policy-check should allow when no manifest exists.

        Exit 0 + skip action (no session created)
        """
        # Don't create a session - just invoke hook directly
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": "src/foo.py", "content": "x"},
        }
        payload_json = json.dumps(payload)
        result = forge_workspace.exec(f"cd /workspace && echo '{payload_json}' | forge hook policy-check")

        assert result.returncode == 0, f"No manifest should fail-open (exit 0), got {result.returncode}"
        # Hook outputs skip JSON when no session found (fail-open zone)
        if result.stdout.strip():
            output = json.loads(result.stdout)
            assert output.get("action") == "skip" or output.get("reason") == "no_session"


# =============================================================================
# PreCompact Tests
# =============================================================================


class TestPreCompactDocker:
    """Pre-compact transcript capture tests with Docker isolation.

    These tests verify the hook captures the full transcript before compaction
    and always exits 0 (never blocks). The old auto-compact blocking behavior
    was removed — CLAUDE_CODE_AUTO_COMPACT_WINDOW handles compaction window sizing.
    """

    def test_captures_transcript_and_updates_manifest(self, precompact_workspace: ContainerLike) -> None:
        """pre-compact should copy transcript to artifacts, update confirmed.compaction, and exit 0."""
        # Create a transcript file for the hook to capture
        precompact_workspace.exec("echo '{\"test\": true}' > /tmp/test-transcript.jsonl")

        exit_code, stdout, stderr = invoke_precompact(
            precompact_workspace,
            cwd="/workspace",
            session_id="test-uuid-abc",
            transcript_path="/tmp/test-transcript.jsonl",
        )

        assert exit_code == 0, f"pre-compact should always exit 0, got {exit_code}. stderr: {stderr}"

        # Verify transcript was copied to artifacts
        find_result = precompact_workspace.exec(
            "find /workspace/.forge/artifacts/precompact-test/transcripts -name '*pre-compact*' -type f"
        )
        assert find_result.stdout.strip(), "Expected pre-compact transcript snapshot in artifacts"

        # Verify confirmed.compaction was updated in the manifest
        manifest_result = precompact_workspace.exec("cat /workspace/.forge/sessions/precompact-test/forge.session.json")
        manifest = json.loads(manifest_result.stdout)
        compaction = manifest.get("confirmed", {}).get("compaction")
        assert compaction is not None, "Expected confirmed.compaction to be set"
        assert compaction.get("compact_count", 0) >= 1, "Expected compact_count >= 1"
        assert len(compaction.get("transcript_snapshots", [])) >= 1, "Expected at least one transcript snapshot"
        snapshot = compaction["transcript_snapshots"][0]
        assert snapshot["reason"] == "pre-compact"
        assert snapshot["copied"] is True

    def test_exits_0_when_no_manifest(self, forge_workspace: ContainerLike) -> None:
        """pre-compact should exit 0 when no session manifest exists (fail-open)."""
        payload = json.dumps(
            {
                "hook_event_name": "PreCompact",
                "session_id": "no-session",
                "transcript_path": "/tmp/t.jsonl",
                "cwd": "/workspace",
            }
        )
        result = forge_workspace.exec(f"cd /workspace && echo '{payload}' | forge hook pre-compact")

        assert result.returncode == 0, f"No manifest should fail-open (exit 0), got {result.returncode}"

    def test_exits_0_when_transcript_missing(self, precompact_workspace: ContainerLike) -> None:
        """pre-compact should exit 0 when transcript file doesn't exist (fail-open)."""
        exit_code, stdout, stderr = invoke_precompact(
            precompact_workspace,
            cwd="/workspace",
            session_id="test-uuid-abc",
            transcript_path="/nonexistent/transcript.jsonl",
        )

        assert exit_code == 0, f"Missing transcript should fail-open (exit 0), got {exit_code}. stderr: {stderr}"


# =============================================================================
# Pipeline Test
# =============================================================================


class TestPolicyPipeline:
    """Full policy hook pipeline verification."""

    def test_tdd_flow_with_manifest_verification(self, policy_workspace: ContainerLike) -> None:
        """Complete TDD flow: test file -> impl file -> verify manifest state.

        This test verifies the full policy state tracking across multiple hook
        invocations within a single session.
        """
        # Step 1: Write test file (should allow)
        exit_code1, _, stderr1 = invoke_policy_check(
            policy_workspace,
            tool_name="Write",
            file_path="tests/test_feature.py",
            content="def test_feature(): pass",
        )
        assert exit_code1 == 0, f"Step 1 failed: test write should allow, got {exit_code1}. stderr: {stderr1}"

        # Verify intermediate state (policy_states uses generic dict keyed by policy_id)
        manifest1 = read_manifest(policy_workspace)
        assert manifest1["confirmed"]["policy"] is not None, "Step 1: policy state should exist"
        policy_states1 = manifest1["confirmed"]["policy"].get("policy_states", {})
        tdd_state1 = policy_states1.get("tdd.tests-before-impl", {})
        tests_touched1 = tdd_state1.get("tests_touched", [])
        assert "tests/test_feature.py" in tests_touched1, "Step 1: tests_touched should contain test file"

        # Step 2: Write impl file (should allow after tests touched)
        exit_code2, _, stderr2 = invoke_policy_check(
            policy_workspace,
            tool_name="Write",
            file_path="src/feature.py",
            content="def feature(): return 42",
        )
        assert (
            exit_code2 == 0
        ), f"Step 2 failed: impl write should allow after test, got {exit_code2}. stderr: {stderr2}"

        # Verify final state - tests_touched should still have the test file
        manifest2 = read_manifest(policy_workspace)
        policy_states2 = manifest2["confirmed"]["policy"].get("policy_states", {})
        tdd_state2 = policy_states2.get("tdd.tests-before-impl", {})
        tests_touched2 = tdd_state2.get("tests_touched", [])
        assert "tests/test_feature.py" in tests_touched2, "Step 2: tests_touched should persist"
