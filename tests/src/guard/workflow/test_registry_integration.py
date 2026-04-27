"""Integration tests for workflow bundle registration."""

from __future__ import annotations

import pytest

from forge.guard.deterministic.registry import (
    get_all_bundles,
    get_bundle_for_policy,
    get_bundle_policies,
    get_policy_ids_for_bundle,
)
from forge.guard.engine import build_engine
from forge.guard.workflow.divergence import build_divergence_config

pytestmark = pytest.mark.integration


class TestWorkflowBundleRegistration:
    def test_build_engine_with_workflow(self):
        config = build_divergence_config()
        bundle_config = {
            "workflow": {
                "workflows": [
                    {
                        "name": config.name,
                        "description": config.description,
                        "intent": config.intent,
                        "tagger_prompt": config.tagger_prompt,
                        "tagger_model": config.tagger_model,
                    }
                ]
            }
        }
        engine = build_engine(["workflow"], bundle_config=bundle_config)
        assert len(engine.policies) == 1
        assert engine.policies[0].policy_id == "workflow.divergence"

    def test_workflow_without_config_returns_empty(self):
        policies = get_bundle_policies("workflow")
        assert policies == []

    def test_workflow_with_empty_workflows_returns_empty(self):
        policies = get_bundle_policies("workflow", config={"workflows": []})
        assert policies == []

    def test_multiple_workflows(self):
        config = {
            "workflows": [
                {"name": "flow-a", "description": "Flow A", "intent": "Flow A intent"},
                {"name": "flow-b", "description": "Flow B", "intent": "Flow B intent"},
            ]
        }
        policies = get_bundle_policies("workflow", config=config)
        assert len(policies) == 2
        assert policies[0].policy_id == "workflow.flow-a"
        assert policies[1].policy_id == "workflow.flow-b"


class TestWorkflowBundleLookup:
    def test_get_bundle_for_workflow_policy(self):
        assert get_bundle_for_policy("workflow.divergence") == "workflow"
        assert get_bundle_for_policy("workflow.custom") == "workflow"

    def test_get_bundle_for_non_workflow(self):
        assert get_bundle_for_policy("tdd.tests-before-impl") == "tdd"

    def test_workflow_in_all_bundles(self):
        assert "workflow" in get_all_bundles()

    def test_policy_ids_for_workflow_returns_empty(self):
        """Workflow policy IDs are dynamic; without config, returns []."""
        assert get_policy_ids_for_bundle("workflow") == []
