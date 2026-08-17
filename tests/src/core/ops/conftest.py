"""Shared fixtures for command-core operation tests."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def forbid_codex_thread_index_sync(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Make a Codex op fail if a deleted identity reaches index reconciliation."""

    def _forbid(module_name: str) -> None:
        monkeypatch.setattr(
            f"forge.core.ops.{module_name}.sync_codex_thread_to_index",
            MagicMock(side_effect=AssertionError("deleted identity must not reach index reconciliation")),
        )

    return _forbid
