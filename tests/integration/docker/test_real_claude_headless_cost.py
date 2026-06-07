"""Real-Claude headless cost/usage: the production seam against the live binary.

The contract twin (``test_headless_cost_report_contract.py``) pins the raw
envelope. This test drives the PRODUCTION code path -- ``run_claude_session``
(memory writer / supervisor / curation share it) -- against the real Claude binary
in Docker, and asserts the seam unwraps ``.result`` AND lifts the runtime's
self-reported cost/usage onto the ``SessionResult``:

- ``stdout`` is the unwrapped model text (NOT the JSON envelope) -> text consumers
  unchanged.
- ``envelope_parsed`` is True, ``cost_micro_usd`` is reported (direct API key,
  5a verdict), ``input_tokens`` is captured.

The memory-writer / worker real-Claude tests assert the verb/worker LEDGER events
(``reporter="claude_code"``); this asserts the SessionResult fields the emit layer
reads, so a regression is localized to the right layer.

Narrow assertions: field presence + exit codes, never LLM prose.

Run:
    ./scripts/test-integration.sh tests/integration/docker/test_real_claude_headless_cost.py -v
"""

from __future__ import annotations

import json
import os

import pytest

from tests.fixtures.docker import ContainerLike
from tests.integration.docker.conftest import setup_real_claude

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_in,
    pytest.mark.slow,
]


@pytest.fixture(scope="module", autouse=True)
def _require_anthropic_api_key() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.fail("ANTHROPIC_API_KEY not set. Add it to your environment/.env and re-run integration tests.")


# Run run_claude_session in-container and emit its SessionResult fields as JSON.
# Heredoc body is single-quoted (no host-side shell expansion); the API key arrives
# via env, never interpolated into the snippet.
_PROBE = """
export ANTHROPIC_API_KEY=$(cat /tmp/.anthropic_key)
export FORGE_RUN_ID=run_headless_cost FORGE_ROOT_RUN_ID=run_headless_cost
cd /workspace && /forge/.venv/bin/python - <<'PY'
import json
from forge.core.reactive.session_runner import run_claude_session

r = run_claude_session("Reply with exactly: ok", timeout_seconds=60)
print("FORGE_RESULT=" + json.dumps({
    "returncode": r.returncode,
    "success": r.success,
    "envelope_parsed": r.envelope_parsed,
    "cost_micro_usd": r.cost_micro_usd,
    "input_tokens": r.input_tokens,
    "output_tokens": r.output_tokens,
    "stdout_head": r.stdout[:120],
}))
PY
"""


class TestRealClaudeHeadlessCost:
    def test_run_claude_session_unwraps_and_self_reports_cost(self, forge_workspace: ContainerLike) -> None:
        setup_real_claude(forge_workspace, session_name="headless-cost")

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        forge_workspace.exec(f"cat > /tmp/.anthropic_key << 'KEY_EOF'\n{api_key}\nKEY_EOF")
        try:
            result = forge_workspace.exec(_PROBE, timeout=120)
        finally:
            forge_workspace.exec("rm -f /tmp/.anthropic_key")

        assert result.returncode == 0, f"probe failed: stdout={result.stdout!r} stderr={result.stderr!r}"
        marker = next((ln for ln in result.stdout.splitlines() if ln.startswith("FORGE_RESULT=")), None)
        assert marker is not None, f"no FORGE_RESULT marker; stdout={result.stdout!r}"
        payload = json.loads(marker[len("FORGE_RESULT=") :])

        assert payload["returncode"] == 0
        assert payload["success"] is True
        # The seam unwrapped the envelope: stdout is model text, not the JSON wrapper.
        assert payload["envelope_parsed"] is True
        assert "total_cost_usd" not in payload["stdout_head"]
        # Direct API key -> the runtime self-reports cost + usage (5a verdict).
        assert payload["cost_micro_usd"] is not None
        assert payload["cost_micro_usd"] >= 0
        assert payload["input_tokens"] is not None
        assert payload["output_tokens"] is not None
