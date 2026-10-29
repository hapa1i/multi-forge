"""Offline pin checks must use the admitted interpreter, not the project preference."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression
ROOT = Path(__file__).resolve().parents[2]


def test_pin_checker_exports_when_project_python_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copyfile(ROOT / name, tmp_path / name)
    shutil.copytree(ROOT / "requirements", tmp_path / "requirements")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    checker = scripts / "check-dependency-pins.py"
    shutil.copyfile(ROOT / "scripts/check-dependency-pins.py", checker)
    # This supported minor's unavailable patch reproduces CI having only Python 3.11.
    (tmp_path / ".python-version").write_text("3.13.99\n")
    monkeypatch.delenv("UV_PYTHON", raising=False)
    monkeypatch.setenv("UV_PYTHON_DOWNLOADS", "never")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "uv-cache"))
    tracked = [tmp_path / "uv.lock", *sorted((tmp_path / "requirements").glob("*.txt"))]
    before = {path: path.read_bytes() for path in tracked}

    control = subprocess.run(
        ["uv", "export", "--locked", "--offline", "--no-emit-project"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert control.returncode != 0
    assert "No interpreter found for Python 3.13.99" in control.stderr

    checked = subprocess.run(
        [sys.executable, "-S", str(checker)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr
    assert "Dependency constraints match uv.lock." in checked.stdout
    assert {path: path.read_bytes() for path in tracked} == before
