"""Backend config creation (copy templates to installed location)."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from forge.config.loader import get_defaults_dir
from forge.core.paths import get_forge_home


def create_backend_config(
    adapter_type: str,
    source_config: Path | None = None,
) -> Path:
    """Create backend config by copying to installed location.

    Config is shared by all instances of the same adapter type.

    Args:
        adapter_type: Adapter type (e.g., "litellm")
        source_config: Source config file (defaults to defaults/backends/{adapter}.yaml)

    Returns:
        Path to created config file

    Raises:
        ValueError: If adapter type is unknown or source config not found
    """
    backend_dir = get_forge_home() / "backends" / adapter_type
    backend_dir.mkdir(parents=True, exist_ok=True)

    # Determine source config
    if source_config is None:
        # Use convention-based path: defaults/backends/{adapter}.yaml
        defaults_dir = get_defaults_dir()  # src/forge/config/defaults/
        source_config = defaults_dir / "backends" / f"{adapter_type}.yaml"

    if not source_config.exists():
        raise ValueError(
            f"No default config for adapter '{adapter_type}': {source_config}\n"
            f"Either provide --config or create {source_config}"
        )

    # Copy config (idempotent - overwrites if exists)
    dest_config = backend_dir / "config.yaml"
    shutil.copy(source_config, dest_config)
    dest_config.chmod(0o600)

    return dest_config


def get_backend_config_path(adapter_type: str) -> Path:
    """Get path to backend config file.

    Args:
        adapter_type: Adapter type (e.g., "litellm")

    Returns:
        Path to config file (may not exist yet)
    """
    return get_forge_home() / "backends" / adapter_type / "config.yaml"


def is_backend_config_outdated(adapter_type: str) -> bool:
    """Check if installed backend config differs from the default.

    Compares SHA256 digests of the installed config and the default template.
    Returns True if the installed config exists but differs from the default
    (meaning new models or settings may be available).

    Args:
        adapter_type: Adapter type (e.g., "litellm")

    Returns:
        True if installed config is outdated, False otherwise.
    """
    installed = get_backend_config_path(adapter_type)
    if not installed.exists():
        return False  # No config yet — will be created on first use

    default = get_defaults_dir() / "backends" / f"{adapter_type}.yaml"
    if not default.exists():
        return False  # No default to compare against

    installed_digest = hashlib.sha256(installed.read_bytes()).hexdigest()
    default_digest = hashlib.sha256(default.read_bytes()).hexdigest()
    return installed_digest != default_digest
