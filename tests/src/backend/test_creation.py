"""Tests for backend config creation."""

from pathlib import Path

import pytest
import yaml

from forge.backend.creation import create_backend_config, get_backend_config_path


class TestCreateBackendConfig:
    """Tests for create_backend_config function."""

    def test_creates_config_from_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify config is created from default template."""
        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        config_path = create_backend_config(adapter_type="litellm")

        assert config_path.exists()
        assert config_path.parent.name == "litellm"
        assert config_path.name == "config.yaml"

        content = config_path.read_text()
        assert "model_list:" in content
        assert "gemini" in content.lower()

    @pytest.mark.parametrize(
        ("model_name", "upstream_model"),
        [
            ("openai/gpt-6-astra", "openai/gpt-6-astra"),
            ("openai/gpt-5.6", "openai/gpt-5.6"),
            ("openai/gpt-5.6-sol", "openai/gpt-5.6-sol"),
            ("openai/gpt-5.6-terra", "openai/gpt-5.6-terra"),
            ("openai/gpt-5.6-luna", "openai/gpt-5.6-luna"),
        ],
    )
    def test_default_config_has_current_and_retained_gpt_model_route(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        model_name: str,
        upstream_model: str,
    ) -> None:
        """The generated LiteLLM config exposes Astra and retained GPT-5.6 model routes."""
        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        config_path = create_backend_config(adapter_type="litellm")
        config = yaml.safe_load(config_path.read_text())
        model_pairs = {(entry["model_name"], entry["litellm_params"]["model"]) for entry in config["model_list"]}

        assert (model_name, upstream_model) in model_pairs

    @pytest.mark.parametrize(
        ("prompt_tokens", "cached_tokens", "expected_input", "expected_output"),
        [
            (100, 0, 0.001, 0.0005),
            (100, 80, 0.00028, 0.0005),
            (272_000, 1_000, 2.711, 0.0005),
            (272_001, 1_000, 5.42202, 0.00075),
        ],
    )
    def test_astra_pricing_without_remote_model_metadata(
        self,
        monkeypatch: pytest.MonkeyPatch,
        prompt_tokens: int,
        cached_tokens: int,
        expected_input: float,
        expected_output: float,
    ) -> None:
        import litellm

        config = yaml.safe_load(create_backend_config(adapter_type="litellm").read_text())
        entry = next(model for model in config["model_list"] if model["model_name"] == "openai/gpt-6-astra")
        entry["litellm_params"]["api_key"] = "test-key"
        monkeypatch.setattr(litellm, "model_cost", {})
        router = litellm.Router(model_list=[entry])
        deployment_id = router.model_list[0]["model_info"]["id"]

        costs = litellm.cost_per_token(
            model=deployment_id,
            custom_llm_provider="openai",
            prompt_tokens=prompt_tokens,
            completion_tokens=10,
            cache_read_input_tokens=cached_tokens,
        )

        assert costs == pytest.approx((expected_input, expected_output))

    @pytest.mark.parametrize(
        ("model_name", "upstream_model"),
        [
            ("gemini/gemini-3.7-flash", "gemini/gemini-3.7-flash"),
            ("gemini-3.7-flash", "gemini/gemini-3.7-flash"),
            ("gemini/gemini-3.6-flash", "gemini/gemini-3.6-flash"),
            ("gemini-3.6-flash", "gemini/gemini-3.6-flash"),
        ],
    )
    def test_default_config_has_current_and_legacy_gemini_flash_routes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        model_name: str,
        upstream_model: str,
    ) -> None:
        """The generated config exposes current and backward-compatible Flash routes."""
        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        config_path = create_backend_config(adapter_type="litellm")
        config = yaml.safe_load(config_path.read_text())
        model_pairs = {(entry["model_name"], entry["litellm_params"]["model"]) for entry in config["model_list"]}

        assert (model_name, upstream_model) in model_pairs

    @pytest.mark.parametrize(
        "model_name",
        [
            "anthropic/claude-haiku-4-5",
            "anthropic/claude-sonnet-5",
            "anthropic/claude-opus-5",
            "anthropic/claude-fable-5-1",
            "anthropic/claude-fable-5",
            "anthropic/claude-opus-4-8",
            "anthropic/claude-opus-4-6",
            "anthropic/claude-sonnet-4-6",
        ],
    )
    def test_default_config_exposes_litellm_anthropic_template_models(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        model_name: str,
    ) -> None:
        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        config_path = create_backend_config(adapter_type="litellm")
        config = yaml.safe_load(config_path.read_text())
        model_pairs = {(entry["model_name"], entry["litellm_params"]["model"]) for entry in config["model_list"]}

        assert (model_name, model_name) in model_pairs

    def test_creates_config_from_custom_source(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify config can be created from custom source."""
        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        custom_config = tmp_path / "custom.yaml"
        custom_config.write_text("custom: config\nkey: value\n")

        config_path = create_backend_config(
            adapter_type="litellm",
            source_config=custom_config,
        )

        assert config_path.exists()
        content = config_path.read_text()
        assert "custom: config" in content

    def test_config_has_restricted_permissions(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify config file has 600 permissions."""
        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        config_path = create_backend_config(adapter_type="litellm")

        mode = config_path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_overwrites_existing_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify creating config overwrites existing file."""
        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        config_path = create_backend_config(adapter_type="litellm")
        initial_content = config_path.read_text()

        custom_config = tmp_path / "custom.yaml"
        custom_config.write_text("different: content\n")

        config_path = create_backend_config(
            adapter_type="litellm",
            source_config=custom_config,
        )

        new_content = config_path.read_text()
        assert new_content != initial_content
        assert "different: content" in new_content

    def test_raises_for_unknown_adapter(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify unknown adapter type raises ValueError (no default config exists)."""
        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        with pytest.raises(ValueError) as exc_info:
            create_backend_config(adapter_type="unknown")
        assert "No default config for adapter 'unknown'" in str(exc_info.value)

    def test_raises_for_missing_source(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify missing source config raises ValueError."""
        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        nonexistent = tmp_path / "nonexistent.yaml"
        with pytest.raises(ValueError) as exc_info:
            create_backend_config(adapter_type="litellm", source_config=nonexistent)
        assert "No default config for adapter" in str(exc_info.value)


class TestGetBackendConfigPath:
    """Tests for get_backend_config_path function."""

    def test_returns_correct_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify correct path is returned."""
        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        path = get_backend_config_path("litellm")

        assert path == tmp_path / "backends" / "litellm" / "config.yaml"

    def test_path_may_not_exist(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify path is returned even if it doesn't exist."""
        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        path = get_backend_config_path("litellm")

        assert not path.exists()
        assert path.name == "config.yaml"
