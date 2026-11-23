"""GPT-6.2 pricing must preserve provider receipts, deployment overrides and unrelated request costs."""

import pytest

from tests.src.backend.test_litellm_model_metadata import _backend_entry, _run_offline

pytestmark = pytest.mark.regression


def test_gateway_keeps_upstream_costs_and_bills_only_reported_long_writes() -> None:
    result = _run_offline(
        """
        import json
        import sys
        from copy import deepcopy
        import litellm
        from forge.backend.litellm_pricing import install_pricing_backport
        from litellm.types.utils import ResponsesAPIResponse

        def response(model, details, tokens=20, tier="default"):
            return ResponsesAPIResponse(
                id="resp_fixture", model=model, created_at=0, object="response", output=[], service_tier=tier,
                usage={"input_tokens": tokens, "input_tokens_details": details, "output_tokens": 1,
                       "total_tokens": tokens + 1},
            )

        def cost(resp, deployment=None):
            return litellm.response_cost_calculator(
                response_object=resp, model=resp.model, custom_llm_provider="openai", call_type="responses",
                optional_params={}, router_model_id=deployment, custom_pricing=deployment is not None,
            )

        entry = json.load(sys.stdin)
        # Put the same long-context and 12h price fields on another OpenAI deployment.
        control = deepcopy(entry)
        control_model = "openai/gpt-4o"
        control["model_name"] = control["litellm_params"]["model"] = control["model_info"]["base_model"] = control_model
        control_id = litellm.Router(model_list=[control]).model_list[0]["model_info"]["id"]
        read_only = response(control_model, {"cached_tokens": 4})
        write_details = {"cache_write_tokens": 10, "cache_write_tokens_details": {"ttl_12h_tokens": 10}}
        long_write = response(control_model, write_details, tokens=272_001, tier="ultrafast")
        before = [cost(read_only, control_id), cost(long_write, control_id)]
        install_pricing_backport()
        after = [cost(read_only, control_id), cost(long_write, control_id)]
        entry["model_info"].update(
            input_cost_per_token=1e-6, output_cost_per_token=2e-6, cache_read_input_token_cost=0.5e-6,
            cache_creation_input_token_cost=3e-6, cache_creation_input_token_cost_above_12hr=8e-6,
        )
        deployment = litellm.Router(model_list=[entry]).model_list[0]["model_info"]["id"]
        totals = []
        for split in (None, {"ttl_30m_tokens": 2, "ttl_12h_tokens": 3}):
            details = {"cached_tokens": 4, "cache_write_tokens": 10}
            if split is not None:
                details["cache_write_tokens_details"] = split
            resp = response(entry["model_name"], details)
            totals.append(round(cost(resp, deployment) * 1_000_000))
        receipts = []
        for header, body in ((0.0, 0.25), (0.75, 0.0)):
            resp._hidden_params["additional_headers"] = {"llm_provider-x-litellm-response-cost": str(header)}
            resp.usage.cost = body
            receipts.append([cost(resp, deployment), resp.usage.cost])
        print(json.dumps({"before": before, "after": after, "totals": totals, "receipts": receipts}))
        """,
        _backend_entry("openai/gpt-6.2-sol"),
    )

    assert all(amount > 0 for amount in result["before"])
    assert result["after"] == result["before"]
    # Six ordinary input tokens, four reads, ten writes, one output. Only three writes report 12h.
    assert result["totals"] == [40, 55]
    assert result["receipts"] == [[0.0, 0.25], [0.75, 0.0]]
