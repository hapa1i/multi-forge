#!/usr/bin/env python3
"""Test an owned rollout copy while its original path is unavailable."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from forge.core.runtime.codex_rollouts import find_rollouts_by_thread_id


def pending_calls(records: list[dict]) -> list[str]:
    """Identify unfinished native tool exchanges in these retained-runtime fixtures."""
    pending = set()
    for record in records:
        payload = record.get("payload", {})
        if record.get("type") != "response_item":
            continue
        kind, call = payload.get("type"), payload.get("call_id")
        if kind in {"function_call", "custom_tool_call"}:
            pending.add(call)
        elif kind in {"function_call_output", "custom_tool_call_output"}:
            pending.discard(call)
    return sorted(pending)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    parser.add_argument("source_id")
    parser.add_argument("prompt", type=Path)
    parser.add_argument("--incomplete", action="store_true")
    parser.add_argument("--without-ancestor", action="store_true")
    parser.add_argument("--existing-copy", action="store_true")
    parser.add_argument("--hide-original-ancestor", action="store_true")
    args = parser.parse_args()
    root = Path(os.environ["PROBE_ROUND_ROOT"])
    original_home, copy_home = root / "codex-home", root / "copy-home"
    if Path(os.environ["CODEX_HOME"]) != copy_home:
        raise ValueError("Use the independently logged-in copy-home.")
    sources = find_rollouts_by_thread_id(args.source_id, home=original_home)
    if len(sources) != 1:
        raise ValueError("Exactly one original source is required.")
    original = sources[0]
    data = original.read_bytes()
    lines = data.splitlines(keepends=True)
    if not lines or not lines[-1].endswith(b"\n"):
        raise ValueError("This quiescent control requires complete JSONL records.")
    records = [json.loads(line) for line in lines]
    if args.incomplete:
        end = next(
            i + 1
            for i, record in enumerate(records)
            if record.get("type") == "response_item"
            and record.get("payload", {}).get("type") in {"function_call", "custom_tool_call"}
        )
        lines, records = lines[:end], records[:end]
    prefix = b"".join(lines)
    copied = copy_home / original.relative_to(original_home)
    if copied.exists():
        if not args.existing_copy or copied.read_bytes() != prefix:
            raise ValueError("An existing copy must match this exact source prefix.")
    copied.parent.mkdir(parents=True, exist_ok=True)
    copied.write_bytes(prefix)
    held = root / "originals-held" / original.name
    held.parent.mkdir(exist_ok=True)
    if held.exists():
        raise ValueError("A held original already exists; restore it first.")
    original.rename(held)
    ancestor_restore = None
    original_ancestor_restore = None
    try:
        if args.without_ancestor:
            parent_id = records[0]["payload"]["history_base"]["thread_id"]
            parents = find_rollouts_by_thread_id(parent_id, home=copy_home)
            if len(parents) != 1:
                raise ValueError("This negative requires one previously copied parent.")
            parent_copy = parents[0]
            parent_held = root / "originals-held" / ("copy-" + parent_copy.name)
            if parent_held.exists():
                raise ValueError("A copied ancestor is already held.")
            parent_copy.rename(parent_held)
            ancestor_restore = (parent_held, parent_copy)
        if args.hide_original_ancestor:
            parent_id = records[0]["payload"]["history_base"]["thread_id"]
            parents = find_rollouts_by_thread_id(parent_id, home=original_home)
            if len(parents) != 1:
                raise ValueError("Exactly one original ancestor is required.")
            parent_original = parents[0]
            parent_held = root / "originals-held" / ("ancestor-" + parent_original.name)
            if parent_held.exists():
                raise ValueError("An original ancestor is already held.")
            parent_original.rename(parent_held)
            original_ancestor_restore = (parent_held, parent_original)
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("b5-fork.py")),
                args.label,
                args.source_id,
                str(args.prompt),
                "--model",
                "gpt-6.1-sol",
                "--isolate",
                "--guarded",
            ],
            check=False,
        )
        report = {
            "original_path_unavailable_during_fork": not original.exists(),
            "original_sha256": hashlib.sha256(data).hexdigest(),
            "prefix_sha256": hashlib.sha256(prefix).hexdigest(),
            "prefix_bytes": len(prefix),
            "prefix_records": len(records),
            "pending_calls": pending_calls(records),
            "copy_unchanged": copied.read_bytes() == prefix,
            "held_original_unchanged": held.read_bytes() == data,
            "original_auth_copied": False,
            "copy_home_independently_logged_in": True,
            "copied_ancestor_unavailable": bool(ancestor_restore),
            "original_ancestor_unavailable": bool(original_ancestor_restore),
        }
        (root / "captures" / args.label / "copy-observation.json").write_text(json.dumps(report, indent=2) + "\n")
        return result.returncode
    finally:
        if ancestor_restore:
            ancestor_restore[0].rename(ancestor_restore[1])
        if original_ancestor_restore:
            original_ancestor_restore[0].rename(original_ancestor_restore[1])
        if original.exists():
            raise ValueError("Original path reappeared; preserve both files for inspection.")
        held.rename(original)


if __name__ == "__main__":
    raise SystemExit(main())
