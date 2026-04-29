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
    """Run ``forge guard supervisor`` through the deterministic resume harness."""
    result = workspace.exec(
        f"cd /workspace && FORGE_TEST_SUPERVISOR_MODE={mode} "
        f"forge guard supervisor -f src/demo.py -r {SUPERVISOR_RESUME_ID} --json"
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
