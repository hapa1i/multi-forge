"""Regression coverage for the repository's never-skip test policy."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

_RUNTIME_SKIP_SYMBOLS = {
    "pytest.importorskip",
    "pytest.mark.skip",
    "pytest.mark.skipif",
    "pytest.skip",
    "unittest.skip",
    "unittest.skipIf",
    "unittest.skipUnless",
}


def _qualified_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        if parent is not None:
            return f"{parent}.{node.attr}"
    return None


def _runtime_skip_locations(path: Path, repo_root: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    locations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Attribute, ast.Name)):
            continue
        name = _qualified_name(node)
        if name in _RUNTIME_SKIP_SYMBOLS:
            locations.append((node.lineno, name))

    display_path = path.relative_to(repo_root)
    return [f"{display_path}:{line}: {name}" for line, name in sorted(locations)]


def test_test_suite_contains_no_runtime_skip_constructs() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    violations = [
        location
        for path in sorted((repo_root / "tests").rglob("*.py"))
        for location in _runtime_skip_locations(path, repo_root)
    ]

    assert violations == [], "runtime test skips violate the Test Maintenance Policy:\n" + "\n".join(violations)
