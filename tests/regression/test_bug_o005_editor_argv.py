"""Regression for O005: every editable configuration surface honors shell-style $EDITOR argv."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from forge.cli import claude as claude_cli
from forge.cli import config_cmd as config_cli
from forge.cli import proxy as proxy_cli
from forge.config import loader as config_loader
from forge.runtime_config import reset_runtime_config

pytestmark = pytest.mark.regression


@pytest.fixture(autouse=True)
def _reset_runtime_config() -> Iterator[None]:
    reset_runtime_config()
    yield
    reset_runtime_config()


def _invoke_editor_surface(surface: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[object, list[list[str]]]:
    calls: list[list[str]] = []

    def fake_which(command: str) -> str | None:
        return "/fake/fake-editor" if command == "fake-editor" else None

    def fake_run(command: list[str], *_args: object, **_kwargs: object) -> SimpleNamespace:
        calls.append([str(part) for part in command])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(shutil, "which", fake_which)
    monkeypatch.setattr(subprocess, "run", fake_run)

    runner = CliRunner()
    if surface == "proxy":
        proxy_path = tmp_path / "proxy.yaml"
        proxy_path.write_text("{}\n", encoding="utf-8")
        monkeypatch.setattr(proxy_cli, "get_proxy_file_path", lambda _proxy_id: proxy_path)
        monkeypatch.setattr(config_loader, "load_proxy_instance_config_from_dict", lambda _data: None)
        result = runner.invoke(proxy_cli.edit_cmd, ["p1"])
    elif surface == "template":
        result = runner.invoke(proxy_cli.template_edit_cmd, ["litellm-openai"])
    elif surface == "config":
        result = runner.invoke(config_cli.edit_cmd)
    else:
        result = runner.invoke(claude_cli.preset_edit)
    return result, calls


@pytest.mark.parametrize("surface", ["proxy", "template", "config", "preset"])
def test_multitoken_editor_is_split_on_every_edit_surface(
    surface: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDITOR", "fake-editor --wait")

    result, calls = _invoke_editor_surface(surface, tmp_path, monkeypatch)

    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0][:2] == ["fake-editor", "--wait"]
    assert len(calls[0]) == 3


def test_single_token_editor_keeps_existing_argv_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDITOR", "fake-editor")

    result, calls = _invoke_editor_surface("config", tmp_path, monkeypatch)

    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0][0] == "fake-editor"
    assert len(calls[0]) == 2
