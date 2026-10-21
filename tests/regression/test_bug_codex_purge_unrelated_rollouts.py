"""Regression: filename age bypassed Codex native dependency checks.

Bug: codex_purge_unrelated_rollouts.
Root cause: excluding rollouts whose filename timestamps predated the target
allowed an admitted descendant's history_base to be ignored. Unknown layouts,
malformed names and archived entries could also bypass the ancestry inventory.

Fix: inspect every admitted active header regardless of filename age. Unknown
ancestry and uncharacterized archived stores refuse; unrelated admitted active
rollouts remain compatible with purge.

Affected: src/forge/session/purge_native.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from forge.core.runtime.codex_review_source import _ancestry_ids
from forge.session import purge_native as native
from forge.session.models import CodexConfirmed, LaunchIntent, SessionState

pytestmark = pytest.mark.regression

THREAD = "01a12b5c-ce1a-72c2-ad3f-05d75f3fba00"
OTHER = "01a12b73-202d-7dd0-a058-f74ec9375dd2"
TARGET_STAMP = "2026-10-20T12-00-00"


@pytest.fixture
def subject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[SessionState, Path, Path]:
    project = tmp_path.resolve() / "project"
    project.mkdir()
    home = tmp_path.resolve() / "codex"
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setattr(native, "check_native_inactivity", lambda runtime: ())
    target = _rollout(home, project, THREAD, TARGET_STAMP)
    state = SessionState(3, "subject", "2026-10-20T00:00:00Z", "2026-10-20T00:00:00Z", forge_root=str(project))
    state.intent.launch = LaunchIntent(runtime="codex")
    state.confirmed.codex = CodexConfirmed(thread_id=THREAD, rollout_path=str(target))
    return state, project, home


def _rollout(
    home: Path,
    cwd: Path,
    thread: str,
    stamp: str,
    *,
    version: str = "0.162.1",
    archived: bool = False,
    **extra: Any,
) -> Path:
    year, month, day = stamp[:10].split("-")
    directory = home / "archived_sessions" if archived else home / "sessions" / year / month / day
    path = directory / f"rollout-{stamp}-{thread}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"id": thread, "cwd": str(cwd), "cli_version": version}
    if version == "0.162.1":
        metadata.update(session_id=thread, history_mode="paginated")
    metadata.update(extra)
    path.write_text(json.dumps({"type": "session_meta", "payload": metadata}) + "\n")
    return path


def test_older_unrelated_admitted_rollout_allows_only_target_removal(subject) -> None:
    state, project, home = subject
    other = _rollout(home, project, OTHER, "2026-10-01T09-00-00")
    original = other.read_bytes()

    plan = native.plan_native_purge(state)

    assert plan.refusals == ()
    assert [Path(file.path).name for file in plan.files] == [f"rollout-{TARGET_STAMP}-{THREAD}.jsonl"]
    assert native.unlink_native_file(plan.files[0])
    assert not Path(plan.files[0].path).exists()
    assert other.read_bytes() == original


@pytest.mark.parametrize(
    ("stamp", "archived", "reason"),
    [
        ("2026-10-01T09-00-00", False, "version"),
        ("2026-10-01T09-00-00", True, "archived"),
        ("2026-10-20T13-00-00", False, "version"),
        ("2026-10-19T00-00-00", False, "version"),
        ("2026-10-21T00-00-00", True, "archived"),
    ],
)
def test_unknown_ancestry_refuses_regardless_of_filename_age(subject, stamp: str, archived: bool, reason: str) -> None:
    state, project, home = subject
    prior_plan = native.plan_native_purge(state)
    other = _rollout(home, project, OTHER, stamp, version="9.9.9", archived=archived)
    target = Path(prior_plan.files[0].path)
    original = target.read_bytes(), other.read_bytes()

    assert any(reason in refusal for refusal in native.plan_native_purge(state).refusals)
    with pytest.raises(native.NativePurgeError, match=reason):
        native.unlink_native_file(prior_plan.files[0])
    assert (target.read_bytes(), other.read_bytes()) == original


def test_old_named_child_preserves_parent_at_preview_and_unlink(subject) -> None:
    state, project, home = subject
    prior_plan = native.plan_native_purge(state)
    target = Path(prior_plan.files[0].path)
    child = _rollout(
        home,
        project,
        OTHER,
        "2026-10-01T09-00-00",
        forked_from_id=THREAD,
        history_base={
            "thread_id": THREAD,
            "end_ordinal_exclusive": 1,
            "end_byte_offset": target.stat().st_size,
        },
    )
    original = target.read_bytes(), child.read_bytes()
    assert _ancestry_ids(home, OTHER) == {THREAD, OTHER}

    assert any("descendant" in refusal for refusal in native.plan_native_purge(state).refusals)
    with pytest.raises(native.NativePurgeError, match="descendant"):
        native.unlink_native_file(prior_plan.files[0])

    assert (target.read_bytes(), child.read_bytes()) == original
    assert _ancestry_ids(home, OTHER) == {THREAD, OTHER}


@pytest.mark.parametrize(
    "ancestry",
    [{"forked_from_id": THREAD}, {"history_base": {"thread_id": THREAD}}],
)
def test_old_named_malformed_ancestry_refuses_preview_and_unlink(subject, ancestry: dict[str, Any]) -> None:
    state, project, home = subject
    prior_plan = native.plan_native_purge(state)
    target = Path(prior_plan.files[0].path)
    child = _rollout(home, project, OTHER, "2026-10-01T09-00-00", **ancestry)
    original = target.read_bytes(), child.read_bytes()

    assert any("ancestry" in refusal for refusal in native.plan_native_purge(state).refusals)
    with pytest.raises(native.NativePurgeError, match="ancestry"):
        native.unlink_native_file(prior_plan.files[0])
    assert (target.read_bytes(), child.read_bytes()) == original


@pytest.mark.parametrize(
    "name",
    ["notes.jsonl", "rollout-2026-09-01T00-00-00-not-a-rollout", "rollout-2026-09-01T00-00-00-invalid.jsonl"],
)
def test_unrecognized_file_in_old_day_directory_refuses_preview_and_unlink(subject, name: str) -> None:
    state, _, home = subject
    prior_plan = native.plan_native_purge(state)
    target = Path(prior_plan.files[0].path)
    original = target.read_bytes()
    stray = home / "sessions" / "2026" / "09" / "01" / name
    stray.parent.mkdir(parents=True)
    stray.write_text("{}\n")

    assert native.plan_native_purge(state).refusals
    with pytest.raises(ValueError):
        native.unlink_native_file(prior_plan.files[0])
    assert target.read_bytes() == original
    assert stray.read_text() == "{}\n"


def test_old_rollout_named_directory_is_not_exempt(subject) -> None:
    state, _, home = subject
    prior_plan = native.plan_native_purge(state)
    stray = home / "sessions" / "2026" / "09" / "01" / f"rollout-2026-09-01T00-00-00-{OTHER}.jsonl"
    stray.mkdir(parents=True)

    assert native.plan_native_purge(state).refusals
    with pytest.raises((native.NativePurgeError, OSError)):
        native.unlink_native_file(prior_plan.files[0])
    assert Path(prior_plan.files[0].path).exists()
    assert stray.is_dir()


def test_old_rollouts_count_toward_total_inventory_bound(subject, monkeypatch: pytest.MonkeyPatch) -> None:
    state, project, home = subject
    _rollout(home, project, OTHER, "2026-09-01T00-00-00")
    _rollout(home, project, "01a12b77-fda2-7b53-a435-ba7de8501d7e", "2026-09-02T00-00-00")
    monkeypatch.setattr(native, "MAX_STORE_FILES", 2)

    assert any("ancestry inventory exceeds" in refusal for refusal in native.plan_native_purge(state).refusals)


@pytest.mark.parametrize(("archived", "reason"), [(False, "Ambiguous"), (True, "archived")])
def test_old_copy_of_target_thread_is_still_checked(subject, archived: bool, reason: str) -> None:
    state, project, home = subject
    _rollout(home, project, THREAD, "2026-09-01T00-00-00", archived=archived)

    assert any(reason in refusal for refusal in native.plan_native_purge(state).refusals)
