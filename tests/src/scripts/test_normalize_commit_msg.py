"""Characterization tests for the repository-owned commit-message normalizer."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCRIPT = SCRIPTS_DIR / "normalize-commit-msg.py"
MAPPING = REPO_ROOT / "config" / "normalize-text-mapping.json"
sys.path.insert(0, str(SCRIPTS_DIR))

# ruff: noqa: E402
mod = importlib.import_module("normalize-commit-msg")


def test_shipped_mapping_is_complete_and_loaded_from_the_repository() -> None:
    configured = json.loads(MAPPING.read_text())
    emoji_map, phrase_map = mod.load_maps(keep_labels=True)

    assert mod.CONFIG_FILE == MAPPING
    assert len(configured["emoji"]) == 156
    assert len(configured["phrases"]) == 16
    assert emoji_map == configured["emoji"]
    assert phrase_map == configured["phrases"]


def test_default_map_strips_every_bracketed_label_without_changing_other_entries() -> None:
    configured = json.loads(MAPPING.read_text())["emoji"]
    emoji_map, _ = mod.load_maps()
    expected = {
        source: "" if replacement.startswith("[") and replacement.endswith("]") else replacement
        for source, replacement in configured.items()
    }

    assert emoji_map == expected


def test_normalize_replaces_symbols_and_removes_label_emoji_without_double_spaces() -> None:
    emoji_map, _ = mod.load_maps()

    assert mod.normalize("\u2705 ship \U0001f525 now", emoji_map, {}) == "\u2713 ship now"


def test_normalize_deletes_an_exact_phrase_line_and_preserves_blank_lines() -> None:
    _, phrase_map = mod.load_maps()
    message = "feat: own hooks\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n"

    assert mod.normalize(message, {}, phrase_map) == "feat: own hooks\n\n"


def test_normalize_applies_phrase_replacement_inline() -> None:
    phrase = "Generated with [Claude Code](https://claude.ai/code)"

    assert mod.normalize(f"before {phrase} after", {}, {phrase: ""}) == "before  after"


def test_normalize_preserves_indentation_for_a_replaced_whole_line() -> None:
    assert mod.normalize("  replace me", {}, {"replace me": "replacement"}) == "  replacement"


def test_filter_mode_keeps_a_label_when_the_message_would_become_empty() -> None:
    result = subprocess.run(
        [str(SCRIPT), "--filter"],
        input="\U0001f525\n",
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == "[fire]\n"
    assert result.stderr == ""


def test_message_file_is_normalized_before_the_command_returns(tmp_path: Path) -> None:
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("\U0001f525 fix: own hook\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n")

    result = subprocess.run([str(SCRIPT), str(message)], capture_output=True, text=True, check=False)

    assert result.returncode == 0
    assert result.stdout == "normalize-commit-msg: normalized commit message\n"
    assert result.stderr == ""
    assert message.read_text() == "fix: own hook\n\n"


def test_missing_config_preserves_the_existing_fail_open_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(mod, "CONFIG_FILE", missing)

    assert mod.load_maps() == ({}, {})
    assert capsys.readouterr().err == f"normalize-commit-msg: warning: config not found: {missing}\n"


def test_pre_commit_config_installs_and_scopes_the_commit_message_hook() -> None:
    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text())
    local_repository = next(repository for repository in config["repos"] if repository["repo"] == "local")
    hook = next(hook for hook in local_repository["hooks"] if hook["id"] == "normalize-commit-msg")

    assert config["default_stages"] == ["pre-commit"]
    assert config["default_install_hook_types"] == ["pre-commit", "commit-msg"]
    assert hook == {
        "id": "normalize-commit-msg",
        "name": "normalize commit message",
        "language": "system",
        "entry": "./scripts/normalize-commit-msg.py",
        "stages": ["commit-msg"],
    }


def test_pre_commit_install_creates_a_real_normalizing_commit_message_hook(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".pre-commit-config.yaml").write_text("""\
default_install_hook_types: [pre-commit, commit-msg]
default_stages: [pre-commit]
repos:
  - repo: local
    hooks:
      - id: normalize-commit-msg
        name: normalize commit message
        language: system
        entry: ./scripts/normalize-commit-msg.py
        stages: [commit-msg]
""")
    (repository / "config").mkdir()
    shutil.copy2(MAPPING, repository / "config" / MAPPING.name)
    (repository / "scripts").mkdir()
    shutil.copy2(SCRIPT, repository / "scripts" / SCRIPT.name)
    environment = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "PRE_COMMIT_HOME": str(tmp_path / "pre-commit-cache"),
    }

    subprocess.run(["git", "init", "--quiet"], cwd=repository, env=environment, check=True)
    subprocess.run(
        ["git", "add", ".pre-commit-config.yaml", "config", "scripts"],
        cwd=repository,
        env=environment,
        check=True,
    )
    installed = subprocess.run(
        [sys.executable, "-m", "pre_commit", "install"],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert installed.returncode == 0, installed.stderr
    pre_commit_hook = repository / ".git" / "hooks" / "pre-commit"
    commit_message_hook = repository / ".git" / "hooks" / "commit-msg"
    assert pre_commit_hook.is_file()
    assert commit_message_hook.is_file()

    message = repository / ".git" / "COMMIT_EDITMSG"
    message.write_text("\U0001f525 fix: installed hook\n")
    invoked = subprocess.run(
        [str(commit_message_hook), str(message)],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert invoked.returncode == 0, invoked.stderr
    assert message.read_text() == "fix: installed hook\n"
