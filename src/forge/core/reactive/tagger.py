"""Cheap LLM classification via core.llm.SyncAdapter.

Classifies actions into tags using a cheap model for routing
decisions in WorkflowPolicy branches.
"""

from __future__ import annotations

import json
import logging
import time

from forge.policy.types import ActionContext

_log = logging.getLogger(__name__)


def tag_action(
    context: ActionContext,
    *,
    model: str,
    prompt_template: str,
) -> list[str]:
    """Classify an action into tags via a cheap LLM call.

    Uses ``core.llm.SyncAdapter`` to make a single LLM call. The prompt
    template is formatted with action context fields. The response is
    parsed as either a JSON array or pipe/comma-separated string.

    Must NOT be called from inside an event loop (SyncAdapter constraint).

    Args:
        context: Action being classified.
        model: Prefixed model ID (e.g., "gemini/gemini-2.0-flash").
        prompt_template: Template with {tool_name}, {target_path}, {content}
                         placeholders.

    Returns:
        List of tag strings. Empty list on any error (fail-open).
    """
    try:
        from forge.core.llm import Message, SyncAdapter, get_client
        from forge.core.usage import (
            emit_direct_llm_usage,
            mint_request_id,
            resolve_client_base_url,
            target_is_forge_proxy,
            with_forge_request_id,
        )

        prompt = prompt_template.format(
            tool_name=context.tool_name,
            target_path=context.target_path or "N/A",
            content=(context.raw_diff or context.new_content or "")[:2000],
        )

        # No provider arg -> routes via local LiteLLM, which is not a provider-user-grouping-capable
        # source, so the provider `user`-field injection is structurally N/A here.
        client = get_client(model)
        adapter = SyncAdapter(client)

        # If this model's client will hit a Forge proxy, forward an X-Request-ID and
        # record it -- the proxy logs a cost record under that id, giving an exact
        # source_refs join. Otherwise send no header (preserving prior behavior on a
        # None-default client) and leave cost_request_id null: a back-reference to a
        # cost record that never materialized is worse than none.
        request_id = mint_request_id() if target_is_forge_proxy(resolve_client_base_url(model)) else None
        hp = with_forge_request_id(None, request_id) if request_id else None

        start = time.monotonic()
        response = adapter.complete([Message(role="user", content=prompt)], hyperparams=hp)
        latency_ms = (time.monotonic() - start) * 1000

        # Best-effort usage attribution: exact provider tokens, ambient run. billing
        # stays unknown -- the tagger routes via local LiteLLM with a dummy key, so it
        # can't prove direct API billing.
        emit_direct_llm_usage(
            command="tagger",
            model=model,
            provider=model.split("/", 1)[0] if "/" in model else None,
            usage=response.usage,
            cost_request_id=request_id,
            latency_ms=latency_ms,
        )

        tags = _parse_tags(response.text)
        from forge.core.telemetry.upstream import record_upstream_operation

        record_upstream_operation(
            command="tagger",
            operation="action.tag",
            status="success" if tags else "skipped",
            session=context.session_name,
            origin=context.origin,
            tool_name=context.tool_name,
            target_path=context.target_path,
            reason_code=None if tags else "no_tags",
            latency_ms=latency_ms,
        )
        return tags

    except Exception as e:
        _log.warning("tag_action failed (model=%s): %s", model, e)
        from forge.core.telemetry.upstream import record_upstream_operation

        record_upstream_operation(
            command="tagger",
            operation="action.tag",
            status="error",
            session=context.session_name,
            origin=context.origin,
            tool_name=context.tool_name,
            target_path=context.target_path,
            reason_code="exception",
            message=str(e),
        )
        return []


def _parse_tags(response: str) -> list[str]:
    """Parse tags from an LLM response.

    Tries JSON array first, then pipe-separated, then comma-separated.

    Args:
        response: Raw text from the LLM.

    Returns:
        List of stripped, non-empty tag strings.
    """
    if not response:
        return []

    text = response.strip()

    # Try JSON array
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [str(t).strip() for t in data if t is not None and str(t).strip()]
    except json.JSONDecodeError:
        pass

    # Try pipe-separated (e.g., "routine | trivial")
    if "|" in text:
        return [t.strip() for t in text.split("|") if t.strip()]

    # Try comma-separated (e.g., "routine, trivial")
    if "," in text:
        return [t.strip() for t in text.split(",") if t.strip()]

    # Single tag
    tag = text.strip()
    return [tag] if tag else []
