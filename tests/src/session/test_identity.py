"""Tests for forge.session.identity — project-scoped session key helpers."""

from __future__ import annotations

import pytest

from forge.session.exceptions import AmbiguousSessionError
from forge.session.identity import (
    make_scoped_key,
    resolve_key_best_effort,
    resolve_key_strict,
    session_name_from_key,
)


class TestSessionNameFromKey:
    def test_extracts_name_from_scoped_key(self) -> None:
        key = make_scoped_key("planner", "/project/a")
        assert session_name_from_key(key) == "planner"

    def test_handles_name_with_hyphens(self) -> None:
        key = make_scoped_key("my-long-session", "/project/b")
        assert session_name_from_key(key) == "my-long-session"


class TestMakeScopedKey:
    def test_deterministic(self) -> None:
        k1 = make_scoped_key("planner", "/project/a")
        k2 = make_scoped_key("planner", "/project/a")
        assert k1 == k2

    def test_different_forge_roots_produce_different_keys(self) -> None:
        k1 = make_scoped_key("planner", "/project/a")
        k2 = make_scoped_key("planner", "/project/b")
        assert k1 != k2

    def test_different_names_produce_different_keys(self) -> None:
        k1 = make_scoped_key("planner", "/project/a")
        k2 = make_scoped_key("executor", "/project/a")
        assert k1 != k2

    def test_key_contains_separator(self) -> None:
        key = make_scoped_key("planner", "/project/a")
        assert "|" in key

    def test_roundtrip_name(self) -> None:
        key = make_scoped_key("planner", "/project/a")
        assert session_name_from_key(key) == "planner"


class TestResolveKeyStrict:
    def _make_sessions(self) -> dict[str, object]:
        """Two sessions named 'planner' in different projects."""

        class Entry:
            def __init__(self, fr: str) -> None:
                self.forge_root = fr
                self.worktree_path = fr

        return {
            make_scoped_key("planner", "/project/a"): Entry("/project/a"),
            make_scoped_key("planner", "/project/b"): Entry("/project/b"),
            make_scoped_key("executor", "/project/a"): Entry("/project/a"),
        }

    def test_scoped_finds_correct_entry(self) -> None:
        sessions = self._make_sessions()
        key = resolve_key_strict(sessions, "planner", "/project/a")
        assert key is not None
        assert session_name_from_key(key) == "planner"
        assert getattr(sessions[key], "forge_root") == "/project/a"

    def test_scoped_returns_none_for_wrong_project(self) -> None:
        sessions = self._make_sessions()
        key = resolve_key_strict(sessions, "planner", "/project/c")
        assert key is None

    def test_unscoped_single_match_succeeds(self) -> None:
        sessions = self._make_sessions()
        key = resolve_key_strict(sessions, "executor", None)
        assert key is not None
        assert session_name_from_key(key) == "executor"

    def test_unscoped_duplicate_raises_ambiguous(self) -> None:
        sessions = self._make_sessions()
        with pytest.raises(AmbiguousSessionError) as exc_info:
            resolve_key_strict(sessions, "planner", None)
        assert "planner" in str(exc_info.value)
        assert "/project/a" in str(exc_info.value)
        assert "/project/b" in str(exc_info.value)

    def test_unscoped_no_match_returns_none(self) -> None:
        sessions = self._make_sessions()
        key = resolve_key_strict(sessions, "nonexistent", None)
        assert key is None


class TestResolveKeyBestEffort:
    def _make_sessions(self) -> dict[str, object]:
        class Entry:
            def __init__(self, fr: str) -> None:
                self.forge_root = fr
                self.worktree_path = fr

        return {
            make_scoped_key("planner", "/project/a"): Entry("/project/a"),
            make_scoped_key("planner", "/project/b"): Entry("/project/b"),
        }

    def test_scoped_finds_correct(self) -> None:
        sessions = self._make_sessions()
        key = resolve_key_best_effort(sessions, "planner", "/project/b")
        assert key is not None
        assert getattr(sessions[key], "forge_root") == "/project/b"

    def test_unscoped_returns_first_match_no_raise(self) -> None:
        sessions = self._make_sessions()
        key = resolve_key_best_effort(sessions, "planner", None)
        assert key is not None
        assert session_name_from_key(key) == "planner"

    def test_unscoped_no_match_returns_none(self) -> None:
        sessions = self._make_sessions()
        key = resolve_key_best_effort(sessions, "nonexistent", None)
        assert key is None
