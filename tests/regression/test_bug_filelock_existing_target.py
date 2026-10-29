"""GHSA-69hj-f68j-2879: locking must not truncate or chmod an existing target."""

from pathlib import Path
from stat import S_IMODE

import pytest
from filelock import FileLock

pytestmark = pytest.mark.regression


def test_filelock_preserves_existing_target_contents_and_permissions(tmp_path: Path) -> None:
    target = tmp_path / "existing-target"
    original = b"Existing user content must survive a lock acquisition.\n"
    target.write_bytes(original)
    target.chmod(0o640)

    with FileLock(target, mode=0o600).acquire(timeout=1):
        assert target.read_bytes() == original
        assert S_IMODE(target.stat().st_mode) == 0o640

    assert target.read_bytes() == original
    assert S_IMODE(target.stat().st_mode) == 0o640
