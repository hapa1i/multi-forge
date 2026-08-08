"""Regression for inconsistent search corruption streams and exit status (D017)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.search.bm25_store import BM25IndexStore
from forge.search.store import SearchDocumentStore

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    ("command", "as_json"),
    [
        (("search", "query", "anything"), False),
        (("search", "query", "anything"), True),
        (("search", "status"), False),
        (("search", "status"), True),
    ],
    ids=["query-human", "query-json", "status-human", "status-json"],
)
def test_search_corruption_is_nonzero_stderr_in_every_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: tuple[str, ...],
    as_json: bool,
) -> None:
    project_root = tmp_path / "project"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)

    # Status needs a document-store marker before it inspects BM25. Query reads
    # BM25 first, so this one fixture reaches the corrupt boundary in both leaves.
    SearchDocumentStore(forge_root=project_root).write([])
    BM25IndexStore(forge_root=project_root).store_path.write_text("not valid json {{{", encoding="utf-8")

    args = [*command]
    if as_json:
        args.append("--json")
    result = CliRunner().invoke(main, args)

    assert result.exit_code == 1
    assert result.stdout == ""
    if as_json:
        payload = json.loads(result.stderr)
        assert "corrupted" in str(payload["error"]).lower()
        assert "rebuild-index" in str(payload["hint"])
    else:
        assert "Search index corrupted or outdated" in result.stderr
        assert "rebuild-index" in result.stderr
