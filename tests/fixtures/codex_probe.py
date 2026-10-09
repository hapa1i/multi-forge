"""Load standalone Codex probe scripts without invoking model runtimes."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

PROBES = Path(__file__).resolve().parents[2] / "scripts/experiments/codex-hooks"


def load_script(name: str) -> ModuleType:
    """Import one experiment helper for offline tests."""
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), PROBES / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
