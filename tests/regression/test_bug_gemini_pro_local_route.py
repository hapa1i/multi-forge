"""Gemini Pro requests must reach a serving local template with only a Google AI key."""

from pathlib import Path

import pytest

from forge import runtime_config
from forge.backend.sources import list_model_sources
from forge.core.ops.session_model_routing import plan_session_model_route

pytestmark = pytest.mark.regression


@pytest.fixture
def gemini_credentials_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Keep the real credential resolver, but exclude ambient keys, files, and .env loading.
    for source in list_model_sources():
        for name in source.required_env_vars:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "test-google-ai-key")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runtime_config, "_config", None)


@pytest.mark.parametrize("model", ["gemini-4-argon", "gemini-3.1-pro-preview", "gemini-2.5-pro"])
@pytest.mark.parametrize("tier", [None, "opus"])
def test_pro_model_selects_serving_local_template(model: str, tier: str | None, gemini_credentials_only: None) -> None:
    plan = plan_session_model_route(model, model_tier=tier)

    assert plan.kind == "proxy"
    assert plan.source_id == "litellm-gemini-local"
    assert plan.proxy is not None
    assert plan.proxy.template == "litellm-gemini-local"
    assert plan.proxy.ensure_reference == "litellm-gemini-local"
    assert plan.selected_model == f"gemini/{model}"
    assert plan.selected_tier == (tier or "sonnet")


def test_flash_model_retains_flash_local_priority(gemini_credentials_only: None) -> None:
    plan = plan_session_model_route("gemini-3.8-flash")

    assert plan.proxy is not None
    assert plan.proxy.template == "litellm-gemini-flash-local"
    assert plan.selected_model == "gemini/gemini-3.8-flash"
