"""Regression: a full search rebuild must replace unusable index bookkeeping."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.search.index_state import IndexStateStore

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    "state_contents",
    [
        pytest.param("not valid json", id="corrupt"),
        pytest.param('{"schema_version": 999, "indexed_files": {}}', id="newer"),
    ],
)
def test_rebuild_replaces_unusable_index_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state_contents: str,
) -> None:
    project_root = tmp_path / "project"
    (project_root / ".git").mkdir(parents=True)
    transcript = project_root / ".forge" / "artifacts" / "session" / "transcripts" / "session-id.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        '{"requestId":"r1","timestamp":"2026-01-01T00:00:00Z",'
        '"message":{"role":"user","content":[{"type":"text","text":"repair me"}]}}\n',
        encoding="utf-8",
    )
    state_path = project_root / ".forge" / "search-index" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(state_contents, encoding="utf-8")
    monkeypatch.chdir(project_root)

    result = CliRunner().invoke(main, ["search", "rebuild-index"])

    assert result.exit_code == 0, result.output
    rebuilt = IndexStateStore(forge_root=project_root).read()
    assert set(rebuilt.indexed_files) == {str(transcript)}
