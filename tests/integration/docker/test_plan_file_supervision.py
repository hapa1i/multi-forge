"""Plan supervision and runtime hook expiry in disposable API-backed identities."""

from __future__ import annotations

import json
import os
import shlex
import time

import pytest

from tests.fixtures.codex_enrollment import codex_exports, prepare_real_codex
from tests.fixtures.docker import ContainerLike, DockerContainer
from tests.integration.docker.conftest import run_claude_print, setup_real_claude

pytestmark = [pytest.mark.integration, pytest.mark.docker_in, pytest.mark.slow]

_PROBE = r"""import json, os, signal, subprocess, sys, threading, time
from pathlib import Path
from forge.core.reactive.watchdog import run_guarded

root = Path("/tmp/b1-expiry")
root.mkdir(exist_ok=True)
payload = json.load(sys.stdin)
def event(kind, **fields):
    with (root / "events.jsonl").open("a") as f:
        f.write(json.dumps(dict(kind=kind, time=time.time(), pid=os.getpid(), pgid=os.getpgrp(), **fields))+"\n")
def handle(sig, frame):
    event("signal", signal=sig)
    sys.exit(128+sig)
for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
    signal.signal(sig, handle)
event("hook", tool=payload.get("tool_name"))
mode = (root / "mode").read_text()
if mode in {"hook", "group"}:
    def terminate():
        if mode == "hook": os.kill(os.getpid(), signal.SIGKILL)
        else: os.killpg(os.getpgrp(), signal.SIGKILL)
    threading.Timer(3, terminate).start()
argv = [sys.executable, str(root / "reviewer.py")]
if mode == "baseline":
    subprocess.run(argv, timeout=120)
else:
    run_guarded(argv, input="", env=dict(os.environ), cwd="/workspace", timeout=90)
"""

_REVIEWER = r"""import json, os, signal, subprocess, sys, time
from pathlib import Path
root = Path("/tmp/b1-expiry")
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(150)"])
with (root / "reviewers.jsonl").open("a") as f:
    f.write(json.dumps(dict(pid=os.getpid(), child=child.pid, pgid=os.getpgrp(), parent=os.getppid()))+"\n")
time.sleep(150)
"""


def _write(workspace: ContainerLike, path: str, content: str, mode: int = 0o600) -> None:
    result = workspace.write_file(path, content, mode=mode)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("runtime", ["claude_code", "codex"])
@pytest.mark.parametrize("mode", ["baseline", "natural", "hook", "group"])
def test_real_executor_hook_expiry(forge_workspace: ContainerLike, tmp_path, runtime, mode):
    """Measure native 60s behavior, then assert the independent guard bounds descendants."""
    workspace = forge_workspace
    cleaned = workspace.exec("rm -rf /tmp/b1-expiry && rm -f /workspace/expiry-result.txt")
    assert cleaned.returncode == 0, cleaned.stderr
    if runtime == "codex":
        assert isinstance(workspace, DockerContainer)
        prepare_real_codex(workspace)
        exports = codex_exports()
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            pytest.fail("The real Claude executor probe requires ANTHROPIC_API_KEY (explicit API-route evidence).")
        setup_real_claude(workspace, session_name="expiry")
        exports = "export FORGE_DEV=/forge"
    setup = workspace.exec(
        f'{exports} && mkdir -p /tmp/b1-expiry && cp "$HOME/.forge/bin/forge-hook" /tmp/b1-expiry/original-hook'
    )
    assert setup.returncode == 0, setup.stderr
    _write(workspace, "/tmp/b1-expiry/mode", mode)
    _write(workspace, "/tmp/b1-expiry/probe.py", _PROBE)
    _write(workspace, "/tmp/b1-expiry/reviewer.py", _REVIEWER)
    # Preserve the registered command and timeout bytes; only its disposable
    # executable body is instrumented. The host enrollment and credentials stay untouched.
    hook_path = workspace.exec(f"{exports} && printf '%s' \"$HOME/.forge/bin/forge-hook\"").stdout
    _write(
        workspace,
        hook_path,
        """#!/bin/bash
case "$1" in
  policy-check|codex-policy-check) exec /forge/.venv/bin/python /tmp/b1-expiry/probe.py ;;
  *) exec /tmp/b1-expiry/original-hook "$@" ;;
esac
""",
        mode=0o700,
    )
    workspace.exec("mkdir -p /tmp/b1-tracebin && rm -f /tmp/b1-tracebin/claude /tmp/b1-tracebin/codex")
    trace_env = {}
    if mode in {"baseline", "natural"}:
        installed = workspace.exec(
            "command -v strace || (apt-get update -qq && apt-get install -y -qq strace)", timeout=90
        )
        assert installed.returncode == 0, installed.stderr
        binary = "codex" if runtime == "codex" else "claude"
        resolved = workspace.exec(f'readlink -f "$(command -v {binary})"').stdout.strip()
        _write(
            workspace,
            f"/tmp/b1-tracebin/{binary}",
            f'#!/bin/sh\nexec strace -ff -tt -e trace=kill,tgkill -o /tmp/b1-expiry/signals {shlex.quote(resolved)} "$@"\n',
            mode=0o700,
        )
        original_path = workspace.exec("printf '%s' \"$PATH\"").stdout
        trace_env = {"PATH": "/tmp/b1-tracebin:" + original_path}
        if runtime == "codex":
            exports += " && export PATH=" + shlex.quote(trace_env["PATH"])
    prompt = (
        "Use "
        + ("apply_patch" if runtime == "codex" else "Write")
        + " exactly once to create /workspace/expiry-result.txt containing done. "
        "Do not use Bash or any other write mechanism. Do not retry after a hook error. Then stop."
    )
    if runtime == "codex":
        _write(workspace, "/tmp/b1-expiry/prompt", prompt)
        result = workspace.exec(
            f"{exports} && export CODEX_API_KEY=$(cat /tmp/.authority_codex_key) && cd /workspace && "
            "timeout --kill-after=3 130 codex exec --json --sandbox workspace-write -m gpt-6.1-sol "
            '-c \'model_reasoning_effort="low"\' "$(cat /tmp/b1-expiry/prompt)"',
            timeout=140,
        )
        exit_code = result.returncode
        runtime_output = result.stdout + result.stderr
    else:
        exit_code, stdout, stderr = run_claude_print(
            workspace,
            prompt,
            session_name="expiry",
            timeout=130,
            extra_env=trace_env,
            extra_args=["--model", "sonnet", "--effort", "low", "--allowedTools", "Write", "--"],
        )
        runtime_output = stdout + stderr
    assert workspace.file_exists("/tmp/b1-expiry/events.jsonl"), "The real runtime did not invoke the enrolled hook"
    events = [json.loads(line) for line in workspace.read_file("/tmp/b1-expiry/events.jsonl").splitlines()]
    reviewers = [json.loads(line) for line in workspace.read_file("/tmp/b1-expiry/reviewers.jsonl").splitlines()]
    pids = [pid for row in reviewers for pid in (row["pid"], row["child"])]
    inspect_code = (
        "import json; from pathlib import Path; rows=[]; "
        f"pids={pids!r}; "
        "\nfor pid in pids:\n"
        " p=Path(f'/proc/{pid}/stat')\n"
        " if p.exists():\n"
        "  fields=p.read_text().split(') ',1)[1].split()\n"
        "  if fields[0] != 'Z': rows.append(dict(pid=pid,state=fields[0],parent=fields[1],pgid=fields[2]))\n"
        "print(json.dumps(rows))"
    )
    _write(workspace, "/tmp/b1-expiry/inspect.py", inspect_code)
    probe = workspace.exec("/forge/.venv/bin/python /tmp/b1-expiry/inspect.py")
    assert probe.returncode == 0, probe.stderr
    surviving = json.loads(probe.stdout)
    initial_survivors = surviving
    # The executor can finish reporting its tool error before the detached
    # watchdog's bounded TERM/KILL grace has elapsed.
    cleanup_started = time.monotonic()
    while surviving and mode != "baseline" and time.monotonic() - cleanup_started < 2:
        time.sleep(0.05)
        probe = workspace.exec("/forge/.venv/bin/python /tmp/b1-expiry/inspect.py")
        assert probe.returncode == 0, probe.stderr
        surviving = json.loads(probe.stdout)
    evidence = dict(
        runtime=runtime,
        mode=mode,
        exit_code=exit_code,
        events=events,
        reviewers=reviewers,
        survivors=surviving,
        survivors_at_executor_exit=initial_survivors,
        cleanup_observation_seconds=round(time.monotonic() - cleanup_started, 2),
        hook_elapsed_seconds=round(time.time() - events[0]["time"], 2),
        runtime_tail=runtime_output[-2500:],
        tool_ran=workspace.file_exists("/workspace/expiry-result.txt"),
    )
    if mode in {"baseline", "natural"}:
        traced = workspace.exec("cat /tmp/b1-expiry/signals.*")
        assert traced.returncode == 0, traced.stderr
        evidence["signal_syscalls"] = [
            line for line in traced.stdout.splitlines() if "kill(" in line or "tgkill(" in line
        ]
        assert evidence["signal_syscalls"], evidence
    (tmp_path / f"{runtime}-{mode}.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence))
    if mode != "baseline":
        assert not surviving, evidence
    assert reviewers, evidence
    restored = workspace.exec(f"cp /tmp/b1-expiry/original-hook {hook_path}")
    assert restored.returncode == 0, restored.stderr


@pytest.mark.parametrize("runtime", ["claude_code", "codex"])
def test_plan_only_configuration_and_hook_review(forge_workspace: ContainerLike, runtime):
    """Both real hook adapters register a plan-only supervisor; the reviewer is deterministic here."""
    workspace = forge_workspace
    workspace.exec("rm -f /tmp/b1-review-prompt")
    created = workspace.exec("cd /workspace && forge session start plan-worker --no-launch")
    assert created.returncode == 0, created.stderr
    _write(workspace, "/workspace/approved.md", "Only add greet.py containing a greeting.\n")
    configured = workspace.exec(
        "cd /workspace && FORGE_SESSION=plan-worker forge policy supervisor set --plan approved.md "
        "--model sonnet --no-supervisor-proxy"
    )
    assert configured.returncode == 0, configured.stderr
    _write(
        workspace,
        "/usr/local/bin/claude",
        """#!/bin/bash
if [ "$1" = "--version" ]; then echo '2.1.291 (Claude Code)'; exit 0; fi
cat >/tmp/b1-review-prompt
printf '%s\n' '{"verdict":"divergent","confidence":0.99,"violations":[{"severity":"high","evidence":"wrong file","citations":["Only add greet.py"]}]}'
""",
        mode=0o700,
    )
    if runtime == "claude_code":
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/other.py", "content": "bad"},
            "cwd": "/workspace",
        }
        hook = "policy-check"
    else:
        payload = {
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Add File: /workspace/other.py\n+bad\n*** End Patch"},
            "cwd": "/workspace",
        }
        hook = "codex-policy-check"
    payload["hook_event_name"] = "PreToolUse"
    _write(workspace, "/tmp/b1-payload.json", json.dumps(payload))
    result = workspace.exec(f"cd /workspace && FORGE_SESSION=plan-worker forge hook {hook} </tmp/b1-payload.json")
    assert workspace.file_exists("/tmp/b1-review-prompt"), result.stdout + result.stderr
    assert "Only add greet.py" in workspace.read_file("/tmp/b1-review-prompt")
    assert result.returncode == 2 or "deny" in result.stdout or "block" in result.stdout, result.stdout + result.stderr
