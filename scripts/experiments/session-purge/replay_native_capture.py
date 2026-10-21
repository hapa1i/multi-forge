"""Replay exported synthetic native bytes in an offline container; never invoke a client."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from native_probe_payload import verify_lifecycle


def main() -> None:
    """Restore only verified transcript/companion evidence and run exact cleanup checks."""
    if not Path("/.dockerenv").exists() or Path.cwd() != Path("/probe/workspace"):
        raise ValueError("Replay requires a disposable container at /probe/workspace")
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        raise ValueError("Offline replay must not receive provider credentials")
    captured = Path("/probe/captured")
    inventory = json.loads((captured / "export-inventory.json").read_text())
    for relative, digest in inventory.items():
        path = captured / relative
        if (
            Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or path.is_symlink()
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise ValueError("Captured native evidence failed integrity verification")
    source = captured / "synthetic-transcripts" / "projects"
    destination = Path("/probe/home/.claude/projects")
    if destination.exists():
        raise ValueError("Replay requires a fresh isolated native store")
    shutil.copytree(source, destination)
    files = [{"path": str(path)} for path in sorted(destination.rglob("*")) if path.is_file()]
    result = verify_lifecycle(files)
    result["mode"] = "offline_replay_of_captured_native_bytes"
    result["native_invocations"] = 0
    result["captured_export_inventory_sha256"] = hashlib.sha256(
        (captured / "export-inventory.json").read_bytes()
    ).hexdigest()
    (Path("/probe/evidence") / "replay-result.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
