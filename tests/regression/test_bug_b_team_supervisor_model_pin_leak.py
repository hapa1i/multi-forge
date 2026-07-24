"""Regression B: executor model pins must not leak into proxied team checks."""

from __future__ import annotations

from contextlib import ExitStack
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest

from forge.policy.team.config import TeamSupervisorConfig
from forge.policy.team.handlers import _run_supervisor

pytestmark = pytest.mark.regression

_MODEL_PINS = {
    "ANTHROPIC_MODEL": "executor-model",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "executor-haiku",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "executor-sonnet",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "executor-opus",
}
_ROUTING_ENV_VARS = (
    "ANTHROPIC_BASE_URL",
    "FORGE_LAUNCH_MODE",
    "FORGE_SIDECAR",
    "FORGE_SUBPROCESS_BASE_URL",
    "FORGE_SUBPROCESS_PROXY",
    "FORGE_SUBPROCESS_PROXY_ID",
    "FORGE_SUBPROCESS_TEMPLATE",
)


@pytest.fixture(autouse=True)
def _isolated_routing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ROUTING_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    for name, value in _MODEL_PINS.items():
        monkeypatch.setenv(name, value)


def _captured_child_env(config: TeamSupervisorConfig) -> dict[str, str]:
    completed = CompletedProcess(
        args=["claude", "-p"],
        returncode=0,
        stdout='{"verdict": "aligned", "confidence": 0.9}',
        stderr="",
    )
    with (
        patch("forge.core.reactive.session_runner.prepare_json_argv", side_effect=lambda cmd, _fmt: (cmd, False)),
        patch("forge.core.reactive.session_runner.subprocess.run", return_value=completed) as run,
        patch("forge.core.reactive.cost_tracking.track_verb_cost"),
        patch("forge.core.usage.emit_usage_for_session_result"),
    ):
        assert _run_supervisor(config, "alice", "team", "idle", "") == (0, "")

    run.assert_called_once()
    return run.call_args.kwargs["env"]


@pytest.mark.parametrize(
    ("source", "expected_base_url"),
    [
        ("explicit_url", "http://explicit.test:8095"),
        ("named_proxy", "http://named.test:8095"),
        ("ambient_proxy", "http://ambient.test:8095"),
        ("inherited_url", "http://inherited.test:8095"),
        ("sidecar_injected_url", "http://host.docker.internal:8095"),
    ],
)
def test_every_resolved_proxy_source_scrubs_executor_model_pins(
    source: str,
    expected_base_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = TeamSupervisorConfig(enabled=True, resume_id="plan-session")

    with ExitStack() as stack:
        if source == "explicit_url":
            config.base_url = expected_base_url
        elif source in {"named_proxy", "ambient_proxy"}:
            proxy_id = "named-proxy" if source == "named_proxy" else "ambient-proxy"
            if source == "named_proxy":
                config.proxy = proxy_id
            else:
                monkeypatch.setenv("FORGE_SUBPROCESS_PROXY", proxy_id)
            entry = MagicMock(
                proxy_id=proxy_id,
                template="openrouter-anthropic",
                base_url=expected_base_url,
            )
            stack.enter_context(patch("forge.core.reactive.routing.lookup_proxy_entry_strict", return_value=entry))
            stack.enter_context(patch("forge.core.reactive.routing._check_proxy_reachable", return_value=True))
        elif source == "inherited_url":
            monkeypatch.setenv("ANTHROPIC_BASE_URL", expected_base_url)
            registry = MagicMock()
            registry.proxies = {}
            stack.enter_context(patch("forge.proxy.proxies.ProxyRegistryStore.read", return_value=registry))
            stack.enter_context(patch("forge.proxy.proxies.lookup_proxy_by_base_url", return_value=None))
            stack.enter_context(patch("forge.core.reactive.routing._probe_proxy_metadata", return_value=None))
        else:
            monkeypatch.setenv("FORGE_SIDECAR", "1")
            monkeypatch.setenv("FORGE_SUBPROCESS_BASE_URL", expected_base_url)
            monkeypatch.setenv("FORGE_SUBPROCESS_PROXY_ID", "sidecar-proxy")
            monkeypatch.setenv("FORGE_SUBPROCESS_TEMPLATE", "openrouter-anthropic")

        child_env = _captured_child_env(config)

    assert child_env["ANTHROPIC_BASE_URL"] == expected_base_url
    for name in _MODEL_PINS:
        assert name not in child_env


@pytest.mark.parametrize("mode", ["direct", "unresolved"])
def test_non_proxied_dispatch_preserves_executor_model_pins(mode: str) -> None:
    config = TeamSupervisorConfig(
        enabled=True,
        resume_id="plan-session",
        direct=mode == "direct",
    )

    child_env = _captured_child_env(config)

    for name, value in _MODEL_PINS.items():
        assert child_env[name] == value
