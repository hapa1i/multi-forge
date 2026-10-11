#!/usr/bin/env python3
"""Prepare trusted B4 experiment hooks and retain bounded, explicitly budgeted runtime captures."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
import shlex
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
RUNTIME = runpy.run_path(str(SCRIPTS / "probe-runtime.py"))


def validate(root: Path) -> None:
    if (root / "CLOSED").exists():
        raise ValueError("This probe round is closed; use a new independent fixture")
    if (root / "B4_ROUND").read_text().strip() != "independent-b4-round-v1":
        raise ValueError("An owned B4 round is required.")
    for key, value in (
        ("HOME", "home"),
        ("CODEX_HOME", "codex-home"),
        ("FORGE_HOME", "forge-home"),
    ):
        if Path(os.environ.get(key, "")).resolve() != root / value:
            raise ValueError(f"Use the round launcher with its independent {key}.")
    if os.environ.get("PYTHON_DOTENV_DISABLED") != "1":
        raise ValueError("Disable dotenv before all setup and probes.")


def setup(root: Path) -> None:
    if (root / "PREPARED").exists() or (root / "ENROLLED").exists():
        raise ValueError("Preparation is one-shot; use a new round rather than overwrite trust.")
    forge = shutil.which("forge")
    assert forge
    command = [
        forge,
        "extension",
        "enable",
        "--scope",
        "user",
        "--runtime",
        "codex",
        "--profile",
        "minimal",
    ]
    command += [
        "--with",
        "hooks",
        "--without",
        "commands,agents,skills,status-line,permissions",
    ]
    result = subprocess.run(command, cwd=root / "project", text=True, capture_output=True, timeout=60)
    (root / "setup-enable.json").write_text(json.dumps(vars(result), default=str, indent=2))
    result.check_returncode()
    project_command = [
        forge,
        "extension",
        "enable",
        "--root",
        str(root / "project"),
        "--scope",
        "local",
        "--runtime",
        "claude",
        "--profile",
        "minimal",
    ]
    project_result = subprocess.run(project_command, text=True, capture_output=True, timeout=60)
    (root / "project-enable.json").write_text(json.dumps(vars(project_result), default=str, indent=2))
    project_result.check_returncode()
    doctor = subprocess.check_output([forge, "extension", "doctor", "--json"], cwd=root / "project", text=True)
    (root / "setup-doctor.json").write_text(doctor)
    assert json.loads(doctor)["hook_dispatcher"]["dev_override"]["effective"] is True
    hookbin = root / "hookbin"
    hookbin.mkdir()
    with (root / "codex-home/config.toml").open("a") as config:
        for event in (
            "SessionStart",
            "UserPromptSubmit",
            "PreToolUse",
            "PostToolUse",
            "Stop",
        ):
            wrapper = hookbin / ("b4-" + event)
            wrapper.write_text(
                "#!/bin/bash\nexec " + shlex.join([sys.executable, str(SCRIPTS / "hooks/b4-hook.py"), event]) + "\n"
            )
            wrapper.chmod(0o700)
            config.write(f'\n[[hooks.{event}]]\n[[hooks.{event}.hooks]]\ntype = "command"\n')
            config.write(f"command = {json.dumps(str(wrapper))}\ntimeout = 60\n")
    (root / "PREPARED").write_text("Enroll this exact fixture through the Codex TUI, then verify delivery.\n")
    (root / "budget.json").write_text(
        json.dumps(
            {
                "ceiling": int(os.environ["PROBE_TURN_CEILING"]),
                "enrollment": 4,
                "identity_boundary": 6,
                "product_evidence": 4,
                "failure": 4,
                "wheel_tui": 4,
                "correction_continuations": 2,
                "retries": 8,
                "real_claude_subscription_review": 0,
                "reviewer": "local admission-compatible stub; real inference requires separate authorization",
                "allocation_note": "Original gate estimates below do not increase the launcher's hard ceiling.",
                "api_inference": 0,
            },
            indent=2,
        )
        + "\n"
    )


def seal(root: Path, enrollment: Path) -> None:
    result = json.loads(enrollment.read_text())
    assert result["enrolled"] and result["codex_succeeded"]
    config = root / "codex-home/config.toml"
    (root / "ENROLLED").write_text(
        json.dumps(
            {
                "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
                "config_without_tui_sha256": config_without_tui(config),
                "preflight": result,
                "note": "Event coverage comes from the saved preflight result; TUI presentation counters are excluded.",
            },
            indent=2,
        )
    )


def config_without_tui(path: Path) -> str:
    config = tomllib.loads(path.read_text())
    config.pop("tui", None)
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def execute(root: Path, label: str, control: dict, command: list[str], seconds: int) -> int:
    if not label or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in label):
        raise ValueError("Capture labels must be plain unique names.")
    if (root / "ENROLLED").exists():
        sealed = json.loads((root / "ENROLLED").read_text())
        config = root / "codex-home/config.toml"
        if sealed["config_sha256"] != hashlib.sha256(config.read_bytes()).hexdigest() and sealed.get(
            "config_without_tui_sha256"
        ) != config_without_tui(config):
            raise ValueError("Exact enrolled configuration changed; explicitly re-enroll before continuing.")
    capture = root / "captures" / label
    capture.mkdir(exist_ok=False)
    control = {
        "mode": "observe",
        "reviewer": "fast",
        **control,
        "capture": str(capture),
    }
    (capture / "control.json").write_text(json.dumps(control, indent=2))
    (root / "control.json").write_text(json.dumps(control))
    shutil.copy2(root / "codex-home/config.toml", capture / "config-before.toml")
    os.chdir(root / "project")
    # Allow B1's 0.5-second watchdog cleanup to finish before measuring survivors.
    code = RUNTIME["bounded_run"](command, capture / "run", seconds, 3, settle=2)
    shutil.copy2(root / "codex-home/config.toml", capture / "config-after.toml")
    for payload in capture.glob("*.stdin.json"):
        path = Path(json.loads(payload.read_text()).get("transcript_path", ""))
        if path.is_file() and path.resolve().is_relative_to(root / "codex-home"):
            shutil.copy2(path, capture / path.name)
    (capture / "completed.json").write_text(json.dumps({"at": time.time(), "exit": code}))
    print(json.dumps({"capture": str(capture), "exit": code}), flush=True)
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("setup")
    enroll = sub.add_parser("seal")
    enroll.add_argument("enrollment", type=Path)
    run = sub.add_parser("run")
    run.add_argument("label")
    run.add_argument("--control", type=Path)
    run.add_argument("--seconds", type=int, default=180)
    run.add_argument("--command", nargs=argparse.REMAINDER, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    validate(root)
    if args.action == "setup":
        setup(root)
    elif args.action == "seal":
        seal(root, args.enrollment)
    else:
        control = json.loads(args.control.read_text()) if args.control else {}
        return execute(root, args.label, control, args.command, args.seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
