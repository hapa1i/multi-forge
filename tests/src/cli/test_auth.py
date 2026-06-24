"""Tests for CLI auth commands."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from forge.cli.auth import _mask_value
from forge.cli.main import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def creds_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point FORGE_HOME to tmp_path so credentials go to a temp file."""
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    return tmp_path / "credentials.yaml"


# --- Helpers ---


class TestHelpers:

    def test_mask_value_long(self) -> None:
        assert _mask_value("sk-ant-1234567890") == "sk-a…7890"

    def test_mask_value_short(self) -> None:
        assert _mask_value("short") == "****"


# --- Login ---


class TestAuthLogin:

    def test_login_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["auth", "login", "--help"])
        assert result.exit_code == 0
        assert "--credential" in result.output
        assert "--profile" in result.output

    def test_login_stores_credential(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Login prompts and stores value in credentials file."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        result = runner.invoke(
            main,
            ["auth", "login", "-c", "anthropic-api"],
            input="sk-ant-test-12345\n",
        )

        assert result.exit_code == 0
        assert "Credentials saved" in result.output

        with open(creds_file) as f:
            data = yaml.safe_load(f)
        assert data["profiles"]["default"]["ANTHROPIC_API_KEY"] == "sk-ant-test-12345"

    def test_login_keeps_existing_on_empty_input(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pressing Enter keeps the existing value."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        from forge.core.auth.credentials_file import save_profile

        save_profile("default", {"ANTHROPIC_API_KEY": "sk-ant-existing"}, path=creds_file)

        result = runner.invoke(
            main,
            ["auth", "login", "-c", "anthropic-api"],
            input="\n",
        )

        assert result.exit_code == 0

        with open(creds_file) as f:
            data = yaml.safe_load(f)
        assert data["profiles"]["default"]["ANTHROPIC_API_KEY"] == "sk-ant-existing"

    def test_login_with_named_profile(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        result = runner.invoke(
            main,
            ["auth", "login", "-c", "anthropic-api", "--profile", "work"],
            input="sk-ant-work-key\n",
        )

        assert result.exit_code == 0
        assert "work" in result.output

        with open(creds_file) as f:
            data = yaml.safe_load(f)
        assert data["profiles"]["work"]["ANTHROPIC_API_KEY"] == "sk-ant-work-key"

    def test_login_no_input_no_existing(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty input with no existing value -> nothing saved."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        result = runner.invoke(
            main,
            ["auth", "login", "-c", "anthropic-api"],
            input="\n",
        )

        assert result.exit_code == 0
        assert "No credentials to save" in result.output

    def test_login_recovers_from_corrupt_file(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Login self-heals when credentials file is corrupt YAML."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        creds_file.parent.mkdir(parents=True, exist_ok=True)
        creds_file.write_text("{corrupt yaml: [unterminated")

        result = runner.invoke(
            main,
            ["auth", "login", "-c", "anthropic-api"],
            input="sk-ant-recovery-key\n",
        )

        assert result.exit_code == 0
        assert "corrupt" in result.output.lower()
        assert "Credentials saved" in result.output

        with open(creds_file) as f:
            data = yaml.safe_load(f)
        assert data["profiles"]["default"]["ANTHROPIC_API_KEY"] == "sk-ant-recovery-key"

    def test_login_blocks_on_version_mismatch(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Login refuses to overwrite a future-version credential file."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        creds_file.parent.mkdir(parents=True, exist_ok=True)
        creds_file.write_text(yaml.dump({"version": 99, "profiles": {"default": {"KEY": "precious"}}}))

        result = runner.invoke(
            main,
            ["auth", "login", "-c", "anthropic-api"],
            input="sk-ant-new-key\n",
        )

        assert result.exit_code != 0
        assert "version 99" in result.output

        raw = yaml.safe_load(creds_file.read_text())
        assert raw["version"] == 99


class TestRetiredNames:

    def test_login_retired_anthropic(self, runner: CliRunner) -> None:
        """Old 'anthropic' name produces migration guidance, not silent accept."""
        result = runner.invoke(main, ["auth", "login", "-c", "anthropic"])
        assert result.exit_code != 0
        assert "anthropic-api" in result.output

    def test_login_retired_litellm_local(self, runner: CliRunner) -> None:
        """Old 'litellm-local' name explains it's not a credential."""
        result = runner.invoke(main, ["auth", "login", "-c", "litellm-local"])
        assert result.exit_code != 0
        assert "not a credential" in result.output
        assert "gemini-api" in result.output

    def test_login_unknown_credential(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["auth", "login", "-c", "bogus"])
        assert result.exit_code != 0
        assert "Unknown credential" in result.output


class TestCredentialMenu:

    def test_menu_shown_without_credential_flag(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without -c, shows numbered menu then prompts for selected credentials."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        # Select credential 2 (anthropic-api), then provide the key
        result = runner.invoke(
            main,
            ["auth", "login"],
            input="2\nsk-ant-menu-test\n",
        )

        assert result.exit_code == 0
        assert "anthropic-api" in result.output
        assert "Forge credentials" in result.output

    def test_menu_all_default(self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pressing Enter at the menu (default 'all') prompts for all credentials."""
        for key in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "LITELLM_API_KEY"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
        monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)

        # All credentials: Enter for menu default, then empty inputs for each
        result = runner.invoke(
            main,
            ["auth", "login"],
            input="\n" + "\n" * 10,  # all + skip everything
        )

        assert result.exit_code == 0
        assert "openrouter" in result.output
        assert "anthropic-api" in result.output

    def test_env_aware_skip(self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When env var is set, prompt shows 'already set via environment variable'."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-from-env")

        result = runner.invoke(
            main,
            ["auth", "login", "-c", "openrouter"],
            input="\n\n",  # skip both vars
        )

        assert result.exit_code == 0
        assert "already set via environment variable" in result.output

    def test_env_ignored_prompt(self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """With auth_ignore_env, login explains env var is ignored and prompts for file value."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-value")
        monkeypatch.setattr(
            "forge.cli.auth._get_auth_ignore_env",
            lambda: True,
        )

        result = runner.invoke(
            main,
            ["auth", "login", "-c", "anthropic-api"],
            input="sk-ant-file-value\n",
        )

        assert result.exit_code == 0
        assert "auth_ignore_env" in result.output
        assert "Credentials saved" in result.output


# --- Status ---


class TestAuthStatus:

    def test_status_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["auth", "status", "--help"])
        assert result.exit_code == 0
        assert "--profile" in result.output

    def test_status_shows_env_source(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")

        result = runner.invoke(main, ["auth", "status"])

        assert result.exit_code == 0
        assert "ANTHROPIC_API_KEY" in result.output
        assert "(env)" in result.output

    def test_status_shows_file_source_with_profile(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        from forge.core.auth.credentials_file import save_profile

        save_profile("default", {"ANTHROPIC_API_KEY": "sk-ant-from-file"}, path=creds_file)

        result = runner.invoke(main, ["auth", "status"])

        assert result.exit_code == 0
        assert "ANTHROPIC_API_KEY" in result.output
        assert "(file:default)" in result.output

    def test_status_shows_not_configured(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        result = runner.invoke(main, ["auth", "status"])

        assert result.exit_code == 0
        assert "not configured" in result.output
        # Never shows "MISSING" — neutral language
        assert "MISSING" not in result.output

    def test_status_dual_view(self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Status shows both capability summary and credential details sections."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

        result = runner.invoke(main, ["auth", "status"])

        assert result.exit_code == 0
        assert "Configured capabilities:" in result.output
        assert "Credential details:" in result.output
        assert "Not configured (set up if needed):" in result.output

    def test_status_masks_values(self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Values are masked in status output -- never shown in full."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-super-secret-key-12345")

        result = runner.invoke(main, ["auth", "status"])

        assert "sk-ant-super-secret-key-12345" not in result.output
        assert "sk-a" in result.output
        assert "2345" in result.output

    def test_status_with_profile(self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LITELLM_API_KEY", raising=False)

        from forge.core.auth.credentials_file import save_profile

        save_profile("work", {"LITELLM_API_KEY": "sk-litellm-work"}, path=creds_file)

        result = runner.invoke(main, ["auth", "status", "--profile", "work"])

        assert result.exit_code == 0
        assert "(file:work)" in result.output

    def test_status_survives_corrupt_file(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Status degrades gracefully when credentials file is corrupt."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        creds_file.parent.mkdir(parents=True, exist_ok=True)
        creds_file.write_text("{corrupt yaml: [unterminated")

        result = runner.invoke(main, ["auth", "status"])

        assert result.exit_code == 0
        assert "corrupt" in result.output.lower()
        assert "not configured" in result.output

    def test_status_blocks_on_version_mismatch(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Status refuses to proceed with a future-version credential file."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        creds_file.parent.mkdir(parents=True, exist_ok=True)
        creds_file.write_text(yaml.dump({"version": 99, "profiles": {}}))

        result = runner.invoke(main, ["auth", "status"])

        assert result.exit_code != 0
        assert "version 99" in result.output

    def test_status_env_ignored(self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """With auth_ignore_env, env vars show as 'env ignored' in status."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-value")
        monkeypatch.setattr(
            "forge.cli.auth._get_auth_ignore_env",
            lambda: True,
        )

        result = runner.invoke(main, ["auth", "status"])

        assert result.exit_code == 0
        assert "env ignored" in result.output

    def test_status_default_value_shown(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OPENROUTER_BASE_URL shows default value when not configured."""
        monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        result = runner.invoke(main, ["auth", "status"])

        assert result.exit_code == 0
        assert "openrouter.ai/api/v1" in result.output
        assert "(default)" in result.output


# --- Status --json ---


# Keys the status JSON payload must clear so leaked env values don't masquerade
# as test setup. Mirrors the credential catalog's secret + connection vars.
_ALL_AUTH_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "CODEX_API_KEY",
    "LITELLM_API_KEY",
    "LITELLM_BASE_URL",
)


def _clear_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop every credential env var so only test-set values appear."""
    for key in _ALL_AUTH_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


class TestAuthStatusJson:

    def _find_cred(self, payload: dict, name: str) -> dict:
        for cred in payload["credentials"]:
            if cred["name"] == name:
                return cred
        raise AssertionError(f"credential {name!r} not in payload")

    def _find_env_var(self, cred: dict, name: str) -> dict:
        for ev in cred["env_vars"]:
            if ev["name"] == name:
                return ev
        raise AssertionError(f"env var {name!r} not in credential {cred['name']!r}")

    def test_status_json_shape_not_configured(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty/not-configured payload has the documented top-level + per-cred keys."""
        import json

        _clear_auth_env(monkeypatch)

        result = runner.invoke(main, ["auth", "status", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)

        assert set(payload.keys()) == {"profile", "credentials", "warning"}
        assert payload["profile"] == "default"
        assert payload["warning"] is None  # clean file -> no degradation warning
        assert isinstance(payload["credentials"], list)
        assert payload["credentials"]  # catalog is non-empty

        for cred in payload["credentials"]:
            assert set(cred.keys()) == {
                "name",
                "summary",
                "configured",
                "state",
                "primary_source",
                "env_vars",
            }
            assert cred["configured"] is False
            assert cred["primary_source"] is None  # not configured -> no source label
            assert isinstance(cred["env_vars"], list)
            for ev in cred["env_vars"]:
                assert set(ev.keys()) == {
                    "name",
                    "configured",
                    "source",
                    "is_secret",
                    "is_default",
                    "value",
                }

    def test_status_json_no_plaintext_secret_in_payload(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SECURITY: a real secret value must never appear in the JSON payload.

        Every env_var flagged is_secret==True must report value==None, regardless
        of whether the secret resolves from env or the credentials file. The raw
        secret string must not appear anywhere in the serialized output.
        """
        import json

        _clear_auth_env(monkeypatch)

        # A secret env var (ANTHROPIC_API_KEY, secret=True) with a real value set,
        # plus a file-sourced secret to cover both resolution paths.
        env_secret = "sk-ant-env-PLAINTEXT-SECRET-9999"
        file_secret = "sk-or-file-PLAINTEXT-SECRET-8888"
        monkeypatch.setenv("ANTHROPIC_API_KEY", env_secret)

        from forge.core.auth.credentials_file import save_profile

        save_profile("default", {"OPENROUTER_API_KEY": file_secret}, path=creds_file)

        result = runner.invoke(main, ["auth", "status", "--json"])

        assert result.exit_code == 0

        # The raw secrets must not appear anywhere in the serialized output.
        assert env_secret not in result.output
        assert file_secret not in result.output

        payload = json.loads(result.output)

        # Airtight: across ALL credentials, every secret env var has value None.
        secret_vars_seen = 0
        for cred in payload["credentials"]:
            for ev in cred["env_vars"]:
                if ev["is_secret"]:
                    secret_vars_seen += 1
                    assert ev["value"] is None, f"plaintext secret leaked for {ev['name']}: {ev['value']!r}"
        assert secret_vars_seen > 0  # at least one secret var exercised

        # The env secret resolved (configured True, sourced from env) but value hidden.
        anthropic = self._find_cred(payload, "anthropic-api")
        api_key = self._find_env_var(anthropic, "ANTHROPIC_API_KEY")
        assert api_key["is_secret"] is True
        assert api_key["configured"] is True
        assert api_key["source"] == "env"
        assert api_key["value"] is None

        # The file secret resolved (configured True, file-sourced) but value hidden.
        openrouter = self._find_cred(payload, "openrouter")
        or_key = self._find_env_var(openrouter, "OPENROUTER_API_KEY")
        assert or_key["is_secret"] is True
        assert or_key["configured"] is True
        assert or_key["source"] == "file:default"
        assert or_key["value"] is None

    def test_status_json_non_secret_value_exposed(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A non-secret connection value (is_secret False) is returned in plaintext."""
        import json

        _clear_auth_env(monkeypatch)

        base_url = "https://litellm.example.com"
        from forge.core.auth.credentials_file import save_profile

        save_profile(
            "default",
            {"LITELLM_API_KEY": "sk-litellm-secret", "LITELLM_BASE_URL": base_url},
            path=creds_file,
        )

        result = runner.invoke(main, ["auth", "status", "--json"])

        assert result.exit_code == 0
        # The secret key must still be hidden even though the base url is shown.
        assert "sk-litellm-secret" not in result.output

        payload = json.loads(result.output)
        litellm = self._find_cred(payload, "litellm-remote")

        url_var = self._find_env_var(litellm, "LITELLM_BASE_URL")
        assert url_var["is_secret"] is False
        assert url_var["configured"] is True
        assert url_var["value"] == base_url

        key_var = self._find_env_var(litellm, "LITELLM_API_KEY")
        assert key_var["is_secret"] is True
        assert key_var["value"] is None

    def test_status_json_default_value_flagged(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unset var with a default value is reported with is_default True."""
        import json

        _clear_auth_env(monkeypatch)

        result = runner.invoke(main, ["auth", "status", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        openrouter = self._find_cred(payload, "openrouter")
        base_url = self._find_env_var(openrouter, "OPENROUTER_BASE_URL")

        assert base_url["is_default"] is True
        assert base_url["configured"] is False
        assert base_url["source"] == "not configured"

    def test_status_json_primary_source_populated(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A configured credential reports the source extracted into primary_source."""
        import json

        _clear_auth_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")

        result = runner.invoke(main, ["auth", "status", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        anthropic = self._find_cred(payload, "anthropic-api")

        assert anthropic["configured"] is True
        assert anthropic["state"] == "configured (env)"
        assert anthropic["primary_source"] == "env"

    def test_status_json_with_profile(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--profile is reflected in the payload and file source labels."""
        import json

        _clear_auth_env(monkeypatch)
        from forge.core.auth.credentials_file import save_profile

        save_profile("work", {"LITELLM_API_KEY": "sk-litellm-work"}, path=creds_file)

        result = runner.invoke(main, ["auth", "status", "--profile", "work", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["profile"] == "work"

        litellm = self._find_cred(payload, "litellm-remote")
        key_var = self._find_env_var(litellm, "LITELLM_API_KEY")
        assert key_var["configured"] is True
        assert key_var["source"] == "file:work"
        assert key_var["value"] is None  # still secret

    def test_status_json_env_ignored_secret_stays_hidden(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With auth_ignore_env, env secret is ignored AND never leaks into JSON."""
        import json

        _clear_auth_env(monkeypatch)
        env_secret = "sk-ant-env-IGNORED-SECRET"
        monkeypatch.setenv("ANTHROPIC_API_KEY", env_secret)
        monkeypatch.setattr("forge.cli.auth._get_auth_ignore_env", lambda: True)

        result = runner.invoke(main, ["auth", "status", "--json"])

        assert result.exit_code == 0
        assert env_secret not in result.output

        payload = json.loads(result.output)
        anthropic = self._find_cred(payload, "anthropic-api")
        api_key = self._find_env_var(anthropic, "ANTHROPIC_API_KEY")

        assert api_key["configured"] is False
        assert api_key["source"] == "not configured (env ignored)"
        assert api_key["value"] is None

    def test_status_json_blocks_on_version_mismatch(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A future-version file yields an {error} JSON object and exit code 1."""
        import json

        _clear_auth_env(monkeypatch)
        creds_file.parent.mkdir(parents=True, exist_ok=True)
        creds_file.write_text(yaml.dump({"version": 99, "profiles": {}}))

        result = runner.invoke(main, ["auth", "status", "--json"])

        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert set(payload.keys()) == {"error"}
        assert "version 99" in payload["error"]

    def test_status_json_warns_on_corrupt_file(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A corrupt file degrades to env-only values but is NOT silent (warning surfaced).

        Mirrors the human path's '⚠︎ Credentials file is corrupt' notice. Unlike a
        version mismatch (which fails loud, exit 1), a parse error is recoverable: the
        payload still lists credentials, env-resolved secrets still apply, and the
        always-present `warning` key carries the degradation message.
        """
        import json

        _clear_auth_env(monkeypatch)
        env_secret = "sk-ant-env-DEGRADE-SECRET"
        monkeypatch.setenv("ANTHROPIC_API_KEY", env_secret)

        creds_file.parent.mkdir(parents=True, exist_ok=True)
        creds_file.write_text("{corrupt yaml: [unterminated")

        result = runner.invoke(main, ["auth", "status", "--json"])

        assert result.exit_code == 0  # recoverable: degrade, don't fail
        assert env_secret not in result.output  # secret still never leaks
        payload = json.loads(result.output)

        assert payload["warning"] is not None
        assert "corrupt" in payload["warning"].lower()
        assert payload["credentials"]  # degraded, not empty

        # Env-resolved secret still applies (degrade != fail) and stays redacted.
        anthropic = self._find_cred(payload, "anthropic-api")
        api_key = self._find_env_var(anthropic, "ANTHROPIC_API_KEY")
        assert api_key["configured"] is True
        assert api_key["source"] == "env"
        assert api_key["value"] is None


# --- Logout ---


class TestAuthLogout:

    def test_logout_removes_profile(self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from forge.core.auth.credentials_file import save_profile

        save_profile("default", {"KEY": "val"}, path=creds_file)

        result = runner.invoke(main, ["auth", "logout", "-y"])

        assert result.exit_code == 0
        assert "Removed" in result.output

    def test_logout_nonexistent_profile(self, runner: CliRunner, creds_file: Path) -> None:
        result = runner.invoke(main, ["auth", "logout", "-y"])

        assert result.exit_code == 0
        assert "not found" in result.output

    def test_logout_confirm_abort(self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from forge.core.auth.credentials_file import save_profile

        save_profile("default", {"KEY": "val"}, path=creds_file)

        result = runner.invoke(main, ["auth", "logout"], input="n\n")

        assert result.exit_code == 0
        assert "Aborted" in result.output

        with open(creds_file) as f:
            data = yaml.safe_load(f)
        assert "default" in data["profiles"]

    def test_logout_with_profile(self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from forge.core.auth.credentials_file import save_profile

        save_profile("work", {"KEY": "val"}, path=creds_file)
        save_profile("default", {"KEY": "val"}, path=creds_file)

        result = runner.invoke(main, ["auth", "logout", "--profile", "work", "-y"])

        assert result.exit_code == 0
        assert "Removed" in result.output
        assert "work" in result.output

        with open(creds_file) as f:
            data = yaml.safe_load(f)
        assert "default" in data["profiles"]
        assert "work" not in data["profiles"]


# --- Profiles ---


class TestAuthProfiles:

    def test_profiles_empty(self, runner: CliRunner, creds_file: Path) -> None:
        result = runner.invoke(main, ["auth", "profiles"])
        assert result.exit_code == 0
        assert "No profiles found" in result.output

    def test_profiles_lists_saved(self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from forge.core.auth.credentials_file import save_profile

        save_profile("default", {"KEY_A": "a", "KEY_B": "b"}, path=creds_file)
        save_profile("work", {"KEY_C": "c"}, path=creds_file)

        result = runner.invoke(main, ["auth", "profiles"])

        assert result.exit_code == 0
        assert "default (2 keys)" in result.output
        assert "work (1 keys)" in result.output

    def test_profiles_marks_active(self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FORGE_PROFILE", raising=False)

        from forge.core.auth.credentials_file import save_profile

        save_profile("default", {"KEY": "val"}, path=creds_file)
        save_profile("work", {"KEY": "val"}, path=creds_file)

        result = runner.invoke(main, ["auth", "profiles"])

        assert "← active" in result.output
        lines = result.output.strip().split("\n")
        active_lines = [line for line in lines if "← active" in line]
        assert len(active_lines) == 1
        assert "default" in active_lines[0]

    def test_profiles_active_from_env(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FORGE_PROFILE", "work")

        from forge.core.auth.credentials_file import save_profile

        save_profile("default", {"KEY": "val"}, path=creds_file)
        save_profile("work", {"KEY": "val"}, path=creds_file)

        result = runner.invoke(main, ["auth", "profiles"])

        lines = result.output.strip().split("\n")
        active_lines = [line for line in lines if "← active" in line]
        assert len(active_lines) == 1
        assert "work" in active_lines[0]


# --- Profiles --json ---


class TestAuthProfilesJson:

    def test_profiles_json_empty(self, runner: CliRunner, creds_file: Path) -> None:
        """No saved profiles -> {profiles: []} with exit code 0."""
        import json

        result = runner.invoke(main, ["auth", "profiles", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload == {"profiles": []}

    def test_profiles_json_populated_shape(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each profile entry has name/key_count/is_active with correct values."""
        import json

        monkeypatch.delenv("FORGE_PROFILE", raising=False)
        from forge.core.auth.credentials_file import save_profile

        save_profile("default", {"KEY_A": "a", "KEY_B": "b"}, path=creds_file)
        save_profile("work", {"KEY_C": "c"}, path=creds_file)

        result = runner.invoke(main, ["auth", "profiles", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert set(payload.keys()) == {"profiles"}

        by_name = {p["name"]: p for p in payload["profiles"]}
        assert set(by_name) == {"default", "work"}
        for entry in payload["profiles"]:
            assert set(entry.keys()) == {"name", "key_count", "is_active"}

        assert by_name["default"]["key_count"] == 2
        assert by_name["work"]["key_count"] == 1

        # Exactly one active profile; 'default' is active without FORGE_PROFILE set.
        active = [p["name"] for p in payload["profiles"] if p["is_active"]]
        assert active == ["default"]

    def test_profiles_json_active_from_env(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FORGE_PROFILE selects which profile is_active in the payload."""
        import json

        monkeypatch.setenv("FORGE_PROFILE", "work")
        from forge.core.auth.credentials_file import save_profile

        save_profile("default", {"KEY": "val"}, path=creds_file)
        save_profile("work", {"KEY": "val"}, path=creds_file)

        result = runner.invoke(main, ["auth", "profiles", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        active = [p["name"] for p in payload["profiles"] if p["is_active"]]
        assert active == ["work"]

    def test_profiles_json_blocks_on_version_mismatch(self, runner: CliRunner, creds_file: Path) -> None:
        """A future-version file yields an {error} JSON object and exit code 1."""
        import json

        creds_file.parent.mkdir(parents=True, exist_ok=True)
        creds_file.write_text(yaml.dump({"version": 99, "profiles": {}}))

        result = runner.invoke(main, ["auth", "profiles", "--json"])

        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert set(payload.keys()) == {"error"}
        assert "version 99" in payload["error"]

    def test_profiles_json_blocks_on_corrupt_file(self, runner: CliRunner, creds_file: Path) -> None:
        """A corrupt YAML file yields an {error} JSON object and exit code 1."""
        import json

        creds_file.parent.mkdir(parents=True, exist_ok=True)
        creds_file.write_text("{corrupt yaml: [unterminated")

        result = runner.invoke(main, ["auth", "profiles", "--json"])

        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert set(payload.keys()) == {"error"}
        assert payload["error"]


# --- Auth group ---


class TestAuthGroup:

    def test_auth_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["auth", "--help"])
        assert result.exit_code == 0
        assert "login" in result.output
        assert "status" in result.output
        assert "logout" in result.output
        assert "profiles" in result.output


class TestLitellmRemoteBaseUrl:
    """LITELLM_BASE_URL should be prompted during litellm-remote login."""

    def test_login_prompts_for_base_url(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LITELLM_API_KEY", raising=False)
        monkeypatch.delenv("LITELLM_BASE_URL", raising=False)

        result = runner.invoke(
            main,
            ["auth", "login", "-c", "litellm-remote"],
            input="my-api-key\nhttps://litellm.example.com\n",
        )
        assert result.exit_code == 0
        creds = yaml.safe_load(creds_file.read_text())
        saved = creds["profiles"]["default"]
        assert saved["LITELLM_API_KEY"] == "my-api-key"
        assert saved["LITELLM_BASE_URL"] == "https://litellm.example.com"

    def test_base_url_not_masked_in_status(
        self, runner: CliRunner, creds_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LITELLM_BASE_URL is a connection value, not a secret -- show it plainly."""
        for key in (
            "LITELLM_BASE_URL",
            "LITELLM_API_KEY",
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENROUTER_API_KEY",
            "OPENROUTER_BASE_URL",
        ):
            monkeypatch.delenv(key, raising=False)
        creds_file.write_text(
            yaml.dump(
                {
                    "version": 1,
                    "profiles": {
                        "default": {
                            "LITELLM_API_KEY": "sk-secret-key",
                            "LITELLM_BASE_URL": "https://litellm.example.com",
                        }
                    },
                }
            )
        )
        result = runner.invoke(main, ["auth", "status"])
        assert result.exit_code == 0
        assert "https://litellm.example.com" in result.output
        assert "sk-secret-key" not in result.output
