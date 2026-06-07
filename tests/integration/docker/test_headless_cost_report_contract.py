"""Headless cost-report contract test (Phase 5a spike) -- the CI twin of reproduce.sh.

Question (the Phase 5 hard gate): does ``claude -p --output-format json`` expose
per-run cost (``total_cost_usd``) and token ``usage`` that Forge can RECORD, for
the direct-API-key auth mode in CI? Card north star: present -> record with
provenance ``reported``; absent -> ``unavailable``; NEVER estimate.

This pins the API-key row of ``scripts/experiments/headless-cost-report/`` in CI,
through the real Claude binary in Docker and the SAME production parser the wiring
uses (``parse_headless_envelope``) -- so a CLI change that drops or reshapes the
envelope fails here, not silently in production.

Verdict vocabulary mirrors reproduce.sh: ``[JSON-INCOMPATIBLE]`` / ``[COST-ABSENT]``
/ ``[USAGE-ABSENT]`` describe the failure modes; the DECISION is GO (cost +
usage reported) for direct API key.

Narrow assertions: field presence + exit codes, never LLM prose.

Run:
    ./scripts/test-integration.sh tests/integration/docker/test_headless_cost_report_contract.py -v
"""

from __future__ import annotations

import os

import pytest

from forge.core.reactive.structured_output import parse_headless_envelope
from tests.fixtures.docker import ContainerLike
from tests.integration.docker.conftest import run_claude_print, setup_real_claude

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_in,
    pytest.mark.slow,
]


@pytest.fixture(scope="module", autouse=True)
def _require_anthropic_api_key() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.fail("ANTHROPIC_API_KEY not set. Add it to your environment/.env and re-run integration tests.")


class TestHeadlessCostReportContract:
    def test_direct_api_key_envelope_reports_cost_and_usage(self, forge_workspace: ContainerLike) -> None:
        setup_real_claude(forge_workspace, session_name="headless-cost-contract")

        exit_code, stdout, stderr = run_claude_print(
            forge_workspace,
            "Reply with exactly: ok",
            session_name="headless-cost-contract",
            extra_args=["--output-format", "json"],
            timeout=60,
        )
        assert exit_code == 0, f"claude -p --output-format json exited {exit_code}; stderr={stderr!r}"

        # Parse with the PRODUCTION parser (not a bespoke one) so the contract test
        # and the wiring agree on shape handling by construction.
        env = parse_headless_envelope(stdout)

        # [JSON-INCOMPATIBLE] guard: the envelope must parse to a usable result.
        assert env.parsed is True, f"[JSON-INCOMPATIBLE] envelope did not parse; stdout head={stdout[:300]!r}"
        # .result must round-trip the model text (text consumers depend on this).
        assert env.result_text.strip(), "result text must be non-empty"
        # DECISION (direct API key): GO -> cost AND usage reported.
        assert (
            env.cost_micro_usd is not None
        ), f"[COST-ABSENT] direct API key must report total_cost_usd (5a); {stderr!r}"
        assert env.cost_micro_usd >= 0
        assert env.input_tokens is not None, "[USAGE-ABSENT] usage.input_tokens must be reported"
        assert env.output_tokens is not None, "[USAGE-ABSENT] usage.output_tokens must be reported"
