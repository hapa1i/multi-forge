"""Regression: a newer-schema audit drift baseline must not be silently downgraded.

Bug (audit P2 #7, low): _load_drift_baseline gated on schema_version == AUDIT_SCHEMA_VERSION
(strict equality), so a baseline written by a NEWER Forge yielded an empty baseline and was then
downgrade-overwritten to the current version with NO notice -- diverging from read_audit_logs,
which warns on newer-schema records and skips them.

Fix: _load_drift_baseline warns once and freezes the proxy; _persist_drift_baseline refuses to
overwrite a frozen (newer-schema) baseline (proxy/audit_logger.py).
"""

from __future__ import annotations

import pytest

from forge.core.state import atomic_write_json, read_json
from forge.proxy import audit_logger
from forge.proxy.audit_logger import AUDIT_SCHEMA_VERSION

pytestmark = pytest.mark.regression


@pytest.fixture(autouse=True)
def _reset_drift_state():
    """Module-level drift caches persist across tests; reset them around this one."""
    for store in (audit_logger._drift_state, audit_logger._drift_state_frozen):
        store.clear()
    audit_logger._warned_newer_schema = False
    yield
    for store in (audit_logger._drift_state, audit_logger._drift_state_frozen):
        store.clear()
    audit_logger._warned_newer_schema = False


def test_newer_schema_drift_baseline_not_downgraded() -> None:
    proxy_id = "p1"
    state_path = audit_logger._audit_state_path(proxy_id)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    newer = {"schema_version": AUDIT_SCHEMA_VERSION + 1, "last_seen": {"system_prompt": "sha256:NEWER"}}
    atomic_write_json(state_path, newer)

    # Load must not adopt the newer baseline; it freezes the proxy instead.
    baseline = audit_logger._load_drift_baseline(proxy_id)
    assert baseline == {}
    assert proxy_id in audit_logger._drift_state_frozen

    # A subsequent drift write must NOT downgrade-overwrite the newer file.
    audit_logger.check_and_record_drift(
        proxy_id=proxy_id,
        dimension="system_prompt",
        current_hash="sha256:CURRENT",
        request_id="r1",
        route={},
    )
    persisted = read_json(state_path)
    assert persisted["schema_version"] == AUDIT_SCHEMA_VERSION + 1, "newer-schema file must not be downgraded"
    assert persisted["last_seen"] == {"system_prompt": "sha256:NEWER"}
