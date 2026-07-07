"""Install diagnosis for ``forge extension doctor`` (epic_global_forge_runtime T1).

Reports how Forge was installed (global tool vs editable/venv) and whether the
``forge`` launcher is reachable on PATH -- including a GUI/launchd-style minimal
PATH.

The minimal-PATH probe is the mechanical signal behind the exit-127 hook
incident: GUI-launched apps (Dock/IDE) inherit launchd's PATH, which excludes
``~/.local/bin`` (where ``uv tool`` / ``pipx`` place the launcher), so a bare
``forge hook ...`` command can be unreachable even when Forge is installed. It is
deliberately reported as a fact, not an error: a correct global install still
reads ``on_path_minimal=false``. See the epic's D2 decision.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from shutil import which as _shutil_which

DIST_NAME = "multi-forge"
EXECUTABLE = "forge"

# launchd's default PATH for GUI-launched processes -- notably excludes
# ``~/.local/bin``. Probing against it answers "would a GUI-launched hook
# subprocess find bare ``forge``?" (epic D2 / the exit-127 incident).
MINIMAL_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

# The two recommended global-tool installs (surfaced in advice + Day-1 docs).
GLOBAL_INSTALL_COMMANDS = ("uv tool install multi-forge", "pipx install multi-forge")

# Fixes for a global install whose bin dir is off PATH -- installed, just not wired
# into the shell (the common "just ran uv tool install / pipx install" state).
PATH_SETUP_COMMANDS = ("uv tool update-shell", "pipx ensurepath")

# shutil.which-compatible callable; injected in tests.
WhichFn = Callable[..., "str | None"]


@dataclass(frozen=True)
class InstallDiagnosis:
    """How Forge is installed and whether it is reachable.

    ``install_kind`` is one of ``global`` | ``editable`` | ``venv`` | ``unknown``.
    ``advice`` is populated only when there is a user-actionable fix (it is not
    driven by ``on_path_minimal``, which is a T2-owned diagnostic signal).
    """

    install_kind: str
    forge_path: str | None
    on_path: bool
    on_path_minimal: bool
    advice: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "install_kind": self.install_kind,
            "forge_path": self.forge_path,
            "on_path": self.on_path,
            "on_path_minimal": self.on_path_minimal,
            "advice": self.advice,
        }

    @property
    def advice_commands(self) -> tuple[str, ...]:
        """Copy-paste commands that resolve the advised state (empty when no advice).

        A global install that is merely off PATH needs shell wiring, not a reinstall.
        """
        if self.advice is None:
            return ()
        if self.install_kind == "global" and not self.on_path:
            return PATH_SETUP_COMMANDS
        return GLOBAL_INSTALL_COMMANDS


def is_editable_install(dist_name: str = DIST_NAME) -> bool:
    """Return True if ``dist_name`` is an editable/development install.

    Reads PEP 610 ``direct_url.json`` (``dir_info.editable``), written by
    ``pip install -e`` / ``uv sync``. Missing or unreadable metadata means "not
    editable" (a PyPI/index install records no editable marker).
    """
    try:
        dist = distribution(dist_name)
    except PackageNotFoundError:
        return False
    try:
        raw = dist.read_text("direct_url.json")
    except (OSError, ValueError):
        return False
    if not raw:
        return False
    try:
        parsed = json.loads(raw)
    except ValueError:
        return False
    dir_info = parsed.get("dir_info") if isinstance(parsed, dict) else None
    return bool(isinstance(dir_info, dict) and dir_info.get("editable"))


def _global_bin_dirs(environ: dict[str, str]) -> set[Path]:
    """Directories where global-tool installers (uv tool, pipx) place launchers."""
    home = environ.get("HOME") or str(Path.home())
    dirs = {Path(home) / ".local" / "bin"}
    # uv honors UV_TOOL_BIN_DIR then XDG_BIN_HOME; pipx honors PIPX_BIN_DIR.
    for var in ("UV_TOOL_BIN_DIR", "XDG_BIN_HOME", "PIPX_BIN_DIR"):
        val = environ.get(var)
        if val:
            dirs.add(Path(val))
    return dirs


def _looks_like_venv_bin(bindir: Path) -> bool:
    """A virtualenv bin dir (``bin``/``Scripts``) has a sibling ``pyvenv.cfg``."""
    if bindir.name not in ("bin", "Scripts"):
        return False
    try:
        return (bindir.parent / "pyvenv.cfg").exists()
    except OSError:
        return False


def _classify(forge_path: str | None, is_editable: bool, environ: dict[str, str]) -> str:
    # Editable wins first: a dev checkout's launcher lives in a venv bin, but
    # "editable" is the more actionable label for a contributor than "venv".
    if is_editable:
        return "editable"
    if forge_path is not None:
        parent = Path(forge_path).parent
        if parent in _global_bin_dirs(environ):
            return "global"
        if _looks_like_venv_bin(parent):
            return "venv"
    return "unknown"


def _advice(install_kind: str, on_path: bool, forge_path: str | None) -> str | None:
    # A global install that resolves on PATH is the recommended end state.
    if install_kind == "global" and on_path:
        return None
    if install_kind == "global":
        # Installed globally but its bin dir is off PATH -- the fix is PATH setup,
        # not a reinstall (the common "just ran uv tool install" state).
        location = forge_path or "its install directory"
        return (
            f"Forge is installed at {location}, but that directory is not on your PATH. Add it so "
            "`forge` resolves in every shell and from hooks."
        )
    if install_kind == "editable":
        return (
            "Editable/development install (contributor setup). End users should install Forge as a "
            "global tool so hooks and other shells resolve it reliably."
        )
    return (
        "Forge is not installed as a globally reachable tool. Install it as a global tool so hooks "
        "and other shells resolve it reliably."
    )


def diagnose_install(
    *,
    argv0: str | None = None,
    which: WhichFn = _shutil_which,
    environ: dict[str, str] | None = None,
    editable: bool | None = None,
) -> InstallDiagnosis:
    """Diagnose the Forge install: kind, launcher path, and PATH reachability.

    Seams are injectable for testing (``argv0``, ``which``, ``environ``,
    ``editable``). ``on_path`` uses the caller's PATH (what a shell or hook
    inherits); ``on_path_minimal`` uses the launchd minimal PATH -- the
    GUI-launch reachability signal (epic D2). The launcher path is reported as
    resolved on PATH (the symlink a user sees, not its target), so a ``uv tool``
    launcher in ``~/.local/bin`` classifies as global rather than by its
    tool-venv target.

    Note the subjects differ: ``install_kind`` reflects the *running* interpreter's
    packaging metadata (``importlib.metadata``), while ``forge_path``/``on_path``
    reflect PATH resolution. In a mixed setup they can describe different installs --
    e.g. invoking a dev checkout's ``.venv/bin/forge`` directly (venv not on PATH)
    while a global install is earlier on PATH yields ``kind=editable`` with a global
    ``forge_path``. Editable-wins precedence is right for the common cases; the
    checkout-local dev override is T8's space (``forge_dev_runtime_override``).
    """
    env = dict(os.environ) if environ is None else environ
    a0 = sys.argv[0] if argv0 is None else argv0
    editable_resolved = is_editable_install() if editable is None else editable

    found = which(EXECUTABLE, path=env.get("PATH"))
    on_path = found is not None
    on_path_minimal = which(EXECUTABLE, path=MINIMAL_PATH) is not None

    # Fall back to argv0 (the running launcher) only when it is an explicit path,
    # so we still report where the running forge lives when PATH would miss it.
    forge_path = found if found else (a0 if a0 and os.sep in a0 else None)
    install_kind = _classify(forge_path, editable_resolved, env)
    return InstallDiagnosis(
        install_kind=install_kind,
        forge_path=forge_path,
        on_path=on_path,
        on_path_minimal=on_path_minimal,
        advice=_advice(install_kind, on_path, forge_path),
    )
