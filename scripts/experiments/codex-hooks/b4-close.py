#!/usr/bin/env python3
"""Close only an owned B4 fixture, retaining pre-sweep observations and evidence."""

import argparse
import hashlib
import json
import runpy
import signal
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
RUNTIME = runpy.run_path(str(SCRIPTS / "probe-runtime.py"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    assert (root / "B4_ROUND").read_text().strip() == "independent-b4-round-v1"
    known = {}
    for registry in (root / "captures").glob("*/run/processes.jsonl"):
        for line in registry.read_text().splitlines():
            row = json.loads(line)
            known[row["pid"]] = row
    before = RUNTIME["living"](known)
    RUNTIME["signal_owned"](before, signal.SIGTERM)
    if before:
        time.sleep(1)
    stubborn = RUNTIME["living"](known)
    RUNTIME["signal_owned"](stubborn, signal.SIGKILL)
    if stubborn:
        time.sleep(0.5)
    remaining = RUNTIME["living"](known)
    assert not remaining
    auth = root / "codex-home/auth.json"
    assert not auth.is_symlink()
    present = auth.exists()
    auth.unlink(missing_ok=True)
    host = json.loads((root / "host-config-hashes.json").read_text())
    after = {
        path: hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None for path in host
    }
    report = {
        "closed_at": time.time(),
        "survivors_before_sweep": before,
        "kill_escalation": stubborn,
        "remaining": remaining,
        "fixture_auth_removed": present and not auth.exists(),
        "host_config_hashes_unchanged": host == after,
        "qualification": "Only recorded host config bytes are compared; unchanged bytes cannot prove token validity or remote revocation. The real Claude login is not owned or removed by this fixture.",
    }
    (root / "teardown.json").write_text(json.dumps(report, indent=2) + "\n")
    (root / "CLOSED").write_text(
        "Owned login removed and recorded processes gone; preserve this evidence and use a new round.\n"
    )
    print(json.dumps({"closed": True, "remaining": len(remaining)}))


if __name__ == "__main__":
    main()
