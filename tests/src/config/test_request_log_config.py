"""Slice 4 (proxy_log_hygiene): strict coercion for the per-proxy logging.requests block.

Mirrors the audit/provider_trace pattern: a security/diagnostics capture control must reject
unknown keys and bad values loudly (a silently-ignored typo would leave the control OFF). The
block is also wired through the loader at both hops (the provider_trace DOA trap).
"""

from __future__ import annotations

import pytest

from forge.config.schema import (
    LoggingConfig,
    RequestLogConfig,
    _coerce_logging_config,
    _coerce_request_log_config,
)


def test_defaults_are_quiet_and_bounded() -> None:
    cfg = RequestLogConfig()
    assert cfg.enabled == "auto"
    assert cfg.body_capture == "metadata"
    assert cfg.response_capture == "metadata"
    assert cfg.max_file_mb == 16 and cfg.max_total_mb == 256 and cfg.retention_days == 14
    assert cfg.stream_chunks is False and cfg.stream_chunk_max_bytes == 0


def test_body_capture_full_is_rejected_with_audit_pointer() -> None:
    with pytest.raises(ValueError, match="no plaintext/full body mode"):
        RequestLogConfig(body_capture="full")


def test_response_capture_full_is_rejected() -> None:
    with pytest.raises(ValueError, match="no plaintext/full body mode"):
        RequestLogConfig(response_capture="full")


def test_invalid_enabled_rejected() -> None:
    with pytest.raises(ValueError, match="logging.requests.enabled must be one of"):
        RequestLogConfig(enabled="yes")


def test_invalid_capture_value_rejected() -> None:
    with pytest.raises(ValueError, match="logging.requests.body_capture must be one of"):
        RequestLogConfig(body_capture="raw")


@pytest.mark.parametrize("field_name", ["max_file_mb", "max_total_mb", "retention_days", "stream_chunk_max_bytes"])
def test_bool_rejected_for_int_budgets(field_name: str) -> None:
    # Route bad-typed values through the coercer (Any-typed) -- the constructor's __post_init__
    # still runs and raises; this avoids static type-checker noise on intentional bad input.
    with pytest.raises(ValueError, match=f"logging.requests.{field_name} must be a non-negative int"):
        _coerce_request_log_config({field_name: True})


@pytest.mark.parametrize("field_name", ["max_file_mb", "retention_days"])
def test_negative_int_budgets_rejected(field_name: str) -> None:
    with pytest.raises(ValueError, match="must be a non-negative int"):
        _coerce_request_log_config({field_name: -1})


def test_stream_chunks_must_be_bool() -> None:
    with pytest.raises(ValueError, match="logging.requests.stream_chunks must be a bool"):
        _coerce_request_log_config({"stream_chunks": "true"})


def test_zero_budgets_allowed_as_unbounded() -> None:
    cfg = RequestLogConfig(max_total_mb=0, retention_days=0, max_file_mb=0)
    assert cfg.max_total_mb == 0 and cfg.retention_days == 0


def test_coerce_request_log_rejects_unknown_key() -> None:
    with pytest.raises(ValueError, match="Unknown logging.requests key"):
        _coerce_request_log_config({"enabled": "on", "captuer": "redacted"})


def test_coerce_request_log_roundtrip() -> None:
    cfg = _coerce_request_log_config({"enabled": "on", "body_capture": "redacted", "retention_days": 3})
    assert cfg.enabled == "on" and cfg.body_capture == "redacted" and cfg.retention_days == 3


def test_logging_config_nests_requests() -> None:
    lc = _coerce_logging_config({"requests": {"enabled": "off"}})
    assert isinstance(lc, LoggingConfig)
    assert lc.requests.enabled == "off"


def test_logging_config_rejects_unknown_subkey() -> None:
    with pytest.raises(ValueError, match="Unknown logging key"):
        _coerce_logging_config({"reqests": {"enabled": "on"}})


def test_logging_config_default_is_request_defaults() -> None:
    assert _coerce_logging_config(None).requests == RequestLogConfig()


# --- Loader wiring (both hops -- the provider_trace DOA trap) ---

_VALID_PROXY = {
    "proxy_format": 1,
    "template": "litellm-openai",
    "template_digest": "sha256:test",
    "provider": "litellm",
    "proxy_endpoint": "http://localhost:8085",
    "port": 8085,
    "upstream_base_url": "https://litellm.test.example.com",
    "tiers": {"haiku": "openai/gpt-5-mini", "sonnet": "openai/gpt-5.5", "opus": "openai/gpt-5.5"},
}


def test_logging_block_survives_both_loader_hops() -> None:
    from forge.config.loader import (
        _proxy_instance_to_forge_config,
        load_proxy_instance_config_from_dict,
    )

    instance = load_proxy_instance_config_from_dict(
        {**_VALID_PROXY, "logging": {"requests": {"enabled": "on", "body_capture": "redacted"}}}
    )
    assert instance.logging.requests.enabled == "on"

    forge_config = _proxy_instance_to_forge_config(instance)
    assert forge_config.proxy.logging.requests.enabled == "on"
    assert forge_config.proxy.logging.requests.body_capture == "redacted"


def test_logging_block_rejects_full_through_loader() -> None:
    from forge.config.loader import load_proxy_instance_config_from_dict

    with pytest.raises(ValueError, match="no plaintext/full body mode"):
        load_proxy_instance_config_from_dict({**_VALID_PROXY, "logging": {"requests": {"body_capture": "full"}}})
