"""Exercise the sessionless Codex launcher with isolated Forge credentials."""

import json
import os
import sys
from pathlib import Path

import pytest

from forge.core.auth.credentials_file import save_profile
from forge.session.codex_invoke import invoke_codex_bare_proxy

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("stored", [False, True], ids=["env-only", "credential-store"])
def test_bare_codex_child_and_nested_forge_credentials(stored, tmp_path: Path, monkeypatch, capfd):
    forge_home = tmp_path / "forge"
    forge_home.mkdir()
    monkeypatch.setenv("FORGE_HOME", str(forge_home))
    monkeypatch.setenv("FORGE_PROFILE", "default")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "fixture-parent")
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=fixture-dotenv\n")
    if stored:
        save_profile("default", {"OPENROUTER_API_KEY": "fixture-store"})

    child = tmp_path / "codex"
    child.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "assert 'OPENROUTER_API_KEY' not in os.environ\n"
        "assert os.environ['FORGE_CODEX_PROXY_TOKEN'] == 'forge-loopback'\n"
        "os.execvp('forge', ['forge', 'auth', 'status', '--json'])\n"
    )
    child.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    assert invoke_codex_bare_proxy(base_url="http://127.0.0.1:8105", cwd=str(tmp_path)) == 0
    status = json.loads(capfd.readouterr().out)
    router = next(cred for cred in status["credentials"] if cred["name"] == "openrouter")
    key = next(var for var in router["env_vars"] if var["name"] == "OPENROUTER_API_KEY")
    assert key["configured"] is stored
    assert key["source"] == ("file:default" if stored else "not configured")
