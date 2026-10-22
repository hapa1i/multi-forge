"""Build pin checks must work when the system python3 predates stdlib tomllib."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

pytestmark = pytest.mark.regression
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("check_status", [0, 9])
def test_make_build_checks_with_supported_python_before_building(tmp_path: Path, check_status: int) -> None:
    shutil.copyfile(REPO_ROOT / "Makefile", tmp_path / "Makefile")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "check-dependency-pins.py").write_text(
        "import sys, tomllib\n"
        "from pathlib import Path\n"
        "assert sys.version_info >= (3, 11)\n"
        "assert sys.flags.no_site\n"
        "Path('checked').touch()\n"
        f"raise SystemExit({check_status})\n"
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    old_python = fake_bin / "python3"
    old_python.write_text("#!/bin/sh\necho 'ModuleNotFoundError: tomllib' >&2\nexit 89\n")
    old_python.chmod(0o755)
    uv = fake_bin / "uv"
    uv.write_text(f"#!{sys.executable}\n" + dedent(f"""\
            import json, sys
            from pathlib import Path
            args = sys.argv[1:]
            with Path('uv-calls.jsonl').open('a') as stream:
                stream.write(json.dumps(args) + '\\n')
            if args[:2] == ['python', 'find']:
                assert args[2:] == ['--no-project', '--no-config', '>=3.11,<3.14']
                print({sys.executable!r})
            elif args[0] == 'build':
                assert Path('checked').exists()
            else:
                raise AssertionError('Project setup attempted before the pin check: ' + repr(args))
            """))
    uv.chmod(0o755)

    result = subprocess.run(
        ["make", "build"],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    calls = [json.loads(line) for line in (tmp_path / "uv-calls.jsonl").read_text().splitlines()]
    assert (tmp_path / "checked").exists(), result.stderr
    assert (result.returncode == 0) == (check_status == 0), result.stderr
    if check_status == 0:
        assert calls[1:] == [
            [
                "build",
                "--build-constraints",
                "requirements/build.txt",
                "--require-hashes",
            ]
        ]
    else:
        assert len(calls) == 1, "A rejected pin check must prevent all builds."
