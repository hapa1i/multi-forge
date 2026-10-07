"""Recreate existing Codex hook trust in Docker without copying native credentials."""

from __future__ import annotations

import json
import os
import shlex
import tomllib
from pathlib import Path

import pytest

from tests.fixtures.docker import DockerContainer

# Capture the operator identity before the autouse test fixtures replace HOME,
# CODEX_HOME, and FORGE_HOME with isolated directories.
_REAL_HOME = Path.home()
_REAL_CODEX_HOME = Path(os.environ.get("CODEX_HOME") or _REAL_HOME / ".codex")
_REAL_FORGE_HOME = Path(os.environ.get("FORGE_HOME") or _REAL_HOME / ".forge")


def codex_identity_config() -> str:
    """Render the non-secret enrolled hook state at its original absolute path."""
    config_path = _REAL_CODEX_HOME / "config.toml"
    if not config_path.is_file():
        pytest.fail(
            f"real Codex authority E2E needs enrolled hook state at {config_path}. "
            "Enable user Codex hooks and complete the interactive trust ceremony."
        )
    try:
        parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        pytest.fail(f"cannot read real Codex hook enrollment state at {config_path}: {exc}")

    hooks = parsed.get("hooks")
    state = hooks.get("state") if isinstance(hooks, dict) else None
    if not isinstance(state, dict):
        pytest.fail(f"real Codex config at {config_path} has no [hooks.state] enrollment records")

    trusted: dict[str, str] = {}
    for event in ("session_start", "pre_tool_use"):
        key = f"{config_path}:{event}:0:0"
        entry = state.get(key)
        digest = entry.get("trusted_hash") if isinstance(entry, dict) else None
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            pytest.fail(
                f"real Codex config has no trusted {event} user-hook record for {config_path}. "
                "Run 'forge extension enable --scope user --runtime codex', open 'codex', "
                "and grant hook trust before re-running."
            )
        trusted[key] = digest

    lines = [
        "[features]",
        "hooks = true",
        "",
        f"[projects.{json.dumps('/workspace')}]",
        'trust_level = "trusted"',
    ]
    for key, digest in trusted.items():
        lines.extend(
            [
                "",
                f"[hooks.state.{json.dumps(key)}]",
                f"trusted_hash = {json.dumps(digest)}",
            ]
        )
    return "\n".join(lines) + "\n"


def codex_exports() -> str:
    return " && ".join(
        [
            f"export HOME={shlex.quote(str(_REAL_HOME))}",
            f"export CODEX_HOME={shlex.quote(str(_REAL_CODEX_HOME))}",
            f"export FORGE_HOME={shlex.quote(str(_REAL_FORGE_HOME))}",
            "export FORGE_DEV=/forge",
        ]
    )


def prepare_real_codex(workspace: DockerContainer) -> None:
    api_key = os.environ.get("CODEX_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        pytest.fail("real Codex authority E2E needs CODEX_API_KEY or OPENAI_API_KEY in the environment/.env")

    directories = workspace.exec(f"mkdir -p {shlex.quote(str(_REAL_CODEX_HOME))} {shlex.quote(str(_REAL_FORGE_HOME))}")
    assert directories.returncode == 0, directories.stderr
    config = workspace.write_file(str(_REAL_CODEX_HOME / "config.toml"), codex_identity_config())
    assert config.returncode == 0, config.stderr
    key = workspace.write_file("/tmp/.authority_codex_key", api_key, mode=0o600)
    assert key.returncode == 0, key.stderr
    protected = workspace.exec(
        f"chmod 700 {shlex.quote(str(_REAL_HOME))} {shlex.quote(str(_REAL_CODEX_HOME))} "
        f"{shlex.quote(str(_REAL_FORGE_HOME))}"
    )
    assert protected.returncode == 0, protected.stderr

    enabled = workspace.exec(
        f"{codex_exports()} && cd /workspace && "
        "forge extension enable --scope user --profile minimal --with hooks --without commands --runtime codex",
        timeout=60,
    )
    assert enabled.returncode == 0, enabled.stderr
