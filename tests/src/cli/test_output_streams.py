"""Stream-ownership guard: read leaves keep ``--json`` on stdout with clean stderr.

Slice 07 (forge_cli_cleanup): results and every ``--json`` payload go to stdout;
diagnostics go to stderr. Click 8.3 removed ``CliRunner(mix_stderr=...)`` -- the
plain runner already separates ``result.stdout`` / ``result.stderr``.

Covers the leaves that previously split their streams (``proxy audit`` rendered
its human table to stderr) plus the already-compliant telemetry leaves, so a
regression in either direction red-tests here.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import TypeGuard

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.ops.session_context import SessionContextError

# --json success paths that need no seeded data: empty logs still yield valid JSON.
_JSON_STDOUT_LEAVES = [
    ["logs", "show", "--json"],
    ["telemetry", "costs", "show", "--json"],
    ["telemetry", "trace", "list", "--json"],
    ["proxy", "audit", "show", "--json"],
    ["proxy", "audit", "diff", "--json"],
    # Regression: empty registry used to print "No proxies registered." to stdout.
    ["proxy", "metrics", "--json"],
]


@pytest.mark.parametrize("args", _JSON_STDOUT_LEAVES, ids=lambda a: " ".join(a))
def test_json_payload_on_stdout_with_clean_stderr(args: list[str]) -> None:
    """``--json`` emits parseable JSON on stdout and writes nothing to stderr."""
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 0, result.output
    json.loads(result.stdout)  # raises if stdout is not pure JSON
    assert result.stderr == ""


def test_shadows_review_bare_json_keeps_stdout_jq_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bare ``memory shadows review --for X --json`` forwards ``as_json`` (no human/Tip leak).

    Regression (forge_cli_cleanup review): the bare-review path ``ctx.invoke``d
    ``shadows_show`` without ``as_json`` and then ``print_tip``ped to stdout, leaking
    non-JSON under ``--json``. Now it forwards ``as_json`` and gates the tip.
    """
    monkeypatch.setattr("forge.cli.memory._collect_shadow_entries", lambda scope, sf: ([], []))
    result = CliRunner().invoke(main, ["memory", "shadows", "review", "--for", "docs/x.md", "--json"])
    assert result.exit_code == 0, result.output
    assert "Tip:" not in result.stdout
    json.loads(result.stdout)  # raises if non-JSON leaked to stdout


def test_activity_json_on_stdout_when_seeded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Seeded ``telemetry activity --json`` emits JSON on stdout, clean stderr.

    Bare invocation exits 1 (no session resolves in an isolated home), so seed the
    resolver + summary to exercise the success branch (``console.print_json``).
    """
    monkeypatch.setattr(
        "forge.cli.activity.resolve_session_identifier",
        lambda session: ("seeded-session", Path.cwd()),
    )
    monkeypatch.setattr(
        "forge.cli.activity.build_session_activity_summary",
        lambda *a, **k: object(),
    )
    monkeypatch.setattr(
        "forge.cli.activity.activity_summary_to_json",
        lambda summary: {"session": "seeded-session", "operations": []},
    )

    result = CliRunner().invoke(main, ["telemetry", "activity", "seeded-session", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["session"] == "seeded-session"
    assert result.stderr == ""


def test_activity_json_error_on_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    """In-branch ``--json`` failures emit JSON on stderr and leave stdout parse-safe."""
    monkeypatch.setattr(
        "forge.cli.activity.resolve_session_identifier",
        lambda session: (_ for _ in ()).throw(SessionContextError("no session")),
    )

    result = CliRunner().invoke(main, ["telemetry", "activity", "--json"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert json.loads(result.stderr) == {"error": "no session"}


def _seed_audit_logs(monkeypatch: pytest.MonkeyPatch, records: list[dict]) -> None:
    # audit_show/diff import read_audit_logs lazily from the source module, so the
    # patch must target the source attribute, not forge.cli.proxy_audit.
    monkeypatch.setattr("forge.proxy.audit_logger.read_audit_logs", lambda *a, **k: list(records))


def test_audit_show_human_table_on_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The human audit table lands on stdout (Slice 07 flipped the shared console off stderr)."""
    _seed_audit_logs(
        monkeypatch,
        [
            {
                "record_type": "request",
                "ts": "2026-01-01T00:00:00Z",
                "proxy_id": "audit-test",
                "mode": "inspect",
                "system_prompt_hash": "sha256:abcdef0123456789",
                "tool_surface_hash": "sha256:9876543210fedcba",
                "counts": {"num_messages": 2, "num_tools": 1},
            }
        ],
    )
    result = CliRunner().invoke(main, ["proxy", "audit", "show", "--period", "all"])
    assert result.exit_code == 0, result.output
    assert "Audit" in result.stdout
    assert "audit-test" in result.stdout
    assert result.stderr == ""


def test_audit_diff_human_table_on_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The human wire-changes table lands on stdout."""
    _seed_audit_logs(
        monkeypatch,
        [
            {
                "record_type": "drift",
                "ts": "2026-01-01T00:00:00Z",
                "proxy_id": "audit-test",
                "dimension": "system_prompt",
                "previous_hash": "sha256:aaaaaaaaaaaa",
                "current_hash": "sha256:bbbbbbbbbbbb",
            }
        ],
    )
    result = CliRunner().invoke(main, ["proxy", "audit", "diff", "--period", "all"])
    assert result.exit_code == 0, result.output
    assert "Wire changes" in result.stdout
    assert "audit-test" in result.stdout
    assert result.stderr == ""


# --- Failure paths: --json read leaves keep stdout clean, diagnostics on stderr -
# The Slice 07 stream contract also governs *errors*: a `--json` read-leaf failure
# must not emit non-JSON (Rich `Error:`/`Tip:`) on stdout, or a script piping stdout
# into a JSON parser chokes on the diagnostic. The error goes to stderr (err_console),
# stdout stays empty, exit is non-zero. Regression guard for the stdout-diagnostic
# leak fixed in model.py / trace.py / session_memory.py.


def test_model_catalog_json_failure_keeps_stdout_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from forge.core.models.catalog import ModelCatalogError

    def _boom() -> None:
        raise ModelCatalogError("bad catalog")

    monkeypatch.setattr("forge.cli.model.load_model_catalog", _boom)
    result = CliRunner().invoke(main, ["model", "catalog", "--json"])
    assert result.exit_code == 1
    assert result.stdout.strip() == ""
    assert "bad catalog" in result.stderr


def test_trace_show_json_failure_keeps_stdout_clean() -> None:
    # Relies on the autouse isolate_forge_home fixture: the empty home has no trace,
    # so `show` raises ForgeOpError before the --json branch.
    result = CliRunner().invoke(main, ["telemetry", "trace", "show", "missing", "--json"])
    assert result.exit_code == 1
    assert result.stdout.strip() == ""
    assert "Error:" in result.stderr


def test_trace_list_json_failure_keeps_stdout_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from forge.core.ops import ForgeOpError

    def _boom(**_: object) -> None:
        raise ForgeOpError("trace read failed")

    monkeypatch.setattr("forge.cli.trace.list_provider_traces", _boom)
    result = CliRunner().invoke(main, ["telemetry", "trace", "list", "--json"])
    assert result.exit_code == 1
    assert result.stdout.strip() == ""
    assert "trace read failed" in result.stderr


def test_session_memory_status_json_failure_keeps_stdout_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from forge.core.ops.session import ForgeOpError

    def _boom(**_: object) -> None:
        raise ForgeOpError("session listing failed")

    monkeypatch.setattr("forge.core.ops.session.list_sessions", _boom)
    result = CliRunner().invoke(main, ["session", "memory", "status", "--json"])
    assert result.exit_code == 1
    assert result.stdout.strip() == ""
    assert "session listing failed" in result.stderr


def test_memory_list_json_failure_keeps_stdout_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Outside a Forge project: the no-root guard fires before the --json branch.
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["memory", "list", "--json"])
    assert result.exit_code == 1
    assert result.stdout.strip() == ""
    assert "Not inside a Forge project" in result.stderr


def test_memory_report_json_failure_keeps_stdout_clean() -> None:
    # `--latest`/`--all` mutual exclusivity is checked before the --json branch.
    result = CliRunner().invoke(main, ["session", "memory", "report", "s1", "--latest", "--all", "--json"])
    assert result.exit_code == 1
    assert result.stdout.strip() == ""
    assert "mutually exclusive" in result.stderr


def test_session_list_json_failure_keeps_stdout_clean() -> None:
    # `--older-than` validation fires before the --json branch.
    result = CliRunner().invoke(main, ["session", "list", "--older-than", "0", "--json"])
    assert result.exit_code == 1
    assert result.stdout.strip() == ""
    assert "--older-than must be >= 1" in result.stderr


# --- Broader sweep: every --json command keeps stdout clean on a pre-flight error.
# Each argv triggers a validation/lookup error that fires before the command's
# `as_json` branch. The diagnostic must land on stderr; stdout must stay empty
# so a script piping `--json` stdout into a parser never sees diagnostic text.
# Relies on the autouse isolate_forge_home fixture for the lookup-miss cases.
_JSON_ERROR_PATH_CASES = [
    (["policy", "check", "--bundle", "tdd", "--json"], "Provide --file or --diff"),
    (["session", "transfer", "show", "no-such-parent-xyz", "--json"], "Error:"),
    (["session", "transfer", "diff", "no-such-parent-xyz", "--json"], "Error:"),
    (["proxy", "show", "no-such-proxy-xyz", "--json"], "Error:"),
    (["proxy", "metrics", "no-such-proxy-xyz", "--json"], "not found in registry"),
    (["proxy", "create", "no-such-template-xyz", "--json"], "not found"),
    (
        ["model", "backend", "test-auth", "no-such-source-xyz", "--json"],
        "Unknown backend source",
    ),
    (
        ["model", "backend", "reconcile", "no-such-source-xyz", "--json"],
        "Provide a local request id",
    ),
    (
        ["workflow", "panel", "x.md", "--context", "bogus", "--json"],
        "Invalid --context",
    ),
    (["workflow", "analyze", "--json"], "No topic provided"),
    (["workflow", "debate", "--json"], "provided"),
    (["workflow", "consensus", "--json"], "provided"),
]


@pytest.mark.parametrize(
    "argv,stderr_substr",
    _JSON_ERROR_PATH_CASES,
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_json_command_error_paths_keep_stdout_clean(argv: list[str], stderr_substr: str) -> None:
    result = CliRunner().invoke(main, argv)
    assert result.exit_code != 0, f"{argv} should fail"
    assert result.stdout.strip() == "", f"{argv} leaked stdout on error: {result.stdout!r}"
    assert stderr_substr in result.stderr, f"{argv} stderr missing {stderr_substr!r}: {result.stderr!r}"


def _cli_root() -> Path:
    return Path(__file__).resolve().parents[3] / "src" / "forge" / "cli"


def _repo_root() -> Path:
    return _cli_root().parents[2]


def _is_name(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _is_attr_call(node: ast.AST, owner: str, attr: str) -> TypeGuard[ast.Call]:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attr
        and _is_name(node.func.value, owner)
    )


def _kw_const_bool(call: ast.Call, name: str) -> bool | None:
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, bool):
            return kw.value.value
    return None


def _is_error_helper_stmt(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Name)
        and stmt.value.func.id in {"print_error", "print_error_with_tip"}
    )


def _is_stdout_console_print_stmt(stmt: ast.stmt) -> bool:
    if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
        return False
    func = stmt.value.func
    return isinstance(func, ast.Attribute) and func.attr == "print" and _is_name(func.value, "console")


def test_error_helpers_do_not_pass_stdout_console() -> None:
    """AST guard: line greps miss multiline ``console=console`` error calls."""
    offenders: list[str] = []
    for path in sorted(_cli_root().glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"print_error", "print_error_with_tip"}
            ):
                continue
            for kw in node.keywords:
                if kw.arg == "console" and _is_name(kw.value, "console"):
                    rel = path.relative_to(_repo_root())
                    offenders.append(f"{rel}:{node.lineno}: {node.func.id}")

    assert offenders == []


def test_error_continuations_do_not_use_stdout_console() -> None:
    """AST guard: a helper error plus an adjacent hint is one stderr message."""
    offenders: list[str] = []

    def check_body(path: Path, body: list[ast.stmt]) -> None:
        for prev_stmt, cur_stmt in zip(body, body[1:]):
            if _is_error_helper_stmt(prev_stmt) and _is_stdout_console_print_stmt(cur_stmt):
                rel = path.relative_to(_repo_root())
                offenders.append(f"{rel}:{cur_stmt.lineno}")

    for path in sorted(_cli_root().glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            for attr in ("body", "orelse", "finalbody"):
                body = getattr(node, attr, None)
                if isinstance(body, list):
                    check_body(path, body)

    assert offenders == []


def test_json_error_echoes_use_stderr() -> None:
    """AST guard for JSON error echoes: machine-readable errors belong on stderr."""
    offenders: list[str] = []
    for path in sorted(_cli_root().glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not _is_attr_call(node, "click", "echo") or not node.args:
                continue
            first_arg = node.args[0]
            if not _is_attr_call(first_arg, "json", "dumps") or not first_arg.args:
                continue
            dumped = first_arg.args[0]
            if not isinstance(dumped, ast.Dict):
                continue
            first_key = dumped.keys[0] if dumped.keys else None
            if not (
                isinstance(first_key, ast.Constant)
                and isinstance(first_key.value, str)
                and first_key.value in {"error", "routing_error"}
            ):
                continue
            if _kw_const_bool(node, "err") is not True:
                rel = path.relative_to(_repo_root())
                offenders.append(f"{rel}:{node.lineno}")

    assert offenders == []


def test_red_secho_uses_stderr() -> None:
    offenders: list[str] = []
    for path in sorted(_cli_root().glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not _is_attr_call(node, "click", "secho"):
                continue
            fg = next((kw.value for kw in node.keywords if kw.arg == "fg"), None)
            if not (isinstance(fg, ast.Constant) and fg.value == "red"):
                continue
            if _kw_const_bool(node, "err") is not True:
                rel = path.relative_to(_repo_root())
                offenders.append(f"{rel}:{node.lineno}")

    assert offenders == []


def test_supervisor_evaluate_json_failure_keeps_stdout_clean(tmp_path: Path) -> None:
    # `--no-proxy`/`--proxy` mutual exclusivity fires before the --json branch.
    # `-f` needs a real path (Click `exists=True`) to reach the function body.
    target = tmp_path / "x.py"
    target.write_text("x = 1\n")
    result = CliRunner().invoke(
        main,
        [
            "policy",
            "supervisor",
            "evaluate",
            "-f",
            str(target),
            "-r",
            "id",
            "--no-proxy",
            "--proxy",
            "p",
            "--json",
        ],
    )
    assert result.exit_code != 0
    assert result.stdout.strip() == ""
    assert "mutually exclusive" in result.stderr
