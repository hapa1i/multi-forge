"""Pin the need for bundled Astra pricing and isolate LiteLLM's global cost caches."""

import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from forge.backend.creation import create_backend_config


def test_astra_pricing_override_is_needed_by_packaged_litellm() -> None:
    distribution = importlib.metadata.distribution("litellm")
    path = Path(str(distribution.locate_file("litellm/model_prices_and_context_window_backup.json")))
    cost_map = json.loads(path.read_text())

    assert not {"gpt-6-astra", "openai/gpt-6-astra"}.intersection(cost_map), (
        "LiteLLM now packages Astra metadata; remove the bundled model_info pricing override "
        "after verifying native costs, and update this boundary test."
    )


def test_astra_pricing_without_remote_model_metadata() -> None:
    config = yaml.safe_load(create_backend_config(adapter_type="litellm").read_text())
    entry = next(model for model in config["model_list"] if model["model_name"] == "openai/gpt-6-astra")
    entry["litellm_params"]["api_key"] = "test-key"
    cases = [
        (100, 0, 0.001, 0.0005),
        (100, 80, 0.00028, 0.0005),
        (272_000, 1_000, 2.711, 0.0005),
        (272_001, 1_000, 5.42202, 0.00075),
    ]
    # Router registration also populates process-global caches outside model_cost.
    # Run the offline calculation in a child so none of that state reaches other tests.
    script = dedent("""\
        import json
        import sys
        import litellm

        data = json.load(sys.stdin)
        litellm.model_cost = {}
        router = litellm.Router(model_list=[data["entry"]])
        deployment_id = router.model_list[0]["model_info"]["id"]
        costs = [
            litellm.cost_per_token(
                model=deployment_id,
                custom_llm_provider="openai",
                prompt_tokens=prompt_tokens,
                completion_tokens=10,
                cache_read_input_tokens=cached_tokens,
            )
            for prompt_tokens, cached_tokens, *_ in data["cases"]
        ]
        print(json.dumps(costs))
        """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps({"entry": entry, "cases": cases}),
        env={**os.environ, "LITELLM_LOCAL_MODEL_COST_MAP": "true"},
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    for actual, (_, _, expected_input, expected_output) in zip(json.loads(result.stdout), cases, strict=True):
        assert actual == pytest.approx((expected_input, expected_output))
