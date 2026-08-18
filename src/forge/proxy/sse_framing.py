"""Incremental framing for JSON events carried by SSE data lines."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class SseJsonDataFramer:
    """Deliver decoded JSON values from complete SSE ``data:`` lines.

    Framing is a best-effort side tap: incomplete lines stay buffered, while
    non-data lines, empty data, ``[DONE]``, invalid UTF-8, and malformed JSON
    are ignored without retaining or logging payload content. The callback owns
    protocol semantics and any exception it raises.
    """

    def __init__(self, on_event: Callable[[Any], None]) -> None:
        self._on_event = on_event
        self._buffer = ""

    def feed(self, chunk: bytes) -> None:
        """Consume one copied stream chunk without mutating forwarded bytes."""
        try:
            decoded = chunk.decode("utf-8")
        except UnicodeDecodeError:
            logger.debug("Ignoring invalid UTF-8 bytes in SSE chunk")
            decoded = chunk.decode("utf-8", errors="ignore")
        except Exception:  # pragma: no cover - bytes.decode is the typed path
            logger.debug("Ignoring undecodable SSE chunk")
            return

        self._buffer += decoded
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.strip()
            if not line.startswith("data:"):
                continue

            data = line.removeprefix("data:").strip()
            if not data or data == "[DONE]":
                continue
            try:
                event = json.loads(data)
            except (TypeError, ValueError):
                logger.debug("Ignoring malformed SSE JSON data line")
                continue
            self._on_event(event)
