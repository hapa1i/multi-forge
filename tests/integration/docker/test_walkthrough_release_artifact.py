"""Exact-wheel isolation contract for the packaged walkthrough frontend."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import zipfile
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.docker_host]
REPO_ROOT = Path(__file__).resolve().parents[3]


def test_walkthrough_setup_report_and_cleanup_resolve_from_one_wheel(
    tmp_path: Path, forge_test_image: str | None
) -> None:
    assert forge_test_image is not None, "walkthrough artifact isolation requires the Docker-host test lane"
    built = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path), str(REPO_ROOT)],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert built.returncode == 0, built.stderr
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1
    wheel = wheels[0]
    wheel_sha256 = hashlib.sha256(wheel.read_bytes()).hexdigest()

    wheel_resources: dict[str, str] = {}
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.namelist():
            marker = "forge/_extensions/skills/walkthrough/"
            if marker not in member or member.endswith("/"):
                continue
            relative = member.split(marker, 1)[1]
            wheel_resources[relative] = hashlib.sha256(archive.read(member)).hexdigest()

    required = {
        "SKILL.md",
        "resources/checklist.md",
        "resources/journey-map.md",
        "scripts/claude-wrapper.sh",
        "scripts/cleanup-owned.sh",
        "scripts/package-identity.py",
        "scripts/protected-paths.py",
        "scripts/run-in-repo.sh",
        "scripts/setup-test-repo.sh",
        "scripts/walkthrough-report.py",
        "scripts/walkthrough-state.py",
    }
    assert required <= set(wheel_resources)

    probe = r"""
set -euo pipefail
uv venv /opt/forge-walkthrough >/tmp/venv.log
cp -a /forge/.venv/lib/python3.12/site-packages/. /opt/forge-walkthrough/lib/python3.12/site-packages/
rm -rf \
  /opt/forge-walkthrough/lib/python3.12/site-packages/forge \
  /opt/forge-walkthrough/lib/python3.12/site-packages/multi_forge-*.dist-info \
  /opt/forge-walkthrough/lib/python3.12/site-packages/_editable_impl_multi_forge.pth
uv pip install --python /opt/forge-walkthrough/bin/python --no-deps --offline "/artifact/__WHEEL__" >/tmp/pip.log
export PATH="/opt/forge-walkthrough/bin:/usr/local/bin:/usr/bin:/bin"
export HOME=/tmp/walkthrough-native-home
export FORGE_HOME="$HOME/.forge"
export CLAUDE_HOME="$HOME/.claude"
export CODEX_HOME="$HOME/.codex"
mkdir -p /tmp/walkthrough-project "$HOME"
cd /tmp/walkthrough-project
git init -q
git config user.email forge-test@localhost
git config user.name "Forge Test"
forge extension enable --scope user --profile standard --runtime claude >/tmp/enable.log
skill="$CLAUDE_HOME/skills/walkthrough"
test -f "$skill/.forge-package.json"
for path in \
  SKILL.md \
  resources/checklist.md \
  resources/journey-map.md \
  scripts/claude-wrapper.sh \
  scripts/cleanup-owned.sh \
  scripts/package-identity.py \
  scripts/protected-paths.py \
  scripts/run-in-repo.sh \
  scripts/setup-test-repo.sh \
  scripts/walkthrough-report.py \
  scripts/walkthrough-state.py; do
  test -f "$skill/$path"
done
python3 "$skill/scripts/package-identity.py" --skill-root "$skill" >/tmp/package-identity.json
export FORGE_TEST_REPO=/tmp/walkthrough-sandbox
bash "$skill/scripts/setup-test-repo.sh"
bash "$skill/scripts/run-in-repo.sh" true
bash "$skill/scripts/run-in-repo.sh" claude --version >/tmp/walkthrough-claude-version.log
bash "$skill/scripts/run-in-repo.sh" python3 "$skill/scripts/protected-paths.py" capture .forge/walkthrough/real-system.json
state="$FORGE_TEST_REPO/.forge/walkthrough/progress.json"
python3 "$skill/scripts/walkthrough-state.py" "$skill/resources/checklist.md" init "$state"
for pair in \
  'RUN_OPTIONS=codex=false,sidecar=false' \
  'RUN_STARTED_EPOCH=1000' \
  'CODEX_AUTH_MODE=none' \
  'DECLARED_HUMAN_CHECKPOINTS=7' \
  'HUMAN_CHECKPOINTS_OBSERVED=0' \
  'DECLARED_PAID_OPERATIONS=2' \
  'PAID_OPERATIONS_OBSERVED=0'; do
  key="${pair%%=*}"
  value="${pair#*=}"
  python3 "$skill/scripts/walkthrough-state.py" "$skill/resources/checklist.md" var "$state" set "$key" "$value" >/dev/null
done
python3 "$skill/scripts/walkthrough-state.py" "$skill/resources/checklist.md" index >/tmp/index.json
python3 "$skill/scripts/walkthrough-state.py" "$skill/resources/checklist.md" report "$state" >/tmp/state-report.json
python3 "$skill/scripts/walkthrough-report.py" \
  --checklist "$skill/resources/checklist.md" \
  --parser "$skill/scripts/walkthrough-state.py" \
  --state "$state" \
  --package-identity /tmp/package-identity.json \
  --output-dir /tmp/walkthrough-report \
  --ended-epoch 1001 >/tmp/run-metrics.json
WALKTHROUGH_SIDECAR_MAY_EXIST=false bash "$skill/scripts/run-in-repo.sh" bash "$skill/scripts/cleanup-owned.sh" all
WALKTHROUGH_SIDECAR_MAY_EXIST=false bash "$skill/scripts/run-in-repo.sh" bash "$skill/scripts/cleanup-owned.sh" all
bash "$skill/scripts/run-in-repo.sh" python3 "$skill/scripts/protected-paths.py" compare .forge/walkthrough/real-system.json
mkdir -p /tmp/foreign-project "$FORGE_TEST_REPO/.forge/artifacts"
printf 'preserve\n' > "$FORGE_TEST_REPO/.forge/artifacts/foreign-registry-proof.txt"
python3 - "$FORGE_TEST_REPO/.forge-home/installed.json" <<'PY'
import json
import pathlib
import sys

pathlib.Path(sys.argv[1]).write_text(json.dumps({
    "version": 3,
    "installations": {
        "local:/tmp/foreign-project": {
            "scope": "local",
            "mode": "copy",
            "profile": "standard",
            "project_path": "/tmp/foreign-project",
        },
    },
}))
PY
if bash "$skill/scripts/setup-test-repo.sh" --reset >/tmp/foreign-reset.out 2>/tmp/foreign-reset.err; then
  echo "ERROR: reset accepted a foreign sandbox-registry row" >&2
  exit 1
fi
grep -F "installations outside walkthrough ownership" /tmp/foreign-reset.err >/dev/null
test -f "$FORGE_TEST_REPO/.forge/artifacts/foreign-registry-proof.txt"
test -f "$FORGE_TEST_REPO/.forge-home/installed.json"
/opt/forge-walkthrough/bin/python -I - <<'PY'
import hashlib
import importlib.metadata
import json
import pathlib
import forge

skill = pathlib.Path("/tmp/walkthrough-native-home/.claude/skills/walkthrough")
hashes = {
    path.relative_to(skill).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in skill.rglob("*")
    if path.is_file() and path.name != ".forge-package.json"
}
print(json.dumps({
    "version": importlib.metadata.version("multi-forge"),
    "wheel_sha256": hashlib.sha256(pathlib.Path("/artifact/__WHEEL__").read_bytes()).hexdigest(),
    "forge_file": forge.__file__,
    "resource_hashes": hashes,
    "identity": json.loads(pathlib.Path("/tmp/package-identity.json").read_text()),
    "index": json.loads(pathlib.Path("/tmp/index.json").read_text()),
    "metrics": json.loads(pathlib.Path("/tmp/run-metrics.json").read_text()),
}))
PY
""".replace("__WHEEL__", wheel.name)

    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{tmp_path}:/artifact:ro",
            "-w",
            "/tmp",
            forge_test_image,
            "bash",
            "-c",
            probe,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r}\nstderr={result.stderr!r}\nprobe={shlex.quote(probe)}"
    evidence = json.loads(result.stdout.strip().splitlines()[-1])
    assert evidence["forge_file"].startswith("/opt/forge-walkthrough/")
    assert evidence["wheel_sha256"] == wheel_sha256
    assert evidence["index"]["version"] == "2.0.0"
    assert evidence["index"]["total_assertions"] == 145
    assert evidence["identity"]["package_tree_matches_marker"] is True
    assert evidence["identity"]["package_matches_answering_distribution"] is True
    assert evidence["identity"]["answering_distribution_kind"] == "installed"
    assert evidence["identity"]["answering_distribution_issue"] is None
    assert evidence["identity"]["walkthrough_payload_present"] is True
    assert evidence["metrics"]["verdict"] == "incomplete"
    assert evidence["resource_hashes"] == wheel_resources
