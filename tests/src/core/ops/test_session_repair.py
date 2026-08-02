"""Tests for the session orphan repair op (scan + apply)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from forge.core.ops.session_repair import (
    RepairScanReport,
    repair_orphans,
    scan_repairable_orphans,
)
from forge.install.project_compat import ProjectCompatibilityError
from forge.session import IndexStore, SessionManager, SessionStore, create_session_state
from forge.session.exceptions import ManifestChangedError
from forge.session.identity import make_scoped_key
from forge.session.models import CodexConfirmed, SessionState, session_state_to_dict
from forge.session.store import CLI_LOCK_TIMEOUT_S, get_manifest_path


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Git repo with a .forge/ dir: a plain Forge project root."""
    root = tmp_path / "proj"
    root.mkdir()
    _git(["init"], root)
    _git(["config", "user.email", "test@test.com"], root)
    _git(["config", "user.name", "Test"], root)
    (root / "README.md").write_text("# test\n")
    _git(["add", "."], root)
    _git(["commit", "-m", "init"], root)
    (root / ".forge").mkdir()
    return root


_ROOT = "sentinel: use the project root"


def seed_orphan(
    root: Path,
    name: str,
    *,
    worktree_path: str | None = _ROOT,
    is_worktree: bool = False,
    owns_worktree: bool = True,
    claude_id: str | None = None,
    thread_id: str | None = None,
) -> SessionState:
    """Write a manifest with no index row: the orphan state under repair.

    ``worktree_path=None`` seeds a manifest with no worktree block; the default
    records the project root itself (the ordinary healthy shape).
    """
    state = create_session_state(name, worktree_path=str(root) if worktree_path is _ROOT else worktree_path)
    if is_worktree:
        assert state.worktree is not None
        state.worktree.is_worktree = True
    if not owns_worktree:
        assert state.worktree is not None
        state.worktree.owns_worktree = False
    if claude_id:
        state.confirmed.claude_session_id = claude_id
    if thread_id:
        state.confirmed.codex = CodexConfirmed(thread_id=thread_id)
    SessionStore(str(root), name).write(state)
    return state


def seed_live(
    root: Path,
    name: str,
    *,
    claude_id: str | None = None,
    thread_id: str | None = None,
) -> SessionState:
    """Write a manifest plus its index row: a healthy session."""
    state = seed_orphan(root, name, claude_id=claude_id, thread_id=thread_id)
    IndexStore().add_from_state(state, str(root), forge_root=str(root), checkout_root=str(root))
    return state


def _rows() -> dict[str, object]:
    return dict(IndexStore().read().sessions)


class TestScan:
    def test_no_sessions_dir_is_empty(self, project: Path) -> None:
        report = scan_repairable_orphans(project)
        assert report.records == ()
        assert report.forge_root == str(project)

    def test_healthy_session_not_reported(self, project: Path) -> None:
        seed_live(project, "healthy")
        report = scan_repairable_orphans(project)
        assert report.records == ()

    def test_session_dir_without_manifest_skipped(self, project: Path) -> None:
        (project / ".forge" / "sessions" / "bare-dir").mkdir(parents=True)
        report = scan_repairable_orphans(project)
        assert report.records == ()

    def test_recorded_checkout_present_is_repairable(self, project: Path) -> None:
        seed_orphan(project, "orphan", claude_id="uuid-1")
        report = scan_repairable_orphans(project)

        assert len(report.records) == 1
        rec = report.records[0]
        assert rec.classification == "repairable"
        assert rec.name == "orphan"
        assert rec.claude_session_id == "uuid-1"
        assert rec.manifest_sha256 is not None
        assert rec.identity is not None
        assert rec.identity.worktree_path == str(project)
        assert rec.identity.checkout_root == str(project)
        assert rec.identity.project_root == str(project)
        assert rec.identity.relative_path == "."
        assert rec.identity.corrected_worktree_path is None

    def test_ordinary_moved_checkout_repairable_with_correction(self, project: Path, tmp_path: Path) -> None:
        gone = tmp_path / "old-location"
        seed_orphan(project, "moved", worktree_path=str(gone))
        report = scan_repairable_orphans(project)

        rec = report.records[0]
        assert rec.classification == "repairable"
        assert rec.identity is not None
        assert rec.identity.corrected_worktree_path == str(project)
        assert str(gone) in rec.detail

    def test_missing_worktree_reports_only(self, project: Path, tmp_path: Path) -> None:
        gone = tmp_path / "deleted-worktree"
        seed_orphan(project, "wt-orphan", worktree_path=str(gone), is_worktree=True)
        report = scan_repairable_orphans(project)

        rec = report.records[0]
        assert rec.classification == "missing-worktree"
        assert rec.identity is None
        assert str(gone) in rec.detail

    def test_claude_uuid_collision(self, project: Path) -> None:
        seed_live(project, "live-one", claude_id="uuid-taken")
        seed_orphan(project, "orphan", claude_id="uuid-taken")
        report = scan_repairable_orphans(project)

        assert len(report.records) == 1
        rec = report.records[0]
        assert rec.classification == "collision"
        assert rec.collision_holder is not None
        assert "live-one" in rec.collision_holder

    def test_collision_when_row_column_lags_live_manifest(self, project: Path) -> None:
        """Review round 3 CRITICAL: a live manifest binding not yet reconciled
        into its row column must still block the orphan (columns lag manifests)."""
        state = seed_orphan(project, "live-lagging")
        IndexStore().add_from_state(state, str(project), forge_root=str(project))
        store = SessionStore(str(project), "live-lagging")
        live = store.read()
        live.confirmed.claude_session_id = "uuid-lag"
        store.write(live)
        assert IndexStore().read().sessions[make_scoped_key("live-lagging", str(project))].claude_session_id is None

        seed_orphan(project, "orphan", claude_id="uuid-lag")
        report = scan_repairable_orphans(project)

        assert len(report.records) == 1
        rec = report.records[0]
        assert rec.classification == "collision"
        assert rec.collision_holder is not None
        assert "live-lagging" in rec.collision_holder

    def test_collision_when_thread_lives_only_on_live_manifest(self, project: Path) -> None:
        """Ordinary Codex sessions record their thread on the manifest alone."""
        state = seed_orphan(project, "live-codex-lag")
        IndexStore().add_from_state(state, str(project), forge_root=str(project))
        store = SessionStore(str(project), "live-codex-lag")
        live = store.read()
        live.confirmed.codex = CodexConfirmed(thread_id="thread-lag")
        store.write(live)

        seed_orphan(project, "orphan", thread_id="thread-lag")
        report = scan_repairable_orphans(project)

        rec = report.records[0]
        assert rec.classification == "collision"
        assert rec.collision_holder is not None
        assert "live-codex-lag" in rec.collision_holder

    def test_sibling_orphans_sharing_conversation(self, project: Path) -> None:
        """Two orphans claiming one conversation: directory order wins, the later
        one classifies collision so apply can never double-bind."""
        seed_orphan(project, "a-first", claude_id="uuid-shared")
        seed_orphan(project, "b-second", claude_id="uuid-shared")

        report = scan_repairable_orphans(project)
        by_name = {r.name: r for r in report.records}
        assert by_name["a-first"].classification == "repairable"
        assert by_name["b-second"].classification == "collision"
        assert by_name["b-second"].collision_holder == "a-first"

    def test_codex_thread_collision(self, project: Path) -> None:
        seed_live(project, "live-codex", thread_id="thread-taken")
        seed_orphan(project, "orphan", thread_id="thread-taken")
        report = scan_repairable_orphans(project)

        rec = report.records[0]
        assert rec.classification == "collision"
        assert rec.collision_holder is not None
        assert "live-codex" in rec.collision_holder

    def test_corrupt_manifest(self, project: Path) -> None:
        path = get_manifest_path(project, "broken")
        path.parent.mkdir(parents=True)
        path.write_text("{ not json")
        report = scan_repairable_orphans(project)

        rec = report.records[0]
        assert rec.classification == "corrupt"

    def test_non_dict_manifest_is_corrupt(self, project: Path) -> None:
        """Review round 3: valid JSON with the wrong top-level shape must classify
        corrupt, not crash the scan with a raw AttributeError."""
        path = get_manifest_path(project, "listy")
        path.parent.mkdir(parents=True)
        path.write_text("[]")
        report = scan_repairable_orphans(project)

        rec = report.records[0]
        assert rec.classification == "corrupt"

    def test_dir_name_mismatch_is_corrupt(self, project: Path) -> None:
        """Review round 3: a manifest naming a different session than its directory
        violates the store invariant; classify corrupt, never 'repair' it into a
        row for the wrong name."""
        state = create_session_state("other-name", worktree_path=str(project))
        path = get_manifest_path(project, "mismatch")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(session_state_to_dict(state)))

        report = scan_repairable_orphans(project)
        rec = report.records[0]
        assert rec.name == "mismatch"
        assert rec.classification == "corrupt"
        assert "other-name" in rec.detail

    def test_unreadable_manifest(self, project: Path) -> None:
        path = get_manifest_path(project, "locked")
        path.parent.mkdir(parents=True)
        path.write_text("{}")
        path.chmod(0o000)
        try:
            report = scan_repairable_orphans(project)
        finally:
            path.chmod(0o644)

        rec = report.records[0]
        assert rec.classification == "unreadable"

    def test_manifest_without_worktree_block_unrepairable(self, project: Path) -> None:
        seed_orphan(project, "no-wt", worktree_path=None)
        # create_session_state only omits the worktree block when no path is given
        state = SessionStore(str(project), "no-wt").read()
        assert state.worktree is None

        report = scan_repairable_orphans(project)
        rec = report.records[0]
        assert rec.classification == "unrepairable"

    def test_scan_is_read_only(self, project: Path, tmp_path: Path) -> None:
        """Index bytes and manifest mtimes unchanged with every classification seeded."""
        seed_live(project, "healthy")
        seed_orphan(project, "repairable-one")
        seed_orphan(project, "moved", worktree_path=str(tmp_path / "old"))
        seed_orphan(project, "wt-gone", worktree_path=str(tmp_path / "gone"), is_worktree=True)
        seed_orphan(project, "no-wt", worktree_path=None)
        seed_live(project, "holder", claude_id="uuid-dup")
        seed_orphan(project, "colliding", claude_id="uuid-dup")
        broken = get_manifest_path(project, "broken")
        broken.parent.mkdir(parents=True)
        broken.write_text("{ not json")
        locked = get_manifest_path(project, "locked")
        locked.parent.mkdir(parents=True)
        locked.write_text("{}")
        locked.chmod(0o000)

        index_path = IndexStore().index_path
        index_before = index_path.read_bytes()
        manifests = sorted((project / ".forge" / "sessions").glob("*/forge.session.json"))
        mtimes_before = [m.stat().st_mtime_ns for m in manifests]

        try:
            report = scan_repairable_orphans(project)
        finally:
            locked.chmod(0o644)

        assert {r.classification for r in report.records} == {
            "repairable",
            "missing-worktree",
            "collision",
            "corrupt",
            "unreadable",
            "unrepairable",
        }
        assert index_path.read_bytes() == index_before
        assert [m.stat().st_mtime_ns for m in manifests] == mtimes_before

    def test_root_level_worktree_present_is_repairable(self, project: Path, tmp_path: Path) -> None:
        linked = tmp_path / "linked-wt"
        _git(["worktree", "add", str(linked), "-b", "lw"], project)
        seed_orphan(project, "root-wt", worktree_path=str(linked), is_worktree=True)

        report = scan_repairable_orphans(project)
        rec = report.records[0]
        assert rec.classification == "repairable"
        assert rec.identity is not None
        # Identity derives from the recorded worktree (D1), not the manifest's
        # location under the main checkout.
        assert Path(rec.identity.worktree_path).resolve() == linked.resolve()
        assert rec.identity.project_root == str(project)
        assert rec.identity.relative_path == "."

    def test_root_level_worktree_gone_reports_only(self, project: Path, tmp_path: Path) -> None:
        linked = tmp_path / "linked-wt"
        _git(["worktree", "add", str(linked), "-b", "lw"], project)
        seed_orphan(project, "root-wt", worktree_path=str(linked), is_worktree=True)
        shutil.rmtree(linked)

        report = scan_repairable_orphans(project)
        assert report.records[0].classification == "missing-worktree"

    def test_nested_project_worktree_shape(self, project: Path, tmp_path: Path) -> None:
        """Nested shape: forge_root remapped into the linked worktree, manifest inside it."""
        linked = tmp_path / "nested-wt"
        _git(["worktree", "add", str(linked), "-b", "nw"], project)
        (linked / ".forge").mkdir()
        seed_orphan(linked, "nested", worktree_path=str(linked), is_worktree=True)

        report = scan_repairable_orphans(linked)
        rec = report.records[0]
        assert rec.classification == "repairable"
        assert rec.identity is not None
        assert Path(rec.identity.worktree_path).resolve() == linked.resolve()
        assert Path(rec.identity.checkout_root).resolve() == linked.resolve()
        # project_root resolves to the main repository, matching creation.
        assert rec.identity.project_root == str(project)
        assert rec.identity.relative_path == "."


class TestApply:
    def _scan(self, project: Path) -> RepairScanReport:
        return scan_repairable_orphans(project)

    def test_repair_publishes_row(self, project: Path) -> None:
        seed_orphan(project, "orphan", claude_id="uuid-1")
        result = repair_orphans(project, self._scan(project).records)

        assert result.repaired == ("orphan",)
        assert result.clean
        rows = IndexStore().read().sessions
        entry = rows[make_scoped_key("orphan", str(project))]
        assert entry.forge_root == str(project)
        assert entry.worktree_path == str(project)
        assert entry.checkout_root == str(project)
        assert entry.relative_path == "."
        assert entry.claude_session_id == "uuid-1"

        # Prune stability (D2): the repaired row survives a list_sessions pass.
        listed = SessionManager().list_sessions()
        assert any(entry.forge_root == str(project) for _, entry in listed)
        assert make_scoped_key("orphan", str(project)) in IndexStore().read().sessions

    def test_into_guest_preserves_owns_worktree(self, project: Path, tmp_path: Path) -> None:
        linked = tmp_path / "guest-wt"
        _git(["worktree", "add", str(linked), "-b", "gw"], project)
        seed_orphan(project, "guest", worktree_path=str(linked), is_worktree=True, owns_worktree=False)

        result = repair_orphans(project, self._scan(project).records)

        assert result.repaired == ("guest",)
        state = SessionStore(str(project), "guest").read()
        assert state.worktree is not None
        assert state.worktree.owns_worktree is False
        entry = IndexStore().read().sessions[make_scoped_key("guest", str(project))]
        assert entry.worktree_path == str(linked)

    def test_repair_leaves_manifest_untouched_when_path_current(self, project: Path) -> None:
        seed_orphan(project, "orphan")
        manifest = get_manifest_path(project, "orphan")
        before = manifest.read_bytes()

        result = repair_orphans(project, self._scan(project).records)

        assert result.repaired == ("orphan",)
        assert manifest.read_bytes() == before

    def test_repair_corrects_stale_recorded_path_on_disk(self, project: Path, tmp_path: Path) -> None:
        gone = tmp_path / "old-location"
        seed_orphan(project, "moved", worktree_path=str(gone))

        result = repair_orphans(project, self._scan(project).records)

        assert result.repaired == ("moved",)
        state = SessionStore(str(project), "moved").read()
        assert state.worktree is not None
        assert state.worktree.path == str(project)
        entry = IndexStore().read().sessions[make_scoped_key("moved", str(project))]
        assert entry.worktree_path == str(project)

    def test_moved_repair_relocates_forge_root_not_claude_namespace(self, project: Path, tmp_path: Path) -> None:
        """Review round 3: a manager-shaped manifest (forge_root wired, launch CWD
        recorded) relocates forge_root with the move, while the Claude namespace
        pointer stays -- the conversation transcripts did not move."""
        gone = tmp_path / "old-location"
        state = create_session_state("moved-full", worktree_path=str(gone))
        state.forge_root = str(gone)
        state.confirmed.claude_project_root = str(gone)
        SessionStore(str(project), "moved-full").write(state)

        result = repair_orphans(project, self._scan(project).records)

        assert result.repaired == ("moved-full",)
        repaired = SessionStore(str(project), "moved-full").read()
        assert repaired.forge_root == str(project)
        assert repaired.worktree is not None
        assert repaired.worktree.path == str(project)
        assert repaired.confirmed.claude_project_root == str(gone)

    def test_collision_refused_without_write(self, project: Path) -> None:
        seed_live(project, "live-one", claude_id="uuid-taken")
        seed_orphan(project, "orphan", claude_id="uuid-taken")

        result = repair_orphans(project, self._scan(project).records)

        assert result.repaired == ()
        assert len(result.refused) == 1
        assert result.refused[0].name == "orphan"
        assert make_scoped_key("orphan", str(project)) not in IndexStore().read().sessions

    def test_vanished_checkout_refused(self, project: Path, tmp_path: Path) -> None:
        linked = tmp_path / "linked-wt"
        _git(["worktree", "add", str(linked), "-b", "lw"], project)
        seed_orphan(project, "root-wt", worktree_path=str(linked), is_worktree=True)

        records = self._scan(project).records
        shutil.rmtree(linked)
        result = repair_orphans(project, records)

        assert result.repaired == ()
        assert len(result.refused) == 1
        assert "vanished between scan and apply" in result.refused[0].reason
        assert make_scoped_key("root-wt", str(project)) not in IndexStore().read().sessions

    def test_manifest_deleted_between_scan_and_apply_refused(self, project: Path) -> None:
        seed_orphan(project, "orphan")
        records = self._scan(project).records
        get_manifest_path(project, "orphan").unlink()

        result = repair_orphans(project, records)

        assert result.repaired == ()
        assert len(result.refused) == 1
        assert "no longer readable" in result.refused[0].reason
        assert make_scoped_key("orphan", str(project)) not in IndexStore().read().sessions

    def test_tampered_manifest_refused_before_txn(self, project: Path) -> None:
        state = seed_orphan(project, "orphan")
        records = self._scan(project).records
        state.confirmed.claude_session_id = "changed-after-scan"
        SessionStore(str(project), "orphan").write(state)

        result = repair_orphans(project, records)

        assert result.repaired == ()
        assert len(result.refused) == 1
        assert "changed since it was scanned" in result.refused[0].reason
        assert make_scoped_key("orphan", str(project)) not in IndexStore().read().sessions

    def test_name_claimed_since_scan_refused(self, project: Path) -> None:
        state = seed_orphan(project, "orphan")
        records = self._scan(project).records
        IndexStore().add_from_state(state, str(project), forge_root=str(project))

        result = repair_orphans(project, records)

        assert result.repaired == ()
        assert len(result.refused) == 1
        assert "claimed by a live session" in result.refused[0].reason

    def test_uuid_bound_since_scan_refused(self, project: Path) -> None:
        seed_orphan(project, "orphan", claude_id="uuid-race")
        records = self._scan(project).records
        seed_live(project, "winner", claude_id="uuid-race")

        result = repair_orphans(project, records)

        assert result.repaired == ()
        assert len(result.refused) == 1
        assert "bound to a live session" in result.refused[0].reason
        assert make_scoped_key("orphan", str(project)) not in IndexStore().read().sessions

    def test_report_only_classes_skipped(self, project: Path, tmp_path: Path) -> None:
        seed_orphan(project, "no-wt", worktree_path=None)
        seed_orphan(project, "wt-gone", worktree_path=str(tmp_path / "gone"), is_worktree=True)
        path = get_manifest_path(project, "broken")
        path.parent.mkdir(parents=True)
        path.write_text("{ not json")

        result = repair_orphans(project, self._scan(project).records)

        assert result.repaired == ()
        assert result.refused == ()
        assert result.failed == ()
        assert result.clean
        assert _rows() == {}

    def test_incompatible_pin_fails_closed(self, project: Path) -> None:
        seed_orphan(project, "orphan")
        records = self._scan(project).records
        (project / ".forge" / "project.toml").write_text('schema_version = 1\nrequired_forge = ">=99.0"\n')

        with pytest.raises(ProjectCompatibilityError):
            repair_orphans(project, records)

        assert _rows() == {}

    def test_clean_and_repair_ownership_disjoint(self, project: Path) -> None:
        """D4: clean removes only corrupt; repair claims only repairable; unreadable belongs to neither."""
        from forge.core.ops.gc import _detect_corrupt_state

        seed_orphan(project, "fixable")
        broken = get_manifest_path(project, "broken")
        broken.parent.mkdir(parents=True)
        broken.write_text("{ not json")
        locked = get_manifest_path(project, "locked")
        locked.parent.mkdir(parents=True)
        locked.write_text("{}")
        locked.chmod(0o000)
        mismatch_state = create_session_state("other-name", worktree_path=str(project))
        mismatch = get_manifest_path(project, "mismatch")
        mismatch.parent.mkdir(parents=True)
        mismatch.write_text(json.dumps(session_state_to_dict(mismatch_state)))

        try:
            clean_category = _detect_corrupt_state({project})
            report = scan_repairable_orphans(project)
        finally:
            locked.chmod(0o644)

        assert sorted(clean_category.items) == sorted([str(broken), str(mismatch)])
        by_name = {r.name: r.classification for r in report.records}
        assert by_name == {
            "fixable": "repairable",
            "broken": "corrupt",
            "mismatch": "corrupt",
            "locked": "unreadable",
        }

    def test_idless_codex_orphan_replaced_between_scan_and_apply(self, project: Path) -> None:
        """Acceptance D6 fixture: a manifest with neither conversation id can only
        be identified by content hash; a replacement between scan and apply is
        refused and publishes nothing."""
        state = create_session_state("codex-idless", worktree_path=str(project), runtime="codex")
        SessionStore(str(project), "codex-idless").write(state)
        records = self._scan(project).records
        assert records[0].classification == "repairable"
        assert records[0].claude_session_id is None
        assert records[0].codex_thread_id is None

        replacement = create_session_state(
            "codex-idless", worktree_path=str(project), worktree_branch="replaced", runtime="codex"
        )
        SessionStore(str(project), "codex-idless").write(replacement)

        result = repair_orphans(project, records)

        assert result.repaired == ()
        assert len(result.refused) == 1
        assert "changed since it was scanned" in result.refused[0].reason
        assert make_scoped_key("codex-idless", str(project)) not in IndexStore().read().sessions

    def test_changed_manifest_compensates_row(self, project: Path) -> None:
        """D6 backstop: a stale-hash callback unwinds the row the txn just wrote."""
        state = seed_orphan(project, "orphan")
        store = SessionStore(str(project), "orphan")
        stale = hashlib.sha256(b"not the manifest bytes").hexdigest()

        with pytest.raises(ManifestChangedError):
            IndexStore().create_session_txn(
                state,
                str(project),
                checkout_root=str(project),
                forge_root=str(project),
                relative_path=".",
                require_uuid_unbound=True,
                write_manifest=lambda: store.update_if_unchanged(stale, timeout_s=CLI_LOCK_TIMEOUT_S),
            )

        assert make_scoped_key("orphan", str(project)) not in IndexStore().read().sessions
