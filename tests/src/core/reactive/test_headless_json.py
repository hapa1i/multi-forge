"""Unit tests for the shared headless-JSON capability + conversion helpers.

Covers ``src/forge/core/reactive/headless_json.py`` (Phase 5): the USD->micros
conversion (``usd_to_micros``), the retry-once-and-latch capability guard
(``should_request_json`` / ``prepare_json_argv`` / ``is_json_flag_rejection`` /
``mark_json_output_unsupported``), and the spike-verdict constants.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest

from forge.core.reactive import headless_json as hj


@pytest.fixture(autouse=True)
def _reset_latch() -> Iterator[None]:
    # The capability latch is process-global; reset around every test so order
    # never leaks a "json unsupported" flag between cases.
    hj.reset_json_capability_cache()
    yield
    hj.reset_json_capability_cache()


class TestUsdToMicros:
    @pytest.mark.parametrize(
        "usd,expected",
        [
            (0.0269, 26900),
            (0.0299, 29900),
            (0.0023, 2300),
            (0.1, 100000),
            (0.07, 70000),
            (1.23, 1230000),
            (0.0, 0),
            (1e-7, 0),  # below micro granularity -> truncates to 0
            (12.345678, 12345678),
        ],
    )
    def test_exact_on_float_hostile_values(self, usd: float, expected: int) -> None:
        # int(Decimal(str(usd)) * 1e6) avoids binary-float drift that round(x*1e6)
        # would introduce on values like 0.07 / 0.0269.
        assert hj.usd_to_micros(usd) == expected

    def test_int_input(self) -> None:
        assert hj.usd_to_micros(2) == 2_000_000

    @pytest.mark.parametrize("bad", [None, True, False, "0.01", "nan", object()])
    def test_non_numeric_and_bool_rejected(self, bad: object) -> None:
        # bool is an int subclass; a JSON `true` must never read as cost 1.
        assert hj.usd_to_micros(bad) is None

    def test_matches_proxy_conversion_on_realistic_corpus(self) -> None:
        # Parity guard (#4): the ledger conversion and the proxy cost-plane
        # conversion (client_adapter.py: round(cost_usd * 1_000_000)) must agree on
        # every realistic 4-significant-figure cost figure, so a direct claude_code
        # cost and a forge_proxy cost are denominated identically. They run on
        # SEPARATE planes (a run is proxied XOR direct), so they never convert the
        # same value -- but agreement on the common range guards silent drift.
        def proxy_round(usd: float) -> int:
            return round(usd * 1_000_000)

        realistic = [0.0269, 0.0299, 0.0023, 0.1, 0.07, 0.03, 1.23, 0.0,
                     0.299999, 12.345678, 0.000001, 0.05, 2.5, 0.0011]
        for usd in realistic:
            assert hj.usd_to_micros(usd) == proxy_round(usd), usd

    def test_known_half_micro_divergence_is_pinned_not_silent(self) -> None:
        # DOCUMENTED, bounded discrepancy (<=1 micro = $0.000001), only at exact
        # half-micro fractions real cost reports never emit: truncate (ledger) vs
        # round-half-even (proxy). Pinned here so aligning the two later is a
        # deliberate, test-visible decision -- not a silent change. See Phase 5
        # change-log follow-up note.
        assert hj.usd_to_micros(1.5e-6) == 1  # truncates
        assert round(1.5e-6 * 1_000_000) == 2  # banker's-rounds up
        assert hj.usd_to_micros(1.0000005) == 1_000_000
        assert round(1.0000005 * 1_000_000) == 1_000_001

    def test_decimal_string_construction_avoids_binary_drift(self) -> None:
        # 0.07 in binary float is 0.0700000000000000066...; round(0.07*1e6) happens
        # to land on 70000 here, but the Decimal(str()) path is exact by construction.
        assert hj.usd_to_micros(0.07) == int(Decimal("0.07") * 1_000_000)


class TestCapabilityGuard:
    def test_requests_json_by_default(self) -> None:
        assert hj.should_request_json(["claude", "-p"]) is True

    def test_latch_suppresses_after_rejection(self) -> None:
        assert hj.should_request_json(["claude", "-p"]) is True
        hj.mark_json_output_unsupported()
        assert hj.should_request_json(["claude", "-p"]) is False

    def test_reset_clears_latch(self) -> None:
        hj.mark_json_output_unsupported()
        assert hj.should_request_json(["claude", "-p"]) is False
        hj.reset_json_capability_cache()
        assert hj.should_request_json(["claude", "-p"]) is True

    def test_incompatible_carveout_suppresses_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The 5a matrix found NONE incompatible (empty frozenset), but the carve-out
        # mechanism must work for a future regression. Monkeypatch a token in.
        monkeypatch.setattr(hj, "_JSON_INCOMPATIBLE", frozenset({"--bare"}))
        assert hj.should_request_json(["claude", "-p", "--bare"]) is False
        assert hj.should_request_json(["claude", "-p"]) is True

    def test_prepare_json_argv_appends_when_allowed(self) -> None:
        argv, requested = hj.prepare_json_argv(["claude", "-p"], "json")
        assert requested is True
        assert argv == ["claude", "-p", "--output-format", "json"]

    def test_prepare_json_argv_skips_when_output_format_none(self) -> None:
        argv, requested = hj.prepare_json_argv(["claude", "-p"], None)
        assert requested is False
        assert argv == ["claude", "-p"]
        assert "--output-format" not in argv

    def test_prepare_json_argv_skips_when_latched(self) -> None:
        hj.mark_json_output_unsupported()
        argv, requested = hj.prepare_json_argv(["claude", "-p"], "json")
        assert requested is False
        assert argv == ["claude", "-p"]

    def test_prepare_json_argv_does_not_mutate_input(self) -> None:
        base = ["claude", "-p"]
        argv, _ = hj.prepare_json_argv(base, "json")
        assert base == ["claude", "-p"]  # caller's argv untouched
        assert argv is not base


class TestIsJsonFlagRejection:
    @pytest.mark.parametrize(
        "stderr",
        [
            "error: unknown option '--output-format'",
            "unrecognized arguments: --output-format json",
            "invalid choice for --output-format",
            "unexpected argument '--output-format'",
        ],
    )
    def test_nonzero_with_rejection_message_is_rejection(self, stderr: str) -> None:
        assert hj.is_json_flag_rejection(2, stderr) is True

    def test_zero_exit_is_never_a_rejection(self) -> None:
        assert hj.is_json_flag_rejection(0, "unknown option --output-format") is False

    def test_nonzero_unrelated_error_is_not_a_rejection(self) -> None:
        assert hj.is_json_flag_rejection(1, "model overloaded, try again") is False

    def test_none_stderr_is_safe(self) -> None:
        assert hj.is_json_flag_rejection(2, None) is False


def test_is_error_reliable_constant_is_true() -> None:
    # 5a confirmed is_error is a trustworthy top-level field -> map it into status.
    assert hj.treat_is_error_as_failure() is True
