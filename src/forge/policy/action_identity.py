"""Canonical action identity for LLM-backed policy caches.

Hook adapters compute the fingerprint before truncating prompt-facing fields.
Consumers may recompute it from an ``ActionContext`` as a compatibility fallback
for contexts created by older state or direct unit callers.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from forge.policy.types import ActionContext

ACTION_IDENTITY_SCHEMA = "forge-policy-action-v1"


def compute_action_fingerprint(
    *,
    tool_name: str,
    target_path: str | None,
    tool_args: Mapping[str, Any] | None = None,
    new_content: str | None = None,
    raw_diff: str | None = None,
) -> str:
    """Hash one canonical, unambiguous representation of an action."""
    args = tool_args or {}
    payload: dict[str, Any] = {
        "schema": ACTION_IDENTITY_SCHEMA,
        "tool_name": tool_name,
        "target_path": target_path,
    }

    if isinstance(raw_diff, str):
        payload["content"] = {"kind": "raw_diff", "raw_diff": raw_diff}
    elif tool_name == "Edit" and ("old_string" in args or "new_string" in args):
        old_string = args.get("old_string")
        new_string = args.get("new_string")
        payload["content"] = {
            "kind": "edit_fragments",
            "old_string": old_string if isinstance(old_string, str) else None,
            "new_string": new_string if isinstance(new_string, str) else new_content,
            "replace_all": args.get("replace_all") is True,
        }
    else:
        content = args.get("content")
        payload["content"] = {
            "kind": "write_content" if tool_name == "Write" else "new_content",
            # ``new_content`` is the adapter's explicit pre-truncation value. Some
            # on-demand callers deliberately keep only a short display excerpt in
            # tool_args, so that mapping is a compatibility fallback, not authority.
            "content": new_content if isinstance(new_content, str) else content if isinstance(content, str) else None,
        }

    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def action_fingerprint(context: ActionContext) -> str:
    """Return a validated precomputed fingerprint or a compatibility fallback."""
    if _is_sha256(context.action_fingerprint):
        assert context.action_fingerprint is not None
        return context.action_fingerprint
    return compute_action_fingerprint(
        tool_name=context.tool_name,
        target_path=context.target_path,
        tool_args=context.tool_args,
        new_content=context.new_content,
        raw_diff=context.raw_diff,
    )


def _is_sha256(value: str | None) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)
