"""Repository conformance checks for production source."""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
SRC_FORGE = REPO_ROOT / "src" / "forge"

TYPE_CHECKING_WORKAROUND_PATTERNS = (
    re.compile(r"^\s*from\s+typing\s+import\b.*\bTYPE_CHECKING\b"),
    re.compile(r"^\s*if\s+TYPE_CHECKING\s*:"),
)
TYPE_IGNORE_PATTERN = re.compile(r"#\s*type:\s*ignore(?:\[[^\]]+\])?")


def test_production_source_has_no_type_checking_workarounds() -> None:
    """Production modules should resolve import cycles architecturally."""
    violations: list[str] = []
    for path in sorted(SRC_FORGE.rglob("*.py")):
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if any(pattern.search(line) for pattern in TYPE_CHECKING_WORKAROUND_PATTERNS):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")

    assert violations == []


def test_production_type_ignores_include_reasons() -> None:
    """Production suppressions must state the runtime invariant that makes them safe."""
    violations: list[str] = []
    for path in sorted(SRC_FORGE.rglob("*.py")):
        tokens = tokenize.generate_tokens(io.StringIO(path.read_text()).readline)
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            match = TYPE_IGNORE_PATTERN.search(token.string)
            if match is None:
                continue
            reason = token.string[match.end() :].strip()
            if not reason.startswith("#") or not reason.removeprefix("#").strip():
                violations.append(f"{path.relative_to(REPO_ROOT)}:{token.start[0]}: {token.string}")

    assert violations == []
