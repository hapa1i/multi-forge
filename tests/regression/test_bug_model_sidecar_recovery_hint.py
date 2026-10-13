"""Configured-sidecar model refusal must not suggest a mutually exclusive launch flag."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.runtime_config import RuntimeConfig

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("leaf", ["start", "incognito"])
def test_configured_sidecar_recovery_uses_supported_config_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leaf: str
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setattr(
        "forge.runtime_config.get_runtime_config",
        lambda: RuntimeConfig(proxy_mode="sidecar"),
    )

    result = CliRunner().invoke(main, ["session", leaf, "worker", "--model", "gpt-5.6-sol"], terminal_width=500)

    assert result.exit_code == 1
    assert "forge config set proxy_mode=host" in result.output
    assert "--host-proxy" not in result.output
