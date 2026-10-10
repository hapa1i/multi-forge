"""Explicit independent B3 homes, restored after ordinary test isolation."""

from __future__ import annotations

import os
import runpy
from pathlib import Path

import pytest

# Capture caller-supplied values before autouse fixtures replace them. There is no
# default to a developer login or to the pytest process's replacement homes.
_INPUTS = {
    key: os.environ.get(key)
    for key in (
        "HOME",
        "CODEX_HOME",
        "FORGE_HOME",
        "FORGE_DEV",
        "PATH",
        "PROBE_ROUND_ROOT",
        "PROBE_CONTROL",
        "PROBE_RUNTIME_IDENTITY",
        "PROBE_TURN_CEILING",
        "PROBE_LAUNCHER",
        "PYTHONPATH",
        "PYTHON_DOTENV_DISABLED",
    )
}


@pytest.fixture
def enrolled_b3_round(monkeypatch, isolate_home, isolate_forge_home, isolate_codex_home):
    """Require the operator's enrolled fixture; never register hooks or copy auth."""
    for key in (
        "HOME",
        "CODEX_HOME",
        "FORGE_HOME",
        "PATH",
        "PROBE_ROUND_ROOT",
        "PROBE_CONTROL",
        "PROBE_RUNTIME_IDENTITY",
        "PROBE_TURN_CEILING",
        "PROBE_LAUNCHER",
    ):
        if not _INPUTS[key]:
            pytest.fail(f"B3 delivery requires an explicitly supplied independent {key}.")
    if _INPUTS["PYTHON_DOTENV_DISABLED"] != "1":
        pytest.fail("B3 delivery requires dotenv disabled before test collection.")
    for key, value in _INPUTS.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_API_KEY"):
        if os.environ.get(key):
            pytest.fail("B3 delivery refuses an API credential in the probe environment.")
    script = Path(__file__).resolve().parents[2] / "scripts/experiments/codex-hooks/b3-run.py"
    round_type = runpy.run_path(str(script))["Round"]
    return round_type(Path(os.environ["PROBE_ROUND_ROOT"]))
