"""Regression coverage for observable best-effort ``forge info`` probes."""

from __future__ import annotations

import importlib.metadata
import json
import logging
import subprocess
import sys
from types import SimpleNamespace
from typing import Callable

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.install.tracking import TrackingStore
from forge.proxy.proxies import ProxyRegistryStore
from forge.session import SessionManager

pytestmark = pytest.mark.regression

_LOGGER_NAME = "forge.cli.info"
_SECRET = "secret-probe-detail"


@pytest.fixture(autouse=True)
def _stable_info_probes(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    monkeypatch.setattr("shutil.which", lambda _command: None)
    monkeypatch.setattr(importlib.metadata, "version", lambda _distribution: "0.test")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["uv", "--version"], 0, stdout="uv 0.test\n"),
    )
    monkeypatch.setattr(TrackingStore, "read", lambda _self: SimpleNamespace(installations={}))
    monkeypatch.setattr(ProxyRegistryStore, "read", lambda _self: SimpleNamespace(proxies={}))
    monkeypatch.setattr(SessionManager, "list_sessions", lambda _self, **_kwargs: [])


def _raise_probe_error(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError(_SECRET)


def _invoke_info_with_debug(caplog: pytest.LogCaptureFixture) -> tuple[dict[str, object], str, str]:
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
    result = CliRunner().invoke(main, ["info", "--json"])
    assert result.exit_code == 0
    return json.loads(result.stdout), result.stderr, caplog.text


@pytest.mark.parametrize(
    ("patch_target", "fallback_key", "fallback_value", "probe_name"),
    [
        ("package", "forge_version", "unknown", "package-version"),
        ("uv", "uv_version", "unknown", "uv-version"),
        ("proxy", "proxies", [], "proxy-registry"),
        ("session", "sessions", [], "session-list"),
    ],
)
def test_info_optional_probe_failures_leave_secret_safe_debug_evidence(
    patch_target: str,
    fallback_key: str,
    fallback_value: object,
    probe_name: str,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patchers: dict[str, Callable[[], None]] = {
        "package": lambda: monkeypatch.setattr(importlib.metadata, "version", _raise_probe_error),
        "uv": lambda: monkeypatch.setattr(subprocess, "run", _raise_probe_error),
        "proxy": lambda: monkeypatch.setattr(ProxyRegistryStore, "read", _raise_probe_error),
        "session": lambda: monkeypatch.setattr(SessionManager, "list_sessions", _raise_probe_error),
    }
    patchers[patch_target]()

    data, stderr, logs = _invoke_info_with_debug(caplog)

    assert data[fallback_key] == fallback_value
    assert stderr == ""
    assert f"forge info {probe_name} probe failed (RuntimeError)" in logs
    assert _SECRET not in logs


def test_info_python_version_comes_directly_from_stdlib(caplog: pytest.LogCaptureFixture) -> None:
    data, stderr, logs = _invoke_info_with_debug(caplog)

    assert data["python_version"] == f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    assert stderr == ""
    assert "python-version probe failed" not in logs


def test_info_nonzero_uv_probe_uses_unknown_with_debug_evidence(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["uv", "--version"],
            17,
            stdout="",
            stderr=_SECRET,
        ),
    )

    data, stderr, logs = _invoke_info_with_debug(caplog)

    assert data["uv_version"] == "unknown"
    assert stderr == ""
    assert "forge info uv-version probe returned exit 17" in logs
    assert _SECRET not in logs
