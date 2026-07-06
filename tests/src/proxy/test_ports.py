"""Tests for shared proxy port probing and caller wrappers."""

from __future__ import annotations

import inspect

import pytest

from forge.proxy import ports, server
from forge.proxy.ports import NoAvailablePortError


def test_find_available_loopback_port_binds_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    bound_addresses: list[tuple[str, int]] = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def bind(self, address: tuple[str, int]) -> None:
            bound_addresses.append(address)

    monkeypatch.setattr(ports.socket, "socket", lambda *_args, **_kwargs: FakeSocket())

    assert ports.find_available_loopback_port(8100, 1) == 8100
    assert bound_addresses == [("127.0.0.1", 8100)]


def test_server_find_available_port_wrapper_preserves_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    signature = inspect.signature(server.find_available_port)
    assert str(signature) == "(start_port: int, max_attempts: int = 10) -> int"

    def _no_port(start_port: int, max_attempts: int) -> int:
        raise NoAvailablePortError

    monkeypatch.setattr(server, "_find_available_loopback_port", _no_port)

    with pytest.raises(RuntimeError, match="Could not find available port in range 8100-8103"):
        server.find_available_port(8100, max_attempts=3)
