"""Regression: Anthropic-native cache accounting reported cache rates far above 100%.

Anthropic's ``input_tokens`` excludes cache reads and writes. The passthrough proxy, headless
Claude results and the statusline treated it as the total prompt, so cache reads divided by it
produced 42,508% in telemetry and 14,546,605% for one direct session's statusline, and cache
writes disappeared from token counts. Forge now records the total prompt with reads and writes
as subsets, matching the translated path and Codex. Direct ``claude -p`` verbs and workers also
carry the write count through to their downstream records.
"""

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from forge.cli.statusline.sources import compute_cache_hit_rate
from forge.core.invoker import Attribution, ClaudeHeadlessInvoker, HeadlessRequest
from forge.core.reactive.session_runner import run_claude_session
from forge.core.reactive.structured_output import parse_headless_envelope
from forge.core.telemetry.downstream import DownstreamRecord, read_downstream_records
from forge.core.usage.emit import emit_usage_for_session_result
from forge.proxy import passthrough
from forge.proxy.metrics import ProxyMetrics

pytestmark = pytest.mark.regression

ANTHROPIC_USAGE = {
    "input_tokens": 4,
    "cache_read_input_tokens": 2519,
    "cache_creation_input_tokens": 477,
    "output_tokens": 9,
}


def test_passthrough_usage_counts_total_input_and_writes() -> None:
    usage = passthrough.extract_usage_from_message({"usage": ANTHROPIC_USAGE})

    assert usage == {"input_tokens": 3000, "output_tokens": 9, "cached_tokens": 2519, "cache_write_tokens": 477}


def test_proxy_metrics_cache_rate_within_100() -> None:
    usage = passthrough.extract_usage_from_message({"usage": ANTHROPIC_USAGE})
    metrics = ProxyMetrics()
    metrics.record_request(
        tier="opus",
        model="claude-opus-5-5",
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        cached_tokens=usage["cached_tokens"],
        latency_ms=1.0,
        streaming=False,
        failed=False,
        error_type=None,
        cost_micros=None,
    )

    assert metrics.snapshot()["cache_hit_rate"] == 84.0  # 2519 / 3000


def test_headless_envelope_counts_total_input() -> None:
    envelope = parse_headless_envelope(json.dumps({"type": "result", "result": "ok", "usage": ANTHROPIC_USAGE}))

    assert envelope.input_tokens == 3000
    assert envelope.cached_tokens == 2519
    assert envelope.cache_write_tokens == 477


def _direct_envelope() -> str:
    return json.dumps({"type": "result", "result": "ok", "total_cost_usd": 0.01, "usage": ANTHROPIC_USAGE})


def _only_downstream_attempt() -> DownstreamRecord:
    records = read_downstream_records(kind="attempt")
    assert len(records) == 1
    return records[0]


@patch("forge.core.reactive.session_runner.subprocess.run")
def test_direct_claude_verb_downstream_keeps_cache_writes(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(stdout=_direct_envelope(), stderr="", returncode=0)
    result = run_claude_session("prompt")

    emit_usage_for_session_result(replace(result, run_id="run-verb"), command="memory-writer", direct=True)

    record = _only_downstream_attempt()
    assert (record.input_tokens, record.cached_tokens, record.cache_write_tokens) == (3000, 2519, 477)


@patch("forge.core.invoker._lifecycle.subprocess.Popen")
def test_direct_claude_worker_downstream_keeps_cache_writes(mock_popen: MagicMock) -> None:
    proc = MagicMock(returncode=0, pid=12345)
    proc.communicate.return_value = (_direct_envelope(), "")
    proc.poll.return_value = 0
    proc.wait.return_value = 0
    mock_popen.return_value = proc
    request = HeadlessRequest(
        argv=["claude", "-p"],
        prompt="prompt",
        env={"FORGE_RUN_ID": "run-worker", "FORGE_ROOT_RUN_ID": "run-worker"},
        cwd=None,
        timeout_seconds=60,
        label="w0",
        attribution=Attribution(command="panel"),
    )

    ClaudeHeadlessInvoker().run_parallel([request])

    record = _only_downstream_attempt()
    assert (record.input_tokens, record.cached_tokens, record.cache_write_tokens) == (3000, 2519, 477)


def test_statusline_cache_rate_within_100(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(json.dumps({"requestId": "r1", "message": {"usage": ANTHROPIC_USAGE}}))

    assert compute_cache_hit_rate(str(transcript)) == 84.0
