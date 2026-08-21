"""Bundle registry for deterministic policies.

Maps bundle names to policy classes. Bundles are collections of related
policies that can be enabled together.
"""

from __future__ import annotations

from typing import Any

from forge.policy.deterministic.coding_standards import (
    NoBackwardCompatPolicy,
    NoEmojiPolicy,
    NoTypeCheckingPolicy,
)
from forge.policy.deterministic.tdd import (
    NoSkipTestsPolicy,
    TDDEnforcementPolicy,
)
from forge.policy.protocols import Policy

# Bundle name -> list of policy classes
# Each class is instantiated fresh when get_bundle_policies() is called
BUNDLES: dict[str, list[type]] = {
    "tdd": [
        TDDEnforcementPolicy,
        NoSkipTestsPolicy,
    ],
    "coding_standards": [
        NoTypeCheckingPolicy,
        NoBackwardCompatPolicy,
        NoEmojiPolicy,
    ],
}

# Map policy_id to bundle for reverse lookup
POLICY_TO_BUNDLE: dict[str, str] = {
    "tdd.tests-before-impl": "tdd",
    "tdd.no-skip-tests": "tdd",
    "coding_standards.no-type-checking": "coding_standards",
    "coding_standards.no-backward-compat": "coding_standards",
    "coding_standards.no-emoji": "coding_standards",
}

_REMOVED_WORKFLOW_BUNDLE_ERROR = (
    "policy bundle 'workflow' was removed; remove 'workflow' from policy.bundles "
    "and delete policy.bundle_config.workflow"
)


def validate_bundle_name(bundle: str) -> None:
    """Reject bundle names that the registry cannot construct."""
    if bundle in BUNDLES:
        return
    if bundle == "workflow":
        raise ValueError(_REMOVED_WORKFLOW_BUNDLE_ERROR)
    available = ", ".join(BUNDLES)
    raise ValueError(f"unknown policy bundle {bundle!r}; available bundles: {available}")


def get_bundle_policies(bundle: str, *, config: dict[str, Any] | None = None) -> list[Policy]:
    """Get instantiated policies for a bundle.

    Args:
        bundle: Bundle name (e.g., "tdd", "coding_standards")
        config: Per-bundle configuration dict. For the "tdd" bundle:
            - ``{"strict": False}`` -> TDDEnforcementPolicy warns instead of denying
            - ``{"strict": True}`` or ``{}`` or ``None`` -> strict mode (default)

    Returns:
        List of policy instances.

    Raises:
        ValueError: If the bundle is unknown or the TDD ``strict`` value is not bool.

    Example:
        >>> policies = get_bundle_policies("tdd")
        >>> [p.policy_id for p in policies]
        ['tdd.tests-before-impl', 'tdd.no-skip-tests']
    """
    validate_bundle_name(bundle)
    policy_classes = BUNDLES[bundle]
    policies: list[Policy] = []
    for cls in policy_classes:
        if bundle == "tdd" and cls is TDDEnforcementPolicy:
            strict = True  # default
            if config and "strict" in config:
                val = config["strict"]
                if not isinstance(val, bool):
                    raise ValueError(f"bundle_config.tdd.strict must be bool, got {type(val).__name__}")
                strict = val
            policies.append(cls(strict=strict))
        else:
            policies.append(cls())
    return policies


def get_bundle_for_policy(policy_id: str) -> str | None:
    """Get the bundle name for a policy ID.

    Args:
        policy_id: Policy identifier (e.g., "tdd.tests-before-impl")

    Returns:
        Bundle name or None if not found.
    """
    return POLICY_TO_BUNDLE.get(policy_id)


def get_policy_ids_for_bundle(bundle: str) -> list[str]:
    """Get list of policy IDs in a bundle.

    Args:
        bundle: Bundle name

    Returns:
        List of policy IDs.
    """
    policies = get_bundle_policies(bundle)
    return [p.policy_id for p in policies]
