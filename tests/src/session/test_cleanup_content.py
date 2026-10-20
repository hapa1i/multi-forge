"""Deletion ownership tests use isolated Forge roots and synthetic transcripts."""

from __future__ import annotations

import json
from pathlib import Path

import dacite
import pytest

from forge.core.reactive.codex_reviewer_home import INPUT_MARKER, MARKER
from forge.session.cleanup_content import (
    ForgeContentPlan,
    apply_forge_content,
    plan_forge_content,
    validate_forge_content_scope,
)
from forge.session.models import CodexConfirmed, Derivation, create_session_state


def _write(path: Path, content: str = "session content") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _state(root: Path):
    state = create_session_state("subject", worktree_path=str(root))
    state.forge_root = str(root)
    state.confirmed.claude_session_id = "11111111-1111-4111-8111-111111111111"
    return state


def test_exact_artifact_transfer_and_queue_cleanup_preserves_other_content(
    tmp_path: Path,
) -> None:
    root, home = tmp_path / "project", tmp_path / "home"
    state = _state(root)
    owned = [
        _write(root / ".forge/artifacts/subject/transcripts/session.jsonl"),
        _write(root / ".forge/artifacts/subject/authority/events.jsonl"),
        _write(root / ".forge/artifacts/subject/routing/events.jsonl"),
        _write(root / ".forge/prev_sessions/subject/generated.md"),
        _write(root / ".forge/prev_sessions/subject/children/old.notes.md", "my notes"),
    ]
    kept = [
        _write(root / ".forge/artifacts/other/transcripts/session.jsonl"),
        _write(root / "docs/project-state.md"),
        _write(home / "telemetry/requests.jsonl"),
        _write(tmp_path / "native/transcript.jsonl"),
    ]
    payload = {
        "session_id": state.confirmed.claude_session_id,
        "session_name": state.name,
        "forge_root": str(root),
    }
    for queue in ("pending-work", "pending-work/failed"):
        owned.append(
            _write(
                home / queue / "job.json",
                json.dumps({"schema_version": 1, "payload": payload}),
            )
        )
    kept.append(
        _write(
            home / "pending-work/other.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "payload": {**payload, "forge_root": str(tmp_path / "other")},
                }
            ),
        )
    )
    before = {path: path.read_bytes() for path in kept}
    plan = plan_forge_content(state, forge_root=root, forge_home=home)
    assert not plan.refusals
    assert any("user-authored transfer notes" in note for note in plan.notes)
    restored = ForgeContentPlan.from_dict(json.loads(json.dumps(plan.to_dict())))
    assert restored == plan
    apply_forge_content(restored)
    assert all(not path.exists() for path in owned)
    assert {path: path.read_bytes() for path in kept} == before
    assert not (root / ".forge/artifacts/subject").exists()
    assert apply_forge_content(restored) == ()


def test_child_context_and_notes_are_owned_but_parent_cache_is_preserved(
    tmp_path: Path,
) -> None:
    root, parent, home = tmp_path / "project", tmp_path / "parent", tmp_path / "home"
    state = _state(root)
    context = _write(parent / ".forge/prev_sessions/ancestor/children/subject.md")
    notes = _write(context.with_name("subject.notes.md"), "user text")
    cache = _write(parent / ".forge/prev_sessions/ancestor/generated.md")
    sibling = _write(context.with_name("sibling.md"))
    state.confirmed.derivation = Derivation(
        parent_session="ancestor",
        parent_forge_root=str(parent),
        context_file=str(context),
    )
    plan = plan_forge_content(state, forge_root=root, forge_home=home)
    assert not plan.refusals
    apply_forge_content(plan)
    assert not context.exists() and not notes.exists()
    assert cache.exists() and sibling.exists()


def test_relative_child_context_uses_child_root_when_parent_path_also_exists(tmp_path: Path) -> None:
    root, parent, home = tmp_path / "project", tmp_path / "parent", tmp_path / "home"
    state = _state(root)
    relative = Path(".forge/prev_sessions/ancestor/children/subject.md")
    context = _write(root / relative, "child snapshot")
    notes = _write(context.with_name("subject.notes.md"), "child notes")
    unrelated = _write(parent / relative, "parent snapshot")
    unrelated_notes = _write(unrelated.with_name("subject.notes.md"), "parent notes")
    state.confirmed.derivation = Derivation(
        parent_session="ancestor", parent_forge_root=str(parent), context_file=str(relative)
    )
    plan = plan_forge_content(state, forge_root=root, forge_home=home)
    assert not plan.refusals
    validate_forge_content_scope(plan, state)
    apply_forge_content(plan)
    assert not context.exists() and not notes.exists()
    assert unrelated.read_text() == "parent snapshot"
    assert unrelated_notes.read_text() == "parent notes"


def test_absolute_child_context_uses_exact_nested_parent_root_for_notes(tmp_path: Path) -> None:
    root, home = tmp_path / "project", tmp_path / "home"
    parent = root / "nested-parent"
    state = _state(root)
    relative = Path(".forge/prev_sessions/ancestor/children/subject.md")
    context = _write(parent / relative, "nested snapshot")
    notes = _write(context.with_name("subject.notes.md"), "nested notes")
    unrelated = _write(root / relative, "outer snapshot")
    unrelated_notes = _write(unrelated.with_name("subject.notes.md"), "outer notes")
    state.confirmed.derivation = Derivation(
        parent_session="ancestor", parent_forge_root=str(parent), context_file=str(context)
    )
    plan = plan_forge_content(state, forge_root=root, forge_home=home)
    assert not plan.refusals
    validate_forge_content_scope(plan, state)
    apply_forge_content(plan)
    assert not context.exists() and not notes.exists()
    assert unrelated.read_text() == "outer snapshot"
    assert unrelated_notes.read_text() == "outer notes"


@pytest.mark.parametrize("replacement", ["bytes", "inode", "new-file", "symlink"])
def test_changed_inventory_refuses_before_removing_any_file(tmp_path: Path, replacement: str) -> None:
    root, home = tmp_path / "project", tmp_path / "home"
    first = _write(root / ".forge/artifacts/subject/a.txt", "first")
    second = _write(first.with_name("z.txt"), "second")
    plan = plan_forge_content(_state(root), forge_root=root, forge_home=home)
    if replacement == "bytes":
        second.write_text("changed")
    elif replacement == "inode":
        staged = _write(second.with_name("replacement.txt"), "second")
        staged.replace(second)
    elif replacement == "new-file":
        _write(first.with_name("new.txt"))
    else:
        second.unlink()
        second.symlink_to(_write(tmp_path / "outside.txt"))
    with pytest.raises((ValueError, OSError)):
        apply_forge_content(plan)
    assert first.read_text() == "first"


def test_symlinked_project_root_is_resolved_but_descendant_link_refuses(
    tmp_path: Path,
) -> None:
    root, home = tmp_path / "project", tmp_path / "home"
    root.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    target = _write(root / ".forge/artifacts/subject/a.txt")
    plan = plan_forge_content(_state(root), forge_root=alias, forge_home=home)
    assert not plan.refusals
    assert str(target) in {item.path for item in plan.files}
    outside = _write(tmp_path / "outside/secret.txt")
    target.with_name("link").symlink_to(outside.parent, target_is_directory=True)
    refused = plan_forge_content(_state(root), forge_root=alias, forge_home=home)
    assert refused.refusals
    with pytest.raises(ValueError):
        apply_forge_content(refused)
    assert outside.exists() and target.exists()


def test_partial_file_failure_can_retry_without_reinventoring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import forge.session.cleanup_content as cleanup

    root, home = tmp_path / "project", tmp_path / "home"
    first = _write(root / ".forge/artifacts/subject/a.txt")
    second = _write(first.with_name("b.txt"))
    plan = plan_forge_content(_state(root), forge_root=root, forge_home=home)
    original = cleanup.os.unlink

    def fail_second(path, **kwargs):
        if path == "b.txt":
            raise PermissionError("injected cleanup failure")
        return original(path, **kwargs)

    monkeypatch.setattr(cleanup.os, "unlink", fail_second)
    with pytest.raises(PermissionError, match="injected"):
        apply_forge_content(plan)
    assert not first.exists() and second.exists()
    monkeypatch.setattr(cleanup.os, "unlink", original)
    apply_forge_content(plan)
    assert not second.exists()


def test_unknown_inventory_version_or_fields_refuse(tmp_path: Path) -> None:
    plan = plan_forge_content(_state(tmp_path), forge_root=tmp_path, forge_home=tmp_path / "home")
    with pytest.raises(ValueError, match="Unsupported"):
        ForgeContentPlan.from_dict({**plan.to_dict(), "schema_version": 2})
    with pytest.raises(dacite.DaciteError):
        ForgeContentPlan.from_dict({**plan.to_dict(), "unrecognized": True})


def test_qa_copies_require_exact_session_identity_and_preserve_reports(
    tmp_path: Path,
) -> None:
    root, home = tmp_path / "project", tmp_path / "home"
    state = _state(root)
    run = home / "manual-testing/qa/runs/one"
    transcript = _write(
        run / "transcript.jsonl",
        json.dumps({"sessionId": state.confirmed.claude_session_id}),
    )
    report = _write(run / "report.md")
    unknown = _write(home / "manual-testing/qa/runs/old/transcript.jsonl", '{"type":"user"}\n')
    marker = _write(
        home / "manual-testing/qa/.pending-transcript",
        json.dumps({"run_dir": str(run), "session_id": state.confirmed.claude_session_id}),
    )
    plan = plan_forge_content(state, forge_root=root, forge_home=home)
    assert not plan.refusals
    assert any(str(unknown) in exclusion for exclusion in plan.exclusions)
    apply_forge_content(plan)
    assert not transcript.exists() and not marker.exists()
    assert unknown.exists() and report.exists()


def test_reviewer_removes_owned_inputs_under_lease_and_preserves_credentials(
    tmp_path: Path,
) -> None:
    root, home = tmp_path / "project", tmp_path / "home"
    state = _state(root)
    state.confirmed.codex = CodexConfirmed(thread_id="22222222-2222-4222-8222-222222222222")
    reviewer = home / "reviewers/codex"
    reviewer.mkdir(parents=True, mode=0o700)
    _write(reviewer / MARKER, json.dumps({"version": 1, "extra_usage_off_asserted": True}))
    _write(reviewer / "review.lock", "")
    auth = _write(reviewer / "auth.json", "synthetic credentials")
    for tree in ("sessions", "review-index"):
        _write(reviewer / tree / INPUT_MARKER, "1\n")
    _write(reviewer / "review-index/state.db", "synthetic private index")
    transcript = _write(
        reviewer / "sessions/2026/10/20/rollout.jsonl",
        json.dumps({"type": "session_meta", "payload": {"id": state.confirmed.codex.thread_id}}),
    )
    plan = plan_forge_content(state, forge_root=root, forge_home=home)
    assert not plan.refusals and not plan.exclusions
    assert plan.reviewer_homes == (str(reviewer),)
    apply_forge_content(plan)
    assert not transcript.exists()
    assert not (reviewer / "review-index").exists()
    assert auth.read_text() == "synthetic credentials"


def test_preview_has_no_write_side_effects_when_content_is_absent(
    tmp_path: Path,
) -> None:
    root, home = tmp_path / "project", tmp_path / "home"
    plan = plan_forge_content(_state(root), forge_root=root, forge_home=home)
    assert not plan.refusals and not plan.files
    assert not root.exists() and not home.exists()


def test_content_created_after_empty_preview_refuses(tmp_path: Path) -> None:
    root, home = tmp_path / "project", tmp_path / "home"
    plan = plan_forge_content(_state(root), forge_root=root, forge_home=home)
    new_content = _write(root / ".forge/artifacts/subject/new.txt")
    with pytest.raises(ValueError, match="New content appeared"):
        apply_forge_content(plan)
    assert new_content.exists()


@pytest.mark.parametrize("change", ["outside-file", "wrong-category", "duplicate", "bad-digest", "negative-stat"])
def test_malformed_persisted_content_inventory_refuses(tmp_path: Path, change: str) -> None:
    root, home = tmp_path / "project", tmp_path / "home"
    _write(root / ".forge/artifacts/subject/source.jsonl")
    raw = json.loads(json.dumps(plan_forge_content(_state(root), forge_root=root, forge_home=home).to_dict()))
    if change == "outside-file":
        raw["files"][0]["path"] = str(root / "private.txt")
    elif change == "wrong-category":
        raw["files"][0]["category"] = "arbitrary"
    elif change == "duplicate":
        raw["files"].append(raw["files"][0])
    elif change == "bad-digest":
        raw["files"][0]["sha256"] = "not-a-digest"
    else:
        raw["files"][0]["device"] = -1
    with pytest.raises(ValueError):
        ForgeContentPlan.from_dict(raw)


def test_persisted_content_scope_binds_home_and_parent_derivation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, home, parent = tmp_path / "project", tmp_path / "home", tmp_path / "parent"
    state = _state(root)
    monkeypatch.setenv("FORGE_HOME", str(home))
    context = _write(parent / ".forge/prev_sessions/ancestor/children/subject.md")
    state.confirmed.derivation = Derivation(
        parent_session="ancestor",
        parent_forge_root=str(parent),
        context_file=str(context),
    )
    _write(
        home / "manual-testing/qa/.pending-transcript", json.dumps({"session_id": state.confirmed.claude_session_id})
    )
    plan = plan_forge_content(state, forge_root=root, forge_home=home)
    validate_forge_content_scope(plan, state)
    state.confirmed.derivation.parent_forge_root = str(tmp_path / "other-parent")
    with pytest.raises(ValueError, match="derivation"):
        validate_forge_content_scope(plan, state)
    state.confirmed.derivation.parent_forge_root = str(parent)
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "other-home"))
    with pytest.raises(ValueError, match="Forge home"):
        validate_forge_content_scope(plan, state)
