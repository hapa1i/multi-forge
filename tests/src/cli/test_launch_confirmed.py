"""record_launch_confirmed + routing classification for launch metadata (G3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.cli.launch_confirmation import _routing_mode_for, record_launch_confirmed
from forge.core.reactive.env import InteractiveApiKeyDecision
from forge.session import SessionStore, create_session_state


def _store_with_manifest(tmp_path: Path) -> SessionStore:
    store = SessionStore(str(tmp_path), "test-session")
    store.write(
        create_session_state(
            "test-session",
            proxy_template="litellm-gemini",
            proxy_base_url="http://localhost:8084",
        )
    )
    return store


class TestRoutingModeFor:
    def test_direct_when_no_base_url(self) -> None:
        assert _routing_mode_for(None, None) == "direct"

    def test_proxy_when_base_url_and_proxy_id(self) -> None:
        assert _routing_mode_for("http://localhost:8085", "p1") == "proxy"

    def test_custom_base_url_when_base_url_without_proxy_id(self) -> None:
        # An opaque base URL with no resolvable Forge proxy id.
        assert _routing_mode_for("http://example.test", None) == "custom_base_url"


class TestRecordLaunchConfirmed:
    def test_writes_omit_launch_facts(self, tmp_path: Path) -> None:
        store = _store_with_manifest(tmp_path)
        record_launch_confirmed(
            store,
            routing_mode="proxy",
            proxy_id="p1",
            base_url="http://localhost:8085",
            decision=InteractiveApiKeyDecision(available=False, source="omitted_by_config"),
        )
        launch = store.read().confirmed.launch
        assert launch is not None
        assert launch.routing_mode == "proxy"
        assert launch.proxy_id == "p1"
        assert launch.base_url == "http://localhost:8085"
        assert launch.api_key_available_to_child is False
        assert launch.api_key_source == "omitted_by_config"

    def test_writes_direct_inherit_facts(self, tmp_path: Path) -> None:
        store = _store_with_manifest(tmp_path)
        record_launch_confirmed(
            store,
            routing_mode="direct",
            proxy_id=None,
            base_url=None,
            decision=InteractiveApiKeyDecision(available=True, source="env"),
        )
        launch = store.read().confirmed.launch
        assert launch is not None
        assert launch.routing_mode == "direct"
        assert launch.proxy_id is None
        assert launch.api_key_available_to_child is True
        assert launch.api_key_source == "env"

    def test_skips_write_and_does_not_resurrect_a_deleted_session(self, tmp_path: Path) -> None:
        # Resurrection guard (mirrors _infer_launch_confirmation): if the session was
        # deleted in the window before this best-effort write (e.g. a concurrent
        # `forge session delete`), record_launch_confirmed must NOT recreate the
        # session directory. Without the exists() preflight, entering store.update()
        # makes the lock layer mkdir-parents the dir to hold its lockfile, leaving a
        # lock-only directory behind.
        store = _store_with_manifest(tmp_path)
        assert store.delete() is True
        assert not store.exists()

        record_launch_confirmed(
            store,
            routing_mode="direct",
            proxy_id=None,
            base_url=None,
            decision=InteractiveApiKeyDecision(available=True, source="env"),
        )

        assert not store.session_dir.exists()  # not resurrected as a lock-only dir
        assert not store.exists()


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
