"""Tests for forge.core.auth.template_secrets module."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from forge.core.auth.template_secrets import (
    TEMPLATE_ENV_VARS,
    get_secrets_for_template,
    required_env_vars_for_template,
    resolve_env_or_credential,
    resolve_env_or_credential_with_source,
)


class TestTemplateSecrets:
    """Verify the template-to-secrets mapping."""

    def test_remote_templates_require_base_url(self) -> None:
        for name in ("litellm-openai", "litellm-gemini", "litellm-anthropic"):
            assert "LITELLM_BASE_URL" in TEMPLATE_ENV_VARS[name]
            assert "LITELLM_API_KEY" in TEMPLATE_ENV_VARS[name]

    def test_local_templates_require_provider_key(self) -> None:
        assert "GEMINI_API_KEY" in TEMPLATE_ENV_VARS["litellm-gemini-local"]
        assert "OPENAI_API_KEY" in TEMPLATE_ENV_VARS["litellm-openai-local"]

    def test_openrouter_templates_require_api_key(self) -> None:
        for name in (
            "openrouter-anthropic",
            "openrouter-openai",
            "openrouter-gemini",
            "openrouter-openai-codex",
            "openrouter-gemini-flash",
            "openrouter-deepseek",
            "openrouter-kimi",
            "openrouter-glm",
            "openrouter-minimax",
            "openrouter-qwen",
        ):
            assert "OPENROUTER_API_KEY" in TEMPLATE_ENV_VARS[name]


class TestRequiredEnvVarsForTemplate:
    """Resolve required env vars from a template's declared ``proxy.source``."""

    def _write_template(self, tmp_path, monkeypatch: pytest.MonkeyPatch, name: str, body: str) -> None:
        monkeypatch.setenv("FORGE_HOME", str(tmp_path))
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir(exist_ok=True)
        (templates_dir / f"{name}.yaml").write_text(body)

    def test_custom_template_resolves_declared_source(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        # A user-named template (absent from TEMPLATE_ENV_VARS) resolves via proxy.source.
        self._write_template(tmp_path, monkeypatch, "my-openrouter", "proxy:\n  source: openrouter\n")
        assert "OPENROUTER_API_KEY" in required_env_vars_for_template("my-openrouter")

    def test_template_without_source_falls_back(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        # No proxy.source and not in TEMPLATE_ENV_VARS -> empty (no credentials known).
        self._write_template(tmp_path, monkeypatch, "nosource", "proxy:\n  family: openai\n")
        assert required_env_vars_for_template("nosource") == []

    def test_unreadable_template_warns_and_falls_back(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # An existing-but-unreadable template must WARN (not silently skip preflight)
        # and still fall back to the shipped catalog map for a known template name.
        def boom(_name: str) -> str:
            raise PermissionError("denied")

        monkeypatch.setattr("forge.config.loader.read_template", boom)
        with caplog.at_level("WARNING"):
            result = required_env_vars_for_template("litellm-openai")

        assert result == TEMPLATE_ENV_VARS["litellm-openai"]
        assert any(r.levelname == "WARNING" and "Could not read template" in r.message for r in caplog.records)

    def test_invalid_yaml_warns_and_falls_back(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._write_template(tmp_path, monkeypatch, "broken", "proxy: [unclosed\n")
        with caplog.at_level("WARNING"):
            result = required_env_vars_for_template("broken")

        assert result == []  # not a shipped name, so the fallback map is empty
        assert any(r.levelname == "WARNING" and "not valid YAML" in r.message for r in caplog.records)

    def test_unknown_name_is_silent(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # A name that is neither shipped nor a user file is normal control flow:
        # FileNotFoundError -> silent None -> empty fallback, no warning noise.
        monkeypatch.setenv("FORGE_HOME", str(tmp_path))
        with caplog.at_level("WARNING"):
            assert required_env_vars_for_template("does-not-exist") == []
        assert not any(r.levelname == "WARNING" for r in caplog.records)


class TestResolveEnvOrCredential:
    """Verify env > credential-file fallback."""

    def test_env_wins_over_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_KEY", "from-env")
        with patch(
            "forge.core.auth.template_secrets._get_file_secrets",
            return_value={"MY_KEY": "from-file"},
        ):
            assert resolve_env_or_credential("MY_KEY") == "from-env"

    def test_file_fallback_when_env_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MY_KEY", raising=False)
        with patch(
            "forge.core.auth.template_secrets._get_file_secrets",
            return_value={"MY_KEY": "from-file"},
        ):
            assert resolve_env_or_credential("MY_KEY") == "from-file"

    def test_returns_none_when_both_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MY_KEY", raising=False)
        with patch(
            "forge.core.auth.template_secrets._get_file_secrets",
            return_value={},
        ):
            assert resolve_env_or_credential("MY_KEY") is None

    def test_file_load_failure_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MY_KEY", raising=False)
        with patch(
            "forge.core.auth.template_secrets._get_file_secrets",
            return_value={},
        ):
            assert resolve_env_or_credential("MY_KEY") is None

    def test_empty_env_value_falls_through_to_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_KEY", "")
        with patch(
            "forge.core.auth.template_secrets._get_file_secrets",
            return_value={"MY_KEY": "from-file"},
        ):
            assert resolve_env_or_credential("MY_KEY") == "from-file"


class TestResolveEnvOrCredentialWithSource:
    """The source breadcrumb must name where the value actually came from."""

    def test_env_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_KEY", "from-env")
        with patch(
            "forge.core.auth.template_secrets._get_file_secrets",
            return_value={"MY_KEY": "from-file"},
        ):
            assert resolve_env_or_credential_with_source("MY_KEY") == ("from-env", "env")

    def test_credential_file_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MY_KEY", raising=False)
        with patch(
            "forge.core.auth.template_secrets._get_file_secrets",
            return_value={"MY_KEY": "from-file"},
        ):
            assert resolve_env_or_credential_with_source("MY_KEY") == ("from-file", "credential_file")

    def test_none_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MY_KEY", raising=False)
        with patch("forge.core.auth.template_secrets._get_file_secrets", return_value={}):
            assert resolve_env_or_credential_with_source("MY_KEY") == (None, "none")

    def test_ignore_env_reports_credential_file_not_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Shell key present, file key present, auth_ignore_env active: the child uses
        # the FILE key, so the source must be credential_file (the review-2 trap).
        monkeypatch.setattr("forge.core.auth.template_secrets._auth_ignore_env", lambda: True)
        monkeypatch.setenv("MY_KEY", "from-env")
        with patch(
            "forge.core.auth.template_secrets._get_file_secrets",
            return_value={"MY_KEY": "from-file"},
        ):
            assert resolve_env_or_credential_with_source("MY_KEY") == ("from-file", "credential_file")


class TestGetSecretsForTemplate:
    """Verify template-scoped secret resolution."""

    def test_unknown_template_returns_empty(self) -> None:
        assert get_secrets_for_template("unknown-template") == {}

    def test_resolves_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "gkey")
        result = get_secrets_for_template("litellm-gemini-local")
        assert result == {"GEMINI_API_KEY": "gkey"}

    def test_resolves_from_credential_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with patch(
            "forge.core.auth.template_secrets._get_file_secrets",
            return_value={"GEMINI_API_KEY": "file-gkey"},
        ):
            result = get_secrets_for_template("litellm-gemini-local")
            assert result == {"GEMINI_API_KEY": "file-gkey"}


class TestAuthIgnoreEnv:
    """Verify auth_ignore_env bypasses environment variables."""

    def _set_ignore_env(self, monkeypatch: pytest.MonkeyPatch, value: bool) -> None:
        monkeypatch.setattr(
            "forge.core.auth.template_secrets._auth_ignore_env",
            lambda: value,
        )

    def test_resolve_skips_env_when_ignore_active(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._set_ignore_env(monkeypatch, True)
        monkeypatch.setenv("MY_KEY", "from-env")
        with patch(
            "forge.core.auth.template_secrets._get_file_secrets",
            return_value={"MY_KEY": "from-file"},
        ):
            assert resolve_env_or_credential("MY_KEY") == "from-file"

    def test_resolve_reads_env_when_ignore_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._set_ignore_env(monkeypatch, False)
        monkeypatch.setenv("MY_KEY", "from-env")
        with patch(
            "forge.core.auth.template_secrets._get_file_secrets",
            return_value={"MY_KEY": "from-file"},
        ):
            assert resolve_env_or_credential("MY_KEY") == "from-env"

    def test_resolve_returns_none_when_ignore_and_no_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._set_ignore_env(monkeypatch, True)
        monkeypatch.setenv("MY_KEY", "from-env")
        with patch(
            "forge.core.auth.template_secrets._get_file_secrets",
            return_value={},
        ):
            assert resolve_env_or_credential("MY_KEY") is None

    def test_get_secrets_skips_env_when_ignore_active(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._set_ignore_env(monkeypatch, True)
        monkeypatch.setenv("GEMINI_API_KEY", "env-key")
        with patch(
            "forge.core.auth.template_secrets._get_file_secrets",
            return_value={"GEMINI_API_KEY": "file-key"},
        ):
            result = get_secrets_for_template("litellm-gemini-local")
            assert result == {"GEMINI_API_KEY": "file-key"}

    def test_get_secrets_reads_env_when_ignore_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._set_ignore_env(monkeypatch, False)
        monkeypatch.setenv("GEMINI_API_KEY", "env-key")
        result = get_secrets_for_template("litellm-gemini-local")
        assert result == {"GEMINI_API_KEY": "env-key"}
