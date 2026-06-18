"""Durable spend-cap state.

Telemetry writes are best-effort, but cap enforcement needs a durable checkpoint so a
storage migration or dropped JSONL write does not silently reset the next proxy restart
to zero spend.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from forge.core.paths import get_forge_home
from forge.core.state import atomic_write_json, now_iso, read_json

CAP_STATE_SCHEMA_VERSION = 1


@dataclass
class CapState:
    proxy_id: str
    monthly_key: str
    monthly_total_micros: int = 0
    daily_window: list[tuple[float, int]] = field(default_factory=list)
    schema_version: int = CAP_STATE_SCHEMA_VERSION
    updated_at: str = field(default_factory=now_iso)


def cap_state_path(proxy_id: str) -> Path:
    return get_forge_home() / "telemetry" / "caps" / f"{proxy_id}.json"


def load_cap_state(proxy_id: str) -> CapState | None:
    path = cap_state_path(proxy_id)
    if not path.exists():
        return None
    raw = read_json(path)
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid cap state at {path}: expected object")
    version = raw.get("schema_version")
    if version != CAP_STATE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported cap state schema_version={version!r} at {path}")
    if raw.get("proxy_id") != proxy_id:
        raise ValueError(f"Cap state proxy_id mismatch at {path}")
    daily_raw = raw.get("daily_window", [])
    if not isinstance(daily_raw, list):
        raise ValueError(f"Invalid cap state daily_window at {path}")
    daily_window: list[tuple[float, int]] = []
    for item in daily_raw:
        if not isinstance(item, list | tuple) or len(item) != 2:
            raise ValueError(f"Invalid cap state daily_window entry at {path}")
        ts, cost = item
        daily_window.append((float(ts), int(cost)))
    return CapState(
        proxy_id=proxy_id,
        monthly_key=str(raw.get("monthly_key") or ""),
        monthly_total_micros=int(raw.get("monthly_total_micros") or 0),
        daily_window=daily_window,
        updated_at=str(raw.get("updated_at") or now_iso()),
    )


def write_cap_state(state: CapState) -> None:
    path = cap_state_path(state.proxy_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent.parent, 0o700)
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    atomic_write_json(
        path,
        {
            "schema_version": CAP_STATE_SCHEMA_VERSION,
            "proxy_id": state.proxy_id,
            "monthly_key": state.monthly_key,
            "monthly_total_micros": state.monthly_total_micros,
            "daily_window": [[ts, cost] for ts, cost in state.daily_window],
            "updated_at": now_iso(),
        },
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
