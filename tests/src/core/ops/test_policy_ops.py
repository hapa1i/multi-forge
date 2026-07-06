import ast
from pathlib import Path


def test_policy_ops_is_ui_free() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    tree = ast.parse((repo_root / "src/forge/core/ops/policy.py").read_text(encoding="utf-8"))
    forbidden_imports = {"click", "rich", "sys"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported = {alias.name.split(".")[0] for alias in node.names}
            assert imported.isdisjoint(forbidden_imports)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module.split(".")[0] not in forbidden_imports
        elif isinstance(node, ast.Call):
            func = node.func
            assert not (isinstance(func, ast.Name) and func.id == "print")
            assert not (
                isinstance(func, ast.Attribute)
                and func.attr == "exit"
                and isinstance(func.value, ast.Name)
                and func.value.id == "sys"
            )
