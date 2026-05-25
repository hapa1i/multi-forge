"""Tests for memory doc inheritance during fork and resume.

Covers: InheritMemoryMode, create_shadow_file, _resolve_inheritance_docs,
filter_docs_for_inheritance, materialize_inherited_shadows,
apply_memory_inheritance.
"""

from __future__ import annotations

import pytest

from forge.session.memory_inheritance import (
    InheritanceDoc,
    InheritMemoryMode,
    apply_memory_inheritance,
    create_shadow_file,
    filter_docs_for_inheritance,
    materialize_inherited_shadows,
)
from forge.session.models import (
    DesignatedDoc,
    HandoffConfig,
    MemoryIntent,
    SessionState,
    create_session_state,
)
from forge.session.passport import Passport, PassportUpdate, write_passport


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


def _make_passport(
    *,
    inherit_on_fork: bool = True,
    strategy: str = "generic",
    mode: str = "direct",
    writers: str = "all-sessions",
    shadow_path: str | None = None,
) -> Passport:
    return Passport(
        version=1,
        intent="Test doc",
        update=PassportUpdate(
            strategy=strategy,
            mode=mode,
            writers=writers,
            inherit_on_fork=inherit_on_fork,
            shadow_path=shadow_path,
        ),
    )


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
# filter_docs_for_inheritance
# ---------------------------------------------------------------------------


class TestFilterDocsForInheritance:
    def _resolved(
        self,
        *,
        inherit_on_fork: bool = True,
        is_shadow: bool = False,
        shadow_path: str | None = None,
        writer_spec: str = "all-sessions",
        strategy: str = "generic",
        path: str = "docs/notes.md",
        shadows: str | None = None,
    ) -> InheritanceDoc:
        return InheritanceDoc(
            doc=DesignatedDoc(path=path, strategy=strategy, shadows=shadows),
            passport=_make_passport(inherit_on_fork=inherit_on_fork, writers=writer_spec),
            is_shadow=is_shadow,
            shadow_path=shadow_path,
            writer_spec=writer_spec,
            inherit_on_fork=inherit_on_fork,
        )

    def test_none_mode_excludes_all(self):
        resolved = [self._resolved(), self._resolved(path="other.md")]
        selected, warnings = filter_docs_for_inheritance(
            resolved, mode=InheritMemoryMode.NONE, child_session_name="child", cli_flag_explicit=False
        )
        assert selected == []
        assert warnings == []

    def test_all_mode_includes_all(self):
        resolved = [self._resolved(), self._resolved(path="other.md")]
        selected, warnings = filter_docs_for_inheritance(
            resolved, mode=InheritMemoryMode.ALL, child_session_name="child", cli_flag_explicit=False
        )
        assert len(selected) == 2
        assert warnings == []

    def test_all_mode_respects_passport_inherit_false(self):
        resolved = [
            self._resolved(inherit_on_fork=True, path="keep.md"),
            self._resolved(inherit_on_fork=False, path="drop.md"),
        ]
        selected, warnings = filter_docs_for_inheritance(
            resolved, mode=InheritMemoryMode.ALL, child_session_name="child", cli_flag_explicit=False
        )
        assert len(selected) == 1
        assert selected[0].doc.path == "keep.md"
        assert warnings == []

    def test_all_mode_explicit_overrides_passport(self):
        resolved = [self._resolved(inherit_on_fork=False, path="forced.md")]
        selected, warnings = filter_docs_for_inheritance(
            resolved, mode=InheritMemoryMode.ALL, child_session_name="child", cli_flag_explicit=True
        )
        assert len(selected) == 1
        assert len(warnings) == 1
        assert "overrides" in warnings[0]

    def test_shadowed_mode_only_shadows(self):
        resolved = [
            self._resolved(is_shadow=False, path="direct.md"),
            self._resolved(is_shadow=True, path=".forge/memory/suggested.md", shadows="docs/official.md"),
        ]
        selected, warnings = filter_docs_for_inheritance(
            resolved, mode=InheritMemoryMode.SHADOWED, child_session_name="child", cli_flag_explicit=False
        )
        assert len(selected) == 1
        assert selected[0].doc.path == ".forge/memory/suggested.md"

    def test_shadowed_mode_respects_passport_inherit_false(self):
        resolved = [self._resolved(is_shadow=True, inherit_on_fork=False, path="shadow.md")]
        selected, _ = filter_docs_for_inheritance(
            resolved, mode=InheritMemoryMode.SHADOWED, child_session_name="child", cli_flag_explicit=False
        )
        assert selected == []

    def test_shadowed_mode_explicit_overrides_passport(self):
        resolved = [self._resolved(is_shadow=True, inherit_on_fork=False, path="shadow.md")]
        selected, warnings = filter_docs_for_inheritance(
            resolved, mode=InheritMemoryMode.SHADOWED, child_session_name="child", cli_flag_explicit=True
        )
        assert len(selected) == 1
        assert len(warnings) == 1

    def test_writer_authorization_warning(self):
        resolved = [self._resolved(writer_spec="planner")]
        selected, warnings = filter_docs_for_inheritance(
            resolved, mode=InheritMemoryMode.ALL, child_session_name="executor", cli_flag_explicit=False
        )
        assert len(selected) == 1
        assert any("writers=" in w for w in warnings)

    def test_writer_all_sessions_no_warning(self):
        resolved = [self._resolved(writer_spec="all-sessions")]
        _, warnings = filter_docs_for_inheritance(
            resolved, mode=InheritMemoryMode.ALL, child_session_name="child", cli_flag_explicit=False
        )
        assert not any("writers=" in w for w in warnings)

    def test_no_child_name_skips_writer_check(self):
        resolved = [self._resolved(writer_spec="planner")]
        _, warnings = filter_docs_for_inheritance(
            resolved, mode=InheritMemoryMode.ALL, child_session_name=None, cli_flag_explicit=False
        )
        assert not any("writers=" in w for w in warnings)


# ---------------------------------------------------------------------------
# materialize_inherited_shadows
# ---------------------------------------------------------------------------


class TestMaterializeInheritedShadows:
    def _shadow_doc(self, shadow_path: str) -> InheritanceDoc:
        return InheritanceDoc(
            doc=DesignatedDoc(path=shadow_path, strategy="suggested", shadows="official.md"),
            passport=None,
            is_shadow=True,
            shadow_path=shadow_path,
            writer_spec="all-sessions",
            inherit_on_fork=True,
        )

    def test_creates_forge_memory_shadow(self, tmp_path):
        doc = self._shadow_doc(".forge/memory/suggested.md")
        created, skipped = materialize_inherited_shadows([doc], tmp_path)
        assert len(created) == 1
        assert (tmp_path / ".forge/memory/suggested.md").is_file()
        assert skipped == []

    def test_skips_non_forge_memory_shadow(self, tmp_path):
        doc = self._shadow_doc("docs/suggested.md")
        created, skipped = materialize_inherited_shadows([doc], tmp_path)
        assert created == []
        assert len(skipped) == 1

    def test_existing_file_not_recreated(self, tmp_path):
        shadow = ".forge/memory/suggested.md"
        (tmp_path / shadow).parent.mkdir(parents=True)
        (tmp_path / shadow).write_text("existing")
        doc = self._shadow_doc(shadow)
        created, skipped = materialize_inherited_shadows([doc], tmp_path)
        assert created == []
        assert skipped == []
        assert (tmp_path / shadow).read_text() == "existing"

    def test_skips_non_shadow_docs(self, tmp_path):
        doc = InheritanceDoc(
            doc=DesignatedDoc(path="docs/notes.md", strategy="generic"),
            passport=None,
            is_shadow=False,
            shadow_path=None,
            writer_spec="all-sessions",
            inherit_on_fork=True,
        )
        created, skipped = materialize_inherited_shadows([doc], tmp_path)
        assert created == []
        assert skipped == []


# ---------------------------------------------------------------------------
# apply_memory_inheritance
# ---------------------------------------------------------------------------


class TestApplyMemoryInheritance:
    def test_all_mode_preserves_docs(self, tmp_path):
        docs = [DesignatedDoc(path="docs/notes.md", strategy="generic")]
        parent = _make_state("parent", designated_docs=docs)
        child = _make_state("child")

        shadow_docs, warnings = apply_memory_inheritance(
            parent_state=parent,
            child_state=child,
            mode=InheritMemoryMode.ALL,
            parent_forge_root=tmp_path,
            child_session_name="child",
            cli_flag_explicit=False,
        )
        assert child.intent.memory is not None
        assert len(child.intent.memory.designated_docs) == 1
        assert child.intent.memory.designated_docs[0].path == "docs/notes.md"

    def test_all_mode_preserves_origin(self, tmp_path):
        """origin='extra' survives the asdict/from_dict round-trip during inheritance."""
        docs = [DesignatedDoc(path="docs/notes.md", strategy="generic", origin="extra")]
        parent = _make_state("parent", designated_docs=docs)
        child = _make_state("child")

        apply_memory_inheritance(
            parent_state=parent,
            child_state=child,
            mode=InheritMemoryMode.ALL,
            parent_forge_root=tmp_path,
            child_session_name="child",
            cli_flag_explicit=False,
        )
        assert child.intent.memory is not None
        assert child.intent.memory.designated_docs[0].origin == "extra"

    def test_none_mode_clears_docs_and_auto_update(self, tmp_path):
        docs = [DesignatedDoc(path="docs/notes.md", strategy="generic")]
        auto_update = HandoffConfig(enabled=True, mode="augment")
        parent = _make_state("parent", designated_docs=docs, auto_update=auto_update)
        child = _make_state("child")

        apply_memory_inheritance(
            parent_state=parent,
            child_state=child,
            mode=InheritMemoryMode.NONE,
            parent_forge_root=tmp_path,
            child_session_name="child",
            cli_flag_explicit=False,
        )
        assert child.intent.memory is None

    def test_none_preserves_effective_memory(self, tmp_path):
        parent = _make_state("parent")
        assert parent.intent.memory is None
        child = _make_state("child")

        apply_memory_inheritance(
            parent_state=parent,
            child_state=child,
            mode=InheritMemoryMode.NONE,
            parent_forge_root=tmp_path,
            child_session_name="child",
            cli_flag_explicit=False,
        )
        assert child.intent.memory is None

    def test_empty_result_assigns_none(self, tmp_path):
        docs = [DesignatedDoc(path="docs/notes.md", strategy="generic")]
        parent = _make_state("parent", designated_docs=docs)

        # Write passport with inherit_on_fork=False
        doc_path = tmp_path / "docs/notes.md"
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text("# Notes")
        write_passport(doc_path, _make_passport(inherit_on_fork=False))

        child = _make_state("child")
        apply_memory_inheritance(
            parent_state=parent,
            child_state=child,
            mode=InheritMemoryMode.ALL,
            parent_forge_root=tmp_path,
            child_session_name="child",
            cli_flag_explicit=False,
        )
        assert child.intent.memory is None

    def test_override_only_happy_path(self, tmp_path):
        """Parent has no intent.memory; docs exist only in overrides."""
        parent = _make_state("parent")
        assert parent.intent.memory is None
        parent.overrides = {
            "memory": {
                "designated_docs": [{"path": "docs/checklist.md", "strategy": "checklist", "shadows": None}],
                "auto_update": {"enabled": True, "mode": "augment"},
            }
        }

        child = _make_state("child")
        apply_memory_inheritance(
            parent_state=parent,
            child_state=child,
            mode=InheritMemoryMode.ALL,
            parent_forge_root=tmp_path,
            child_session_name="child",
            cli_flag_explicit=False,
        )
        assert child.intent.memory is not None
        assert len(child.intent.memory.designated_docs) == 1
        assert child.intent.memory.designated_docs[0].path == "docs/checklist.md"
        assert child.intent.memory.auto_update is not None
        assert child.intent.memory.auto_update.enabled is True

    def test_none_on_null_effective_memory(self, tmp_path):
        """When effective memory is None, child gets None."""
        parent = _make_state("parent")
        child = _make_state("child")

        apply_memory_inheritance(
            parent_state=parent,
            child_state=child,
            mode=InheritMemoryMode.ALL,
            parent_forge_root=tmp_path,
            child_session_name="child",
            cli_flag_explicit=False,
        )
        assert child.intent.memory is None

    def test_shadowed_mode_filters_to_shadows(self, tmp_path):
        docs = [
            DesignatedDoc(path="docs/notes.md", strategy="generic"),
            DesignatedDoc(path=".forge/memory/suggested.md", strategy="suggested", shadows="docs/official.md"),
        ]
        parent = _make_state("parent", designated_docs=docs)
        child = _make_state("child")

        shadow_docs, _ = apply_memory_inheritance(
            parent_state=parent,
            child_state=child,
            mode=InheritMemoryMode.SHADOWED,
            parent_forge_root=tmp_path,
            child_session_name="child",
            cli_flag_explicit=False,
        )
        assert child.intent.memory is not None
        assert len(child.intent.memory.designated_docs) == 1
        assert child.intent.memory.designated_docs[0].shadows == "docs/official.md"
        assert len(shadow_docs) == 1

    def test_passport_authoritative_shadow_classification(self, tmp_path):
        """A doc with mode=shadow-only in passport but doc.shadows=None is still shadow."""
        doc_path = tmp_path / "docs/official.md"
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text("# Official")
        write_passport(
            doc_path,
            _make_passport(mode="shadow-only", shadow_path=".forge/memory/suggested.md"),
        )

        docs = [DesignatedDoc(path="docs/official.md", strategy="generic")]
        parent = _make_state("parent", designated_docs=docs)
        child = _make_state("child")

        shadow_docs, _ = apply_memory_inheritance(
            parent_state=parent,
            child_state=child,
            mode=InheritMemoryMode.SHADOWED,
            parent_forge_root=tmp_path,
            child_session_name="child",
            cli_flag_explicit=False,
        )
        assert child.intent.memory is not None
        assert len(child.intent.memory.designated_docs) == 1
        assert len(shadow_docs) == 1

    def test_missing_passport_defaults_to_inherit(self, tmp_path):
        docs = [DesignatedDoc(path="docs/nonexistent.md", strategy="generic")]
        parent = _make_state("parent", designated_docs=docs)
        child = _make_state("child")

        apply_memory_inheritance(
            parent_state=parent,
            child_state=child,
            mode=InheritMemoryMode.ALL,
            parent_forge_root=tmp_path,
            child_session_name="child",
            cli_flag_explicit=False,
        )
        assert child.intent.memory is not None
        assert len(child.intent.memory.designated_docs) == 1

    def test_malformed_passport_warns_and_defaults(self, tmp_path):
        doc_path = tmp_path / "docs/notes.md"
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text("---\nforge_memory:\n  version: 1\n  update:\n    strategy: 999\n---\n# Notes")

        docs = [DesignatedDoc(path="docs/notes.md", strategy="generic")]
        parent = _make_state("parent", designated_docs=docs)
        child = _make_state("child")

        _, warnings = apply_memory_inheritance(
            parent_state=parent,
            child_state=child,
            mode=InheritMemoryMode.ALL,
            parent_forge_root=tmp_path,
            child_session_name="child",
            cli_flag_explicit=False,
        )
        assert child.intent.memory is not None
        assert len(child.intent.memory.designated_docs) == 1
        assert any("Malformed" in w for w in warnings)

    def test_auto_update_preserved_in_all_mode(self, tmp_path):
        auto_update = HandoffConfig(enabled=True, mode="augment", min_turns=5)
        parent = _make_state("parent", designated_docs=[], auto_update=auto_update)
        child = _make_state("child")

        apply_memory_inheritance(
            parent_state=parent,
            child_state=child,
            mode=InheritMemoryMode.ALL,
            parent_forge_root=tmp_path,
            child_session_name="child",
            cli_flag_explicit=False,
        )
        assert child.intent.memory is not None
        assert child.intent.memory.auto_update is not None
        assert child.intent.memory.auto_update.min_turns == 5

    def test_stale_intent_not_leaked_when_effective_none(self, tmp_path):
        """If parent overrides clear memory (effective=None), child must get None."""
        parent = _make_state(
            "parent",
            designated_docs=[DesignatedDoc(path="stale.md", strategy="generic")],
        )
        parent.overrides = {"memory": None}

        child = _make_state("child")
        apply_memory_inheritance(
            parent_state=parent,
            child_state=child,
            mode=InheritMemoryMode.ALL,
            parent_forge_root=tmp_path,
            child_session_name="child",
            cli_flag_explicit=False,
        )
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
    is unaffected by --inherit-memory. Exercises the real manager path."""

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
# CLI-level tests for --inherit-memory
# ---------------------------------------------------------------------------


class TestInheritMemoryCLI:
    """Tests for the --inherit-memory CLI option on fork and resume."""

    def test_resume_inherit_memory_without_fresh_errors(self):
        """Explicit --inherit-memory without --fresh should error."""
        from click.testing import CliRunner

        from forge.cli.main import main as cli

        runner = CliRunner()
        result = runner.invoke(cli, ["session", "resume", "nonexistent", "--inherit-memory", "none"])
        assert result.exit_code != 0
        assert "--inherit-memory requires --fresh" in result.output

    def test_resume_inherit_memory_all_without_fresh_errors(self):
        """Even --inherit-memory all (seeming no-op) requires --fresh."""
        from click.testing import CliRunner

        from forge.cli.main import main as cli

        runner = CliRunner()
        result = runner.invoke(cli, ["session", "resume", "nonexistent", "--inherit-memory", "all"])
        assert result.exit_code != 0
        assert "--inherit-memory requires --fresh" in result.output

    def test_fork_inherit_memory_option_accepted(self):
        """--inherit-memory is accepted by fork (may fail on missing session)."""
        from click.testing import CliRunner

        from forge.cli.main import main as cli

        runner = CliRunner()
        result = runner.invoke(cli, ["session", "fork", "nonexistent", "--inherit-memory", "shadowed"])
        assert "--inherit-memory" not in result.output or "requires" not in result.output

    def test_fork_inherit_memory_invalid_choice_rejected(self):
        """Invalid --inherit-memory value is rejected by Click."""
        from click.testing import CliRunner

        from forge.cli.main import main as cli

        runner = CliRunner()
        result = runner.invoke(cli, ["session", "fork", "nonexistent", "--inherit-memory", "invalid"])
        assert result.exit_code != 0
        assert "Invalid value" in result.output or "invalid" in result.output.lower()


# ---------------------------------------------------------------------------
# Regression: fork-then-track preserves inherited + new docs
# ---------------------------------------------------------------------------


class TestForkThenTrack:
    """After inheriting docs into a child's intent, running the track
    write path (effective-read / full-list-write to overrides) must keep
    both inherited and newly tracked docs.

    This locks in the invariant from memory.py: _current_docs reads
    effective (intent + overrides merged) and _write_docs replaces the
    whole list in overrides. If _write_docs ever switched to append-only
    deltas, inherited docs in intent would be silently dropped.
    """

    def test_track_after_inherit_keeps_both_docs(self, tmp_path):
        from forge.session.effective import compute_effective_intent

        inherited_doc = DesignatedDoc(path="docs/inherited.md", strategy="checklist")
        parent = _make_state("parent", designated_docs=[inherited_doc])
        child = _make_state("child")

        apply_memory_inheritance(
            parent_state=parent,
            child_state=child,
            mode=InheritMemoryMode.ALL,
            parent_forge_root=tmp_path,
            child_session_name="child",
            cli_flag_explicit=False,
        )

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
