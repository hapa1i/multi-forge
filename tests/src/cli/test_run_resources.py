"""Tests for workflow resource loading via importlib.resources."""

from __future__ import annotations

import pytest

from forge.cli.workflow import _load_workflow_resource


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
