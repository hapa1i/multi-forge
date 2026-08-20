"""Regression: workflow-policy config silently discarded unknown keys.

O083: ``_build_workflow_policies`` used dacite's non-strict default, so a
misspelling such as ``tagger_promt`` produced a policy with the permissive empty
default. Nested workflow dataclasses had the same failure mode.
"""

from __future__ import annotations

from typing import Any

import pytest

from forge.policy.deterministic.registry import get_bundle_policies

pytestmark = pytest.mark.regression


def _workflow(**overrides: Any) -> dict[str, Any]:
    workflow = {"name": "guardrails", "description": "Review guarded changes"}
    workflow.update(overrides)
    return workflow


@pytest.mark.parametrize(
    ("workflow", "unknown_field"),
    [
        (_workflow(tagger_promt="Classify this change"), "tagger_promt"),
        (
            _workflow(
                branches=[
                    {
                        "name": "review",
                        "match_tags": ["architectural"],
                        "checker": {"prompt_templat": "Check this change"},
                    }
                ]
            ),
            "prompt_templat",
        ),
    ],
)
def test_o083_unknown_workflow_keys_fail_with_entry_context(
    workflow: dict[str, Any], unknown_field: str
) -> None:
    with pytest.raises(ValueError) as caught:
        get_bundle_policies("workflow", config={"workflows": [workflow]})

    message = str(caught.value)
    assert "bundle_config.workflow.workflows[0]" in message
    assert "guardrails" in message
    assert unknown_field in message


@pytest.mark.parametrize(
    ("workflow", "expected_detail"),
    [
        (_workflow(throttle_seconds="fast"), "throttle_seconds"),
        ("not-an-object", "must be an object, got str"),
    ],
)
def test_o083_malformed_workflow_entries_raise_actionable_value_error(
    workflow: object, expected_detail: str
) -> None:
    with pytest.raises(ValueError, match=r"bundle_config\.workflow\.workflows\[0\]") as caught:
        get_bundle_policies("workflow", config={"workflows": [workflow]})

    assert expected_detail in str(caught.value)


def test_o083_valid_defaulted_workflows_preserve_order_and_defaults() -> None:
    policies = get_bundle_policies(
        "workflow",
        config={
            "workflows": [
                _workflow(),
                {"name": "second", "description": "Second workflow"},
            ]
        },
    )

    assert [policy.policy_id for policy in policies] == ["workflow.guardrails", "workflow.second"]
    assert [policy.description for policy in policies] == ["Review guarded changes", "Second workflow"]
    assert [policy.intent for policy in policies] == ["", ""]
