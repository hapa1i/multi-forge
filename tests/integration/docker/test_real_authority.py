"""Real-runtime end-to-end validation for managed-session artifact authority.

These release smokes cross the production ``forge session start`` launch transaction,
real Dockerized Claude/Codex binaries, user-scoped hook dispatch, and the authority
journal. They intentionally do not construct markers or invoke hook commands in test
code.

Run via::

    ./scripts/test-integration.sh tests/integration/docker/test_real_authority.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

import pytest

from tests.fixtures.codex_enrollment import codex_exports, prepare_real_codex
from tests.fixtures.docker import ContainerLike, DockerContainer

pytestmark = [pytest.mark.integration, pytest.mark.docker_in, pytest.mark.slow]

_ADVISORY_SESSION = "real-authority-advisory"
_PRODUCER_SESSION = "real-authority-producer"
_ADVISORY_SENTINEL = "/workspace/authority-advisory-sentinel.txt"
_PRODUCER_SENTINEL = "/workspace/authority-producer-sentinel.txt"
_CODEX_SESSION = "real-authority-codex"
_CODEX_SENTINEL = "/workspace/authority-codex-sentinel.txt"


@pytest.fixture(scope="module")
def _require_anthropic_api_key() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.fail("ANTHROPIC_API_KEY not set. Add it to your environment/.env and re-run integration tests.")


def _enable_user_hooks(workspace: ContainerLike) -> None:
    result = workspace.exec(
        "cd /workspace && forge extension enable --scope user --profile standard --with hooks --without commands"
    )
    assert result.returncode == 0, result.stderr


def _install_launch_wrapper(workspace: ContainerLike, prompt: str) -> None:
    """Put a real-Claude passthrough first on PATH for one Forge launch.

    ``forge_workspace`` keeps the image's real binary at ``claude-real`` while its
    ordinary integration tests use a mock. The wrapper preserves Forge's argv and
    environment, adding only a bounded print-mode prompt and Bash allow-list. It
    records marker *presence*, never marker bytes.
    """
    key_result = workspace.write_file(
        "/tmp/.authority_anthropic_key",
        os.environ["ANTHROPIC_API_KEY"],
        mode=0o600,
    )
    assert key_result.returncode == 0, key_result.stderr
    prompt_result = workspace.write_file("/tmp/.authority_prompt", prompt, mode=0o600)
    assert prompt_result.returncode == 0, prompt_result.stderr
    wrapper_result = workspace.write_file(
        "/tmp/authority-bin/claude",
        """#!/bin/bash
set -euo pipefail
if [ -n "${FORGE_AUTHORITY_MARKER:-}" ]; then
    printf 'present' > /tmp/authority_marker_state
else
    printf 'absent' > /tmp/authority_marker_state
fi
if [ -x /usr/local/bin/claude-real ]; then
    upstream=/usr/local/bin/claude-real
elif [ -x /root/.local/bin/claude ]; then
    upstream=/root/.local/bin/claude
else
    echo "real Claude binary not found" >&2
    exit 127
fi
exec "$upstream" "$@" --print "$(cat /tmp/.authority_prompt)" --output-format json --allowedTools Bash
""",
        mode=0o700,
    )
    assert wrapper_result.returncode == 0, wrapper_result.stderr


def _run_authority_launch(
    workspace: ContainerLike, *, session: str, role: str, prompt: str
) -> tuple[subprocess.CompletedProcess[str], str | None]:
    made_dir = workspace.exec("mkdir -p /tmp/authority-bin && rm -f /tmp/authority_marker_state")
    assert made_dir.returncode == 0, made_dir.stderr
    _install_launch_wrapper(workspace, prompt)
    try:
        result = workspace.exec(
            "export PATH=/tmp/authority-bin:$PATH"
            " && export ANTHROPIC_API_KEY=$(cat /tmp/.authority_anthropic_key)"
            f" && cd /workspace && timeout 120 forge session start {session} --authority {role}",
            timeout=135,
        )
        marker_state = (
            workspace.read_file("/tmp/authority_marker_state")
            if workspace.file_exists("/tmp/authority_marker_state")
            else None
        )
        return result, marker_state
    finally:
        workspace.exec(
            "rm -rf /tmp/authority-bin /tmp/.authority_anthropic_key "
            "/tmp/.authority_prompt /tmp/authority_marker_state"
        )


def _authority_events(workspace: ContainerLike, session: str) -> list[dict[str, Any]]:
    journal = workspace.read_file(f"/workspace/.forge/artifacts/{session}/authority/events.jsonl")
    return [json.loads(line) for line in journal.splitlines()]


def _assert_committed_route(
    workspace: ContainerLike,
    *,
    session: str,
    expected_kind: str,
    expected_run_id: str,
) -> None:
    journal = workspace.read_file(f"/workspace/.forge/artifacts/{session}/routing/events.jsonl")
    events = [json.loads(line) for line in journal.splitlines()]
    assert len(events) == 1, events
    event = events[0]
    assert event["event_type"] == "launch_routing_committed"
    assert event["operation"] == "start"
    assert event["payload"]["route"]["kind"] == expected_kind
    assert event["run_id"] == expected_run_id

    manifest = json.loads(workspace.read_file(f"/workspace/.forge/sessions/{session}/forge.session.json"))
    assert manifest["confirmed"]["route_commit"] == {
        "event_id": event["event_id"],
        "run_id": expected_run_id,
    }


def _event(events: list[dict[str, Any]], event_type: str) -> dict[str, Any]:
    matches = [event for event in events if event["event_type"] == event_type]
    assert len(matches) == 1, (event_type, events)
    return matches[0]


def _prepare_codex_parent(workspace: DockerContainer) -> None:
    """Seed an existing transcript so the E2E does not pay for unrelated transfer curation."""
    transcript = "\n".join(
        [
            json.dumps(
                {
                    "requestId": "authority-parent",
                    "timestamp": "2026-08-22T00:00:00Z",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": "Plan a sentinel."}],
                    },
                }
            ),
            json.dumps(
                {
                    "requestId": "authority-parent",
                    "timestamp": "2026-08-22T00:00:01Z",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Use one apply_patch call."}],
                    },
                }
            ),
        ]
    )
    written = workspace.write_file("/workspace/authority-parent.jsonl", transcript)
    assert written.returncode == 0, written.stderr
    created = workspace.exec(f"{codex_exports()} && cd /workspace && forge session start planner --no-launch")
    assert created.returncode == 0, created.stderr
    setup_script = """from forge.session.manager import SessionManager

manager = SessionManager()
store = manager.get_session_store("planner", forge_root="/workspace")
store.update(
    timeout_s=5.0,
    mutate=lambda state: setattr(state.confirmed, "transcript_path", "/workspace/authority-parent.jsonl"),
)
"""
    script = workspace.write_file("/tmp/prepare-authority-parent.py", setup_script)
    assert script.returncode == 0, script.stderr
    updated = workspace.exec(f"{codex_exports()} && /forge/.venv/bin/python /tmp/prepare-authority-parent.py")
    assert updated.returncode == 0, updated.stderr


@pytest.mark.usefixtures("_require_anthropic_api_key")
class TestRealClaudeAuthority:
    """Exercise real tool requests on both sides of the authority boundary."""

    def test_advisory_launch_denies_real_bash_request(self, forge_workspace: ContainerLike) -> None:
        _enable_user_hooks(forge_workspace)
        result, marker_state = _run_authority_launch(
            forge_workspace,
            session=_ADVISORY_SESSION,
            role="advisory",
            prompt=(
                "Use the Bash tool exactly once to run: "
                "printf 'authority-advisory-was-written' > authority-advisory-sentinel.txt. "
                "You must request the tool rather than describing the command. After its result, reply briefly."
            ),
        )

        assert result.returncode == 0, f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        assert marker_state == "present"
        assert not forge_workspace.file_exists("/tmp/authority_marker_state")
        assert not forge_workspace.file_exists(_ADVISORY_SENTINEL)

        events = _authority_events(forge_workspace, _ADVISORY_SESSION)
        event_types = [event["event_type"] for event in events]
        assert event_types[0:3] == [
            "authority_configured",
            "launch_preflight",
            "run_started",
        ]
        assert event_types[-1] == "run_ended"
        denials = [event for event in events if event["event_type"] == "request_denied"]
        assert denials, events

        run_id = _event(events, "run_started")["run_id"]
        assert run_id is not None
        assert _event(events, "launch_preflight")["run_id"] == run_id
        assert _event(events, "run_ended")["run_id"] == run_id
        assert all(event["run_id"] == run_id for event in denials)
        assert "Bash" in {event["payload"]["covered_tool"] for event in denials}
        _assert_committed_route(
            forge_workspace,
            session=_ADVISORY_SESSION,
            expected_kind="direct",
            expected_run_id=run_id,
        )

    def test_producer_launch_allows_real_bash_request(self, forge_workspace: ContainerLike) -> None:
        _enable_user_hooks(forge_workspace)
        result, marker_state = _run_authority_launch(
            forge_workspace,
            session=_PRODUCER_SESSION,
            role="producer",
            prompt=(
                "Use the Bash tool exactly once to run: "
                "printf 'authority-producer-was-written' > authority-producer-sentinel.txt. "
                "You must execute the tool rather than describing the command. After its result, reply briefly."
            ),
        )

        assert result.returncode == 0, f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        assert marker_state == "absent"
        assert not forge_workspace.file_exists("/tmp/authority_marker_state")
        assert forge_workspace.read_file(_PRODUCER_SENTINEL) == "authority-producer-was-written"

        events = _authority_events(forge_workspace, _PRODUCER_SESSION)
        assert [event["event_type"] for event in events] == [
            "authority_configured",
            "launch_preflight",
            "run_started",
            "run_ended",
        ]
        run_id = _event(events, "run_started")["run_id"]
        assert run_id is not None
        assert _event(events, "launch_preflight")["run_id"] == run_id
        assert _event(events, "run_ended")["run_id"] == run_id
        _assert_committed_route(
            forge_workspace,
            session=_PRODUCER_SESSION,
            expected_kind="direct",
            expected_run_id=run_id,
        )


class TestRealCodexAuthority:
    """Exercise a real enrolled Codex hook inside the disposable Docker identity."""

    def test_advisory_launch_denies_real_apply_patch_request(self, forge_workspace: ContainerLike) -> None:
        if not isinstance(forge_workspace, DockerContainer):
            pytest.fail("real Codex authority E2E requires host pytest to spawn its disposable Docker container")

        prepare_real_codex(forge_workspace)
        _prepare_codex_parent(forge_workspace)
        try:
            result = forge_workspace.exec(
                f"{codex_exports()}"
                " && export CODEX_API_KEY=$(cat /tmp/.authority_codex_key)"
                " && cd /workspace"
                f" && timeout --kill-after=10s 280s forge session start {_CODEX_SESSION}"
                " --runtime codex --resume-from planner"
                " --strategy structured --sandbox workspace-write --authority advisory"
                ' --task "Use apply_patch exactly once to add authority-codex-sentinel.txt containing '
                "authority-codex-was-written. Do not use shell redirection. You must request apply_patch; "
                'after its result, reply briefly."',
                timeout=300,
            )
        finally:
            forge_workspace.exec("rm -f /tmp/.authority_codex_key /tmp/prepare-authority-parent.py")

        assert result.returncode == 0, f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        assert not forge_workspace.file_exists(_CODEX_SENTINEL)

        events = _authority_events(forge_workspace, _CODEX_SESSION)
        event_types = [event["event_type"] for event in events]
        assert event_types[0:3] == [
            "authority_configured",
            "launch_preflight",
            "run_started",
        ]
        assert event_types[-1] == "run_ended"
        denials = [event for event in events if event["event_type"] == "request_denied"]
        assert denials, events

        run_id = _event(events, "run_started")["run_id"]
        assert run_id is not None
        assert _event(events, "launch_preflight")["run_id"] == run_id
        assert _event(events, "run_ended")["run_id"] == run_id
        assert all(event["run_id"] == run_id for event in denials)
        assert "apply_patch" in {event["payload"]["covered_tool"] for event in denials}
        _assert_committed_route(
            forge_workspace,
            session=_CODEX_SESSION,
            expected_kind="runtime_native",
            expected_run_id=run_id,
        )
