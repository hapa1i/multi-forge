"""O077 regressions for ambiguous policy-check content selectors."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from forge.cli.main import main

pytestmark = pytest.mark.regression


class _TrackingInput(io.BytesIO):
    """Track content reads while allowing Click's zero-byte type probe."""

    def __init__(self, value: bytes) -> None:
        super().__init__(value)
        self.content_reads = 0

    def read(self, size: int | None = -1) -> bytes:
        if size != 0:
            self.content_reads += 1
        return super().read(size)


@pytest.mark.parametrize("file_selector", ["--file", "-f"])
def test_policy_check_rejects_file_and_diff_before_reading_either_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_selector: str,
) -> None:
    source = tmp_path / "source.py"
    source.write_text("original = True\n")
    stdin = _TrackingInput(b"+++ b/source.py\n+replacement = True\n")

    original_read_text = Path.read_text
    file_reads: list[Path] = []

    def guarded_read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        if path == source:
            file_reads.append(path)
            raise AssertionError("policy check read --file despite the conflicting --diff selector")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    result = CliRunner().invoke(
        main,
        ["policy", "check", "--bundle", "tdd", file_selector, str(source), "--diff"],
        input=stdin,
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Options --file and --diff cannot be used together" in result.stderr
    assert stdin.content_reads == 0
    assert file_reads == []
