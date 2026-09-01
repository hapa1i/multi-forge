"""Regression: QA step 18.4 must clean its project after an early failure."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

REPO_ROOT = Path(__file__).resolve().parents[2]
FRAGMENT = REPO_ROOT / "src" / "skills" / "qa" / "resources" / "checklist" / "18-disable.md"


def _step_18_4_code() -> str:
    text = FRAGMENT.read_text(encoding="utf-8")
    section = text.split("### 18.4 ", 1)[1].split("\n---", 1)[0]
    match = re.search(r"```bash\n(.*?)\n```", section, flags=re.DOTALL)
    assert match is not None
    return match.group(1)


def test_failed_enable_runs_disable_and_removes_disposable_root(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    events = tmp_path / "events.log"
    fake_forge = fake_bin / "forge"
    fake_forge.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s|%s\\n" "$PWD" "$*" >> "$FORGE_QA_CLEANUP_EVENTS"\n'
        'if [[ "$*" == *"extension enable"* ]]; then exit 42; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake_forge.chmod(0o755)
    test_repo = tmp_path / "test-repo"
    test_repo.mkdir()
    forge_home = tmp_path / "forge-home"
    forge_home.mkdir()
    env = {
        **os.environ,
        "FORGE_HOME": str(forge_home),
        "FORGE_QA_CLEANUP_EVENTS": str(events),
        "FORGE_TEST_REPO": str(test_repo),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }

    result = subprocess.run(
        ["bash", "-c", _step_18_4_code()],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    recorded = events.read_text(encoding="utf-8").splitlines()
    assert result.returncode == 42
    assert "extension enable" in recorded[0]
    assert "extension disable --scope project --yes" in recorded[1]
    disposable_root = Path(recorded[1].split("|", 1)[0])
    assert not disposable_root.exists()
