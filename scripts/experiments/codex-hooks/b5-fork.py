#!/usr/bin/env python3
"""Capture one synthetic native fork and compare the observed source and parent state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from forge.core.runtime.codex_rollouts import find_rollouts_by_thread_id


def state_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def forge_state(root: Path) -> dict[str, str]:
    return {
        f"{scope}/{name}": digest
        for scope in ("action/.forge", "forge-home")
        for name, digest in state_hashes(root / scope).items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    parser.add_argument("source_id")
    parser.add_argument("prompt", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--argv-control", action="store_true")
    parser.add_argument("--disable-hooks", action="store_true")
    parser.add_argument("--isolate", action="store_true")
    parser.add_argument("--guarded", action="store_true")
    parser.add_argument("--sandbox", choices=("read-only", "workspace-write"), default="read-only")
    parser.add_argument("--schema", type=Path)
    parser.add_argument("--seconds", type=float, default=45)
    parser.add_argument("--config", action="append", default=[])
    args = parser.parse_args()
    root = Path(os.environ["PROBE_ROUND_ROOT"])
    home = Path(os.environ["CODEX_HOME"])
    sources = find_rollouts_by_thread_id(args.source_id, home=home)
    if len(sources) != 1:
        raise ValueError("Exactly one rollout must resolve from the source ID.")
    source = sources[0]
    before = source.read_bytes()
    parent_before = forge_state(root)
    destination = root / "captures" / args.label
    prompt = args.prompt.read_text()
    command = [
        "codex",
        "exec",
        "--json",
        "--sandbox",
        args.sandbox,
        "-C",
        str(root / "action"),
        "fork",
        "--ephemeral",
        "--output-schema",
        str(args.schema or root / "review-schema.json"),
        "-o",
        str(destination / "last.txt"),
    ]
    if args.model:
        command += ["-m", args.model, "-c", 'model_reasoning_effort="low"']
    if args.disable_hooks:
        command += ["--disable", "hooks"]
    child_env = dict(os.environ)
    removed = []
    if args.isolate:
        command += ["--ignore-user-config", "--ignore-rules"]
        for feature in ("hooks", "multi_agent", "apps", "plugins"):
            command += ["--disable", feature]
        command += ["-c", "agents.enabled=false"]
        for key in tuple(child_env):
            if key.startswith("FORGE_") and key not in {"FORGE_HOME", "FORGE_DEV"}:
                removed.append(key)
                child_env.pop(key)
            elif key in {"CODEX_THREAD_ID", "CODEX_INTERNAL_ORIGINATOR_OVERRIDE"}:
                removed.append(key)
                child_env.pop(key)
    for config in args.config:
        command += ["-c", config]
    command += [args.source_id, prompt if args.argv_control else "-"]
    driver = Path(__file__).with_name("b5-capture.py")
    if args.guarded:
        command = [
            sys.executable,
            str(Path(__file__).with_name("b5-guard.py")),
            str(args.seconds),
            *command,
        ]
    result = subprocess.run(
        [
            sys.executable,
            str(driver),
            "run",
            "--seconds",
            str(args.seconds + (5 if args.guarded else 0)),
            "--settle",
            "2" if args.guarded else "0",
            args.label,
            "--",
            *command,
        ],
        input=None if args.argv_control else prompt,
        text=True,
        cwd=root / "action",
        env=child_env,
        check=False,
    )
    after = source.read_bytes()
    events = []
    for line in (destination / "run/stdout").read_text().splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    child_ids = [event["thread_id"] for event in events if event.get("type") == "thread.started"]
    parent_after = forge_state(root)
    last = (destination / "last.txt").read_text() if (destination / "last.txt").is_file() else ""
    try:
        verdict = json.loads(last) if last else None
    except ValueError:
        verdict = None
    report = {
        "source_id": args.source_id,
        "source_path": str(source),
        "source_sha256_before": hashlib.sha256(before).hexdigest(),
        "source_sha256_after": hashlib.sha256(after).hexdigest(),
        "source_bytes": len(before),
        "source_unchanged": before == after,
        "child_ids": child_ids,
        "persistent_child_rollouts": [
            str(path) for child in child_ids for path in find_rollouts_by_thread_id(child, home=home)
        ],
        "parent_state_changed": sorted(
            key for key in parent_before.keys() | parent_after.keys() if parent_before.get(key) != parent_after.get(key)
        ),
        "completed": any(event.get("type") == "turn.completed" for event in events),
        "verdict": verdict,
        "prompt_transport": "argv control" if args.argv_control else "stdin",
        "prompt_bytes": len(prompt.encode()),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "returncode": result.returncode,
        "identity_variables_removed": sorted(removed),
        "hook_observations": (
            (destination / "hooks.jsonl").read_text().splitlines() if (destination / "hooks.jsonl").exists() else []
        ),
    }
    (destination / "fork-result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
