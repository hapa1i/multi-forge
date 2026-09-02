#!/usr/bin/env python3
"""Capture or compare privacy-preserving facts for real extension paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import NotRequired, TypedDict

PROTECTED_PATHS = {
    "claude_settings": Path(".claude/settings.json"),
    "claude_local_settings": Path(".claude/settings.local.json"),
    "claude_commands": Path(".claude/commands"),
    "claude_agents": Path(".claude/agents"),
    "claude_skills": Path(".claude/skills"),
    "codex_skills": Path(".agents/skills"),
}


class ProtectedPathFacts(TypedDict):
    exists: bool
    kind: str | None
    mode: str | None
    digest: str | None
    error: NotRequired[str]


class ProtectedSnapshot(TypedDict):
    schema_version: int
    targets: dict[str, ProtectedPathFacts]


def _hash_path(path: Path) -> str:
    digest = hashlib.sha256()

    def add(node: Path, relative: str) -> None:
        metadata = node.lstat()
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(oct(stat.S_IMODE(metadata.st_mode)).encode())
        digest.update(b"\0")
        if node.is_symlink():
            digest.update(b"symlink\0")
            digest.update(os.readlink(node).encode("utf-8", errors="surrogateescape"))
        elif node.is_dir():
            digest.update(b"directory\0")
            for child in sorted(node.iterdir(), key=lambda item: os.fsencode(item.name)):
                child_relative = f"{relative}/{child.name}" if relative else child.name
                add(child, child_relative)
        elif node.is_file():
            digest.update(b"file\0")
            with node.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            digest.update(b"other\0")

    add(path, "")
    return f"sha256:{digest.hexdigest()}"


def _facts(path: Path) -> ProtectedPathFacts:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return {"exists": False, "kind": None, "mode": None, "digest": None}
    except (OSError, UnicodeError) as exc:
        return {
            "exists": True,
            "kind": "unreadable",
            "mode": None,
            "digest": None,
            "error": type(exc).__name__,
        }

    try:
        if path.is_symlink():
            kind = "symlink"
        elif path.is_dir():
            kind = "directory"
        elif path.is_file():
            kind = "file"
        else:
            kind = "other"
        return {
            "exists": True,
            "kind": kind,
            "mode": oct(stat.S_IMODE(metadata.st_mode)),
            "digest": _hash_path(path),
        }
    except (OSError, UnicodeError) as exc:
        return {
            "exists": True,
            "kind": "unreadable",
            "mode": None,
            "digest": None,
            "error": type(exc).__name__,
        }


def capture(home: Path) -> ProtectedSnapshot:
    return {
        "schema_version": 1,
        "targets": {label: _facts(home / relative) for label, relative in PROTECTED_PATHS.items()},
    }


def write_capture(path: Path, snapshot: ProtectedSnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _unreadable_labels(snapshot: object) -> list[str]:
    if not isinstance(snapshot, dict):
        return list(PROTECTED_PATHS)
    targets = snapshot.get("targets")
    if not isinstance(targets, dict):
        return list(PROTECTED_PATHS)
    return [
        label
        for label in PROTECTED_PATHS
        if not isinstance(targets.get(label), dict) or targets[label].get("kind") == "unreadable"
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("capture", "compare"))
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--home", type=Path, default=Path.home())
    args = parser.parse_args()

    current = capture(args.home)
    unreadable = _unreadable_labels(current)
    if unreadable:
        print(
            json.dumps(
                {
                    "status": "error",
                    "reason": "protected_paths_unreadable",
                    "targets": unreadable,
                }
            ),
            file=sys.stderr,
        )
        return 2

    if args.action == "capture":
        write_capture(args.snapshot, current)
        print(
            json.dumps(
                {"status": "captured", "target_count": len(PROTECTED_PATHS)},
                sort_keys=True,
            )
        )
        return 0

    try:
        baseline = json.loads(args.snapshot.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "reason": "baseline_unreadable",
                    "error": type(exc).__name__,
                }
            ),
            file=sys.stderr,
        )
        return 2

    baseline_unreadable = _unreadable_labels(baseline) if isinstance(baseline, dict) else list(PROTECTED_PATHS)
    if baseline_unreadable:
        print(
            json.dumps(
                {
                    "status": "error",
                    "reason": "baseline_incomplete",
                    "targets": baseline_unreadable,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    baseline_targets = baseline.get("targets", {}) if isinstance(baseline, dict) else {}
    changed = [label for label in PROTECTED_PATHS if baseline_targets.get(label) != current["targets"][label]]
    print(
        json.dumps(
            {"status": "match" if not changed else "changed", "changed": changed},
            sort_keys=True,
        )
    )
    return 0 if not changed else 1


if __name__ == "__main__":
    raise SystemExit(main())
