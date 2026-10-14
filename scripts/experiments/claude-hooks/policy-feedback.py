"""Prepare a synthetic native permission/context trial; inference requires --run."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import shlex
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

MODEL = "claude-haiku-4-5-20251001"
CLI_VERSION = "2.1.296"
BEFORE = "value = 0\n"
AFTER = "value = 1\n"


def manifest() -> dict[str, Any]:
    """Return the complete proposal without reading auth, user configuration or transcripts."""
    cases = []
    for tool in ("Write", "Edit"):
        for feedback in (True, False):
            for allowed in (True, False):
                name = f"{tool.lower()}-{'allow' if allowed else 'manual'}-{'on' if feedback else 'off'}"
                operation = (
                    "Use Write once to create fixture.txt containing exactly `value = 1` followed by a newline."
                    if tool == "Write"
                    else "Read fixture.txt once, then use Edit once to replace `value = 0` with `value = 1`."
                )
                cases.append(
                    {
                        "id": name,
                        "tool": tool,
                        "feedback": feedback,
                        "allow_rule": allowed,
                        "canary": "forge-context-" + hashlib.sha256((name + ":2026-10-14").encode()).hexdigest()[:24],
                        "prompt": (
                            operation + " Do not retry or use another tool if permission is denied. "
                            "After the attempt, report whether it succeeded and repeat any FORGE_CONTEXT_TOKEN "
                            "received in hook context, or say NO_CONTEXT_TOKEN if none was received. "
                            "Do not inspect other files."
                        ),
                    }
                )
    return {
        "version": 1,
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "responder_sha256": hashlib.sha256(
            (Path(__file__).resolve().parents[3] / "src/forge/cli/hooks/policy.py").read_bytes()
        ).hexdigest(),
        "cli_version": CLI_VERSION,
        "model": MODEL,
        "billing": "Anthropic API key; canonical api.anthropic.com; no subscription or gateway fallback",
        "cases": cases,
        "max_invocations": 8,
        "max_agentic_turns_per_invocation": 4,
        "max_admitted_mutations_per_invocation": 1,
        "cli_budget_usd_per_invocation": 0.10,
        "planning_budget_usd": 0.80,
        "wall_seconds_per_invocation": 90,
        "data": "fixed synthetic prompts and fixture.txt only; no repository content or transcripts",
        "isolation": "new output directory; separate workspace, HOME, Claude config and Forge home for every case",
        "permissions": "manual mode, permission-prompts=none; explicit allow-rule controls; no bypass mode",
        "limits": "Agentic-turn and CLI budget limits do not guarantee physical HTTP request counts or the invoice.",
    }


def command(binary: str, case: dict[str, Any], settings_path: Path) -> list[str]:
    """Build a bounded print invocation with only the declared file tools available."""
    return [
        binary,
        "--print",
        "--model",
        MODEL,
        "--max-turns",
        "4",
        "--max-budget-usd",
        "0.10",
        "--output-format",
        "json",
        "--permission-mode",
        "manual",
        "--permission-prompts",
        "none",
        "--tools",
        f"Read,{case['tool']}",
        "--settings",
        str(settings_path),
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--restricted",
        "--no-session-persistence",
        "--disable-slash-commands",
        "--no-chrome",
        case["prompt"],
    ]


def hook(spec_path: Path) -> int:
    """Guard the synthetic target and capture the actual responder output outside the workspace."""
    from forge.cli.hooks.policy import ClaudeHookResponder

    spec = json.loads(spec_path.read_text())
    payload = json.loads(sys.stdin.read(65_537))
    tool = payload.get("tool_name")
    args = payload.get("tool_input", {})
    target = Path(args.get("file_path", "")).resolve()
    expected = Path(spec["target"])
    permitted = payload.get("hook_event_name") == "PreToolUse" and target == expected
    permitted = permitted and tool in {"Read", spec["case"]["tool"]}
    if tool == "Write":
        permitted = permitted and args.get("content") == AFTER
    elif tool == "Edit":
        old = args.get("old_string")
        permitted = permitted and old in {BEFORE, BEFORE.strip()}
        permitted = permitted and args.get("new_string") == (AFTER if old == BEFORE else AFTER.strip())
        permitted = permitted and args.get("replace_all", False) is False
    journal = spec_path.parent / "hooks.jsonl"
    with journal.open("a+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0)
        prior = [json.loads(line) for line in stream]
        permitted = permitted and sum(item["tool"] == tool for item in prior) == 0
        wire = {}
        if permitted and tool != "Read" and spec["case"]["feedback"]:
            wire = ClaudeHookResponder().allow_feedback("FORGE_CONTEXT_TOKEN=" + spec["case"]["canary"])
        stream.write(
            json.dumps(
                {
                    "tool": tool,
                    "permission_mode": payload.get("permission_mode"),
                    "permitted": permitted,
                    "wire": wire,
                }
            )
            + "\n"
        )
    if not permitted:
        print(
            "Synthetic probe permits only its single declared file action and one preparatory read.",
            file=sys.stderr,
        )
        return 2
    if tool != "Read":
        print(
            "Synthetic policy operator notice (retained with feedback off).",
            file=sys.stderr,
        )
    print(json.dumps(wire))
    return 0


def validate_case(
    case: dict[str, Any],
    report: dict[str, Any],
    events: list[dict[str, Any]],
    content: str | None,
) -> None:
    """Require observed native action/context evidence, not just a successful process exit."""
    if any(not event["permitted"] or event["tool"] not in {"Read", case["tool"]} for event in events):
        raise ValueError("A probe hook refused or observed an unexpected tool attempt")
    if sum(event["tool"] == "Read" for event in events) > 1:
        raise ValueError("The native case attempted more than one preparatory read")
    actions = [event for event in events if event["tool"] == case["tool"]]
    if len(actions) != 1 or not actions[0]["permitted"]:
        raise ValueError("Expected exactly one admitted synthetic tool attempt")
    if actions[0]["permission_mode"] not in {"default", "manual"}:
        raise ValueError("Native permission mode was not manual/default")
    output = actions[0]["wire"].get("hookSpecificOutput", {})
    if "permissionDecision" in output:
        raise ValueError("Hook unexpectedly overrode native permissions")
    if bool(output.get("additionalContext")) != case["feedback"]:
        raise ValueError("Feedback toggle did not match the emitted wire")
    expected = AFTER if case["allow_rule"] else BEFORE if case["tool"] == "Edit" else None
    if content != expected:
        raise ValueError("File result does not match native permission expectation")
    denials = report.get("permission_denials", [])
    if not case["allow_rule"] and not any(item.get("tool_name") == case["tool"] for item in denials):
        raise ValueError("Missing native permission-denial evidence")
    observed = case["canary"] in report.get("result", "")
    if case["allow_rule"] and observed != case["feedback"]:
        raise ValueError("Model receipt did not match the feedback control")
    if report.get("is_error"):
        raise ValueError("Native run ended with an error")
    cost = report.get("total_cost_usd")
    if cost is None:
        raise ValueError("Native CLI cost estimate is unavailable; stop before another invocation")
    if type(cost) not in {int, float} or not math.isfinite(cost) or not 0 <= cost <= 0.10:
        raise ValueError("Reported cost exceeded the per-invocation allowance or was malformed")


def run(approved: dict[str, Any], output: Path) -> None:
    """Execute each approved case at most once; preserve partial evidence and stop on the first failure."""
    if approved != manifest():
        raise ValueError("Manifest or harness changed; prepare a new manifest for approval")
    binary = shutil.which("claude")
    if not binary:
        raise ValueError("Claude executable is unavailable")
    binary = str(Path(binary).resolve())
    version = subprocess.run([binary, "--version"], text=True, capture_output=True, check=True, timeout=10).stdout
    if version.strip() != f"{CLI_VERSION} (Claude Code)":
        raise ValueError("Claude version changed; review the trial before running")
    from forge.core.auth.template_secrets import resolve_env_or_credential

    key = resolve_env_or_credential("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("Anthropic API credentials are unavailable; no subscription fallback is permitted")
    output.mkdir(parents=True, exist_ok=False)
    (output / "manifest.json").write_text(json.dumps(approved, indent=2) + "\n")
    for case in approved["cases"]:
        root = output / case["id"]
        workspace = root / "workspace"
        private = root / "private"
        workspace.mkdir(parents=True)
        for ancestor in (workspace, *workspace.parents):
            if any((ancestor / name).exists() for name in ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md")):
                raise ValueError("Trial workspace would inherit instructions; choose an isolated output root")
        private.mkdir(mode=0o700)
        target = workspace / "fixture.txt"
        if case["tool"] == "Edit":
            target.write_text(BEFORE)
        spec_path = private / "spec.json"
        spec_path.write_text(json.dumps({"case": case, "target": str(target)}))
        hook_command = shlex.join([sys.executable, str(Path(__file__).resolve()), "--hook", str(spec_path)])
        settings = {
            "permissions": {"allow": ["Read"] + ([case["tool"]] if case["allow_rule"] else [])},
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Read|Write|Edit",
                        "hooks": [
                            {"type": "command", "command": hook_command, "timeout": 20},
                        ],
                    }
                ]
            },
        }
        settings_path = private / "settings.json"
        settings_path.write_text(json.dumps(settings))
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(private / "home"),
            "CLAUDE_CONFIG_DIR": str(private / "claude"),
            "FORGE_HOME": str(private / "forge"),
            "ANTHROPIC_API_KEY": key,
            "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
            "DISABLE_AUTOUPDATER": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        }
        argv = command(binary, case, settings_path)
        (private / "started.json").write_text(json.dumps({"argv": argv, "cli_version": version.strip()}))
        process = subprocess.Popen(
            argv,
            cwd=workspace,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        stdout = stderr = ""
        try:
            stdout, stderr = process.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                stdout, stderr = process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
            raise ValueError("Native trial exceeded its wall deadline") from None
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
            # Raw output is local evidence; replace the resolved key before saving any process text.
            (private / "stdout.txt").write_text(stdout.replace(key, "[REDACTED]"))
            (private / "stderr.txt").write_text(stderr.replace(key, "[REDACTED]"))
        if process.returncode:
            raise ValueError(f"Native case {case['id']} failed; inspect its retained local output")
        report = json.loads(stdout)
        events = [json.loads(line) for line in (private / "hooks.jsonl").read_text().splitlines()]
        content = target.read_text() if target.exists() else None
        validate_case(case, report, events, content)
        (private / "verified.json").write_text(
            json.dumps(
                {
                    "verified": True,
                    "cli_cost_estimate_usd": report.get("total_cost_usd"),
                }
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hook", type=Path)
    parser.add_argument(
        "--run",
        type=Path,
        help="Path to the exact approved manifest; makes paid API calls",
    )
    parser.add_argument("--output", type=Path, help="New isolated evidence directory for a live run")
    args = parser.parse_args()
    if args.hook:
        try:
            return hook(args.hook)
        except Exception:
            print(
                "Synthetic probe hook could not validate its input; action refused.",
                file=sys.stderr,
            )
            return 2
    if args.run:
        if not args.output or not args.output.is_absolute():
            parser.error("--run requires an absolute --output pointing to a new directory")
        run(json.loads(args.run.read_text()), args.output)
    else:
        print(json.dumps(manifest(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
