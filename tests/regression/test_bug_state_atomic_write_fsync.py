"""Regression: former hand-rolled atomic writers must use durable fsync semantics."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import pytest

from forge.cli.statusline.throttle import _write as write_statusline_cache
from forge.config.loader import write_proxy_instance_config
from forge.config.schema import ProxyInstanceConfig, TierModels
from forge.core.auth.credentials_file import save_profile
from forge.runtime_config import write_runtime_config
from forge.session.claude.paths import get_transcript_path
from forge.session.claude.relocate import relocate_transcript

pytestmark = pytest.mark.regression


class FsyncSpy:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from forge.core.state import io as state_io

        self.calls: list[str] = []
        self._dir_fds: set[int] = set()
        real_open = state_io.os.open
        real_fsync = state_io.os.fsync

        def open_spy(path: str, flags: int, *args: Any, **kwargs: Any) -> int:
            fd = real_open(path, flags, *args, **kwargs)
            if Path(path).is_dir():
                self._dir_fds.add(fd)
            return fd

        def fsync_spy(fd: int) -> None:
            self.calls.append("dir" if fd in self._dir_fds else "file")
            real_fsync(fd)

        monkeypatch.setattr(state_io.os, "open", open_spy)
        monkeypatch.setattr(state_io.os, "fsync", fsync_spy)

    def assert_file_and_dir_fsynced(self) -> None:
        assert "file" in self.calls
        assert "dir" in self.calls


@pytest.fixture
def fsync_spy(monkeypatch: pytest.MonkeyPatch) -> FsyncSpy:
    return FsyncSpy(monkeypatch)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_proxy_config_write_uses_fsynced_atomic_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fsync_spy: FsyncSpy
) -> None:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge"))
    config = ProxyInstanceConfig(
        proxy_format=1,
        template="litellm-test",
        template_digest="digest",
        provider="litellm",
        proxy_endpoint="http://127.0.0.1:8080",
        port=8080,
        upstream_base_url="http://127.0.0.1:4000",
        tiers=TierModels(haiku="h", sonnet="s", opus="o"),
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )

    path = write_proxy_instance_config("proxy-one", config)

    fsync_spy.assert_file_and_dir_fsynced()
    assert _mode(path) == 0o600
    assert path.read_text(encoding="utf-8").startswith("# Forge Proxy Configuration\n")


def test_credentials_write_uses_fsynced_atomic_helper(tmp_path: Path, fsync_spy: FsyncSpy) -> None:
    path = tmp_path / "credentials.yaml"

    save_profile("default", {"API_KEY": "secret"}, path=path)

    fsync_spy.assert_file_and_dir_fsynced()
    assert _mode(path) == 0o600
    assert path.read_text(encoding="utf-8").startswith("# Forge Credential Store")


def test_runtime_config_write_uses_fsynced_atomic_helper(tmp_path: Path, fsync_spy: FsyncSpy) -> None:
    path = tmp_path / "config.yaml"

    write_runtime_config({"proxy_mode": "host"}, path=path)

    fsync_spy.assert_file_and_dir_fsynced()
    assert _mode(path) == 0o600
    assert "proxy_mode: host" in path.read_text(encoding="utf-8")


def test_statusline_cache_write_uses_fsynced_atomic_helper(tmp_path: Path, fsync_spy: FsyncSpy) -> None:
    path = tmp_path / "cache" / "entry.json"
    payload = {"version": 1, "computed_at": 1.5, "cache_hit_rate": 42.0}

    write_statusline_cache(path, payload)

    fsync_spy.assert_file_and_dir_fsynced()
    assert _mode(path) == 0o600
    assert path.read_text(encoding="utf-8") == json.dumps(payload)


def test_relocate_transcript_uses_fsynced_atomic_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fsync_spy: FsyncSpy
) -> None:
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / "claude"))
    source_root = (tmp_path / "source").resolve()
    dest_root = (tmp_path / "dest").resolve()
    source_root.mkdir()
    dest_root.mkdir()
    session_id = "session-uuid"
    source_bytes = b'{"type":"assistant","signed":"\\xff"}\nraw-bytes:\xff\n'
    source_path = get_transcript_path(str(source_root), session_id)
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(source_bytes)

    result = relocate_transcript(
        session_id=session_id,
        source_project_root=str(source_root),
        dest_project_root=str(dest_root),
    )

    fsync_spy.assert_file_and_dir_fsynced()
    assert result.dest_path.read_bytes() == source_bytes
    assert _mode(result.dest_path) == 0o600
