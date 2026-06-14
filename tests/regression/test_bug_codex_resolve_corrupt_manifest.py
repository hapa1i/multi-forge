"""Regression: a corrupt Codex manifest was reported as 'session not found'.

Bug: ``resolve_codex_session`` caught broad ``ForgeSessionError`` as "not found", masking
``ManifestCorruptedError``/``ManifestValidationError`` (siblings of, not,
``SessionNotFoundError``), and treated corruption as a scoping miss in the fallback.

Fix: narrow not-found handling to ``SessionNotFoundError``; surface other
``ForgeSessionError`` as a distinct "could not be read (manifest may be corrupt)"
``ForgeOpError`` (src/forge/core/ops/codex_session.py).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from forge.core.ops.codex_session import resolve_codex_session
from forge.core.ops.session import ForgeOpError
from forge.session.exceptions import ManifestCorruptedError, SessionNotFoundError

pytestmark = pytest.mark.regression


def test_corrupt_manifest_on_scoped_read_is_not_reported_as_not_found() -> None:
    manager = MagicMock()
    manager.get_session_entry.side_effect = ManifestCorruptedError("/p/forge.session.json", "invalid JSON")
    with pytest.raises(ForgeOpError) as ei:
        resolve_codex_session(manager, "sess", forge_root=Path("/proj"))
    msg = str(ei.value)
    assert "could not be read" in msg
    assert "not found" not in msg


def test_corrupt_manifest_on_unscoped_fallback_is_not_reported_as_not_found() -> None:
    manager = MagicMock()
    # Scoped lookup misses (legitimate cross-CWD), then the unscoped fallback hits corruption.
    manager.get_session_entry.side_effect = [
        SessionNotFoundError("sess"),
        ManifestCorruptedError("/p/forge.session.json", "deserialization error"),
    ]
    with pytest.raises(ForgeOpError) as ei:
        resolve_codex_session(manager, "sess", forge_root=Path("/proj"))
    assert "could not be read" in str(ei.value)


def test_genuinely_missing_session_still_reports_not_found() -> None:
    manager = MagicMock()
    manager.get_session_entry.side_effect = SessionNotFoundError("sess")
    manager.get_session.side_effect = SessionNotFoundError("sess")
    with pytest.raises(ForgeOpError) as ei:
        resolve_codex_session(manager, "sess", forge_root=Path("/proj"))
    assert "not found" in str(ei.value)
