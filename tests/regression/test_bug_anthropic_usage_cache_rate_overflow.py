"""Regression: Anthropic-native cache accounting reported cache rates far above 100%.

Anthropic's ``input_tokens`` excludes cache reads and writes. The passthrough proxy, headless
Claude results and the statusline treated it as the total prompt, so cache reads divided by it
produced 42,508% in telemetry and 14,546,605% for one direct session's statusline, and cache
writes disappeared from token counts. Forge now records the total prompt with reads and writes
as subsets, matching the translated path and Codex.
"""

import json
from pathlib import Path

import pytest

from forge.cli.statusline.sources import compute_cache_hit_rate
from forge.core.reactive.structured_output import parse_headless_envelope
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


def test_statusline_cache_rate_within_100(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(json.dumps({"requestId": "r1", "message": {"usage": ANTHROPIC_USAGE}}))

    assert compute_cache_hit_rate(str(transcript)) == 84.0
