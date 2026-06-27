"""Tests for the Codex headless preflight disk cache (epic consumer_lanes, T4).

The cache lets the per-Write/Edit supervisor hook read codex readiness without the ~20s
``codex doctor`` probe. These assert the round-trip and every invalidation path; the
binary/auth-store signature seams are monkeypatched so the tests never depend on a real
codex install.
"""

from __future__ import annotations

import pytest

from forge.core.runtime import codex_preflight_cache as cpc
from forge.core.runtime.codex_preflight import CodexPreflight
from forge.core.state.io import atomic_write_json


def _preflight(**overrides: object) -> CodexPreflight:
    base: dict[str, object] = {
        "installed": True,
        "version": "0.137.0",
        "version_ok": True,
        "auth_method": "chatgpt_tokens",
        "auth_source": "codex_store",
        "billing_mode": "subscription_quota",
        "ready": True,
        "blocking_reason": None,
        "hook_seam": "enrollment_gated",
        "proxy_responses": "native_direct",
        "doctor_status": "warning",
    }
    base.update(overrides)
    return CodexPreflight(**base)  # type: ignore[arg-type]


@pytest.fixture
def pinned_signatures(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin binary + auth-store + credentials signatures and the clock so write and read agree (a hit)."""
    monkeypatch.setattr(cpc, "_codex_binary_signature", lambda runtime: ("/usr/bin/codex", 1000.0))
    monkeypatch.setattr(cpc, "_auth_store_mtime", lambda: 2000.0)
    monkeypatch.setattr(cpc, "_credentials_mtime", lambda: 4000.0)
    monkeypatch.setattr(cpc, "_now", lambda: 5000.0)


class TestCodexPreflightCacheRoundTrip:
    def test_ready_preflight_round_trips(self, pinned_signatures: None) -> None:
        written = _preflight()
        cpc.write_codex_preflight_cache(written)
        assert cpc.read_fresh_codex_preflight() == written

    def test_unready_preflight_round_trips(self, pinned_signatures: None) -> None:
        # An unready preflight is cached too, so the hot path surfaces the real blocking_reason
        # ("not logged in") rather than a generic cache-miss message.
        written = _preflight(ready=False, blocking_reason="run 'codex login --device-auth'")
        cpc.write_codex_preflight_cache(written)
        got = cpc.read_fresh_codex_preflight()
        assert got is not None
        assert got.ready is False
        assert got.blocking_reason == "run 'codex login --device-auth'"


class TestCodexPreflightCacheInvalidation:
    def test_missing_file_is_miss(self) -> None:
        assert cpc.read_fresh_codex_preflight() is None

    def test_corrupt_json_is_miss(self, pinned_signatures: None) -> None:
        path = cpc._cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("this is not json{", encoding="utf-8")
        assert cpc.read_fresh_codex_preflight() is None

    def test_version_mismatch_is_miss(self, pinned_signatures: None) -> None:
        # A future/old cache shape is discarded (runtime-only state), never an error.
        atomic_write_json(cpc._cache_path(), {"version": 999, "preflight": {}})
        assert cpc.read_fresh_codex_preflight() is None

    def test_ttl_expiry_is_miss(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cpc, "_codex_binary_signature", lambda runtime: ("/usr/bin/codex", 1000.0))
        monkeypatch.setattr(cpc, "_auth_store_mtime", lambda: 2000.0)
        monkeypatch.setattr(cpc, "_now", lambda: 5000.0)
        cpc.write_codex_preflight_cache(_preflight())

        # Advance past the TTL: the same signatures are fresh, but the timestamp is stale.
        monkeypatch.setattr(cpc, "_now", lambda: 5000.0 + cpc.DEFAULT_PREFLIGHT_TTL_SECONDS + 1)
        assert cpc.read_fresh_codex_preflight() is None

    def test_within_ttl_is_hit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cpc, "_codex_binary_signature", lambda runtime: ("/usr/bin/codex", 1000.0))
        monkeypatch.setattr(cpc, "_auth_store_mtime", lambda: 2000.0)
        monkeypatch.setattr(cpc, "_now", lambda: 5000.0)
        cpc.write_codex_preflight_cache(_preflight())

        monkeypatch.setattr(cpc, "_now", lambda: 5000.0 + cpc.DEFAULT_PREFLIGHT_TTL_SECONDS - 1)
        assert cpc.read_fresh_codex_preflight() is not None

    def test_binary_upgrade_invalidates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cpc, "_auth_store_mtime", lambda: 2000.0)
        monkeypatch.setattr(cpc, "_now", lambda: 5000.0)
        monkeypatch.setattr(cpc, "_codex_binary_signature", lambda runtime: ("/usr/bin/codex", 1000.0))
        cpc.write_codex_preflight_cache(_preflight())

        # Codex upgraded -> the binary mtime changed since the cache was written.
        monkeypatch.setattr(cpc, "_codex_binary_signature", lambda runtime: ("/usr/bin/codex", 9999.0))
        assert cpc.read_fresh_codex_preflight() is None

    def test_auth_store_change_invalidates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cpc, "_codex_binary_signature", lambda runtime: ("/usr/bin/codex", 1000.0))
        monkeypatch.setattr(cpc, "_now", lambda: 5000.0)
        monkeypatch.setattr(cpc, "_auth_store_mtime", lambda: 2000.0)
        cpc.write_codex_preflight_cache(_preflight())

        # A login/logout rewrote $CODEX_HOME/auth.json -> a different mtime.
        monkeypatch.setattr(cpc, "_auth_store_mtime", lambda: 3333.0)
        assert cpc.read_fresh_codex_preflight() is None

    def test_credentials_change_invalidates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # M4: _resolve_codex_auth reads CODEX_API_KEY from ~/.forge/credentials.yaml *before* the
        # codex store, so editing that file changes readiness. Its mtime is a stat-able key.
        monkeypatch.setattr(cpc, "_codex_binary_signature", lambda runtime: ("/usr/bin/codex", 1000.0))
        monkeypatch.setattr(cpc, "_auth_store_mtime", lambda: 2000.0)
        monkeypatch.setattr(cpc, "_now", lambda: 5000.0)
        monkeypatch.setattr(cpc, "_credentials_mtime", lambda: 4000.0)
        cpc.write_codex_preflight_cache(_preflight())

        # An edit to credentials.yaml (e.g. a newly added CODEX_API_KEY) -> a different mtime.
        monkeypatch.setattr(cpc, "_credentials_mtime", lambda: 4444.0)
        assert cpc.read_fresh_codex_preflight() is None

    def test_shape_drift_is_miss(self, pinned_signatures: None) -> None:
        # A payload whose preflight dict no longer matches the CodexPreflight constructor is
        # discarded (TypeError on reconstruct -> None), not propagated.
        atomic_write_json(
            cpc._cache_path(),
            {
                "version": cpc.CODEX_PREFLIGHT_CACHE_VERSION,
                "written_at": 5000.0,
                "codex_bin_path": "/usr/bin/codex",
                "codex_bin_mtime": 1000.0,
                "auth_store_mtime": 2000.0,
                "credentials_mtime": 4000.0,  # match pinned_signatures so we reach the shape-drift path
                "preflight": {"unexpected_field": True},
            },
        )
        assert cpc.read_fresh_codex_preflight() is None
