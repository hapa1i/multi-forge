"""Regression: negative Codex skill probes must prove the turn and command evidence."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGES = REPO_ROOT / "scripts" / "experiments" / "codex-skills" / "stages"

FAKE_CODEX = r"""#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
    --version)
        echo "codex-cli 0.144.5"
        exit 0
        ;;
    login)
        echo "Logged in"
        exit 0
        ;;
    exec)
        shift
        output=""
        prompt=""
        while [ "$#" -gt 0 ]; do
            if [ "$1" = "-o" ]; then
                output="$2"
                shift 2
            else
                prompt="$1"
                shift
            fi
        done
        [ -n "$output" ] || exit 91

        policy_skill="$HOME/.agents/skills/probe-explicit-only"
        script_skill="$HOME/.agents/skills/probe-script"
        message=""
        if [[ "$prompt" == *"deliberately unnamed policy probe"* ]]; then
            if rg -q --fixed-strings "allow_implicit_invocation: false" "$policy_skill/agents/openai.yaml"; then
                [ "${FAKE_CODEX_FAIL_BLOCKED:-0}" != "1" ] || exit 77
                message="NO_IMPLICIT_SKILL"
            else
                message="EXPLICIT_POLICY_9E8D7"
            fi
        elif [[ "$prompt" == *"explicit policy probe"* ]]; then
            message="EXPLICIT_POLICY_9E8D7"
        elif rg -q --fixed-strings 'Execute `bash scripts/marker.sh` verbatim.' "$script_skill/SKILL.md"; then
            [ "${FAKE_CODEX_FAIL_LITERAL:-0}" != "1" ] || exit 78
            command="${FAKE_LITERAL_COMMAND:-$SHELL -lc 'bash scripts/marker.sh'}"
            exit_code="${FAKE_LITERAL_EXIT:-127}"
            message="literal command failed"
            printf '{"type":"item.completed","item":{"id":"item_1","type":"command_execution","command":"%s","aggregated_output":"not found\\n","exit_code":%s,"status":"failed"}}\n' \
                "$command" "$exit_code"
        elif rg -q --fixed-strings "resolved absolute path" "$script_skill/SKILL.md"; then
            message="SCRIPT_ROOT_5B4C3"
        elif rg -q --fixed-strings "packaged read-only resource" "$script_skill/SKILL.md"; then
            message="RESOURCE_ROOT_2D1E0"
        else
            exit 92
        fi

        printf '%s\n' "$message" >"$output"
        printf '{"type":"item.completed","item":{"id":"item_2","type":"agent_message","text":"%s"}}\n' "$message"
        printf '{"type":"turn.completed"}\n'
        exit 0
        ;;
esac

exit 93
"""

FAKE_RG = r"""#!/usr/bin/env bash
set -euo pipefail

options=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        -q) options+=("-q") ;;
        -i) options+=("-i") ;;
        -qi | -iq) options+=("-q" "-i") ;;
        --fixed-strings) options+=("-F") ;;
        --) shift; break ;;
        -*) echo "unsupported fake rg option: $1" >&2; exit 2 ;;
        *) break ;;
    esac
    shift
done
[ "$#" -gt 0 ] || exit 2
pattern="$1"
shift
exec grep "${options[@]}" -- "$pattern" "$@"
"""


def _probe_environment(tmp_path: Path, **overrides: str) -> dict[str, str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    codex = fake_bin / "codex"
    codex.write_text(FAKE_CODEX, encoding="utf-8")
    codex.chmod(0o755)
    rg = fake_bin / "rg"
    rg.write_text(FAKE_RG, encoding="utf-8")
    rg.chmod(0o755)

    real_codex_home = tmp_path / "real-codex-home"
    real_codex_home.mkdir()
    (real_codex_home / "auth.json").write_text("{}\n", encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "PROBE_REAL_HOME": str(tmp_path / "real-home"),
            "PROBE_REAL_CODEX_HOME": str(real_codex_home),
            "CODEX_SKILLS_CAPTURE_DIR": str(tmp_path / "captures"),
            "PROBE_TURN_TIMEOUT": "5",
            **overrides,
        }
    )
    return env


def _run_stage(tmp_path: Path, stage: str, **overrides: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(STAGES / stage)],
        capture_output=True,
        check=False,
        env=_probe_environment(tmp_path, **overrides),
        text=True,
    )


def test_invocation_policy_requires_enabled_control_and_successful_blocked_turn(
    tmp_path: Path,
) -> None:
    success = _run_stage(tmp_path / "success", "40-invocation-policy.sh")
    assert success.returncode == 0, success.stderr
    assert "implicit control loaded" in success.stdout

    failed_turn = _run_stage(tmp_path / "failed", "40-invocation-policy.sh", FAKE_CODEX_FAIL_BLOCKED="1")
    assert failed_turn.returncode != 0
    assert "implicit-blocked Codex turn failed" in failed_turn.stderr


def test_script_resolution_requires_successful_negative_turn(tmp_path: Path) -> None:
    failed_turn = _run_stage(tmp_path, "50-script-resolution.sh", FAKE_CODEX_FAIL_LITERAL="1")
    assert failed_turn.returncode != 0
    assert "literal Codex turn failed" in failed_turn.stderr


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("FAKE_LITERAL_COMMAND", "/bin/bash -lc 'echo bash scripts/marker.sh'"),
        ("FAKE_LITERAL_EXIT", "1"),
    ],
)
def test_script_resolution_requires_exact_command_and_exit(
    tmp_path: Path,
    override: str,
    value: str,
) -> None:
    result = _run_stage(tmp_path, "50-script-resolution.sh", **{override: value})
    assert result.returncode != 0
    assert "did not record completed command 'bash scripts/marker.sh' with exit 127" in result.stderr


def test_script_resolution_accepts_complete_jsonl_evidence(tmp_path: Path) -> None:
    result = _run_stage(tmp_path, "50-script-resolution.sh")
    assert result.returncode == 0, result.stderr
    assert "CWD-relative script fails" in result.stdout
