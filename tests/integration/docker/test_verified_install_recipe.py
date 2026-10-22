"""Execute the documented global wheel recipe with real artifact verification."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]
ROOT = Path(__file__).resolve().parents[3]


def test_verified_wheel_recipe_preserves_launcher_on_hash_refusal(
    synced_container: ContainerLike,
) -> None:
    document = (ROOT / "docs/developer/dependency_security.md").read_text()
    recipe = document.split("<!-- verified-wheel-install:start -->", 1)[1].split("```bash\n", 1)[1].split("```", 1)[0]
    setup = synced_container.exec(
        """
set -euo pipefail
recipe_root=$(mktemp -d /tmp/forge-verified-recipe.XXXXXX)
uv build --offline --wheel --build-constraints /forge/requirements/build.txt --require-hashes \
    --out-dir "$recipe_root/dist" /forge >&2
printf '%s' "$recipe_root"
""",
        timeout=180,
    )
    assert setup.returncode == 0, setup.stderr
    root = setup.stdout.strip()
    assert root.startswith("/tmp/forge-verified-recipe.") and "\n" not in root
    script = f"{root}/install.sh"
    written = synced_container.write_file(script, recipe)
    assert written.returncode == 0, written.stderr
    inputs = f"""
set -euo pipefail
unset UV_OFFLINE
export FORGE_CHECKOUT=/forge
export FORGE_WHEEL=$(find {shlex.quote(root)}/dist -name '*.whl' -print -quit)
export FORGE_INSTALL_DIR={shlex.quote(root)}/release
export FORGE_USER_BIN={shlex.quote(root)}/home/.local/bin
"""
    existing_refused = synced_container.exec(inputs + f"""
export FORGE_INSTALL_DIR={shlex.quote(root)}/existing-release
export FORGE_WHEEL_SHA256=$(sha256sum "$FORGE_WHEEL" | cut -d ' ' -f 1)
mkdir "$FORGE_INSTALL_DIR"
printf 'existing installation' > "$FORGE_INSTALL_DIR/sentinel"
if bash {shlex.quote(script)} > {shlex.quote(root)}/existing-refusal.log 2>&1; then
    echo 'Reused an existing installation directory' >&2
    exit 1
fi
test "$(cat "$FORGE_INSTALL_DIR/sentinel")" = 'existing installation'
test ! -e "$FORGE_INSTALL_DIR/venv"
""")
    assert existing_refused.returncode == 0, existing_refused.stderr
    refused = synced_container.exec(inputs + f"""
mkdir -p "$FORGE_USER_BIN"
printf 'previous launcher\n' > "$FORGE_USER_BIN/forge"
export FORGE_WHEEL_SHA256={'0' * 64}
if bash {shlex.quote(script)} > {shlex.quote(root)}/refusal.log 2>&1; then
    echo 'Accepted a wheel with the wrong hash' >&2
    exit 1
fi
test ! -e "$FORGE_INSTALL_DIR"
test "$(cat "$FORGE_USER_BIN/forge")" = 'previous launcher'
cat {shlex.quote(root)}/refusal.log
rm "$FORGE_USER_BIN/forge"
""")
    assert refused.returncode == 0, refused.stderr
    assert "FAILED" in refused.stdout
    installed = synced_container.exec(
        inputs + f"""
export FORGE_WHEEL_SHA256=$(sha256sum "$FORGE_WHEEL" | cut -d ' ' -f 1)
bash {shlex.quote(script)} >&2
export HOME={shlex.quote(root)}/home
export FORGE_HOME="$HOME/.forge"
export PATH="$FORGE_USER_BIN:$PATH"
cd {shlex.quote(root)}
forge --version >&2
forge extension enable --scope user --profile minimal --with hooks --without commands >&2
forge extension doctor --json > doctor.json
"$FORGE_INSTALL_DIR/venv/bin/python" -I - <<'PY'
import json
import os
from pathlib import Path
import forge

doctor = json.loads(Path('doctor.json').read_text())
runtime = json.loads((Path(os.environ['FORGE_HOME']) / 'runtime.json').read_text())
assert Path(forge.__file__).is_relative_to(Path(os.environ['FORGE_INSTALL_DIR']) / 'venv')
assert runtime['forge_binary_path'] == os.environ['FORGE_USER_BIN'] + '/forge'
print(json.dumps({{'doctor': doctor, 'launcher': runtime['forge_binary_path']}}))
PY
""",
        timeout=180,
    )
    assert installed.returncode == 0, installed.stderr
    evidence = json.loads(installed.stdout)
    assert evidence["launcher"] == f"{root}/home/.local/bin/forge"

    directory_refused = synced_container.exec(
        inputs + f"""
export FORGE_INSTALL_DIR={shlex.quote(root)}/blocked-launcher
export FORGE_USER_BIN={shlex.quote(root)}/blocked-bin
export FORGE_WHEEL_SHA256=$(sha256sum "$FORGE_WHEEL" | cut -d ' ' -f 1)
mkdir -p "$FORGE_USER_BIN/forge"
if bash {shlex.quote(script)} > {shlex.quote(root)}/launcher-refusal.log 2>&1; then
    echo 'Accepted an existing directory as the launcher path' >&2
    exit 1
fi
test -x "$FORGE_INSTALL_DIR/venv/bin/forge"
test -d "$FORGE_USER_BIN/forge"
test ! -e "$FORGE_USER_BIN/forge/forge"
test ! -L "$FORGE_USER_BIN/forge/forge"
""",
        timeout=180,
    )
    assert directory_refused.returncode == 0, directory_refused.stderr

    # Corrupt only the runtime artifact allowlist, leaving project metadata and versions intact.
    tampered = synced_container.exec(
        inputs + f"""
mkdir {shlex.quote(root)}/reviewed
cp /forge/pyproject.toml /forge/uv.lock {shlex.quote(root)}/reviewed/
python3 - {shlex.quote(root)}/reviewed/uv.lock <<'PY'
import re
import sys
from pathlib import Path

lock = Path(sys.argv[1])
blocks = lock.read_text().split('[[package]]')
changed = False
for index, block in enumerate(blocks):
    if block.startswith('\\nname = "idna"\\n'):
        blocks[index] = re.sub(r'sha256:[a-f0-9]{{64}}', 'sha256:' + '0' * 64, block)
        changed = blocks[index] != block
assert changed, 'Expected to replace the reviewed idna artifact hashes'
lock.write_text('[[package]]'.join(blocks))
PY
export FORGE_CHECKOUT={shlex.quote(root)}/reviewed
export FORGE_INSTALL_DIR={shlex.quote(root)}/bad-runtime
export FORGE_WHEEL_SHA256=$(sha256sum "$FORGE_WHEEL" | cut -d ' ' -f 1)
previous_target=$(readlink "$FORGE_USER_BIN/forge")
if bash {shlex.quote(script)} > {shlex.quote(root)}/runtime-refusal.log 2>&1; then
    echo 'Accepted a dependency absent from the hash allowlist' >&2
    exit 1
fi
test "$(readlink "$FORGE_USER_BIN/forge")" = "$previous_target"
cat {shlex.quote(root)}/runtime-refusal.log
""",
        timeout=180,
    )
    assert tampered.returncode == 0, tampered.stderr
    assert "idna" in tampered.stdout
    assert "Hash mismatch" in tampered.stdout
