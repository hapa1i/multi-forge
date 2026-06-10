"""Deterministic supervisor E2E tests in Docker.

Exercises the on-demand supervisor CLI against a harnessed ``claude -p --resume``
path so the suite can deterministically cover:
- aligned plan checks (exit 0)
- divergent plan checks (exit 1)
- supervisor infrastructure failures (exit 2)

This file intentionally does not use real LLM calls. Real Claude worker coverage
for ``claude -p --bare`` lives in a separate slow test.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_in,
]

SUPERVISOR_RESUME_ID = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def supervisor_workspace(forge_workspace: ContainerLike) -> ContainerLike:
    """Install a deterministic claude -p --resume harness on top of the mock binary."""
    # forge_workspace already points /usr/local/bin/claude at claude-mock, so
    # replace the mock target in place to keep the existing symlink wiring.
    result = forge_workspace.exec(
        """
        cat > /usr/local/bin/claude-mock << 'SCRIPT'
#!/bin/bash
set -euo pipefail

if [ "${1:-}" = "--version" ]; then
    echo "99.99.99 (Claude Code)"
    exit 0
fi

echo "$(date -Iseconds) claude $*" >> /tmp/claude_invocations.log

has_print=false
has_resume=false
for arg in "$@"; do
    if [ "$arg" = "-p" ]; then
        has_print=true
    fi
    if [ "$arg" = "--resume" ]; then
        has_resume=true
    fi
done

if [ "$has_print" = true ] && [ "$has_resume" = true ]; then
    case "${FORGE_TEST_SUPERVISOR_MODE:-aligned}" in
        aligned)
            cat << 'EOF'
```json
{"verdict":"aligned","confidence":0.97,"violations":[]}
```
EOF
            exit 0
            ;;
        divergent)
            cat << 'EOF'
```json
{"verdict":"divergent","confidence":0.99,"violations":[{"severity":"high","evidence":"Edited src/demo.py outside the approved plan","suggested_fix":"Restore src/demo.py to the planned implementation","citations":["Plan: create src/demo.py with greet(name) only"]}]}
```
EOF
            exit 0
            ;;
        infra_error)
            echo "simulated resume failure" >&2
            exit 2
            ;;
        *)
            echo "unknown FORGE_TEST_SUPERVISOR_MODE=${FORGE_TEST_SUPERVISOR_MODE:-}" >&2
            exit 3
            ;;
    esac
fi

echo "unexpected claude invocation in supervisor harness: $*" >&2
exit 4
SCRIPT
        chmod +x /usr/local/bin/claude-mock
        mkdir -p /workspace/src
        cat > /workspace/src/demo.py << 'PY'
def greet(name: str) -> str:
    return f"hello, {name}"
PY
        > /tmp/claude_invocations.log
        """,
    )
    if result.returncode != 0:
        pytest.fail(f"Failed to install supervisor harness: {result.stderr}")

    return forge_workspace


def _run_supervisor_check(workspace: ContainerLike, *, mode: str) -> tuple[int, dict[str, Any], str]:
    """Run ``forge policy supervisor`` through the deterministic resume harness."""
    result = workspace.exec(
        f"cd /workspace && FORGE_TEST_SUPERVISOR_MODE={mode} "
        f"forge policy supervisor -f src/demo.py -r {SUPERVISOR_RESUME_ID} --json"
    )
    invocations = workspace.read_file("/tmp/claude_invocations.log")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(
            "Supervisor CLI did not emit parseable JSON.\n"
            f"exit_code={result.returncode}\n"
            f"stdout={result.stdout!r}\n"
            f"stderr={result.stderr!r}\n"
            f"invocations={invocations!r}\n"
            f"json_error={exc}"
        )

    if not isinstance(payload, dict):
        pytest.fail(
            "Supervisor CLI emitted JSON, but not the expected object payload.\n"
            f"exit_code={result.returncode}\n"
            f"stdout={result.stdout!r}\n"
            f"stderr={result.stderr!r}\n"
            f"invocations={invocations!r}"
        )

    return result.returncode, payload, invocations


class TestSupervisorE2E:
    """Deterministic supervisor coverage for aligned, divergent, and infra-error paths."""

    def test_resume_harness_allows_aligned_action(self, supervisor_workspace: ContainerLike) -> None:
        exit_code, output, invocations = _run_supervisor_check(supervisor_workspace, mode="aligned")

        assert exit_code == 0
        assert output["passed"] is True
        assert output["clean"] is True
        assert output["final_decision"] == "allow"
        assert output["warnings"] == []
        assert f"--resume {SUPERVISOR_RESUME_ID}" in invocations

    def test_resume_harness_denies_divergent_action(self, supervisor_workspace: ContainerLike) -> None:
        exit_code, output, invocations = _run_supervisor_check(supervisor_workspace, mode="divergent")

        assert exit_code == 1
        assert output["passed"] is False
        assert output["final_decision"] == "deny"
        assert len(output["violations"]) == 1
        assert f"--resume {SUPERVISOR_RESUME_ID}" in invocations

    def test_resume_harness_reports_infra_error(self, supervisor_workspace: ContainerLike) -> None:
        exit_code, output, invocations = _run_supervisor_check(supervisor_workspace, mode="infra_error")

        assert exit_code == 2
        assert output["passed"] is False
        assert output["clean"] is False
        assert output["final_decision"] == "error"
        assert any(str(w).startswith("Supervisor error:") for w in output["warnings"])
        assert f"--resume {SUPERVISOR_RESUME_ID}" in invocations

    def test_session_set_wires_supervisor_config(self, supervisor_workspace: ContainerLike) -> None:
        """``forge session set policy.supervisor.*`` should populate the manifest."""
        ws = supervisor_workspace

        ws.exec("cd /workspace && forge session start executor --no-proxy --no-launch")
        ws.exec(
            f"cd /workspace && forge session set --session executor "
            f"policy.supervisor.resume_id {SUPERVISOR_RESUME_ID}"
        )
        ws.exec("cd /workspace && forge session set --session executor policy.supervisor.timeout_seconds 30")

        exec_manifest = ws.read_json("/workspace/.forge/sessions/executor/forge.session.json")
        sup_override = exec_manifest.get("overrides", {}).get("policy", {})
        assert sup_override.get("supervisor", {}).get("resume_id") == SUPERVISOR_RESUME_ID
        assert sup_override.get("supervisor", {}).get("timeout_seconds") == 30


HOOK_PAYLOAD = json.dumps(
    {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": "src/demo.py", "content": "def widget(): pass"},
    }
)

# Run-identity env vars are REQUIRED for the ledger assertion: emit_direct_llm_usage
# silently no-ops without an ambient run identity (core/usage/emit.py).
RUN_ENV = "FORGE_RUN_ID=run_cascadee2e0 FORGE_ROOT_RUN_ID=run_cascadee2e0"


def _wire_cascade_session(ws: ContainerLike, name: str = "cascade-exec") -> None:
    """Create a session with cascade enabled via session-set overrides.

    The tier-1 checker model points at an unreachable backend so the cheap check
    fails fast and the cascade's degrade-to-frontier guarantee is exercised.
    """
    ws.exec(f"cd /workspace && forge session start {name} --no-proxy --no-launch")
    ws.write_file("/workspace/plan.md", "# Approved Plan\nCreate src/demo.py with greet(name) only.\n")
    for key, value in (
        ("policy.enabled", "true"),
        ("policy.supervisor.resume_id", SUPERVISOR_RESUME_ID),
        ("policy.supervisor.direct", "true"),
        ("policy.supervisor.cascade", "true"),
        ("policy.supervisor.plan_override_path", "/workspace/plan.md"),
        ("policy.supervisor.checker_model", "gemini/cascade-test-unreachable"),
    ):
        result = ws.exec(f"cd /workspace && forge session set --session {name} {key} {value}")
        assert result.returncode == 0, f"session set {key} failed: {result.stderr}"


def _run_hook_check(ws: ContainerLike, *, session: str, mode: str) -> tuple[int, str, str]:
    result = ws.exec(
        f"cd /workspace && echo '{HOOK_PAYLOAD}' | "
        f"FORGE_SESSION={session} FORGE_TEST_SUPERVISOR_MODE={mode} {RUN_ENV} forge hook policy-check"
    )
    invocations = ws.read_file("/tmp/claude_invocations.log")
    return result.returncode, result.stderr, invocations


class TestCascadeE2E:
    """Cascade hook-path coverage: tier-1 error degrades to exactly one frontier check."""

    def test_escalation_resolved_aligned(self, supervisor_workspace: ContainerLike) -> None:
        ws = supervisor_workspace
        _wire_cascade_session(ws, "cascade-a")

        exit_code, stderr, invocations = _run_hook_check(ws, session="cascade-a", mode="aligned")

        assert exit_code == 0, stderr
        # Exactly one frontier (mock-claude --resume) invocation: the resolver ran once.
        assert invocations.count(f"--resume {SUPERVISOR_RESUME_ID}") == 1
        # The tier-1 error was resolved to allow: no leaked policy-warning noise.
        assert "Policy warning" not in stderr

    def test_escalation_resolved_divergent_blocks(self, supervisor_workspace: ContainerLike) -> None:
        ws = supervisor_workspace
        _wire_cascade_session(ws, "cascade-b")

        exit_code, stderr, invocations = _run_hook_check(ws, session="cascade-b", mode="divergent")

        assert exit_code == 2
        assert "Policy violation" in stderr
        assert invocations.count(f"--resume {SUPERVISOR_RESUME_ID}") == 1

    def test_plan_check_error_event_in_ledger(self, supervisor_workspace: ContainerLike) -> None:
        ws = supervisor_workspace
        _wire_cascade_session(ws, "cascade-c")

        exit_code, stderr, _ = _run_hook_check(ws, session="cascade-c", mode="aligned")
        assert exit_code == 0, stderr

        events = ws.exec("cat $HOME/.forge/usage/events/*.jsonl")
        plan_check_lines = [
            json.loads(line) for line in events.stdout.splitlines() if line.strip() and '"plan-check"' in line
        ]
        assert plan_check_lines, f"no plan-check ledger event found: {events.stdout!r}"
        event = plan_check_lines[-1]
        assert event["status"] == "error"
        assert event["session"] == "cascade-c"
        assert event["root_run_id"] == "run_cascadee2e0"

    def test_supervise_cli_cascade_wiring(self, supervisor_workspace: ContainerLike) -> None:
        """Real CLI chain: supervise target -> reload-from -> --cascade toggles intent."""
        ws = supervisor_workspace
        ws.exec("cd /workspace && forge session start cascade-planner --no-proxy --no-launch")
        ws.exec("cd /workspace && forge session start cascade-d --no-proxy --no-launch")
        ws.write_file("/workspace/plan.md", "# Approved Plan\n")

        # supervise <target> validates conversation evidence; a --no-launch session has
        # only a pre-seeded UUID. Fabricate hook confirmation (same pattern as
        # tests/integration/cli/test_session_commands_integration.py).
        planner_path = "/workspace/.forge/sessions/cascade-planner/forge.session.json"
        planner = ws.read_json(planner_path)
        planner["confirmed"]["claude_session_id"] = SUPERVISOR_RESUME_ID
        planner["confirmed"]["confirmed_by"] = "hook:SessionStart:startup"
        ws.write_json(planner_path, planner)

        set_target = ws.exec("cd /workspace && forge policy supervise cascade-planner --session cascade-d")
        assert set_target.returncode == 0, set_target.stderr

        # No approved snapshot anywhere yet: enabling cascade fails loud, pre-mutation.
        unresolved = ws.exec("cd /workspace && forge policy supervise --cascade --session cascade-d")
        assert unresolved.returncode == 1
        assert "No approved plan snapshot" in unresolved.stdout + unresolved.stderr

        reload_result = ws.exec(
            "cd /workspace && forge policy supervise --reload-from /workspace/plan.md --session cascade-d"
        )
        assert reload_result.returncode == 0, reload_result.stderr

        enabled = ws.exec("cd /workspace && forge policy supervise --cascade --session cascade-d")
        assert enabled.returncode == 0, enabled.stderr

        manifest = ws.read_json("/workspace/.forge/sessions/cascade-d/forge.session.json")
        sup = manifest["intent"]["policy"]["supervisor"]
        assert sup["cascade"] is True
        assert sup["plan_override_path"] == "/workspace/plan.md"
