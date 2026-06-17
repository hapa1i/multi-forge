"""Slice 4 (proxy_log_hygiene): config-driven request JSONL writer.

The per-proxy RequestLogConfig gates whether request diagnostics are written (enabled:
auto/off/on) and whether bodies are captured (metadata vs redacted). There is no plaintext
mode; redacted bodies reuse the audit redaction builders.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.config.schema import RequestLogConfig
from forge.proxy import utils
from forge.proxy.utils import log_request_response, request_logging_enabled


@pytest.fixture(autouse=True)
def _reset_rc():
    from forge.runtime_config import reset_runtime_config

    reset_runtime_config()
    yield
    reset_runtime_config()


# --- request_logging_enabled matrix -----------------------------------------------------


def test_enabled_off_never_writes(monkeypatch) -> None:
    monkeypatch.setattr(utils, "_should_write_structured_logs", lambda: True)  # debug on
    assert request_logging_enabled(RequestLogConfig(enabled="off")) is False


def test_enabled_on_always_writes(monkeypatch) -> None:
    monkeypatch.setattr(utils, "_should_write_structured_logs", lambda: False)  # debug off
    assert request_logging_enabled(RequestLogConfig(enabled="on")) is True


def test_enabled_auto_follows_debug(monkeypatch) -> None:
    monkeypatch.setattr(utils, "_should_write_structured_logs", lambda: True)
    assert request_logging_enabled(RequestLogConfig(enabled="auto")) is True
    monkeypatch.setattr(utils, "_should_write_structured_logs", lambda: False)
    assert request_logging_enabled(RequestLogConfig(enabled="auto")) is False


def test_none_config_behaves_as_auto(monkeypatch) -> None:
    monkeypatch.setattr(utils, "_should_write_structured_logs", lambda: False)
    assert request_logging_enabled(None) is False
    monkeypatch.setattr(utils, "_should_write_structured_logs", lambda: True)
    assert request_logging_enabled(None) is True


# --- body capture write behavior --------------------------------------------------------


def _written_shard(tmp_path: Path) -> Path:
    files = list((tmp_path / "forge_home" / "logs" / "requests").glob("*_requests.*.jsonl"))
    assert len(files) == 1
    return files[0]


def _written_event(tmp_path: Path) -> dict:
    return json.loads(_written_shard(tmp_path).read_text(encoding="utf-8").strip())


async def _write(tmp_path, monkeypatch, cfg: RequestLogConfig) -> None:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge_home"))
    await log_request_response(
        request_id="req_1",
        original_model="claude-opus",
        mapped_model="gpt-5.5",
        request_body={"model": "x", "messages": [{"role": "user", "content": "secret text"}]},
        response_body={"id": "resp_1", "content": [{"type": "text", "text": "private reply"}]},
        status_code=200,
        duration_ms=12.3,
        request_log=cfg,
    )


@pytest.mark.asyncio
async def test_metadata_mode_omits_bodies(tmp_path, monkeypatch) -> None:
    """Default metadata mode: no request_body/response_body keys -- counts/timing only."""
    await _write(tmp_path, monkeypatch, RequestLogConfig(enabled="on"))  # defaults: metadata
    event = _written_event(tmp_path)
    assert "request_body" not in event and "response_body" not in event
    assert event["request_id"] == "req_1" and event["status_code"] == 200
    # Sanity: no plaintext leaked into the metadata record.
    assert "secret text" not in json.dumps(event) and "private reply" not in json.dumps(event)


@pytest.mark.asyncio
async def test_redacted_mode_includes_redacted_structure(tmp_path, monkeypatch) -> None:
    await _write(
        tmp_path, monkeypatch, RequestLogConfig(enabled="on", body_capture="redacted", response_capture="redacted")
    )
    event = _written_event(tmp_path)
    assert "request_body" in event and "response_body" in event
    # Structure preserved, content redacted -- never plaintext.
    assert "secret text" not in json.dumps(event)
    assert "private reply" not in json.dumps(event)
    assert event["request_body"]["messages"][0]["role"] == "user"
    assert event["request_body"]["messages"][0]["content"]["redacted"] is True


@pytest.mark.asyncio
async def test_written_shard_is_owner_only_0600(tmp_path, monkeypatch) -> None:
    """Shards can hold redacted-but-sensitive bodies, so they must be owner-only (open_secure_append).

    Locks the 0600 property at the request-log boundary directly rather than relying on the
    writer's choice of helper (card acceptance: "preserve owner-only permissions").
    """
    await _write(
        tmp_path, monkeypatch, RequestLogConfig(enabled="on", body_capture="redacted", response_capture="redacted")
    )
    shard = _written_shard(tmp_path)
    assert oct(shard.stat().st_mode & 0o777) == "0o600"


@pytest.mark.asyncio
async def test_off_writes_nothing(tmp_path, monkeypatch) -> None:
    await _write(tmp_path, monkeypatch, RequestLogConfig(enabled="off"))
    assert not (tmp_path / "forge_home" / "logs" / "requests").exists()
