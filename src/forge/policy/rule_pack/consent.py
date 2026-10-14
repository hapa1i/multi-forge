"""Session-bound acknowledgment of paid repository-action sharing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from forge.session.effective import apply_overrides
from forge.session.models import SessionState

BUNDLE_NAME = "jev_rule_pack"
ACKNOWLEDGMENT_KEY = "acknowledgment"
DISCLOSURE = (
    "Jev checks incur API charges and send supplied repository action content to OpenRouter and its selected "
    "TypeSafe provider, with zero data retention required on every request. Each derived session requires its own "
    "acknowledgment."
)
_RECOVERY = "use 'forge policy enable --help' for the validating activation command"


def build_acknowledgment(
    session: SessionState, settings: Mapping[str, Any], *, acknowledge_paid_data_sharing: bool
) -> dict[str, Any]:
    """Bind an explicit acknowledgment to one session instance and validated pack settings."""
    if acknowledge_paid_data_sharing is not True:
        raise ValueError(DISCLOSURE + " Explicit acknowledgment is required.")
    if not session.name or not session.created_at or not session.forge_root or not session.worktree:
        raise ValueError("Jev acknowledgment requires a session instance with project and worktree identity")
    if not Path(session.forge_root).is_absolute() or not Path(session.worktree.path).is_absolute():
        raise ValueError("Jev acknowledgment requires absolute project and worktree paths")
    if ACKNOWLEDGMENT_KEY in settings:
        raise ValueError("Supply pack settings without an existing acknowledgment")
    identity = {
        "name": session.name,
        "created_at": session.created_at,
        "forge_root": str(Path(session.forge_root).resolve()),
        "worktree": str(Path(session.worktree.path).resolve()),
    }
    return {
        "version": 1,
        "disclosure_version": 1,
        "session_digest": _digest(identity),
        "settings_digest": _digest(settings),
        "endpoint": "https://openrouter.ai/api/alpha/decisions",
        "data_scope": "supplied-repository-action",
        "zdr_required": True,
    }


def has_acknowledgment(session: SessionState, config: Mapping[str, Any]) -> bool:
    """Reject absent, stale or copied acknowledgments without credential or network access."""
    supplied = config.get(ACKNOWLEDGMENT_KEY)
    if not isinstance(supplied, dict):
        return False
    settings = {key: value for key, value in config.items() if key != ACKNOWLEDGMENT_KEY}
    try:
        expected = build_acknowledgment(session, settings, acknowledge_paid_data_sharing=True)
        # JSON equality keeps bool/int substitutions and unknown fields from passing a dict comparison.
        return _encoded(supplied) == _encoded(expected)
    except (OSError, RuntimeError, ValueError, TypeError, RecursionError):
        return False


def revoke_acknowledgment(session: SessionState) -> None:
    """Revoke intent and override grants so clearing an override cannot revive consent."""
    if session.intent.policy:
        _remove_grant(session.intent.policy.bundle_config)
    policy = session.overrides.get("policy")
    if isinstance(policy, dict):
        _remove_grant(policy.get("bundle_config"))


def strip_inherited_activation(session: SessionState) -> None:
    """Remove only Jev selection/configuration from a newly created child."""
    if session.intent.policy:
        session.intent.policy.bundles = [name for name in session.intent.policy.bundles if name != BUNDLE_NAME]
        session.intent.policy.bundle_config.pop(BUNDLE_NAME, None)
    policy = session.overrides.get("policy")
    if isinstance(policy, dict):
        bundles = policy.get("bundles")
        if isinstance(bundles, list):
            policy["bundles"] = [name for name in bundles if name != BUNDLE_NAME]
        config = policy.get("bundle_config")
        if isinstance(config, dict):
            config.pop(BUNDLE_NAME, None)


def reject_raw_activation(key: str, value: Any) -> None:
    """Reject a raw selection/config write; unrelated policy settings remain supported."""
    rejected = False
    if key == "policy" and isinstance(value, dict):
        for name, item in value.items():
            reject_raw_activation(f"policy.{name}", item)
    elif key == "policy.bundles":
        rejected = value == BUNDLE_NAME or isinstance(value, (list, tuple)) and BUNDLE_NAME in value
    elif key == "policy.bundle_config":
        rejected = isinstance(value, dict) and BUNDLE_NAME in value
    elif key == f"policy.bundle_config.{BUNDLE_NAME}" or key.startswith(f"policy.bundle_config.{BUNDLE_NAME}."):
        rejected = True
    if rejected:
        raise ValueError(f"Jev paid-data acknowledgment cannot be set through raw overrides; {_RECOVERY}")


def snapshot_activation(session: SessionState) -> dict[str, Any] | None:
    """Read only paid policy state so unrelated malformed overrides can still be repaired."""
    base = asdict(session.intent.policy) if session.intent.policy else {}
    override = session.overrides.get("policy", {})
    if override is None:
        return None
    policy = apply_overrides(base, override) if isinstance(override, dict) else base
    bundles = policy.get("bundles")
    if policy.get("enabled") is not True or not isinstance(bundles, list) or BUNDLE_NAME not in bundles:
        return None
    config = policy.get("bundle_config")
    return {"config": config.get(BUNDLE_NAME) if isinstance(config, dict) else None}


def check_raw_transition(before: dict[str, Any] | None, after: dict[str, Any] | None) -> bool:
    """Refuse enabling/changing an effective paid configuration; return whether to revoke it."""
    if after is not None and before != after:
        raise ValueError(f"Raw overrides cannot activate or change paid Jev checks; {_RECOVERY}")
    return before is not None and after is None


def _remove_grant(config: Any) -> None:
    if isinstance(config, dict):
        value = config.get(BUNDLE_NAME)
        if isinstance(value, dict):
            value.pop(ACKNOWLEDGMENT_KEY, None)


def _encoded(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_encoded(value).encode()).hexdigest()
