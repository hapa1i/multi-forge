import logging
from pathlib import Path

import pytest

from forge.proxy.proxies import ProxyRegistryStore, recover_proxy_id_from_base_url

pytestmark = pytest.mark.regression


def test_proxy_id_recovery_logs_and_find_by_base_url_stays_loud(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = ProxyRegistryStore(tmp_path / "index.json")

    def _boom():
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(store, "read", _boom)

    with caplog.at_level(logging.DEBUG, logger="forge.proxy.proxies"):
        assert recover_proxy_id_from_base_url("http://localhost:8084", store=store) is None

    assert "proxy_id recovery from base_url failed" in caplog.text
    with pytest.raises(RuntimeError, match="registry unavailable"):
        store.find_by_base_url("http://localhost:8084")
