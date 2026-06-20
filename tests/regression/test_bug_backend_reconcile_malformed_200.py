"""Regression: malformed-but-parseable OpenRouter 200 bodies map to unavailable, not found.

Bug class: misleading remote reconciliation. A 200 whose JSON parses but is not a generation
object (a JSON array/string/number, or a non-dict ``data`` wrapper) was treated as a successful
``found`` record with empty metadata, so ``forge backend reconcile`` could report a join when the
remote body was unusable. Such bodies must surface as ``unavailable``.

Root cause: ``_record_from_body`` fell back to ``data = payload`` (or ``{}``) for any non-dict
shape instead of rejecting it.

Affected: src/forge/backend/remote/openrouter.py (``OpenRouterRemoteAdapter._record_from_body``).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from forge.backend.remote.openrouter import OpenRouterRemoteAdapter

pytestmark = pytest.mark.regression


class _Resp:
    status_code = 200

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _Client:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def __enter__(self) -> "_Client":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def get(self, *args: Any, **kwargs: Any) -> _Resp:
        return _Resp(self._payload)


@pytest.fixture(autouse=True)
def _key_and_home(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)


@pytest.mark.parametrize(
    "payload",
    [[], ["not", "a", "record"], "oops", 3, {"data": []}, {"data": "oops"}, {"data": None}],
)
def test_parseable_malformed_200_body_is_unavailable(monkeypatch, payload: Any) -> None:
    monkeypatch.setattr(httpx, "Client", lambda **_kw: _Client(payload))
    rec = OpenRouterRemoteAdapter().lookup_remote_record("gen-x")
    assert rec.outcome == "unavailable"
    assert rec.http_status == 200
    assert rec.detail == "malformed response body"
