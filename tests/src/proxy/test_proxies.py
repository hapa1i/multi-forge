"""Tests for proxy registry store."""

from __future__ import annotations

import json
import os

# NOTE: used for monkeypatching in overlay deletion failure test
import shutil
import subprocess
from multiprocessing import Process
from pathlib import Path

import pytest

from forge.core.state import now_iso
from forge.proxy.proxies import (
    PROXY_REGISTRY_VERSION,
    ProxyEntry,
    ProxyRegistry,
    ProxyRegistryCorruptedError,
    ProxyRegistryStore,
    _is_orphaned_starting,
    is_pid_alive,
)
from forge.proxy.proxy_orchestrator import prune_stale_proxies


def test_read_returns_empty_when_missing(tmp_path: Path) -> None:
    registry_path = tmp_path / "proxies" / "index.json"
    store = ProxyRegistryStore(registry_path)

    registry = store.read()

    assert registry.version == PROXY_REGISTRY_VERSION
    assert registry.proxies == {}


def test_read_raises_on_corrupted_json(tmp_path: Path) -> None:
    registry_path = tmp_path / "proxies" / "index.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text("{not-json}")

    store = ProxyRegistryStore(registry_path)

    with pytest.raises(ProxyRegistryCorruptedError):
        store.read()


def test_read_raises_on_invalid_version(tmp_path: Path) -> None:
    registry_path = tmp_path / "proxies" / "index.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(json.dumps({"version": 999, "proxies": {}}))

    store = ProxyRegistryStore(registry_path)

    with pytest.raises(ProxyRegistryCorruptedError):
        store.read()


def test_write_creates_parent_directory(tmp_path: Path) -> None:
    registry_path = tmp_path / "proxies" / "index.json"
    store = ProxyRegistryStore(registry_path)

    registry = ProxyRegistry(
        proxies={
            "proxy_1": ProxyEntry(
                proxy_id="proxy_1",
                template="litellm-openai",
                base_url="http://localhost:8085",
                port=8085,
            )
        }
    )

    store.write(registry)

    assert registry_path.is_file()


def _add_proxy(registry_path: str, proxy_id: str) -> None:
    store = ProxyRegistryStore(Path(registry_path))

    def _mutate(r: ProxyRegistry) -> None:
        r.proxies[proxy_id] = ProxyEntry(
            proxy_id=proxy_id,
            template="litellm-openai",
            base_url=f"http://localhost:{8000 + int(proxy_id.split('_')[-1])}",
            port=8000 + int(proxy_id.split("_")[-1]),
        )

    store.update(timeout_s=5.0, mutate=_mutate)


def test_update_merges_concurrent_writes(tmp_path: Path) -> None:
    registry_path = tmp_path / "proxies" / "index.json"

    p1 = Process(target=_add_proxy, args=(str(registry_path), "proxy_1"))
    p2 = Process(target=_add_proxy, args=(str(registry_path), "proxy_2"))

    p1.start()
    p2.start()
    p1.join(timeout=5.0)
    p2.join(timeout=5.0)

    assert not p1.is_alive()
    assert not p2.is_alive()

    store = ProxyRegistryStore(registry_path)
    registry = store.read()
    assert "proxy_1" in registry.proxies
    assert "proxy_2" in registry.proxies


def test_read_write_roundtrip(tmp_path: Path) -> None:
    registry_path = tmp_path / "proxies" / "index.json"
    store = ProxyRegistryStore(registry_path)

    registry = ProxyRegistry(
        proxies={
            "proxy_1": ProxyEntry(
                proxy_id="proxy_1",
                template="litellm-openai",
                base_url="http://localhost:8085",
                port=8085,
                pid=123,
                created_at="2025-12-20T00:00:00+00:00",
                last_seen_at="2025-12-20T00:01:00+00:00",
                status="healthy",
            )
        }
    )

    store.write(registry)
    read_back = store.read()

    assert read_back.version == PROXY_REGISTRY_VERSION
    assert "proxy_1" in read_back.proxies

    entry = read_back.proxies["proxy_1"]
    assert entry.proxy_id == "proxy_1"
    assert entry.template == "litellm-openai"
    assert entry.base_url == "http://localhost:8085"
    assert entry.port == 8085
    assert entry.pid == 123
    assert entry.status == "healthy"


def test_is_pid_alive_returns_false_for_invalid_pid() -> None:
    assert is_pid_alive(0) is False
    assert is_pid_alive(-1) is False


def test_is_pid_alive_treats_permission_error_as_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_permission(pid: int, sig: int) -> None:
        raise PermissionError("no permission")

    monkeypatch.setattr("forge.core.process.os.kill", _raise_permission)
    assert is_pid_alive(12345) is True


def test_prune_dead_pids_prunes_dead_pid_and_keeps_pid_none(tmp_path: Path) -> None:
    registry_path = tmp_path / "proxies" / "index.json"
    store = ProxyRegistryStore(registry_path)

    proc = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
    proc.wait(timeout=2.0)

    store.write(
        ProxyRegistry(
            proxies={
                "proxy_dead": ProxyEntry(
                    proxy_id="proxy_dead",
                    template="litellm-openai",
                    base_url="http://localhost:8085",
                    port=8085,
                    pid=proc.pid,
                ),
                "proxy_adopted": ProxyEntry(
                    proxy_id="proxy_adopted",
                    template="litellm-openai",
                    base_url="http://localhost:8086",
                    port=8086,
                    pid=None,
                ),
            }
        )
    )

    pruned = store.prune_dead_pids(timeout_s=1.0)
    assert pruned == ["proxy_dead"]

    after = store.read()
    assert "proxy_dead" not in after.proxies
    assert "proxy_adopted" in after.proxies


def test_prune_dead_pids_keeps_alive_pid(tmp_path: Path) -> None:
    registry_path = tmp_path / "proxies" / "index.json"
    store = ProxyRegistryStore(registry_path)

    store.write(
        ProxyRegistry(
            proxies={
                "proxy_alive": ProxyEntry(
                    proxy_id="proxy_alive",
                    template="litellm-openai",
                    base_url="http://localhost:8085",
                    port=8085,
                    pid=os.getpid(),
                )
            }
        )
    )

    pruned = store.prune_dead_pids(timeout_s=1.0)
    assert pruned == []

    after = store.read()
    assert "proxy_alive" in after.proxies


def test_prune_stale_proxies_deletes_overlay_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Point ProxyRegistryStore at our tmp registry via FORGE_HOME.
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))

    store = ProxyRegistryStore()

    proc = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
    proc.wait(timeout=2.0)

    proxy_id = "proxy_dead"
    store.write(
        ProxyRegistry(
            proxies={
                proxy_id: ProxyEntry(
                    proxy_id=proxy_id,
                    template="litellm-openai",
                    base_url="http://localhost:8085",
                    port=8085,
                    pid=proc.pid,
                )
            }
        )
    )

    overlay_dir = tmp_path / "proxies" / proxy_id
    overlay_dir.mkdir(parents=True)
    (overlay_dir / "config.yaml").write_text("proxy:\n  default_tier: sonnet\n")

    result = prune_stale_proxies(timeout_s=1.0)
    assert result.pruned_proxy_ids == [proxy_id]
    assert not overlay_dir.exists()


def test_prune_stale_proxies_overlay_delete_failure_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))

    store = ProxyRegistryStore()

    proc = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
    proc.wait(timeout=2.0)

    proxy_id = "proxy_dead"
    store.write(
        ProxyRegistry(
            proxies={
                proxy_id: ProxyEntry(
                    proxy_id=proxy_id,
                    template="litellm-openai",
                    base_url="http://localhost:8085",
                    port=8085,
                    pid=proc.pid,
                )
            }
        )
    )

    overlay_dir = tmp_path / "proxies" / proxy_id
    overlay_dir.mkdir(parents=True)
    (overlay_dir / "config.yaml").write_text("proxy:\n  default_tier: sonnet\n")

    def _raise(*args: object, **kwargs: object) -> None:
        raise OSError("nope")

    monkeypatch.setattr(shutil, "rmtree", _raise)

    result = prune_stale_proxies(timeout_s=1.0)
    assert result.pruned_proxy_ids == [proxy_id]
    assert result.delete_errors

    # Registry is still pruned.
    after = store.read()
    assert proxy_id not in after.proxies


# ---------------------------------------------------------------------------
# Orphaned "starting" entry pruning
# ---------------------------------------------------------------------------


def test_is_orphaned_starting_old_entry() -> None:
    """An entry created long ago with no PID is orphaned."""
    entry = ProxyEntry(
        proxy_id="proxy_old",
        template="t",
        base_url="http://localhost:8085",
        port=8085,
        pid=None,
        created_at="2020-01-01T00:00:00+00:00",
        status="starting",
    )
    assert _is_orphaned_starting(entry) is True


def test_is_orphaned_starting_recent_entry() -> None:
    """An entry created just now is NOT orphaned (still starting up)."""
    entry = ProxyEntry(
        proxy_id="proxy_new",
        template="t",
        base_url="http://localhost:8085",
        port=8085,
        pid=None,
        created_at=now_iso(),
        status="starting",
    )
    assert _is_orphaned_starting(entry) is False


def test_is_orphaned_starting_no_timestamp() -> None:
    """An entry with no created_at is treated as orphaned."""
    entry = ProxyEntry(
        proxy_id="proxy_no_ts",
        template="t",
        base_url="http://localhost:8085",
        port=8085,
        pid=None,
        created_at=None,
        status="starting",
    )
    assert _is_orphaned_starting(entry) is True


def test_prune_dead_pids_removes_orphaned_starting(tmp_path: Path) -> None:
    """Prune removes 'starting' entries with no PID that are older than threshold."""
    registry_path = tmp_path / "proxies" / "index.json"
    store = ProxyRegistryStore(registry_path)

    store.write(
        ProxyRegistry(
            proxies={
                "proxy_orphaned": ProxyEntry(
                    proxy_id="proxy_orphaned",
                    template="litellm-openai",
                    base_url="http://localhost:8087",
                    port=8087,
                    pid=None,
                    created_at="2020-01-01T00:00:00+00:00",
                    status="starting",
                ),
                "proxy_configured": ProxyEntry(
                    proxy_id="proxy_configured",
                    template="litellm-openai",
                    base_url="http://localhost:8086",
                    port=8086,
                    pid=None,
                    created_at="2020-01-01T00:00:00+00:00",
                    status="configured",
                ),
                "proxy_fresh_starting": ProxyEntry(
                    proxy_id="proxy_fresh_starting",
                    template="litellm-openai",
                    base_url="http://localhost:8088",
                    port=8088,
                    pid=None,
                    created_at=now_iso(),
                    status="starting",
                ),
            }
        )
    )

    pruned = store.prune_dead_pids(timeout_s=1.0)
    assert pruned == ["proxy_orphaned"]

    after = store.read()
    assert "proxy_orphaned" not in after.proxies
    # "configured" entries are never pruned
    assert "proxy_configured" in after.proxies
    # Fresh "starting" entries are kept (could still be starting up)
    assert "proxy_fresh_starting" in after.proxies
