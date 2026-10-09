#!/usr/bin/env python3
"""Prepare B2 response/stub fixtures around an already retained, independently logged-in runtime.

Run through the round's clean-environment launcher, after stages 00/05/10/60/61.
This rebuilds disposable hook registrations, never credentials. Enroll the emitted
fixture project interactively before running the product and delivery stages.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
from pathlib import Path


def prepare(root: Path) -> None:
    scripts = Path(__file__).resolve().parent
    checkout = scripts.parents[2]
    if Path(os.environ.get("FORGE_DEV", "")).resolve() != checkout:
        raise ValueError("Run with FORGE_DEV bound to this checkout.")
    if (root / "prepared").exists():
        raise ValueError("Already prepared; do not erase enrollment to repeat a stage.")
    identity = json.loads((root / "identity.json").read_text())
    identity["model"] = "gpt-6.1-sol"
    identity["effort"] = "low"
    (root / "identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    subprocess.run(
        [
            "/bin/bash",
            "-c",
            'source "$1/lib.sh"; fixture_init 80-enroll-fixture; fixture_build; '
            "fixture_register_project; fixture_register_user; fixture_tee_all",
            "probe",
            str(scripts),
        ],
        check=True,
    )
    login_home = Path(os.environ["CODEX_HOME"])
    stale_json = login_home / "hooks.json"
    if stale_json.exists():
        stale_json.rename(root / "captures/80-enroll-fixture/meta/baseline-hooks.json")
    forge = checkout / ".venv/bin/forge"
    subprocess.run(
        [
            str(forge),
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
        check=True,
    )
    doctor = subprocess.check_output([str(forge), "extension", "doctor", "--json"], text=True)
    (root / "captures/80-enroll-fixture/meta/forge-doctor.json").write_text(doctor)
    report = json.loads(doctor)
    assert report["hook_dispatcher"]["dev_override"]["effective"] is True
    control = root / "control.json"
    control.write_text(
        json.dumps({"capture": str(root / "captures/preparation"), "mode": "observe", "reviewer": "fast"})
    )
    hookbin = root / "hookbin"
    hookbin.mkdir(exist_ok=True)
    python = checkout / ".venv/bin/python"
    events = [
        "SessionStart",
        "PreToolUse",
        "PostToolUse",
        "UserPromptSubmit",
        "Stop",
        "SubagentStart",
        "SubagentStop",
        "Background",
    ]
    with (login_home / "config.toml").open("a") as config:
        for event in events:
            wrapper = hookbin / f"b2-{event}"
            wrapper.write_text(
                "#!/bin/bash\nexec " + shlex.join([str(python), str(scripts / "hooks/b2-hook.py"), event]) + "\n"
            )
            wrapper.chmod(0o700)
            event_name = "PostToolUse" if event == "Background" else event
            config.write(f'\n[[hooks.{event_name}]]\n[[hooks.{event_name}.hooks]]\ntype = "command"\n')
            config.write(f"command = {json.dumps(str(wrapper))}\ntimeout = 60\n")
            if event == "Background":
                config.write("async = true\n")
    stub = root / "stub-bin/claude"
    stub.write_text("#!/bin/bash\nexec " + shlex.join([str(python), str(scripts / "hooks/b2-reviewer.py")]) + ' "$@"\n')
    stub.chmod(0o700)
    launcher = root / "run"
    text = launcher.read_text().replace(
        '  "$@"',
        "  PROBE_CONTROL=" + shlex.quote(str(control)) + " \\\n"
        "  PYTHONPATH=" + shlex.quote(str(scripts / "instrumentation")) + " \\\n"
        "  GIT_CONFIG_GLOBAL=/dev/null \\\n"
        "  GIT_CONFIG_NOSYSTEM=1 \\\n"
        '  "$@"',
    )
    launcher.write_text(text)
    (root / "prepared").write_text("B2 fixture prepared; enroll without trust bypass.\n")
    project = root / "captures/fixture/proj"
    print(f"Enroll at {project}; use the clean launcher and retained codex wrapper.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    prepare(args.root.resolve())


if __name__ == "__main__":
    main()
