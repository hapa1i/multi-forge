"""Unit tests for project-scoped memory scanner functions."""

from __future__ import annotations

from forge.session.passport import synthesize_passport, write_passport
from forge.session.project_memory import (
    check_shadow_path_collision_in_roots,
    is_under_scan_roots,
    scan_passported_docs,
    scan_shadow_passports,
    scan_stale_passports,
)

# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def _write_doc(tmp_path, rel, *, strategy="generic", writers="all-sessions", update_mode="direct", shadow_path=None):
    """Write a markdown file with a valid forge_memory passport."""
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Body\n", encoding="utf-8")
    passport = synthesize_passport(strategy=strategy, update_mode=update_mode, shadow_path=shadow_path, writers=writers)
    write_passport(path, passport)
    return path


def _write_plain(tmp_path, rel) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# No passport\n", encoding="utf-8")


def test_scan_finds_passported_doc(tmp_path):
    _write_doc(tmp_path, "docs/changelog.md", strategy="changelog")
    docs = scan_passported_docs(tmp_path, ["docs/"], "any-session")
    assert [d.path for d in docs] == ["docs/changelog.md"]
    assert docs[0].strategy == "changelog"


def test_scan_skips_no_passport(tmp_path):
    _write_plain(tmp_path, "docs/notes.md")
    assert scan_passported_docs(tmp_path, ["docs/"], "any-session") == []


def test_scan_always_includes_forge_memory(tmp_path):
    _write_doc(tmp_path, ".forge/memory/state.md", strategy="project-state")
    # roots does NOT mention .forge/memory; the scanner unions it in.
    docs = scan_passported_docs(tmp_path, ["docs/"], "any-session")
    assert ".forge/memory/state.md" in [d.path for d in docs]


def test_scan_respects_roots(tmp_path):
    _write_doc(tmp_path, "docs/in.md")
    _write_doc(tmp_path, "other/out.md")
    paths = [d.path for d in scan_passported_docs(tmp_path, ["docs/"], "any-session")]
    assert "docs/in.md" in paths
    assert "other/out.md" not in paths


def test_scan_excludes_dotgit(tmp_path):
    _write_doc(tmp_path, "docs/good.md")
    _write_doc(tmp_path, ".git/bad.md")
    _write_doc(tmp_path, "node_modules/pkg/bad.md")
    paths = [d.path for d in scan_passported_docs(tmp_path, ["."], "any-session")]
    assert "docs/good.md" in paths
    assert ".git/bad.md" not in paths
    assert "node_modules/pkg/bad.md" not in paths


def test_scan_shadow_mode(tmp_path):
    _write_doc(
        tmp_path,
        "docs/official.md",
        strategy="generic",
        update_mode="shadow-only",
        shadow_path=".forge/memory/shadow_official.md",
    )
    docs = scan_passported_docs(tmp_path, ["docs/"], "any-session")
    assert len(docs) == 1
    assert docs[0].path == ".forge/memory/shadow_official.md"
    assert docs[0].shadows == "docs/official.md"
    assert docs[0].strategy == "generic"


def test_scan_shadow_materialized(tmp_path):
    _write_doc(
        tmp_path,
        "docs/official.md",
        strategy="generic",
        update_mode="shadow-only",
        shadow_path=".forge/memory/shadow_official.md",
    )
    scan_passported_docs(tmp_path, ["docs/"], "any-session")
    assert (tmp_path / ".forge/memory/shadow_official.md").is_file()


def test_scan_shadow_no_double_count(tmp_path):
    # Official has a shadow-only passport; the materialized shadow has no
    # passport, so it must not produce a second DesignatedDoc.
    _write_doc(
        tmp_path,
        "docs/official.md",
        strategy="generic",
        update_mode="shadow-only",
        shadow_path=".forge/memory/shadow_official.md",
    )
    # Pre-materialize the empty shadow so it is in the candidate set this run.
    (tmp_path / ".forge/memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".forge/memory/shadow_official.md").write_text("", encoding="utf-8")
    docs = scan_passported_docs(tmp_path, ["docs/"], "any-session")
    assert len(docs) == 1
    assert docs[0].shadows == "docs/official.md"


def test_scan_writer_filtering(tmp_path):
    _write_doc(tmp_path, "docs/mine.md", writers="all-sessions")
    _write_doc(tmp_path, "docs/theirs.md", writers="other-session")
    paths = [d.path for d in scan_passported_docs(tmp_path, ["docs/"], "my-session")]
    assert "docs/mine.md" in paths
    assert "docs/theirs.md" not in paths


def test_scan_malformed_passport_skips(tmp_path):
    _write_doc(tmp_path, "docs/good.md")
    bad = tmp_path / "docs/bad.md"
    bad.write_text("---\nforge_memory:\n  version: not-an-int\n  intent: x\n---\n# Body\n", encoding="utf-8")
    paths = [d.path for d in scan_passported_docs(tmp_path, ["docs/"], "any-session")]
    assert "docs/good.md" in paths
    assert "docs/bad.md" not in paths


def test_scan_deterministic_order(tmp_path):
    for name in ("c", "a", "b"):
        _write_doc(tmp_path, f"docs/{name}.md")
    paths = [d.path for d in scan_passported_docs(tmp_path, ["docs/"], "any-session")]
    assert paths == sorted(paths)
    assert paths == ["docs/a.md", "docs/b.md", "docs/c.md"]


def test_scan_root_containment(tmp_path):
    _write_doc(tmp_path, "docs/in.md")
    # Absolute and parent-escaping roots are rejected (logged, skipped), not fatal.
    paths = [d.path for d in scan_passported_docs(tmp_path, ["/etc", "../escape", "docs/"], "any-session")]
    assert paths == ["docs/in.md"]


def test_scan_paths_forge_root_relative(tmp_path):
    _write_doc(tmp_path, "docs/direct.md")
    _write_doc(
        tmp_path,
        "docs/shadowed.md",
        strategy="generic",
        update_mode="shadow-only",
        shadow_path=".forge/memory/shadow_shadowed.md",
    )
    for d in scan_passported_docs(tmp_path, ["docs/"], "any-session"):
        assert not d.path.startswith("/")
        if d.shadows is not None:
            assert not d.shadows.startswith("/")


def test_scan_cap_after_filtering(tmp_path):
    # Plain files sort BEFORE passported ones; they must not consume the cap.
    for i in range(5):
        _write_plain(tmp_path, f"docs/a_plain_{i:02d}.md")
    for i in range(55):
        _write_doc(tmp_path, f"docs/z_pass_{i:02d}.md")
    docs = scan_passported_docs(tmp_path, ["docs/"], "any-session")
    assert len(docs) == 50  # cap honored
    assert all(d.path.startswith("docs/z_pass_") for d in docs)  # plain files filtered out


def test_scan_root_rejects_dotdot_component(tmp_path):
    # `docs/..` resolves back inside forge_root but must be rejected so it
    # cannot silently scan the whole repo. A real `docs/` root still works.
    _write_doc(tmp_path, "docs/in.md")
    _write_doc(tmp_path, "top.md")  # repo root; only reachable via a whole-repo scan
    paths = [d.path for d in scan_passported_docs(tmp_path, ["docs/..", "docs/"], "any-session")]
    assert "docs/in.md" in paths
    assert "top.md" not in paths


def test_scan_unsafe_shadow_path_skipped(tmp_path):
    # Hand-authored shadow-only passports with absolute/escaping shadow_path
    # must be skipped, not emitted with an out-of-tree DesignatedDoc.
    _write_doc(
        tmp_path, "docs/escaping.md", strategy="generic", update_mode="shadow-only", shadow_path="../../escape.md"
    )
    _write_doc(tmp_path, "docs/absolute.md", strategy="generic", update_mode="shadow-only", shadow_path="/tmp/x.md")
    assert scan_passported_docs(tmp_path, ["docs/"], "any-session") == []


# ---------------------------------------------------------------------------
# is_under_scan_roots
# ---------------------------------------------------------------------------


def test_is_under_scan_roots_in_root(tmp_path):
    assert is_under_scan_roots("docs/x.md", tmp_path, ("docs/",)) is True


def test_is_under_scan_roots_always_includes_memory_dir(tmp_path):
    # .forge/memory/ is unioned in even when roots is narrower.
    assert is_under_scan_roots(".forge/memory/s.md", tmp_path, ("docs/",)) is True


def test_is_under_scan_roots_sibling_false(tmp_path):
    # Real containment, not string prefix: docs-extra is NOT under docs/.
    assert is_under_scan_roots("docs-extra/x.md", tmp_path, ("docs/",)) is False


def test_is_under_scan_roots_parent_escape_false(tmp_path):
    assert is_under_scan_roots("../outside.md", tmp_path, ("docs/",)) is False


def test_is_under_scan_roots_absolute_false(tmp_path):
    assert is_under_scan_roots("/etc/passwd", tmp_path, ("docs/",)) is False


def test_is_under_scan_roots_dot_root(tmp_path):
    # An explicit "." root contains everything.
    assert is_under_scan_roots("anything/x.md", tmp_path, (".",)) is True


def test_is_under_scan_roots_skips_unsafe_root(tmp_path):
    # A '..' root resolves to the parent and would falsely "contain" in-repo docs;
    # it must be skipped (matching scan_passported_docs, which rejects it), so an
    # in-docs path is NOT reported as under roots when '../' is the only doc root.
    assert is_under_scan_roots("docs/x.md", tmp_path, ("../",)) is False


# ---------------------------------------------------------------------------
# scan_shadow_passports
# ---------------------------------------------------------------------------


def test_scan_shadow_passports_yields_shadow_only(tmp_path):
    _write_doc(
        tmp_path,
        "docs/official.md",
        strategy="generic",
        update_mode="shadow-only",
        shadow_path=".forge/memory/shadow_official.md",
    )
    assert scan_shadow_passports(tmp_path, ["docs/"]) == [
        ("docs/official.md", ".forge/memory/shadow_official.md", "generic")
    ]


def test_scan_shadow_passports_ignores_direct(tmp_path):
    _write_doc(tmp_path, "docs/direct.md", strategy="changelog")  # direct mode
    assert scan_shadow_passports(tmp_path, ["docs/"]) == []


def test_scan_shadow_passports_unfiltered_by_writer(tmp_path):
    # Unlike scan_passported_docs, a writer restriction does NOT exclude it.
    _write_doc(
        tmp_path,
        "docs/restricted.md",
        strategy="generic",
        update_mode="shadow-only",
        shadow_path=".forge/memory/shadow_restricted.md",
        writers="other-session",
    )
    assert [r[0] for r in scan_shadow_passports(tmp_path, ["docs/"])] == ["docs/restricted.md"]


def test_scan_shadow_passports_does_not_materialize(tmp_path):
    _write_doc(
        tmp_path,
        "docs/official.md",
        strategy="generic",
        update_mode="shadow-only",
        shadow_path=".forge/memory/shadow_official.md",
    )
    scan_shadow_passports(tmp_path, ["docs/"])
    # Read-only inspection must NOT create the shadow file.
    assert not (tmp_path / ".forge/memory/shadow_official.md").exists()


def test_scan_shadow_passports_skips_malformed(tmp_path):
    _write_doc(
        tmp_path,
        "docs/good.md",
        strategy="generic",
        update_mode="shadow-only",
        shadow_path=".forge/memory/shadow_good.md",
    )
    (tmp_path / "docs/bad.md").write_text("---\nforge_memory:\n  version: not-an-int\n---\n# Body\n", encoding="utf-8")
    assert [r[0] for r in scan_shadow_passports(tmp_path, ["docs/"])] == ["docs/good.md"]


# ---------------------------------------------------------------------------
# check_shadow_path_collision_in_roots
# ---------------------------------------------------------------------------


def test_collision_detected_for_different_official(tmp_path):
    _write_doc(
        tmp_path,
        "docs/a.md",
        strategy="generic",
        update_mode="shadow-only",
        shadow_path=".forge/memory/shared.md",
    )
    msg = check_shadow_path_collision_in_roots(".forge/memory/shared.md", "docs/b.md", tmp_path, ("docs/",))
    assert msg is not None
    assert "docs/a.md" in msg


def test_collision_none_for_same_official(tmp_path):
    _write_doc(
        tmp_path,
        "docs/a.md",
        strategy="generic",
        update_mode="shadow-only",
        shadow_path=".forge/memory/shared.md",
    )
    # Re-authoring the same official doc is not a collision (upsert).
    assert check_shadow_path_collision_in_roots(".forge/memory/shared.md", "docs/a.md", tmp_path, ("docs/",)) is None


def test_collision_none_when_unused(tmp_path):
    _write_doc(
        tmp_path,
        "docs/a.md",
        strategy="generic",
        update_mode="shadow-only",
        shadow_path=".forge/memory/a.md",
    )
    assert check_shadow_path_collision_in_roots(".forge/memory/other.md", "docs/b.md", tmp_path, ("docs/",)) is None


def test_collision_skips_malformed_unrelated(tmp_path):
    # A malformed unrelated passport must not raise; the check returns None.
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs/bad.md").write_text("---\nforge_memory:\n  version: not-an-int\n---\n# Body\n", encoding="utf-8")
    assert check_shadow_path_collision_in_roots(".forge/memory/x.md", "docs/b.md", tmp_path, ("docs/",)) is None


def test_scan_stale_finds_removed_strategies(tmp_path):
    """scan_stale_passports detects docs with removed strategies."""
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs/debug.md").write_text(
        "---\nforge_memory:\n  version: 1\n  intent: debug notes\n"
        "  update:\n    strategy: debugging\n---\n# Debug\n",
        encoding="utf-8",
    )
    _write_doc(tmp_path, "docs/changelog.md", strategy="changelog")
    stale = scan_stale_passports(tmp_path, ["docs/"])
    assert len(stale) == 1
    rel, strategy, hint = stale[0]
    assert rel == "docs/debug.md"
    assert strategy == "debugging"
    assert "generic" in hint


def test_scan_stale_ignores_valid_strategies(tmp_path):
    """scan_stale_passports returns empty for valid strategies."""
    _write_doc(tmp_path, "docs/changelog.md", strategy="changelog")
    _write_doc(tmp_path, "docs/notes.md", strategy="generic")
    stale = scan_stale_passports(tmp_path, ["docs/"])
    assert stale == []
