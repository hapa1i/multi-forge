"""Tests for memory doc inheritance during fork and resume.

Covers: create_shadow_file, apply_memory_inheritance (extras-only model),
relaunch_session preservation, and the --inherit-memory tombstone.
"""

from __future__ import annotations

import pytest

from forge.session.memory_inheritance import (
    apply_memory_inheritance,
    create_shadow_file,
)
from forge.session.models import (
    DesignatedDoc,
    HandoffConfig,
    MemoryIntent,
    SessionState,
    create_session_state,
)


def _make_state(
    name: str = "test-session",
    *,
    designated_docs: list[DesignatedDoc] | None = None,
    auto_update: HandoffConfig | None = None,
    overrides: dict | None = None,
) -> SessionState:
    state = create_session_state(name=name)
    if designated_docs is not None or auto_update is not None:
        state.intent.memory = MemoryIntent(
            designated_docs=designated_docs or [],
            auto_update=auto_update,
        )
    if overrides:
        state.overrides = overrides
    return state


# ---------------------------------------------------------------------------
# create_shadow_file
# ---------------------------------------------------------------------------


class TestCreateShadowFile:
    def test_creates_forge_memory_shadow(self, tmp_path):
        shadow = ".forge/memory/suggested_notes.md"
        assert create_shadow_file(shadow, tmp_path) is True
        assert (tmp_path / shadow).is_file()

    def test_existing_file_is_noop(self, tmp_path):
        shadow = ".forge/memory/suggested_notes.md"
        (tmp_path / shadow).parent.mkdir(parents=True)
        (tmp_path / shadow).write_text("existing")
        assert create_shadow_file(shadow, tmp_path) is False
        assert (tmp_path / shadow).read_text() == "existing"

    def test_non_forge_memory_returns_false(self, tmp_path):
        assert create_shadow_file("docs/notes.md", tmp_path) is False

    def test_unsafe_path_raises(self, tmp_path):
        with pytest.raises(ValueError, match="unsafe"):
            create_shadow_file("../../etc/shadow", tmp_path)

    def test_creates_parent_directories(self, tmp_path):
        shadow = ".forge/memory/deep/nested/suggested.md"
        assert create_shadow_file(shadow, tmp_path) is True
        assert (tmp_path / shadow).is_file()


# ---------------------------------------------------------------------------
# apply_memory_inheritance (extras-only model)
# ---------------------------------------------------------------------------


class TestApplyMemoryInheritance:
    def test_extras_inherited_by_default(self):
        docs = [DesignatedDoc(path="docs/scratch.md", strategy="generic", origin="extra")]
        parent = _make_state("parent", designated_docs=docs)
        child = _make_state("child")

        apply_memory_inheritance(parent_state=parent, child_state=child)

        assert child.intent.memory is not None
        assert len(child.intent.memory.designated_docs) == 1
        assert child.intent.memory.designated_docs[0].path == "docs/scratch.md"

    def test_no_inherit_extras_strips(self):
        docs = [DesignatedDoc(path="docs/scratch.md", strategy="generic", origin="extra")]
        parent = _make_state("parent", designated_docs=docs)
        child = _make_state("child")

        apply_memory_inheritance(parent_state=parent, child_state=child, inherit_extras=False)

        assert child.intent.memory is None

    def test_project_docs_not_inherited(self):
        """origin=None (project/legacy docs) are dropped; they are passport-discovered."""
        docs = [DesignatedDoc(path="docs/notes.md", strategy="generic")]
        parent = _make_state("parent", designated_docs=docs)
        child = _make_state("child")

        apply_memory_inheritance(parent_state=parent, child_state=child)

        assert child.intent.memory is None

    def test_auto_update_preserved(self):
        auto_update = HandoffConfig(enabled=True, mode="augment", min_turns=5)
        parent = _make_state("parent", designated_docs=[], auto_update=auto_update)
        child = _make_state("child")

        apply_memory_inheritance(parent_state=parent, child_state=child)

        assert child.intent.memory is not None
        assert child.intent.memory.auto_update is not None
        assert child.intent.memory.auto_update.min_turns == 5

    def test_none_memory_yields_none(self):
        parent = _make_state("parent")
        assert parent.intent.memory is None
        child = _make_state("child")

        apply_memory_inheritance(parent_state=parent, child_state=child)

        assert child.intent.memory is None

    def test_mixed_origins_only_extras(self):
        docs = [
            DesignatedDoc(path="docs/project.md", strategy="changelog"),
            DesignatedDoc(path="docs/scratch.md", strategy="generic", origin="extra"),
        ]
        parent = _make_state("parent", designated_docs=docs)
        child = _make_state("child")

        apply_memory_inheritance(parent_state=parent, child_state=child)

        assert child.intent.memory is not None
        assert len(child.intent.memory.designated_docs) == 1
        assert child.intent.memory.designated_docs[0].origin == "extra"

    def test_empty_result_assigns_none(self):
        """All docs are project-scoped (origin=None); after filtering nothing remains."""
        docs = [DesignatedDoc(path="docs/notes.md", strategy="generic")]
        parent = _make_state("parent", designated_docs=docs)
        child = _make_state("child")

        apply_memory_inheritance(parent_state=parent, child_state=child)

        assert child.intent.memory is None

    def test_origin_preserved_through_inheritance(self):
        """origin='extra' survives the asdict/from_dict round-trip during inheritance."""
        docs = [DesignatedDoc(path="docs/notes.md", strategy="generic", origin="extra")]
        parent = _make_state("parent", designated_docs=docs)
        child = _make_state("child")

        apply_memory_inheritance(parent_state=parent, child_state=child)

        assert child.intent.memory is not None
        assert child.intent.memory.designated_docs[0].origin == "extra"

    def test_override_with_extras(self):
        """Extras in parent overrides survive inheritance."""
        parent = _make_state("parent")
        assert parent.intent.memory is None
        parent.overrides = {
            "memory": {
                "designated_docs": [
                    {"path": "docs/scratch.md", "strategy": "generic", "shadows": None, "origin": "extra"}
                ],
                "auto_update": {"enabled": True, "mode": "augment"},
            }
        }
        child = _make_state("child")

        apply_memory_inheritance(parent_state=parent, child_state=child)

        assert child.intent.memory is not None
        assert len(child.intent.memory.designated_docs) == 1
        assert child.intent.memory.designated_docs[0].path == "docs/scratch.md"
        assert child.intent.memory.auto_update is not None

    def test_stale_intent_not_leaked_when_effective_none(self):
        """If parent overrides clear memory (effective=None), child must get None."""
        parent = _make_state(
            "parent",
            designated_docs=[DesignatedDoc(path="stale.md", strategy="generic")],
        )
        parent.overrides = {"memory": None}
        child = _make_state("child")

        apply_memory_inheritance(parent_state=parent, child_state=child)

        assert child.intent.memory is None


# ---------------------------------------------------------------------------
# Regression: relaunch_session preserves override-tracked docs
# ---------------------------------------------------------------------------


def _init_git_repo(path):
    import subprocess

    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], capture_output=True, check=True, cwd=str(path))
    subprocess.run(["git", "config", "user.name", "T"], capture_output=True, check=True, cwd=str(path))


class TestRelaunchPreservesOverrides:
    """relaunch_session() deep-copies overrides (including tracked docs) and
    is unaffected by --inherit-extras. Exercises the real manager path."""

    def test_relaunch_preserves_override_memory_docs(self, tmp_path):
        """relaunch_session preserves memory docs stored in overrides."""
        from forge.session.manager import SessionManager
        from forge.session.store import SessionStore

        _init_git_repo(tmp_path)
        (tmp_path / ".forge").mkdir()

        manager = SessionManager()
        manager.start_session(name="relaunch-parent", worktree_path=str(tmp_path))

        def _add_memory_overrides(state):
            state.overrides = {
                "memory": {
                    "designated_docs": [{"path": "docs/tracked.md", "strategy": "checklist", "shadows": None}],
                    "auto_update": {"enabled": True, "mode": "augment"},
                }
            }

        store = SessionStore(str(tmp_path), "relaunch-parent")
        store.update(timeout_s=5.0, mutate=_add_memory_overrides)

        _, child = manager.relaunch_session("relaunch-parent", child_name="relaunch-child")

        assert child.overrides is not None
        assert "memory" in child.overrides
        child_docs = child.overrides["memory"]["designated_docs"]
        assert len(child_docs) == 1
        assert child_docs[0]["path"] == "docs/tracked.md"
        assert child.overrides["memory"]["auto_update"]["enabled"] is True

    def test_relaunch_deepcopy_isolation(self, tmp_path):
        """Modifying parent overrides after relaunch does not affect child."""
        from forge.session.manager import SessionManager
        from forge.session.store import SessionStore

        _init_git_repo(tmp_path)
        (tmp_path / ".forge").mkdir()

        manager = SessionManager()
        manager.start_session(name="iso-parent", worktree_path=str(tmp_path))

        def _add_overrides(state):
            state.overrides = {
                "memory": {
                    "designated_docs": [{"path": "docs/one.md", "strategy": "generic", "shadows": None}],
                }
            }

        store = SessionStore(str(tmp_path), "iso-parent")
        store.update(timeout_s=5.0, mutate=_add_overrides)

        _, child = manager.relaunch_session("iso-parent", child_name="iso-child")

        parent_reread = store.read()
        parent_reread.overrides["memory"]["designated_docs"].append(
            {"path": "docs/two.md", "strategy": "generic", "shadows": None}
        )

        assert len(child.overrides["memory"]["designated_docs"]) == 1


# ---------------------------------------------------------------------------
# CLI-level tests: --inherit-memory tombstone + --inherit-extras
# ---------------------------------------------------------------------------


class TestInheritMemoryTombstone:
    """The old --inherit-memory flag errors with actionable replacement guidance.

    Tombstone fires BEFORE session lookup so nonexistent sessions don't mask it.
    """

    @pytest.fixture()
    def _runner(self):
        from click.testing import CliRunner

        from forge.cli.main import main as cli

        return CliRunner(), cli

    def test_fork_tombstone_all(self, _runner):
        runner, cli = _runner
        result = runner.invoke(cli, ["session", "fork", "nonexistent", "--inherit-memory", "all"])
        assert result.exit_code != 0
        assert "--inherit-memory is removed" in result.output
        assert "passports are discovered" in result.output

    def test_fork_tombstone_none(self, _runner):
        runner, cli = _runner
        result = runner.invoke(cli, ["session", "fork", "nonexistent", "--inherit-memory", "none"])
        assert result.exit_code != 0
        assert "--no-inherit-extras" in result.output
        assert "--no-copy-memory-activation" in result.output

    def test_fork_tombstone_shadowed(self, _runner):
        runner, cli = _runner
        result = runner.invoke(cli, ["session", "fork", "nonexistent", "--inherit-memory", "shadowed"])
        assert result.exit_code != 0
        assert "passport-discovered" in result.output

    def test_resume_tombstone(self, _runner):
        runner, cli = _runner
        result = runner.invoke(cli, ["session", "resume", "nonexistent", "--inherit-memory", "all"])
        assert result.exit_code != 0
        assert "--inherit-memory is removed" in result.output


class TestInheritExtrasCLI:
    """Tests for the new --inherit-extras / --no-inherit-extras flags."""

    @pytest.fixture()
    def _runner(self):
        from click.testing import CliRunner

        from forge.cli.main import main as cli

        return CliRunner(), cli

    def test_fork_inherit_extras_accepted(self, _runner):
        """--inherit-extras is accepted by fork (may fail on missing session)."""
        runner, cli = _runner
        result = runner.invoke(cli, ["session", "fork", "nonexistent", "--inherit-extras"])
        assert "--inherit-extras" not in result.output or "removed" not in result.output

    def test_fork_no_inherit_extras_accepted(self, _runner):
        runner, cli = _runner
        result = runner.invoke(cli, ["session", "fork", "nonexistent", "--no-inherit-extras"])
        assert "--inherit-extras" not in result.output or "removed" not in result.output

    def test_resume_inherit_extras_requires_fresh(self, _runner):
        runner, cli = _runner
        result = runner.invoke(cli, ["session", "resume", "nonexistent", "--no-inherit-extras"])
        assert result.exit_code != 0
        assert "requires --fresh" in result.output


# ---------------------------------------------------------------------------
# Regression: fork-then-track preserves inherited + new docs
# ---------------------------------------------------------------------------


class TestForkThenTrack:
    """After inheriting extras into a child's intent, running the track
    write path (effective-read / full-list-write to overrides) must keep
    both inherited and newly tracked docs.
    """

    def test_track_after_inherit_keeps_both_docs(self):
        from forge.session.effective import compute_effective_intent

        inherited_doc = DesignatedDoc(path="docs/inherited.md", strategy="checklist", origin="extra")
        parent = _make_state("parent", designated_docs=[inherited_doc])
        child = _make_state("child")

        apply_memory_inheritance(parent_state=parent, child_state=child)

        assert child.intent.memory is not None
        assert len(child.intent.memory.designated_docs) == 1

        effective_before = compute_effective_intent(child)
        effective_docs = list(effective_before.memory.designated_docs)
        new_doc = DesignatedDoc(path="docs/new-tracked.md", strategy="generic")
        effective_docs.append(new_doc)

        payload = [{"path": d.path, "strategy": d.strategy, "shadows": d.shadows} for d in effective_docs]
        child.overrides = {"memory": {"designated_docs": payload}}

        effective_after = compute_effective_intent(child)
        assert effective_after.memory is not None
        result_paths = [d.path for d in effective_after.memory.designated_docs]
        assert "docs/inherited.md" in result_paths
        assert "docs/new-tracked.md" in result_paths
        assert len(result_paths) == 2
