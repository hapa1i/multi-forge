"""Cheap LLM classification via core.llm.SyncAdapter.

Classifies actions into tags using a cheap model for routing
decisions in WorkflowPolicy branches.
"""

from __future__ import annotations

import json
import logging

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
        from forge.core.usage import emit_direct_llm_usage, mint_request_id, with_forge_request_id

        prompt = prompt_template.format(
            tool_name=context.tool_name,
            target_path=context.target_path or "N/A",
            content=(context.raw_diff or context.new_content or "")[:2000],
        )

        client = get_client(model)
        adapter = SyncAdapter(client)
        # Forward X-Request-ID so a Forge proxy in the path (if this model is routed
        # through one) can correlate this call's cost record. With a None-default
        # client, merge_hyperparams returns this hp verbatim, so every other param
        # stays at its default -- behavior is preserved, only the header is added.
        hp = with_forge_request_id(None, mint_request_id())
        response = adapter.complete([Message(role="user", content=prompt)], hyperparams=hp)

        # Best-effort usage attribution: provider-reported tokens, ambient run.
        # cost_request_id stays null -- the tagger can't prove a Forge-proxy target,
        # and a dangling back-reference would be worse than none.
        emit_direct_llm_usage(
            command="tagger",
            model=model,
            provider=model.split("/", 1)[0] if "/" in model else None,
            usage=response.usage,
        )

        return _parse_tags(response.text)

    except Exception as e:
        _log.warning("tag_action failed (model=%s): %s", model, e)
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
