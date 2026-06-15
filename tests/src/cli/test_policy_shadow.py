"""Tests for ``forge policy shadow`` (show + group; the hidden run worker is covered
by ``tests/src/policy/semantic/test_shadow_runner.py``).

The command lazily imports ``resolve_session_identifier`` from
``forge.core.ops.session_context``, so the resolver is patched at its source.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from forge.cli.main import main


def _patch_resolver(monkeypatch, name: str = "planner", forge_root: str | None = None) -> None:
    monkeypatch.setattr(
        "forge.core.ops.session_context.resolve_session_identifier",
        lambda _s=None: (name, forge_root),
    )


def _write_done(forge_root, cand_hash: str, *, status: str, session: str = "planner", **extra) -> None:
    d = Path(forge_root) / ".forge" / "artifacts" / session / "shadow"
    d.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "captured_at": "2026-06-10T12:00:00Z",
        "checked_at": "2026-06-10T12:05:00Z",
        "tool_name": "Write",
        "target_path": "src/foo.py",
        "status": status,
    }
    record.update(extra)
    (d / f"{cand_hash}.done").write_text(json.dumps(record))


def test_group_help_lists_show_hides_run() -> None:
    result = CliRunner().invoke(main, ["policy", "shadow", "--help"])
    assert result.exit_code == 0
    assert "show" in result.output
    # `run` is the hidden detached worker; it must not appear in user-facing help.
    assert "run " not in result.output.lower().split("commands:")[-1]


def test_show_no_disagreements(monkeypatch, tmp_path) -> None:
    _write_done(tmp_path, "a1", status="agree")  # an agree is not a disagreement
    _patch_resolver(monkeypatch, forge_root=str(tmp_path))
    result = CliRunner().invoke(main, ["policy", "shadow", "show", "planner"])
    assert result.exit_code == 0
    assert "No shadow disagreements" in result.output


def test_show_renders_disagreement_with_citations(monkeypatch, tmp_path) -> None:
    _write_done(
        tmp_path,
        "d1",
        status="disagree",
        frontier_verdict="divergent",
        frontier_confidence=0.9,
        frontier_violations=[
            {"evidence": "wrote to a file outside the plan", "citations": ["Step 2: only touch src/bar.py"]}
        ],
    )
    _patch_resolver(monkeypatch, forge_root=str(tmp_path))
    result = CliRunner().invoke(main, ["policy", "shadow", "show", "planner"])
    assert result.exit_code == 0
    assert "Shadow audit" in result.output
    assert "disagree" in result.output
    assert "src/foo.py" in result.output
    assert "wrote to a file outside the plan" in result.output
    assert "Step 2: only touch src/bar.py" in result.output


def test_show_all_includes_agree(monkeypatch, tmp_path) -> None:
    _write_done(tmp_path, "a1", status="agree")
    _write_done(tmp_path, "d1", status="disagree")
    _patch_resolver(monkeypatch, forge_root=str(tmp_path))

    default = CliRunner().invoke(main, ["policy", "shadow", "show", "planner"])
    assert default.output.count("disagree") >= 1
    assert "agree" not in default.output.replace("disagree", "")  # only the disagreement shown

    full = CliRunner().invoke(main, ["policy", "shadow", "show", "planner", "--all"])
    assert full.exit_code == 0
    assert "2 shown" in full.output


def test_show_json(monkeypatch, tmp_path) -> None:
    _write_done(tmp_path, "d1", status="disagree")
    _write_done(tmp_path, "a1", status="agree")
    _patch_resolver(monkeypatch, forge_root=str(tmp_path))
    result = CliRunner().invoke(main, ["policy", "shadow", "show", "planner", "--all", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["session"] == "planner"
    assert {r["status"] for r in data["records"]} == {"agree", "disagree"}


def test_show_disagree_hides_uncited_violations(monkeypatch, tmp_path) -> None:
    """A disagreement renders only the cited violations that met the block bar; uncited
    ones (which did not drive the block) are review noise and are hidden."""
    _write_done(
        tmp_path,
        "d1",
        status="disagree",
        frontier_verdict="divergent",
        frontier_confidence=0.9,
        frontier_violations=[
            {"evidence": "blocking cited violation", "citations": ["Step 2"]},
            {"evidence": "uncited non-blocking noise", "citations": []},
        ],
    )
    _patch_resolver(monkeypatch, forge_root=str(tmp_path))
    result = CliRunner().invoke(main, ["policy", "shadow", "show", "planner"])
    assert result.exit_code == 0
    assert "blocking cited violation" in result.output
    assert "uncited non-blocking noise" not in result.output


def test_show_all_keeps_uncited_for_inconclusive(monkeypatch, tmp_path) -> None:
    """For a non-disagree (inconclusive), the uncited violations are exactly why it did NOT
    block, so --all keeps them."""
    _write_done(
        tmp_path,
        "i1",
        status="inconclusive",
        frontier_verdict="divergent",
        frontier_violations=[{"evidence": "low-confidence note", "citations": []}],
    )
    _patch_resolver(monkeypatch, forge_root=str(tmp_path))
    result = CliRunner().invoke(main, ["policy", "shadow", "show", "planner", "--all"])
    assert result.exit_code == 0
    assert "low-confidence note" in result.output


def test_show_not_found_exits_1(monkeypatch) -> None:
    from forge.core.ops.session_context import SessionContextError

    def _raise(_s=None):  # noqa: ANN001
        raise SessionContextError("no session 'ghost'")

    monkeypatch.setattr("forge.core.ops.session_context.resolve_session_identifier", _raise)
    result = CliRunner().invoke(main, ["policy", "shadow", "show", "ghost"])
    assert result.exit_code == 1
    assert "forge session list" in result.output
