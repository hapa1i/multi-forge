"""Tests for forge.review.engine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from forge.core.invoker import (
    Attribution,
    ClaudeHeadlessInvoker,
    CodexHeadlessInvoker,
    HeadlessRequest,
    HeadlessResult,
)
from forge.core.reactive.routing import ModelRoute, RoutingResult, RoutingSource
from forge.core.runtime.codex_preflight import CodexPreflight
from forge.review.engine import (
    _prepare_worker,
    _to_review_result,
    preflight_check,
    run_multi_review,
)
from forge.review.models import DEFAULT_MODELS, ModelAvailability, ModelSpec, PromptMode
from forge.review.routing import WorkerRoutingPlan

_CODEX_SUCCESS_STREAM = (Path(__file__).resolve().parents[2] / "fixtures/codex/exec_json_success.jsonl").read_text()


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch):
    """Ensure ANTHROPIC_API_KEY is absent so --bare auto-detect is off by default."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _claude_cli_available(monkeypatch):
    """Preflight tests opt out explicitly when they need to simulate a missing worker runtime."""
    monkeypatch.setattr("forge.review.engine.shutil.which", lambda name: "/usr/local/bin/claude")


def _spec(
    name: str = "test-model",
    family: str = "openai",
    preferred_proxy: str | None = "test-proxy",
    provider_refs: tuple[tuple[str, str], ...] | None = None,
    prompt: str | None = None,
    prompt_mode: PromptMode = "override",
    runtime: str = "claude_code",
) -> ModelSpec:
    if provider_refs is None:
        if preferred_proxy:
            provider_refs = (("openrouter", f"openai/{name}"),)
        else:
            provider_refs = (("direct", name),)
    return ModelSpec(
        name=name,
        model_id=name,
        family=family,
        provider_refs=provider_refs,
        description="Test",
        preferred_proxy=preferred_proxy,
        prompt=prompt,
        prompt_mode=prompt_mode,
        runtime=runtime,
    )


def _codex_spec() -> ModelSpec:
    return ModelSpec(
        name="codex",
        model_id="codex-default",
        family="openai",
        provider_refs=(),
        description="Native Codex",
        runtime="codex",
    )


def _route(
    provider: str = "openrouter",
    model_ref: str = "openai/gpt-5.5",
    template_id: str = "openrouter-openai",
    credential: str = "openrouter",
    family: str = "openai",
) -> ModelRoute:
    return ModelRoute(
        provider=provider,
        credential=credential,
        family=family,
        template_id=template_id if provider != "direct" else None,
        template_family=family if provider != "direct" else None,
        model_ref=model_ref,
    )


def _routing_result(
    route: ModelRoute | None = None,
    base_url: str | None = "http://localhost:8096",
    source: RoutingSource = "preferred_proxy",
) -> RoutingResult:
    if route is None:
        route = _route()
    return RoutingResult(
        base_url=base_url,
        proxy_id="test-proxy",
        template="openrouter-openai",
        source=source,
        route=route,
        credential=route.credential if route else None,
    )


def _runtime_native_result() -> RoutingResult:
    return RoutingResult(
        base_url=None,
        proxy_id=None,
        template=None,
        source="runtime_native",
        route=None,
        credential=None,
    )


def _plan(*results: RoutingResult, codex_preflight: CodexPreflight | None = None) -> WorkerRoutingPlan:
    return WorkerRoutingPlan(
        routes=tuple(results),
        resolved_at="2026-05-14T12:00:00Z",
        via_override=None,
        codex_preflight=codex_preflight,
    )


def _codex_preflight(
    *,
    ready: bool = True,
    blocking_reason: str | None = None,
    billing_mode: str = "subscription_quota",
) -> CodexPreflight:
    return CodexPreflight(
        installed=True,
        version="0.145.0",
        version_ok=True,
        auth_method="chatgpt_tokens",
        auth_source="codex_store",
        billing_mode=billing_mode,  # type: ignore[arg-type]
        ready=ready,
        blocking_reason=blocking_reason,
        hook_seam="enrollment_gated",
        proxy_responses="native_direct",
        doctor_status="ok",
    )


def _mock_popen(stdout: str = "review output", returncode: int = 0, stderr: str = ""):
    """Create a mock Popen that returns given output."""
    proc = MagicMock()
    proc.communicate.return_value = (stdout, stderr)
    proc.returncode = returncode
    proc.poll.return_value = returncode
    proc.pid = 12345
    return proc


class TestRunMultiReview:
    def test_default_claude_quorum_request_shape_golden(self):
        specs = list(DEFAULT_MODELS.values())
        routes = [
            (
                _route(
                    provider="openrouter",
                    model_ref=spec.provider_refs[0][1],
                    family=spec.family,
                )
                if spec.preferred_proxy
                else _route(
                    provider="direct",
                    model_ref=spec.provider_refs[0][1],
                    family=spec.family,
                    credential="anthropic-api",
                )
            )
            for spec in specs
        ]
        plan = _plan(
            *[
                _routing_result(
                    route=route,
                    base_url=None if route.provider == "direct" else f"http://proxy-{idx}:8096",
                    source="direct" if route.provider == "direct" else "preferred_proxy",
                )
                for idx, route in enumerate(routes)
            ]
        )
        attribution = Attribution(command="panel", workflow="review", session="golden")
        captured: list[HeadlessRequest] = []

        def build_env(*, base_url=None, direct=False, extra_vars=None):
            return {
                "ENV_KIND": "direct" if direct else str(base_url),
                **(extra_vars or {}),
            }

        def run_parallel(_self, requests):
            captured.extend(requests)
            return [
                HeadlessResult(
                    label=request.label,
                    stdout="ok",
                    stderr="",
                    returncode=0,
                    duration_seconds=1.0,
                )
                for request in requests
            ]

        with (
            patch("forge.review.engine.resolve_env_or_credential", return_value=None),
            patch("forge.review.engine.build_claude_env", side_effect=build_env),
            patch("forge.review.engine.direct_model_env", return_value={"DIRECT_MODEL": "pinned"}),
            patch("forge.review.engine.can_use_bare", return_value=False),
            patch("forge.review.engine.ClaudeHeadlessInvoker.run_parallel", new=run_parallel),
        ):
            run_multi_review(
                "review prompt",
                models=specs,
                routing_plan=plan,
                timeout_seconds=321,
                cwd="/worktree",
                attribution=attribution,
                reasoning_effort="high",
            )

        assert captured == [
            HeadlessRequest(
                argv=["claude", "-p", "--model", routes[0].model_ref, "--effort", "high"],
                prompt="review prompt",
                env={"ENV_KIND": "http://proxy-0:8096", "FORGE_COMMAND": "review"},
                cwd="/worktree",
                timeout_seconds=321,
                label=specs[0].effective_worker_id,
                model=routes[0].model_ref,
                provider=routes[0].provider,
                proxy_id="test-proxy",
                attribution=attribution,
                base_url="http://proxy-0:8096",
            ),
            HeadlessRequest(
                argv=["claude", "-p", "--model", routes[1].model_ref, "--effort", "high"],
                prompt="review prompt",
                env={"ENV_KIND": "http://proxy-1:8096", "FORGE_COMMAND": "review"},
                cwd="/worktree",
                timeout_seconds=321,
                label=specs[1].effective_worker_id,
                model=routes[1].model_ref,
                provider=routes[1].provider,
                proxy_id="test-proxy",
                attribution=attribution,
                base_url="http://proxy-1:8096",
            ),
            HeadlessRequest(
                argv=["claude", "-p", "--effort", "high"],
                prompt="review prompt",
                env={"ENV_KIND": "direct", "FORGE_COMMAND": "review", "DIRECT_MODEL": "pinned"},
                cwd="/worktree",
                timeout_seconds=321,
                label=specs[2].effective_worker_id,
                model=routes[2].model_ref,
                provider=routes[2].provider,
                proxy_id="test-proxy",
                attribution=attribution,
                base_url=None,
            ),
        ]

    @patch("forge.review.engine.ClaudeHeadlessInvoker.run_parallel")
    @patch("forge.review.engine.CodexHeadlessInvoker.run_parallel")
    def test_codex_only_uses_codex_parallel_dispatch(self, mock_codex_parallel, mock_claude_parallel):
        preflight = _codex_preflight()
        plan = _plan(_runtime_native_result(), codex_preflight=preflight)
        mock_codex_parallel.return_value = [
            HeadlessResult(
                label="codex",
                stdout="codex review",
                stderr="",
                returncode=0,
                duration_seconds=1.0,
            )
        ]

        output = run_multi_review("review", models=[_codex_spec()], routing_plan=plan)

        assert output.results[0].stdout == "codex review"
        mock_codex_parallel.assert_called_once()
        mock_claude_parallel.assert_not_called()
        request = mock_codex_parallel.call_args.args[0][0]
        assert request.argv == ["codex", "exec", "--json", "--sandbox", "read-only"]

    @patch("forge.review.engine.ClaudeHeadlessInvoker.run_parallel")
    @patch("forge.review.engine.CodexHeadlessInvoker.run_parallel")
    @patch("forge.review.engine.run_grouped_parallel")
    def test_mixed_runtime_dispatch_uses_one_grouped_pool(
        self,
        mock_grouped,
        mock_codex_parallel,
        mock_claude_parallel,
    ):
        specs = [_spec("claude-worker"), _codex_spec(), _spec("claude-worker-2")]
        plan = _plan(
            _routing_result(),
            _runtime_native_result(),
            _routing_result(),
            codex_preflight=_codex_preflight(),
        )

        def outcomes(jobs):
            return [
                HeadlessResult(
                    label=request.label,
                    stdout=f"out-{request.label}",
                    stderr="",
                    returncode=0,
                    duration_seconds=1.0,
                )
                for _invoker, request in jobs
            ]

        mock_grouped.side_effect = outcomes

        output = run_multi_review("review", models=specs, routing_plan=plan, reasoning_effort="high")

        mock_grouped.assert_called_once()
        mock_codex_parallel.assert_not_called()
        mock_claude_parallel.assert_not_called()
        jobs = mock_grouped.call_args.args[0]
        assert [type(invoker) for invoker, _request in jobs] == [
            ClaudeHeadlessInvoker,
            CodexHeadlessInvoker,
            ClaudeHeadlessInvoker,
        ]
        assert [request.label for _invoker, request in jobs] == ["claude-worker", "codex", "claude-worker-2"]
        assert "--effort" in jobs[0][1].argv
        assert "--effort" not in jobs[1][1].argv
        assert [result.model_name for result in output.results] == ["claude-worker", "codex", "claude-worker-2"]

    @patch("forge.review.engine.CodexHeadlessInvoker.run_parallel")
    def test_codex_without_frozen_preflight_fails_without_spawn(self, mock_parallel):
        plan = _plan(_runtime_native_result())

        output = run_multi_review("review", models=[_codex_spec()], routing_plan=plan)

        assert output.failed == 1
        assert "forge runtime preflight codex" in (output.results[0].error or "")
        mock_parallel.assert_not_called()

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_codex_worker_emits_runtime_native_usage_and_one_direct_downstream_attempt(self, mock_popen):
        from forge.cli.workflow import _resolved_models_summary
        from forge.core.telemetry.downstream import read_downstream_records
        from forge.core.usage.ledger import read_usage_events

        mock_popen.return_value = _mock_popen(_CODEX_SUCCESS_STREAM)
        spec = _codex_spec()
        plan = _plan(_runtime_native_result(), codex_preflight=_codex_preflight())
        with patch.dict(
            "os.environ",
            {"FORGE_RUN_ID": "run_verb", "FORGE_ROOT_RUN_ID": "run_root"},
        ):
            output = run_multi_review(
                "review",
                models=[spec],
                routing_plan=plan,
                attribution=Attribution(command="panel", workflow="panel", session="s1"),
            )

        result = output.results[0]
        assert result.success is True
        assert result.stdout == "OK"
        assert result.run_id is not None

        events = read_usage_events(run_id=result.run_id)
        assert len(events) == 1
        event = events[0]
        assert (event.route, event.runtime, event.billing_mode) == (
            "codex_exec",
            "codex",
            "subscription_quota",
        )
        assert (event.provider, event.model, event.proxy_id) == ("openai", None, None)
        assert (event.input_tokens, event.output_tokens, event.cached_tokens) == (14936, 22, 10624)
        assert event.cost_micro_usd is None

        attempts = read_downstream_records(kind="attempt", forge_run_id=result.run_id)
        assert len(attempts) == 1
        attempt = attempts[0]
        assert (attempt.source_kind, attempt.provider, attempt.backend_id) == ("provider", "openai", None)
        assert (attempt.input_tokens, attempt.output_tokens, attempt.cached_tokens) == (14936, 22, 10624)
        assert attempt.cost_micros is None
        assert attempt.proxy_id is None
        assert attempt.request_id is None
        assert attempt.provider_request_id is None
        assert attempt.audit_record_type is None

        summary = _resolved_models_summary([spec], plan)["codex"]
        assert (summary["provider"], summary["runtime"]) == (event.provider, event.runtime)

    @patch("forge.review.engine.run_grouped_parallel")
    @patch("forge.review.engine.ClaudeHeadlessInvoker.run_parallel")
    @patch("forge.review.engine.CodexHeadlessInvoker.run_parallel")
    def test_resume_with_codex_fails_whole_invocation_without_spawn(
        self,
        mock_codex_parallel,
        mock_claude_parallel,
        mock_grouped,
    ):
        specs = [_spec("claude-worker"), _codex_spec()]
        plan = _plan(_routing_result(), _runtime_native_result(), codex_preflight=_codex_preflight())

        output = run_multi_review("review", models=specs, routing_plan=plan, resume_id="uuid-123")

        assert output.failed == 2
        assert all("--context blind" in (result.error or "") for result in output.results)
        mock_codex_parallel.assert_not_called()
        mock_claude_parallel.assert_not_called()
        mock_grouped.assert_not_called()

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_single_model_success(self, mock_popen_cls):
        mock_popen_cls.return_value = _mock_popen("great review")
        plan = _plan(_routing_result())
        output = run_multi_review("review this", models=[_spec()], routing_plan=plan)
        assert output.successful == 1
        assert output.results[0].success
        assert output.results[0].stdout == "great review"

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_multiple_models_parallel(self, mock_popen_cls):
        mock_popen_cls.return_value = _mock_popen("output")
        specs = [_spec(f"model-{i}") for i in range(3)]
        plan = _plan(*[_routing_result() for _ in range(3)])
        output = run_multi_review("review", models=specs, routing_plan=plan)
        assert output.successful == 3
        assert len(output.results) == 3

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_results_in_deterministic_order(self, mock_popen_cls):
        mock_popen_cls.return_value = _mock_popen("output")
        specs = [_spec("alpha"), _spec("beta"), _spec("gamma")]
        plan = _plan(*[_routing_result() for _ in range(3)])
        output = run_multi_review("review", models=specs, routing_plan=plan)
        names = [r.model_name for r in output.results]
        assert names == ["alpha", "beta", "gamma"]

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_duplicate_model_specs_return_one_result_per_input_in_order(self, mock_popen_cls):
        mock_popen_cls.side_effect = [_mock_popen("first"), _mock_popen("second")]
        specs = [_spec("same-model"), _spec("same-model")]
        plan = _plan(*[_routing_result() for _ in range(2)])
        output = run_multi_review("review", models=specs, routing_plan=plan)
        assert len(output.results) == 2
        assert [r.model_name for r in output.results] == ["same-model", "same-model"]
        assert {r.stdout for r in output.results} == {"first", "second"}

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_model_failure_captured(self, mock_popen_cls):
        mock_popen_cls.return_value = _mock_popen(stdout="", returncode=1, stderr="error msg")
        plan = _plan(_routing_result())
        output = run_multi_review("review", models=[_spec()], routing_plan=plan)
        assert output.failed == 1
        assert output.results[0].error == "error msg"

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_direct_model_no_base_url(self, mock_popen_cls):
        """Direct route means no ANTHROPIC_BASE_URL in env."""
        mock_popen_cls.return_value = _mock_popen("direct output")
        direct_route = _route(provider="direct", model_ref="claude-opus-4-6")
        direct_result = _routing_result(route=direct_route, base_url=None, source="direct")
        plan = _plan(direct_result)
        output = run_multi_review(
            "review",
            models=[_spec(preferred_proxy=None, provider_refs=(("direct", "claude-opus-4-6"),))],
            routing_plan=plan,
        )
        assert output.successful == 1
        call_kwargs = mock_popen_cls.call_args.kwargs
        assert "ANTHROPIC_BASE_URL" not in call_kwargs["env"]

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_forge_depth_set_in_env(self, mock_popen_cls):
        mock_popen_cls.return_value = _mock_popen("output")
        plan = _plan(_routing_result())
        with patch.dict("os.environ", {"FORGE_DEPTH": "0"}):
            run_multi_review("review", models=[_spec()], routing_plan=plan)
        call_kwargs = mock_popen_cls.call_args.kwargs
        assert call_kwargs["env"]["FORGE_DEPTH"] == "1"

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_worker_surfaces_run_id(self, mock_popen_cls):
        """Each ReviewResult carries the worker's run identity (parent = the verb)."""
        mock_popen_cls.return_value = _mock_popen("output")
        plan = _plan(_routing_result())
        with patch.dict(
            "os.environ",
            {"FORGE_RUN_ID": "run_verb", "FORGE_ROOT_RUN_ID": "run_root"},
            clear=True,
        ):
            output = run_multi_review("review", models=[_spec()], routing_plan=plan)
        result = output.results[0]
        assert result.parent_run_id == "run_verb"
        assert result.root_run_id == "run_root"
        assert result.run_id and result.run_id not in ("run_verb", "run_root")

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_per_worker_event_records_routed_model_provider_proxy(self, mock_popen_cls):
        """The per-worker usage event records the actual routed model/provider/proxy
        (route.model_ref / route.provider / routing_result.proxy_id), not the friendly
        spec id with null provider/proxy."""
        from forge.core.invoker import Attribution
        from forge.core.usage.ledger import read_usage_events

        mock_popen_cls.return_value = _mock_popen("output")
        route = _route(provider="openrouter", model_ref="openai/gpt-5.5")
        plan = _plan(_routing_result(route=route))  # proxy_id="test-proxy"
        # NOTE: no clear=True -- that would wipe FORGE_HOME (the isolate_forge_home tmp dir),
        # sending the ledger write to the real ~/.forge while the read sees the tmp dir.
        with patch.dict("os.environ", {"FORGE_RUN_ID": "run_v", "FORGE_ROOT_RUN_ID": "run_v"}):
            run_multi_review("review", models=[_spec()], routing_plan=plan, attribution=Attribution(command="panel"))
        events = read_usage_events()
        assert len(events) == 1
        e = events[0]
        assert (e.command, e.attribution_granularity, e.parent_run_id) == ("panel", "worker", "run_v")
        assert (e.model, e.provider, e.proxy_id) == ("openai/gpt-5.5", "openrouter", "test-proxy")

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_bare_flag_when_api_key_present(self, mock_popen_cls):
        mock_popen_cls.return_value = _mock_popen("output")
        plan = _plan(_routing_result())
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            run_multi_review("review", models=[_spec()], routing_plan=plan)
        cmd = mock_popen_cls.call_args[0][0]
        assert "--bare" in cmd

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_bare_flag_skipped_without_api_key(self, mock_popen_cls):
        mock_popen_cls.return_value = _mock_popen("output")
        plan = _plan(_routing_result())
        run_multi_review("review", models=[_spec()], routing_plan=plan)
        cmd = mock_popen_cls.call_args[0][0]
        assert "--bare" not in cmd

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_resume_id_in_command(self, mock_popen_cls):
        mock_popen_cls.return_value = _mock_popen("output")
        plan = _plan(_routing_result())
        run_multi_review("review", models=[_spec()], routing_plan=plan, resume_id="uuid-123")
        cmd = mock_popen_cls.call_args[0][0]
        assert "--resume" in cmd
        assert "uuid-123" in cmd

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_model_flag_for_proxied_worker(self, mock_popen_cls):
        """Proxied workers get --model from route.model_ref."""
        mock_popen_cls.return_value = _mock_popen("output")
        route = _route(model_ref="openai/gpt-5.5")
        plan = _plan(_routing_result(route=route))
        run_multi_review("review", models=[_spec()], routing_plan=plan)
        cmd = mock_popen_cls.call_args[0][0]
        assert "--model" in cmd
        assert "openai/gpt-5.5" in cmd

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_direct_worker_uses_env_pin_not_model_flag(self, mock_popen_cls, monkeypatch):
        mock_popen_cls.return_value = _mock_popen("output")
        monkeypatch.setenv("FORGE_SUBPROCESS_PROXY", "openrouter")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://inherited:8080")

        direct_route = _route(provider="direct", model_ref="claude-opus-4-8")
        direct_result = _routing_result(route=direct_route, base_url=None, source="direct")
        plan = _plan(direct_result)

        run_multi_review(
            "review",
            models=[
                _spec(
                    name="claude-opus-4.8",
                    family="anthropic",
                    preferred_proxy=None,
                    provider_refs=(("direct", "claude-opus-4-8"),),
                )
            ],
            routing_plan=plan,
        )

        cmd = mock_popen_cls.call_args[0][0]
        env = mock_popen_cls.call_args.kwargs["env"]
        assert "--model" not in cmd
        assert env["ANTHROPIC_MODEL"] == "opus"
        assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-opus-4-8"
        assert "ANTHROPIC_BASE_URL" not in env
        assert "FORGE_SUBPROCESS_PROXY" not in env

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_cwd_passed_through(self, mock_popen_cls):
        mock_popen_cls.return_value = _mock_popen("output")
        plan = _plan(_routing_result())
        run_multi_review("review", models=[_spec()], routing_plan=plan, cwd="/my/project")
        call_kwargs = mock_popen_cls.call_args.kwargs
        assert call_kwargs["cwd"] == "/my/project"

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_start_new_session_for_cleanup(self, mock_popen_cls):
        mock_popen_cls.return_value = _mock_popen("output")
        plan = _plan(_routing_result())
        run_multi_review("review", models=[_spec()], routing_plan=plan)
        call_kwargs = mock_popen_cls.call_args.kwargs
        assert call_kwargs["start_new_session"] is True

    def test_empty_models_returns_empty(self):
        output = run_multi_review("review", models=[])
        assert output.successful == 0
        assert output.results == []

    def test_skips_at_max_forge_depth(self):
        with patch.dict("os.environ", {"FORGE_DEPTH": "2"}):
            output = run_multi_review("review", models=[_spec()])
        assert output.results == []
        assert output.successful == 0

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_runs_below_max_forge_depth(self, mock_popen_cls):
        mock_popen_cls.return_value = _mock_popen("output")
        plan = _plan(_routing_result())
        with patch.dict("os.environ", {"FORGE_DEPTH": "1"}):
            output = run_multi_review("review", models=[_spec()], routing_plan=plan)
        assert output.successful == 1
        mock_popen_cls.assert_called_once()

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_per_worker_prompt_override(self, mock_popen_cls):
        mock_popen_cls.return_value = _mock_popen("output")
        plan = _plan(_routing_result())
        run_multi_review("global prompt", models=[_spec(prompt="worker-specific")], routing_plan=plan)
        communicate_kwargs = mock_popen_cls.return_value.communicate.call_args[1]
        assert communicate_kwargs["input"] == "worker-specific"

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_none_prompt_falls_back_to_global(self, mock_popen_cls):
        mock_popen_cls.return_value = _mock_popen("output")
        plan = _plan(_routing_result())
        run_multi_review("global prompt", models=[_spec(prompt=None)], routing_plan=plan)
        communicate_kwargs = mock_popen_cls.return_value.communicate.call_args[1]
        assert communicate_kwargs["input"] == "global prompt"

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_prompt_prefix_mode_prepends_hint_to_global_prompt(self, mock_popen_cls):
        mock_popen_cls.return_value = _mock_popen("output")
        plan = _plan(_routing_result())
        run_multi_review(
            "global prompt",
            models=[_spec(prompt="worker hint", prompt_mode="prefix")],
            routing_plan=plan,
        )
        communicate_kwargs = mock_popen_cls.return_value.communicate.call_args[1]
        assert communicate_kwargs["input"] == "worker hint\n\nglobal prompt"

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_mixed_prompts(self, mock_popen_cls):
        mock_popen_cls.return_value = _mock_popen("output")
        specs = [_spec("custom", prompt="my custom"), _spec("default", prompt=None)]
        plan = _plan(*[_routing_result() for _ in range(2)])
        run_multi_review("global prompt", models=specs, routing_plan=plan)
        inputs = {call[1]["input"] for call in mock_popen_cls.return_value.communicate.call_args_list}
        assert inputs == {"my custom", "global prompt"}


def _avail(spec: ModelSpec, status: str = "ready", reason: str = "") -> ModelAvailability:
    return ModelAvailability(spec=spec, status=status, reason=reason)


class TestPreflightCheck:
    """Tests for preflight_check() with routing plan."""

    def test_missing_claude_cli_returns_worker_runtime_error(self, monkeypatch: pytest.MonkeyPatch):
        specs = [_spec("a"), _spec("b")]
        plan = _plan(*[_routing_result() for _ in range(2)])
        monkeypatch.setattr("forge.review.engine.shutil.which", lambda name: None)

        errors = preflight_check(specs, routing_plan=plan)

        assert len(errors) == 1
        assert "claude CLI not found in PATH" in errors[0]
        assert "proxy-routed models" in errors[0]

    def test_all_routed_returns_empty(self):
        specs = [_spec("a"), _spec("b")]
        plan = _plan(*[_routing_result() for _ in range(2)])
        assert preflight_check(specs, routing_plan=plan) == []

    def test_codex_only_does_not_require_claude_binary(self, monkeypatch):
        monkeypatch.setattr("forge.review.engine.shutil.which", lambda name: None)
        plan = _plan(_runtime_native_result(), codex_preflight=_codex_preflight())

        assert preflight_check([_codex_spec()], routing_plan=plan) == []

    def test_codex_cache_miss_fails_closed_with_refresh_command(self):
        errors = preflight_check([_codex_spec()], routing_plan=_plan(_runtime_native_result()))

        assert len(errors) == 1
        assert "forge runtime preflight codex" in errors[0]

    def test_codex_unready_snapshot_fails_closed_with_reason(self):
        plan = _plan(
            _runtime_native_result(),
            codex_preflight=_codex_preflight(ready=False, blocking_reason="Codex login required"),
        )

        errors = preflight_check([_codex_spec()], routing_plan=plan)

        assert len(errors) == 1
        assert "Codex login required" in errors[0]
        assert "forge runtime preflight codex" in errors[0]

    def test_resume_context_with_codex_names_blind_fix(self):
        plan = _plan(_runtime_native_result(), codex_preflight=_codex_preflight())

        errors = preflight_check([_codex_spec()], routing_plan=plan, resume_id="uuid-123")

        assert len(errors) == 1
        assert "--context blind" in errors[0]

    def test_unresolved_route_returns_error(self):
        spec = _spec("a")
        unresolved = RoutingResult(
            base_url=None,
            proxy_id=None,
            template=None,
            source="unresolved",
            route=None,
            credential=None,
            warning="No compatible proxy found",
        )
        plan = _plan(unresolved)
        errors = preflight_check([spec], routing_plan=plan)
        assert len(errors) == 1
        assert "a" in errors[0]

    def test_direct_route_requires_anthropic_api_key(self):
        spec = _spec(
            name="claude-opus",
            family="anthropic",
            preferred_proxy=None,
            provider_refs=(("direct", "claude-opus-4-6"),),
        )
        direct_route = _route(
            provider="direct",
            credential="anthropic-api",
            family="anthropic",
            model_ref="claude-opus-4-6",
        )
        direct_result = _routing_result(route=direct_route, base_url=None, source="direct")
        plan = _plan(direct_result)

        with patch("forge.review.engine.resolve_env_or_credential", return_value=None):
            errors = preflight_check([spec], routing_plan=plan)

        assert len(errors) == 1
        assert "ANTHROPIC_API_KEY" in errors[0]
        assert "Workflow model 'claude-opus'" in errors[0]

    def test_direct_route_allows_resolved_anthropic_api_key(self):
        spec = _spec(
            name="claude-opus",
            family="anthropic",
            preferred_proxy=None,
            provider_refs=(("direct", "claude-opus-4-6"),),
        )
        direct_route = _route(
            provider="direct",
            credential="anthropic-api",
            family="anthropic",
            model_ref="claude-opus-4-6",
        )
        direct_result = _routing_result(route=direct_route, base_url=None, source="direct")
        plan = _plan(direct_result)

        with patch("forge.review.engine.resolve_env_or_credential", return_value="sk-test"):
            errors = preflight_check([spec], routing_plan=plan)

        assert errors == []

    @patch("forge.review.models.check_model_availability")
    def test_fallback_without_plan(self, mock_avail):
        spec = _spec("a")
        mock_avail.return_value = [_avail(spec)]
        assert preflight_check([spec]) == []


class TestReviewResultMapping:
    @pytest.mark.parametrize(
        ("runtime", "argv", "stdout", "stderr", "returncode", "expected_error"),
        [
            ("claude_code", ["claude", "-p"], "runtime failure", "", 0, "runtime failure"),
            (
                "codex",
                ["codex", "exec", "--json", "--sandbox", "read-only"],
                "",
                "provider rejected request",
                0,
                "provider rejected request",
            ),
            ("codex", ["codex", "exec", "--json"], "", "", 0, "Runtime reported error"),
            ("claude_code", ["claude", "-p"], "provider failure", "", 7, "provider failure"),
            ("codex", ["codex", "exec", "--json"], "", "", 9, "Exit code 9"),
        ],
    )
    def test_runtime_error_fails_with_preserved_streams(
        self,
        runtime,
        argv,
        stdout,
        stderr,
        returncode,
        expected_error,
    ):
        request = HeadlessRequest(
            argv=argv,
            prompt="review",
            env={},
            label="worker",
            attribution=Attribution(command="panel", runtime=runtime),
        )
        outcome = HeadlessResult(
            label="worker",
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            duration_seconds=1.0,
            runtime_is_error=True,
        )

        result = _to_review_result(request, outcome)

        assert result.success is False
        assert result.stdout == stdout
        assert result.stderr == stderr
        assert result.error == expected_error


class TestCredentialInjection:
    """Tests for ANTHROPIC_API_KEY injection from credential file into workflow env."""

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_credential_file_key_injected_into_env(self, mock_popen_cls, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mock_popen_cls.return_value = _mock_popen("output")

        plan = _plan(_routing_result())
        with patch(
            "forge.review.engine.resolve_env_or_credential",
            return_value="sk-from-file",
        ):
            run_multi_review("test", models=[_spec()], routing_plan=plan)

        call_kwargs = mock_popen_cls.call_args[1]
        assert call_kwargs["env"]["ANTHROPIC_API_KEY"] == "sk-from-file"

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_bare_flag_uses_built_env(self, mock_popen_cls, monkeypatch: pytest.MonkeyPatch) -> None:
        """--bare should be added when ANTHROPIC_API_KEY is in the built env."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mock_popen_cls.return_value = _mock_popen("output")

        plan = _plan(_routing_result())
        with patch(
            "forge.review.engine.resolve_env_or_credential",
            return_value="sk-from-file",
        ):
            run_multi_review("test", models=[_spec()], routing_plan=plan)

        cmd = mock_popen_cls.call_args[0][0]
        assert "--bare" in cmd


class TestReasoningEffort:
    """reasoning_effort threads into the worker argv as `--effort <level>` after `--model`."""

    def _prepare(self, reasoning_effort):
        prepared = _prepare_worker(
            _spec(),
            _routing_result(),
            prompt="review this",
            cwd=None,
            resume_id=None,
            timeout_seconds=600,
            attribution=None,
            reasoning_effort=reasoning_effort,
        )
        assert isinstance(prepared, HeadlessRequest)
        return prepared.argv

    def test_prepare_worker_appends_effort_flag(self):
        argv = self._prepare("high")
        assert "--effort" in argv
        idx = argv.index("--effort")
        assert argv[idx + 1] == "high"

    def test_prepare_worker_effort_after_model_flag(self):
        argv = self._prepare("high")
        assert "--model" in argv
        assert "--effort" in argv
        assert argv.index("--effort") > argv.index("--model")

    def test_prepare_worker_no_effort_omits_flag(self):
        argv = self._prepare(None)
        assert "--effort" not in argv

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_run_multi_review_forwards_effort_to_each_worker(self, mock_popen_cls):
        mock_popen_cls.return_value = _mock_popen("output")
        specs = [_spec(f"model-{i}") for i in range(3)]
        plan = _plan(*[_routing_result() for _ in range(3)])
        run_multi_review("review", models=specs, routing_plan=plan, reasoning_effort="max")
        assert mock_popen_cls.call_count == 3
        for call in mock_popen_cls.call_args_list:
            cmd = call[0][0]
            assert "--effort" in cmd
            assert cmd[cmd.index("--effort") + 1] == "max"
            assert cmd.index("--effort") > cmd.index("--model")

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_run_multi_review_without_effort_omits_flag(self, mock_popen_cls):
        mock_popen_cls.return_value = _mock_popen("output")
        plan = _plan(_routing_result())
        run_multi_review("review", models=[_spec()], routing_plan=plan)
        cmd = mock_popen_cls.call_args[0][0]
        assert "--effort" not in cmd


class TestCodexWorkerShaping:
    def test_prepare_codex_worker_uses_read_only_sanitized_runtime_request(self, monkeypatch):
        for name, value in {
            "ANTHROPIC_API_KEY": "anthropic-secret",
            "ANTHROPIC_BASE_URL": "http://proxy:8084",
            "FORGE_SUBPROCESS_PROXY": "proxy-id",
            "CODEX_API_KEY": "stale-codex-key",
            "CODEX_ACCESS_TOKEN": "stale-codex-token",
        }.items():
            monkeypatch.setenv(name, value)
        attribution = Attribution(command="panel", workflow="review", session="s1")

        prepared = _prepare_worker(
            _codex_spec(),
            _runtime_native_result(),
            prompt="review this",
            cwd="/worktree",
            resume_id=None,
            timeout_seconds=321,
            attribution=attribution,
            reasoning_effort="high",
            codex_preflight=_codex_preflight(),
        )

        assert isinstance(prepared, HeadlessRequest)
        assert prepared.argv == ["codex", "exec", "--json", "--sandbox", "read-only"]
        assert prepared.prompt == "review this"
        assert prepared.cwd == "/worktree"
        assert prepared.timeout_seconds == 321
        assert prepared.label == "codex"
        assert prepared.model is None
        assert prepared.provider == "openai"
        assert prepared.base_url is None
        assert prepared.proxy_id is None
        assert prepared.output_format is None
        assert prepared.attribution is not None
        assert prepared.attribution.runtime == "codex"
        assert prepared.attribution.billing_mode == "subscription_quota"
        assert prepared.attribution.operation == "workflow.worker"
        for stripped in (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_BASE_URL",
            "FORGE_SUBPROCESS_PROXY",
            "CODEX_API_KEY",
            "CODEX_ACCESS_TOKEN",
        ):
            assert stripped not in prepared.env

    def test_prepare_codex_worker_preserves_optional_no_attribution(self):
        prepared = _prepare_worker(
            _codex_spec(),
            _runtime_native_result(),
            prompt="review this",
            cwd=None,
            resume_id=None,
            timeout_seconds=600,
            attribution=None,
            codex_preflight=_codex_preflight(),
        )

        assert isinstance(prepared, HeadlessRequest)
        assert prepared.attribution is None
