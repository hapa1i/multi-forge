"""Opaque join between a managed Responses create and a foreground native turn."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from forge.core.run_id import is_valid_run_id


def turn_reference(run_id: str, thread_id: str, turn_id: str) -> str:
    """Scope the native UUIDs to this launch before recording their association."""
    material = f"{run_id}/{UUID(thread_id)}/{UUID(turn_id)}"
    return hashlib.sha256(material.encode("ascii")).hexdigest()


def request_turn_reference(body: dict[str, Any] | None, run_id: str | None) -> str | None:
    if not run_id or not is_valid_run_id(run_id):
        return None
    metadata = (body or {}).get("client_metadata")
    if not isinstance(metadata, dict):
        return None
    raw = metadata.get("x-codex-turn-metadata")
    if not isinstance(raw, str) or len(raw) > 16_384:
        return None
    try:
        native = json.loads(raw)
        if native["request_kind"] != "turn":
            return None
        thread, turn = metadata["thread_id"], metadata["turn_id"]
        if (thread, turn) != (native["thread_id"], native["turn_id"]):
            return None
        if not isinstance(thread, str) or not isinstance(turn, str):
            return None
        return turn_reference(run_id, thread, turn)
    except (TypeError, ValueError, KeyError, RecursionError):
        return None
