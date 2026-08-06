"""O006 regression: non-object confirmed state is manifest corruption.

Root cause: ``SessionStore._validate_data`` called ``.get()`` on the unvalidated
``confirmed`` value, so explicit null and other non-object values leaked a raw
``AttributeError`` instead of the typed durable-state classification.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.session import SessionStore, create_session_state
from forge.session.exceptions import ManifestCorruptedError

pytestmark = pytest.mark.regression


def test_explicit_null_confirmed_is_corruption_and_preserves_manifest(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    store = SessionStore(str(project), "broken-confirmed")
    store.write(create_session_state("broken-confirmed", worktree_path=str(project)))

    data = json.loads(store.manifest_path.read_text())
    data["confirmed"] = None
    store.manifest_path.write_text(json.dumps(data))
    original = store.manifest_path.read_bytes()

    with pytest.raises(ManifestCorruptedError, match="confirmed must be an object"):
        store.read()

    assert store.manifest_path.read_bytes() == original
