"""Per-session manifest storage.

Path: <forge_root>/.forge/sessions/<session_name>/forge.session.json

Schema: v1 only (no migration).

Session manifests are treated as a strict contract:
- No schema migration
- No unknown field preservation
- Invalid manifests fail fast on read

Writes always produce schema v1.

Invariant: session names are globally unique across all worktrees (enforced by
IndexStore.add_session). The directory name IS the session name.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, Callable, get_origin, get_type_hints

import dacite

from forge.core.state import atomic_write_json, now_iso
from forge.core.state.lock import file_lock_for_target
from forge.core.typing_helpers import unwrap_optional

from .exceptions import (
    ManifestCorruptedError,
    ManifestValidationError,
    SessionFileNotFoundError,
)
from .models import SCHEMA_VERSION, SessionState, session_state_to_dict
from .validation import validate_name

_SUPPORTED_SCHEMA_VERSIONS = {1}

MANIFEST_FILENAME = "forge.session.json"
MANIFEST_DIR = ".forge"
SESSIONS_DIR = "sessions"

HOOK_LOCK_TIMEOUT_S = 0.2
CLI_LOCK_TIMEOUT_S = 5.0

_store_logger = logging.getLogger(__name__)


def strip_preview_memory_doc_lists(data: dict[str, Any], session_name: str = "") -> None:
    """Strip removed ``designated_docs`` from pre-simplification manifests.

    Session manifests no longer persist per-session doc lists. Old manifests
    written before the simplification may contain ``designated_docs`` in
    ``intent.memory`` or ``overrides.memory``. This strips them before dacite
    so strict deserialization succeeds. Non-empty lists trigger a warning per
    coding-standards section 5.
    """
    had_nonempty = False
    for section in ("intent", "overrides"):
        section_obj = data.get(section)
        if not isinstance(section_obj, dict):
            continue
        mem = section_obj.get("memory")
        if isinstance(mem, dict) and "designated_docs" in mem:
            docs = mem.pop("designated_docs")
            if docs:
                had_nonempty = True
    if had_nonempty:
        _store_logger.warning(
            "Session '%s' had session-scoped memory docs (designated_docs), "
            "no longer supported; stripped on read. "
            "Project docs via passports are unaffected.",
            session_name,
        )


# --- Free functions — use these for path construction everywhere (avoid drift) ---


def get_sessions_dir(forge_root: str | Path) -> Path:
    """Return the sessions directory for a Forge project.

    Returns: <forge_root>/.forge/sessions/
    """
    return Path(forge_root) / MANIFEST_DIR / SESSIONS_DIR


def get_manifest_path(forge_root: str | Path, session_name: str) -> Path:
    """Return the manifest path for a specific session.

    Returns: <forge_root>/.forge/sessions/<session_name>/forge.session.json
    """
    return Path(forge_root) / MANIFEST_DIR / SESSIONS_DIR / session_name / MANIFEST_FILENAME


class SessionStore:
    """Read/write session state to per-session manifest directory.

    Each session has its own directory under <forge_root>/.forge/sessions/<name>/.
    Multiple sessions can coexist in the same Forge project.
    """

    def __init__(self, forge_root: str, session_name: str) -> None:
        """Initialize store for a specific session in a Forge project.

        Args:
            forge_root: Absolute path to the Forge project root (where .forge/ lives).
            session_name: Session name (must be valid per validate_name).
        """
        self._forge_root = Path(forge_root).resolve()
        self._session_name = session_name
        self._manifest_path = get_manifest_path(self._forge_root, session_name)

    @property
    def manifest_path(self) -> Path:
        """Return the full path to the manifest file."""
        return self._manifest_path

    @property
    def forge_root(self) -> Path:
        """Return the Forge project root."""
        return self._forge_root

    @property
    def session_name(self) -> str:
        """Return the session name."""
        return self._session_name

    @property
    def session_dir(self) -> Path:
        """Return the session directory (parent of manifest file)."""
        return self._manifest_path.parent

    def exists(self) -> bool:
        """Check if a manifest exists in this worktree."""
        return self._manifest_path.is_file()

    def read_raw(self) -> dict[str, Any] | None:
        """Read manifest as raw JSON dict, skipping validation/deserialization.

        For best-effort field extraction when full parsing fails (e.g. force-delete
        needs confirmed.claude_session_id from a schema-mismatched manifest).

        Returns None if the file doesn't exist or isn't valid JSON.
        """
        if not self.exists():
            return None
        try:
            with open(self._manifest_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def read(self) -> SessionState:
        """Read and parse the session manifest.

        Schema v1 only. No migration, no unknown field preservation.

        Raises:
            SessionFileNotFoundError: If manifest doesn't exist.
            ManifestCorruptedError: If manifest cannot be parsed.
            ManifestValidationError: If manifest is missing required fields.
        """
        if not self.exists():
            raise SessionFileNotFoundError(str(self._manifest_path))

        try:
            with open(self._manifest_path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ManifestCorruptedError(str(self._manifest_path), f"invalid JSON: {e}")
        except OSError as e:
            raise ManifestCorruptedError(str(self._manifest_path), f"read error: {e}")

        strip_preview_memory_doc_lists(data, session_name=self._session_name)
        self._validate_data(data)

        try:
            manifest = dacite.from_dict(
                data_class=SessionState,
                data=data,
                config=dacite.Config(strict=True),
            )
        except (dacite.DaciteError, TypeError, KeyError, ValueError) as e:
            raise ManifestCorruptedError(str(self._manifest_path), f"deserialization error: {e}")

        return manifest

    def write(self, manifest: SessionState) -> None:
        """Write the session manifest atomically under lock.

        Uses atomic write pattern via core.state.atomic_write_json.
        Creates session directory if it doesn't exist.
        Acquires the same file lock as update() to prevent CLI write + hook
        update lost-update races (D10).

        Args:
            manifest: The manifest to write.

        Raises:
            InvalidSessionNameError: If manifest name is invalid.
        """
        self.session_dir.mkdir(parents=True, exist_ok=True)

        with file_lock_for_target(target_path=self._manifest_path, timeout_s=CLI_LOCK_TIMEOUT_S):
            self._write_unlocked(manifest)

    def _write_unlocked(self, manifest: SessionState) -> None:
        """Write manifest without acquiring lock (caller must hold it)."""
        validate_name(manifest.name)

        # Enforce invariant: directory name == manifest name (Issue A).
        if manifest.name != self._session_name:
            raise ValueError(
                f"Manifest name '{manifest.name}' does not match store session "
                f"name '{self._session_name}'. This would create a directory/name mismatch."
            )

        data = session_state_to_dict(manifest)
        data["schema_version"] = SCHEMA_VERSION
        atomic_write_json(self._manifest_path, data)

    def delete(self) -> bool:
        """Delete the session directory and its contents.

        Uses shutil.rmtree since the session directory is entirely session-owned.
        Leaves the parent sessions/ directory in place even if empty (D12).

        Returns:
            True if directory was removed, False if it didn't exist.
        """
        session_dir = self.session_dir
        if session_dir.is_dir():
            shutil.rmtree(session_dir, ignore_errors=True)
            return True
        return False

    def update_last_accessed(self) -> SessionState:
        """Update last_accessed_at timestamp and return updated manifest."""

        return self.update(
            timeout_s=CLI_LOCK_TIMEOUT_S,
            mutate=lambda m: setattr(m, "last_accessed_at", now_iso()),
        )

    def update(self, *, timeout_s: float, mutate: Callable[[SessionState], None]) -> SessionState:
        """Update a manifest via a locked read-modify-write cycle.

        This prevents lost updates when multiple processes (CLI + hooks) mutate
        different sections of the manifest concurrently.

        Args:
            timeout_s: How long to wait for the manifest lock.
            mutate: Callback that mutates the loaded manifest in-place.

        Returns:
            The updated manifest after persistence.

        Raises:
            FileLockTimeoutError: If lock cannot be acquired within timeout.
            SessionFileNotFoundError / ManifestCorruptedError / ManifestValidationError: On read failures.
            InvalidSessionNameError: On write failures.
        """

        with file_lock_for_target(target_path=self._manifest_path, timeout_s=timeout_s):
            manifest = self.read()
            mutate(manifest)
            self._write_unlocked(manifest)
            return manifest

    def _validate_data(self, data: dict[str, Any]) -> None:
        """Validate required fields for schema v1.

        The manifest is treated as a strict contract:
        - schema_version must be supported
        - required fields must be present
        - overrides must target valid SessionIntent fields only

        Raises:
            ManifestCorruptedError: If schema version is unsupported or types are invalid.
            ManifestValidationError: If required fields are missing.
        """
        missing: list[str] = []

        # Check schema version
        if "schema_version" not in data:
            missing.append("schema_version")
        elif data["schema_version"] not in _SUPPORTED_SCHEMA_VERSIONS:
            raise ManifestCorruptedError(
                str(self._manifest_path),
                f"incompatible schema version {data['schema_version']} "
                f"(this Forge expects {sorted(_SUPPORTED_SCHEMA_VERSIONS)}). "
                f"Delete this session and recreate it.",
            )

        # Overrides are required (empty dict allowed)
        if "overrides" not in data:
            missing.append("overrides")
        elif not isinstance(data["overrides"], dict):
            raise ManifestCorruptedError(str(self._manifest_path), "overrides must be an object")

        if "name" not in data:
            missing.append("name")

        if "created_at" not in data:
            missing.append("created_at")
        if "last_accessed_at" not in data:
            missing.append("last_accessed_at")

        if "intent" not in data:
            missing.append("intent")
            intent: dict[str, Any] = {}
        else:
            intent_obj = data.get("intent")
            if intent_obj is None or not isinstance(intent_obj, dict):
                raise ManifestCorruptedError(str(self._manifest_path), "intent must be an object")
            intent = intent_obj
        # Check intent.proxy fields (optional; but if present must be complete)
        proxy = intent.get("proxy")
        if proxy is not None:
            if not isinstance(proxy, dict):
                raise ManifestCorruptedError(str(self._manifest_path), "intent.proxy must be an object")

            if "template" not in proxy:
                missing.append("intent.proxy.template")
            if "base_url" not in proxy:
                missing.append("intent.proxy.base_url")

        # Strict overrides schema: keys must be valid SessionIntent paths
        overrides = data.get("overrides")
        if isinstance(overrides, dict):
            _validate_overrides_schema(overrides, str(self._manifest_path))

        # Optional: confirmed.started_with_proxy (B2.1.6)
        confirmed = data.get("confirmed", {})
        started_with_proxy = confirmed.get("started_with_proxy")
        if started_with_proxy is not None:
            if not isinstance(started_with_proxy, dict):
                raise ManifestCorruptedError(
                    str(self._manifest_path),
                    "confirmed.started_with_proxy must be an object",
                )

            base_url = started_with_proxy.get("base_url")
            if not isinstance(base_url, str) or not base_url:
                raise ManifestCorruptedError(
                    str(self._manifest_path),
                    "confirmed.started_with_proxy.base_url is required",
                )

            proxy_id = started_with_proxy.get("proxy_id")
            if proxy_id is not None and not isinstance(proxy_id, str):
                raise ManifestCorruptedError(
                    str(self._manifest_path),
                    "confirmed.started_with_proxy.proxy_id must be a string",
                )

            template = started_with_proxy.get("template")
            if template is not None and not isinstance(template, str):
                raise ManifestCorruptedError(
                    str(self._manifest_path),
                    "confirmed.started_with_proxy.template must be a string",
                )

            port = started_with_proxy.get("port")
            if port is not None and not isinstance(port, int):
                raise ManifestCorruptedError(
                    str(self._manifest_path),
                    "confirmed.started_with_proxy.port must be an integer",
                )

        if missing:
            raise ManifestValidationError(str(self._manifest_path), missing)


def _is_dict_type(tp: Any) -> bool:
    """Check if a type annotation is a dict type (dict, Dict, dict[...])."""
    return get_origin(tp) is dict or tp is dict


def _collect_dataclass_field_names(cls: type[Any]) -> set[str]:
    return {f.name for f in fields(cls) if not f.name.startswith("_")}


def _collect_dataclass_field_types(cls: type[Any]) -> dict[str, Any]:
    # Use get_type_hints so forward refs and Optional are resolved.
    return get_type_hints(cls)


def _validate_overrides_schema(overrides: dict[str, Any], manifest_path: str) -> None:
    """Validate that override keys target only real SessionIntent fields.

    SessionState.overrides is a dict, so dacite cannot enforce its schema.
    We validate it manually against the SessionIntent dataclass structure.

    Rules:
    - No unknown keys at any level
    - No `custom` namespace
    - Only nested dataclass fields may contain nested dict overrides
    """
    from .models import SessionIntent

    _validate_overrides_dict_against_dataclass(
        overrides=overrides,
        cls=SessionIntent,
        path_prefix="overrides",
        manifest_path=manifest_path,
    )


def _validate_overrides_dict_against_dataclass(
    overrides: dict[str, Any],
    cls: Any,
    path_prefix: str,
    manifest_path: str,
) -> None:
    if not is_dataclass(cls):
        raise ManifestCorruptedError(manifest_path, f"internal error: {cls} is not a dataclass")

    if not isinstance(cls, type):
        raise ManifestCorruptedError(manifest_path, f"internal error: {cls} is not a type")

    valid_fields = _collect_dataclass_field_names(cls)
    type_hints = _collect_dataclass_field_types(cls)

    for key, value in overrides.items():
        if key == "custom":
            raise ManifestCorruptedError(manifest_path, "overrides.custom is not supported")

        if key not in valid_fields:
            raise ManifestCorruptedError(manifest_path, f"unknown override key: {path_prefix}.{key}")

        field_type = type_hints.get(key)
        if field_type is None:
            # Should not happen for normal dataclasses; treat as schema error.
            raise ManifestCorruptedError(manifest_path, f"missing type hint for {path_prefix}.{key}")

        actual_type = unwrap_optional(field_type)

        # Nested dict overrides are only allowed for nested dataclasses or dict-typed fields.
        if isinstance(value, dict):
            if is_dataclass(actual_type):
                _validate_overrides_dict_against_dataclass(
                    overrides=value,
                    cls=actual_type,
                    path_prefix=f"{path_prefix}.{key}",
                    manifest_path=manifest_path,
                )
            elif not _is_dict_type(actual_type):
                raise ManifestCorruptedError(
                    manifest_path,
                    f"{path_prefix}.{key} does not support nested override keys",
                )
            # else: dict-typed field — accept any dict value without schema validation
