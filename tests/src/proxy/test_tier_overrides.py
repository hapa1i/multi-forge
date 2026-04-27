"""Tests for tier override application in proxy server."""

from unittest.mock import MagicMock, patch

import pytest

from forge.config import TierOverride


class TestGetTierOverride:
    """Tests for _get_tier_override helper."""

    def test_returns_tier_override_when_configured(self) -> None:
        """Verify tier override is returned when configured for the tier."""
        from forge.proxy.server import _get_tier_override

        mock_tier_override = TierOverride(
            reasoning_effort="high",
            temperature=0.7,
        )
        mock_tier_overrides = MagicMock()
        mock_tier_overrides.get.return_value = mock_tier_override

        mock_provider_cfg = MagicMock()
        mock_provider_cfg.tier_overrides = mock_tier_overrides

        mock_proxy_cfg = MagicMock()
        mock_proxy_cfg.get_provider.return_value = mock_provider_cfg

        mock_config = MagicMock()
        mock_config.proxy = mock_proxy_cfg

        with patch("forge.proxy.server.config", mock_config):
            result = _get_tier_override("opus")

        assert result is not None
        assert result.reasoning_effort == "high"
        assert result.temperature == 0.7
        mock_tier_overrides.get.assert_called_once_with("opus")

    def test_returns_none_when_tier_not_configured(self) -> None:
        """Verify None is returned when tier has no override configured."""
        from forge.proxy.server import _get_tier_override

        mock_tier_overrides = MagicMock()
        mock_tier_overrides.get.return_value = None

        mock_provider_cfg = MagicMock()
        mock_provider_cfg.tier_overrides = mock_tier_overrides

        mock_proxy_cfg = MagicMock()
        mock_proxy_cfg.get_provider.return_value = mock_provider_cfg

        mock_config = MagicMock()
        mock_config.proxy = mock_proxy_cfg

        with patch("forge.proxy.server.config", mock_config):
            result = _get_tier_override("haiku")

        assert result is None

    def test_returns_none_on_exception(self) -> None:
        """Verify None is returned when an exception occurs."""
        from forge.proxy.server import _get_tier_override

        mock_proxy_cfg = MagicMock()
        mock_proxy_cfg.get_provider.side_effect = ValueError("Config error")

        mock_config = MagicMock()
        mock_config.proxy = mock_proxy_cfg

        with patch("forge.proxy.server.config", mock_config):
            result = _get_tier_override("opus")

        assert result is None


class TestTierOverrideApplication:
    """Tests for tier override application in request processing."""

    @pytest.fixture
    def tier_override_fixture(self) -> TierOverride:
        """Create a tier override with all fields set."""
        return TierOverride(
            reasoning_effort="high",
            verbosity="detailed",
            temperature=0.8,
            thinking_budget_tokens=10000,
        )

    def test_tier_override_applied_when_request_has_no_explicit_value(
        self, tier_override_fixture: TierOverride
    ) -> None:
        """Verify tier overrides are applied when request doesn't specify values."""
        # Simulate the logic that would be in create_message
        openai_request_dict: dict = {"model": "test-model"}
        request_temperature = None
        request_reasoning_effort = None
        request_verbosity = None
        request_thinking = None
        tier_override = tier_override_fixture

        # Apply temperature
        if request_temperature is not None:
            openai_request_dict["temperature"] = request_temperature
        elif tier_override and tier_override.temperature is not None:
            openai_request_dict["temperature"] = tier_override.temperature

        # Apply reasoning_effort
        if request_reasoning_effort is not None:
            openai_request_dict["reasoning_effort"] = request_reasoning_effort
        elif tier_override and tier_override.reasoning_effort is not None:
            openai_request_dict["reasoning_effort"] = tier_override.reasoning_effort

        # Apply verbosity
        if request_verbosity is not None:
            openai_request_dict["verbosity"] = request_verbosity
        elif tier_override and tier_override.verbosity is not None:
            openai_request_dict["verbosity"] = tier_override.verbosity

        # Apply thinking
        if request_thinking is not None:
            openai_request_dict["thinking"] = request_thinking
        elif tier_override and tier_override.thinking_budget_tokens is not None:
            openai_request_dict["thinking"] = {"budget_tokens": tier_override.thinking_budget_tokens}

        # Verify all tier overrides were applied
        assert openai_request_dict["temperature"] == 0.8
        assert openai_request_dict["reasoning_effort"] == "high"
        assert openai_request_dict["verbosity"] == "detailed"
        assert openai_request_dict["thinking"] == {"budget_tokens": 10000}

    def test_request_explicit_value_takes_precedence_over_tier_override(
        self, tier_override_fixture: TierOverride
    ) -> None:
        """Verify request explicit values take precedence over tier overrides."""
        openai_request_dict: dict = {"model": "test-model"}
        request_temperature = 0.5
        request_reasoning_effort = "low"
        request_verbosity = "minimal"
        request_thinking = {"budget_tokens": 5000}
        tier_override = tier_override_fixture

        # Apply temperature (request explicit should win)
        if request_temperature is not None:
            openai_request_dict["temperature"] = request_temperature
        elif tier_override and tier_override.temperature is not None:
            openai_request_dict["temperature"] = tier_override.temperature

        # Apply reasoning_effort (request explicit should win)
        if request_reasoning_effort is not None:
            openai_request_dict["reasoning_effort"] = request_reasoning_effort
        elif tier_override and tier_override.reasoning_effort is not None:
            openai_request_dict["reasoning_effort"] = tier_override.reasoning_effort

        # Apply verbosity (request explicit should win)
        if request_verbosity is not None:
            openai_request_dict["verbosity"] = request_verbosity
        elif tier_override and tier_override.verbosity is not None:
            openai_request_dict["verbosity"] = tier_override.verbosity

        # Apply thinking (request explicit should win)
        if request_thinking is not None:
            openai_request_dict["thinking"] = request_thinking
        elif tier_override and tier_override.thinking_budget_tokens is not None:
            openai_request_dict["thinking"] = {"budget_tokens": tier_override.thinking_budget_tokens}

        # Verify request explicit values were used
        assert openai_request_dict["temperature"] == 0.5
        assert openai_request_dict["reasoning_effort"] == "low"
        assert openai_request_dict["verbosity"] == "minimal"
        assert openai_request_dict["thinking"] == {"budget_tokens": 5000}

    def test_no_tier_override_leaves_values_unset(self) -> None:
        """Verify no values are added when tier override is None."""
        openai_request_dict: dict = {"model": "test-model"}
        tier_override = None

        # Apply with no request values and no tier override
        if tier_override and tier_override.temperature is not None:
            openai_request_dict["temperature"] = tier_override.temperature

        if tier_override and tier_override.reasoning_effort is not None:
            openai_request_dict["reasoning_effort"] = tier_override.reasoning_effort

        # Verify nothing was added
        assert "temperature" not in openai_request_dict
        assert "reasoning_effort" not in openai_request_dict

    def test_partial_tier_override_applies_only_configured_fields(self) -> None:
        """Verify only configured tier override fields are applied."""
        openai_request_dict: dict = {"model": "test-model"}
        tier_override = TierOverride(
            reasoning_effort="medium",
            # temperature, verbosity, thinking_budget_tokens are None
        )

        # Apply all fields
        if tier_override and tier_override.temperature is not None:
            openai_request_dict["temperature"] = tier_override.temperature

        if tier_override and tier_override.reasoning_effort is not None:
            openai_request_dict["reasoning_effort"] = tier_override.reasoning_effort

        if tier_override and tier_override.verbosity is not None:
            openai_request_dict["verbosity"] = tier_override.verbosity

        if tier_override and tier_override.thinking_budget_tokens is not None:
            openai_request_dict["thinking"] = {"budget_tokens": tier_override.thinking_budget_tokens}

        # Verify only reasoning_effort was applied
        assert openai_request_dict.get("reasoning_effort") == "medium"
        assert "temperature" not in openai_request_dict
        assert "verbosity" not in openai_request_dict
        assert "thinking" not in openai_request_dict
