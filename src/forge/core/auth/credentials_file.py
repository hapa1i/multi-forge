"""File-based credential store (~/.forge/credentials.yaml).

Provides atomic read/write for the credential file with named profiles.
The FileSecretsProvider (in secrets.py) reads from this store;
CLI commands (forge auth login/status/logout) write via these functions.

Schema:
    version: 1
    profiles:
      default:
        LITELLM_API_KEY: "sk-..."
      personal:
        ANTHROPIC_API_KEY: "sk-ant-..."

Security: file permissions set to 0o600 (owner read/write only).
Concurrency: advisory file lock on write to prevent concurrent clobber.
"""

from __future__ import annotations

import os
import re
from io import StringIO
from pathlib import Path
from typing import Any

import yaml

from forge.core.paths import get_forge_home
from forge.core.state import atomic_write_text
from forge.core.state.lock import file_lock_for_target

CREDENTIALS_FILENAME = "credentials.yaml"
SCHEMA_VERSION = 1


class CredentialVersionError(Exception):
    """Credential file has an incompatible schema version.

    Distinct from ValueError (YAML corruption) so callers can distinguish
    "safe to overwrite" from "don't touch — upgrade Forge first".
    """


# Profile names: alphanumeric, hyphens, underscores only
_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def get_credentials_path() -> Path:
    """Return path to ~/.forge/credentials.yaml."""
    return get_forge_home() / CREDENTIALS_FILENAME


def resolve_profile(profile: str | None = None) -> str:
    """Resolve active profile name.

    Args:
        profile: Explicit profile name (from CLI --profile flag).
                 If None, falls back to FORGE_PROFILE env var, then "default".
    """
    if profile is not None:
        return profile
    return os.environ.get("FORGE_PROFILE", "default")


def _validate_profile_name(name: str) -> None:
    """Validate profile name contains only safe characters.

    Raises:
        ValueError: If name contains path separators, spaces, or control chars.
    """
    if not _PROFILE_NAME_RE.match(name):
        raise ValueError(
            f"Invalid profile name '{name}': "
            f"must match [A-Za-z0-9_-] (no spaces, path separators, or special chars)"
        )


def load_credentials(path: Path | None = None) -> dict[str, dict[str, str]]:
    """Load all profiles from the credentials file.

    Returns:
        Dict mapping profile names to their key-value secrets.
        Returns empty dict if file doesn't exist.

    Raises:
        ValueError: If file exists but is malformed.
    """
    creds_path = path or get_credentials_path()
    if not creds_path.exists():
        return {}

    try:
        with open(creds_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(
            f"Corrupt credentials file: {creds_path}\n"
            f"Recovery: mv {creds_path} {creds_path}.corrupt && forge auth login\n"
            f"Parse error: {e}"
        ) from e

    if data is None:
        return {}

    if not isinstance(data, dict):
        raise ValueError(f"credentials.yaml must be a YAML mapping, got {type(data).__name__}")

    version = data.get("version")
    if version is not None and version != SCHEMA_VERSION:
        raise CredentialVersionError(
            f"credentials.yaml has version {version}, but this Forge only supports version {SCHEMA_VERSION}. "
            f"Upgrade Forge or recreate the file with 'forge auth login'."
        )

    profiles = data.get("profiles", {})
    if not isinstance(profiles, dict):
        raise ValueError("credentials.yaml 'profiles' must be a mapping")

    # Validate all profile values are flat string dicts
    for name, secrets in profiles.items():
        if not isinstance(secrets, dict):
            raise ValueError(f"Profile '{name}' must be a mapping")
        for k, v in secrets.items():
            if not isinstance(v, str):
                raise ValueError(f"Profile '{name}' key '{k}' must be a string, got {type(v).__name__}")

    return profiles


def load_profile(profile: str, *, path: Path | None = None) -> dict[str, str]:
    """Load a single profile's secrets.

    Returns empty dict if the profile or file doesn't exist.
    """
    profiles = load_credentials(path)
    return profiles.get(profile, {})


def save_profile(
    profile: str,
    secrets: dict[str, str],
    *,
    path: Path | None = None,
    merge: bool = True,
) -> Path:
    """Save secrets to a profile in the credentials file.

    Uses advisory file lock, atomic write (tempfile + os.replace),
    and 0o600 permissions.

    Args:
        profile: Profile name to save to.
        secrets: Key-value pairs to store.
        path: Override credentials file path (for testing).
        merge: If True, merge with existing profile secrets.
               If False, replace the profile entirely.

    Returns:
        Path to credentials file.

    Raises:
        ValueError: If profile name is invalid.
    """
    _validate_profile_name(profile)

    creds_path = path or get_credentials_path()

    with file_lock_for_target(target_path=creds_path, timeout_s=5.0):
        # Read-modify-write under lock
        try:
            profiles = load_credentials(creds_path)
        except ValueError:
            # Corrupt file — start fresh under lock
            profiles = {}

        if merge and profile in profiles:
            profiles[profile].update(secrets)
        else:
            profiles[profile] = dict(secrets)

        _write_credentials(creds_path, profiles)

    return creds_path


def delete_profile(profile: str, *, path: Path | None = None) -> bool:
    """Delete a profile from the credentials file.

    Returns True if the profile existed, False otherwise.

    Raises:
        ValueError: If profile name is invalid.
    """
    _validate_profile_name(profile)

    creds_path = path or get_credentials_path()

    with file_lock_for_target(target_path=creds_path, timeout_s=5.0):
        try:
            profiles = load_credentials(creds_path)
        except ValueError:
            return False

        if profile not in profiles:
            return False

        del profiles[profile]
        _write_credentials(creds_path, profiles)

    return True


def list_profiles(path: Path | None = None) -> list[str]:
    """Return sorted list of profile names."""
    profiles = load_credentials(path)
    return sorted(profiles.keys())


def _write_credentials(creds_path: Path, profiles: dict[str, dict[str, str]]) -> None:
    """Atomic write of credentials file with 0o600 permissions."""
    creds_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {
        "version": SCHEMA_VERSION,
        "profiles": profiles,
    }

    stream = StringIO()
    stream.write("# Forge Credential Store — managed by `forge auth login`\n\n")
    yaml.safe_dump(data, stream, default_flow_style=False, sort_keys=False)
    atomic_write_text(creds_path, stream.getvalue(), mode=0o600)
