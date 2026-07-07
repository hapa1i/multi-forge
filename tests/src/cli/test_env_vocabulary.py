"""Guards for Forge env-var vocabulary in user-facing surfaces."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

ENV_CLASSES = {
    "FORGE_HOME": "public",
    "FORGE_PROFILE": "public",
    "FORGE_DEBUG": "public-diagnostic",
    "FORGE_STATUS_TRUNCATE": "public-diagnostic",
    "FORGE_CODEX_PROXY_TOKEN": "internal-wiring",
    "FORGE_COMMAND": "internal-wiring",
    "FORGE_DEFAULT_PROXY_BASE_URL": "internal-wiring",
    "FORGE_DEFAULT_PROXY_TEMPLATE": "internal-wiring",
    "FORGE_DEPTH": "internal-wiring",
    "FORGE_FORGE_ROOT": "internal-wiring",
    "FORGE_FORK_NAME": "internal-wiring",
    "FORGE_LAUNCH_MODE": "internal-wiring",
    "FORGE_OMIT_INTERACTIVE_KEY": "internal-wiring",
    "FORGE_PARENT_RUN_ID": "internal-wiring",
    "FORGE_PARENT_SESSION": "internal-wiring",
    "FORGE_PROXY_ID": "internal-wiring",
    "FORGE_PROXY_WIRE_SHAPE": "internal-wiring",
    "FORGE_ROOT_RUN_ID": "internal-wiring",
    "FORGE_RUN_ID": "internal-wiring",
    "FORGE_SESSION": "internal-wiring",
    "FORGE_SIDECAR": "internal-wiring",
    "FORGE_SUBPROCESS_BASE_URL": "internal-wiring",
    "FORGE_SUBPROCESS_PROXY": "internal-wiring",
    "FORGE_SUBPROCESS_PROXY_ID": "internal-wiring",
    "FORGE_SUBPROCESS_TEMPLATE": "internal-wiring",
    "FORGE_TEMPLATE": "internal-wiring",
    "FORGE_MANUAL_TEST_SYSTEM_PROMPT": "test-qa",
    "FORGE_QA_ANTHROPIC_PROXY": "test-qa",
    "FORGE_QA_ANTHROPIC_TEMPLATE": "test-qa",
    "FORGE_QA_DEEPSEEK_TEMPLATE": "test-qa",
    "FORGE_QA_GEMINI_PROXY": "test-qa",
    "FORGE_QA_GEMINI_TEMPLATE": "test-qa",
    "FORGE_QA_MINIMAX_TEMPLATE": "test-qa",
    "FORGE_QA_OPENAI_PROXY": "test-qa",
    "FORGE_QA_OPENAI_TEMPLATE": "test-qa",
    "FORGE_QA_PROVIDER_PROFILE": "test-qa",
    "FORGE_QA_WORKFLOW_MODEL_A": "test-qa",
    "FORGE_QA_WORKFLOW_MODEL_B": "test-qa",
    "FORGE_QA_WORKFLOW_MODELS": "test-qa",
    "FORGE_TEST_REPO": "test-qa",
}

INTERNAL_ENV_NAMES = frozenset(name for name, class_ in ENV_CLASSES.items() if class_ == "internal-wiring")
DOC_DIAGNOSTIC_START = "<!-- forge-env-vocab: diagnostic:start -->"
DOC_DIAGNOSTIC_END = "<!-- forge-env-vocab: diagnostic:end -->"
ENV_NAME_RE = re.compile(r"(?<![A-Z0-9_])FORGE_[A-Z0-9_]+(?![A-Z0-9_])")
ENV_ASSIGNMENT_RE = re.compile(r"(?<![A-Z0-9_])(FORGE_[A-Z0-9_]+)=")
TABLE_CLASS_SLUGS = {
    "Public": "public",
    "Public diagnostic": "public-diagnostic",
    "Internal wiring": "internal-wiring",
    "Test/QA harness": "test-qa",
}


@dataclass(frozen=True)
class EnvVocabularyOffender:
    path: str
    line: int
    sink: str
    name: str
    text: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _module_constants(tree: ast.Module) -> dict[str, str]:
    constants: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                constants[target.id] = node.value.value
    return constants


def _docstring_nodes(tree: ast.Module) -> set[ast.Constant]:
    docstrings: set[ast.Constant] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            docstrings.add(first.value)
    return docstrings


def _strings_from_node(node: ast.AST, constants: dict[str, str]) -> list[tuple[int, str]]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [(node.lineno, node.value)]
    if isinstance(node, ast.Name) and node.id in constants:
        return [(node.lineno, constants[node.id])]

    strings: list[tuple[int, str]] = []
    for child in ast.iter_child_nodes(node):
        strings.extend(_strings_from_node(child, constants))
    return strings


def _decorator_is_click_command(node: ast.AST) -> bool:
    func = node.func if isinstance(node, ast.Call) else node
    return isinstance(func, ast.Attribute) and func.attr in {"command", "group"}


def _click_imported_sink_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module != "click":
            continue
        for alias in node.names:
            if alias.name in {"echo", "ClickException"}:
                names.add(alias.asname or alias.name)
    return names


def _scan_text_for_internal_names(
    rel_path: str,
    line: int,
    sink: str,
    text: str,
) -> list[EnvVocabularyOffender]:
    return [
        EnvVocabularyOffender(rel_path, line, sink, name, text.strip())
        for name in sorted(set(ENV_NAME_RE.findall(text)) & INTERNAL_ENV_NAMES)
    ]


def scan_python_user_visible_sinks(paths: list[Path], repo_root: Path) -> list[EnvVocabularyOffender]:
    offenders: list[EnvVocabularyOffender] = []
    sink_calls = {
        "click.echo",
        "click.ClickException",
        "print_error",
        "print_tip",
        "print_error_with_tip",
        "handle_session_error",
        "console.print",
        "err_console.print",
    }

    for path in sorted(paths):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        constants = _module_constants(tree)
        imported_click_sinks = _click_imported_sink_names(tree)
        rel_path = path.relative_to(repo_root).as_posix() if path.is_relative_to(repo_root) else path.name

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and any(_decorator_is_click_command(d) for d in node.decorator_list):
                docstring = ast.get_docstring(node, clean=False)
                if docstring:
                    offenders.extend(
                        _scan_text_for_internal_names(
                            rel_path,
                            node.body[0].lineno,
                            "click command docstring",
                            docstring,
                        )
                    )

            if isinstance(node, ast.Call):
                call_name = _qualified_name(node.func)
                if call_name in sink_calls or call_name in imported_click_sinks:
                    for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                        for line, text in _strings_from_node(arg, constants):
                            offenders.extend(_scan_text_for_internal_names(rel_path, line, call_name, text))

                for keyword in node.keywords:
                    if keyword.arg in {"help", "short_help", "epilog", "reason"}:
                        for line, text in _strings_from_node(keyword.value, constants):
                            offenders.extend(_scan_text_for_internal_names(rel_path, line, keyword.arg, text))

            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values, strict=False):
                    if isinstance(key, ast.Constant) and key.value == "reason":
                        for line, text in _strings_from_node(value, constants):
                            offenders.extend(_scan_text_for_internal_names(rel_path, line, "% reason payload", text))

            if isinstance(node, ast.Raise) and node.exc is not None:
                for line, text in _strings_from_node(node.exc, constants):
                    offenders.extend(_scan_text_for_internal_names(rel_path, line, "raise", text))

    return offenders


def _resolve_env_name(node: ast.AST, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value if ENV_NAME_RE.fullmatch(node.value) else None
    if isinstance(node, ast.Name):
        value = constants.get(node.id)
        if value and ENV_NAME_RE.fullmatch(value):
            return value
    return None


def _joined_static_text(node: ast.JoinedStr) -> str:
    return "".join(
        value.value for value in node.values if isinstance(value, ast.Constant) and isinstance(value.value, str)
    )


def _is_env_constant_target(name: str) -> bool:
    return name.startswith("ENV_") or name.endswith("_VAR") or name.endswith("_VARS")


def _live_product_env_names(root: Path) -> set[str]:
    names: set[str] = set()
    for path in sorted((root / "src" / "forge").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        constants = _module_constants(tree)
        docstrings = _docstring_nodes(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node not in docstrings:
                names.update(ENV_ASSIGNMENT_RE.findall(node.value))

            if isinstance(node, ast.JoinedStr):
                names.update(ENV_ASSIGNMENT_RE.findall(_joined_static_text(node)))

            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and _is_env_constant_target(target.id):
                        if name := _resolve_env_name(node.value, constants):
                            names.add(name)
                    if isinstance(target, ast.Subscript):
                        if name := _resolve_env_name(target.slice, constants):
                            names.add(name)

                if isinstance(node.value, ast.Dict):
                    for key in node.value.keys:
                        if key is None:
                            continue
                        if name := _resolve_env_name(key, constants):
                            names.add(name)

            if isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.value and _is_env_constant_target(node.target.id):
                    if name := _resolve_env_name(node.value, constants):
                        names.add(name)
                if isinstance(node.target, ast.Subscript):
                    if name := _resolve_env_name(node.target.slice, constants):
                        names.add(name)

            if isinstance(node, ast.Subscript):
                if _qualified_name(node.value) == "os.environ":
                    if name := _resolve_env_name(node.slice, constants):
                        names.add(name)

            if isinstance(node, ast.Call):
                call_name = _qualified_name(node.func)
                if call_name in {
                    "os.getenv",
                    "os.environ.get",
                    "os.environ.pop",
                    "os.environ.setdefault",
                    "os.environ.__getitem__",
                }:
                    if node.args and (name := _resolve_env_name(node.args[0], constants)):
                        names.add(name)
                    continue

                if isinstance(node.func, ast.Attribute) and node.func.attr in {"get", "pop", "setdefault"}:
                    if _qualified_name(node.func.value) == "os.environ" and node.args:
                        if name := _resolve_env_name(node.args[0], constants):
                            names.add(name)

    return names


def _doc_paths(root: Path) -> list[Path]:
    return sorted((root / "docs" / "end-user").rglob("*.md")) + [root / "docs" / "cli_reference.md"]


def scan_docs_for_internal_names(paths: list[Path], repo_root: Path) -> list[EnvVocabularyOffender]:
    offenders: list[EnvVocabularyOffender] = []
    marker_errors: list[str] = []

    for path in sorted(paths):
        rel_path = path.relative_to(repo_root).as_posix() if path.is_relative_to(repo_root) else path.name
        in_diagnostic = False
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if DOC_DIAGNOSTIC_START in line:
                if in_diagnostic:
                    marker_errors.append(f"{rel_path}:{line_no}: nested diagnostic marker")
                in_diagnostic = True
                continue
            if DOC_DIAGNOSTIC_END in line:
                if not in_diagnostic:
                    marker_errors.append(f"{rel_path}:{line_no}: unopened diagnostic marker")
                in_diagnostic = False
                continue
            if in_diagnostic:
                continue
            offenders.extend(_scan_text_for_internal_names(rel_path, line_no, "docs", line))
        if in_diagnostic:
            marker_errors.append(f"{rel_path}: unclosed diagnostic marker")

    assert not marker_errors, f"bad forge-env-vocab diagnostic markers: {marker_errors}"
    return offenders


def _appendix_table() -> dict[str, str]:
    appendix = (_repo_root() / "docs" / "design_appendix.md").read_text(encoding="utf-8")
    section = appendix.split("### A.7b Forge env-var vocabulary", maxsplit=1)[1].split("\n### ", maxsplit=1)[0]

    table: dict[str, str] = {}
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        match = re.fullmatch(r"`(FORGE_[A-Z0-9_]+)`", cells[0])
        if not match:
            continue
        table[match.group(1)] = TABLE_CLASS_SLUGS[cells[1]]
    return table


def test_env_vocab_mapping_matches_design_appendix_table() -> None:
    assert _appendix_table() == ENV_CLASSES


def test_env_vocab_covers_live_product_env_inventory() -> None:
    live_names = _live_product_env_names(_repo_root())
    assert live_names <= set(ENV_CLASSES), f"classify live FORGE_* env vars: {sorted(live_names - set(ENV_CLASSES))}"


def test_regex_only_forge_tokens_are_not_classified_as_env_vars() -> None:
    table = _appendix_table()
    assert "FORGE_MAX_DEPTH" not in table
    assert "WT_FORGE_LOG_SNAPSHOTS" not in table
    assert "FORGE_REV" not in table


def test_python_guard_flags_user_visible_internal_env_names(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        '''
import click


@click.command()
@click.option("--session", help="Target $FORGE_SESSION")
def cmd():
    """Uses FORGE_SESSION in help."""
    raise RuntimeError("Missing FORGE_SUBPROCESS_PROXY_ID")
''',
        encoding="utf-8",
    )

    offenders = scan_python_user_visible_sinks([sample], tmp_path)
    assert {offender.sink for offender in offenders} == {"help", "click command docstring", "raise"}
    assert {offender.name for offender in offenders} == {"FORGE_SESSION", "FORGE_SUBPROCESS_PROXY_ID"}


def test_python_guard_flags_console_print_and_bare_click_imports(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        """
from click import echo


def cmd(console):
    console.print("Leaked FORGE_SESSION")
    echo("Leaked FORGE_FORK_NAME")
""",
        encoding="utf-8",
    )

    offenders = scan_python_user_visible_sinks([sample], tmp_path)
    assert [(offender.sink, offender.name) for offender in offenders] == [
        ("console.print", "FORGE_SESSION"),
        ("echo", "FORGE_FORK_NAME"),
    ]


def test_python_guard_ignores_env_reads_and_plain_helper_docstrings(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        '''
import os


def helper():
    """Plain helper mentions FORGE_SESSION for implementation notes."""
    os.environ.get("FORGE_SESSION")
    os.getenv("FORGE_PROXY_ID")
''',
        encoding="utf-8",
    )

    assert scan_python_user_visible_sinks([sample], tmp_path) == []


def test_docs_guard_flags_internal_names_except_public_and_paired_diagnostics(tmp_path: Path) -> None:
    concept = tmp_path / "cli_reference.md"
    concept.write_text("Normal flow says use FORGE_SESSION.\n", encoding="utf-8")
    hook = tmp_path / "hook.md"
    hook.write_text(
        "\n".join(
            [
                "Normal hook prose leaks FORGE_SESSION.",
                "FORGE_DEBUG is public diagnostic and allowed.",
                DOC_DIAGNOSTIC_START,
                "Troubleshooting can inspect FORGE_FORK_NAME -> FORGE_SESSION.",
                DOC_DIAGNOSTIC_END,
            ]
        ),
        encoding="utf-8",
    )

    offenders = scan_docs_for_internal_names([concept, hook], tmp_path)
    assert [(offender.path, offender.name) for offender in offenders] == [
        ("cli_reference.md", "FORGE_SESSION"),
        ("hook.md", "FORGE_SESSION"),
    ]


def test_current_python_user_visible_surfaces_do_not_name_internal_env_vars() -> None:
    root = _repo_root()
    paths = sorted((root / "src" / "forge" / "cli").rglob("*.py"))
    paths += sorted((root / "src" / "forge" / "core" / "ops").rglob("*.py"))

    offenders = scan_python_user_visible_sinks(paths, root)
    assert offenders == []


def test_current_user_docs_do_not_name_internal_env_vars_outside_diagnostics() -> None:
    root = _repo_root()
    offenders = scan_docs_for_internal_names(_doc_paths(root), root)
    assert offenders == []
