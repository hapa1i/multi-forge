"""Tests for workflow resource loading via importlib.resources."""

from __future__ import annotations

import pytest

from forge.cli.workflow import (
    _load_workflow_resource,
    _resolve_consensus_prompt,
    _resolve_debate_prompt,
)


class TestLoadWorkflowResource:
    def test_thinkdeep_loads(self):
        content = _load_workflow_resource("thinkdeep.md")
        assert len(content) > 100
        assert "Deep Analysis Framework" in content

    def test_codereview_loads(self):
        content = _load_workflow_resource("codereview.md")
        assert len(content) > 100
        assert "Code Review" in content

    def test_docreview_loads(self):
        content = _load_workflow_resource("docreview.md")
        assert len(content) > 100
        assert "Document Review" in content

    def test_nonexistent_raises(self):
        with pytest.raises((FileNotFoundError, TypeError)):
            _load_workflow_resource("nonexistent.md")


class TestEvaluationTemplatesLoad:
    """The 4 debate/consensus eval templates now live in forge.review.resources
    (moved out of cli/workflow.py). Single source of truth, so no drift guard is
    needed -- these assert the placeholders the resolvers depend on survive."""

    def test_debate_evaluation_loads(self):
        content = _load_workflow_resource("debate_evaluation.md")
        assert "Structured Evaluation" in content
        assert "{stance_prompt}" in content
        assert "{proposal}" in content

    def test_code_debate_evaluation_loads(self):
        content = _load_workflow_resource("code_debate_evaluation.md")
        assert "Adversarial Code Evaluation" in content
        assert "{stance_prompt}" in content
        assert "{target}" in content

    def test_consensus_evaluation_loads(self):
        content = _load_workflow_resource("consensus_evaluation.md")
        assert "Consensus Evaluation" in content
        assert "{role_prompt}" in content
        assert "{subject}" in content

    def test_code_consensus_evaluation_loads(self):
        content = _load_workflow_resource("code_consensus_evaluation.md")
        assert "Code Consensus Evaluation" in content
        assert "{role_prompt}" in content
        assert "{target}" in content

    def test_consensus_uses_support_not_accept_vocabulary(self):
        """Consensus templates must use SUPPORT/OPPOSE, not ACCEPT/REJECT."""
        for name in ("consensus_evaluation.md", "code_consensus_evaluation.md"):
            content = _load_workflow_resource(name)
            assert "SUPPORT" in content
            assert "OPPOSE" in content
            assert '"ACCEPT"' not in content
            assert '"REJECT"' not in content


class TestResolveDebatePrompt:
    """_resolve_debate_prompt loads the template and injects the subject -- no models/proxy."""

    def test_proposal_mode_wraps_subject(self):
        result = _resolve_debate_prompt(("Adopt", "feature", "flags"), None, code_mode=False)
        assert result is not None
        assert "Adopt feature flags" in result
        assert "{proposal}" not in result  # placeholder substituted
        assert "{stance_prompt}" in result  # runner fills this downstream

    def test_code_mode_wraps_target(self):
        result = _resolve_debate_prompt(("src/foo.py",), None, code_mode=True)
        assert result is not None
        assert "src/foo.py" in result
        assert "{target}" not in result
        assert "Adversarial Code Evaluation" in result

    def test_explicit_prompt_overrides_subject(self):
        result = _resolve_debate_prompt(("ignored",), "explicit proposal", code_mode=False)
        assert result is not None
        assert "explicit proposal" in result
        assert "ignored" not in result


class TestResolveConsensusPrompt:
    """_resolve_consensus_prompt loads the template and injects the subject -- no models/proxy."""

    def test_proposal_mode_wraps_subject(self):
        result = _resolve_consensus_prompt(("Use", "Postgres"), None, code_mode=False)
        assert result is not None
        assert "Use Postgres" in result
        assert "{subject}" not in result
        assert "{role_prompt}" in result

    def test_code_mode_wraps_target(self):
        result = _resolve_consensus_prompt(("src/bar.py",), None, code_mode=True)
        assert result is not None
        assert "src/bar.py" in result
        assert "{target}" not in result
        assert "Code Consensus Evaluation" in result
