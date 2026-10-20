"""Paths for cleanup inventories that must outlive their source checkout."""

from __future__ import annotations

import hashlib
from pathlib import Path

from forge.core.paths import get_forge_home

from .validation import validate_name


def cleanup_state_path(forge_root: str | Path, name: str) -> Path:
    """Return the external retry inventory for one project-scoped session name."""
    validate_name(name)
    identity = str(Path(forge_root).expanduser().resolve()) + "\0" + name
    return get_forge_home() / "session-cleanup" / (hashlib.sha256(identity.encode()).hexdigest() + ".json")
