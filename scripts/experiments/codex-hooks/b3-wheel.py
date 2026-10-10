#!/usr/bin/env python3
"""Exercise one installed wheel through the already trusted B3 dispatcher."""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    root = Path(os.environ["PROBE_ROUND_ROOT"])
    installed = root / "wheel-env"
    if "FORGE_DEV" in os.environ or Path(sys.prefix) != installed:
        raise ValueError("Run with the clean wheel's Python and without FORGE_DEV.")
    import forge

    if not Path(forge.__file__).is_relative_to(installed):
        raise ValueError("Forge did not import from the installed wheel.")
    paths = [root / "codex-home/config.toml", root / "codex-home/hooks.json", root / "forge-home/bin/forge-hook"]
    before = {str(p): digest(p) for p in paths if p.exists()}
    metadata = root / "forge-home/runtime.json"
    original = metadata.read_bytes()
    value = json.loads(original)
    value["forge_binary_path"] = str(installed / "bin/forge")
    metadata.write_text(json.dumps(value, indent=2) + "\n")
    report = {
        "wheel_sha256": digest(next((root / "wheel").glob("*.whl"))),
        "launcher_sha256": digest(installed / "bin/forge"),
        "forge_module": forge.__file__,
        "before": before,
        "metadata_override": value,
    }
    try:
        doctor = subprocess.run(
            [str(installed / "bin/forge"), "extension", "doctor", "--json"], capture_output=True, text=True
        )
        report["doctor"] = json.loads(doctor.stdout)
        report["doctor_exit"] = doctor.returncode
        round_type = runpy.run_path(str(Path(__file__).with_name("b3-run.py")))["Round"]
        runner = round_type(root)
        runner.case("wheel-source", "source", session="b3-wheel")
        runner.case("wheel-off", "stub", session="b3-wheel", feedback=False)
        runner.case("wheel-deny", "source-deny", session="b3-wheel")
    finally:
        metadata.write_bytes(original)
        report["after"] = {str(p): digest(p) for p in paths if p.exists()}
        report["routing_restored"] = metadata.read_bytes() == original
        (root / "wheel-verification.json").write_text(json.dumps(report, indent=2) + "\n")
    assert report["before"] == report["after"]


if __name__ == "__main__":
    main()
