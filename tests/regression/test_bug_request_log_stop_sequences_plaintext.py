"""Regression (proxy_log_hygiene review): ``stop_sequences`` plaintext leak in redacted bodies.

Root cause: ``_redact_body_for_log`` listed ``stop_sequences`` in ``_SAFE_KEYS`` and copied it
verbatim. ``stop_sequences`` is caller-supplied text (arbitrary delimiter strings that can embed
proprietary content), so the "redacted = sanitized structure, never plaintext" contract was broken
on BOTH planes that share the redactor: the audit plane and the new request-diagnostics plane
(``logging.requests`` with ``body_capture=redacted``).

Affected file: ``src/forge/proxy/utils.py`` (``_redact_body_for_log`` / ``_SAFE_KEYS``).
Fix: drop ``stop_sequences`` from the verbatim-copy set; emit ``{"redacted": True, "count": N}``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.config.schema import RequestLogConfig
from forge.proxy.utils import _redact_body_for_log, log_request_response

pytestmark = pytest.mark.regression

_CANARY = "SECRET_CANARY_STOP_SEQUENCE"


def test_redactor_replaces_stop_sequences_with_count() -> None:
    """The shared redactor (audit + request planes) must never copy stop_sequences verbatim."""
    out = _redact_body_for_log({"model": "claude-x", "stop_sequences": [_CANARY, "</proprietary>"]})
    assert out is not None
    assert _CANARY not in json.dumps(out)  # no plaintext leak
    assert out["stop_sequences"] == {"redacted": True, "count": 2}  # structure/cardinality kept
    assert out["model"] == "claude-x"  # structural metadata still passes through


def test_redactor_ignores_non_list_stop_sequences() -> None:
    """A malformed (non-list) stop_sequences is dropped, not copied verbatim."""
    out = _redact_body_for_log({"model": "m", "stop_sequences": _CANARY})
    assert out is not None
    assert _CANARY not in json.dumps(out)
    assert "stop_sequences" not in out  # not a list -> omitted entirely


@pytest.mark.asyncio
async def test_request_log_redacted_mode_omits_stop_sequences_plaintext(tmp_path, monkeypatch) -> None:
    """End-to-end: the request-diagnostics shard never persists stop_sequences plaintext."""
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge_home"))
    await log_request_response(
        request_id="req_canary",
        original_model="claude-opus",
        mapped_model="gpt-5.5",
        request_body={"model": "x", "stop_sequences": [_CANARY], "messages": []},
        response_body=None,
        status_code=200,
        duration_ms=1.0,
        request_log=RequestLogConfig(enabled="on", body_capture="redacted"),
    )
    shards = list((tmp_path / "forge_home" / "logs" / "requests").glob("*_requests.*.jsonl"))
    assert len(shards) == 1
    written = Path(shards[0]).read_text(encoding="utf-8")
    assert _CANARY not in written  # canary never reaches disk
    event = json.loads(written.strip())
    assert event["request_body"]["stop_sequences"] == {"redacted": True, "count": 1}
