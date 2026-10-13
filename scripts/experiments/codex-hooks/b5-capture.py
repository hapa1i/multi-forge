#!/usr/bin/env python3
"""Prepare B5's real hooks and capture bounded commands with source/config provenance."""

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
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
RUNTIME = runpy.run_path(str(SCRIPTS / "probe-runtime.py"))
EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")


def validate() -> Path:
    root = Path(os.environ["PROBE_ROUND_ROOT"])
    if (
        root.resolve() != root
        or (root / "B5_ROUND").read_text() != "independent-b5-round-v1\n"
        or (root / "CLOSED").exists()
    ):
        raise ValueError("Use a canonical open B5 fixture.")
    for variable, relative in (("HOME", "home"), ("FORGE_HOME", "forge-home")):
        if Path(os.environ[variable]) != root / relative:
            raise ValueError("Use the fixture's clean run launcher.")
    home = Path(os.environ["CODEX_HOME"])
    if (
        home.resolve() != home
        or home.parent != root
        or (home / ".forge-codex-probe-home").read_text() != "independent-login-v1\n"
    ):
        raise ValueError("Use an independently prepared home inside this round.")
    if os.environ.get("PYTHON_DOTENV_DISABLED") != "1":
        raise ValueError("Disable dotenv before setup or capture.")
    return root


def setup(root: Path) -> None:
    """Install actual Forge hooks only in the owned fixture, with observation alongside them."""
    marker = root / "HOOKS_PREPARED"
    if Path(os.environ["CODEX_HOME"]) != root / "codex-home":
        raise ValueError("Only the primary fixture home receives Forge hooks.")
    if marker.exists():
        raise ValueError("Hook setup is one-shot; do not replace established trust.")
    (root / "action/.forge").mkdir(exist_ok=True)
    forge = str(Path(os.environ["FORGE_DEV"]) / ".venv/bin/forge")
    commands = (
        [
            forge,
            "extension",
            "enable",
            "--scope",
            "user",
            "--runtime",
            "codex",
            "--profile",
            "minimal",
            "--with",
            "hooks",
            "--without",
            "commands,agents,skills,status-line,permissions",
        ],
        [forge, "extension", "doctor", "--json"],
    )
    records = json.loads((root / "setup.json").read_text()) if (root / "setup.json").exists() else []
    for command in commands:
        result = subprocess.run(command, cwd=root / "action", text=True, capture_output=True, timeout=60)
        records.append(vars(result))
        (root / "setup.json").write_text(json.dumps(records, indent=2) + "\n")
        result.check_returncode()
    assert json.loads(records[-1]["stdout"])["hook_dispatcher"]["dev_override"]["effective"] is True
    hookbin = root / "hookbin"
    hookbin.mkdir()
    with (root / "codex-home/config.toml").open("a") as config:
        for event in EVENTS:
            wrapper = hookbin / event
            wrapper.write_text(
                "#!/bin/bash\nexec " + shlex.join([sys.executable, str(SCRIPTS / "hooks/b5-observe.py"), event]) + "\n"
            )
            wrapper.chmod(0o700)
            config.write(f'\n[[hooks.{event}]]\n[[hooks.{event}.hooks]]\ntype = "command"\n')
            config.write(f"command = {json.dumps(str(wrapper))}\ntimeout = 60\n")
    marker.write_text("Registrations prepared; actual trust enrollment and delivery are not yet verified.\n")
    print(marker.read_text().strip())


def capture(root: Path, label: str, command: list[str], seconds: float, settle: float = 0) -> int:
    """Persist the exact experimental inputs and bounded process result, including failures."""
    if not label or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in label):
        raise ValueError("Use a unique plain capture label.")
    if not command or not 0 < seconds <= 600:
        raise ValueError("Provide a command and a deadline of at most 600 seconds.")
    destination = root / "captures" / label
    destination.mkdir(exist_ok=False)
    os.environ["PROBE_CAPTURE"] = str(destination)
    checkout = Path(os.environ["FORGE_DEV"])
    diff = subprocess.check_output(["git", "-C", str(checkout), "diff", "HEAD"])
    (destination / "forge.patch").write_bytes(diff)
    provenance = {
        "forge_revision": subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip(),
        "forge_diff_sha256": hashlib.sha256(diff).hexdigest(),
        "case": os.environ.get("PROBE_CASE"),
        "model": os.environ.get("PROBE_MODEL"),
        "auth_mode": os.environ.get("PROBE_AUTH_MODE", "subscription-only"),
        "identity": json.loads((root / "identity.json").read_text()),
        "configs": {},
    }
    for label_, path in (
        ("user-config", Path(os.environ["CODEX_HOME"]) / "config.toml"),
        ("user-hooks", Path(os.environ["CODEX_HOME"]) / "hooks.json"),
        ("project-config", Path.cwd() / ".codex/config.toml"),
        ("forge-config", root / "forge-home/config.yaml"),
    ):
        if path.is_file():
            shutil.copy2(path, destination / label_)
            provenance["configs"][str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    (destination / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    code = RUNTIME["bounded_run"](command, destination / "run", seconds, 5, settle=settle)
    outer_result = json.loads((destination / "run/process-result.json").read_text())
    starts = (
        [json.loads(line) for line in (root / "starts.jsonl").read_text().splitlines()]
        if (root / "starts.jsonl").exists()
        else []
    )
    outcomes = (
        [json.loads(line) for line in (root / "outcomes.jsonl").read_text().splitlines()]
        if (root / "outcomes.jsonl").exists()
        else []
    )
    finished = {row["id"] for row in outcomes}
    for row in starts:
        if row["capture"] == str(destination) and row["id"] not in finished:
            RUNTIME["append_json"](
                root / "outcomes.jsonl",
                {
                    "id": row["id"],
                    "returncode": None,
                    "observation": "wrapper did not report an exit",
                    "outer_result": outer_result,
                },
            )
    print(
        json.dumps({"capture": str(destination), "exit": code, "process_result": outer_result}),
        flush=True,
    )
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("setup")
    run = sub.add_parser("run")
    run.add_argument("--seconds", type=float, default=60)
    run.add_argument("--settle", type=float, default=0)
    run.add_argument("label")
    run.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    root = validate()
    if args.action == "setup":
        setup(root)
        return 0
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    return capture(root, args.label, command, args.seconds, args.settle)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, KeyError, ValueError) as exc:
        sys.exit(str(exc))
