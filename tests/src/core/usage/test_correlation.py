"""Tests for direct-path request correlation primitives (Phase 4c).

``with_forge_request_id`` forwards an ``X-Request-ID`` without clobbering or
mutating the caller's hyperparameters; ``target_is_forge_proxy`` only returns
True for a base_url registered as a Forge proxy (else a stamped
``cost_request_id`` would dangle).
"""

from __future__ import annotations

import json

from forge.core.llm import ModelHyperparameters
from forge.core.usage.correlation import mint_request_id, target_is_forge_proxy, with_forge_request_id
from forge.proxy.proxies import get_proxy_registry_path


class TestWithForgeRequestId:
    def test_adds_header_from_none(self) -> None:
        hp = with_forge_request_id(None, "req_x")
        assert hp.extra["openai"]["extra_headers"]["X-Request-ID"] == "req_x"

    def test_merges_without_clobbering(self) -> None:
        base = ModelHyperparameters(extra={"openai": {"extra_headers": {"User-Agent": "ua"}}})
        hp = with_forge_request_id(base, "req_y")
        assert hp.extra["openai"]["extra_headers"] == {"User-Agent": "ua", "X-Request-ID": "req_y"}

    def test_does_not_mutate_caller(self) -> None:
        base = ModelHyperparameters(extra={"openai": {"extra_headers": {"User-Agent": "ua"}}})
        with_forge_request_id(base, "req_z")
        assert base.extra == {"openai": {"extra_headers": {"User-Agent": "ua"}}}

    def test_mint_request_id_prefix(self) -> None:
        rid = mint_request_id()
        assert rid.startswith("req_") and len(rid) > len("req_")


class TestTargetIsForgeProxy:
    def _write_registry(self, base_url: str) -> None:
        path = get_proxy_registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "proxies": {
                        "p1": {
                            "proxy_id": "p1",
                            "template": "litellm-gemini",
                            "base_url": base_url,
                            "port": 8084,
                        }
                    },
                }
            )
        )

    def test_none_is_false(self) -> None:
        assert target_is_forge_proxy(None) is False

    def test_no_registry_is_false(self) -> None:
        assert target_is_forge_proxy("http://localhost:8084") is False

    def test_registered_url_is_true(self) -> None:
        self._write_registry("http://localhost:8084")
        assert target_is_forge_proxy("http://localhost:8084") is True

    def test_trailing_slash_normalized(self) -> None:
        self._write_registry("http://localhost:8084")
        assert target_is_forge_proxy("http://localhost:8084/") is True

    def test_unregistered_url_is_false(self) -> None:
        self._write_registry("http://localhost:8084")
        assert target_is_forge_proxy("http://localhost:9999") is False
