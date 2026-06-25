"""Regression: a relocated provider_trace inject key in proxy.yaml warns and is ignored.

Bug class: silent config drop / stale recognized config. The ``inject_provider_user`` toggle moved
from per-proxy ``proxy.yaml`` to the global ``~/.forge/config.yaml`` so one switch governs both the
proxied and the direct OpenRouter routes (card: ``openrouter_user_direct_callers``). ``proxy.yaml``
is user-owned config (a system boundary, coding-standards section 5), so a ``proxy.yaml`` that still
carries the relocated key must warn-and-degrade (accepted, ignored, with a one-time notice naming the
new home), never be silently dropped into an apparently-valid default and never rejected as an
unknown key.

Root causes guarded:
1. ``ProviderTraceConfig`` no longer carries an inject field (it is retention-only).
2. The relocated key is accepted (no unknown-key reject) and emits exactly one relocation warning
   naming ``~/.forge/config.yaml`` + the ``forge config set`` command.
3. Retention siblings still apply alongside a relocated key; the warning is one-time per process.

Affected file: src/forge/config/schema.py (_coerce_provider_trace_config).
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

import forge.config.schema as schema_mod
from forge.config.schema import ProviderTraceConfig, ProxyConfig

pytestmark = pytest.mark.regression

_RELOCATION_MARKER = "moved to ~/.forge/config.yaml"


@pytest.fixture(autouse=True)
def _reset_legacy_warn_latch():
    # The relocation warning is one-time per process; reset the module latch so each test that
    # asserts on the warning actually sees it, regardless of test order.
    schema_mod._warned_legacy_inject_key = False
    yield
    schema_mod._warned_legacy_inject_key = False


def _provider_trace(**kwargs: Any) -> ProviderTraceConfig:
    # ProxyConfig coerces the provider_trace mapping in __post_init__ (see test_schema.py).
    cfg = ProxyConfig(provider_trace=dict(kwargs))  # type: ignore[arg-type]  # coerced in __post_init__
    assert isinstance(cfg.provider_trace, ProviderTraceConfig)
    return cfg.provider_trace


def test_inject_field_removed_from_proxy_schema():
    # The toggle moved to the global runtime config; the proxy-owned dataclass must not carry it.
    assert not hasattr(ProviderTraceConfig(), "inject_provider_user")


def test_relocated_key_accepted_ignored_with_one_warning(caplog):
    with caplog.at_level(logging.WARNING):
        pt = _provider_trace(inject_provider_user=True, retention_days=7)
    # Accepted (no reject) + retention sibling preserved + the key itself ignored (no field).
    assert pt.retention_days == 7
    assert not hasattr(pt, "inject_provider_user")
    moved = [m for m in caplog.messages if _RELOCATION_MARKER in m]
    assert len(moved) == 1
    assert "forge config set provider_trace.inject_provider_user=true" in moved[0]


def test_relocated_key_does_not_trip_unknown_key_reject():
    # Popped before _reject_unknown_keys, so it must not raise "Unknown provider_trace key",
    # and sibling real keys still apply.
    pt = _provider_trace(inject_provider_user=True, retention_days=7, max_total_mb=99)
    assert pt.retention_days == 7
    assert pt.max_total_mb == 99


def test_warning_is_one_time_per_process(caplog):
    # A config can be coerced repeatedly within a process; the module latch must suppress repeats.
    with caplog.at_level(logging.WARNING):
        _provider_trace(inject_provider_user=True)
        _provider_trace(inject_provider_user=True)
    moved = [m for m in caplog.messages if _RELOCATION_MARKER in m]
    assert len(moved) == 1
