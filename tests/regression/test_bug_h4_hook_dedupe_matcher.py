"""Regression test for H4: hook dedupe dropped intended matchers.

Bug: merge_hooks() deduplicated by command path only. If two hooks shared the
same command (e.g., "forge hook policy-check") but had different matchers
("Write" vs "Edit"), the second entry was dropped as a duplicate.

Impact: Only one PreToolUse matcher got installed. Policy enforcement silently
failed for the dropped matcher (e.g., Edit operations bypassed policy checks).

Fix: Changed dedupe identity to full JSON entry equality via _canonical_json().
Two entries are duplicates only if structurally identical (all fields match).

Fixed in: src/forge/install/settings_merge.py (action plan Step 1, H4)
"""

import pytest

pytestmark = pytest.mark.regression


def test_same_command_different_matchers_both_preserved() -> None:
    """Two hooks with same command but different matchers must both survive merge."""
    from forge.install.settings_merge import merge_hooks

    settings: dict = {}
    hook_write = {"matcher": "Write", "hooks": [{"command": "forge hook policy-check"}]}
    hook_edit = {"matcher": "Edit", "hooks": [{"command": "forge hook policy-check"}]}

    merge_hooks(settings, "PreToolUse", [hook_write, hook_edit])

    entries = settings["hooks"]["PreToolUse"]
    assert len(entries) == 2
    matchers = {e["matcher"] for e in entries}
    assert matchers == {"Write", "Edit"}


def test_identical_entries_still_deduped() -> None:
    """Merging the exact same entry twice must produce only one copy."""
    from forge.install.settings_merge import merge_hooks

    settings: dict = {}
    entry = {"matcher": "Write", "hooks": [{"command": "forge hook policy-check"}]}

    merge_hooks(settings, "PreToolUse", [entry, entry])

    assert len(settings["hooks"]["PreToolUse"]) == 1


def test_canonical_json_deterministic() -> None:
    """_canonical_json() must produce identical output regardless of key order."""
    from forge.install.settings_merge import _canonical_json

    entry_a = {"matcher": "Write", "command": "forge hook x", "timeout": 10}
    entry_b = {"timeout": 10, "command": "forge hook x", "matcher": "Write"}

    assert _canonical_json(entry_a) == _canonical_json(entry_b)


def test_merge_into_existing_dedupes_against_prior() -> None:
    """New entries that match existing entries in settings are not re-added."""
    from forge.install.settings_merge import merge_hooks

    existing_entry = {
        "matcher": "Write",
        "hooks": [{"command": "forge hook policy-check"}],
    }
    settings: dict = {"hooks": {"PreToolUse": [existing_entry]}}

    added = merge_hooks(settings, "PreToolUse", [existing_entry])

    assert len(settings["hooks"]["PreToolUse"]) == 1
    assert len(added) == 0  # Nothing new added
