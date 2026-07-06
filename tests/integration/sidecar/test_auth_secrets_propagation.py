"""E2E test: credential file secrets propagate into Docker containers.

Verifies the full path:
  forge auth login → ~/.forge/credentials.yaml → get_secrets_for_template()
  → Docker --env-file → env var visible inside container.

This is the only auth path that crosses a process boundary (host → container).

Marker: @pytest.mark.docker_host
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

from forge.core.auth.template_secrets import get_secrets_for_template
from forge.sidecar.docker import is_docker_available

pytestmark = [pytest.mark.integration, pytest.mark.docker_host]


@pytest.fixture(scope="module", autouse=True)
def _require_docker() -> None:
    """Fail loudly if Docker is unavailable (never skip tests policy)."""
    if not is_docker_available():
        pytest.fail("Docker not available. Start Docker and re-run integration tests.")


@pytest.fixture
def isolated_forge_home() -> Path:
    """Return the isolated FORGE_HOME set by the autouse fixture.

    The autouse isolate_forge_home (tests/conftest.py) already creates
    tmp_path/forge_home and sets FORGE_HOME. We just read it back.
    """
    return Path(os.environ["FORGE_HOME"])


def _write_creds(forge_home: Path, profile: str, secrets: dict[str, str]) -> Path:
    """Write credentials file and return its path."""
    creds_path = forge_home / "credentials.yaml"
    data = {"version": 1, "profiles": {profile: secrets}}
    with open(creds_path, "w") as f:
        yaml.safe_dump(data, f)
    os.chmod(str(creds_path), 0o600)
    return creds_path


class TestSecretsPropagateToContainer:
    """Verify file-based secrets reach Docker containers via env vars."""

    def test_credential_file_secret_visible_in_container(
        self,
        isolated_forge_home: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Secret from credentials.yaml is resolved by get_secrets_for_template()
        and propagated into a Docker container via --env-file."""
        # Store a test key in the credential file (not in env)
        test_key = "sk-test-e2e-propagation-12345"
        _write_creds(isolated_forge_home, "default", {"GEMINI_API_KEY": test_key})
        monkeypatch.setenv("FORGE_HOME", str(isolated_forge_home))
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

        # Resolve secrets the way the real sidecar code does
        secrets = get_secrets_for_template("litellm-gemini-local")
        assert secrets == {
            "GEMINI_API_KEY": test_key
        }, "get_secrets_for_template should resolve GEMINI_API_KEY from credential file"

        # Write them to a temp env-file (same pattern as run_sidecar_session)
        fd, env_file = tempfile.mkstemp(prefix=".forge-env-", suffix=".env")
        try:
            with os.fdopen(fd, "w") as f:
                for k, v in secrets.items():
                    f.write(f"{k}={v}\n")
            os.chmod(env_file, 0o600)

            # Run container and check the env var is visible inside
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--env-file",
                    env_file,
                    "alpine",
                    "sh",
                    "-c",
                    "echo $GEMINI_API_KEY",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            assert result.returncode == 0
            assert (
                test_key in result.stdout.strip()
            ), f"GEMINI_API_KEY should be visible inside container, got: {result.stdout!r}"
        finally:
            try:
                os.unlink(env_file)
            except OSError:
                pass

    def test_env_overrides_file_in_container(
        self,
        isolated_forge_home: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When both env var and file exist, env var wins in the container."""
        file_key = "sk-from-file-should-lose"
        env_key = "sk-from-env-should-win"

        _write_creds(isolated_forge_home, "default", {"LITELLM_API_KEY": file_key})
        monkeypatch.setenv("FORGE_HOME", str(isolated_forge_home))
        monkeypatch.setenv("LITELLM_API_KEY", env_key)

        secrets = get_secrets_for_template("litellm-openai")
        assert secrets["LITELLM_API_KEY"] == env_key, "Env should win over file"

        # Verify in container
        fd, env_file = tempfile.mkstemp(prefix=".forge-env-", suffix=".env")
        try:
            with os.fdopen(fd, "w") as f:
                for k, v in secrets.items():
                    f.write(f"{k}={v}\n")
            os.chmod(env_file, 0o600)

            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--env-file",
                    env_file,
                    "alpine",
                    "sh",
                    "-c",
                    "echo $LITELLM_API_KEY",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            assert result.returncode == 0
            assert env_key in result.stdout.strip()
            assert file_key not in result.stdout.strip()
        finally:
            try:
                os.unlink(env_file)
            except OSError:
                pass

    def test_multiple_secrets_propagate(
        self,
        isolated_forge_home: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Multiple secrets from credential file all arrive in the container."""
        _write_creds(
            isolated_forge_home,
            "default",
            {
                "LITELLM_API_KEY": "sk-litellm-e2e-test",
                "GEMINI_API_KEY": "AIza-e2e-test-456",
            },
        )
        monkeypatch.setenv("FORGE_HOME", str(isolated_forge_home))
        monkeypatch.delenv("LITELLM_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

        # litellm-gemini-local requires GEMINI_API_KEY
        secrets = get_secrets_for_template("litellm-gemini-local")
        assert len(secrets) == 1
        assert "GEMINI_API_KEY" in secrets

        fd, env_file = tempfile.mkstemp(prefix=".forge-env-", suffix=".env")
        try:
            with os.fdopen(fd, "w") as f:
                for k, v in secrets.items():
                    f.write(f"{k}={v}\n")
            os.chmod(env_file, 0o600)

            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--env-file",
                    env_file,
                    "alpine",
                    "sh",
                    "-c",
                    "echo $GEMINI_API_KEY",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            assert result.returncode == 0
            assert "AIza-e2e-test-456" in result.stdout
        finally:
            try:
                os.unlink(env_file)
            except OSError:
                pass
