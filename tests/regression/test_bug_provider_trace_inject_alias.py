"""Regression: provider_trace.inject_openrouter_user is honored as a deprecated alias.

Bug class: silent config drop. When the observability plane went provider-generic, the config
key inject_openrouter_user was renamed to inject_provider_user. proxy.yaml is user-owned config
(a system boundary, coding-standards section 5), so the old key must be honored with a
deprecation warning rather than rejected as an unknown key -- a strict reject would silently
disable an opt-in the user still has set, with no path to diagnose it.

Root causes guarded:
1. The old key still enables grouping and emits exactly one deprecation warning.
2. The old key carries its actual value (False stays False -- not "present -> True").
3. The new key wins verbatim when both are present (value used, not OR-ed with the old one).
4. The old key is popped before the strict allowlist, so it never trips _reject_unknown_keys.

Affected file: src/forge/config/schema.py (_coerce_provider_trace_config).
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

import forge.config.schema as schema_mod
from forge.config.schema import ProviderTraceConfig, ProxyConfig

pytestmark = pytest.mark.regression


@pytest.fixture(autouse=True)
def _reset_legacy_warn_latch():
    # The deprecation warning is one-time per process; reset the module latch so each test that
    # asserts on the warning actually sees it, regardless of test order.
    schema_mod._warned_legacy_inject_key = False
    yield
    schema_mod._warned_legacy_inject_key = False


def _provider_trace(**kwargs: Any) -> ProviderTraceConfig:
    # ProxyConfig coerces the provider_trace mapping in __post_init__ (see test_schema.py).
    cfg = ProxyConfig(provider_trace=dict(kwargs))  # type: ignore[arg-type]  # coerced in __post_init__
    assert isinstance(cfg.provider_trace, ProviderTraceConfig)
    return cfg.provider_trace


def test_legacy_key_is_honored_with_one_warning(caplog):
    with caplog.at_level(logging.WARNING):
        pt = _provider_trace(inject_openrouter_user=True)
    assert pt.inject_provider_user is True
    deprecations = [m for m in caplog.messages if "inject_openrouter_user is deprecated" in m]
    assert len(deprecations) == 1
    assert "rename it to inject_provider_user" in deprecations[0]


def test_legacy_key_false_is_honored():
    # The alias carries the actual value, not just "present -> True".
    assert _provider_trace(inject_openrouter_user=False).inject_provider_user is False


def test_new_key_wins_when_both_present(caplog):
    # new=False + old=True: the new key's value is used verbatim. If the old key were OR-ed in
    # the result would be True, so False here proves the new key wins (and the old is ignored).
    with caplog.at_level(logging.WARNING):
        pt = _provider_trace(inject_provider_user=False, inject_openrouter_user=True)
    assert pt.inject_provider_user is False
    assert any("ignored because" in m for m in caplog.messages)


def test_legacy_key_does_not_trip_unknown_key_reject():
    # Popped before _reject_unknown_keys, so it must not raise "Unknown provider_trace key",
    # and a sibling real key still applies.
    pt = _provider_trace(inject_openrouter_user=True, retention_days=7)
    assert pt.inject_provider_user is True
    assert pt.retention_days == 7


def test_warning_is_one_time_per_process(caplog):
    # The doc promises a one-time deprecation warning; the module latch must suppress repeats so a
    # config coerced repeatedly within a process does not spam the log. The value is still honored
    # on every coercion -- only the warning is latched.
    with caplog.at_level(logging.WARNING):
        first = _provider_trace(inject_openrouter_user=True)
        second = _provider_trace(inject_openrouter_user=True)
    assert first.inject_provider_user is True
    assert second.inject_provider_user is True
    deprecations = [m for m in caplog.messages if "inject_openrouter_user is deprecated" in m]
    assert len(deprecations) == 1
