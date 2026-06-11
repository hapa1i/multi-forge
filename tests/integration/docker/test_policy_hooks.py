"""Docker-based tests for PolicyCheck, CodexPolicyCheck, and PreCompact hooks.

These tests verify hook behavior with complete filesystem and network isolation.
PolicyCheck tests TDD enforcement (Claude wire: exit 2 blocks); CodexPolicyCheck
tests the same enforcement on the Codex wire (stdout deny JSON, always exit 0);
PreCompact tests transcript capture before compaction.

Tests invoke `forge hook <name>` directly via container.exec() and verify:
- Exit codes (0 = allow, 2 = block for Claude policy; 0 always for Codex + pre-compact)
- Wire output (Codex deny JSON on stdout)
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


def invoke_codex_policy_check(
    workspace: ContainerLike,
    patch_command: str,
    session_name: str = "policy-test",
    tool_name: str = "apply_patch",
) -> tuple[int, str, str]:
    """Invoke forge hook codex-policy-check and return (exit_code, stdout, stderr).

    Payload shape pinned by tests/fixtures/codex/hooks/pre_tool_use.stdin.json
    (codex-cli 0.138.0, snake_case). Codex deny rides in stdout JSON with exit 0.
    """
    payload = {
        "session_id": "019eb075-fd3f-7381-9008-9ef8df491237",
        "transcript_path": "/tmp/rollout.jsonl",
        "cwd": "/workspace",
        "hook_event_name": "PreToolUse",
        "model": "gpt-5.5",
        "permission_mode": "bypassPermissions",
        "turn_id": "019eb075-fd77-7992-b35d-73a30bfe9614",
        "tool_name": tool_name,
        "tool_input": {"command": patch_command},
        "tool_use_id": "call_docker_test",
    }
    payload_json = json.dumps(payload)
    result = workspace.exec(
        f"cd /workspace && export FORGE_SESSION={session_name}"
        f" && printf '%s' '{payload_json}' | forge hook codex-policy-check"
    )
    return result.returncode, result.stdout, result.stderr


def _codex_patch(*sections: str) -> str:
    return "*** Begin Patch\n" + "\n".join(sections) + "\n*** End Patch"


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
# CodexPolicyCheck Tests
# =============================================================================


class TestCodexPolicyCheckDocker:
    """TDD enforcement on the Codex wire (codex-policy-check) with Docker isolation.

    Same policy engine as TestPolicyCheckDocker, different wire contract:
    a block is a strict ``hookSpecificOutput`` deny JSON on stdout with exit 0
    (Codex fails OPEN on malformed hook output -- exit codes don't carry the deny).
    """

    def test_blocks_impl_without_tests_via_stdout_deny_json(self, policy_workspace: ContainerLike) -> None:
        """Add File to src/ without tests -> exit 0 + stdout deny JSON (not exit 2)."""
        exit_code, stdout, stderr = invoke_codex_policy_check(
            policy_workspace,
            _codex_patch("*** Add File: src/foo.py", "+print(1)"),
        )

        assert exit_code == 0, f"Codex deny must exit 0, got {exit_code}. stderr: {stderr}"
        wire = json.loads(stdout)
        assert set(wire.keys()) == {"hookSpecificOutput"}, f"stdout must be strict wire JSON, got: {stdout}"
        out = wire["hookSpecificOutput"]
        assert out["permissionDecision"] == "deny"
        assert "tdd.tests-before-impl" in out["permissionDecisionReason"]

    def test_allows_test_file_add_with_empty_stdout(self, policy_workspace: ContainerLike) -> None:
        """Add File to tests/ -> exit 0, NO stdout, manifest state updated."""
        exit_code, stdout, stderr = invoke_codex_policy_check(
            policy_workspace,
            _codex_patch("*** Add File: tests/test_foo.py", "+def test_foo(): pass"),
        )

        assert exit_code == 0, f"Expected allow, got {exit_code}. stderr: {stderr}"
        assert stdout.strip() == "", f"Allow must emit no stdout, got: {stdout}"

        manifest = read_manifest(policy_workspace)
        assert manifest["confirmed"]["policy"] is not None
        assert manifest["confirmed"]["confirmed_by"] == "hook:codex-policy-check"
        tdd_state = manifest["confirmed"]["policy"].get("policy_states", {}).get("tdd.tests-before-impl", {})
        assert "tests/test_foo.py" in tdd_state.get("tests_touched", [])

    def test_allows_impl_after_test_add_across_invocations(self, policy_workspace: ContainerLike) -> None:
        """State persists through the manifest between hook invocations."""
        exit_code1, _, stderr1 = invoke_codex_policy_check(
            policy_workspace,
            _codex_patch("*** Add File: tests/test_bar.py", "+def test_bar(): pass"),
        )
        assert exit_code1 == 0, f"Test add should allow, got {exit_code1}. stderr: {stderr1}"

        exit_code2, stdout2, stderr2 = invoke_codex_policy_check(
            policy_workspace,
            _codex_patch("*** Add File: src/bar.py", "+print(2)"),
        )
        assert exit_code2 == 0, f"Impl after test should allow, got {exit_code2}. stderr: {stderr2}"
        assert stdout2.strip() == "", f"Allow must emit no stdout, got: {stdout2}"

    def test_decision_log_records_per_file_apply_patch_summaries(self, policy_workspace: ContainerLike) -> None:
        """A multi-file patch persists one decision-log entry per file op."""
        exit_code, stdout, _ = invoke_codex_policy_check(
            policy_workspace,
            _codex_patch(
                "*** Add File: tests/test_multi.py",
                "+def test_multi(): pass",
                "*** Add File: src/multi.py",
                "+print(3)",
            ),
        )
        assert exit_code == 0
        assert stdout.strip() == ""

        manifest = read_manifest(policy_workspace)
        summaries = [e["context_summary"] for e in manifest["confirmed"]["policy"]["decisions"]]
        assert "apply_patch:tests/test_multi.py" in summaries
        assert "apply_patch:src/multi.py" in summaries

    def test_fail_open_on_invalid_json(self, policy_workspace: ContainerLike) -> None:
        result = policy_workspace.exec("cd /workspace && echo 'not valid json' | forge hook codex-policy-check")

        assert result.returncode == 0, f"Invalid JSON should fail-open (exit 0), got {result.returncode}"
        assert result.stdout.strip() == "", f"Fail-open should produce no stdout, got: {result.stdout}"

    def test_fail_open_when_no_manifest(self, forge_workspace: ContainerLike) -> None:
        """No session -> exit 0, empty stdout (stderr-only note)."""
        payload = json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {"command": "*** Begin Patch\n*** Add File: src/x.py\n+1\n*** End Patch"},
                "cwd": "/workspace",
            }
        )
        result = forge_workspace.exec(f"cd /workspace && printf '%s' '{payload}' | forge hook codex-policy-check")

        assert result.returncode == 0, f"No manifest should fail-open (exit 0), got {result.returncode}"
        assert result.stdout.strip() == "", f"Fail-open should produce no stdout, got: {result.stdout}"

    def test_bash_tool_passes_through(self, policy_workspace: ContainerLike) -> None:
        """Bash actions are not policy-evaluated (parity with Claude skipping non-Write/Edit)."""
        exit_code, stdout, _ = invoke_codex_policy_check(
            policy_workspace,
            "echo hi",
            tool_name="Bash",
        )

        assert exit_code == 0
        assert stdout.strip() == ""


# =============================================================================
# Codex SessionStart Transfer Delivery Tests
# =============================================================================

_CODEX_THREAD_ID = "019eb075-ef05-7702-9045-0a8a88b512d2"
_CODEX_ROLLOUT = f"/root/.codex/sessions/2026/06/10/rollout-2026-06-10T03-36-19-{_CODEX_THREAD_ID}.jsonl"
_PENDING_PATH = "/workspace/.forge/sessions/policy-test/codex/pending-context.md"
_RECEIPT_PATH = "/workspace/.forge/sessions/policy-test/codex/context-receipt.json"


def invoke_codex_session_start(
    workspace: ContainerLike,
    session_name: str = "policy-test",
) -> tuple[int, str, str]:
    """Invoke forge hook codex-session-start with a fixture-shaped SessionStart payload.

    Payload shape pinned by tests/fixtures/codex/hooks/session_start.stdin.json
    (codex-cli 0.138.0, snake_case).
    """
    payload = {
        "session_id": _CODEX_THREAD_ID,
        "transcript_path": _CODEX_ROLLOUT,
        "cwd": "/workspace",
        "hook_event_name": "SessionStart",
        "model": "gpt-5.5",
        "permission_mode": "bypassPermissions",
        "source": "startup",
    }
    payload_json = json.dumps(payload)
    result = workspace.exec(
        f"cd /workspace && export FORGE_SESSION={session_name}"
        f" && printf '%s' '{payload_json}' | forge hook codex-session-start"
    )
    return result.returncode, result.stdout, result.stderr


class TestCodexSessionStartDocker:
    """SessionStart transfer delivery (codex-session-start) with Docker isolation.

    Delivery: staged file -> strict additionalContext wire JSON on stdout + a receipt
    the CLI reconciles. Every non-delivery path is a silent no-op (exit 0, no output:
    a user-scope registration fires for every Codex session, so unrelated sessions
    must see no Forge stderr noise) -- Codex fails OPEN on malformed hook output.
    """

    def test_staged_context_delivered_with_receipt(self, policy_workspace: ContainerLike) -> None:
        body = "# Handoff context (curated transfer from a prior planning session)\n\nCURATED-BODY"
        policy_workspace.mkdir("/workspace/.forge/sessions/policy-test/codex", parents=True)
        policy_workspace.write_file(_PENDING_PATH, body)
        assert policy_workspace.file_exists(_PENDING_PATH), "staging precondition failed"

        exit_code, stdout, stderr = invoke_codex_session_start(policy_workspace)

        assert exit_code == 0, f"Delivery must exit 0, got {exit_code}. stderr: {stderr}"
        wire = json.loads(stdout)
        assert set(wire.keys()) == {"hookSpecificOutput"}, f"stdout must be strict wire JSON, got: {stdout}"
        out = wire["hookSpecificOutput"]
        assert set(out.keys()) == {"hookEventName", "additionalContext"}
        assert out["hookEventName"] == "SessionStart"
        assert out["additionalContext"].strip() == body.strip()

        # Staged file consumed; receipt carries the payload's thread identity.
        assert not policy_workspace.file_exists(_PENDING_PATH)
        receipt = policy_workspace.read_json(_RECEIPT_PATH)
        assert receipt["session_id"] == _CODEX_THREAD_ID
        assert receipt["transcript_path"] == _CODEX_ROLLOUT
        assert receipt["source"] == "startup"

    def test_nothing_staged_is_silent(self, policy_workspace: ContainerLike) -> None:
        """The resume-turn case: no staged file -> exit 0, no stdout, no receipt."""
        exit_code, stdout, stderr = invoke_codex_session_start(policy_workspace)

        assert exit_code == 0
        assert stdout.strip() == ""
        assert "[forge]" not in stderr, f"silent no-op must not emit Forge stderr noise, got: {stderr}"
        assert not policy_workspace.file_exists(_RECEIPT_PATH)

    def test_non_forge_session_is_silent(self, policy_workspace: ContainerLike) -> None:
        """Regression: the user-scope case. A Codex session with no FORGE_SESSION in
        its env (any non-Forge Codex start) must be a silent no-op -- no stdout and
        no Forge stderr noise."""
        payload = json.dumps(
            {
                "session_id": _CODEX_THREAD_ID,
                "transcript_path": _CODEX_ROLLOUT,
                "cwd": "/workspace",
                "hook_event_name": "SessionStart",
                "model": "gpt-5.5",
                "permission_mode": "bypassPermissions",
                "source": "startup",
            }
        )
        result = policy_workspace.exec(
            f"cd /workspace && unset FORGE_SESSION FORGE_FORK_NAME"
            f" && printf '%s' '{payload}' | forge hook codex-session-start"
        )

        assert result.returncode == 0
        assert result.stdout.strip() == ""
        assert "[forge]" not in result.stderr, f"non-Forge session must see no Forge noise, got: {result.stderr}"

    def test_fail_open_on_invalid_json(self, policy_workspace: ContainerLike) -> None:
        result = policy_workspace.exec("cd /workspace && echo 'not valid json' | forge hook codex-session-start")

        assert result.returncode == 0, f"Invalid JSON should fail-open (exit 0), got {result.returncode}"
        assert result.stdout.strip() == "", f"Fail-open should produce no stdout, got: {result.stdout}"


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
