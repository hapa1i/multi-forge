"""Keep startup diagnostics when the wheel smoke removes its temporary install."""

import os
import subprocess
from pathlib import Path
from textwrap import dedent

import pytest

pytestmark = pytest.mark.regression


def test_failed_backend_start_prints_log_before_cleanup(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    smoke_temps = tmp_path / "smoke"
    smoke_temps.mkdir()
    stopped = tmp_path / "stopped"
    programs = {
        "uv": """\
            #!/usr/bin/env bash
            set -eu
            case "$1" in
                build)
                    touch "$4/multi_forge-test.whl"
                    ;;
                venv)
                    mkdir -p "$4/bin"
                    cp "$SMOKE_TEST_BIN/forge" "$SMOKE_TEST_BIN/python" "$4/bin/"
                    ;;
            esac
            """,
        "python": "#!/usr/bin/env bash\nexit 0\n",
        "forge": """\
            #!/usr/bin/env bash
            set -eu
            case "$3" in
                start)
                    mkdir -p "$FORGE_HOME/logs/backend"
                    echo 'RuntimeError: startup diagnostic' > "$FORGE_HOME/logs/backend/litellm-49177.log"
                    exit 23
                    ;;
                stop)
                    touch "$SMOKE_TEST_STOPPED"
                    ;;
            esac
            """,
    }
    for name, program in programs.items():
        executable = fake_bin / name
        executable.write_text(dedent(program))
        executable.chmod(0o755)

    script = Path(__file__).resolve().parents[2] / "scripts" / "test-wheel-runtime.sh"
    result = subprocess.run(
        ["bash", str(script)],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "TMPDIR": str(smoke_temps),
            "FORGE_WHEEL_SMOKE_PORT": "49177",
            "SMOKE_TEST_BIN": str(fake_bin),
            "SMOKE_TEST_STOPPED": str(stopped),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 23
    assert "RuntimeError: startup diagnostic" in result.stderr
    assert stopped.exists()
    assert not list(smoke_temps.iterdir())
