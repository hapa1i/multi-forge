"""Tests for config loader functions (deep_merge, load_yaml, env_to_dict, load_config, proxy I/O, templates)."""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from forge.config import load_config
from forge.config.loader import (
    deep_merge,
    env_to_dict,
    get_user_template_path,
    is_user_template,
    list_template_names,
    load_yaml,
    read_shipped_template,
    read_template,
    shipped_template_exists,
    template_exists,
    validate_template_name,
)


class TestDeepMerge:
    """Tests for deep_merge function."""

    def test_simple_merge(self):
        """Merges flat dicts correctly."""
        base = {"a": 1, "b": 2}
        overlay = {"b": 3, "c": 4}
        result = deep_merge(base, overlay)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        """Merges nested dicts recursively."""
        base = {"outer": {"a": 1, "b": 2}}
        overlay = {"outer": {"b": 3, "c": 4}}
        result = deep_merge(base, overlay)
        assert result == {"outer": {"a": 1, "b": 3, "c": 4}}

    def test_none_values_skipped(self):
        """None values in overlay don't override base."""
        base = {"a": 1, "b": 2}
        overlay = {"a": None, "c": 3}
        result = deep_merge(base, overlay)
        assert result == {"a": 1, "b": 2, "c": 3}

    def test_base_not_modified(self):
        """Original dicts are not modified."""
        base = {"a": 1}
        overlay = {"b": 2}
        _ = deep_merge(base, overlay)
        assert base == {"a": 1}
        assert overlay == {"b": 2}


class TestLoadYaml:
    """Tests for YAML loading."""

    def test_load_existing_file(self, tmp_path):
        """Loads YAML file correctly."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("key: value\nnested:\n  inner: data")

        result = load_yaml(yaml_file)
        assert result == {"key": "value", "nested": {"inner": "data"}}

    def test_load_missing_file(self, tmp_path):
        """Returns empty dict for missing file."""
        result = load_yaml(tmp_path / "nonexistent.yaml")
        assert result == {}

    def test_load_invalid_yaml(self, tmp_path):
        """Returns empty dict for invalid YAML."""
        yaml_file = tmp_path / "invalid.yaml"
        yaml_file.write_text("invalid: yaml: content: [}")

        result = load_yaml(yaml_file)
        assert result == {}


class TestEnvToDict:
    """Tests for environment variable mapping (recognized overrides only)."""

    def test_maps_forge_home(self, monkeypatch):
        """Maps FORGE_HOME to session.forge_home."""
        monkeypatch.setenv("FORGE_HOME", "/custom/forge")

        result = env_to_dict()

        assert result["session"]["forge_home"] == "/custom/forge"

    def test_ignores_non_mapped_env(self, monkeypatch):
        """Provider/config env vars and the removed *_AUTH_URL secrets are not mapped."""
        monkeypatch.setenv("LITELLM_BASE_URL", "http://example.com")
        monkeypatch.setenv("PREFERRED_PROVIDER", "openai")
        monkeypatch.setenv("GEMINI_AUTH_URL", "https://auth.example.com")
        monkeypatch.setenv("OPENAI_AUTH_URL", "https://auth.example.com")

        result = env_to_dict()

        # No proxy/auth_url plumbing remains; only recognized overrides map through
        assert "proxy" not in result


class TestLoadConfig:
    """Tests for config loading (3-source model)."""

    def test_empty_config_uses_schema_defaults(self):
        """load_config() with no args returns schema defaults."""
        config = load_config()

        # Schema defaults from SessionConfig and ProxyConfig
        assert config.session.default_tier == "sonnet"
        assert config.proxy.default_tier == "sonnet"
        assert config.proxy.default_port == 8082

    def test_template_loading(self):
        """Template loading populates config from template YAML."""
        config = load_config(template="litellm-gemini-local")

        assert config.proxy.active_template == "litellm-gemini-local"
        assert config.proxy.preferred_provider == "litellm"
        assert config.proxy.backend == "litellm-gemini-local"
        assert config.proxy.default_port == 8086
        assert config.proxy.litellm.base_url == ""
        assert config.proxy.litellm.tiers.opus == "gemini/gemini-3.1-pro-preview"
        assert config.proxy.backend_dependency is not None
        assert config.proxy.backend_dependency.adapter == "litellm"
        assert config.proxy.backend_dependency.port == 4000
        assert config.proxy.backend_dependency.required_env_vars == ["GEMINI_API_KEY"]

    def test_template_loading_gemini_flash_local(self):
        """Gemini Flash local template loads with all tiers using Flash."""
        config = load_config(template="litellm-gemini-flash-local")

        assert config.proxy.active_template == "litellm-gemini-flash-local"
        assert config.proxy.preferred_provider == "litellm"
        assert config.proxy.default_port == 8088
        assert config.proxy.litellm.tiers.haiku == "gemini/gemini-3-flash-preview"
        assert config.proxy.litellm.tiers.sonnet == "gemini/gemini-3-flash-preview"
        assert config.proxy.litellm.tiers.opus == "gemini/gemini-3-flash-preview"

    def test_template_loading_openai_local(self):
        """OpenAI local template loads with correct tier models."""
        config = load_config(template="litellm-openai-local")

        assert config.proxy.active_template == "litellm-openai-local"
        assert config.proxy.preferred_provider == "litellm"
        assert config.proxy.default_port == 8089
        assert config.proxy.litellm.tiers.haiku == "openai/gpt-5.4-mini"
        assert config.proxy.litellm.tiers.sonnet == "openai/gpt-5.6-sol"
        assert config.proxy.litellm.tiers.opus == "openai/gpt-5.6-sol"

    def test_template_loading_openai_codex_local(self):
        """OpenAI Codex local template loads with correct tier models."""
        config = load_config(template="litellm-openai-codex-local")

        assert config.proxy.active_template == "litellm-openai-codex-local"
        assert config.proxy.preferred_provider == "litellm"
        assert config.proxy.default_port == 8090
        assert config.proxy.litellm.tiers.haiku == "openai/gpt-5.1-codex-mini"
        assert config.proxy.litellm.tiers.sonnet == "openai/gpt-5.3-codex"
        assert config.proxy.litellm.tiers.opus == "openai/gpt-5.6-sol"

    @pytest.mark.parametrize(
        ("template", "provider", "expected_tiers"),
        [
            (
                "openrouter-openai",
                "openrouter",
                ("openai/gpt-5.4-mini", "openai/gpt-5.6-sol", "openai/gpt-5.6-sol"),
            ),
            (
                "litellm-openai",
                "litellm",
                ("openai/gpt-5.4-mini", "openai/gpt-5.6-sol", "openai/gpt-5.6-sol"),
            ),
            (
                "litellm-openai-local",
                "litellm",
                ("openai/gpt-5.4-mini", "openai/gpt-5.6-sol", "openai/gpt-5.6-sol"),
            ),
            (
                "openrouter-openai-codex",
                "openrouter",
                (
                    "openai/gpt-5.1-codex-mini",
                    "openai/gpt-5.3-codex",
                    "openai/gpt-5.6-sol",
                ),
            ),
            (
                "litellm-openai-codex-local",
                "litellm",
                (
                    "openai/gpt-5.1-codex-mini",
                    "openai/gpt-5.3-codex",
                    "openai/gpt-5.6-sol",
                ),
            ),
            (
                "codex-responses-local",
                "litellm",
                ("openai/gpt-5.4-mini", "openai/gpt-5.6-sol", "openai/gpt-5.6-sol"),
            ),
        ],
    )
    def test_openai_templates_use_expected_gpt_5_6_sol_tiers(
        self,
        template: str,
        provider: str,
        expected_tiers: tuple[str, str, str],
    ) -> None:
        """OpenAI templates promote GPT-5.6 Sol without changing their other tiers."""
        config = load_config(template=template)
        provider_config = getattr(config.proxy, provider)

        assert (
            provider_config.tiers.haiku,
            provider_config.tiers.sonnet,
            provider_config.tiers.opus,
        ) == expected_tiers

    def test_template_sets_active_template(self):
        """load_config(template=...) sets proxy.active_template."""
        config = load_config(template="litellm-openai")

        assert config.proxy.active_template == "litellm-openai"

    def test_template_not_found_raises(self):
        """load_config(template="nonexistent") raises ValueError."""
        with pytest.raises(ValueError, match="Template not found"):
            load_config(template="nonexistent-template")

    def test_get_model_for_tier(self):
        """get_model_for_tier returns correct model."""
        config = load_config(template="litellm-gemini-local")

        assert config.proxy.get_model_for_tier("opus") == "gemini/gemini-3.1-pro-preview"
        assert config.proxy.get_model_for_tier("sonnet") == "gemini/gemini-3.1-pro-preview"
        assert config.proxy.get_model_for_tier("haiku") == "gemini/gemini-3-flash-preview"

    def test_template_loading_openrouter_anthropic(self, monkeypatch: pytest.MonkeyPatch):
        """OpenRouter anthropic template loads with correct provider and tiers."""
        monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)

        config = load_config(template="openrouter-anthropic")

        assert config.proxy.active_template == "openrouter-anthropic"
        assert config.proxy.preferred_provider == "openrouter"
        assert config.proxy.backend == "openrouter"
        assert config.proxy.default_port == 8095
        assert config.proxy.openrouter.tiers.haiku == "anthropic/claude-haiku-4.5"
        assert config.proxy.openrouter.tiers.sonnet == "anthropic/claude-sonnet-5"
        # Defaults: sonnet -> Sonnet 5, opus -> Opus 4.8; displaced models stay selectable via --model.
        assert config.proxy.openrouter.tiers.opus == "anthropic/claude-opus-4.8"
        assert config.proxy.openrouter.base_url == "https://openrouter.ai/api/v1"
        assert config.proxy.openrouter.model_alternatives == {
            "opus": {
                "claude-fable-5": "anthropic/claude-fable-5",
                "claude-opus-4-6": "anthropic/claude-opus-4.6",
            },
            "sonnet": {
                "claude-sonnet-4-6": "anthropic/claude-sonnet-4.6",
            },
        }

    def test_openrouter_source_endpoint_resolves_from_env(self, monkeypatch: pytest.MonkeyPatch):
        """OpenRouter templates intentionally allow the catalog endpoint override."""
        monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.internal.example.com/api/v1")

        config = load_config(template="openrouter-anthropic")

        assert config.proxy.backend == "openrouter"
        assert config.proxy.openrouter.base_url == "https://openrouter.internal.example.com/api/v1"

    def test_remote_litellm_source_endpoint_resolves_from_env(self, monkeypatch: pytest.MonkeyPatch):
        """Remote LiteLLM templates derive upstream base_url from their catalog source."""
        monkeypatch.setenv("LITELLM_BASE_URL", "https://litellm.env.example.com")

        config = load_config(template="litellm-gemini")

        assert config.proxy.backend == "litellm-remote"
        assert config.proxy.litellm.base_url == "https://litellm.env.example.com"

    def test_remote_litellm_source_endpoint_resolves_from_credential_file(self, monkeypatch: pytest.MonkeyPatch):
        """Connection-value endpoints can come from the credential file when env is absent."""
        monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
        with patch(
            "forge.core.auth.template_secrets._get_file_secrets",
            return_value={"LITELLM_BASE_URL": "https://litellm.file.example.com"},
        ):
            config = load_config(template="litellm-gemini")

        assert config.proxy.backend == "litellm-remote"
        assert config.proxy.litellm.base_url == "https://litellm.file.example.com"

    def test_remote_litellm_source_endpoint_respects_auth_ignore_env(self, monkeypatch: pytest.MonkeyPatch):
        """Template loading uses the same auth_ignore_env branch as secret resolution."""
        monkeypatch.setattr("forge.core.auth.template_secrets._auth_ignore_env", lambda: True)
        monkeypatch.setenv("LITELLM_BASE_URL", "https://litellm.env.example.com")
        with patch(
            "forge.core.auth.template_secrets._get_file_secrets",
            return_value={"LITELLM_BASE_URL": "https://litellm.file.example.com"},
        ):
            config = load_config(template="litellm-gemini")

        assert config.proxy.backend == "litellm-remote"
        assert config.proxy.litellm.base_url == "https://litellm.file.example.com"

    def test_remote_litellm_source_endpoint_missing_is_empty(self, monkeypatch: pytest.MonkeyPatch):
        """Missing connection values remain empty until proxy creation reports missing credentials."""
        monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
        with patch("forge.core.auth.template_secrets._get_file_secrets", return_value={}):
            config = load_config(template="litellm-gemini")

        assert config.proxy.backend == "litellm-remote"
        assert config.proxy.litellm.base_url == ""

    def test_litellm_anthropic_templates_default_opus_to_4_8(self):
        """LiteLLM Anthropic templates default opus to Opus 4.8, sonnet to Sonnet 5."""
        for template in ("litellm-anthropic", "litellm-anthropic-local"):
            config = load_config(template=template)

            assert config.proxy.preferred_provider == "litellm", template
            assert config.proxy.litellm.tiers.sonnet == "anthropic/claude-sonnet-5", template
            assert config.proxy.litellm.tiers.opus == "anthropic/claude-opus-4-8", template
            assert config.proxy.litellm.model_alternatives == {
                "opus": {
                    "claude-fable-5": "anthropic/claude-fable-5",
                    "claude-opus-4-6": "anthropic/claude-opus-4-6",
                },
                "sonnet": {
                    "claude-sonnet-4-6": "anthropic/claude-sonnet-4-6",
                },
            }, template

    def test_anthropic_passthrough_opus_tier_is_4_8(self):
        """Passthrough forwards the client model unchanged; opus tier default is Opus 4.8 (no alternatives map)."""
        config = load_config(template="anthropic-passthrough")

        assert config.proxy.backend == "anthropic-passthrough"
        assert config.proxy.litellm.base_url == "https://api.anthropic.com"
        assert config.proxy.litellm.tiers.sonnet == "claude-sonnet-5"
        assert config.proxy.litellm.tiers.opus == "claude-opus-4-8"
        assert config.proxy.litellm.model_alternatives == {}

    def test_openrouter_config_placed_on_correct_field(self):
        """OpenRouter config should land on proxy.openrouter, not proxy.litellm."""
        config = load_config(template="openrouter-anthropic")

        assert config.proxy.openrouter.tiers.sonnet != ""
        assert config.proxy.litellm.tiers.sonnet == ""

    # NOTE: User config file support removed
    # Proxies own full config; no ~/.claude/forge.config.yaml


class TestTemplateFamilyMetadata:
    """Every shipped template must declare a model family."""

    TEMPLATE_DIR = Path("src/forge/config/defaults/templates")

    EXPECTED_FAMILIES = {
        "openrouter-anthropic": "anthropic",
        "openrouter-openai": "openai",
        "openrouter-openai-codex": "openai",
        "openrouter-gemini": "gemini",
        "openrouter-gemini-flash": "gemini",
        "openrouter-deepseek": "deepseek",
        "openrouter-kimi": "kimi",
        "openrouter-minimax": "minimax",
        "openrouter-qwen": "qwen",
        "openrouter-glm": "glm",
        "litellm-anthropic": "anthropic",
        "litellm-anthropic-local": "anthropic",
        "litellm-openai": "openai",
        "litellm-openai-local": "openai",
        "litellm-openai-codex-local": "openai",
        "litellm-gemini": "gemini",
        "litellm-gemini-local": "gemini",
        "litellm-gemini-flash-local": "gemini",
        "litellm-gemini-test": "gemini",
    }

    def _shipped_template_names(self) -> list[str]:
        return sorted(p.stem for p in self.TEMPLATE_DIR.glob("*.yaml"))

    def test_every_shipped_template_has_family(self):
        for name in self._shipped_template_names():
            config = load_config(template=name)
            assert config.proxy.family, f"Template '{name}' missing proxy.family"

    def test_template_families_match_expected(self):
        for name, expected_family in self.EXPECTED_FAMILIES.items():
            config = load_config(template=name)
            assert (
                config.proxy.family == expected_family
            ), f"Template '{name}': expected family '{expected_family}', got '{config.proxy.family}'"

    def test_family_propagates_through_proxy_instance(self, tmp_path, monkeypatch):
        """family round-trips through proxy.yaml creation and reload."""
        from forge.config.loader import (
            load_proxy_instance_config,
            write_proxy_instance_config,
        )
        from forge.config.schema import ProxyInstanceConfig, TierModels

        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        config = ProxyInstanceConfig(
            proxy_format=1,
            template="openrouter-openai",
            template_digest="sha256:test",
            provider="openrouter",
            proxy_endpoint="http://localhost:8096",
            port=8096,
            upstream_base_url="https://openrouter.ai/api/v1",
            tiers=TierModels(haiku="openai/gpt-5.4-mini", sonnet="openai/gpt-5.5", opus="openai/gpt-5.5"),
            family="openai",
        )

        write_proxy_instance_config("test-proxy", config)
        loaded = load_proxy_instance_config("test-proxy")
        assert loaded is not None
        assert loaded.family == "openai"

    def test_family_in_proxy_config_from_instance(self, tmp_path, monkeypatch):
        """family on ProxyInstanceConfig flows into ProxyConfig via loader."""
        from forge.config.loader import _proxy_instance_to_forge_config
        from forge.config.schema import ProxyInstanceConfig, TierModels

        config = ProxyInstanceConfig(
            proxy_format=1,
            template="openrouter-gemini",
            template_digest="sha256:test",
            provider="openrouter",
            backend="openrouter",
            proxy_endpoint="http://localhost:8097",
            port=8097,
            upstream_base_url="https://openrouter.ai/api/v1",
            tiers=TierModels(
                haiku="google/gemini-3-flash", sonnet="google/gemini-3.1-pro", opus="google/gemini-3.1-pro"
            ),
            family="gemini",
        )

        forge_config = _proxy_instance_to_forge_config(config)
        assert forge_config.proxy.family == "gemini"
        assert forge_config.proxy.backend == "openrouter"

    @pytest.fixture()
    def user_templates_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setenv("FORGE_HOME", str(tmp_path))
        tpl_dir = tmp_path / "templates"
        tpl_dir.mkdir()
        return tpl_dir

    def test_family_validation_rejects_numeric(self, user_templates_dir):
        """family: 123 is rejected (must be a non-blank string)."""
        bad = user_templates_dir / "bad-numeric.yaml"
        bad.write_text("proxy:\n  family: 123\n  preferred_provider: openrouter\n  default_port: 9999\n")
        with pytest.raises(ValueError, match="non-blank string"):
            load_config(template="bad-numeric")

    def test_family_validation_rejects_blank(self, user_templates_dir):
        """family: '   ' (whitespace-only) is rejected."""
        bad = user_templates_dir / "bad-blank.yaml"
        bad.write_text("proxy:\n  family: '   '\n  preferred_provider: openrouter\n  default_port: 9999\n")
        with pytest.raises(ValueError, match="non-blank string"):
            load_config(template="bad-blank")

    def test_family_validation_rejects_null_proxy(self, user_templates_dir):
        """proxy: null produces a clear error, not AttributeError."""
        bad = user_templates_dir / "bad-null.yaml"
        bad.write_text("proxy: null\n")
        with pytest.raises(ValueError, match="must have a 'proxy' mapping"):
            load_config(template="bad-null")

    def test_template_rejects_nonmapping_tier_overrides(self, user_templates_dir):
        """A malformed 'tier_overrides: []' template fails with ValueError, not AttributeError.

        Regression: the template path (load_config(template=...) -> dict_to_dataclass ->
        ProxyConfig.__post_init__) passed a raw list into _validate_static_tier_override_constraints,
        which did overrides.get(tier) -> AttributeError, escaping callers that guard on ValueError.
        """
        bad = user_templates_dir / "bad-overrides.yaml"
        bad.write_text(
            "proxy:\n"
            "  family: openai\n"
            "  backend: openrouter\n"
            "  default_port: 9911\n"
            "  openrouter:\n"
            "    tier_overrides: []\n"
        )
        with pytest.raises(ValueError, match="must be a mapping"):
            load_config(template="bad-overrides")

    def test_template_backend_validation_rejects_non_string(self, user_templates_dir):
        """proxy.backend must be a string before strict schema loading."""
        bad = user_templates_dir / "bad-backend-shape.yaml"
        bad.write_text(
            "proxy:\n"
            "  family: gemini\n"
            "  preferred_provider: litellm\n"
            "  backend:\n"
            "    id: litellm-gemini-local\n"
            "  default_port: 9999\n"
        )
        with pytest.raises(ValueError, match="proxy.backend"):
            load_config(template="bad-backend-shape")

    def test_template_backend_validation_rejects_unknown_backend(self, user_templates_dir):
        """proxy.backend must resolve to a backend instance id, alias, or unique kind."""
        bad = user_templates_dir / "bad-backend-unknown.yaml"
        bad.write_text(
            "proxy:\n"
            "  family: gemini\n"
            "  preferred_provider: litellm\n"
            "  backend: missing-backend\n"
            "  default_port: 9999\n"
        )
        with pytest.raises(ValueError, match="unknown proxy.backend"):
            load_config(template="bad-backend-unknown")

    def test_template_source_clean_break_rejects_old_field(self, user_templates_dir):
        """proxy.source fails loudly instead of silently aliasing the old template field."""
        bad = user_templates_dir / "old-source.yaml"
        bad.write_text("proxy:\n  family: gemini\n  preferred_provider: litellm\n  source: openrouter\n")
        with pytest.raises(ValueError, match="proxy.source is no longer supported"):
            load_config(template="old-source")

    def test_custom_template_without_backend_is_rejected(self, user_templates_dir):
        """Custom templates need proxy.backend."""
        bad = user_templates_dir / "custom-no-backend.yaml"
        bad.write_text("proxy:\n  family: gemini\n  preferred_provider: litellm\n  default_port: 9999\n")
        with pytest.raises(ValueError, match="must declare non-blank 'proxy.backend'"):
            load_config(template="custom-no-backend")

    def test_remote_source_rejects_inline_backend_dependency(self, user_templates_dir):
        """Remote sources cannot smuggle local lifecycle back into templates."""
        bad = user_templates_dir / "remote-with-backend.yaml"
        bad.write_text(
            "proxy:\n"
            "  family: openai\n"
            "  preferred_provider: openrouter\n"
            "  backend: openrouter\n"
            "  default_port: 9999\n"
            "  backend_dependency:\n"
            "    adapter: litellm\n"
            "    port: 4000\n"
        )
        with pytest.raises(ValueError, match="backend_dependency.*remote source"):
            load_config(template="remote-with-backend")

    def test_runtime_native_source_cannot_back_a_proxy(self, user_templates_dir):
        """A subscription source (runtime_native, e.g. chatgpt) cannot be a proxy template source.

        T2 non-goal: a key-authenticated proxy cannot carry a subscription whose auth
        is owned by a runtime, so the template must fail to load -- not mint a proxy
        for a backend Forge cannot dial.
        """
        bad = user_templates_dir / "custom-chatgpt.yaml"
        bad.write_text(
            "proxy:\n"
            "  family: openai\n"
            "  preferred_provider: litellm\n"
            "  backend: chatgpt\n"
            "  default_port: 9999\n"
        )
        with pytest.raises(ValueError, match="runtime-native source 'chatgpt'"):
            load_config(template="custom-chatgpt")

    def test_shipped_templates_declare_source_not_inline_lifecycle_or_base_url(self):
        """Shipped templates use source catalog ownership for lifecycle and remote endpoint facts."""
        for template in self._shipped_template_names():
            data = yaml.safe_load(read_shipped_template(template))
            proxy = data["proxy"]
            assert "backend" in proxy, template
            assert "source" not in proxy, template
            assert "backend_dependency" not in proxy, template
            if proxy["preferred_provider"] == "openrouter":
                assert "base_url" not in proxy["openrouter"], template
            if template == "anthropic-passthrough":
                assert "base_url" not in proxy["litellm"], template


class TestProxyFileIO:
    """Tests for proxy file I/O functions."""

    def test_get_proxy_file_path(self, tmp_path, monkeypatch):
        """get_proxy_file_path returns correct path."""
        from forge.config.loader import get_proxy_file_path

        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        path = get_proxy_file_path("test-proxy")

        assert path == tmp_path / "proxies" / "test-proxy" / "proxy.yaml"

    def test_write_and_load_proxy_instance_config(self, tmp_path, monkeypatch):
        """write_proxy_instance_config and load_proxy_instance_config round-trip correctly."""
        from forge.config.loader import (
            load_proxy_instance_config,
            write_proxy_instance_config,
        )
        from forge.config.schema import ProxyInstanceConfig, TierModels

        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        original = ProxyInstanceConfig(
            proxy_format=1,
            template="litellm-gemini",
            template_digest="sha256:abc123def456",
            provider="litellm",
            proxy_endpoint="http://localhost:8085",
            port=8085,
            upstream_base_url="https://litellm.test.example.com",
            tiers=TierModels(
                haiku="gemini/gemini-3-flash-preview",
                sonnet="gemini/gemini-3.1-pro-preview",
                opus="gemini/gemini-3.1-pro-preview",
            ),
            default_tier="opus",
            created_at="2025-01-04T12:00:00Z",
        )

        # Write
        path = write_proxy_instance_config("my-proxy", original)
        assert path.exists()

        # Load
        loaded = load_proxy_instance_config("my-proxy")
        assert loaded is not None
        assert loaded.proxy_format == 1
        assert loaded.template == "litellm-gemini"
        assert loaded.provider == "litellm"
        assert loaded.port == 8085
        assert loaded.tiers.haiku == "gemini/gemini-3-flash-preview"
        assert loaded.default_tier == "opus"

    def test_proxy_instance_config_writes_backend_not_source(self, tmp_path, monkeypatch):
        """proxy.yaml uses the canonical backend key."""
        from forge.config.loader import write_proxy_instance_config
        from forge.config.schema import ProxyInstanceConfig, TierModels

        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        config = ProxyInstanceConfig(
            proxy_format=1,
            template="openrouter-openai",
            template_digest="sha256:test",
            provider="openrouter",
            proxy_endpoint="http://localhost:8096",
            port=8096,
            upstream_base_url="https://openrouter.ai/api/v1",
            tiers=TierModels(haiku="h", sonnet="s", opus="o"),
            backend="openrouter",
        )

        path = write_proxy_instance_config("backend-key", config)
        data = yaml.safe_load(path.read_text())

        assert data["backend"] == "openrouter"
        assert "source" not in data

    def test_proxy_instance_config_round_trips_costs(self, tmp_path, monkeypatch):
        """Cost cap config survives write/load of proxy.yaml."""
        from forge.config.loader import (
            load_proxy_instance_config,
            write_proxy_instance_config,
        )
        from forge.config.schema import ProxyInstanceConfig, TierModels

        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        original = ProxyInstanceConfig(
            proxy_format=1,
            template="litellm-gemini",
            template_digest="sha256:abc123def456",
            provider="litellm",
            proxy_endpoint="http://localhost:8085",
            port=8085,
            upstream_base_url="https://litellm.test.example.com",
            tiers=TierModels(haiku="h", sonnet="s", opus="o"),
            costs={
                "caps": {"per_day": 20.0, "per_month": 100.0},
                "on_cap_hit": "warn",
            },
        )

        write_proxy_instance_config("cost-proxy", original)
        loaded = load_proxy_instance_config("cost-proxy")

        assert loaded is not None
        assert loaded.costs.caps.per_day == 20.0
        assert loaded.costs.caps.per_month == 100.0
        assert loaded.costs.on_cap_hit == "warn"

    def test_proxy_instance_config_round_trips_intercept_audit(self, tmp_path, monkeypatch):
        """wire_shape/intercept/audit survive write/load of proxy.yaml."""
        from forge.config.loader import (
            load_proxy_instance_config,
            write_proxy_instance_config,
        )
        from forge.config.schema import ProxyInstanceConfig, TierModels

        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        original = ProxyInstanceConfig(
            proxy_format=1,
            template="anthropic-passthrough",
            template_digest="sha256:abc",
            provider="litellm",
            proxy_endpoint="http://localhost:8096",
            port=8096,
            upstream_base_url="https://api.anthropic.com",
            tiers=TierModels(haiku="h", sonnet="s", opus="o"),
            wire_shape="anthropic_passthrough",
            intercept={"mode": "inspect"},
            audit={"audit_full_body": True, "retention_days": 30},
        )

        write_proxy_instance_config("audit-proxy", original)
        loaded = load_proxy_instance_config("audit-proxy")

        assert loaded is not None
        assert loaded.wire_shape == "anthropic_passthrough"
        assert loaded.intercept.mode == "inspect"
        assert loaded.audit.audit_full_body is True
        assert loaded.audit.retention_days == 30

    def test_proxy_instance_to_forge_config_propagates_intercept_audit(self):
        """wire_shape/intercept/audit reach the runtime ProxyConfig (propagation trap)."""
        from forge.config.loader import _proxy_instance_to_forge_config
        from forge.config.schema import ProxyInstanceConfig, TierModels

        config = ProxyInstanceConfig(
            proxy_format=1,
            template="anthropic-passthrough",
            template_digest="sha256:test",
            provider="litellm",
            proxy_endpoint="http://localhost:8096",
            port=8096,
            upstream_base_url="https://api.anthropic.com",
            tiers=TierModels(haiku="h", sonnet="s", opus="o"),
            wire_shape="anthropic_passthrough",
            intercept={"mode": "override", "override": {"system_prompt_augment": "Stay on task."}},
            audit={"audit_full_body": True},
        )

        forge_config = _proxy_instance_to_forge_config(config)

        assert forge_config.proxy.wire_shape == "anthropic_passthrough"
        assert forge_config.proxy.intercept.mode == "override"
        assert forge_config.proxy.intercept.override.system_prompt_augment == "Stay on task."
        assert forge_config.proxy.audit.audit_full_body is True

    def test_load_proxy_instance_config_not_found(self, tmp_path, monkeypatch):
        """load_proxy_instance_config returns None for missing file."""
        from forge.config.loader import load_proxy_instance_config

        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        result = load_proxy_instance_config("nonexistent")
        assert result is None

    def test_from_dict_normalizes_shape_errors_to_valueerror(self):
        """Malformed nested shape raises ValueError, not raw AttributeError/TypeError.

        Regression: proxy start / model-pin load guards catch (StateCorruptedError,
        ValueError). Before normalization, a shape like 'tiers: []' raised
        AttributeError from the raw .get() extraction and escaped those guards as a
        traceback. Shape failures are now converted at this single boundary.
        """
        from forge.config.loader import load_proxy_instance_config_from_dict

        base = {
            "template": "litellm-gemini",
            "provider": "litellm",
            "proxy_endpoint": "http://localhost:8084",
            "port": 8084,
            "upstream_base_url": "https://litellm.test.example.com",
            "tiers": {"haiku": "h", "sonnet": "s", "opus": "o"},
        }
        bad_shapes = [
            {**base, "tiers": []},  # non-mapping section (AttributeError)
            {**base, "tier_overrides": []},  # non-mapping section (AttributeError)
            {**base, "tier_overrides": {"haiku": "x"}},  # override not a mapping (TypeError from **)
            {**base, "tier_overrides": {"haiku": []}},  # falsy non-mapping must not be ignored
            {**base, "tier_overrides": {"haiku": False}},  # falsy non-mapping must not be ignored
            {**base, "tier_overrides": {"haiku": ""}},  # falsy non-mapping must not be ignored
            {**base, "tier_overrides": {"haiku": 0}},  # falsy non-mapping must not be ignored
            {**base, "tier_overrides": {"haiku": {"nope": 1}}},  # override unknown key (TypeError)
            [],  # top-level not a mapping (AttributeError)
        ]
        for data in bad_shapes:
            with pytest.raises(ValueError, match="Malformed proxy configuration"):
                load_proxy_instance_config_from_dict(data)

    def test_from_dict_allows_empty_or_null_tier_override_leaves(self):
        """Empty mapping/null tier override leaves mean no override; falsy non-mappings do not."""
        from forge.config.loader import load_proxy_instance_config_from_dict

        base = {
            "template": "litellm-gemini",
            "provider": "litellm",
            "proxy_endpoint": "http://localhost:8084",
            "port": 8084,
            "upstream_base_url": "https://litellm.test.example.com",
            "tiers": {"haiku": "h", "sonnet": "s", "opus": "o"},
        }
        for tier_overrides in ({}, {"haiku": None}, {"haiku": {}}):
            config = load_proxy_instance_config_from_dict({**base, "tier_overrides": tier_overrides})

            assert config.tier_overrides.haiku is None

    def test_from_dict_preserves_semantic_valueerror_verbatim(self):
        """A semantic violation keeps its own __post_init__ message, not the shape wrapper."""
        from forge.config.loader import load_proxy_instance_config_from_dict

        data = {
            "template": "litellm-gemini",
            "provider": "gemini",  # unsupported provider: semantic check in __post_init__
            "proxy_endpoint": "http://localhost:8084",
            "port": 8084,
            "upstream_base_url": "https://litellm.test.example.com",
            "tiers": {"haiku": "h", "sonnet": "s", "opus": "o"},
        }
        with pytest.raises(ValueError, match="Unsupported proxy provider"):
            load_proxy_instance_config_from_dict(data)

    def test_from_dict_rejects_old_source_field(self):
        """Old runtime proxy.source clean-breaks with a recreate tip."""
        from forge.config.loader import load_proxy_instance_config_from_dict

        data = {
            "template": "litellm-gemini",
            "provider": "litellm",
            "proxy_endpoint": "http://localhost:8084",
            "port": 8084,
            "upstream_base_url": "https://litellm.test.example.com",
            "tiers": {"haiku": "h", "sonnet": "s", "opus": "o"},
            "source": "litellm-remote",
        }

        with pytest.raises(ValueError, match="proxy.source is no longer supported"):
            load_proxy_instance_config_from_dict(data)

    def test_from_dict_accepts_unknown_backend_for_runtime_boundary(self):
        """Unknown proxy.backend is accepted here; the running proxy warns/degrades."""
        from forge.config.loader import load_proxy_instance_config_from_dict

        data = {
            "template": "litellm-gemini",
            "provider": "litellm",
            "proxy_endpoint": "http://localhost:8084",
            "port": 8084,
            "upstream_base_url": "https://litellm.test.example.com",
            "tiers": {"haiku": "h", "sonnet": "s", "opus": "o"},
            "backend": "no-such-backend",
        }

        config = load_proxy_instance_config_from_dict(data)

        assert config.backend == "no-such-backend"

    def test_write_proxy_instance_config_atomic_and_permissions(self, tmp_path, monkeypatch):
        """write_proxy_instance_config uses atomic write and sets 0600 permissions."""

        from forge.config.loader import write_proxy_instance_config
        from forge.config.schema import ProxyInstanceConfig, TierModels

        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        config = ProxyInstanceConfig(
            proxy_format=1,
            template="test",
            template_digest="sha256:test",
            provider="litellm",
            proxy_endpoint="http://localhost:8084",
            port=8084,
            upstream_base_url="https://litellm.test.example.com",
            tiers=TierModels(haiku="h", sonnet="s", opus="o"),
        )

        path = write_proxy_instance_config("test-proxy", config)

        # Check file exists
        assert path.exists()

        # Check permissions (0600 = owner read/write only)
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600

        # No temp file should remain
        tmp_file = path.with_suffix(".yaml.tmp")
        assert not tmp_file.exists()

    def test_compute_template_digest(self):
        """compute_template_digest returns SHA256 prefix for a real template."""
        from forge.config.loader import compute_template_digest

        digest = compute_template_digest("litellm-openai")

        assert digest.startswith("sha256:")
        assert len(digest) == 19  # "sha256:" + 12 hex chars


class TestLoadConfigWithProxy:
    """Tests for load_config() with proxy_id."""

    def test_load_config_with_proxy_id_reads_directly(self, tmp_path, monkeypatch):
        """When proxy_id provided and proxy.yaml exists, load directly."""
        from forge.config import load_config
        from forge.config.loader import write_proxy_instance_config
        from forge.config.schema import ProxyInstanceConfig, TierModels

        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        # Create proxy.yaml
        proxy_config = ProxyInstanceConfig(
            proxy_format=1,
            template="test-template",
            template_digest="sha256:test123",
            provider="litellm",
            proxy_endpoint="http://localhost:9999",
            port=9999,
            upstream_base_url="https://litellm.test.example.com",
            tiers=TierModels(
                haiku="test-haiku",
                sonnet="test-sonnet",
                opus="test-opus",
            ),
            default_tier="opus",
        )
        write_proxy_instance_config("my-proxy", proxy_config)

        # Load with proxy_id
        config = load_config(proxy_id="my-proxy")

        # Should use proxy config values
        assert config.proxy.default_port == 9999
        assert config.proxy.preferred_provider == "litellm"
        assert config.proxy.default_tier == "opus"
        assert config.proxy.litellm.tiers.haiku == "test-haiku"
        assert config.proxy.litellm.tiers.sonnet == "test-sonnet"
        assert config.proxy.litellm.tiers.opus == "test-opus"

    def test_load_config_with_proxy_id_applies_costs(self, tmp_path, monkeypatch):
        """Proxy-owned cost caps reach the runtime ProxyConfig."""
        from forge.config import load_config
        from forge.config.loader import write_proxy_instance_config
        from forge.config.schema import ProxyInstanceConfig, TierModels

        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        proxy_config = ProxyInstanceConfig(
            proxy_format=1,
            template="test-template",
            template_digest="sha256:test123",
            provider="litellm",
            proxy_endpoint="http://localhost:9999",
            port=9999,
            upstream_base_url="https://litellm.test.example.com",
            tiers=TierModels(haiku="test-haiku", sonnet="test-sonnet", opus="test-opus"),
            costs={
                "caps": {"per_day": "20.00", "per_month": "100.00"},
                "on_cap_hit": "warn",
            },
        )
        write_proxy_instance_config("cost-proxy", proxy_config)

        config = load_config(proxy_id="cost-proxy")

        assert config.proxy.costs.caps.per_day == 20.0
        assert config.proxy.costs.caps.per_month == 100.0
        assert config.proxy.costs.on_cap_hit == "warn"

    def test_load_config_with_nonexistent_lease_raises(self, tmp_path, monkeypatch):
        """Missing proxy_id raises ValueError (fail fast)."""
        from forge.config import load_config

        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        # Load with non-existent proxy_id - should raise ValueError
        with pytest.raises(ValueError, match="Proxy not found"):
            load_config(proxy_id="nonexistent")


class TestTemplateResolution:
    """Tests for user template overlay resolution."""

    @pytest.fixture
    def user_templates_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """Set up isolated FORGE_HOME with a user templates directory."""
        monkeypatch.setenv("FORGE_HOME", str(tmp_path))
        tpl_dir = tmp_path / "templates"
        tpl_dir.mkdir()
        return tpl_dir

    def test_list_includes_user_templates(self, user_templates_dir: Path) -> None:
        """User templates appear in list_template_names()."""
        (user_templates_dir / "my-custom.yaml").write_text("proxy:\n  default_port: 9999\n")
        names = list_template_names()
        assert "my-custom" in names

    def test_list_deduplicates_user_and_shipped(self, user_templates_dir: Path) -> None:
        """User override of shipped template appears once, not twice."""
        (user_templates_dir / "litellm-openai.yaml").write_text("proxy:\n  default_port: 9999\n")
        names = list_template_names()
        assert names.count("litellm-openai") == 1

    def test_template_exists_finds_user_template(self, user_templates_dir: Path) -> None:
        (user_templates_dir / "my-custom.yaml").write_text("proxy:\n  default_port: 9999\n")
        assert template_exists("my-custom")

    def test_read_template_prefers_user(self, user_templates_dir: Path) -> None:
        """User copy takes precedence over shipped template."""
        user_content = "# user override\nproxy:\n  default_port: 1111\n"
        (user_templates_dir / "litellm-openai.yaml").write_text(user_content)
        content = read_template("litellm-openai")
        assert "user override" in content

    def test_read_template_falls_back_to_shipped(self, user_templates_dir: Path) -> None:
        """Without user copy, shipped template is returned."""
        content = read_template("litellm-openai")
        assert "litellm" in content.lower()
        assert "user override" not in content

    def test_is_user_template(self, user_templates_dir: Path) -> None:
        (user_templates_dir / "litellm-openai.yaml").write_text("proxy: {}")
        assert is_user_template("litellm-openai")
        assert not is_user_template("litellm-gemini")

    def test_shipped_template_exists(self, user_templates_dir: Path) -> None:
        assert shipped_template_exists("litellm-openai")
        assert shipped_template_exists("openrouter-anthropic")
        assert not shipped_template_exists("nonexistent-xyz")

    def test_openrouter_templates_in_template_list(self, user_templates_dir: Path) -> None:
        """OpenRouter family templates appear in shipped template list."""
        names = list_template_names()
        assert "openrouter-anthropic" in names
        assert "openrouter-openai" in names
        assert "openrouter-gemini" in names
        assert "openrouter-openai-codex" in names
        assert "openrouter-gemini-flash" in names
        assert "openrouter-deepseek" in names
        assert "openrouter-kimi" in names
        assert "openrouter-glm" in names
        assert "openrouter-minimax" in names
        assert "openrouter-qwen" in names

    def test_openrouter_open_model_templates_load(self, user_templates_dir: Path) -> None:
        """OpenRouter open-model family templates load with expected tiers."""
        cases = {
            "openrouter-deepseek": (
                "deepseek/deepseek-v4-flash",
                "deepseek/deepseek-v4-pro",
                "deepseek/deepseek-v4-pro",
            ),
            "openrouter-qwen": ("qwen/qwen3.6-flash", "qwen/qwen3.6-plus", "qwen/qwen3.6-max-preview"),
            "openrouter-kimi": ("google/gemma-4-31b-it", "moonshotai/kimi-k2.6", "moonshotai/kimi-k2.6"),
            "openrouter-glm": ("z-ai/glm-4.7-flash", "z-ai/glm-5.2", "z-ai/glm-5.2"),
            "openrouter-minimax": ("google/gemma-4-31b-it", "minimax/minimax-m3", "minimax/minimax-m3"),
        }

        for template, (haiku, sonnet, opus) in cases.items():
            config = load_config(template=template)
            assert config.proxy.preferred_provider == "openrouter"
            assert config.proxy.openrouter.tiers.haiku == haiku
            assert config.proxy.openrouter.tiers.sonnet == sonnet
            assert config.proxy.openrouter.tiers.opus == opus

        qwen = load_config(template="openrouter-qwen")
        assert qwen.proxy.openrouter.model_alternatives == {
            "sonnet": {"qwen3-coder": "qwen/qwen3-coder"},
            "opus": {"qwen3-coder": "qwen/qwen3-coder"},
        }
        kimi = load_config(template="openrouter-kimi")
        assert kimi.proxy.openrouter.model_alternatives == {
            "sonnet": {"kimi-k2.5": "moonshotai/kimi-k2.5"},
            "opus": {"kimi-k2.5": "moonshotai/kimi-k2.5"},
        }
        minimax = load_config(template="openrouter-minimax")
        assert minimax.proxy.openrouter.model_alternatives == {
            "sonnet": {
                "minimax-m2.7": "minimax/minimax-m2.7",
                "minimax-m2.5": "minimax/minimax-m2.5",
            },
            "opus": {
                "minimax-m2.7": "minimax/minimax-m2.7",
                "minimax-m2.5": "minimax/minimax-m2.5",
            },
        }

    def test_read_shipped_template_ignores_user(self, user_templates_dir: Path) -> None:
        """read_shipped_template always returns the built-in content."""
        (user_templates_dir / "litellm-openai.yaml").write_text("# user override\n")
        content = read_shipped_template("litellm-openai")
        assert "user override" not in content
        assert "litellm" in content.lower()

    def test_get_user_template_path(self, user_templates_dir: Path) -> None:
        path = get_user_template_path("litellm-openai")
        assert path == user_templates_dir / "litellm-openai.yaml"

    def test_validate_template_name_rejects_path_traversal(self) -> None:
        with pytest.raises(ValueError):
            validate_template_name("../etc/passwd")
        with pytest.raises(ValueError):
            validate_template_name("foo/bar")
        with pytest.raises(ValueError):
            validate_template_name("")
        with pytest.raises(ValueError):
            validate_template_name(".hidden")

    def test_validate_template_name_accepts_valid(self) -> None:
        validate_template_name("litellm-openai")
        validate_template_name("my.template-v2")
        validate_template_name("A123")

    def test_list_handles_malformed_user_yaml(self, user_templates_dir: Path) -> None:
        """Malformed YAML in user templates dir doesn't crash listing."""
        (user_templates_dir / "bad.yaml").write_text("{{{{not yaml")
        names = list_template_names()
        assert "bad" in names
