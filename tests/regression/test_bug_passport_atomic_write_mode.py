"""Regression: atomic passport rewrites must retain the authored document mode."""

import stat
from pathlib import Path

import pytest

from forge.session.passport import Passport, write_passport

pytestmark = pytest.mark.regression


def test_passport_write_preserves_existing_file_mode(tmp_path: Path) -> None:
    doc = tmp_path / "memory.md"
    doc.write_text("# Memory\n")
    doc.chmod(0o644)

    write_passport(doc, Passport(version=1, intent="Project documentation"))

    assert stat.S_IMODE(doc.stat().st_mode) == 0o644
