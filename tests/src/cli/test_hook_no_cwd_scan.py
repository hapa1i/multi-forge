"""Guard: hooks resolve a session by identity, never by scanning a directory.

design.md section 3.10 makes hook session resolution `FORGE_FORK_NAME` ->
`FORGE_SESSION` -> IndexStore UUID lookup, with no CWD-based directory scan. The
adoption discovery preview (`forge session adopt` with no id) is the first code
that walks a Claude project directory, and it is CLI-only by design: a hook that
picked up the same scan would resolve sessions by filesystem proximity and
silently reattach the wrong conversation.

This is an import-level guard rather than a behavioral one because the failure
mode is a future edit reaching for a convenient helper, not a bug in today's
handlers.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_HOOKS_DIR = Path(__file__).resolve().parents[3] / "src" / "forge" / "cli" / "hooks"

# Names that imply "find a conversation by looking at a directory".
_FORBIDDEN_NAMES = frozenset({"discover_adoptable", "get_project_encoded_dir", "get_claude_projects_dir"})


def _hook_modules() -> list[Path]:
    modules = sorted(p for p in _HOOKS_DIR.rglob("*.py") if p.name != "__init__.py")
    assert modules, f"no hook modules found under {_HOOKS_DIR}"
    return modules


@pytest.mark.parametrize("module_path", _hook_modules(), ids=lambda p: p.name)
def test_hook_module_does_not_import_a_directory_scanner(module_path: Path) -> None:
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name.rsplit(".", 1)[-1] for alias in node.names)

    offenders = sorted(imported & _FORBIDDEN_NAMES)
    assert not offenders, (
        f"{module_path.name} imports {offenders}: hooks must resolve sessions by "
        "identity (design.md 3.10), not by scanning a Claude project directory"
    )
