"""B4 observation: B3 stream/provenance capture plus copies of ephemeral enrollment receipts."""

import atexit
import json
import os
import runpy
import sys
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[1] / "b3_instrumentation/sitecustomize.py"))


def retain_receipts() -> None:
    project, session = os.environ.get("FORGE_FORGE_ROOT"), os.environ.get("FORGE_SESSION")
    if sys.argv[1:2] != ["hook"] or not project or not session:
        return
    capture = Path(json.loads(Path(os.environ["PROBE_CONTROL"]).read_text())["capture"])
    capture.mkdir(parents=True, exist_ok=True)
    for name in ("observation-receipt.json", "context-receipt.json"):
        receipt = Path(project) / ".forge/sessions" / session / "codex" / name
        if receipt.is_file():
            (capture / f"{os.getpid()}-{name}").write_bytes(receipt.read_bytes())


atexit.register(retain_receipts)
