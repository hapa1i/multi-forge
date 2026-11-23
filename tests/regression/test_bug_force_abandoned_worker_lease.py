"""Explicit cleanup can clear only the abandoned worker leases the user reviewed."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.paths import get_forge_home
from forge.session import (
    ForgeSessionError,
    IndexStore,
    SessionManager,
    SessionStore,
    deletion,
)
from forge.session.cleanup import clean_old_sessions
from forge.session.cleanup_state import cleanup_state_path
from forge.session.workers import capture_session_instance
from tests.fixtures.session_state import publish_session_from_fields

pytestmark = pytest.mark.regression


def _lease(root: Path, name: str, *, pid: int = 2**31 - 1, label: str = "session launch") -> Path:
    token = capture_session_instance(root, name)
    path = get_forge_home() / "session-workers" / token / f"{uuid4().hex}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            dict(
                schema_version=1,
                session_name=name,
                forge_root=str(root),
                instance_id=token,
                label=label,
                pid=pid,
            )
        )
    )
    return path


def _force_plan(index: IndexStore, root: Path) -> deletion.SessionDeletionPlan:
    return deletion.plan_session_deletion(
        index,
        "subject",
        forge_root=str(root),
        force=True,
        discard_abandoned_leases=True,
    )


@pytest.mark.parametrize("verb", ["delete", "purge", "clean"])
def test_manual_force_clears_only_abandoned_leases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verb: str) -> None:
    monkeypatch.chdir(tmp_path)
    if verb == "delete":
        # Lease removals must stay visible even when the home is inside the project's .forge inventory.
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / ".forge" / "home"))
    # Container integration covers a real native child. Host clients are unrelated to this fixture.
    monkeypatch.setattr("forge.session.purge_native.check_native_inactivity", lambda _runtime: ())
    monkeypatch.setattr(deletion, "check_native_inactivity", lambda _runtime: ())
    index = IndexStore()
    for name in ("abandoned", "live"):
        publish_session_from_fields(index, name, tmp_path, tmp_path)
        index.update_session(name, "2020-01-01T00:00:00Z", forge_root=str(tmp_path))
    abandoned, live = _lease(tmp_path, "abandoned"), _lease(tmp_path, "live", pid=os.getpid())
    before = index.index_path.read_bytes()
    args = ["sess", verb, *(["--older-than", "1"] if verb == "clean" else ["--all"])]
    runner = CliRunner(env={"COLUMNS": "40"})
    refused = runner.invoke(main, args)
    assert refused.exit_code == 1, refused.output
    refusal = next(line for line in refused.stdout.splitlines() if line.startswith("Refused abandoned:"))
    assert str(abandoned) in refusal and "abandoned lease" in refusal and "--force" in refusal
    if verb == "purge":
        preview = runner.invoke(main, [*args, "--force", "--json"])
        plans = {p["name"]: p for p in json.loads(preview.stdout)["targets"]}
        assert plans["live"]["refusals"] and not plans["abandoned"]["refusals"]
        assert [f["path"] for f in plans["abandoned"]["content"]["files"]] == [str(abandoned)]
    else:
        preview = runner.invoke(main, [*args, "--force"], input="n\n")
        assert "Native children may still be running" in preview.stdout and str(abandoned) in preview.stdout
        assert "abandoned worker lease for abandoned" in preview.stdout
    assert preview.exit_code == 1
    assert index.index_path.read_bytes() == before and abandoned.exists() and live.exists()
    applied = runner.invoke(main, [*args, "--force", "--yes"])
    assert applied.exit_code == 1 and "live" in applied.stdout
    assert not abandoned.exists() and not SessionStore(str(tmp_path), "abandoned").exists()
    assert live.exists() and SessionStore(str(tmp_path), "live").exists()


@pytest.mark.parametrize("change", ["added", "edited", "replaced", "became-live", "wrong-owner"])
def test_force_revalidates_each_lease_before_saving_retry(tmp_path: Path, change: str) -> None:
    index = IndexStore()
    publish_session_from_fields(index, "subject", tmp_path, tmp_path)
    path = _lease(tmp_path, "subject")
    plan = _force_plan(index, tmp_path)
    assert not plan.refusals
    if change == "added":
        _lease(tmp_path, "subject")
    elif change == "replaced":
        replacement = path.with_suffix(".tmp")
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
    else:
        record = json.loads(path.read_text())
        if change == "became-live":
            record["pid"] = os.getpid()
        elif change == "wrong-owner":
            record["instance_id"] = uuid4().hex
        else:
            record["label"] = "different writer"
        path.write_text(json.dumps(record))
    with pytest.raises(ForgeSessionError, match="Preview the selection again"):
        deletion.apply_session_deletion(index, plan)
    assert path.exists() and SessionStore(str(tmp_path), "subject").exists()
    assert not cleanup_state_path(tmp_path, "subject").exists()


def test_force_is_explicit_even_when_automatic_cleanup_forces_worktrees(
    tmp_path: Path,
) -> None:
    index = IndexStore()
    publish_session_from_fields(index, "subject", tmp_path, tmp_path)
    index.update_session("subject", "2020-01-01T00:00:00Z", forge_root=str(tmp_path))
    path = _lease(tmp_path, "subject")
    retention = clean_old_sessions(older_than_days=1, force=True)
    assert retention.failed and not retention.deleted
    with pytest.raises(ForgeSessionError, match="abandoned lease"):
        SessionManager(index_store=index).purge_session("subject", forge_root=str(tmp_path), force=True)
    assert path.exists() and SessionStore(str(tmp_path), "subject").exists()


def test_retry_keeps_the_original_lease_inventory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    index = IndexStore()
    publish_session_from_fields(index, "subject", tmp_path, tmp_path)
    selected = _lease(tmp_path, "subject")
    plan = _force_plan(index, tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(
            deletion.ActiveSessionStore,
            "clear_session",
            Mock(side_effect=OSError("interrupted")),
        )
        with pytest.raises(ForgeSessionError, match="interrupted"):
            deletion.apply_session_deletion(index, plan)
    assert not selected.exists() and cleanup_state_path(tmp_path, "subject").exists()
    with pytest.raises(ForgeSessionError, match="retry that cleanup command with --force"):
        SessionManager(index_store=index).delete_session("subject", forge_root=str(tmp_path), force=True)
    unselected = _lease(tmp_path, "subject")
    retry = _force_plan(index, tmp_path)
    assert retry.content.abandoned_worker_leases == {selected}
    assert any("outside the saved inventory" in reason for reason in retry.refusals)
    assert unselected.exists() and SessionStore(str(tmp_path), "subject").exists()
    unselected.unlink()
    deletion.apply_session_deletion(index, _force_plan(index, tmp_path))
    assert not SessionStore(str(tmp_path), "subject").exists() and not cleanup_state_path(tmp_path, "subject").exists()


def test_restored_leases_must_belong_to_the_selected_instance_and_force(
    tmp_path: Path,
) -> None:
    index = IndexStore()
    for name in ("subject", "other"):
        publish_session_from_fields(index, name, tmp_path, tmp_path)
    _lease(tmp_path, "subject")
    other = _lease(tmp_path, "other")
    plan = _force_plan(index, tmp_path)
    unforced = plan.to_dict()
    unforced["force"] = False
    with pytest.raises(ValueError, match="session instance"):
        deletion.SessionDeletionPlan.from_dict(unforced)
    redirected = plan.to_dict()
    redirected["content"]["files"][0]["path"] = str(other)
    with pytest.raises(ValueError, match="session instance"):
        deletion.SessionDeletionPlan.from_dict(redirected)


def test_older_forced_retry_cannot_add_an_abandoned_lease(tmp_path: Path) -> None:
    index = IndexStore()
    publish_session_from_fields(index, "subject", tmp_path, tmp_path)
    # Older inventories could record force for the worktree, but never selected leases.
    original = deletion.plan_session_deletion(index, "subject", forge_root=str(tmp_path), force=True)
    deletion._save_retry(cleanup_state_path(tmp_path, "subject"), original)
    new_lease = _lease(tmp_path, "subject")
    retry = _force_plan(index, tmp_path)
    assert retry.force and retry.retry and not retry.content.abandoned_worker_leases
    with pytest.raises(ForgeSessionError, match="outside the saved inventory"):
        deletion.apply_session_deletion(index, retry)
    assert new_lease.exists() and SessionStore(str(tmp_path), "subject").exists()
