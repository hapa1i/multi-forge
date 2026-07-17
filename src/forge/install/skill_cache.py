"""Stable content-addressed cache for compiled runtime skill packages."""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path

from forge.core.paths import get_forge_home
from forge.core.state import atomic_write_bytes, atomic_write_text, file_lock_for_target

from .skill_compiler import CompiledSkillPackage

_CACHE_FORMAT = b"forge-compiled-skill-v1\0"


def compiled_skill_digest(package: CompiledSkillPackage) -> str:
    """Return a deterministic digest over package identity, paths, modes, and bytes."""

    digest = hashlib.sha256(_CACHE_FORMAT)
    _update_digest(digest, package.runtime.value.encode())
    _update_digest(digest, package.name.encode())
    for package_file in sorted(package.files, key=lambda item: item.path.as_posix()):
        _update_digest(digest, package_file.path.as_posix().encode())
        _update_digest(digest, package_file.mode.to_bytes(4, "big"))
        _update_digest(digest, package_file.content)
    return digest.hexdigest()


def _update_digest(digest: "hashlib._Hash", value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def compiled_skill_cache_dir(package: CompiledSkillPackage, *, forge_home: Path | None = None) -> Path:
    """Return the stable cache directory without creating it."""

    root = forge_home or get_forge_home()
    return (
        root
        / "cache"
        / "compiled-skills"
        / "v1"
        / package.runtime.value
        / package.name
        / compiled_skill_digest(package)
    )


def materialize_compiled_skill(package: CompiledSkillPackage, *, forge_home: Path | None = None) -> Path:
    """Atomically materialize package files and return their stable cache root."""

    package_root = compiled_skill_cache_dir(package, forge_home=forge_home)
    marker = package_root / ".complete"
    expected_digest = compiled_skill_digest(package)
    with file_lock_for_target(target_path=marker, timeout_s=5.0):
        if _cache_is_current(package, package_root, marker, expected_digest):
            return package_root
        for package_file in sorted(package.files, key=lambda item: item.path.as_posix()):
            target = package_root.joinpath(*package_file.path.parts)
            atomic_write_bytes(target, package_file.content, mode=package_file.mode)
        atomic_write_text(marker, expected_digest + "\n", mode=0o644)
    return package_root


def _cache_is_current(
    package: CompiledSkillPackage,
    package_root: Path,
    marker: Path,
    expected_digest: str,
) -> bool:
    try:
        if marker.is_symlink():
            return False
        if marker.read_text(encoding="utf-8").strip() != expected_digest:
            return False
        for package_file in package.files:
            cached = package_root.joinpath(*package_file.path.parts)
            if cached.is_symlink() or not cached.is_file():
                return False
            if cached.read_bytes() != package_file.content:
                return False
            if stat.S_IMODE(cached.stat().st_mode) != package_file.mode:
                return False
    except OSError:
        return False
    return True


__all__ = [
    "compiled_skill_cache_dir",
    "compiled_skill_digest",
    "materialize_compiled_skill",
]
