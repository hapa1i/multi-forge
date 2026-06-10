"""Unit tests for Codex rollout discovery (codex_frontend Phase 2)."""

from __future__ import annotations

import os
from pathlib import Path

from forge.core.runtime.codex_rollouts import codex_home, find_rollout_path

_TID = "019eaa51-6920-7c41-ae34-d4f7f368d55a"


def _make_rollout(home: Path, date: str, ts: str, thread_id: str) -> Path:
    day_dir = home / "sessions" / date
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"rollout-{ts}-{thread_id}.jsonl"
    path.write_text('{"type":"session_meta"}\n')
    return path


class TestCodexHome:
    def test_env_override_wins(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "custom"))
        assert codex_home() == tmp_path / "custom"

    def test_defaults_to_dot_codex(self, monkeypatch) -> None:
        monkeypatch.delenv("CODEX_HOME", raising=False)
        assert codex_home() == Path.home() / ".codex"


class TestFindRolloutPath:
    def test_finds_matching_rollout(self, tmp_path: Path) -> None:
        expected = _make_rollout(tmp_path, "2026/06/10", "2026-06-10T12-00-00", _TID)
        _make_rollout(tmp_path, "2026/06/10", "2026-06-10T11-00-00", "other-thread-id")
        assert find_rollout_path(_TID, home=tmp_path) == expected

    def test_none_when_no_match(self, tmp_path: Path) -> None:
        _make_rollout(tmp_path, "2026/06/10", "2026-06-10T12-00-00", "other-thread-id")
        assert find_rollout_path(_TID, home=tmp_path) is None

    def test_none_when_sessions_dir_missing(self, tmp_path: Path) -> None:
        assert find_rollout_path(_TID, home=tmp_path) is None

    def test_none_for_empty_thread_id(self, tmp_path: Path) -> None:
        assert find_rollout_path("", home=tmp_path) is None

    def test_searches_across_dates(self, tmp_path: Path) -> None:
        expected = _make_rollout(tmp_path, "2026/05/31", "2026-05-31T09-00-00", _TID)
        assert find_rollout_path(_TID, home=tmp_path) == expected

    def test_multi_match_newest_mtime_wins(self, tmp_path: Path) -> None:
        older = _make_rollout(tmp_path, "2026/06/09", "2026-06-09T12-00-00", _TID)
        newer = _make_rollout(tmp_path, "2026/06/10", "2026-06-10T12-00-00", _TID)
        os.utime(older, (1000, 1000))
        os.utime(newer, (2000, 2000))
        assert find_rollout_path(_TID, home=tmp_path) == newer

    def test_env_home_used_when_not_passed(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        expected = _make_rollout(tmp_path, "2026/06/10", "2026-06-10T12-00-00", _TID)
        assert find_rollout_path(_TID) == expected
