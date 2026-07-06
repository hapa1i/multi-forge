"""Factories for Codex headless test results."""

from __future__ import annotations

from typing import Any


def codex_result(**overrides: Any) -> Any:
    """Build a ``HeadlessResult`` shaped like ``CodexHeadlessInvoker.run`` returns."""
    from forge.core.invoker.types import HeadlessResult

    defaults: dict[str, Any] = {
        "label": "codex",
        "stdout": "",
        "stderr": "",
        "returncode": 0,
        "duration_seconds": 0.1,
    }
    defaults.update(overrides)
    return HeadlessResult(**defaults)
