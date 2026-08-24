"""Tests for repository-local Markdown path and fragment validation."""

import importlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

mod = importlib.import_module("check-markdown-links")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _files(*paths: Path) -> set[Path]:
    return {path.resolve() for path in paths}


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_accepts_relative_path_and_generated_fragment(tmp_path):
    target = _write(tmp_path / "docs" / "target.md", "# Target\n\n## Repeated\n\n## Repeated\n")
    source = _write(tmp_path / "README.md", "[second](docs/target.md#repeated-1)\n")

    assert mod.markdown_anchors(target) == {"target", "repeated", "repeated-1"}
    assert mod.audit_paths(tmp_path, [source], _files(source, target)) == []


def test_reports_missing_path_and_fragment(tmp_path):
    _write(tmp_path / "target.md", "# Present\n")
    source = _write(tmp_path / "source.md", "[missing](absent.md)\n[anchor](target.md#absent)\n")

    failures = mod.audit_paths(tmp_path, [source], _files(source, tmp_path / "target.md"))

    assert [(failure.line, failure.reason) for failure in failures] == [
        (1, "target does not exist"),
        (2, "Markdown fragment does not exist"),
    ]


def test_accepts_remote_links_self_fragments_and_fenced_examples(tmp_path):
    source = _write(
        tmp_path / "source.md",
        "# Same Document\n[remote](https://example.com/missing)\n[local](#same-document)\n"
        "```md\n[example](missing.md)\n```\n",
    )

    assert mod.audit_paths(tmp_path, [source], _files(source)) == []


def test_reports_missing_self_fragment(tmp_path):
    source = _write(tmp_path / "source.md", "# Present\n[missing](#absent)\n")

    failures = mod.audit_paths(tmp_path, [source], _files(source))

    assert len(failures) == 1
    assert failures[0].reason == "Markdown fragment does not exist"


def test_rejects_repository_escape(tmp_path):
    source = _write(tmp_path / "docs" / "source.md", "[escape](../../outside.md)\n")

    failures = mod.audit_paths(tmp_path, [source], _files(source))

    assert len(failures) == 1
    assert failures[0].reason == "target escapes repository"


def test_rejects_existing_target_absent_from_candidate_git_state(tmp_path):
    _git(tmp_path, "init", "-q")
    source = _write(tmp_path / "source.md", "[target](target.md)\n")
    target = _write(tmp_path / "target.md", "# Target\n")
    _git(tmp_path, "add", "source.md")

    candidates = mod.candidate_files(tmp_path)
    failures = mod.audit_paths(tmp_path, [source], candidates)

    assert target.resolve() not in candidates
    assert [failure.reason for failure in failures] == ["target is not in candidate Git state"]


def test_accepts_staged_addition_and_rejects_restored_staged_deletion(tmp_path):
    _git(tmp_path, "init", "-q")
    source = _write(tmp_path / "source.md", "[target](target.md)\n")
    target = _write(tmp_path / "target.md", "# Target\n")
    _git(tmp_path, "add", "source.md", "target.md")

    assert mod.audit_paths(tmp_path, [source], mod.candidate_files(tmp_path)) == []

    _git(tmp_path, "update-index", "--force-remove", "target.md")
    assert target.is_file()
    failures = mod.audit_paths(tmp_path, [source], mod.candidate_files(tmp_path))

    assert [failure.reason for failure in failures] == ["target is not in candidate Git state"]


def test_rejects_staged_deleted_symlink_when_tracked_referent_remains(tmp_path):
    _git(tmp_path, "init", "-q")
    source = _write(tmp_path / "source.md", "[alias](alias.md)\n")
    referent = _write(tmp_path / "target.md", "# Target\n")
    alias = tmp_path / "alias.md"
    alias.symlink_to(referent.name)
    _git(tmp_path, "add", "source.md", "target.md", "alias.md")
    _git(tmp_path, "update-index", "--force-remove", "alias.md")

    candidates = mod.candidate_files(tmp_path)
    failures = mod.audit_paths(tmp_path, [source], candidates)

    assert alias not in candidates
    assert referent in candidates
    assert [failure.reason for failure in failures] == ["target is not in candidate Git state"]


def test_supplied_sources_are_added_to_candidate_markdown_sources(tmp_path):
    _git(tmp_path, "init", "-q")
    tracked = _write(tmp_path / "tracked.md", "# Tracked\n")
    supplied = _write(tmp_path / "supplied.md", "[broken](missing.md)\n")
    _git(tmp_path, "add", "tracked.md")

    candidates = mod.candidate_files(tmp_path)
    sources = mod.markdown_sources(tmp_path, candidates, [Path("supplied.md")])

    assert sources == sorted([tracked.resolve(), supplied.resolve()])
    failures = mod.audit_paths(tmp_path, sources, candidates)
    assert [(failure.source, failure.reason) for failure in failures] == [
        (supplied.resolve(), "target does not exist"),
    ]


def test_supplied_source_through_repository_symlink_uses_canonical_identity(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    source = _write(root / "source.md", "[target](target.md)\n")
    target = _write(root / "target.md", "# Target\n")
    _git(root, "add", "source.md", "target.md")
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)

    candidates = mod.candidate_files(root)
    sources = mod.markdown_sources(root.resolve(), candidates, [alias / "source.md"])

    assert sources == sorted([source.resolve(), target.resolve()])
    assert mod.audit_paths(root.resolve(), sources, candidates) == []


def test_main_prints_absolute_source_when_failure_is_outside_root(tmp_path, monkeypatch, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    foreign = tmp_path / "alias" / "source.md"
    failure = mod.LinkFailure(foreign, 7, "missing.md", "target does not exist")
    monkeypatch.setattr(mod, "parse_args", lambda _argv: SimpleNamespace(paths=[]))
    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=f"{root}\n"),
    )
    monkeypatch.setattr(mod, "candidate_files", lambda _root: set())
    monkeypatch.setattr(mod, "markdown_sources", lambda _root, _candidates, _paths: [])
    monkeypatch.setattr(mod, "audit_paths", lambda _root, _sources, _candidates: [failure])

    assert mod.main([]) == 1

    captured = capsys.readouterr()
    assert f"{foreign}:7: target does not exist: missing.md" in captured.out


def test_rejects_link_through_tracked_symlinked_directory(tmp_path):
    _git(tmp_path, "init", "-q")
    source = _write(tmp_path / "source.md", "[target](linkdir/target.md)\n")
    target = _write(tmp_path / "realdir" / "target.md", "# Target\n")
    linkdir = tmp_path / "linkdir"
    linkdir.symlink_to(target.parent.name, target_is_directory=True)
    _git(tmp_path, "add", "source.md", "realdir/target.md", "linkdir")

    failures = mod.audit_paths(tmp_path, [source], mod.candidate_files(tmp_path))

    assert [failure.reason for failure in failures] == ["target is not in candidate Git state"]


def test_accepts_directory_target_with_candidate_descendant(tmp_path):
    source = _write(tmp_path / "README.md", "[docs](docs/)\n")
    target = _write(tmp_path / "docs" / "guide.md", "# Guide\n")

    assert mod.audit_paths(tmp_path, [source], _files(source, target)) == []


def test_retired_consolidated_design_token_has_no_live_references():
    """The removed path must not survive in source comments that the Markdown audit cannot see."""
    candidates = [
        *REPO_ROOT.glob("src/**/*.py"),
        *REPO_ROOT.glob("tests/**/*.py"),
        *REPO_ROOT.glob("docs/**/*.md"),
    ]
    retired_token = "design_" + "appendix"
    references = [path.relative_to(REPO_ROOT) for path in candidates if retired_token in path.read_text()]
    assert references == []
