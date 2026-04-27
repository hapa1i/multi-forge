"""Bundle registry for deterministic policies.

Maps bundle names to policy classes. Bundles are collections of related
policies that can be enabled together.

Available bundles:
- tdd: Test-driven development workflow enforcement
- coding_standards: Code style and architecture conventions
- workflow: Config-driven tagger → branch → stage pipelines
"""

from __future__ import annotations

from typing import Any

from forge.guard.deterministic.coding_standards import (
    NoBackwardCompatPolicy,
    NoEmojiPolicy,
    NoTypeCheckingPolicy,
)
from forge.guard.deterministic.tdd import (
    NoSkipTestsPolicy,
    TDDEnforcementPolicy,
)
from forge.guard.protocols import Policy

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


def get_bundle_policies(bundle: str, *, config: dict[str, Any] | None = None) -> list[Policy]:
    """Get instantiated policies for a bundle.

    Args:
        bundle: Bundle name (e.g., "tdd", "coding_standards", "workflow")
        config: Per-bundle configuration dict. For the "tdd" bundle:
            - ``{"strict": False}`` -> TDDEnforcementPolicy warns instead of denying
            - ``{"strict": True}`` or ``{}`` or ``None`` -> strict mode (default)

            For the "workflow" bundle:
            - ``{"workflows": [{...}, ...]}`` -> one WorkflowPolicy per entry

    Returns:
        List of policy instances. Empty list if bundle not found.

    Raises:
        ValueError: If config contains invalid types (e.g., ``strict`` is not bool).

    Example:
        >>> policies = get_bundle_policies("tdd")
        >>> [p.policy_id for p in policies]
        ['tdd.tests-before-impl', 'tdd.no-skip-tests']
    """
    if bundle == "workflow":
        return _build_workflow_policies(config)

    policy_classes = BUNDLES.get(bundle, [])
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


def _build_workflow_policies(config: dict[str, Any] | None) -> list[Policy]:
    """Instantiate WorkflowPolicy instances from workflow config.

    Lazy-imports workflow module to avoid pulling LLM dependencies
    unless the workflow bundle is actually used.
    """
    import dacite

    from forge.guard.workflow.config import WorkflowConfig
    from forge.guard.workflow.policy import WorkflowPolicy

    if not config:
        return []
    workflows = config.get("workflows", [])
    if not isinstance(workflows, list):
        raise ValueError(f"bundle_config.workflow.workflows must be a list, got {type(workflows).__name__}")
    policies: list[Policy] = []
    for wf_dict in workflows:
        wf_config = dacite.from_dict(WorkflowConfig, wf_dict)
        policies.append(WorkflowPolicy(config=wf_config))
    return policies


def get_all_bundles() -> list[str]:
    """Get list of all available bundle names."""
    return list(BUNDLES.keys()) + ["workflow"]


def get_bundle_for_policy(policy_id: str) -> str | None:
    """Get the bundle name for a policy ID.

    Args:
        policy_id: Policy identifier (e.g., "tdd.tests-before-impl")

    Returns:
        Bundle name or None if not found.
    """
    if policy_id.startswith("workflow."):
        return "workflow"
    return POLICY_TO_BUNDLE.get(policy_id)


def get_policy_ids_for_bundle(bundle: str) -> list[str]:
    """Get list of policy IDs in a bundle.

    For the "workflow" bundle, returns ``[]`` because workflow policy IDs
    are dynamic (``workflow.<name>``) and only known at runtime with config.

    Args:
        bundle: Bundle name

    Returns:
        List of policy IDs. Empty list if bundle not found.
    """
    policies = get_bundle_policies(bundle)
    return [p.policy_id for p in policies]
