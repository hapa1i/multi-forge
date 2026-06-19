"""Tests for emit_codex_usage (Phase 5c).

A native ``codex exec`` run is DIRECT to OpenAI: tokens are reported by the JSONL
stream, but there is no Forge proxy cost record, so the event carries exact tokens
with no cost and ``confidence="unavailable"`` (the ledger's confidence is a cost
signal). The autouse ``isolate_forge_home`` fixture gives each test a clean ledger.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from forge.core.invoker import Attribution, CodexHeadlessInvoker, HeadlessRequest
from forge.core.telemetry.downstream import read_downstream_records
from forge.core.usage import emit_codex_usage, emit_worker_usage
from forge.core.usage.ledger import read_usage_events

_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "codex"
_SUCCESS_STREAM = (_FIXTURES / "exec_json_success.jsonl").read_text()


class TestEmitCodexUsageProvenance:
    def test_reserved_literals_and_honest_cost_absence(self):
        emit_codex_usage(
            run_id="run_c",
            parent_run_id="run_verb",
            root_run_id="run_root",
            command="bridge",
            status="success",
            billing_mode="api",
            model="gpt-5.5",
            input_tokens=14936,
            output_tokens=22,
            cached_tokens=10624,
        )
        events = read_usage_events()
        assert len(events) == 1
        e = events[0]
        assert e.route == "codex_exec"
        assert e.reporter == "codex_jsonl"
        assert e.measurement_source == "runtime_native"
        assert e.confidence == "unavailable"  # cost-only signal; Codex reports no $
        assert e.cost_micro_usd is None
        assert e.source_refs is None  # direct to OpenAI: no proxy request_id exists
        assert (e.input_tokens, e.output_tokens, e.cached_tokens) == (14936, 22, 10624)
        assert e.billing_mode == "api"
        assert e.runtime == "codex"
        assert e.attribution_granularity == "worker"
        assert (e.run_id, e.parent_run_id, e.root_run_id) == (
            "run_c",
            "run_verb",
            "run_root",
        )
        assert read_downstream_records(kind="attempt")[0].backend_id is None

    def test_billing_mode_defaults_to_unknown(self):
        emit_codex_usage(run_id="run_c", command="bridge", status="success")
        assert read_usage_events()[0].billing_mode == "unknown"

    def test_no_run_id_no_event(self):
        emit_codex_usage(run_id="", command="bridge", status="success")
        assert read_usage_events() == []


class TestInvokerPathEmission:
    _IDENT = {
        "FORGE_RUN_ID": "run_c",
        "FORGE_PARENT_RUN_ID": "run_verb",
        "FORGE_ROOT_RUN_ID": "run_root",
    }

    def _req(self, attribution: Attribution | None) -> HeadlessRequest:
        return HeadlessRequest(
            argv=["codex", "exec", "--json", "--sandbox", "workspace-write"],
            prompt="p",
            env=dict(self._IDENT),
            output_format=None,
            base_url=None,
            provider="openai",
            attribution=attribution,
        )

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_attribution_emits_one_codex_event(self, mock_popen):
        from unittest.mock import MagicMock

        proc = MagicMock()
        proc.communicate.return_value = (_SUCCESS_STREAM, "")
        proc.returncode = 0
        proc.poll.return_value = 0
        proc.pid = 4242
        mock_popen.return_value = proc

        attr = Attribution(
            command="bridge",
            workflow="transfer",
            session="s1",
            runtime="codex",
            billing_mode="api",
        )
        CodexHeadlessInvoker().run_parallel([self._req(attr)])

        events = read_usage_events()
        assert len(events) == 1
        e = events[0]
        assert e.route == "codex_exec" and e.runtime == "codex"
        assert (e.run_id, e.parent_run_id, e.root_run_id) == (
            "run_c",
            "run_verb",
            "run_root",
        )
        assert (e.input_tokens, e.output_tokens, e.cached_tokens) == (14936, 22, 10624)
        assert (e.command, e.workflow, e.session) == ("bridge", "transfer", "s1")

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_no_attribution_no_event(self, mock_popen):
        from unittest.mock import MagicMock

        proc = MagicMock()
        proc.communicate.return_value = (_SUCCESS_STREAM, "")
        proc.returncode = 0
        proc.poll.return_value = 0
        proc.pid = 4242
        mock_popen.return_value = proc

        CodexHeadlessInvoker().run_parallel([self._req(None)])
        assert read_usage_events() == []


class TestRunTreeJoin:
    """5e anchor: a Codex leaf and a Claude leaf under the same root are joinable."""

    def test_codex_and_claude_events_share_root(self):
        emit_worker_usage(
            run_id="run_claude",
            parent_run_id="run_verb",
            root_run_id="shared_root",
            command="panel",
            status="success",
        )
        emit_codex_usage(
            run_id="run_codex",
            parent_run_id="run_verb",
            root_run_id="shared_root",
            command="bridge",
            status="success",
            input_tokens=100,
            output_tokens=10,
        )
        joined = read_usage_events(root_run_id="shared_root")
        assert {e.run_id for e in joined} == {"run_claude", "run_codex"}
        codex_events = read_usage_events(runtime="codex", root_run_id="shared_root")
        assert [e.route for e in codex_events] == ["codex_exec"]
