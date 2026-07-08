"""User-scope hook dispatcher artifact and renderer.

The installed ``~/.forge/bin/forge-hook`` script is intentionally stdlib-only:
hook subprocesses may not have Forge's uv-tool venv on ``PYTHONPATH``, and the
hot no-op path must not pay Forge import cost.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forge import __version__
from forge.core.paths import get_forge_home
from forge.core.state import atomic_write_json, atomic_write_text, now_iso

from .doctor import EXECUTABLE, global_bin_dirs

DISPATCHER_FILENAME = "forge-hook"
DISPATCHER_BIN_DIR = "bin"
RUNTIME_METADATA_FILENAME = "runtime.json"
RUNTIME_METADATA_VERSION = 1

_STAMP_VERSION_RE = re.compile(r'^FORGE_HOOK_DISPATCHER_VERSION = "([^"]*)"$')
_STAMP_SOURCE_RE = re.compile(r'^FORGE_HOOK_DISPATCHER_SOURCE_SHA256 = "([0-9a-f]*)"$')


@dataclass(frozen=True)
class HookDispatcherInstallResult:
    """Paths written when rendering the dispatcher artifact."""

    dispatcher_path: str
    metadata_path: str
    forge_binary_path: str | None


@dataclass(frozen=True)
class HookDispatcherDiagnosis:
    """Doctor-facing status for the installed hook dispatcher shim."""

    path: str
    status: str
    installed_version: str | None
    expected_version: str
    installed_source_sha256: str | None
    expected_source_sha256: str
    metadata_path: str
    metadata_status: str
    forge_binary_path: str | None
    advice: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "status": self.status,
            "installed_version": self.installed_version,
            "expected_version": self.expected_version,
            "installed_source_sha256": self.installed_source_sha256,
            "expected_source_sha256": self.expected_source_sha256,
            "metadata_path": self.metadata_path,
            "metadata_status": self.metadata_status,
            "forge_binary_path": self.forge_binary_path,
            "advice": self.advice,
        }


# Drift guard: _GATE_SOURCE is the embed-safe stdlib copy of
# core.ops.context.find_forge_root plus project_registry canonicalization,
# path-match, and hook-read validation rules. If those rules change, update this
# block and the behavioral parity fixture matrix in test_hook_dispatcher.py
# together; the rendered source hash only detects installed-vs-package staleness.
_GATE_SOURCE = r"""
import json
import os
import sys
from pathlib import Path

PROJECT_REGISTRY_VERSION = 1


def _forge_home() -> Path:
    value = os.environ.get("FORGE_HOME")
    if value:
        return Path(value).expanduser()
    return Path.home() / ".forge"


def _canonicalize(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def _same_existing_path(left: str | Path, right: str | Path) -> bool:
    try:
        return Path(left).samefile(Path(right))
    except OSError:
        return False


def _paths_match(enrolled_path: str | Path, candidate_path: str | Path) -> bool:
    enrolled_key = _canonicalize(enrolled_path)
    candidate_key = _canonicalize(candidate_path)
    return enrolled_key == candidate_key or _same_existing_path(enrolled_key, candidate_key)


def _find_forge_root(start: Path) -> Path | None:
    current = start.expanduser().resolve(strict=False)
    while current != current.parent:
        if (current / ".forge").is_dir():
            return current
        if (current / ".git").exists():
            return None
        current = current.parent
    return None


def _registry_roots() -> list[str] | None:
    path = _forge_home() / "projects.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        allowed_top = {"schema_version", "projects"}
        if set(data) - allowed_top:
            return None
        if data.get("schema_version") != PROJECT_REGISTRY_VERSION:
            return None
        projects = data.get("projects", [])
        if not isinstance(projects, list):
            return None
        roots: list[str] = []
        for index, item in enumerate(projects):
            if not isinstance(item, dict):
                return None
            allowed = {"canonical_path", "enrolled_at", "enrollment_source"}
            if set(item) - allowed:
                return None
            canonical_path = item.get("canonical_path")
            enrolled_at = item.get("enrolled_at")
            enrollment_source = item.get("enrollment_source")
            if not isinstance(canonical_path, str) or not canonical_path:
                return None
            if not isinstance(enrolled_at, str) or not enrolled_at:
                return None
            if enrollment_source not in {"manual", "enable", "worktree", "backfill"}:
                return None
            roots.append(_canonicalize(canonical_path))
        return roots
    except (OSError, json.JSONDecodeError):
        return None


def _is_enrolled(start: Path) -> bool:
    root = _find_forge_root(start)
    if root is None:
        return False
    roots = _registry_roots()
    if roots is None:
        return False
    return any(_paths_match(enrolled, root) for enrolled in roots)


def _should_dispatch() -> bool:
    if os.environ.get("FORGE_SESSION"):
        return True
    return _is_enrolled(Path.cwd())
"""

_RESOLVER_SOURCE = r"""
RUNTIME_METADATA_VERSION = 1


def _runtime_metadata_path() -> Path:
    return _forge_home() / "runtime.json"


def _read_runtime_metadata() -> dict[str, object]:
    path = _runtime_metadata_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get("schema_version") != RUNTIME_METADATA_VERSION:
        return {}
    return data


def _global_bin_dirs() -> list[Path]:
    home = os.environ.get("HOME") or str(Path.home())
    dirs = [Path(home) / ".local" / "bin"]
    for var in ("UV_TOOL_BIN_DIR", "XDG_BIN_HOME", "PIPX_BIN_DIR"):
        value = os.environ.get(var)
        if value:
            dirs.append(Path(value))
    seen: set[str] = set()
    unique: list[Path] = []
    for directory in dirs:
        key = str(directory.expanduser())
        if key not in seen:
            unique.append(directory.expanduser())
            seen.add(key)
    return unique


def _candidate_forge_paths() -> list[Path]:
    candidates: list[Path] = []
    metadata = _read_runtime_metadata()
    recorded = metadata.get("forge_binary_path")
    if isinstance(recorded, str) and recorded:
        candidates.append(Path(recorded).expanduser())
    for directory in _global_bin_dirs():
        candidates.append(directory / "forge")

    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def _is_executable(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def _resolve_forge() -> tuple[Path | None, list[Path]]:
    checked = _candidate_forge_paths()
    for candidate in checked:
        if _is_executable(candidate):
            return candidate, checked
    return None, checked
"""

_DISPATCHER_SOURCE = r"""
def main() -> int:
    try:
        should_dispatch = _should_dispatch()
    except Exception:
        return 0
    if not should_dispatch:
        return 0

    argv = sys.argv[1:]
    if not argv:
        sys.stderr.write("forge hook dispatcher: missing hook name\n")
        return 2

    forge_path, checked = _resolve_forge()
    if forge_path is None:
        checked_display = ", ".join(str(path) for path in checked) or "(no candidate paths)"
        sys.stderr.write(
            "forge hook dispatcher could not find the global 'forge' launcher. "
            f"Checked: {checked_display}. "
            "Run 'forge extension sync' after installing Forge as a global tool.\n"
        )
        return 127

    os.execv(str(forge_path), [str(forge_path), "hook", *argv])
    return 127
"""


def get_hook_dispatcher_path(forge_home: Path | None = None) -> Path:
    """Return the installed dispatcher executable path."""

    home = forge_home or get_forge_home()
    return home / DISPATCHER_BIN_DIR / DISPATCHER_FILENAME


def get_runtime_metadata_path(forge_home: Path | None = None) -> Path:
    """Return the dispatcher runtime metadata path."""

    home = forge_home or get_forge_home()
    return home / RUNTIME_METADATA_FILENAME


def dispatcher_source_block() -> str:
    """Return the embed-safe stdlib source rendered into the shim."""

    return "\n\n".join(
        (
            textwrap.dedent(_GATE_SOURCE).strip(),
            textwrap.dedent(_RESOLVER_SOURCE).strip(),
            textwrap.dedent(_DISPATCHER_SOURCE).strip(),
        )
    )


def dispatcher_source_sha256() -> str:
    """Return the stable hash for the shim source contract."""

    return hashlib.sha256(dispatcher_source_block().encode("utf-8")).hexdigest()


def render_dispatcher_script(*, version: str = __version__) -> str:
    """Render the executable stdlib dispatcher script."""

    source_hash = dispatcher_source_sha256()
    return (
        "#!/usr/bin/env python3\n"
        "# Generated by Forge. Re-render with 'forge extension sync'.\n"
        "from __future__ import annotations\n"
        "\n"
        f'FORGE_HOOK_DISPATCHER_VERSION = "{version}"\n'
        f'FORGE_HOOK_DISPATCHER_SOURCE_SHA256 = "{source_hash}"\n'
        "\n"
        f"{dispatcher_source_block()}\n\n"
        'if __name__ == "__main__":\n'
        "    raise SystemExit(main())\n"
    )


def render_dispatcher_command(handler: str, *, forge_home: Path | None = None) -> str:
    """Return the hook command byte form T5 will register."""

    path = get_hook_dispatcher_path(forge_home).expanduser()
    return f"{shlex.quote(str(path))} {shlex.quote(handler)}"


def normalize_dispatcher_command_home(command: str, *, home: Path | None = None) -> str:
    """Normalize the user's home path to ``$HOME`` for golden assertions."""

    home_path = str((home or Path.home()).expanduser())
    return command.replace(home_path, "$HOME")


def find_current_forge_binary(
    *,
    argv0: str | None = None,
    environ: dict[str, str] | None = None,
    which: Any = shutil.which,
) -> Path | None:
    """Resolve the current launcher path to record in runtime metadata."""

    def _absolute_without_resolving(path: Path) -> Path:
        expanded = path.expanduser()
        return expanded if expanded.is_absolute() else Path.cwd() / expanded

    env = dict(os.environ) if environ is None else environ
    found = which(EXECUTABLE, path=env.get("PATH"))
    if found:
        return _absolute_without_resolving(Path(found))

    a0 = sys.argv[0] if argv0 is None else argv0
    if a0 and os.sep in a0 and Path(a0).name == EXECUTABLE:
        return _absolute_without_resolving(Path(a0))
    return None


def _metadata_forge_path(path: Path | None) -> str | None:
    if path is None:
        return None
    expanded = path.expanduser()
    absolute = expanded if expanded.is_absolute() else Path.cwd() / expanded
    return str(absolute)


def _runtime_metadata_dict(forge_binary_path: Path | None, dispatcher_path: Path) -> dict[str, object]:
    return {
        "schema_version": RUNTIME_METADATA_VERSION,
        "forge_binary_path": _metadata_forge_path(forge_binary_path),
        "dispatcher_path": str(dispatcher_path),
        "dispatcher_version": __version__,
        "dispatcher_source_sha256": dispatcher_source_sha256(),
        "updated_at": now_iso(),
    }


def read_runtime_metadata(path: Path | None = None) -> dict[str, object] | None:
    """Read dispatcher runtime metadata leniently for resolver/doctor use."""

    metadata_path = path or get_runtime_metadata_path()
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema_version") != RUNTIME_METADATA_VERSION:
        return None
    return data


def write_runtime_metadata(
    *,
    forge_binary_path: Path | None,
    dispatcher_path: Path,
    path: Path | None = None,
) -> Path:
    """Write runtime metadata for the standalone dispatcher."""

    metadata_path = path or get_runtime_metadata_path()
    atomic_write_json(metadata_path, _runtime_metadata_dict(forge_binary_path, dispatcher_path))
    return metadata_path


def install_hook_dispatcher(
    *,
    forge_binary_path: Path | None = None,
    argv0: str | None = None,
    environ: dict[str, str] | None = None,
    which: Any = shutil.which,
) -> HookDispatcherInstallResult:
    """Render ``~/.forge/bin/forge-hook`` and write resolver metadata."""

    dispatcher_path = get_hook_dispatcher_path()
    resolved_forge = forge_binary_path or find_current_forge_binary(argv0=argv0, environ=environ, which=which)
    atomic_write_text(dispatcher_path, render_dispatcher_script(), mode=0o755)
    metadata_path = write_runtime_metadata(forge_binary_path=resolved_forge, dispatcher_path=dispatcher_path)
    return HookDispatcherInstallResult(
        dispatcher_path=str(dispatcher_path),
        metadata_path=str(metadata_path),
        forge_binary_path=_metadata_forge_path(resolved_forge),
    )


def parse_dispatcher_stamp(content: str) -> tuple[str | None, str | None]:
    """Extract the version/source stamp from a rendered dispatcher script."""

    installed_version: str | None = None
    installed_source_sha256: str | None = None
    for line in content.splitlines():
        if installed_version is None and (match := _STAMP_VERSION_RE.match(line)):
            installed_version = match.group(1)
        if installed_source_sha256 is None and (match := _STAMP_SOURCE_RE.match(line)):
            installed_source_sha256 = match.group(1)
        if installed_version is not None and installed_source_sha256 is not None:
            break
    return installed_version, installed_source_sha256


def diagnose_hook_dispatcher() -> HookDispatcherDiagnosis:
    """Return doctor-facing drift status for the dispatcher artifact."""

    dispatcher_path = get_hook_dispatcher_path()
    metadata_path = get_runtime_metadata_path()
    expected_version = __version__
    expected_source_sha256 = dispatcher_source_sha256()
    metadata = read_runtime_metadata(metadata_path)
    metadata_status = "current" if metadata is not None else ("missing" if not metadata_path.exists() else "invalid")
    forge_binary_path = None
    if metadata is not None:
        raw_path = metadata.get("forge_binary_path")
        if isinstance(raw_path, str) and raw_path:
            forge_binary_path = raw_path

    if not dispatcher_path.exists():
        return HookDispatcherDiagnosis(
            path=str(dispatcher_path),
            status="missing",
            installed_version=None,
            expected_version=expected_version,
            installed_source_sha256=None,
            expected_source_sha256=expected_source_sha256,
            metadata_path=str(metadata_path),
            metadata_status=metadata_status,
            forge_binary_path=forge_binary_path,
            advice="Run 'forge extension sync' to render the hook dispatcher.",
        )

    try:
        content = dispatcher_path.read_text(encoding="utf-8")
    except OSError as e:
        return HookDispatcherDiagnosis(
            path=str(dispatcher_path),
            status="unreadable",
            installed_version=None,
            expected_version=expected_version,
            installed_source_sha256=None,
            expected_source_sha256=expected_source_sha256,
            metadata_path=str(metadata_path),
            metadata_status=metadata_status,
            forge_binary_path=forge_binary_path,
            advice=f"Fix permissions for {dispatcher_path}: {e}",
        )

    installed_version, installed_source_sha256 = parse_dispatcher_stamp(content)
    is_current = installed_version == expected_version and installed_source_sha256 == expected_source_sha256
    status = "current" if is_current else "stale"
    advice = None if is_current else "Run 'forge extension sync' to re-render the hook dispatcher."
    return HookDispatcherDiagnosis(
        path=str(dispatcher_path),
        status=status,
        installed_version=installed_version,
        expected_version=expected_version,
        installed_source_sha256=installed_source_sha256,
        expected_source_sha256=expected_source_sha256,
        metadata_path=str(metadata_path),
        metadata_status=metadata_status,
        forge_binary_path=forge_binary_path,
        advice=advice,
    )


def known_forge_launcher_paths(environ: dict[str, str] | None = None) -> list[Path]:
    """Return resolver fallback launcher paths, shared with tests/docs."""

    env = dict(os.environ) if environ is None else environ
    return [directory / EXECUTABLE for directory in global_bin_dirs(env)]
