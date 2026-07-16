"""Regression coverage for the top-level setup script."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SETUP_SCRIPT = Path(__file__).parents[3] / "scripts" / "setup.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_uninstall_disables_all_extensions_noninteractively(tmp_path: Path) -> None:
    """setup.sh must use disable's --yes confirmation bypass, not removed --force."""
    home = tmp_path / "home"
    forge_home = home / ".forge-test"
    forge_bin = forge_home / "bin"
    fake_bin = tmp_path / "bin"
    invocation_log = tmp_path / "forge-invocations"
    forge_bin.mkdir(parents=True)
    fake_bin.mkdir()
    (forge_home / ".forge-home").write_text("managed-by-setup-sh\n", encoding="utf-8")

    _write_executable(
        forge_bin / "forge",
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$FORGE_INVOCATIONS"\n',
    )
    for command in ("python3", "pip3", "pip", "docker"):
        _write_executable(fake_bin / command, "#!/bin/sh\nexit 1\n")
    _write_executable(fake_bin / "uv", "#!/bin/sh\nexit 0\n")

    env = {
        **os.environ,
        "HOME": str(home),
        "FORGE_HOME": str(forge_home),
        "FORGE_INVOCATIONS": str(invocation_log),
        "PATH": os.pathsep.join((str(fake_bin), "/usr/bin", "/bin")),
    }
    result = subprocess.run(
        ["/bin/bash", str(SETUP_SCRIPT), "--uninstall", "--yes"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert invocation_log.read_text(encoding="utf-8").splitlines() == [
        "info",
        "extension disable --all --yes",
    ]
