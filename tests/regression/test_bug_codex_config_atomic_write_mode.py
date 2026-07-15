"""Regression for Codex config atomic-write mode preservation.

Bug ID: codex-config-atomic-write-mode
Root cause: the shared atomic writer replaced an existing user-owned config with
the ``0600`` mode of its temporary file when callers supplied no explicit mode.
Affected files: ``src/forge/core/state/io.py`` and
``src/forge/install/codex_hooks.py``.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from forge.install.codex_hooks import (
    apply_codex_merge,
    get_builtin_codex_entries,
    remove_codex_block,
)

pytestmark = pytest.mark.regression

_USER_CONFIG = 'model = "gpt-5.5-codex"\n'


def test_codex_merge_preserves_existing_user_config_mode(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(_USER_CONFIG, encoding="utf-8")
    config.chmod(0o644)

    apply_codex_merge(config, get_builtin_codex_entries())

    assert stat.S_IMODE(config.stat().st_mode) == 0o644


def test_codex_remove_preserves_existing_user_config_mode(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(_USER_CONFIG, encoding="utf-8")
    apply_codex_merge(config, get_builtin_codex_entries())
    config.chmod(0o644)

    result = remove_codex_block(config, get_builtin_codex_entries())

    assert result.removed and not result.deleted_file
    assert config.read_text(encoding="utf-8") == _USER_CONFIG
    assert stat.S_IMODE(config.stat().st_mode) == 0o644


def test_fresh_codex_config_keeps_secure_atomic_default(tmp_path: Path) -> None:
    config = tmp_path / "codex" / "config.toml"

    apply_codex_merge(config, get_builtin_codex_entries())

    assert stat.S_IMODE(config.stat().st_mode) == 0o600
