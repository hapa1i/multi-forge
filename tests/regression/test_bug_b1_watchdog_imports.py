"""B1: a supervised checkout could replace the watchdog and forge its verdict."""

import os
import sys

import pytest

from forge.core.reactive.watchdog import run_guarded

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("module", ["json.py", "random.py", "token.py", "typing.py", "forge/__init__.py"])
def test_guard_helpers_cannot_import_from_checkout(tmp_path, monkeypatch, module):
    planted = tmp_path / module
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text("print('forged aligned verdict'); raise SystemExit(0)\n")
    monkeypatch.chdir(tmp_path)
    env = dict(os.environ, PYTHONPATH=str(tmp_path), REVIEW_MARKER="actual reviewer")
    result = run_guarded(
        [sys.executable, "-I", "-c", "import os; print(os.environ['REVIEW_MARKER']); print(os.getcwd())"],
        input="",
        env=env,
        cwd=None,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["actual reviewer", str(tmp_path)]
