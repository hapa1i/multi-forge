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
FORGE_DEV_VAR = "FORGE_DEV"
_USER_HOOK_ENABLE_COMMAND = (
    "forge extension enable --scope user --profile minimal --with hooks,codex-hooks --without commands"
)
_USER_HOOK_SYNC_COMMAND = "forge extension sync --scope user"

_STAMP_VERSION_RE = re.compile(r'^FORGE_HOOK_DISPATCHER_VERSION = "([^"]*)"$')
_STAMP_SOURCE_RE = re.compile(r'^FORGE_HOOK_DISPATCHER_SOURCE_SHA256 = "([0-9a-f]*)"$')


@dataclass(frozen=True)
class HookDispatcherInstallResult:
    """Paths written when rendering the dispatcher artifact."""

    dispatcher_path: str
    metadata_path: str
    forge_binary_path: str | None


@dataclass(frozen=True)
class DevOverrideDiagnosis:
    """Doctor-facing state for the checkout-local dispatcher override."""

    present: bool
    value: str | None
    target: str | None
    valid: bool
    effective: bool
    advice: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "present": self.present,
            "value": self.value,
            "target": self.target,
            "valid": self.valid,
            "effective": self.effective,
            "advice": self.advice,
        }


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
    dev_override: DevOverrideDiagnosis
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
            "dev_override": self.dev_override.to_dict(),
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
FORGE_DEV_VAR = "FORGE_DEV"


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


def _dev_override_target() -> tuple[Path | None, str | None]:
    value = os.environ.get(FORGE_DEV_VAR, "")
    if not value:
        return None, f"{FORGE_DEV_VAR} is set but empty; expected an absolute Forge checkout root"
    try:
        root = Path(value).expanduser()
    except (OSError, RuntimeError) as exc:
        return None, f"{FORGE_DEV_VAR} value {value!r} could not be expanded: {exc}"
    if not root.is_absolute():
        return None, f"{FORGE_DEV_VAR} must name an absolute Forge checkout root; got {value!r}"
    target = root / ".venv" / "bin" / "forge"
    if not _is_executable(target):
        return target, f"{FORGE_DEV_VAR} target is missing or not executable: {target}"
    return target, None


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

    if FORGE_DEV_VAR in os.environ:
        forge_path, error = _dev_override_target()
        if error is not None or forge_path is None:
            sys.stderr.write(f"forge hook dispatcher: {error or f'{FORGE_DEV_VAR} target is invalid'}\n")
            return 127
        try:
            os.execv(str(forge_path), [str(forge_path), "hook", *argv])
        except OSError as exc:
            sys.stderr.write(
                f"forge hook dispatcher: {FORGE_DEV_VAR} target could not be executed: {forge_path}: {exc}\n"
            )
            return 127
        return 127

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
    """Return the literal absolute host hook command byte form."""

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

    env = dict(os.environ) if environ is None else environ
    found = which(EXECUTABLE, path=env.get("PATH"))
    if found:
        try:
            return _absolute_without_resolving(Path(found))
        except (OSError, RuntimeError):
            pass

    a0 = sys.argv[0] if argv0 is None else argv0
    if a0 and os.sep in a0 and Path(a0).name == EXECUTABLE:
        try:
            return _absolute_without_resolving(Path(a0))
        except (OSError, RuntimeError):
            pass
    return None


def _absolute_without_resolving(path: Path) -> Path:
    expanded = path.expanduser()
    return expanded if expanded.is_absolute() else Path.cwd() / expanded


def _is_executable_file(path: Path) -> bool:
    try:
        return path.is_absolute() and path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def _is_venv_launcher(path: Path) -> bool:
    """Classify the launcher lexically so global-tool symlinks stay global."""

    if path.parent.name not in ("bin", "Scripts"):
        return False
    try:
        return (path.parent.parent / "pyvenv.cfg").is_file()
    except OSError:
        return False


def _recorded_forge_binary(metadata: dict[str, object] | None) -> Path | None:
    if metadata is None:
        return None
    raw = metadata.get("forge_binary_path")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return Path(raw).expanduser()
    except (OSError, RuntimeError):
        return None


def select_forge_binary_for_recording(
    *,
    discovered: Path | None,
    recorded: Path | None,
    environ: dict[str, str] | None = None,
) -> Path | None:
    """Select durable launcher metadata without sticky-recording a project venv."""

    env = dict(os.environ) if environ is None else environ
    if discovered is not None and _is_executable_file(discovered) and not _is_venv_launcher(discovered):
        return discovered
    if recorded is not None and _is_executable_file(recorded) and not _is_venv_launcher(recorded):
        return recorded
    for candidate in known_forge_launcher_paths(env):
        if _is_executable_file(candidate) and not _is_venv_launcher(candidate):
            return candidate
    return None


def _resolve_current_dispatch_target(recorded: Path | None, environ: dict[str, str]) -> Path | None:
    candidates = ([recorded] if recorded is not None else []) + known_forge_launcher_paths(environ)
    for candidate in candidates:
        if _is_executable_file(candidate):
            return candidate
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
    env = dict(os.environ) if environ is None else environ
    resolved_forge: Path | None
    if forge_binary_path is not None:
        resolved_forge = _absolute_without_resolving(forge_binary_path)
    else:
        discovered = find_current_forge_binary(argv0=argv0, environ=env, which=which)
        recorded = _recorded_forge_binary(read_runtime_metadata())
        resolved_forge = select_forge_binary_for_recording(discovered=discovered, recorded=recorded, environ=env)
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


def _validate_dev_override(
    environ: dict[str, str],
) -> tuple[bool, str | None, Path | None, str | None]:
    if FORGE_DEV_VAR not in environ:
        return False, None, None, None
    value = environ.get(FORGE_DEV_VAR, "")
    if not value:
        return (
            True,
            value,
            None,
            f"{FORGE_DEV_VAR} is empty; set it to an absolute Forge checkout root.",
        )
    try:
        root = Path(value).expanduser()
    except (OSError, RuntimeError) as exc:
        return True, value, None, f"{FORGE_DEV_VAR} could not be expanded: {exc}"
    if not root.is_absolute():
        return (
            True,
            value,
            None,
            f"{FORGE_DEV_VAR} must name an absolute Forge checkout root.",
        )
    target = root / ".venv" / "bin" / EXECUTABLE
    if not _is_executable_file(target):
        return (
            True,
            value,
            target,
            f"{FORGE_DEV_VAR} target is missing or not executable: {target}",
        )
    return True, value, target, None


def _diagnose_dev_override(
    *,
    environ: dict[str, str],
    dispatcher_path: Path,
    dispatcher_status: str,
    recovery_command: str,
) -> DevOverrideDiagnosis:
    present, value, target, validation_error = _validate_dev_override(environ)
    if not present:
        return DevOverrideDiagnosis(False, None, None, False, False, None)
    target_str = str(target) if target is not None else None
    if validation_error is not None:
        return DevOverrideDiagnosis(True, value, target_str, False, False, validation_error)
    dispatcher_executable = _is_executable_file(dispatcher_path)
    if dispatcher_status == "non_executable" or (dispatcher_status == "current" and not dispatcher_executable):
        advice = f"Restore execute permission for {dispatcher_path} (or run '{recovery_command}')."
        return DevOverrideDiagnosis(True, value, target_str, True, False, advice)
    if dispatcher_status != "current":
        advice = f"Run '{recovery_command}' so the installed hook dispatcher can honor FORGE_DEV."
        return DevOverrideDiagnosis(True, value, target_str, True, False, advice)
    return DevOverrideDiagnosis(True, value, target_str, True, True, None)


def _has_user_installation() -> bool:
    """Best-effort: does the tracked user install require the dispatcher?

    The dispatcher is user-scoped, so an unrelated project installation must
    not select ``sync``: bare sync cannot discover that installation from an
    arbitrary working directory. A skills-only user install deliberately does
    not render the dispatcher, so its recovery must name an enable command that
    adds runtime hooks instead of an ineffective skills-only sync. Corrupt or
    unreadable tracking keeps the user-sync advice so the command surfaces the
    existing reset path.
    """
    try:
        from .tracking import TrackingStore

        installation = TrackingStore().get_installation("user")
        return installation is not None and any(module != "skills" for module in installation.modules_enabled)
    except Exception:  # Diagnosis must never raise; degrade to the sync advice.
        return True


def diagnose_hook_dispatcher(
    *,
    environ: dict[str, str] | None = None,
    argv0: str | None = None,
    which: Any = shutil.which,
    has_user_installation: bool | None = None,
) -> HookDispatcherDiagnosis:
    """Return doctor-facing drift status for the dispatcher artifact."""

    env = dict(os.environ) if environ is None else environ
    has_user = _has_user_installation() if has_user_installation is None else has_user_installation
    recovery_cmd = _USER_HOOK_SYNC_COMMAND if has_user else _USER_HOOK_ENABLE_COMMAND
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
    recorded = _recorded_forge_binary(metadata)
    current_dispatch_target = _resolve_current_dispatch_target(recorded, env)
    discovered = find_current_forge_binary(argv0=argv0, environ=env, which=which)
    next_recorded_target = select_forge_binary_for_recording(discovered=discovered, recorded=recorded, environ=env)

    if not dispatcher_path.exists():
        status = "missing"
        return HookDispatcherDiagnosis(
            path=str(dispatcher_path),
            status=status,
            installed_version=None,
            expected_version=expected_version,
            installed_source_sha256=None,
            expected_source_sha256=expected_source_sha256,
            metadata_path=str(metadata_path),
            metadata_status=metadata_status,
            forge_binary_path=forge_binary_path,
            dev_override=_diagnose_dev_override(
                environ=env,
                dispatcher_path=dispatcher_path,
                dispatcher_status=status,
                recovery_command=recovery_cmd,
            ),
            advice=(
                f"Run '{recovery_cmd}' to render the hook dispatcher."
                if has_user
                else f"Run '{recovery_cmd}' to install runtime hooks and render the hook dispatcher."
            ),
        )

    try:
        content = dispatcher_path.read_text(encoding="utf-8")
    except OSError as e:
        status = "unreadable"
        return HookDispatcherDiagnosis(
            path=str(dispatcher_path),
            status=status,
            installed_version=None,
            expected_version=expected_version,
            installed_source_sha256=None,
            expected_source_sha256=expected_source_sha256,
            metadata_path=str(metadata_path),
            metadata_status=metadata_status,
            forge_binary_path=forge_binary_path,
            dev_override=_diagnose_dev_override(
                environ=env,
                dispatcher_path=dispatcher_path,
                dispatcher_status=status,
                recovery_command=recovery_cmd,
            ),
            advice=f"Fix permissions for {dispatcher_path}: {e}",
        )

    installed_version, installed_source_sha256 = parse_dispatcher_stamp(content)
    is_current = installed_version == expected_version and installed_source_sha256 == expected_source_sha256
    dispatcher_executable = _is_executable_file(dispatcher_path)
    if not dispatcher_executable:
        status = "non_executable"
        advice = f"Run '{recovery_cmd}' to restore the hook dispatcher's executable mode."
    elif not is_current:
        status = "stale"
        advice = f"Run '{recovery_cmd}' to re-render the hook dispatcher."
    elif recorded is not None and _is_executable_file(recorded) and _is_venv_launcher(recorded):
        status = "current"
        advice = f"Run '{recovery_cmd}' to replace the recorded virtualenv launcher used by hook dispatch."
    elif current_dispatch_target is None:
        status = "current"
        if next_recorded_target is not None:
            advice = f"Run '{recovery_cmd}' to record {next_recorded_target} for hook dispatch."
        else:
            advice = (
                "No recorded or known global Forge launcher is executable; " f"install one and run '{recovery_cmd}'."
            )
    else:
        status = "current"
        advice = None
    dev_override = _diagnose_dev_override(
        environ=env,
        dispatcher_path=dispatcher_path,
        dispatcher_status=status,
        recovery_command=recovery_cmd,
    )
    if dev_override.effective and current_dispatch_target is None and advice is not None:
        advice = f"FORGE_DEV is effective for this process; without it, normal resolution reports: {advice}"
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
        dev_override=dev_override,
        advice=advice,
    )


def known_forge_launcher_paths(environ: dict[str, str] | None = None) -> list[Path]:
    """Return resolver fallback launcher paths, shared with tests/docs."""

    env = dict(os.environ) if environ is None else environ
    return [directory / EXECUTABLE for directory in global_bin_dirs(env)]
