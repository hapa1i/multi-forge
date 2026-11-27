"""Managed launch selection must verify the pinned listener before releasing native history."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import forge.core.runtime.codex_proxy_launch as launch
import forge.proxy.proxy_orchestrator as proxies
from forge.core.runtime.codex_preflight import CodexPreflight
from forge.session.models import ProxyIntent

BINDING = ProxyIntent("codex-responses-openrouter", "http://127.0.0.1:8230", "primary")
REQUESTED = "uncatalogued/example:latest"
MAPPED = "uncatalogued/fallback"


@pytest.fixture
def proxy(monkeypatch):
    pf = CodexPreflight(
        installed=True,
        version="0.141.0",
        version_ok=True,
        auth_method="proxy_token",
        auth_source="forge_proxy",
        billing_mode="unknown",
        ready=True,
        blocking_reason=None,
        hook_seam="unknown",
        proxy_responses="native_direct",
        doctor_status=None,
    )
    preflight = Mock(return_value=pf)
    resolve = Mock(return_value=(BINDING, False))
    listener = Mock(
        return_value=proxies.ResponsesListener(
            "different/default",
            {"required_zdr": True, "requested_default_model": "first/default", "zdr_fallbacks": {REQUESTED: MAPPED}},
            "openrouter",
            "openrouter",
        )
    )
    monkeypatch.setattr(launch, "preflight_codex", preflight)
    monkeypatch.setattr(proxies, "ensure_proxy", resolve)
    monkeypatch.setattr(proxies, "read_responses_listener", listener)
    return SimpleNamespace(pf=preflight, resolve=resolve, listener=listener)


def test_managed_creation_resolves_template_and_model_precedence(proxy):
    preflight, selected = launch.resolve_codex_proxy_launch(
        proxy_name=BINDING.template,
        extra_args=["-c", "model=ignored", "-m", REQUESTED],
    )
    proxy.pf.assert_called_once_with(loopback_auth=True)
    proxy.resolve.assert_called_once_with(BINDING.template)
    assert preflight.proxy_responses == "proxy_supported"
    assert (selected.requested_model, selected.dispatched_model) == (REQUESTED, MAPPED)
    assert selected.notices == (f"OpenRouter ZDR fallback: requested {REQUESTED}, dispatching {MAPPED}.",)


def test_resume_inspects_only_the_recorded_listener_and_replays_exact_slug(proxy):
    _, selected = launch.resolve_codex_proxy_launch(binding=BINDING, replay=(REQUESTED, MAPPED))
    proxy.resolve.assert_not_called()
    proxy.listener.assert_called_once_with(
        BINDING.base_url, expected_proxy_id="primary", expected_template=BINDING.template
    )
    assert (selected.requested_model, selected.dispatched_model) == (REQUESTED, MAPPED)


def test_resume_refuses_changed_mapping_even_with_same_explicit_slug(proxy):
    with pytest.raises(ValueError, match="previously dispatched"):
        launch.resolve_codex_proxy_launch(
            binding=BINDING, replay=(REQUESTED, "old/target"), extra_args=["-m", REQUESTED]
        )


def test_unknown_completed_selection_refuses_explicit_resume_before_network(proxy):
    with pytest.raises(ValueError, match="model to replay"):
        launch.resolve_codex_proxy_launch(binding=BINDING, extra_args=["-m", "new/target"])
    proxy.listener.assert_not_called()


def test_below_floor_rejects_before_starting_proxy(proxy):
    from dataclasses import replace

    proxy.pf.return_value = replace(proxy.pf.return_value, version="0.140.0")
    with pytest.raises(ValueError, match="0.141.0"):
        launch.resolve_codex_proxy_launch(proxy_name=BINDING.template)
    proxy.resolve.assert_not_called()


def test_corrupt_registered_origin_refuses_before_identity_request(proxy):
    proxy.resolve.return_value = (
        SimpleNamespace(proxy_id="primary", template=BINDING.template, base_url="http://example.org:1234"),
        False,
    )
    with pytest.raises(ValueError, match="loopback"):
        launch.resolve_codex_proxy_launch(proxy_name="primary")
    proxy.listener.assert_not_called()


@pytest.mark.parametrize(
    "args",
    [
        ["--model="],
        ["-m="],
        ["-m", "  "],
        ["-c", 'model=""'],
        ["--config=model=   "],
    ],
)
def test_blank_explicit_slug_refuses_before_listener_selection(proxy, args):
    for selection in ({"proxy_name": BINDING.template}, {"binding": BINDING, "replay": (REQUESTED, MAPPED)}):
        with pytest.raises(ValueError, match="nonempty model slug"):
            launch.resolve_codex_proxy_launch(extra_args=args, **selection)
    proxy.resolve.assert_not_called()
    proxy.listener.assert_not_called()
