"""Carry inherited authentication through an otherwise isolated Claude reviewer."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryFile
from typing import Iterator


def inherited_auth_settings(
    env: dict[str, str], *, cwd: str | None, direct: bool, excluded_env: tuple[str, ...] = ()
) -> dict[str, object]:
    """Copy only auth settings; never carry hooks, tools, plugins, or permissions.

    User settings are trusted auth configuration. Project/local auth environment
    is admitted only when Claude's user-owned trust record approves the checkout. Explicit
    child routing and hydrated environment credentials retain precedence.
    """
    home = Path(env.get("HOME") or str(Path.home()))
    config = Path(env.get("CLAUDE_CONFIG_DIR") or str(home / ".claude"))
    paths = [config / "settings.json"]
    project = Path(cwd or Path.cwd()).resolve()
    for parent in (project, *project.parents):
        if (parent / ".git").exists():
            project = parent
            break
    metadata_path = config / ".claude.json" if env.get("CLAUDE_CONFIG_DIR") else home / ".claude.json"
    try:
        trusted = (
            json.loads(metadata_path.read_text())
            .get("projects", {})
            .get(str(project), {})
            .get("hasTrustDialogAccepted")
        )
    except (OSError, ValueError, AttributeError):
        trusted = False
    if trusted is True:
        paths.extend([project / ".claude/settings.json", project / ".claude/settings.local.json"])

    selected: dict[str, object] = {}
    auth_env: dict[str, str] = {}
    for path in paths:
        if not path.exists():
            continue
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError(f"Claude auth settings must be a regular file smaller than 2 MiB: {path}")
        settings = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            raise ValueError(f"Claude auth settings must be a JSON object: {path}")
        if "apiKeyHelper" in settings:
            helper = settings["apiKeyHelper"]
            if not isinstance(helper, str):
                raise ValueError(f"Claude apiKeyHelper must be a command string: {path}")
            if path != paths[0] and helper != selected.get("apiKeyHelper"):
                raise ValueError(
                    "Reviewer apiKeyHelper must come from user settings, outside the supervised checkout. "
                    "Move the trusted helper to user settings or export its credential before launching Forge."
                )
            selected["apiKeyHelper"] = helper
        values = settings.get("env", {})
        if not isinstance(values, dict):
            raise ValueError(f"Claude auth environment must be an object: {path}")
        for key, value in values.items():
            if key.startswith(("ANTHROPIC_", "AWS_", "GOOGLE_", "AZURE_", "CLAUDE_CODE_USE_")) or key in {
                "CLAUDE_CODE_OAUTH_TOKEN",
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "NO_PROXY",
            }:
                if not isinstance(value, str):
                    raise ValueError(f"Claude auth environment values must be strings: {path}")
                auth_env[key] = value
    for key, value in auth_env.items():
        if key not in excluded_env and not (direct and key == "ANTHROPIC_BASE_URL"):
            env.setdefault(key, value)
    return selected


@contextmanager
def auth_settings_descriptor(settings: dict[str, object]) -> Iterator[tuple[list[str], tuple[int, ...]]]:
    """Keep settings off argv and disk paths, including if the hook is SIGKILLed."""
    if not settings:
        yield [], ()
        return
    with TemporaryFile(mode="w+") as handle:
        json.dump(settings, handle)
        handle.flush()
        handle.seek(0)
        descriptor = handle.fileno()
        yield ["--settings", f"/dev/fd/{descriptor}"], (descriptor,)
