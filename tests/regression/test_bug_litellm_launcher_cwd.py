"""A project-local litellm.py must not interfere with managed gateway startup."""

import subprocess
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.backend.adapters.litellm import LiteLLMAdapter

pytestmark = pytest.mark.regression


def test_gateway_launcher_imports_installed_litellm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "litellm.py").touch()
    monkeypatch.delenv("PYTHONSAFEPATH", raising=False)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "true")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    config = tmp_path / "config.yaml"
    config.write_text("model_list: []\n")

    adapter = LiteLLMAdapter()
    with (
        patch("subprocess.Popen") as launch,
        patch.object(adapter, "_wait_for_health", return_value=True),
    ):
        launch.return_value.pid = 12345
        adapter.start("litellm-4000", config, 4000)

    # Exercise the gateway imports without binding a port.
    command = launch.call_args.args[0]
    options = launch.call_args.kwargs
    result = subprocess.run(
        [*command, "--version"],
        cwd=options.get("cwd"),
        env=options["env"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert version("litellm") in result.stdout
