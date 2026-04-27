"""Unit tests for sandbox secrets propagation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from forge.sidecar.secrets import TEMPLATE_SECRETS, get_secrets_for_template


@pytest.fixture
def creds_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point FORGE_HOME to tmp_path so credential file is isolated."""
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    return tmp_path / "credentials.yaml"


def _write_creds(path: Path, profile: str, secrets: dict[str, str]) -> None:
    """Write a minimal credentials file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": 1, "profiles": {profile: secrets}}
    with open(path, "w") as f:
        yaml.safe_dump(data, f)


class TestGetSecretsForTemplate:
    """Tests for get_secrets_for_template()."""

    def test_litellm_openai_returns_api_key_and_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LiteLLM OpenAI template returns LITELLM_API_KEY and LITELLM_BASE_URL."""
        monkeypatch.setenv("LITELLM_API_KEY", "sk-test-123")
        monkeypatch.setenv("LITELLM_BASE_URL", "https://litellm.corp.example.com")
        secrets = get_secrets_for_template("litellm-openai")
        assert secrets == {
            "LITELLM_API_KEY": "sk-test-123",
            "LITELLM_BASE_URL": "https://litellm.corp.example.com",
        }

    def test_litellm_gemini_returns_api_key_and_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LiteLLM Gemini template returns LITELLM_API_KEY and LITELLM_BASE_URL."""
        monkeypatch.setenv("LITELLM_API_KEY", "sk-gemini-456")
        monkeypatch.setenv("LITELLM_BASE_URL", "https://litellm.corp.example.com")
        secrets = get_secrets_for_template("litellm-gemini")
        assert secrets == {
            "LITELLM_API_KEY": "sk-gemini-456",
            "LITELLM_BASE_URL": "https://litellm.corp.example.com",
        }

    def test_unknown_template_returns_empty(self) -> None:
        """Unknown template returns empty dict."""
        secrets = get_secrets_for_template("unknown-template")
        assert secrets == {}

    def test_missing_secret_not_included(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing/unset secrets are not included in result."""
        monkeypatch.delenv("LITELLM_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
        secrets = get_secrets_for_template("litellm-openai")
        assert secrets == {}

    def test_empty_secret_not_included(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty string secrets are not included."""
        monkeypatch.setenv("LITELLM_API_KEY", "")
        monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
        secrets = get_secrets_for_template("litellm-openai")
        assert secrets == {}


class TestFileSecretsFallback:
    """Tests for credential file fallback in sidecar secret resolution."""

    def test_falls_back_to_credential_file(self, creds_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Secret resolves from credential file when env var is unset."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        _write_creds(creds_file, "default", {"GEMINI_API_KEY": "AIza-from-file"})

        secrets = get_secrets_for_template("litellm-gemini-local")
        assert secrets == {"GEMINI_API_KEY": "AIza-from-file"}

    def test_env_overrides_credential_file(self, creds_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Env var wins over credential file value."""
        monkeypatch.setenv("GEMINI_API_KEY", "AIza-from-env")
        _write_creds(creds_file, "default", {"GEMINI_API_KEY": "AIza-from-file"})

        secrets = get_secrets_for_template("litellm-gemini-local")
        assert secrets == {"GEMINI_API_KEY": "AIza-from-env"}

    def test_file_fallback_uses_active_profile(self, creds_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sidecar uses FORGE_PROFILE to pick the right profile."""
        monkeypatch.delenv("LITELLM_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
        monkeypatch.setenv("FORGE_PROFILE", "work")

        # Write key only in 'work' profile
        creds_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "profiles": {
                "default": {},
                "work": {"LITELLM_API_KEY": "sk-from-work-profile"},
            },
        }
        with open(creds_file, "w") as f:
            yaml.safe_dump(data, f)

        secrets = get_secrets_for_template("litellm-openai")
        assert secrets == {"LITELLM_API_KEY": "sk-from-work-profile"}

    def test_corrupt_file_returns_empty(self, creds_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Corrupt credential file doesn't crash sidecar -- returns empty."""
        monkeypatch.delenv("LITELLM_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
        creds_file.parent.mkdir(parents=True, exist_ok=True)
        creds_file.write_text("{corrupt yaml: [unterminated")

        secrets = get_secrets_for_template("litellm-openai")
        assert secrets == {}

    def test_missing_file_returns_empty(self, creds_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No credential file doesn't crash sidecar -- returns empty."""
        monkeypatch.delenv("LITELLM_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_BASE_URL", raising=False)

        secrets = get_secrets_for_template("litellm-openai")
        assert secrets == {}


class TestTemplateSecretsMapping:
    """Tests for the TEMPLATE_SECRETS mapping."""

    def test_litellm_remote_templates_require_api_key_and_base_url(self) -> None:
        """LiteLLM remote templates require LITELLM_API_KEY and LITELLM_BASE_URL."""
        for template in ("litellm-openai", "litellm-gemini", "litellm-anthropic"):
            assert "LITELLM_API_KEY" in TEMPLATE_SECRETS[template]
            assert "LITELLM_BASE_URL" in TEMPLATE_SECRETS[template]

    def test_local_litellm_uses_gemini_api_key(self) -> None:
        """Local LiteLLM (dev and test) uses personal GEMINI_API_KEY."""
        assert "GEMINI_API_KEY" in TEMPLATE_SECRETS["litellm-gemini-local"]
        assert "GEMINI_API_KEY" in TEMPLATE_SECRETS["litellm-gemini-test"]

    def test_local_gemini_flash_uses_gemini_api_key(self) -> None:
        """Local Gemini Flash uses personal GEMINI_API_KEY."""
        assert "GEMINI_API_KEY" in TEMPLATE_SECRETS["litellm-gemini-flash-local"]

    def test_local_openai_uses_openai_api_key(self) -> None:
        """Local OpenAI uses personal OPENAI_API_KEY."""
        assert "OPENAI_API_KEY" in TEMPLATE_SECRETS["litellm-openai-local"]

    def test_local_openai_codex_uses_openai_api_key(self) -> None:
        """Local OpenAI Codex uses personal OPENAI_API_KEY."""
        assert "OPENAI_API_KEY" in TEMPLATE_SECRETS["litellm-openai-codex-local"]

    def test_local_anthropic_uses_anthropic_api_key(self) -> None:
        """Local Anthropic uses personal ANTHROPIC_API_KEY."""
        assert "ANTHROPIC_API_KEY" in TEMPLATE_SECRETS["litellm-anthropic-local"]
