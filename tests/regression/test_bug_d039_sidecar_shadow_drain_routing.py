"""Regression for D039: sidecar Stop probed a host-only root for shadow candidates.

Deferred markers need host-resolvable paths, but candidate discovery runs inside
the sidecar and must inspect the mounted Forge root. Reusing the marker payload
root for both concerns made a mounted pending candidate invisible.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.hooks import hooks
from forge.core.workqueue import pending_work_dir
from forge.session import IndexStore, create_session_state
from forge.session.artifacts import get_artifact_paths
from forge.session.workers import (
    SESSION_INSTANCE_ENV,
    SIDECAR_LEASE_ENV,
    sidecar_session_lease,
)
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


def test_sidecar_stop_probes_mounted_root_and_enqueues_one_host_resolvable_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container_root = tmp_path / "workspace"
    host_worktree = tmp_path / "host-checkout"
    host_forge_root = tmp_path / "host-main"
    container_root.mkdir()
    host_worktree.mkdir()
    host_forge_root.mkdir()

    session_name = "sidecar-shadow"
    session_id = "sidecar-shadow-uuid"
    transcript = container_root / "transcript.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    state = create_session_state(session_name, worktree_path=str(host_worktree))
    state.confirmed.claude_session_id = session_id
    state.confirmed.transcript_path = str(transcript)

    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge-home"))
    entry = publish_session(IndexStore(), state, host_forge_root, forge_root=host_forge_root)
    assert entry.instance_id is not None
    # Project the mounted manifest into the container namespace. Keep candidates
    # absent from the host-only path so probing the wrong root still fails.
    shutil.copytree(host_forge_root / ".forge", container_root / ".forge")
    shadow_dir = get_artifact_paths(container_root, session_name).shadow_abs
    shadow_dir.mkdir(parents=True)
    (shadow_dir / "candidate.json").write_text('{"status":"pending"}\n', encoding="utf-8")

    monkeypatch.chdir(container_root)
    monkeypatch.setattr("forge.session.workers._sidecar_exit_confirmed", lambda _name: True)
    with sidecar_session_lease(host_forge_root, session_name, expected_instance_id=entry.instance_id) as lease:
        monkeypatch.setenv("FORGE_SESSION", session_name)
        monkeypatch.setenv("FORGE_FORGE_ROOT", str(container_root))
        monkeypatch.setenv("FORGE_SIDECAR", "1")
        monkeypatch.setenv("FORGE_SIDECAR_HOST_WORKTREE_PATH", str(host_worktree))
        monkeypatch.setenv("FORGE_SIDECAR_HOST_FORGE_ROOT", str(host_forge_root))
        monkeypatch.setenv(SESSION_INSTANCE_ENV, entry.instance_id)
        monkeypatch.setenv(SIDECAR_LEASE_ENV, str(lease))
        monkeypatch.setattr("forge.session.workers.SIDECAR_LEASE_MOUNT", str(lease.parent))

        result = CliRunner().invoke(
            hooks,
            ["stop"],
            input=json.dumps(
                {
                    "hook_event_name": "Stop",
                    "session_id": session_id,
                    "transcript_path": str(transcript),
                    "cwd": str(container_root),
                }
            ),
        )

    assert result.exit_code == 0
    assert json.loads(result.output).get("queued_shadow") is True, result.output
    markers = list(pending_work_dir().glob(f"shadow-{session_id}.json"))
    assert len(markers) == 1
    marker = json.loads(markers[0].read_text(encoding="utf-8"))
    assert marker["kind"] == "shadow"
    assert marker["payload"]["worktree_path"] == str(host_worktree)
    assert marker["payload"]["forge_root"] == str(host_forge_root)
    assert marker["payload"]["instance_id"] == entry.instance_id
