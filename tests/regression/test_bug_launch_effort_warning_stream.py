"""A launch-effort clamp is a diagnostic, including when stdout is redirected."""

from __future__ import annotations

import pytest

from forge.cli.session_launch_args import warn_if_effort_clamped
from forge.core.models.model_routes import normalize_model_route_request
from forge.core.ops.session_model_routing import ResolvedModelRoute
from forge.core.runtime.launch_args import RuntimeLaunchArgs

pytestmark = pytest.mark.regression


def test_launch_effort_warning_uses_stderr(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("forge.core.reactive.env.resolve_proxy_wire_shape", lambda **_kwargs: "openai_translated")
    route = ResolvedModelRoute(
        request=normalize_model_route_request("gemini-3.7-flash"),
        kind="proxy",
        selected_tier="opus",
        proxy_template="openrouter-gemini-flash",
        proxy_base_url="http://127.0.0.1:65530",
        selected_model="google/gemini-3.7-flash",
    )

    warn_if_effort_clamped(RuntimeLaunchArgs(effort="max"), route)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--effort max will run as high" in " ".join(captured.err.split())
