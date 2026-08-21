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
import shlex
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

from tests.fixtures.docker import ContainerLike, DockerContainer

pytestmark = [pytest.mark.integration, pytest.mark.docker_in, pytest.mark.slow]

_ADVISORY_SESSION = "real-authority-advisory"
_PRODUCER_SESSION = "real-authority-producer"
_ADVISORY_SENTINEL = "/workspace/authority-advisory-sentinel.txt"
_PRODUCER_SENTINEL = "/workspace/authority-producer-sentinel.txt"
_CODEX_SESSION = "real-authority-codex"
_CODEX_SENTINEL = "/workspace/authority-codex-sentinel.txt"

# Capture the operator identity before the autouse test fixtures replace HOME,
# CODEX_HOME, and FORGE_HOME with isolated directories.
_REAL_HOME = Path.home()
_REAL_CODEX_HOME = Path(os.environ.get("CODEX_HOME") or _REAL_HOME / ".codex")
_REAL_FORGE_HOME = Path(os.environ.get("FORGE_HOME") or _REAL_HOME / ".forge")


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
    key_result = workspace.write_file("/tmp/.authority_anthropic_key", os.environ["ANTHROPIC_API_KEY"])
    assert key_result.returncode == 0, key_result.stderr
    prompt_result = workspace.write_file("/tmp/.authority_prompt", prompt)
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
    )
    assert wrapper_result.returncode == 0, wrapper_result.stderr
    prepared = workspace.exec("chmod 700 /tmp/authority-bin/claude /tmp/.authority_anthropic_key")
    assert prepared.returncode == 0, prepared.stderr


def _run_authority_launch(
    workspace: ContainerLike, *, session: str, role: str, prompt: str
) -> subprocess.CompletedProcess[str]:
    made_dir = workspace.exec("mkdir -p /tmp/authority-bin")
    assert made_dir.returncode == 0, made_dir.stderr
    _install_launch_wrapper(workspace, prompt)
    try:
        return workspace.exec(
            "export PATH=/tmp/authority-bin:$PATH"
            " && export ANTHROPIC_API_KEY=$(cat /tmp/.authority_anthropic_key)"
            f" && cd /workspace && timeout 120 forge session start {session} --authority {role}",
            timeout=135,
        )
    finally:
        workspace.exec("rm -rf /tmp/authority-bin /tmp/.authority_anthropic_key " "/tmp/.authority_prompt")


def _authority_events(workspace: ContainerLike, session: str) -> list[dict[str, Any]]:
    journal = workspace.read_file(f"/workspace/.forge/artifacts/{session}/authority/events.jsonl")
    return [json.loads(line) for line in journal.splitlines()]


def _event(events: list[dict[str, Any]], event_type: str) -> dict[str, Any]:
    matches = [event for event in events if event["event_type"] == event_type]
    assert len(matches) == 1, (event_type, events)
    return matches[0]


def _codex_identity_config() -> str:
    """Render the non-secret enrolled hook state at its original absolute path."""
    config_path = _REAL_CODEX_HOME / "config.toml"
    if not config_path.is_file():
        pytest.fail(
            f"real Codex authority E2E needs enrolled hook state at {config_path}. "
            "Enable user Codex hooks and complete the interactive trust ceremony."
        )
    try:
        parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        pytest.fail(f"cannot read real Codex hook enrollment state at {config_path}: {exc}")

    hooks = parsed.get("hooks")
    state = hooks.get("state") if isinstance(hooks, dict) else None
    if not isinstance(state, dict):
        pytest.fail(f"real Codex config at {config_path} has no [hooks.state] enrollment records")

    trusted: dict[str, str] = {}
    for event in ("session_start", "pre_tool_use"):
        key = f"{config_path}:{event}:0:0"
        entry = state.get(key)
        digest = entry.get("trusted_hash") if isinstance(entry, dict) else None
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            pytest.fail(
                f"real Codex config has no trusted {event} user-hook record for {config_path}. "
                "Run 'forge extension enable --scope user --runtime codex', open 'codex', "
                "and grant hook trust before re-running."
            )
        trusted[key] = digest

    lines = [
        "[features]",
        "hooks = true",
        "",
        f"[projects.{json.dumps('/workspace')}]",
        'trust_level = "trusted"',
    ]
    for key, digest in trusted.items():
        lines.extend(
            [
                "",
                f"[hooks.state.{json.dumps(key)}]",
                f"trusted_hash = {json.dumps(digest)}",
            ]
        )
    return "\n".join(lines) + "\n"


def _codex_exports() -> str:
    return " && ".join(
        [
            f"export HOME={shlex.quote(str(_REAL_HOME))}",
            f"export CODEX_HOME={shlex.quote(str(_REAL_CODEX_HOME))}",
            f"export FORGE_HOME={shlex.quote(str(_REAL_FORGE_HOME))}",
            "export FORGE_DEV=/forge",
        ]
    )


def _prepare_real_codex(workspace: DockerContainer) -> None:
    api_key = os.environ.get("CODEX_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        pytest.fail("real Codex authority E2E needs CODEX_API_KEY or OPENAI_API_KEY in the environment/.env")

    directories = workspace.exec(f"mkdir -p {shlex.quote(str(_REAL_CODEX_HOME))} {shlex.quote(str(_REAL_FORGE_HOME))}")
    assert directories.returncode == 0, directories.stderr
    config = workspace.write_file(str(_REAL_CODEX_HOME / "config.toml"), _codex_identity_config())
    assert config.returncode == 0, config.stderr
    key = workspace.write_file("/tmp/.authority_codex_key", api_key)
    assert key.returncode == 0, key.stderr
    protected = workspace.exec(
        f"chmod 700 {shlex.quote(str(_REAL_HOME))} {shlex.quote(str(_REAL_CODEX_HOME))} "
        f"{shlex.quote(str(_REAL_FORGE_HOME))} && chmod 600 /tmp/.authority_codex_key"
    )
    assert protected.returncode == 0, protected.stderr

    enabled = workspace.exec(
        f"{_codex_exports()} && cd /workspace && "
        "forge extension enable --scope user --profile minimal --with hooks --without commands --runtime codex",
        timeout=60,
    )
    assert enabled.returncode == 0, enabled.stderr


def _prepare_codex_parent(workspace: DockerContainer) -> None:
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
    created = workspace.exec(f"{_codex_exports()} && cd /workspace && forge session start planner --no-launch")
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
    updated = workspace.exec(f"{_codex_exports()} && /forge/.venv/bin/python /tmp/prepare-authority-parent.py")
    assert updated.returncode == 0, updated.stderr


@pytest.mark.usefixtures("_require_anthropic_api_key")
class TestRealClaudeAuthority:
    """Exercise real tool requests on both sides of the authority boundary."""

    def test_advisory_launch_denies_real_bash_request(self, forge_workspace: ContainerLike) -> None:
        _enable_user_hooks(forge_workspace)
        result = _run_authority_launch(
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
        assert forge_workspace.read_file("/tmp/authority_marker_state") == "present"
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
        assert {event["payload"]["covered_tool"] for event in denials} == {"Bash"}

    def test_producer_launch_allows_real_bash_request(self, forge_workspace: ContainerLike) -> None:
        _enable_user_hooks(forge_workspace)
        result = _run_authority_launch(
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
        assert forge_workspace.read_file("/tmp/authority_marker_state") == "absent"
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


class TestRealCodexAuthority:
    """Exercise a real enrolled Codex hook inside the disposable Docker identity."""

    def test_advisory_launch_denies_real_apply_patch_request(self, forge_workspace: ContainerLike) -> None:
        if not isinstance(forge_workspace, DockerContainer):
            pytest.fail("real Codex authority E2E requires host pytest to spawn its disposable Docker container")

        _prepare_real_codex(forge_workspace)
        _prepare_codex_parent(forge_workspace)
        try:
            result = forge_workspace.exec(
                f"{_codex_exports()}"
                " && export CODEX_API_KEY=$(cat /tmp/.authority_codex_key)"
                " && cd /workspace"
                f" && forge session start {_CODEX_SESSION} --runtime codex --resume-from planner"
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
