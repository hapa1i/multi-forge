"""Consumer wheel smoke must not silently retain developer dependency constraints."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

pytestmark = pytest.mark.regression
REPO_ROOT = Path(__file__).resolve().parents[2]
CONSTRAINT_ENV = (
    "UV_BUILD_CONSTRAINT",
    "UV_CONSTRAINT",
    "UV_OVERRIDE",
    "UV_EXCLUDE",
    "UV_EXCLUDE_NEWER",
    "UV_CONFIG_FILE",
)


@pytest.mark.parametrize("unconstrained", [False, True])
def test_wheel_smoke_separates_consumer_resolution_from_locked_install(tmp_path: Path, unconstrained: bool) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "test-wheel-runtime.sh"
    shutil.copyfile(REPO_ROOT / "scripts/test-wheel-runtime.sh", script)
    shutil.copyfile(REPO_ROOT / "scripts/wheel-smoke-cleanup.py", scripts / "wheel-smoke-cleanup.py")
    (tmp_path / "uv.toml").write_text('constraint-dependencies = ["example==1.0"]\n')
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls_path = tmp_path / "uv-calls.jsonl"
    uv = fake_bin / "uv"
    python_stub = f'#!/bin/sh\n[ "$1" = -c ] && exit 0\nexec {shlex.quote(sys.executable)} "$@"\n'
    forge_stub = f"#!{sys.executable}\n" + dedent("""\
        import json, os, sys
        from pathlib import Path
        if sys.argv[3] == 'start':
            port = int(sys.argv[-1])
            process_id = f'litellm-{port}'
            registry = Path(os.environ['FORGE_HOME']) / 'backends/index.json'
            registry.parent.mkdir(parents=True, exist_ok=True)
            registry.write_text(json.dumps({'version': 2, 'processes': {process_id: {
                'process_id': process_id, 'adapter_type': 'litellm', 'port': port, 'pid': 2147483647,
            }}}))
        """)
    uv.write_text(f"#!{sys.executable}\n" + dedent(f"""\
            import json, os, sys
            from pathlib import Path
            args = sys.argv[1:]
            with Path({str(calls_path)!r}).open('a') as stream:
                stream.write(json.dumps({{'args': args, 'constraints': {{
                    key: os.environ[key] for key in {CONSTRAINT_ENV!r} if key in os.environ
                }}}}) + '\\n')
            if args[0] == 'build':
                directory = Path(args[args.index('--out-dir') + 1])
                (directory / 'multi_forge-test.whl').touch()
            elif args[0] == 'venv':
                directory = Path(args[-1]) / 'bin'
                directory.mkdir(parents=True)
                for name, source in {{'python': {python_stub!r}, 'forge': {forge_stub!r}}}.items():
                    executable = directory / name
                    executable.write_text(source)
                    executable.chmod(0o755)
            """))
    uv.chmod(0o755)
    curl = fake_bin / "curl"
    curl.write_text("#!/bin/sh\nexit 0\n")
    curl.chmod(0o755)

    result = subprocess.run(
        ["bash", str(script), *(["--unconstrained"] if unconstrained else [])],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            **{key: "inherited-constraint" for key in CONSTRAINT_ENV},
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
    build = next(call["args"] for call in calls if call["args"][0] == "build")
    assert "--require-hashes" in build and "--build-constraints" in build
    installs = [call for call in calls if call["args"][:2] == ["pip", "install"]]
    if unconstrained:
        assert len(installs) == 1
        assert installs[0]["constraints"] == {}
        assert installs[0]["args"][2:4] == ["--no-config", "--python"]
        assert len(installs[0]["args"]) == 6
        assert installs[0]["args"][-1].endswith("/multi_forge-test.whl")
        assert not any(call["args"][0] == "export" for call in calls)
    else:
        assert len(installs) == 2
        assert "--require-hashes" in installs[0]["args"] and "--no-build" in installs[0]["args"]
        assert "--no-deps" in installs[1]["args"]
        assert any(call["args"][0] == "export" and "--locked" in call["args"] for call in calls)
