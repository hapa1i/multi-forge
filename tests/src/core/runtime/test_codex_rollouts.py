"""Unit tests for Codex rollout discovery (codex_frontend Phases 2 + 5)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from forge.core.runtime.codex_rollouts import (
    DiscoveredRollout,
    codex_home,
    find_rollout_path,
    find_rollouts_since,
    parse_rollout_filename,
)

_TID = "019eaa51-6920-7c41-ae34-d4f7f368d55a"
_TID_B = "11111111-2222-3333-4444-555555555555"


def _make_rollout(home: Path, date: str, ts: str, thread_id: str, *, head: str | None = None) -> Path:
    day_dir = home / "sessions" / date
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"rollout-{ts}-{thread_id}.jsonl"
    path.write_text((head if head is not None else '{"type":"session_meta"}') + "\n")
    return path


def _since(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


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


class TestParseRolloutFilename:
    def test_parses_thread_id_from_filename(self, tmp_path: Path) -> None:
        path = tmp_path / f"rollout-2026-06-10T03-36-19-{_TID}.jsonl"
        parsed = parse_rollout_filename(path)
        assert parsed == DiscoveredRollout(thread_id=_TID, path=path)

    def test_opaque_non_uuid_id_still_parses(self, tmp_path: Path) -> None:
        # Phase 2 treats the id opaquely; the parser keeps that stance (strict on
        # the timestamp prefix, loose on the id).
        path = tmp_path / "rollout-2026-06-10T03-36-19-other-thread-id.jsonl"
        parsed = parse_rollout_filename(path)
        assert parsed is not None
        assert parsed.thread_id == "other-thread-id"

    def test_rejects_names_without_timestamp_prefix(self, tmp_path: Path) -> None:
        assert parse_rollout_filename(tmp_path / f"rollout-{_TID}.jsonl") is None
        assert parse_rollout_filename(tmp_path / "rollout-garbage.jsonl") is None
        assert parse_rollout_filename(tmp_path / f"notes-2026-06-10T03-36-19-{_TID}.jsonl") is None


class TestFindRolloutsSince:
    def test_finds_post_launch_rollout_with_thread_id_from_filename(self, tmp_path: Path) -> None:
        path = _make_rollout(tmp_path, "2026/06/11", "2026-06-11T10-00-00", _TID)
        os.utime(path, (6000, 6000))
        results = find_rollouts_since(_since(5000), home=tmp_path)
        assert results == [DiscoveredRollout(thread_id=_TID, path=path)]

    def test_excludes_rollouts_older_than_since(self, tmp_path: Path) -> None:
        old = _make_rollout(tmp_path, "2026/06/10", "2026-06-10T10-00-00", _TID_B)
        new = _make_rollout(tmp_path, "2026/06/11", "2026-06-11T10-00-00", _TID)
        os.utime(old, (1000, 1000))
        os.utime(new, (6000, 6000))
        results = find_rollouts_since(_since(5000), home=tmp_path)
        assert [r.thread_id for r in results] == [_TID]

    def test_mtime_skew_allowance_includes_borderline_file(self, tmp_path: Path) -> None:
        path = _make_rollout(tmp_path, "2026/06/11", "2026-06-11T10-00-00", _TID)
        os.utime(path, (4999, 4999))  # 1s before since, within the 2s skew
        assert find_rollouts_since(_since(5000), home=tmp_path) != []
        os.utime(path, (4990, 4990))  # 10s before since, beyond the skew
        assert find_rollouts_since(_since(5000), home=tmp_path) == []

    def test_newest_mtime_first(self, tmp_path: Path) -> None:
        older = _make_rollout(tmp_path, "2026/06/11", "2026-06-11T10-00-00", _TID_B)
        newer = _make_rollout(tmp_path, "2026/06/11", "2026-06-11T11-00-00", _TID)
        os.utime(older, (6000, 6000))
        os.utime(newer, (7000, 7000))
        results = find_rollouts_since(_since(5000), home=tmp_path)
        assert [r.thread_id for r in results] == [_TID, _TID_B]

    def test_unparseable_filenames_skipped(self, tmp_path: Path) -> None:
        day_dir = tmp_path / "sessions" / "2026/06/11"
        day_dir.mkdir(parents=True)
        bogus = day_dir / "rollout-garbage.jsonl"
        bogus.write_text("{}\n")
        os.utime(bogus, (6000, 6000))
        assert find_rollouts_since(_since(5000), home=tmp_path) == []

    def test_missing_home_returns_empty(self, tmp_path: Path) -> None:
        assert find_rollouts_since(_since(5000), home=tmp_path / "absent") == []

    def test_cwd_narrows_concurrent_siblings(self, tmp_path: Path) -> None:
        mine = _make_rollout(
            tmp_path, "2026/06/11", "2026-06-11T10-00-00", _TID, head=json.dumps({"cwd": str(tmp_path / "work")})
        )
        other = _make_rollout(
            tmp_path, "2026/06/11", "2026-06-11T10-00-01", _TID_B, head=json.dumps({"cwd": str(tmp_path / "elsewhere")})
        )
        os.utime(mine, (6000, 6000))
        os.utime(other, (6001, 6001))
        results = find_rollouts_since(_since(5000), cwd=str(tmp_path / "work"), home=tmp_path)
        assert [r.thread_id for r in results] == [_TID]

    def test_cwd_found_when_nested_in_head(self, tmp_path: Path) -> None:
        mine = _make_rollout(
            tmp_path,
            "2026/06/11",
            "2026-06-11T10-00-00",
            _TID,
            head=json.dumps({"type": "session_meta", "payload": {"cwd": str(tmp_path / "work")}}),
        )
        other = _make_rollout(
            tmp_path, "2026/06/11", "2026-06-11T10-00-01", _TID_B, head=json.dumps({"payload": {"cwd": "/elsewhere"}})
        )
        os.utime(mine, (6000, 6000))
        os.utime(other, (6001, 6001))
        results = find_rollouts_since(_since(5000), cwd=str(tmp_path / "work"), home=tmp_path)
        assert [r.thread_id for r in results] == [_TID]

    def test_same_cwd_ambiguity_returns_both(self, tmp_path: Path) -> None:
        # The caller refuses to guess between two rollouts claiming the same cwd.
        head = json.dumps({"cwd": str(tmp_path / "work")})
        a = _make_rollout(tmp_path, "2026/06/11", "2026-06-11T10-00-00", _TID, head=head)
        b = _make_rollout(tmp_path, "2026/06/11", "2026-06-11T10-00-01", _TID_B, head=head)
        os.utime(a, (6000, 6000))
        os.utime(b, (6001, 6001))
        results = find_rollouts_since(_since(5000), cwd=str(tmp_path / "work"), home=tmp_path)
        assert {r.thread_id for r in results} == {_TID, _TID_B}

    def test_unknown_head_shape_does_not_narrow(self, tmp_path: Path) -> None:
        # Heads without a recognizable cwd must not eliminate the true rollout.
        a = _make_rollout(tmp_path, "2026/06/11", "2026-06-11T10-00-00", _TID)
        b = _make_rollout(tmp_path, "2026/06/11", "2026-06-11T10-00-01", _TID_B, head="not json")
        os.utime(a, (6000, 6000))
        os.utime(b, (6001, 6001))
        results = find_rollouts_since(_since(5000), cwd=str(tmp_path / "work"), home=tmp_path)
        assert {r.thread_id for r in results} == {_TID, _TID_B}

    def test_single_known_mismatching_cwd_is_rejected(self, tmp_path: Path) -> None:
        # A lone rollout with a different known cwd is a concurrent stranger, not ours.
        path = _make_rollout(
            tmp_path, "2026/06/11", "2026-06-11T10-00-00", _TID, head=json.dumps({"cwd": "/elsewhere"})
        )
        os.utime(path, (6000, 6000))
        results = find_rollouts_since(_since(5000), cwd=str(tmp_path / "work"), home=tmp_path)
        assert results == []

    def test_single_unknown_head_shape_is_kept(self, tmp_path: Path) -> None:
        # Unknown heads may still be true rollouts from a changed Codex schema.
        path = _make_rollout(tmp_path, "2026/06/11", "2026-06-11T10-00-00", _TID, head="not json")
        os.utime(path, (6000, 6000))
        results = find_rollouts_since(_since(5000), cwd=str(tmp_path / "work"), home=tmp_path)
        assert [r.thread_id for r in results] == [_TID]
