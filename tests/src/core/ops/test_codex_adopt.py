"""Tests for the Codex adoption arm (native_session_adoption Slice 4).

The Codex arm's discovery differs from Claude's: the thread id is only a filename
suffix under `$CODEX_HOME/sessions/YYYY/MM/DD/`, and the launch directory lives
inside the file. So the lookup is a glob that can return several hits, and every
ambiguous outcome must be refused rather than resolved by mtime.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from forge.core.ops.codex_adopt import (
    ROLLOUT_SOURCE_ADOPTED,
    adopt_codex_session,
    find_adoptable_rollout,
    plan_codex_adoption,
)
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session_adopt import (
    CODEX_RUNTIME,
    AdoptError,
    detect_adoption_runtime,
)
from forge.session import SessionStore, UuidAlreadyBoundError
from forge.session.claude.paths import get_transcript_path

_THREAD = "019f0b65-b51c-7683-99c7-bb48107f7b83"


@pytest.fixture(autouse=True)
def codex_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Point CODEX_HOME at the test tree and make the preflight pass.

    The preflight shells out to the real `codex` binary; adoption only needs its
    auth posture, so it is stubbed. `find_adoptable_rollout` still reads the real
    filesystem, which is what these tests are about.
    """
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))

    import forge.core.ops.codex_adopt as mod

    class _Preflight:
        auth_method = "codex_store"
        auth_source = "chatgpt"
        billing_mode = "subscription"

    monkeypatch.setattr(mod, "assert_codex_ready", lambda **_: _Preflight())
    return _Preflight


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    (project / ".forge").mkdir()
    return project


def _write_rollout(
    tmp_path: Path,
    cwd: Path,
    *,
    thread_id: str = _THREAD,
    day: str = "2026/06/27",
    stamp: str = "2026-06-27T19-24-02",
    include_cwd: bool = True,
) -> Path:
    day_dir = tmp_path / "codex" / "sessions" / day
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"rollout-{stamp}-{thread_id}.jsonl"
    head: dict[str, object] = {"type": "session_meta", "payload": {"id": thread_id}}
    if include_cwd:
        assert isinstance(head["payload"], dict)
        head["payload"]["cwd"] = str(cwd)
    path.write_text(json.dumps(head) + "\n", encoding="utf-8")
    os.utime(path, (0, 0))
    return path


class TestRolloutLookup:
    def test_finds_the_rollout_for_this_directory(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        expected = _write_rollout(tmp_path, project)
        assert find_adoptable_rollout(_THREAD, project) == expected

    def test_rejects_a_thread_with_no_rollout(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        with pytest.raises(AdoptError, match="no Codex rollout"):
            find_adoptable_rollout(_THREAD, project)

    def test_rejects_a_rollout_launched_elsewhere(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        _write_rollout(tmp_path, tmp_path / "somewhere-else")
        with pytest.raises(AdoptError, match="was launched from"):
            find_adoptable_rollout(_THREAD, project)

    def test_refuses_to_guess_between_two_matches_in_this_directory(self, tmp_path: Path) -> None:
        """`find_rollout_path` would take newest-mtime; adoption must not."""
        project = _make_project(tmp_path)
        _write_rollout(tmp_path, project, day="2026/06/27", stamp="2026-06-27T19-24-02")
        newer = _write_rollout(tmp_path, project, day="2026/06/28", stamp="2026-06-28T09-00-00")
        os.utime(newer, (10_000, 10_000))

        with pytest.raises(AdoptError, match="matches 2 rollouts"):
            find_adoptable_rollout(_THREAD, project)

    def test_rejects_a_rollout_with_no_recorded_cwd(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        _write_rollout(tmp_path, project, include_cwd=False)
        with pytest.raises(AdoptError, match="records no launch directory"):
            find_adoptable_rollout(_THREAD, project)

    def test_an_unreadable_head_keeps_a_verified_match_ambiguous(self, tmp_path: Path) -> None:
        """Missing evidence is not evidence of a different directory.

        Dropping the unverifiable rollout would silently bind the other one -- and
        the unverifiable one may be the conversation the user meant.
        """
        project = _make_project(tmp_path)
        _write_rollout(tmp_path, project, day="2026/06/27", stamp="2026-06-27T19-24-02")
        _write_rollout(tmp_path, project, day="2026/06/28", stamp="2026-06-28T09-00-00", include_cwd=False)

        with pytest.raises(AdoptError, match="matches 2 rollouts"):
            find_adoptable_rollout(_THREAD, project)

    def test_ignores_a_file_whose_name_is_not_a_rollout(self, tmp_path: Path) -> None:
        """The glob is looser than the naming contract; the parser is the authority."""
        project = _make_project(tmp_path)
        real = _write_rollout(tmp_path, project)
        (real.parent / f"rollout-{_THREAD}.jsonl").write_text("{}\n", encoding="utf-8")

        assert find_adoptable_rollout(_THREAD, project) == real

    def test_a_thread_id_that_is_only_a_suffix_does_not_match(self, tmp_path: Path) -> None:
        """The glob matches any name *ending* in the id; identity is the parsed field.

        `rollout-<ts>-not-the-thread-<wanted>.jsonl` is a different thread whose id
        happens to end with the requested one. Binding it would point the session at
        someone else's conversation.
        """
        project = _make_project(tmp_path)
        day = tmp_path / "codex" / "sessions" / "2026" / "07" / "27"
        day.mkdir(parents=True, exist_ok=True)
        decoy = day / f"rollout-2026-07-27T12-00-00-not-the-thread-{_THREAD}.jsonl"
        decoy.write_text(
            json.dumps({"type": "session_meta", "payload": {"id": "other", "cwd": str(project)}}) + "\n",
            encoding="utf-8",
        )

        with pytest.raises(AdoptError, match="no Codex rollout"):
            find_adoptable_rollout(_THREAD, project)

    def test_a_suffix_match_does_not_route_the_runtime_either(self, tmp_path: Path) -> None:
        """detect_adoption_runtime shares the lookup, so it shared the false positive."""
        project = _make_project(tmp_path)
        day = tmp_path / "codex" / "sessions" / "2026" / "07" / "27"
        day.mkdir(parents=True, exist_ok=True)
        (day / f"rollout-2026-07-27T12-00-00-not-the-thread-{_THREAD}.jsonl").write_text("{}\n", encoding="utf-8")

        with pytest.raises(AdoptError, match="no conversation"):
            detect_adoption_runtime(ExecutionContext.from_cwd(project), _THREAD)


class TestRuntimeDetection:
    def test_routes_a_codex_thread_to_the_codex_arm(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        _write_rollout(tmp_path, project)
        assert detect_adoption_runtime(ExecutionContext.from_cwd(project), _THREAD) == CODEX_RUNTIME

    def test_routes_a_claude_transcript_to_the_claude_arm(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        path = get_transcript_path(str(project), _THREAD)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"type": "user", "cwd": str(project)}) + "\n", encoding="utf-8")

        assert detect_adoption_runtime(ExecutionContext.from_cwd(project), _THREAD) == "claude_code"

    def test_refuses_to_guess_when_both_runtimes_match(self, tmp_path: Path) -> None:
        """Routing on the id's UUID version would be a guess about a third-party detail."""
        project = _make_project(tmp_path)
        _write_rollout(tmp_path, project)
        path = get_transcript_path(str(project), _THREAD)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"type": "user", "cwd": str(project)}) + "\n", encoding="utf-8")

        with pytest.raises(AdoptError, match="matches both"):
            detect_adoption_runtime(ExecutionContext.from_cwd(project), _THREAD)

    def test_reports_both_search_locations_when_nothing_matches(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        with pytest.raises(AdoptError, match="CODEX_HOME"):
            detect_adoption_runtime(ExecutionContext.from_cwd(project), _THREAD)


class TestCodexAdoptWrites:
    def test_binds_the_thread_without_claude_fields(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        rollout = _write_rollout(tmp_path, project)
        ctx = ExecutionContext.from_cwd(project)

        result = adopt_codex_session(ctx, plan_codex_adoption(ctx, _THREAD), name="adopted")

        assert result.rollout_path == rollout, "the re-resolved path is what callers report"
        state = SessionStore(str(project), result.name).read()
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.thread_id == _THREAD
        assert state.confirmed.codex.rollout_path == str(rollout)
        assert state.confirmed.codex.rollout_source == ROLLOUT_SOURCE_ADOPTED
        assert state.intent.launch is not None
        assert state.intent.launch.runtime == CODEX_RUNTIME

        # The Claude arm's fields must stay unset (card Phase 2, design_appendix I.1).
        assert state.confirmed.claude_session_id is None
        assert state.confirmed.launch is None
        assert state.confirmed.codex.context_delivery is None
        assert state.confirmed.codex.last_run_at is None

    def test_records_adoption_provenance(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        rollout = _write_rollout(tmp_path, project)
        ctx = ExecutionContext.from_cwd(project)

        adopt_codex_session(ctx, plan_codex_adoption(ctx, _THREAD), name="adopted")

        adoption = SessionStore(str(project), "adopted").read().confirmed.adoption
        assert adoption is not None
        assert adoption.source_runtime == "codex"
        assert adoption.source_path == str(rollout)
        assert adoption.model_basis is None, "Codex resolves its own model"

    def test_second_adopt_of_one_thread_is_rejected(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        _write_rollout(tmp_path, project)
        ctx = ExecutionContext.from_cwd(project)
        adopt_codex_session(ctx, plan_codex_adoption(ctx, _THREAD), name="first")

        with pytest.raises(UuidAlreadyBoundError) as excinfo:
            plan_codex_adoption(ctx, _THREAD)
        assert excinfo.value.owner == "first"

    def test_the_rollout_is_never_copied_or_moved(self, tmp_path: Path) -> None:
        """Adoption's input is user-owned state; nothing here touches $CODEX_HOME."""
        project = _make_project(tmp_path)
        rollout = _write_rollout(tmp_path, project)
        before = rollout.read_bytes()
        ctx = ExecutionContext.from_cwd(project)

        adopt_codex_session(ctx, plan_codex_adoption(ctx, _THREAD), name="adopted")

        assert rollout.read_bytes() == before
        artifacts = project / ".forge" / "artifacts" / "adopted" / "transcripts"
        assert not list(artifacts.glob("*.jsonl")) if artifacts.exists() else True

    def test_an_unready_codex_creates_no_state(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Preflight is fail-closed: a session whose only next step fails is worse than none."""
        import forge.core.ops.codex_adopt as mod
        from forge.core.runtime.codex_preflight import CodexPreflightError

        project = _make_project(tmp_path)
        _write_rollout(tmp_path, project)

        class _Unready:
            blocking_reason = "codex binary not found"

        def _not_ready(**_):
            raise CodexPreflightError(_Unready())  # type: ignore[arg-type]  # only blocking_reason is read

        monkeypatch.setattr(mod, "assert_codex_ready", _not_ready)

        with pytest.raises(AdoptError, match="Codex is not ready"):
            plan_codex_adoption(ExecutionContext.from_cwd(project), _THREAD)

        assert not (project / ".forge" / "sessions").exists()

    def test_adopted_session_routes_to_codex_resume_with_no_new_dispatch(self, tmp_path: Path) -> None:
        """The card's Codex-arm claim: resume needs no adoption-specific code.

        `session_runtime` reads the manifest, and the resume leaf branches on it
        (session_lifecycle.py:1345) before any Claude predicate runs.
        """
        from forge.session.models import session_runtime

        project = _make_project(tmp_path)
        _write_rollout(tmp_path, project)
        ctx = ExecutionContext.from_cwd(project)

        adopt_codex_session(ctx, plan_codex_adoption(ctx, _THREAD), name="adopted")

        assert session_runtime(SessionStore(str(project), "adopted").read()) == CODEX_RUNTIME
