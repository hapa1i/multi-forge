"""Forge build constraints must not become policy for projects using its images."""

from __future__ import annotations

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


def test_unrelated_project_can_select_its_own_backend_dependency(synced_container: ContainerLike) -> None:
    result = synced_container.exec(
        r"""
python - <<'PY'
import os
import subprocess
import tempfile
import textwrap
import zipfile
from pathlib import Path

assert "UV_BUILD_CONSTRAINT" not in os.environ
with tempfile.TemporaryDirectory(prefix="forge-build-policy-") as directory:
    root = Path(directory)
    wheels = root / "wheels"
    wheels.mkdir()
    # This local fixture deliberately conflicts with Forge's packaging pin.
    with zipfile.ZipFile(wheels / "packaging-0.0.0-py3-none-any.whl", "w") as wheel:
        wheel.writestr("packaging/__init__.py", '__version__ = "0.0.0"\n')
        wheel.writestr("packaging-0.0.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: packaging\nVersion: 0.0.0\n")
        wheel.writestr("packaging-0.0.0.dist-info/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        wheel.writestr("packaging-0.0.0.dist-info/RECORD", "")
    project = root / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(textwrap.dedent('''
        [build-system]
        requires = ["packaging==0.0.0"]
        build-backend = "backend"
        backend-path = ["."]
    '''))
    (project / "backend.py").write_text(textwrap.dedent('''
        from pathlib import Path
        from zipfile import ZipFile
        import packaging

        def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
            assert packaging.__version__ == "0.0.0"
            filename = "unrelated-0.0.0-py3-none-any.whl"
            with ZipFile(Path(wheel_directory) / filename, "w") as wheel:
                wheel.writestr("unrelated-0.0.0.dist-info/METADATA", "Metadata-Version: 2.1\\nName: unrelated\\nVersion: 0.0.0\\n")
                wheel.writestr("unrelated-0.0.0.dist-info/WHEEL", "Wheel-Version: 1.0\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n")
                wheel.writestr("unrelated-0.0.0.dist-info/RECORD", "")
            return filename
    '''))
    subprocess.run(
        ["uv", "build", "--wheel", "--offline", "--no-index", "--find-links", str(wheels),
         "--cache-dir", str(root / "cache")],
        cwd=project, check=True,
    )
    assert (project / "dist/unrelated-0.0.0-py3-none-any.whl").is_file()
PY
""",
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_forge_backend_cache_still_supports_hash_verified_offline_build(synced_container: ContainerLike) -> None:
    result = synced_container.exec(
        """
set -eu
build_directory=$(mktemp -d /tmp/forge-offline-wheel.XXXXXX)
trap 'rm -rf "$build_directory"' EXIT
uv build /forge --wheel --offline --build-constraints /forge/requirements/build.txt --require-hashes \
    --out-dir "$build_directory"
test -n "$(find "$build_directory" -name '*.whl' -print -quit)"
""",
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
