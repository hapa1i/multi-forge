#!/usr/bin/env python3
"""Replay a captured Stop prefix from a copy while the owned original is absent."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    parser.add_argument("--fresh-index", action="store_true")
    args = parser.parse_args()
    root = Path(os.environ["PROBE_ROUND_ROOT"])
    if Path(os.environ["CODEX_HOME"]) != root / "copy-home":
        raise ValueError("Use the independently logged-in copy-home")
    scripts = Path(__file__).resolve().parent
    admission = runpy.run_path(str(scripts / "b5-admission.py"))
    captured = root / "captures/G12-stop"
    boundary = json.loads((captured / "boundary-before.json").read_text())
    hooks = [json.loads(line) for line in (captured / "hooks.jsonl").read_text().splitlines()]
    payload = next(row["payload"] for row in hooks if row["event"] == "Stop")
    selected = admission["select_prefixes"](
        root / "codex-home", boundary["source_id"], end_bytes=boundary["prefix_bytes"], stop=payload
    )
    if len(selected) != 1 or selected[0]["sha256"] != boundary["prefix_sha256"]:
        raise ValueError("This control requires the exact captured Stop root prefix")
    source = selected[0]
    original = source["path"]
    copied = root / "copy-home" / original.relative_to(root / "codex-home")
    original_bytes, previous_copy = original.read_bytes(), copied.read_bytes()
    held = root / "originals-held" / original.name
    if any(held.parent.iterdir()):
        raise ValueError("Restore all earlier originals before this control")
    configs = []
    index = root / "copy-indexes" / args.label
    databases = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (root / "copy-home").glob("*.sqlite*")
    }
    moved: list[tuple[Path, Path]] = []
    if args.fresh_index:
        index.mkdir(mode=0o700, parents=True, exist_ok=False)
        configs = ["--config", "sqlite_home=" + json.dumps(str(index))]
    original.rename(held)
    try:
        if args.fresh_index:
            for path in (root / "copy-home/sessions").glob("*/*/*/*.jsonl"):
                if path == copied:
                    continue
                saved = root / "copy-sessions-held" / args.label / path.relative_to(root / "copy-home")
                saved.parent.mkdir(parents=True, exist_ok=True)
                if saved.exists():
                    raise ValueError("A previous copied session is still held")
                path.rename(saved)
                moved.append((saved, path))
        copied.write_bytes(source["data"])
        result = subprocess.run(
            [
                sys.executable,
                str(scripts / "b5-fork.py"),
                args.label,
                boundary["source_id"],
                str(captured / "review-prompt.txt"),
                "--model",
                "gpt-6.1-sol",
                "--isolate",
                "--guarded",
                *configs,
            ],
            check=False,
        )
        report = {
            "event": "Stop",
            "replayed_captured_boundary": True,
            "live_hook_during_this_repeat": False,
            "prefix_sha256": source["sha256"],
            "prefix_bytes": len(source["data"]),
            "original_path_unavailable": not original.exists(),
            "original_unchanged": held.read_bytes() == original_bytes,
            "copy_unchanged": copied.read_bytes() == source["data"],
            "fresh_sqlite_home": str(index) if args.fresh_index else None,
            "sqlite_files_created": sorted(p.name for p in index.glob("*.sqlite")) if args.fresh_index else [],
            "unselected_copied_rollouts_held": len(moved),
            "existing_sqlite_files_unchanged": all(
                path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest
                for name, digest in databases.items()
                for path in [root / name]
            ),
            "admission_helper_sha256": hashlib.sha256((scripts / "b5-admission.py").read_bytes()).hexdigest(),
        }
        (root / "captures" / args.label / "boundary-copy.json").write_text(json.dumps(report, indent=2) + "\n")
        return result.returncode
    finally:
        copied.write_bytes(previous_copy)
        for saved, path in moved:
            saved.rename(path)
        if original.exists():
            raise ValueError("Original reappeared; preserve both files for inspection")
        held.rename(original)


if __name__ == "__main__":
    raise SystemExit(main())
