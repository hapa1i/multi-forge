"""Regression: forge.__version__ must not drift from the canonical pyproject version.

Bug: ``src/forge/__init__.py`` hardcoded ``__version__ = "0.5.0"`` while the package
shipped as 0.6.0. ``cli/hooks/commands.py`` stamps ``forge.__version__`` into every
session manifest's ``PolicyConfirmed.forge_version`` and ``core/workqueue/queue.py``
into every work-queue record, so the stale literal silently wrote the wrong version
into durable state that telemetry reads back.

Root cause: the version was a hardcoded literal independent of ``pyproject.toml``.
Fix: derive ``__version__`` from ``importlib.metadata`` so ``pyproject.toml`` is the
single source of truth (``src/forge/__init__.py``).
"""

import tomllib
from pathlib import Path

import pytest

import forge

pytestmark = pytest.mark.regression


def _pyproject_version() -> str:
    """Read ``[project].version`` from the repo's pyproject.toml (the canonical source)."""
    for parent in Path(__file__).resolve().parents:
        pyproject = parent / "pyproject.toml"
        if pyproject.exists():
            with pyproject.open("rb") as fh:
                return str(tomllib.load(fh)["project"]["version"])
    raise AssertionError("pyproject.toml not found above the regression test tree")


def test_version_matches_pyproject_single_source() -> None:
    """forge.__version__ equals the canonical pyproject version, not a stale literal."""
    assert forge.__version__ == _pyproject_version()
