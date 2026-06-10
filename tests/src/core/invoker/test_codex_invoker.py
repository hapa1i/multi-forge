"""Tests for CodexHeadlessInvoker + prepare_codex_request (Phase 5b, B3/B4).

The shared lifecycle (process groups, ordered fan-out, cancellation races) is proven
in ``test_claude_invoker.py``; these tests cover the Codex hooks: JSONL-stream result
building (replaying the B0 fixtures through a mocked subprocess), the never-retry
predicate, the ``codex`` binary error, and the request-builder's argv/env/attribution.
Subprocess is always mocked; ``isolate_forge_home`` gives a clean ledger.
"""

from __future__ import annotations

import signal
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from forge.core.invoker import (
    Attribution,
    CodexHeadlessInvoker,
    HeadlessRequest,
    prepare_codex_request,
)
from forge.core.runtime.codex_preflight import CodexPreflight

_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "codex"
_SUCCESS_STREAM = (_FIXTURES / "exec_json_success.jsonl").read_text()
_ERROR_STREAM = (_FIXTURES / "exec_json_error.jsonl").read_text()

_IDENT = {"FORGE_RUN_ID": "run_c", "FORGE_PARENT_RUN_ID": "run_verb", "FORGE_ROOT_RUN_ID": "run_root"}


def _codex_req(
    *,
    label: str = "c0",
    env: dict[str, str] | None = None,
    prompt: str = "p",
    attribution: Attribution | None = None,
    timeout: int = 600,
) -> HeadlessRequest:
    return HeadlessRequest(
        argv=["codex", "exec", "--json", "--sandbox", "workspace-write"],
        prompt=prompt,
        env=env if env is not None else {},
        cwd=None,
        timeout_seconds=timeout,
        label=label,
        provider="openai",
        output_format=None,
        base_url=None,
        attribution=attribution,
    )


def _mock_proc(stdout: str = _SUCCESS_STREAM, returncode: int = 0, stderr: str = "", *, communicate_side_effect=None):
    proc = MagicMock()
    if communicate_side_effect is not None:
        proc.communicate.side_effect = communicate_side_effect
    else:
        proc.communicate.return_value = (stdout, stderr)
    proc.returncode = returncode
    proc.poll.return_value = returncode
    proc.pid = 4242
    proc.wait.return_value = returncode
    return proc


def _preflight(
    *, auth_source: str = "credential_file", billing_mode: str = "api", auth_method: str | None = None
) -> CodexPreflight:
    if auth_method is None:
        auth_method = "chatgpt_tokens" if auth_source == "codex_store" else "api_key"
    return CodexPreflight(
        installed=True,
        version="0.137.0",
        version_ok=True,
        auth_method=auth_method,  # type: ignore[arg-type]
        auth_source=auth_source,
        billing_mode=billing_mode,  # type: ignore[arg-type]
        ready=True,
        blocking_reason=None,
        hook_seam="unknown",
        proxy_responses="native_direct",
        doctor_status="ok",
    )


class TestCodexResultBuilding:
    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_success_stream_reduced_to_text_and_tokens(self, mock_popen):
        mock_popen.return_value = _mock_proc(_SUCCESS_STREAM)
        out = CodexHeadlessInvoker().run_parallel([_codex_req()])
        r = out[0]
        assert r.stdout == "OK"
        assert (r.input_tokens, r.output_tokens, r.cached_tokens) == (14936, 22, 10624)
        assert r.runtime_is_error is False and r.success is True
        assert r.cost_micro_usd is None  # native runtime: no $ figure

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_error_stream_sets_runtime_is_error(self, mock_popen):
        mock_popen.return_value = _mock_proc(_ERROR_STREAM, returncode=1)
        out = CodexHeadlessInvoker().run_parallel([_codex_req()])
        r = out[0]
        assert r.runtime_is_error is True
        assert r.success is False and r.returncode == 1
        assert r.input_tokens is None  # failed turn carried no usage

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_error_message_surfaced_on_empty_stderr(self, mock_popen):
        # codex reports the failure reason in the JSONL stream with empty stderr; the
        # provider reason must reach stderr so callers don't see a blank failure.
        mock_popen.return_value = _mock_proc(_ERROR_STREAM, returncode=1, stderr="")
        out = CodexHeadlessInvoker().run_parallel([_codex_req()])
        assert out[0].runtime_is_error is True
        assert "not supported" in out[0].stderr

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_real_stderr_preserved_over_stream_error_message(self, mock_popen):
        mock_popen.return_value = _mock_proc(_ERROR_STREAM, returncode=1, stderr="actual stderr line")
        out = CodexHeadlessInvoker().run_parallel([_codex_req()])
        assert out[0].stderr == "actual stderr line"  # not overwritten by the stream reason

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_results_in_input_order(self, mock_popen):
        mock_popen.side_effect = [_mock_proc(_SUCCESS_STREAM) for _ in range(4)]
        out = CodexHeadlessInvoker().run_parallel([_codex_req(label=f"c{i}") for i in range(4)])
        assert [r.label for r in out] == [f"c{i}" for i in range(4)]

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_run_id_surfaced_from_env(self, mock_popen):
        mock_popen.return_value = _mock_proc(_SUCCESS_STREAM)
        out = CodexHeadlessInvoker().run_parallel([_codex_req(env=dict(_IDENT))])
        r = out[0]
        assert (r.run_id, r.parent_run_id, r.root_run_id) == ("run_c", "run_verb", "run_root")

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_thread_id_surfaced_as_runtime_session_id(self, mock_popen):
        mock_popen.return_value = _mock_proc(_SUCCESS_STREAM)
        out = CodexHeadlessInvoker().run(_codex_req())
        assert out.runtime_session_id == "019eaa51-6920-7c41-ae34-d4f7f368d55a"


class TestCodexLifecycleHooks:
    @patch("forge.core.invoker._lifecycle.os.getpgid", return_value=321)
    @patch("forge.core.invoker._lifecycle.os.killpg")
    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_timeout_kills_process_group(self, mock_popen, mock_killpg, _getpgid):
        proc = _mock_proc(communicate_side_effect=subprocess.TimeoutExpired(cmd="codex", timeout=1))
        proc.poll.return_value = 0
        mock_popen.return_value = proc
        out = CodexHeadlessInvoker().run_parallel([_codex_req(timeout=1)])
        assert out[0].timed_out is True and out[0].success is False
        assert any(call.args == (321, signal.SIGTERM) for call in mock_killpg.call_args_list)

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_single_shot_missing_binary(self, mock_popen):
        mock_popen.side_effect = FileNotFoundError()
        out = CodexHeadlessInvoker().run(_codex_req())
        assert out.success is False and out.error == "codex CLI not found in PATH"

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_no_format_retry_even_on_claude_rejection_stderr(self, mock_popen):
        # stderr that WOULD trip Claude's --output-format rejection regex; Codex's
        # predicate is always False, so there must be exactly one spawn (no retry).
        mock_popen.return_value = _mock_proc(
            _SUCCESS_STREAM, returncode=2, stderr="error: unknown option '--output-format'"
        )
        CodexHeadlessInvoker().run_parallel([_codex_req()])
        assert mock_popen.call_count == 1


class TestPrepareCodexRequest:
    def test_argv_is_codex_exec_json_with_sandbox_and_model(self):
        req = prepare_codex_request(
            prompt="hi", preflight=_preflight(), attribution=Attribution(command="bridge"), model="gpt-5.5"
        )
        assert req.argv == ["codex", "exec", "--json", "--sandbox", "workspace-write", "-m", "gpt-5.5"]
        assert req.output_format is None and req.base_url is None and req.provider == "openai"
        assert req.proxy_id is None

    def test_sandbox_override(self):
        req = prepare_codex_request(
            prompt="hi", preflight=_preflight(), attribution=Attribution(command="bridge"), sandbox="read-only"
        )
        assert req.argv[:5] == ["codex", "exec", "--json", "--sandbox", "read-only"]

    def test_resume_thread_id_appends_resume_subcommand_after_options(self):
        # Probe 60 form A: options BEFORE the `resume` subcommand; prompt stays on stdin.
        req = prepare_codex_request(
            prompt="continue",
            preflight=_preflight(),
            attribution=Attribution(command="codex-resume"),
            model="gpt-5.5",
            resume_thread_id="019eaa51-6920-7c41-ae34-d4f7f368d55a",
        )
        assert req.argv == [
            "codex",
            "exec",
            "--json",
            "--sandbox",
            "workspace-write",
            "-m",
            "gpt-5.5",
            "resume",
            "019eaa51-6920-7c41-ae34-d4f7f368d55a",
        ]
        assert req.prompt == "continue"

    def test_no_resume_subcommand_without_thread_id(self):
        req = prepare_codex_request(prompt="hi", preflight=_preflight(), attribution=Attribution(command="bridge"))
        assert "resume" not in req.argv

    @patch("forge.core.invoker.codex.codex_api_key_for_subprocess", return_value="sk-test-key")
    def test_credential_file_auth_injects_key(self, _key):
        req = prepare_codex_request(
            prompt="hi", preflight=_preflight(auth_source="credential_file"), attribution=Attribution(command="bridge")
        )
        assert req.env["CODEX_API_KEY"] == "sk-test-key"
        assert req.base_url is None

    @patch("forge.core.invoker.codex.codex_api_key_for_subprocess")
    def test_codex_store_auth_does_not_inject_key(self, mock_key, monkeypatch):
        monkeypatch.delenv("CODEX_API_KEY", raising=False)
        req = prepare_codex_request(
            prompt="hi", preflight=_preflight(auth_source="codex_store"), attribution=Attribution(command="bridge")
        )
        mock_key.assert_not_called()  # codex reads its own store; no injection
        assert "CODEX_API_KEY" not in req.env

    @patch("forge.core.invoker.codex.codex_api_key_for_subprocess", return_value=None)
    def test_env_sanitized_of_claude_proxy_and_contradicting_auth(self, _key, monkeypatch):
        # codex_store auth: the child must carry NO stale Codex key/token and NO inherited
        # Claude/proxy routing -- else the child contradicts the preflight (a stale
        # CODEX_API_KEY would override the ChatGPT login) or leaks the Anthropic key.
        for var, val in {
            "CODEX_API_KEY": "stale-key",
            "CODEX_ACCESS_TOKEN": "stale-token",
            "ANTHROPIC_API_KEY": "anthropic-key",
            "ANTHROPIC_BASE_URL": "http://proxy:8084",
            "ANTHROPIC_CUSTOM_HEADERS": "X-Forge-Run-ID: run_bad",
            "FORGE_SUBPROCESS_PROXY": "litellm-gemini",
            "FORGE_SUBPROCESS_BASE_URL": "http://proxy:8084",
            "FORGE_SUBPROCESS_PROXY_ID": "p1",
            "FORGE_SUBPROCESS_TEMPLATE": "litellm-gemini",
        }.items():
            monkeypatch.setenv(var, val)
        req = prepare_codex_request(
            prompt="hi", preflight=_preflight(auth_source="codex_store"), attribution=Attribution(command="bridge")
        )
        for leaked in (
            "CODEX_API_KEY",
            "CODEX_ACCESS_TOKEN",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_CUSTOM_HEADERS",
            "FORGE_SUBPROCESS_PROXY",
            "FORGE_SUBPROCESS_BASE_URL",
            "FORGE_SUBPROCESS_PROXY_ID",
            "FORGE_SUBPROCESS_TEMPLATE",
        ):
            assert leaked not in req.env, leaked
        assert req.base_url is None

    @patch("forge.core.invoker.codex.codex_api_key_for_subprocess", return_value="sk-resolved")
    def test_credential_file_auth_strips_inherited_key_then_injects_resolved(self, _key, monkeypatch):
        # An inherited env CODEX_API_KEY must not win over the Forge-resolved value
        # (respects auth_ignore_env): strip, then inject the resolver's key.
        monkeypatch.setenv("CODEX_API_KEY", "inherited-stale")
        req = prepare_codex_request(
            prompt="hi", preflight=_preflight(auth_source="credential_file"), attribution=Attribution(command="bridge")
        )
        assert req.env["CODEX_API_KEY"] == "sk-resolved"

    @patch("forge.core.invoker.codex.codex_api_key_for_subprocess", return_value=None)
    def test_enterprise_token_auth_restores_access_token(self, _key, monkeypatch):
        # auth_source=env via CODEX_ACCESS_TOKEN (no API key): the child keeps the token,
        # never a key -- a ready=True enterprise preflight must produce a usable child env.
        monkeypatch.setenv("CODEX_ACCESS_TOKEN", "ent-token")
        monkeypatch.delenv("CODEX_API_KEY", raising=False)
        req = prepare_codex_request(
            prompt="hi",
            preflight=_preflight(auth_source="env", auth_method="enterprise_token", billing_mode="unknown"),
            attribution=Attribution(command="bridge"),
        )
        assert req.env["CODEX_ACCESS_TOKEN"] == "ent-token"
        assert "CODEX_API_KEY" not in req.env

    def test_attribution_stamped_with_runtime_and_billing_mode(self):
        req = prepare_codex_request(
            prompt="hi",
            preflight=_preflight(billing_mode="subscription_quota"),
            attribution=Attribution(command="bridge", workflow="transfer", session="s1"),
        )
        assert req.attribution is not None
        assert req.attribution.runtime == "codex"
        assert req.attribution.billing_mode == "subscription_quota"
        # caller-supplied verb context preserved
        assert (req.attribution.command, req.attribution.workflow, req.attribution.session) == (
            "bridge",
            "transfer",
            "s1",
        )

    def test_run_tree_triple_stamped_from_parent_env(self, monkeypatch):
        monkeypatch.setenv("FORGE_RUN_ID", "parent_run")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "tree_root")
        monkeypatch.delenv("FORGE_PARENT_RUN_ID", raising=False)
        req = prepare_codex_request(prompt="hi", preflight=_preflight(), attribution=Attribution(command="bridge"))
        # Child gets a fresh run_id, parent == the spawner, root inherited (one run tree).
        assert req.env["FORGE_RUN_ID"] != "parent_run"
        assert req.env["FORGE_PARENT_RUN_ID"] == "parent_run"
        assert req.env["FORGE_ROOT_RUN_ID"] == "tree_root"

    def test_forge_depth_incremented_for_codex_child(self, monkeypatch):
        monkeypatch.setenv("FORGE_DEPTH", "1")
        req = prepare_codex_request(prompt="hi", preflight=_preflight(), attribution=Attribution(command="bridge"))
        assert req.env["FORGE_DEPTH"] == "2"
