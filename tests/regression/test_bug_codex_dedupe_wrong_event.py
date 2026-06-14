"""Regression: Codex manual-registration dedupe accepted commands under the wrong event.

Bug (codex_frontend Phase 6 review, P1): ``plan_codex_merge`` deduplicated
against a flattened set of command strings (``_collect_commands``), ignoring
which event each command was registered under. ``forge hook codex-policy-check``
under SessionStart -- or both Forge commands under a typo'd event name, which
Codex loads silently -- read as "already registered", so the installer skipped
silently, left the install untracked, and enforcement never ran.

Root cause: src/forge/install/codex_hooks.py -- dedupe identity must match
Codex's own registration identity ((event, command) with type="command"),
not bare command strings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.install.codex_hooks import get_builtin_codex_entries, plan_codex_merge

pytestmark = pytest.mark.regression

ENTRIES = get_builtin_codex_entries()


def _entry(event: str, command: str, extra: str = "") -> str:
    return (
        f"[[hooks.{event}]]\n{extra}[[hooks.{event}.hooks]]\n"
        f'type = "command"\ncommand = "{command}"\ntimeout = 60\n'
    )


def test_commands_under_swapped_events_install_not_skip(tmp_path: Path) -> None:
    """The exact failure: both commands present, both under the wrong event."""
    config = tmp_path / "config.toml"
    config.write_text(
        _entry("SessionStart", "forge hook codex-policy-check")
        + _entry("Stop", "forge hook codex-session-start")
    )
    plan = plan_codex_merge(config, ENTRIES)
    assert plan.action == "install", (
        "wrong-event registrations were treated as 'already registered', "
        "silently leaving enforcement nonfunctional and untracked"
    )


def test_commands_under_bogus_event_install_not_skip(tmp_path: Path) -> None:
    """Codex loads bogus event names silently; they must not satisfy dedupe."""
    config = tmp_path / "config.toml"
    config.write_text(
        _entry("SessionStarted", "forge hook codex-session-start")
        + _entry("SessionStarted", "forge hook codex-policy-check")
    )
    assert plan_codex_merge(config, ENTRIES).action == "install"


def test_one_correct_one_wrong_event_conflicts(tmp_path: Path) -> None:
    """A correct-event registration plus a wrong-event one is the partial case."""
    config = tmp_path / "config.toml"
    config.write_text(
        _entry("SessionStart", "forge hook codex-session-start")
        + _entry("Stop", "forge hook codex-policy-check")
    )
    plan = plan_codex_merge(config, ENTRIES)
    assert plan.action == "conflict"
    assert "codex-session-start" in (plan.reason or "")
    assert "codex-policy-check" in (plan.reason or "")


def test_correct_event_manual_registration_still_skips(tmp_path: Path) -> None:
    """Guard the intended behavior: correct (event, command) pairs dedupe."""
    config = tmp_path / "config.toml"
    config.write_text(
        _entry("SessionStart", "forge hook codex-session-start")
        + _entry("PreToolUse", "forge hook codex-policy-check")
    )
    plan = plan_codex_merge(config, ENTRIES)
    assert plan.action == "skip"
    assert "outside Forge markers" in (plan.reason or "")


def test_matcher_is_ignored_in_dedupe(tmp_path: Path) -> None:
    """A matcher'd correct-event registration still counts as registered.

    It fires on overlapping events, so installing ours alongside it would
    double-fire -- the precise thing dedupe exists to prevent.
    """
    config = tmp_path / "config.toml"
    config.write_text(
        _entry("SessionStart", "forge hook codex-session-start")
        + _entry("PreToolUse", "forge hook codex-policy-check", extra='matcher = "apply_patch"\n')
    )
    assert plan_codex_merge(config, ENTRIES).action == "skip"


def test_non_command_type_does_not_count(tmp_path: Path) -> None:
    """An entry with a different type is not a working registration."""
    config = tmp_path / "config.toml"
    config.write_text(
        "[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\n"
        'type = "script"\ncommand = "forge hook codex-session-start"\ntimeout = 60\n'
        + _entry("PreToolUse", "forge hook codex-policy-check")
    )
    plan = plan_codex_merge(config, ENTRIES)
    assert plan.action == "conflict"  # only policy-check counts as registered
