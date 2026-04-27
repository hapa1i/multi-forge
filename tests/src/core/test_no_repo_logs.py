"""Regression guard: prevent repo-local log path usage.

We previously had bugs where code looked for logs under the source tree
(e.g. ``Path(__file__).parent.parent / 'logs'``), which caused runtime logs to
accumulate under ``src/forge/logs/`` instead of the canonical ``$FORGE_HOME/logs``.

This test fails if those patterns reappear.
"""

from __future__ import annotations

from pathlib import Path


def test_no_repo_local_logs_paths() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    src_root = repo_root / "src" / "forge"
    assert src_root.is_dir(), f"Missing src/forge at {src_root}"

    offenders: list[str] = []

    for path in src_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")

        if 'parent.parent / "logs"' in text:
            offenders.append(f'{path}: contains parent.parent / "logs"')

        if "src/forge/logs" in text:
            offenders.append(f"{path}: contains src/forge/logs")

    assert not offenders, "Repo-local logs path usage found:\n" + "\n".join(offenders)
