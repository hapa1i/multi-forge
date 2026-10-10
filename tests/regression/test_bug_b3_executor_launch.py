"""Feedback admission must preserve launchers and reject inherited runtime identity."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from forge.core.invoker.codex import CodexHeadlessInvoker
from forge.core.invoker.types import Attribution, HeadlessRequest
from forge.core.reactive.env import RunIdentity, build_claude_env
from forge.core.runtime.codex_feedback import (
    CODEX_EXECUTOR_IDENTITY_VAR,
    prepare_executor_launch,
)
from forge.session.codex_invoke import invoke_codex_interactive
from tests.src.session.test_codex_invoke import _preflight

pytestmark = pytest.mark.regression
_STREAM = (Path(__file__).parents[1] / "fixtures/codex/exec_json_success.jsonl").read_text()


@pytest.mark.parametrize("target_name", ["volta-shim", "mise", "aqua-proxy"])
@pytest.mark.parametrize("frontend", ["headless", "tui"])
@pytest.mark.parametrize("version_ok", [True, False])
def test_symlink_shims_keep_argv0_and_child_cwd(tmp_path, monkeypatch, target_name, frontend, version_ok) -> None:
    worktree = tmp_path / "worktree"
    (worktree / "bin").mkdir(parents=True)
    target = worktree / "bin" / target_name
    target.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "if os.path.basename(sys.argv[0]) != 'codex': sys.exit(23)\n"
        f"if sys.argv[1:] == ['--version']:\n print('codex-cli 0.162.1'); sys.exit({0 if version_ok else 7})\n"
        f"print({_STREAM!r})\n"
    )
    target.chmod(0o700)
    launcher = worktree / "bin/codex"
    launcher.symlink_to(target.name)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "bin")
    if frontend == "headless":
        env = dict(os.environ)
        request = HeadlessRequest(
            argv=["codex", "exec", "--json"],
            env=env,
            prompt="fixture",
            cwd=str(worktree),
            attribution=Attribution(command="codex-bridge", session="fixture"),
        )
        result = CodexHeadlessInvoker().run(request)
        assert result.success, result.stderr
        assert (CODEX_EXECUTOR_IDENTITY_VAR in env) is version_ok
        if version_ok:
            record = json.loads(env[CODEX_EXECUTOR_IDENTITY_VAR])
            assert record["launcher"] == str(launcher)
            assert record["executable"] == str(target)
    else:
        assert (
            invoke_codex_interactive(
                preflight=_preflight(auth_source="codex_store"),
                session_name="fixture",
                forge_root=str(worktree),
                cwd=str(worktree),
                run_identity=RunIdentity("run_fixture", None, "run_fixture"),
            )
            == 0
        )


def test_relative_executable_and_streaming_fingerprint(tmp_path, monkeypatch) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    launcher = worktree / "codex"
    content = b'#!/bin/sh\nprintf "codex-cli 0.162.1\\n"\n'
    launcher.write_bytes(content)
    launcher.chmod(0o700)
    monkeypatch.chdir(tmp_path)

    def forbid_whole_file_read(*args, **kwargs):
        raise AssertionError("Launch identity must stream executable hashing")

    monkeypatch.setattr(Path, "read_bytes", forbid_whole_file_read)
    env = {"PATH": "/bin"}
    argv = prepare_executor_launch(["./codex", "exec"], env, cwd=str(worktree))
    assert argv == [str(launcher), "exec"]
    assert json.loads(env[CODEX_EXECUTOR_IDENTITY_VAR])["sha256"] == hashlib.sha256(content).hexdigest()


def test_actual_hook_parent_accepts_managed_executor_and_rejects_nested_runtime(tmp_path) -> None:
    hook = (
        "import os; from forge.core.runtime.codex_feedback import policy_feedback_supported; "
        "print(policy_feedback_supported(os.environ))"
    )
    nested = f"import subprocess,sys; subprocess.run([sys.executable, '-c', {hook!r}], check=True)"
    launcher = tmp_path / "codex"
    launcher.write_text(
        f"#!{sys.executable}\n"
        "import json, subprocess, sys\n"
        "if sys.argv[1:] == ['--version']:\n print('codex-cli 0.162.1'); sys.exit(0)\n"
        f"direct = subprocess.check_output([sys.executable, '-c', {hook!r}], text=True).strip()\n"
        f"nested = subprocess.check_output([sys.executable, '-c', {nested!r}], text=True).strip()\n"
        "print(json.dumps({'direct':direct, 'nested':nested}))\n"
    )
    launcher.chmod(0o700)
    env = dict(os.environ)
    argv = prepare_executor_launch([str(launcher)], env)
    completed = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=10, check=True)
    assert json.loads(completed.stdout) == {"direct": "True", "nested": "False"}


def test_claude_children_strip_codex_admission_even_from_extra_vars(monkeypatch) -> None:
    monkeypatch.setenv(CODEX_EXECUTOR_IDENTITY_VAR, "inherited")
    env = build_claude_env(direct=True, hydrate_credentials=False, extra_vars={CODEX_EXECUTOR_IDENTITY_VAR: "copied"})
    assert CODEX_EXECUTOR_IDENTITY_VAR not in env
