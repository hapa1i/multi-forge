"""Unit tests for the Phase 2 audit logger (logging, hashing, drift, retention)."""

from __future__ import annotations

import json
import os
import time

import pytest

from forge.core.telemetry import downstream as downstream_telemetry
from forge.proxy import audit_logger
from forge.proxy.utils import redact_headers

ROUTE = {"template": "anthropic-passthrough", "provider": "litellm", "tier": "opus"}


@pytest.fixture(autouse=True)
def _isolated_audit_home(tmp_path, monkeypatch):
    # Fresh FORGE_HOME per test so audit shards + drift state never leak across tests.
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    audit_logger._drift_state.clear()
    audit_logger._warned_newer_schema = False
    downstream_telemetry._warned_newer_schema = False
    downstream_telemetry._warned_older_schema = False
    yield
    audit_logger._drift_state.clear()
    downstream_telemetry._warned_newer_schema = False
    downstream_telemetry._warned_older_schema = False


def _meta(request_id="r", proxy_id="p", **kw):
    audit_logger.write_metadata_record(
        request_id=request_id,
        proxy_id=proxy_id,
        mode="inspect",
        route=ROUTE,
        system_prompt_hash=kw.pop("system_prompt_hash", None),
        tool_surface_hash=kw.pop("tool_surface_hash", None),
        **kw,
    )


def _downstream_dir():
    return downstream_telemetry._downstream_dir()


def _downstream_path():
    return downstream_telemetry._current_log_path()


class TestAuditStatePath:
    """Drift-state file location (Slice 2e: read-only config mount forces a redirect)."""

    def test_host_mode_writes_beside_proxy_yaml(self, monkeypatch):
        from forge.core.paths import get_forge_home

        monkeypatch.delenv("FORGE_SIDECAR", raising=False)
        monkeypatch.delenv("FORGE_PROXY_ID", raising=False)
        assert audit_logger._audit_state_path("px") == get_forge_home() / "proxies" / "px" / "audit_state.json"

    def test_proxy_id_sidecar_redirects_to_writable_audit_mount(self, monkeypatch):
        from forge.core.paths import get_forge_home

        # A proxy-id sidecar mounts ~/.forge/proxies/<id>/ read-only, so the drift
        # baseline must land in the writable audit mount instead.
        monkeypatch.setenv("FORGE_SIDECAR", "1")
        monkeypatch.setenv("FORGE_PROXY_ID", "px")
        assert audit_logger._audit_state_path("px") == get_forge_home() / "telemetry" / "audit_state" / "px.json"

    def test_template_only_sidecar_does_not_redirect(self, monkeypatch):
        from forge.core.paths import get_forge_home

        # Template-only sidecars set FORGE_SIDECAR but mount no audit/ dir, so the
        # redirect target would not exist — keep the host-mode path.
        monkeypatch.setenv("FORGE_SIDECAR", "1")
        monkeypatch.delenv("FORGE_PROXY_ID", raising=False)
        assert audit_logger._audit_state_path("px") == get_forge_home() / "proxies" / "px" / "audit_state.json"


class TestHashing:
    def test_system_prompt_str_and_list_equivalent(self):
        as_str = audit_logger.hash_system_prompt("You are helpful.")
        as_list = audit_logger.hash_system_prompt([{"type": "text", "text": "You are helpful."}])
        assert as_str == as_list
        assert as_str.startswith("sha256:")

    def test_system_prompt_ignores_cache_control(self):
        a = audit_logger.hash_system_prompt([{"type": "text", "text": "X", "cache_control": {"type": "ephemeral"}}])
        b = audit_logger.hash_system_prompt([{"type": "text", "text": "X"}])
        assert a == b

    def test_system_prompt_excludes_non_text_blocks(self):
        """A non-text system block must not enter the hash (it would read as drift)."""
        text_only = audit_logger.hash_system_prompt([{"type": "text", "text": "X"}])
        with_other = audit_logger.hash_system_prompt(
            [{"type": "text", "text": "X"}, {"type": "image", "text": "ignored"}]
        )
        assert text_only == with_other

    def test_system_prompt_none_and_empty(self):
        assert audit_logger.hash_system_prompt(None) is None
        assert audit_logger.hash_system_prompt("") is None
        assert audit_logger.hash_system_prompt([]) is None

    def test_system_prompt_changes_on_text_change(self):
        assert audit_logger.hash_system_prompt("A") != audit_logger.hash_system_prompt("B")

    def test_tool_surface_stable_under_reorder_and_description(self):
        t1 = [
            {"name": "Bash", "description": "run", "input_schema": {"type": "object"}},
            {"name": "Read", "description": "read", "input_schema": {"type": "object"}},
        ]
        t2 = [
            {
                "name": "Read",
                "description": "DIFFERENT PROSE",
                "input_schema": {"type": "object"},
            },
            {"name": "Bash", "description": "run", "input_schema": {"type": "object"}},
        ]
        assert audit_logger.hash_tool_surface(t1) == audit_logger.hash_tool_surface(t2)

    def test_tool_surface_changes_on_schema_change(self):
        t1 = [{"name": "Bash", "input_schema": {"type": "object", "properties": {}}}]
        t2 = [
            {
                "name": "Bash",
                "input_schema": {"type": "object", "properties": {"cmd": {}}},
            }
        ]
        assert audit_logger.hash_tool_surface(t1) != audit_logger.hash_tool_surface(t2)

    def test_tool_surface_none_and_empty(self):
        assert audit_logger.hash_tool_surface(None) is None
        assert audit_logger.hash_tool_surface([]) is None


class TestWriteRead:
    def test_metadata_record_carries_backend_id(self):
        _meta(request_id="r-backend", proxy_id="p", backend_id="anthropic-passthrough")

        raw = json.loads(_downstream_path().read_text().splitlines()[0])
        assert raw["backend_id"] == "anthropic-passthrough"

        payload = audit_logger.read_audit_logs()[0]
        assert payload["backend_id"] == "anthropic-passthrough"

    def test_metadata_round_trip(self):
        _meta(
            request_id="req_1",
            system_prompt_hash="sha256:aaa",
            tool_surface_hash="sha256:bbb",
            counts={"num_messages": 3, "num_tools": 2},
        )
        recs = audit_logger.read_audit_logs()
        assert len(recs) == 1
        r = recs[0]
        assert r["record_type"] == "request"
        assert r["full_body"] is False
        assert r["schema_version"] == 1
        assert r["ts"].endswith("Z")
        assert r["system_prompt_hash"] == "sha256:aaa"
        assert r["counts"]["num_messages"] == 3

    def test_full_body_redacts_headers_and_body(self):
        audit_logger.write_full_body_record(
            request_id="req_2",
            proxy_id="p",
            mode="inspect",
            route=ROUTE,
            request_headers={
                "Authorization": "Bearer SECRET",
                "anthropic-version": "2023-06-01",
            },
            request_body={
                "model": "m",
                "system": "secret sys",
                "messages": [{"role": "user", "content": "hi secret"}],
            },
        )
        r = audit_logger.read_audit_logs(record_type="request")[0]
        assert r["full_body"] is True
        assert r["request_headers"]["Authorization"] == {
            "redacted": True,
            "length": len("Bearer SECRET"),
        }
        assert r["request_headers"]["anthropic-version"] == "2023-06-01"
        assert r["request_body"]["model"] == "m"
        assert r["request_body"]["system"] == {
            "redacted": True,
            "length": len("secret sys"),
        }

    def test_read_filters_by_proxy_and_request(self):
        _meta(request_id="a", proxy_id="p1")
        _meta(request_id="b", proxy_id="p2")
        assert {r["proxy_id"] for r in audit_logger.read_audit_logs(proxy_id="p1")} == {"p1"}
        assert {r["request_id"] for r in audit_logger.read_audit_logs(request_id="b")} == {"b"}

    def test_newer_schema_records_skipped(self):
        path = _downstream_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(
                json.dumps(
                    {
                        "schema_version": 99,
                        "kind": "audit",
                        "downstream_event_id": "ds_future",
                        "payload": {
                            "record_type": "request",
                            "ts": "2026-01-01T00:00:00Z",
                        },
                    }
                )
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "schema_version": downstream_telemetry.DOWNSTREAM_SCHEMA_VERSION,
                        "kind": "audit",
                        "downstream_event_id": "ds_ok",
                        "proxy_id": "ok",
                        "payload": {
                            "schema_version": 1,
                            "record_type": "request",
                            "proxy_id": "ok",
                            "ts": "2026-01-02T00:00:00Z",
                        },
                    }
                )
                + "\n"
            )
        recs = audit_logger.read_audit_logs()
        assert all(r.get("schema_version") == 1 for r in recs)
        assert any(r.get("proxy_id") == "ok" for r in recs)

    def test_best_effort_never_raises(self, monkeypatch):
        def _boom(*a, **k):
            raise OSError("disk full")

        monkeypatch.setattr("forge.core.state.open_secure_append", _boom)
        audit_logger.log_audit_record({"record_type": "request", "request_id": "x"})  # must not raise

    def test_file_and_dir_permissions(self):
        _meta()
        files = list(_downstream_dir().glob("*.jsonl"))
        assert files
        assert oct(files[0].stat().st_mode)[-3:] == "600"
        assert oct(_downstream_dir().stat().st_mode)[-3:] == "700"


class TestDrift:
    @staticmethod
    def _drift(current_hash, request_id="r", dimension="system_prompt", proxy_id="p"):
        return audit_logger.check_and_record_drift(
            proxy_id=proxy_id,
            dimension=dimension,
            current_hash=current_hash,
            request_id=request_id,
            route=ROUTE,
        )

    def test_first_observation_is_baseline_not_drift(self):
        assert self._drift("sha256:a") is False
        assert audit_logger.read_audit_logs(record_type="drift") == []

    def test_repeat_hash_no_drift(self):
        self._drift("sha256:a", "r1")
        assert self._drift("sha256:a", "r2") is False
        assert audit_logger.read_audit_logs(record_type="drift") == []

    def test_changed_hash_fires_drift(self):
        self._drift("sha256:a", "r1")
        assert self._drift("sha256:b", "r2") is True
        drifts = audit_logger.read_audit_logs(record_type="drift")
        assert len(drifts) == 1
        assert drifts[0]["dimension"] == "system_prompt"
        assert drifts[0]["previous_hash"] == "sha256:a"
        assert drifts[0]["current_hash"] == "sha256:b"

    def test_baseline_survives_restart(self):
        self._drift("sha256:a", "r1")
        audit_logger._drift_state.clear()  # simulate restart
        assert self._drift("sha256:a", "r2") is False  # reseeded from file
        audit_logger._drift_state.clear()
        assert self._drift("sha256:b", "r3") is True

    def test_dimensions_independent(self):
        self._drift("sha256:a", "r1", dimension="system_prompt")
        self._drift("sha256:t", "r1", dimension="tool_surface")
        assert self._drift("sha256:a2", "r2", dimension="system_prompt") is True
        assert self._drift("sha256:t", "r2", dimension="tool_surface") is False

    def test_none_hash_is_noop(self):
        assert self._drift(None) is False


class TestPrune:
    def test_prune_by_age_deletes_old_downstream_shard(self):
        _meta()
        shard = list(_downstream_dir().glob("*.jsonl"))[0]
        shard = shard.rename(shard.with_name("2000-01_1.jsonl"))
        old = time.time() - 30 * 86400
        os.utime(shard, (old, old))
        audit_logger.prune_audit_logs(retention_days=14, max_total_mb=512)
        assert not shard.exists()

    def test_prune_keeps_recent(self):
        _meta()
        audit_logger.prune_audit_logs(retention_days=14, max_total_mb=512)
        assert list(_downstream_dir().glob("*.jsonl"))

    def test_prune_by_total_size_deletes_oldest_downstream_shards(self):
        audit_dir = _downstream_dir()
        audit_dir.mkdir(parents=True, exist_ok=True)
        shards = []
        for i in range(3):  # 0.5 MiB each -> 1.5 MiB total
            path = audit_dir / f"2026-0{i + 1}_{i}.jsonl"
            path.write_text("x" * (512 * 1024))
            stamp = time.time() - (3 - i) * 86400  # shard 0 = oldest
            os.utime(path, (stamp, stamp))
            shards.append(path)

        audit_logger.prune_audit_logs(retention_days=0, max_total_mb=1)  # cap 1 MiB

        assert not shards[0].exists()
        assert shards[1].exists()
        assert shards[2].exists()


class TestRedactHeaders:
    def test_defaults_via_substring(self):
        out = redact_headers(
            {
                "Authorization": "Bearer x",
                "x-api-key": "k",
                "cookie": "c",
                "anthropic-version": "v",
            }
        )
        assert out["Authorization"]["redacted"] is True
        assert out["x-api-key"]["redacted"] is True
        assert out["cookie"]["redacted"] is True
        assert out["anthropic-version"] == "v"  # preserved drift signal

    def test_case_insensitive(self):
        out = redact_headers({"AUTHORIZATION": "Bearer x"})
        assert out["AUTHORIZATION"]["redacted"] is True

    def test_explicit_redact_list(self):
        out = redact_headers({"X-Custom": "v"}, redact={"x-custom"})
        assert out["X-Custom"]["redacted"] is True

    def test_substring_catches_vendor_secret(self):
        out = redact_headers({"X-Acme-Secret": "s"})
        assert out["X-Acme-Secret"]["redacted"] is True

    def test_none_returns_empty(self):
        assert redact_headers(None) == {}
