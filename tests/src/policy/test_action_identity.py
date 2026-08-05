"""Tests for canonical policy action identity."""

from __future__ import annotations

from forge.policy.action_identity import action_fingerprint, compute_action_fingerprint
from forge.policy.types import ActionContext


def _fingerprint(**overrides: object) -> str:
    values: dict[str, object] = {
        "tool_name": "Edit",
        "target_path": "src/app.py",
        "tool_args": {"old_string": "old", "new_string": "new"},
        "new_content": "new",
    }
    values.update(overrides)
    return compute_action_fingerprint(**values)  # type: ignore[arg-type]


def _context(*, fingerprint: str | None = None) -> ActionContext:
    return ActionContext(
        origin="claude_code",
        event="PreToolUse.Edit",
        tool_name="Edit",
        tool_args={"old_string": "old", "new_string": "new"},
        repo_root="/repo",
        session_name="worker",
        target_path="src/app.py",
        new_content="new",
        action_fingerprint=fingerprint,
    )


def test_identical_actions_have_stable_opaque_sha256_identity() -> None:
    first = _fingerprint()
    second = _fingerprint()

    assert first == second
    assert len(first) == 64
    assert set(first) <= set("0123456789abcdef")
    assert "old" not in first and "new" not in first


def test_edit_identity_includes_old_new_and_replace_all() -> None:
    base = _fingerprint()

    assert _fingerprint(tool_args={"old_string": "other", "new_string": "new"}) != base
    assert _fingerprint(tool_args={"old_string": "old", "new_string": "other"}, new_content="other") != base
    assert _fingerprint(tool_args={"old_string": "old", "new_string": "new", "replace_all": True}) != base


def test_canonical_fields_have_unambiguous_boundaries() -> None:
    first = _fingerprint(tool_args={"old_string": "ab", "new_string": "c"}, new_content="c")
    second = _fingerprint(tool_args={"old_string": "a", "new_string": "bc"}, new_content="bc")

    assert first != second


def test_raw_diff_is_authoritative_for_diff_actions() -> None:
    first = _fingerprint(raw_diff="@@\n-removed-one")
    second = _fingerprint(raw_diff="@@\n-removed-two")

    assert first != second


def test_explicit_full_content_beats_bounded_tool_args_excerpt() -> None:
    common_args = {"content": "same display excerpt"}
    first = _fingerprint(tool_name="Write", tool_args=common_args, new_content="same display excerpt\nfirst tail")
    second = _fingerprint(tool_name="Write", tool_args=common_args, new_content="same display excerpt\nsecond tail")

    assert first != second


def test_context_uses_only_valid_precomputed_digest() -> None:
    precomputed = "a" * 64
    assert action_fingerprint(_context(fingerprint=precomputed)) == precomputed

    fallback = action_fingerprint(_context(fingerprint="not-a-digest"))
    assert fallback == _fingerprint()
