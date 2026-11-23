"""Backport GPT-6.2 pricing metadata and Responses cache retention to the pinned LiteLLM 1.102.2 gateway."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import cast

import litellm
from litellm import cost_calculator
from litellm.litellm_core_utils.llm_cost_calc import utils as token_pricing
from litellm.proxy.proxy_cli import run_server
from litellm.types.utils import ModelInfo, Usage

_NATIVE_USAGE = cost_calculator._get_usage_object
_NATIVE_RATES = token_pricing._get_token_base_cost
_WRITE = "cache_creation_input_token_cost"
_WRITE_12H = f"{_WRITE}_above_12hr"
_GPT_62 = {"gpt-6.2-astra", "gpt-6.2-sol", "openai/gpt-6.2-astra", "openai/gpt-6.2-sol"}
_LONG_ULTRAFAST = {
    f"{field}_above_272k_tokens_ultrafast"
    for field in ("input_cost_per_token", "output_cost_per_token", "cache_read_input_token_cost", _WRITE)
}


def _field(obj: object, name: str) -> object:
    return obj.get(name) if isinstance(obj, Mapping) else getattr(obj, name, None)


def _usage_with_write_retention(completion_response: object) -> Usage | None:
    usage = _NATIVE_USAGE(completion_response)
    if (
        usage is None
        or usage.prompt_tokens_details is None
        or not getattr(usage.prompt_tokens_details, "cache_write_tokens", None)
    ):
        return usage

    raw_details = _field(_field(completion_response, "usage"), "input_tokens_details")
    lifetimes = _field(raw_details, "cache_write_tokens_details")
    long_writes = _field(lifetimes, "ttl_12h_tokens")
    if not isinstance(long_writes, int) or long_writes <= 0:
        return usage
    # Retain the server's split on a billing-only copy, without altering the provider receipt.
    details = usage.prompt_tokens_details.model_copy(update={"cache_write_tokens_details": lifetimes})
    return usage.model_copy(update={"prompt_tokens_details": details})


def _rates_with_write_retention(
    model_info: ModelInfo,
    usage: Usage,
    service_tier: str | None = None,
    current_time: datetime | None = None,
    *,
    threshold_is_inclusive: bool = False,
    missing_cache_read_uses_input: bool = False,
) -> tuple[float, float, float, float, float]:
    def rates(info: ModelInfo) -> tuple[float, float, float, float, float]:
        return _NATIVE_RATES(
            info,
            usage,
            service_tier,
            current_time,
            threshold_is_inclusive=threshold_is_inclusive,
            missing_cache_read_uses_input=missing_cache_read_uses_input,
        )

    # LiteLLM's lookup keeps the selected registry key, including the unique ID of a custom-priced deployment.
    # Read that row so two deployments of the same model can charge different amounts.
    key = model_info.get("key", "")
    row = litellm.model_cost.get(key, {})
    if key not in _GPT_62 and row.get("base_model") not in _GPT_62:
        return rates(model_info)
    if model_info.get("litellm_provider") not in {None, "openai"}:
        return rates(model_info)

    pricing = dict(model_info)
    pricing.update({k: v for k, v in row.items() if k in _LONG_ULTRAFAST})
    ordinary = rates(cast(ModelInfo, pricing))
    if _WRITE_12H not in row:
        return ordinary
    details = usage.prompt_tokens_details
    total_writes = getattr(details, "cache_write_tokens", None)
    long_writes = _field(_field(details, "cache_write_tokens_details"), "ttl_12h_tokens")
    if not total_writes or not isinstance(long_writes, int) or long_writes <= 0:
        return ordinary

    # Resolve the longer retention with the gateway's own tier and context rules. Its cost calculator accepts
    # one write rate for this usage record, so weight the two rates by the counts the provider actually returned.
    long_info = pricing.copy()
    for key, price in row.items():
        if key.startswith(_WRITE_12H):
            long_info[_WRITE + key[len(_WRITE_12H) :]] = price
    input_rate, output_rate, write_rate, hour_rate, read_rate = ordinary
    long_rate = rates(cast(ModelInfo, long_info))[2]
    write_rate += (long_rate - write_rate) * min(long_writes, total_writes) / total_writes
    return input_rate, output_rate, write_rate, hour_rate, read_rate


def install_pricing_backport() -> None:
    """Install before the gateway registers deployments or calculates any costs."""
    cost_calculator._get_usage_object = _usage_with_write_retention
    token_pricing._get_token_base_cost = _rates_with_write_retention


# Uvicorn's spawned workers re-execute the launcher as __mp_main__.
if __name__ in {"__main__", "__mp_main__"}:
    install_pricing_backport()

if __name__ == "__main__":
    run_server()
