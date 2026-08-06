"""D011 regression: a shared JSON read OSError is unreadable state, not corruption.

Root cause: ``read_json`` wrapped ``OSError`` from ``open()`` in
``StateCorruptedError``, allowing callers such as the workqueue to quarantine bytes
whose contents had never been shown to be malformed.
"""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from forge.core.state import StateUnreadableError, read_json

pytestmark = pytest.mark.regression


def test_read_oserror_is_unreadable_and_preserves_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "state.json"
    original = b'{"schema_version": 1}\n'
    target.write_bytes(original)

    real_open = builtins.open
    failed = False

    def fail_first_target_read(file, *args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal failed
        if Path(file) == target and not failed:
            failed = True
            raise OSError("simulated transient read failure")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fail_first_target_read)

    with pytest.raises(StateUnreadableError, match="simulated transient read failure"):
        read_json(target)

    assert target.read_bytes() == original
