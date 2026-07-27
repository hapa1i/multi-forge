"""Tests for the adopt command-core op (native_session_adoption Slice 2).

Adoption is the first operation whose *input* is user-owned state Forge did not
create, so several tests here assert on what adoption must **not** touch.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from forge.core.ops.context import ExecutionContext
from forge.core.ops.session_adopt import (
    MODEL_BASIS_EXPLICIT,
    MODEL_BASIS_INFERRED,
    MODEL_BASIS_NONE,
    AdoptError,
    adopt_session,
    infer_transcript_model,
    plan_adoption,
    read_transcript_cwd,
)
from forge.session import SessionStore, UuidAlreadyBoundError
from forge.session.claude.paths import get_transcript_path
from forge.session.index import IndexStore

_UUID = "aaaa1111-2222-3333-4444-555566667777"


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    (project / ".forge").mkdir()
    return project


def _write_transcript(
    project: Path,
    *,
    session_uuid: str = _UUID,
    cwd: str | None = None,
    models: tuple[str, ...] = ("claude-opus-5",),
    include_cwd: bool = True,
) -> Path:
    """Write a native-shaped transcript and return its path."""
    entries: list[dict[str, object]] = []
    user: dict[str, object] = {"type": "user", "message": {"role": "user"}}
    if include_cwd:
        user["cwd"] = cwd or str(project)
    entries.append(user)
    for model in models:
        entry: dict[str, object] = {"type": "assistant", "message": {"model": model}}
        if include_cwd:
            entry["cwd"] = cwd or str(project)
        entries.append(entry)

    path = get_transcript_path(str(project), session_uuid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    # Age it past the double-attach window so plans are not flagged recently_active.
    os.utime(path, (0, 0))
    return path


class TestTranscriptReaders:
    def test_reads_recorded_cwd(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        path = _write_transcript(project)
        assert read_transcript_cwd(path) == str(project)

    def test_missing_cwd_returns_none(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        path = _write_transcript(project, include_cwd=False)
        assert read_transcript_cwd(path) is None

    def test_infers_last_real_model(self, tmp_path: Path) -> None:
        """Mixed-model transcripts are real (2 of 470 sampled); last-wins is the rule."""
        project = _make_project(tmp_path)
        path = _write_transcript(project, models=("claude-fable-5", "claude-opus-4-8"))
        assert infer_transcript_model(path) == "claude-opus-4-8"

    def test_filters_synthetic_sentinel(self, tmp_path: Path) -> None:
        """`<synthetic>` is a sentinel, not a model id, even when it is last."""
        project = _make_project(tmp_path)
        path = _write_transcript(project, models=("claude-opus-5", "<synthetic>"))
        assert infer_transcript_model(path) == "claude-opus-5"

    def test_no_assistant_turn_infers_nothing(self, tmp_path: Path) -> None:
        """The majority case locally (346 of 470): user-only transcripts."""
        project = _make_project(tmp_path)
        path = _write_transcript(project, models=())
        assert infer_transcript_model(path) is None

    def test_malformed_lines_do_not_abort_the_scan(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        path = _write_transcript(project)
        path.write_text(
            "not json\n\n" + json.dumps({"type": "assistant", "message": {"model": "claude-opus-5"}}) + "\n",
            encoding="utf-8",
        )
        assert infer_transcript_model(path) == "claude-opus-5"


class TestPlanPreconditions:
    def test_rejects_outside_forge_project(self, tmp_path: Path) -> None:
        bare = tmp_path / "bare"
        bare.mkdir()
        ctx = ExecutionContext.from_cwd(bare)
        with pytest.raises(AdoptError, match="not inside a Forge project"):
            plan_adoption(ctx, _UUID)

    def test_rejects_missing_transcript(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        with pytest.raises(AdoptError, match="no transcript"):
            plan_adoption(ExecutionContext.from_cwd(project), _UUID)

    def test_rejects_transcript_from_a_lossy_encoding_sibling(self, tmp_path: Path) -> None:
        """`a.b`, `a_b` and `a-b` share one encoded directory (paths.py:47).

        A sibling's transcript can therefore appear under this project's encoded
        dir. The recorded-cwd cross-check is what stops adoption binding it.
        """
        project = _make_project(tmp_path)
        sibling = str(project.parent / "other-project")
        _write_transcript(project, cwd=sibling)

        with pytest.raises(AdoptError, match="was launched from"):
            plan_adoption(ExecutionContext.from_cwd(project), _UUID)

    def test_rejects_transcript_without_a_recorded_cwd(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        _write_transcript(project, include_cwd=False)
        with pytest.raises(AdoptError, match="records no launch directory"):
            plan_adoption(ExecutionContext.from_cwd(project), _UUID)

    def test_rejects_empty_conversation_id(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        with pytest.raises(AdoptError, match="conversation id is required"):
            plan_adoption(ExecutionContext.from_cwd(project), "")

    @pytest.mark.parametrize(
        "bad_id",
        [
            "/etc/passwd",
            "../../../etc/passwd",
            "not-a-uuid",
            "aaaa1111-2222-3333-4444-555566667777/../evil",
            "aaaa1111-2222-3333-4444-55556666777",  # one hex digit short
            "aaaa1111-2222-3333-4444-5555666677778",  # one too many
        ],
    )
    def test_rejects_ids_that_are_not_canonical_uuids(self, tmp_path: Path, bad_id: str) -> None:
        """The id is a filename component, so shape is a path-safety boundary."""
        project = _make_project(tmp_path)
        with pytest.raises(AdoptError, match="is not a conversation id"):
            plan_adoption(ExecutionContext.from_cwd(project), bad_id)

    def test_normalizes_whitespace_and_case(self, tmp_path: Path) -> None:
        """Copy-paste artifacts are folded to the canonical lowercase id."""
        project = _make_project(tmp_path)
        _write_transcript(project)

        plan = plan_adoption(ExecutionContext.from_cwd(project), f"  {_UUID.upper()}\n")

        assert plan.session_uuid == _UUID

    def test_uppercase_cannot_double_bind_an_adopted_conversation(self, tmp_path: Path) -> None:
        """The already-bound check is a string equality, so casing must not slip past it."""
        project = _make_project(tmp_path)
        ctx = ExecutionContext.from_cwd(project)
        _write_transcript(project)
        adopt_session(ctx, plan_adoption(ctx, _UUID), name="first")

        with pytest.raises(UuidAlreadyBoundError) as excinfo:
            plan_adoption(ctx, _UUID.upper())
        assert excinfo.value.owner == "first"

    def test_no_state_is_created_by_a_rejected_plan(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        with pytest.raises(AdoptError):
            plan_adoption(ExecutionContext.from_cwd(project), _UUID)
        assert not (project / ".forge" / "sessions").exists()
        assert IndexStore().read().sessions == {}


class TestModelBasis:
    def test_explicit_override_wins_over_inference(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        _write_transcript(project, models=("claude-opus-4-8",))
        plan = plan_adoption(ExecutionContext.from_cwd(project), _UUID, model_override="claude-opus-5")
        assert (plan.model, plan.model_basis) == ("claude-opus-5", MODEL_BASIS_EXPLICIT)

    def test_inferred_from_transcript(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        _write_transcript(project, models=("claude-opus-4-8",))
        plan = plan_adoption(ExecutionContext.from_cwd(project), _UUID)
        assert (plan.model, plan.model_basis) == ("claude-opus-4-8", MODEL_BASIS_INFERRED)

    def test_no_basis_leaves_the_pin_unset(self, tmp_path: Path) -> None:
        """P3: adoption must not invent a default it would then apply to a proxy resume."""
        project = _make_project(tmp_path)
        _write_transcript(project, models=())
        plan = plan_adoption(ExecutionContext.from_cwd(project), _UUID)
        assert (plan.model, plan.model_basis) == (None, MODEL_BASIS_NONE)

    def test_explicit_alias_is_normalized_like_session_start(self, tmp_path: Path) -> None:
        """`session start` persists DirectModelPin.env_model; adoption must match."""
        project = _make_project(tmp_path)
        _write_transcript(project)
        plan = plan_adoption(ExecutionContext.from_cwd(project), _UUID, model_override="opus")
        assert (plan.model, plan.model_basis) == ("claude-opus-5", MODEL_BASIS_EXPLICIT)

    @pytest.mark.parametrize(
        ("bad_model", "expected"),
        [
            ("gpt-4o", "only supports Claude models"),  # catalogued, but not Claude
            ("claude-nonesuch-9", "Unknown direct Claude model"),
        ],
    )
    def test_explicit_bad_model_is_rejected(self, tmp_path: Path, bad_model: str, expected: str) -> None:
        """The user typed it, so it fails loudly -- unlike an inferred value."""
        project = _make_project(tmp_path)
        _write_transcript(project)
        with pytest.raises(AdoptError, match=expected):
            plan_adoption(ExecutionContext.from_cwd(project), _UUID, model_override=bad_model)

    def test_uncatalogued_transcript_model_degrades_instead_of_failing(self, tmp_path: Path) -> None:
        """An unresolvable pin is not inert: model_pin.py:61 raises on it at resume.

        The conversation really ran on this model, so refusing to adopt would be
        wrong; dropping the pin keeps the session resumable.
        """
        project = _make_project(tmp_path)
        _write_transcript(project, models=("claude-3-5-sonnet-20241022",))
        plan = plan_adoption(ExecutionContext.from_cwd(project), _UUID)
        assert (plan.model, plan.model_basis) == (None, MODEL_BASIS_NONE)


class TestAdoptWrites:
    def test_binds_the_native_uuid_and_records_provenance(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        source = _write_transcript(project, models=("claude-opus-5",))
        ctx = ExecutionContext.from_cwd(project)

        result = adopt_session(ctx, plan_adoption(ctx, _UUID), name="adopted")

        state = SessionStore(str(project), "adopted").read()
        assert state.confirmed.claude_session_id == _UUID
        assert state.confirmed.claude_project_root == str(project)
        assert state.intent.launch is not None
        assert state.intent.launch.direct_model == "claude-opus-5"

        adoption = state.confirmed.adoption
        assert adoption is not None
        assert adoption.source_runtime == "claude_code"
        assert adoption.source_path == str(source)
        assert adoption.model_basis == MODEL_BASIS_INFERRED
        assert adoption.adopted_at

        assert (project / result.artifact_rel).is_file()

    def test_artifact_entry_matches_the_stop_shape(self, tmp_path: Path) -> None:
        """Readers of confirmed.artifacts.transcripts[] must not need a special case."""
        project = _make_project(tmp_path)
        ctx = ExecutionContext.from_cwd(project)
        _write_transcript(project)
        adopt_session(ctx, plan_adoption(ctx, _UUID), name="adopted")

        entries = SessionStore(str(project), "adopted").read().confirmed.artifacts["transcripts"]
        assert len(entries) == 1
        assert entries[0]["reason"] == "adopt"
        assert entries[0]["session_id"] == _UUID
        assert set(entries[0]) == {"captured_at", "reason", "source_path", "session_id", "copied_path", "copied"}

    def test_queues_search_indexing_but_not_memory(self, tmp_path: Path) -> None:
        """Memory stays tied to a real Stop handoff, not to adoption copying a file."""
        from forge.core.workqueue import pending_work_dir

        project = _make_project(tmp_path)
        ctx = ExecutionContext.from_cwd(project)
        _write_transcript(project)
        result = adopt_session(ctx, plan_adoption(ctx, _UUID), name="adopted")

        assert result.indexed
        markers = {p.name for p in pending_work_dir().glob("*.json")}
        assert f"idx-{_UUID}.json" in markers
        assert f"{_UUID}.json" not in markers, "adopt must not enqueue a stop/handoff marker"

    def test_adopt_creates_no_git_worktree(self, tmp_path: Path) -> None:
        """create_worktree must stay False, or rollback would arm against a real checkout.

        `_rollback_worktree` short-circuits on `if not created_worktree`
        (manager.py:482), so passing True here would make a failed adopt able to
        delete a checkout Forge did not create.
        """
        project = _make_project(tmp_path)
        ctx = ExecutionContext.from_cwd(project)
        _write_transcript(project)
        adopt_session(ctx, plan_adoption(ctx, _UUID), name="adopted")

        state = SessionStore(str(project), "adopted").read()
        assert state.worktree is not None
        assert state.worktree.is_worktree is False
        assert state.worktree.path == str(project)


class TestConcurrencyAndRollback:
    def test_second_adopt_of_one_uuid_is_rejected(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        ctx = ExecutionContext.from_cwd(project)
        _write_transcript(project)
        adopt_session(ctx, plan_adoption(ctx, _UUID), name="first")

        with pytest.raises(UuidAlreadyBoundError) as excinfo:
            plan_adoption(ctx, _UUID)
        assert excinfo.value.owner == "first"

    def test_racing_adopt_is_caught_inside_the_index_lock(self, tmp_path: Path) -> None:
        """The plan's check releases its lock before the write, so the write re-checks.

        Simulated by reusing a plan captured before the competing bind -- exactly
        the state a loser of the race holds.
        """
        project = _make_project(tmp_path)
        ctx = ExecutionContext.from_cwd(project)
        _write_transcript(project)

        stale_plan = plan_adoption(ctx, _UUID)  # captured while the UUID was free
        adopt_session(ctx, plan_adoption(ctx, _UUID), name="winner")

        with pytest.raises(UuidAlreadyBoundError) as excinfo:
            adopt_session(ctx, stale_plan, name="loser")
        assert excinfo.value.owner == "winner"

        assert not (project / ".forge" / "sessions" / "loser").exists()
        assert IndexStore().get_session("winner", forge_root=str(project))

    def test_failure_after_the_copy_leaves_no_binding_and_spares_the_source(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The load-bearing safety property: rollback never reaches user-owned state."""
        project = _make_project(tmp_path)
        ctx = ExecutionContext.from_cwd(project)
        source = _write_transcript(project)
        source_bytes = source.read_bytes()
        agent_log = source.parent / _UUID / "subagents" / "agent-1.jsonl"
        agent_log.parent.mkdir(parents=True, exist_ok=True)
        agent_log.write_text("{}\n", encoding="utf-8")

        plan = plan_adoption(ctx, _UUID)

        import forge.core.ops.session_adopt as adopt_mod

        real_copy = adopt_mod.safe_copy_file
        calls = {"n": 0}

        def _fail_once(src: Path, dst: Path, **kwargs: object) -> bool:
            """Fail the first copy only.

            Deliberately not `monkeypatch.undo()`: the autouse `isolate_forge_home`
            and `isolate_claude_home` fixtures share this same monkeypatch instance,
            so undoing would restore the real HOME mid-test and send the re-run
            looking at the developer's actual ~/.claude.
            """
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("disk full")
            return bool(real_copy(src, dst, **kwargs))  # type: ignore[arg-type]  # kwargs is overwrite: bool

        monkeypatch.setattr(adopt_mod, "safe_copy_file", _fail_once)

        with pytest.raises(AdoptError, match="could not capture the transcript"):
            adopt_session(ctx, plan, name="doomed")

        # Forge state is fully unwound.
        assert not (project / ".forge" / "sessions" / "doomed").exists()
        assert IndexStore().read().sessions == {}
        # list() matters: a bare glob() generator is always truthy.
        assert not list((project / ".forge" / "artifacts" / "doomed" / "transcripts").glob("*.jsonl"))

        # User-owned state is untouched -- the whole point of the narrow rollback.
        assert source.is_file()
        assert source.read_bytes() == source_bytes
        assert agent_log.is_file()

        # And the failure is recoverable: a re-run succeeds.
        result = adopt_session(ctx, plan_adoption(ctx, _UUID), name="doomed")
        assert result.session_uuid == _UUID

    def test_binding_recorded_only_in_a_manifest_still_blocks_adoption(self, tmp_path: Path) -> None:
        """Card step 1: index first, then manifests.

        The in-lock check reads the index alone, so a UUID that drifted out of
        its index column would double-bind without the manifest fallback.
        """
        project = _make_project(tmp_path)
        ctx = ExecutionContext.from_cwd(project)
        _write_transcript(project)
        adopt_session(ctx, plan_adoption(ctx, _UUID), name="owner")

        # Drop just the index column, leaving the manifest authoritative.
        store = IndexStore()
        index = store.read()
        for entry in index.sessions.values():
            entry.claude_session_id = None
        store.write(index)
        assert store.find_session_by_uuid(_UUID) is None

        with pytest.raises(UuidAlreadyBoundError) as excinfo:
            plan_adoption(ctx, _UUID)
        assert excinfo.value.owner == "owner"

    def test_transcript_deleted_during_the_prompt_aborts_before_writing(self, tmp_path: Path) -> None:
        """The double-attach prompt blocks on a human, so the plan can go stale."""
        project = _make_project(tmp_path)
        ctx = ExecutionContext.from_cwd(project)
        source = _write_transcript(project)

        plan = plan_adoption(ctx, _UUID)
        source.unlink()  # user closed and cleaned up while the prompt waited

        with pytest.raises(AdoptError, match="no transcript"):
            adopt_session(ctx, plan, name="adopted")

        assert not (project / ".forge" / "sessions" / "adopted").exists()
        assert IndexStore().read().sessions == {}
