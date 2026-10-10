"""Instrumented model-only control; not evidence of the unmodified product wire."""

import json
import os
import runpy
import sys
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[1] / "b3_instrumentation/sitecustomize.py"))

if sys.argv[1:3] == ["hook", "codex-policy-check"]:
    from forge.cli.hooks import codex_policy_feedback

    original = codex_policy_feedback.render_policy_feedback

    def model_only(*args, **kwargs):
        wire = original(*args, **kwargs)
        if wire:
            capture = Path(json.loads(Path(os.environ["PROBE_CONTROL"]).read_text())["capture"])
            (capture / "unmodified-product-wire.json").write_text(wire)
            payload = json.loads(wire)
            payload.pop("systemMessage", None)
            return json.dumps(payload)
        return wire

    codex_policy_feedback.render_policy_feedback = model_only
