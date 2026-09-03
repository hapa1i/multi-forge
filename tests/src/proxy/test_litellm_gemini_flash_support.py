"""Pin the packaged LiteLLM support boundary for current Gemini Flash routes."""

from __future__ import annotations

import importlib.metadata
import json
import re
from pathlib import Path

import pytest

# First LiteLLM release whose packaged cost map contains the model.
FIRST_PACKAGED_SUPPORT = (1, 98, 0)

PACKAGED_MODELS = (
    "gemini/gemini-3.6-flash",
    "vertex_ai/gemini-3.6-flash",
    "gemini/gemini-3.7-flash",
    "vertex_ai/gemini-3.7-flash",
)
UNPACKAGED_MODELS = (
    "gemini/gemini-3.8-flash",
    "vertex_ai/gemini-3.8-flash",
)


def _installed_litellm_version() -> tuple[int, int, int]:
    parts = importlib.metadata.version("litellm").split(".")[:3]
    numeric = []
    for part in parts:
        match = re.match(r"\d+", part)
        numeric.append(int(match.group()) if match else 0)
    while len(numeric) < 3:
        numeric.append(0)
    return (numeric[0], numeric[1], numeric[2])


def _packaged_cost_map() -> dict[str, object]:
    distribution = importlib.metadata.distribution("litellm")
    path = Path(str(distribution.locate_file("litellm/model_prices_and_context_window_backup.json")))
    return json.loads(path.read_text(encoding="utf-8"))


def test_litellm_version_has_packaged_gemini_37_support() -> None:
    version = _installed_litellm_version()

    assert (
        version >= FIRST_PACKAGED_SUPPORT
    ), f"litellm {version} predates packaged Gemini 3.7 support; require at least {FIRST_PACKAGED_SUPPORT}"


@pytest.mark.parametrize("model_key", PACKAGED_MODELS)
def test_supported_gemini_flash_routes_exist_in_packaged_cost_map(model_key: str) -> None:
    assert model_key in _packaged_cost_map(), f"LiteLLM must package pricing and capability metadata for {model_key}"


@pytest.mark.parametrize("model_key", UNPACKAGED_MODELS)
def test_gemini_38_stays_openrouter_only_until_litellm_packages_it(model_key: str) -> None:
    assert (
        model_key not in _packaged_cost_map()
    ), f"LiteLLM now packages {model_key}; add and verify local/remote 3.8 routes, then update this boundary test"
