"""Loopback port probing shared by proxy startup paths."""

from __future__ import annotations

import socket


class NoAvailablePortError(RuntimeError):
    """Raised when no loopback port is available in the requested range."""


def is_loopback_port_in_use(port: int) -> bool:
    """Return whether a TCP port is unavailable on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return True
        return False


def find_available_loopback_port(start_port: int, max_attempts: int) -> int:
    """Find an available TCP port on 127.0.0.1."""
    for port in range(start_port, start_port + max_attempts):
        if not is_loopback_port_in_use(port):
            return port
    raise NoAvailablePortError
