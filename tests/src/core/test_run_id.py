"""Tests for the run-id format leaf module (mint + validate).

The proxy validates inbound ``X-Forge-Run-ID``/``X-Forge-Root-Run-ID`` headers with
``is_valid_run_id`` before logging them (Slice 4g), so the format guard must reject
malformed, spoofed, and header-injection values -- not just accept well-formed ones.
"""

from __future__ import annotations

import pytest

from forge.core.run_id import RUN_ID_RE, is_valid_run_id, mint_run_id


def test_mint_is_valid_and_shaped() -> None:
    rid = mint_run_id()
    assert rid.startswith("run_")
    assert len(rid) == len("run_") + 12
    assert is_valid_run_id(rid)
    assert RUN_ID_RE.match(rid)


def test_mint_is_unique() -> None:
    assert mint_run_id() != mint_run_id()


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "run_",  # no hex
        "run_short",  # not 12 hex
        "run_7e81a1bb765",  # 11 hex
        "run_7e81a1bb765d0",  # 13 hex
        "run_7E81A1BB765D",  # uppercase (mint is lowercase)
        "req_7e81a1bb765d",  # wrong prefix (proxy request id, not a run id)
        "run_7e81a1bb765g",  # non-hex char
        " run_7e81a1bb765d",  # leading space
        "run_7e81a1bb765d ",  # trailing space
        "run_7e81a1bb765d\nX-Evil: injected",  # header injection
        "x: y\nX-Forge-Run-ID: run_7e81a1bb765d",  # spoof attempt
    ],
)
def test_rejects_malformed_and_injection(value: str | None) -> None:
    assert not is_valid_run_id(value)
