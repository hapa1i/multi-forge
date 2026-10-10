"""Executor feedback admission is refreshed at launch, not during each hook."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.core.invoker.codex import CodexHeadlessInvoker
from forge.core.invoker.types import Attribution, HeadlessRequest
from forge.core.runtime.codex_feedback import (
    CODEX_EXECUTOR_IDENTITY_VAR,
    policy_feedback_supported,
    prepare_executor_launch,
)


@pytest.fixture(autouse=True)
def bound_hook_origin(monkeypatch):
    # These tests isolate record/version admission; real ancestry has regression coverage.
    monkeypatch.setattr("forge.core.runtime.codex_feedback._hook_from_launch_child", lambda parent: True)


def executable(tmp_path: Path, version="0.162.1") -> Path:
    path = tmp_path / "codex"
    path.write_text(f'#!/bin/sh\nprintf "codex-cli {version}\\n"\n')
    path.chmod(0o700)
    return path


def test_exact_launcher_is_resolved_and_inherited_identity_replaced(tmp_path: Path) -> None:
    binary = executable(tmp_path)
    env = {"PATH": str(tmp_path), CODEX_EXECUTOR_IDENTITY_VAR: "stale", "SECRET": "not in identity"}
    argv = prepare_executor_launch(["codex", "exec", "resume", "thread"], env)
    assert argv == [str(binary), "exec", "resume", "thread"]
    identity = json.loads(env[CODEX_EXECUTOR_IDENTITY_VAR])
    assert identity["executable"] == str(binary)
    assert "SECRET" not in env[CODEX_EXECUTOR_IDENTITY_VAR]
    with patch("subprocess.run", side_effect=AssertionError("no hot-path probe")):
        assert policy_feedback_supported(env)


@pytest.mark.parametrize(
    "version, supported",
    [("0.161.0", True), ("0.162.1", True), ("0.149.1", False), ("0.999.0", False), ("development", False)],
)
def test_version_admission_is_feature_specific(tmp_path, version, supported) -> None:
    executable(tmp_path, version)
    env = {"PATH": str(tmp_path)}
    prepare_executor_launch(["codex"], env)
    assert policy_feedback_supported(env) is supported


def test_replacement_before_resume_refreshes_but_running_identity_survives(tmp_path) -> None:
    executable(tmp_path)
    running = {"PATH": str(tmp_path)}
    prepare_executor_launch(["codex"], running)
    old = running[CODEX_EXECUTOR_IDENTITY_VAR]
    executable(tmp_path, "0.149.1")
    assert policy_feedback_supported(running)
    resumed = dict(running)
    prepare_executor_launch(["codex", "exec", "resume", "thread"], resumed)
    assert resumed[CODEX_EXECUTOR_IDENTITY_VAR] != old
    assert not policy_feedback_supported(resumed)


def test_replacement_during_probe_invalidates_identity(tmp_path) -> None:
    binary = executable(tmp_path)
    env = {"PATH": str(tmp_path), CODEX_EXECUTOR_IDENTITY_VAR: "stale"}
    from subprocess import CompletedProcess

    def replaced(*args, **kwargs):
        executable(tmp_path, "0.149.1")
        return CompletedProcess(args[0], 0, "codex-cli 0.162.1\n")

    with patch("forge.core.runtime.codex_feedback.subprocess.run", side_effect=replaced):
        assert prepare_executor_launch(["codex"], env) == [str(binary)]
    assert CODEX_EXECUTOR_IDENTITY_VAR not in env


def test_missing_binary_and_malformed_identity_are_conservative(tmp_path) -> None:
    env = {"PATH": str(tmp_path), CODEX_EXECUTOR_IDENTITY_VAR: "stale"}
    assert prepare_executor_launch(["codex"], env) == ["codex"]
    assert CODEX_EXECUTOR_IDENTITY_VAR not in env
    for raw in ("", "[]", "invalid", "{}", json.dumps({"version": ["0.162.1"]}), "x" * 4097):
        assert not policy_feedback_supported({CODEX_EXECUTOR_IDENTITY_VAR: raw})


def test_headless_launch_records_facts_at_dispatch_not_request_construction(tmp_path) -> None:
    binary = executable(tmp_path)
    request = HeadlessRequest(
        argv=["codex", "exec", "resume", "thread"],
        prompt="p",
        env={"PATH": str(tmp_path)},
        attribution=Attribution(command="codex-resume", session="test"),
    )
    argv, hints = CodexHeadlessInvoker()._prepare_argv(request)
    assert hints.is_jsonl_stream
    assert argv[0] == str(binary)
    assert policy_feedback_supported(request.env)
    executable(tmp_path, "0.149.1")
    CodexHeadlessInvoker()._prepare_argv(request)
    assert not policy_feedback_supported(request.env)


def test_tui_start_and_resume_use_same_launch_seam(tmp_path, monkeypatch) -> None:
    from forge.core.reactive.env import RunIdentity
    from forge.session.codex_invoke import invoke_codex_interactive
    from tests.src.session.test_codex_invoke import _preflight

    binary = executable(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv(CODEX_EXECUTOR_IDENTITY_VAR, "inherited")
    import subprocess

    run = subprocess.run

    for thread in (None, "thread"):

        def launch(argv, **kwargs):
            if argv[-1] == "--version":
                return run(argv, **kwargs)
            assert argv[0] == str(binary)
            assert ("resume" in argv) is (thread is not None)
            assert policy_feedback_supported(kwargs["env"])
            return subprocess.CompletedProcess(argv, 0)

        with patch("forge.session.codex_invoke.subprocess.run", side_effect=launch):
            assert (
                invoke_codex_interactive(
                    preflight=_preflight(auth_source="codex_store"),
                    session_name="test",
                    forge_root=str(tmp_path),
                    cwd=str(tmp_path),
                    run_identity=RunIdentity("run_1", None, "run_1"),
                    resume_thread_id=thread,
                )
                == 0
            )
    assert os.environ[CODEX_EXECUTOR_IDENTITY_VAR] == "inherited"


def test_reviewer_does_not_probe_executor_or_inherit_its_identity() -> None:
    request = HeadlessRequest(
        argv=["codex", "exec"],
        prompt="p",
        env={CODEX_EXECUTOR_IDENTITY_VAR: "stale"},
        attribution=Attribution(command="supervisor"),
        watchdog_deadline=1.0,
    )
    with patch("forge.core.invoker.codex.prepare_executor_launch", side_effect=AssertionError("no reviewer probe")):
        assert CodexHeadlessInvoker()._prepare_argv(request)[0] == request.argv
    assert CODEX_EXECUTOR_IDENTITY_VAR not in request.env
