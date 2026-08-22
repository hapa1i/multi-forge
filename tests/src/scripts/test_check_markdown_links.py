"""Tests for repository-local Markdown path and fragment validation."""

import importlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

mod = importlib.import_module("check-markdown-links")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_accepts_relative_path_and_generated_fragment(tmp_path):
    target = _write(tmp_path / "docs" / "target.md", "# Target\n\n## Repeated\n\n## Repeated\n")
    source = _write(tmp_path / "README.md", "[second](docs/target.md#repeated-1)\n")

    assert mod.markdown_anchors(target) == {"target", "repeated", "repeated-1"}
    assert mod.audit_paths(tmp_path, [source]) == []


def test_reports_missing_path_and_fragment(tmp_path):
    _write(tmp_path / "target.md", "# Present\n")
    source = _write(tmp_path / "source.md", "[missing](absent.md)\n[anchor](target.md#absent)\n")

    failures = mod.audit_paths(tmp_path, [source])

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

    assert mod.audit_paths(tmp_path, [source]) == []


def test_reports_missing_self_fragment(tmp_path):
    source = _write(tmp_path / "source.md", "# Present\n[missing](#absent)\n")

    failures = mod.audit_paths(tmp_path, [source])

    assert len(failures) == 1
    assert failures[0].reason == "Markdown fragment does not exist"


def test_rejects_repository_escape(tmp_path):
    source = _write(tmp_path / "docs" / "source.md", "[escape](../../outside.md)\n")

    failures = mod.audit_paths(tmp_path, [source])

    assert len(failures) == 1
    assert failures[0].reason == "target escapes repository"


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
