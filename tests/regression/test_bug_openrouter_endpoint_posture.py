"""A single proxy profile previously determined both clients' capability reports."""

from types import SimpleNamespace

import pytest

from forge.cli.statusline.registry import _produce_audit
from forge.config.loader import get_proxy_file_path
from forge.core.runtime.codex_preflight import resolve_responses_posture

pytestmark = pytest.mark.regression


def test_saved_translated_openrouter_accepts_codex_without_rewrite():
    path = get_proxy_file_path("cyan-coconut")
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = b"""proxy_format: 1
template: openrouter-gemini
provider: openrouter
backend: openrouter
wire_shape: openai_translated
proxy_endpoint: http://127.0.0.1:8085
port: 8085
upstream_base_url: https://openrouter.ai/api/v1
tiers:
  haiku: google/gemini-4-hydrogen
  sonnet: google/gemini-4-neon
  opus: google/gemini-4-neon
"""
    path.write_bytes(saved)
    posture = resolve_responses_posture("cyan-coconut")
    assert posture.posture == "proxy_supported", posture.blocking_reason
    assert path.read_bytes() == saved


def test_claude_audit_reads_messages_on_responses_profile():
    raw = {
        "wire_shape": "openai_responses_passthrough",
        "intercept_mode": "inspect",
        "intercept": {"thinking_blocks_preserved": True},
        "endpoints": {"messages": {"mode": "inspect", "thinking_blocks_preserved": False}},
    }
    ctx = SimpleNamespace(is_proxy=True, runtime=SimpleNamespace(raw=raw))
    assert "(lossy)" in _produce_audit(ctx)
