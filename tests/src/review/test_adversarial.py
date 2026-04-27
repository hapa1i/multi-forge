"""Tests for forge.review.adversarial."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from forge.review.adversarial import (
    ETHICAL_GUARDRAIL,
    STANCE_MARKER,
    run_adversarial,
    validate_resource,
)
from forge.review.models import ModelSpec, StanceSpec


def _spec(name: str = "test-model", proxy: str | None = "test-proxy") -> ModelSpec:
    return ModelSpec(name=name, proxy=proxy, model_flag=None, description="Test")


def _mock_popen(stdout: str = "output", returncode: int = 0):
    proc = MagicMock()
    proc.communicate.return_value = (stdout, "")
    proc.returncode = returncode
    proc.poll.return_value = returncode
    proc.pid = 12345
    return proc


class TestValidateResource:
    def test_accepts_resource_with_marker(self, tmp_path):
        resource = tmp_path / "eval.md"
        resource.write_text(f"Evaluate this: {STANCE_MARKER}")
        content = validate_resource(str(resource))
        assert STANCE_MARKER in content

    def test_rejects_resource_without_marker(self, tmp_path):
        resource = tmp_path / "eval.md"
        resource.write_text("No marker here")
        with pytest.raises(ValueError, match="stance_prompt"):
            validate_resource(str(resource))


class TestStanceSpec:
    def test_valid_stances(self):
        for stance in ("for", "against", "neutral"):
            spec = StanceSpec(stance=stance, stance_prompt="test", model=_spec())
            assert spec.stance == stance

    def test_invalid_stance_raises(self):
        with pytest.raises(ValueError, match="Invalid stance"):
            StanceSpec(stance="maybe", stance_prompt="test", model=_spec())


class TestRunAdversarial:
    @patch(
        "forge.review.engine.lookup_proxy_base_url",
        return_value="http://localhost:8085",
    )
    @patch("forge.review.engine.subprocess.Popen")
    def test_replaces_stance_marker(self, mock_popen_cls, mock_lookup, tmp_path):
        resource = tmp_path / "eval.md"
        resource.write_text(f"Evaluate: {STANCE_MARKER}\nEnd.")
        mock_popen_cls.return_value = _mock_popen()

        stances = [
            StanceSpec(stance="for", stance_prompt="Be supportive", model=_spec("m1")),
        ]
        run_adversarial(str(resource), stances)

        # The worker prompt should have the stance text replacing the marker
        communicate_kwargs = mock_popen_cls.return_value.communicate.call_args[1]
        worker_prompt = communicate_kwargs["input"]
        assert "Be supportive" in worker_prompt
        assert STANCE_MARKER not in worker_prompt

    @patch(
        "forge.review.engine.lookup_proxy_base_url",
        return_value="http://localhost:8085",
    )
    @patch("forge.review.engine.subprocess.Popen")
    def test_ethical_guardrail_present(self, mock_popen_cls, mock_lookup, tmp_path):
        """Ethical guardrail is appended to ALL worker prompts."""
        resource = tmp_path / "eval.md"
        resource.write_text(f"Evaluate: {STANCE_MARKER}")
        mock_popen_cls.return_value = _mock_popen()

        stances = [
            StanceSpec(stance="against", stance_prompt="Be critical", model=_spec()),
        ]
        run_adversarial(str(resource), stances)

        worker_prompt = mock_popen_cls.return_value.communicate.call_args[1]["input"]
        assert ETHICAL_GUARDRAIL in worker_prompt

    @patch(
        "forge.review.engine.lookup_proxy_base_url",
        return_value="http://localhost:8085",
    )
    @patch("forge.review.engine.subprocess.Popen")
    def test_mandatory_blinding(self, mock_popen_cls, mock_lookup, tmp_path):
        """resume_id is always None (mandatory blinding)."""
        resource = tmp_path / "eval.md"
        resource.write_text(f"Evaluate: {STANCE_MARKER}")
        mock_popen_cls.return_value = _mock_popen()

        stances = [
            StanceSpec(stance="neutral", stance_prompt="Be balanced", model=_spec()),
        ]
        run_adversarial(str(resource), stances)

        # Check the Popen command does NOT contain --resume
        cmd = mock_popen_cls.call_args[0][0]
        assert "--resume" not in cmd

    @patch(
        "forge.review.engine.lookup_proxy_base_url",
        return_value="http://localhost:8085",
    )
    @patch("forge.review.engine.subprocess.Popen")
    def test_worker_names_include_stance(self, mock_popen_cls, mock_lookup, tmp_path):
        resource = tmp_path / "eval.md"
        resource.write_text(f"Evaluate: {STANCE_MARKER}")
        mock_popen_cls.return_value = _mock_popen()

        stances = [
            StanceSpec(stance="for", stance_prompt="Support", model=_spec("gpt")),
            StanceSpec(stance="against", stance_prompt="Critique", model=_spec("gem")),
        ]
        output = run_adversarial(str(resource), stances)

        names = [r.model_name for r in output.results]
        assert "gpt-for" in names
        assert "gem-against" in names

    def test_incompatible_resource_raises(self, tmp_path):
        resource = tmp_path / "no-marker.md"
        resource.write_text("Just plain text")

        stances = [StanceSpec(stance="for", stance_prompt="test", model=_spec())]
        with pytest.raises(ValueError, match="stance_prompt"):
            run_adversarial(str(resource), stances)

    @patch(
        "forge.review.engine.lookup_proxy_base_url",
        return_value="http://localhost:8085",
    )
    @patch("forge.review.engine.subprocess.Popen")
    def test_output_includes_stances(self, mock_popen_cls, mock_lookup, tmp_path):
        resource = tmp_path / "eval.md"
        resource.write_text(f"Evaluate: {STANCE_MARKER}")
        mock_popen_cls.return_value = _mock_popen()

        stances = [
            StanceSpec(stance="for", stance_prompt="test", model=_spec("m1")),
            StanceSpec(stance="against", stance_prompt="test", model=_spec("m2")),
        ]
        output = run_adversarial(str(resource), stances)

        assert output.stances == ["for", "against"]
        assert output.resource_path == str(resource)
