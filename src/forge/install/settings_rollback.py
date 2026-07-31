"""Exact rollback snapshots for Claude settings and Forge ownership sidecars."""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

from forge.core.state import atomic_write_bytes

from .settings_merge import find_added_files


@dataclass(frozen=True)
class SettingsRollbackState:
    """Exact pre-apply settings and ownership-sidecar state."""

    settings_path: Path
    settings_content: bytes | None
    settings_mode: int | None
    added_files: tuple[tuple[Path, bytes, int], ...]


def capture_settings_rollback_state(settings_path: Path) -> SettingsRollbackState:
    """Capture settings and all ownership sidecars before an apply mutation."""

    if settings_path.is_file():
        settings_content = settings_path.read_bytes()
        settings_mode = stat.S_IMODE(settings_path.stat().st_mode)
    else:
        settings_content = None
        settings_mode = None
    added_files = tuple(
        (path, path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        for path in find_added_files(settings_path)
    )
    return SettingsRollbackState(
        settings_path=settings_path,
        settings_content=settings_content,
        settings_mode=settings_mode,
        added_files=added_files,
    )


def restore_settings_rollback_state(state: SettingsRollbackState) -> list[str]:
    """Best-effort restore settings and ownership sidecars after apply failure."""

    failures: list[str] = []
    try:
        if state.settings_content is None:
            state.settings_path.unlink(missing_ok=True)
        else:
            atomic_write_bytes(
                state.settings_path,
                state.settings_content,
                mode=state.settings_mode,
            )
    except OSError:
        failures.append(str(state.settings_path))

    prior_added_paths = {path for path, _content, _mode in state.added_files}
    try:
        current_added_files = find_added_files(state.settings_path)
    except OSError:
        failures.append(f"{state.settings_path} ownership sidecars")
        current_added_files = []
    for path in current_added_files:
        if path in prior_added_paths:
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            failures.append(str(path))
    for path, content, mode in state.added_files:
        try:
            atomic_write_bytes(path, content, mode=mode)
        except OSError:
            failures.append(str(path))
    return failures
