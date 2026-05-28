"""Regression: stale designated_docs with traversal paths are stripped on read.

Bug: legacy ``memory.designated_docs`` overrides could contain absolute or
traversal shadow paths. The old ``forge memory shadows show`` read those paths
directly, allowing outside-root content to be printed.

Fix: ``designated_docs`` was removed from ``MemoryIntent``. Old manifests are
sanitized by ``strip_preview_memory_doc_lists()`` on read, which strips the
field and logs a warning for non-empty entries.

Affected files: src/forge/session/store.py, src/forge/session/models.py
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from forge.session.store import SessionStore, strip_preview_memory_doc_lists

pytestmark = pytest.mark.regression


def test_stale_designated_docs_stripped_on_read(tmp_path: Path) -> None:
    """Old manifest with designated_docs reads without error; field is gone."""
    from forge.session.models import create_session_state

    state = create_session_state("s1", worktree_path=str(tmp_path))
    store = SessionStore(str(tmp_path), "s1")
    store.write(state)

    manifest_path = store._manifest_path
    with open(manifest_path, encoding="utf-8") as f:
        raw = json.load(f)

    intent = raw.setdefault("intent", {})
    if intent.get("memory") is None:
        intent["memory"] = {}
    intent["memory"]["designated_docs"] = [
        {"path": "/etc/passwd", "strategy": "generic", "shadows": "docs/impl_notes.md"}
    ]
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(raw, f)

    loaded = store.read()
    assert not hasattr(loaded.intent.memory, "designated_docs") if loaded.intent.memory else True


def test_strip_logs_warning_for_nonempty(caplog: pytest.LogCaptureFixture) -> None:
    """Non-empty designated_docs triggers a logger warning."""
    data: dict = {
        "intent": {"memory": {"designated_docs": [{"path": "x.md", "strategy": "generic"}]}},
        "overrides": {},
    }
    with caplog.at_level(logging.WARNING, logger="forge.session.store"):
        strip_preview_memory_doc_lists(data, session_name="test-session")
    assert "designated_docs" in caplog.text
    assert "no longer supported" in caplog.text
    assert "intent" in data and "designated_docs" not in data["intent"].get("memory", {})


def test_strip_silent_for_empty() -> None:
    """Empty designated_docs is stripped without warning."""
    data: dict = {
        "intent": {"memory": {"designated_docs": []}},
        "overrides": {},
    }
    strip_preview_memory_doc_lists(data, session_name="test-session")
    assert "designated_docs" not in data["intent"].get("memory", {})


def test_overrides_designated_docs_stripped_on_read(tmp_path: Path) -> None:
    """Stale designated_docs in overrides is stripped on read."""
    from forge.session.models import create_session_state

    state = create_session_state("s1", worktree_path=str(tmp_path))
    store = SessionStore(str(tmp_path), "s1")
    store.write(state)

    manifest_path = store._manifest_path
    with open(manifest_path, encoding="utf-8") as f:
        raw = json.load(f)

    overrides = raw.setdefault("overrides", {})
    overrides.setdefault("memory", {})["designated_docs"] = [{"path": "docs/notes.md", "strategy": "generic"}]
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(raw, f)

    loaded = store.read()
    mem_overrides = loaded.overrides.get("memory", {}) if isinstance(loaded.overrides, dict) else {}
    assert "designated_docs" not in mem_overrides


def test_effective_intent_succeeds_after_stripping(tmp_path: Path) -> None:
    """Both intent and overrides designated_docs are stripped; effective intent succeeds."""
    from forge.session.effective import compute_effective_intent
    from forge.session.models import create_session_state

    state = create_session_state("s1", worktree_path=str(tmp_path))
    store = SessionStore(str(tmp_path), "s1")
    store.write(state)

    manifest_path = store._manifest_path
    with open(manifest_path, encoding="utf-8") as f:
        raw = json.load(f)

    intent = raw.setdefault("intent", {})
    if intent.get("memory") is None:
        intent["memory"] = {}
    intent["memory"]["designated_docs"] = [{"path": "docs/log.md", "strategy": "changelog"}]
    overrides = raw.setdefault("overrides", {})
    overrides.setdefault("memory", {})["designated_docs"] = [{"path": "docs/extra.md", "strategy": "generic"}]
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(raw, f)

    loaded = store.read()
    effective = compute_effective_intent(loaded)
    assert not hasattr(effective.memory, "designated_docs") if effective.memory else True
