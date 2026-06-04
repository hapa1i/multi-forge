"""File-backed throttle + cache_hit segment tests.

The throttle persists the computed cache-hit-rate so a busy session recomputes
at most once per TTL window (each render is a fresh process). All failures
fail-open. Proxy mode reads the live metric and writes no file.
"""

from __future__ import annotations

import contextlib
import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from forge.cli import status_line as sl
from forge.cli.status_line import (
    _ANSI_RE,
    ProxyRuntimeTruth,
    TranscriptStats,
    status_line,
)
from forge.cli.statusline.throttle import _cache_path, read_or_compute
from forge.core.paths import get_forge_home
from forge.runtime_config import RuntimeConfig, StatusLineConfig


def _transcript(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(
        json.dumps({"requestId": "r1", "message": {"usage": {"input_tokens": 100, "cache_read_input_tokens": 50}}})
    )
    return str(p)


class TestThrottle:
    def test_computes_and_writes_cache_file(self, tmp_path):
        path = _transcript(tmp_path)
        calls = []

        def compute(p):
            calls.append(p)
            return 50.0

        rate = read_or_compute(path, "sess-1", ttl=12, compute_fn=compute, now=1000.0)
        assert rate == 50.0
        assert len(calls) == 1
        assert _cache_path("sess-1", path).is_file()

    def test_within_ttl_reuses_without_recompute(self, tmp_path):
        path = _transcript(tmp_path)
        spy = MagicMock(return_value=50.0)
        read_or_compute(path, "sess-1", ttl=12, compute_fn=spy, now=1000.0)
        # Re-render 5s later, transcript changed -> still within TTL -> reuse.
        (tmp_path / "t.jsonl").write_text(
            json.dumps({"requestId": "r2", "message": {"usage": {"input_tokens": 10, "cache_read_input_tokens": 9}}})
        )
        rate = read_or_compute(path, "sess-1", ttl=12, compute_fn=spy, now=1005.0)
        assert rate == 50.0  # stale-but-throttled value
        assert spy.call_count == 1  # not recomputed

    def test_unchanged_transcript_reuses_past_ttl(self, tmp_path):
        path = _transcript(tmp_path)
        spy = MagicMock(return_value=50.0)
        read_or_compute(path, "s", ttl=12, compute_fn=spy, now=1000.0)
        # 100s later (past TTL) but transcript identical -> reuse, no recompute.
        rate = read_or_compute(path, "s", ttl=12, compute_fn=spy, now=1100.0)
        assert rate == 50.0
        assert spy.call_count == 1

    def test_changed_and_past_ttl_recomputes(self, tmp_path):
        path = _transcript(tmp_path)
        spy = MagicMock(side_effect=[50.0, 90.0])
        read_or_compute(path, "s", ttl=12, compute_fn=spy, now=1000.0)
        (tmp_path / "t.jsonl").write_text(
            json.dumps({"requestId": "r9", "message": {"usage": {"input_tokens": 10, "cache_read_input_tokens": 9}}})
        )
        rate = read_or_compute(path, "s", ttl=12, compute_fn=spy, now=1100.0)
        assert rate == 90.0
        assert spy.call_count == 2

    def test_corrupt_cache_file_recomputes(self, tmp_path):
        path = _transcript(tmp_path)
        cache_file = _cache_path("s", path)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("{not json")
        spy = MagicMock(return_value=50.0)
        rate = read_or_compute(path, "s", ttl=12, compute_fn=spy, now=1000.0)
        assert rate == 50.0
        assert spy.call_count == 1

    def test_version_mismatch_recomputes(self, tmp_path):
        path = _transcript(tmp_path)
        cache_file = _cache_path("s", path)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"version": 999, "computed_at": 1000.0, "cache_hit_rate": 12.0}))
        spy = MagicMock(return_value=50.0)
        rate = read_or_compute(path, "s", ttl=12, compute_fn=spy, now=1000.0)
        assert rate == 50.0  # ignored stale-version entry
        assert spy.call_count == 1

    def test_none_result_not_cached(self, tmp_path):
        path = _transcript(tmp_path)
        rate = read_or_compute(path, "s", ttl=12, compute_fn=lambda p: None, now=1000.0)
        assert rate is None
        assert not _cache_path("s", path).is_file()

    def test_cache_key_is_hashed_not_raw_session_id(self, tmp_path):
        path = _transcript(tmp_path)
        weird = "../../etc/passwd\nnasty"
        cp = _cache_path(weird, path)
        assert weird not in str(cp)
        assert cp.suffix == ".json"
        assert cp.parent == get_forge_home() / "cache" / "statusline"


def _render_cache_hit(fixture, *, proxy=None, cache_hit="auto"):
    cfg = RuntimeConfig(statusline=StatusLineConfig(segments=["model", "cache_hit"], cache_hit=cache_hit))
    runner = CliRunner()
    with contextlib.ExitStack() as es:
        es.enter_context(patch.object(sl, "_get_terminal_width", return_value=200))
        es.enter_context(patch.object(sl, "detect_proxy", return_value=(proxy or (False, None, False))))
        es.enter_context(patch.object(sl, "discover_session", return_value=(None, False)))
        es.enter_context(patch.object(sl, "get_git_branch", return_value=None))
        es.enter_context(patch.object(sl, "_cached_scan_transcript", return_value=TranscriptStats()))
        es.enter_context(patch("forge.runtime_config.get_runtime_config", return_value=cfg))
        res = runner.invoke(status_line, input=json.dumps(fixture), env={"FORGE_STATUS_TRUNCATE": "0"})
    assert res.exit_code == 0, res.output
    return _ANSI_RE.sub("", res.output)


_PROXY_WITH_CACHE = (
    True,
    ProxyRuntimeTruth(
        {
            "is_proxy": True,
            "proxy": {"proxy_id": "p", "template": "litellm-openai", "port": 8085, "base_url": "http://localhost:8085"},
            "runtime": {
                "active_tier": "sonnet",
                "active_context_window": 128000,
                "tier_mappings": {"sonnet": "gpt-4o"},
            },
            "metrics": {"cache_hit_rate": 64.0},
        }
    ),
    True,
)


class TestCacheHitSegmentE2E:
    def _fixture(self, tmp_path):
        p = tmp_path / "t.jsonl"
        p.write_text(
            json.dumps({"requestId": "r1", "message": {"usage": {"input_tokens": 100, "cache_read_input_tokens": 30}}})
        )
        return {
            "session_id": "sess-e2e",
            "transcript_path": str(p),
            "workspace": {"current_dir": "/tmp/demo"},
            "model": {"display_name": "Opus 4.6"},
            "context_window": {
                "context_window_size": 200000,
                "used_percentage": 12,
                "current_usage": {"input_tokens": 1},
            },
        }

    def test_proxy_reads_metric_no_file_written(self, tmp_path):
        before = (
            set((get_forge_home() / "cache" / "statusline").glob("*.json"))
            if (get_forge_home() / "cache" / "statusline").is_dir()
            else set()
        )
        visible = _render_cache_hit(self._fixture(tmp_path), proxy=_PROXY_WITH_CACHE)
        assert "cache:64%" in visible
        after = (
            set((get_forge_home() / "cache" / "statusline").glob("*.json"))
            if (get_forge_home() / "cache" / "statusline").is_dir()
            else set()
        )
        assert before == after  # proxy path writes no throttle file

    def test_direct_computes_and_writes_throttle_file(self, tmp_path):
        visible = _render_cache_hit(self._fixture(tmp_path))
        assert "cache:30%" in visible  # 30 / 100
        assert _cache_path("sess-e2e", str(tmp_path / "t.jsonl")).is_file()

    def test_cache_hit_off_hides_segment(self, tmp_path):
        visible = _render_cache_hit(self._fixture(tmp_path), cache_hit="off")
        assert "cache:" not in visible
