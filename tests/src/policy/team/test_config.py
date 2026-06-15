"""Tests for forge.policy.team.config and PolicyIntent integration."""

from __future__ import annotations

import dacite
import pytest

from forge.policy.team.config import TeamSupervisorConfig
from forge.session.models import PolicyIntent


class TestTeamSupervisorConfig:
    def test_defaults(self):
        config = TeamSupervisorConfig()
        assert config.enabled is False
        assert config.tagger_model == "gemini/gemini-2.0-flash"
        assert config.resume_id is None
        assert config.timeout_seconds == 45
        assert config.throttle_seconds == 60
        assert config.max_blocks_per_task == 3

    def test_dacite_round_trip(self):
        data = {
            "enabled": True,
            "tagger_model": "openai/gpt-4o-mini",
            "resume_id": "abc-123",
            "timeout_seconds": 30,
            "max_blocks_per_task": 5,
        }
        config = dacite.from_dict(TeamSupervisorConfig, data)
        assert config.enabled is True
        assert config.resume_id == "abc-123"
        assert config.max_blocks_per_task == 5


class TestPolicyIntentTeamSupervisor:
    def test_default_is_none(self):
        intent = PolicyIntent()
        assert intent.team_supervisor is None

    def test_dacite_with_team_supervisor(self):
        data = {
            "enabled": True,
            "team_supervisor": {
                "enabled": True,
                "resume_id": "plan-session-id",
            },
        }
        intent = dacite.from_dict(PolicyIntent, data)
        assert intent.team_supervisor is not None
        assert intent.team_supervisor.enabled is True
        assert intent.team_supervisor.resume_id == "plan-session-id"

    def test_dacite_without_team_supervisor(self):
        """Existing manifests without team_supervisor still deserialize."""
        data = {"enabled": True, "bundles": ["tdd"]}
        intent = dacite.from_dict(PolicyIntent, data)
        assert intent.team_supervisor is None


class TestTeamSupervisorEffortValidation:
    """effort uses the claude --effort vocabulary (low/medium/high/xhigh/max)."""

    def test_max_is_valid(self):
        assert TeamSupervisorConfig(effort="max").effort == "max"

    def test_none_rejected(self):
        # "none" is a core.llm value, not a claude --effort level.
        with pytest.raises(ValueError):
            TeamSupervisorConfig(effort="none")

    def test_bogus_rejected(self):
        with pytest.raises(ValueError):
            TeamSupervisorConfig(effort="bogus")
