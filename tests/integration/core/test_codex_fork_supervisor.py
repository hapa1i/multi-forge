"""Installed invoker/copy/audit composition with an explicit local stub, no model calls.

Runtime compatibility and model verdict quality require the separate native B5
product controls. This exercises the production subprocess and durable owners.
"""

import json
import sys
from dataclasses import replace

import pytest

from forge.core.reactive import codex_reviewer_home as reviewer
from forge.core.runtime.codex_review_source import bind_source
from forge.policy.semantic.attempts import read_attempts
from forge.policy.semantic.supervisor import (
    SemanticSupervisorPolicy,
    run_supervisor_check,
)
from forge.policy.types import ActionContext
from forge.session.models import LaneRecord, SupervisorConfig
from tests.fixtures.native_supervisor import (
    CHILD,
    THREAD,
    allow_synthetic_instructions,
    synthetic_rows,
    write_rollout,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def native_review(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "source"))
    monkeypatch.setenv("FORGE_SESSION", "parent")
    monkeypatch.setenv("FORGE_DEPTH", "0")
    monkeypatch.setenv("FORGE_RUN_ID", "parent-run")
    monkeypatch.setenv("FORGE_ROOT_RUN_ID", "root-run")
    allow_synthetic_instructions(monkeypatch)
    write_rollout(tmp_path / "source", synthetic_rows())
    log = tmp_path / "stub-invocations.jsonl"
    stub = tmp_path / "admitted-stub.py"
    stub.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "prompt=sys.stdin.read()\n"
        f"with Path({str(log)!r}).open('a') as log:\n"
        " log.write(json.dumps({'argv':sys.argv, 'env_keys':sorted(os.environ), 'stdin_chars':len(prompt), 'cwd':os.getcwd(), 'global_ignore_leaked':'GLOBAL_IGNORE_SENTINEL' in prompt})+'\\n')\n"
        "deny='FORBIDDEN_EDIT' in prompt\n"
        "verdict={'verdict':'divergent' if deny else 'aligned','confidence':1.0,'violations':"
        "[{'severity':'high','evidence':'Unapproved color','citations':['Use COBALT.'],'suggested_fix':'Use the approved color.'}] if deny else []}\n"
        f"print(json.dumps({{'type':'thread.started','thread_id':{CHILD!r}}}))\n"
        "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps(verdict)}}))\n"
        "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':974814,'cached_input_tokens':604288,'output_tokens':461}}))\n"
    )
    stub.chmod(0o700)
    monkeypatch.setattr(reviewer, "require_codex_fork_binary", lambda: str(stub))
    home = reviewer.initialize_home(extra_usage_off=True)
    (home / "auth.json").write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "account_id": "synthetic-account",
                    "access_token": "synthetic",
                    "refresh_token": "synthetic",
                },
            }
        )
    )
    plan = tmp_path / "approved.md"
    plan.write_text("Use COBALT.\n")
    config = SupervisorConfig(
        native_source=bind_source(THREAD, forge_root=None),
        auth_mode="subscription-only",
        supervisor_model="gpt-6.1-sol",
        supervisor_effort="low",
        plan_override_path=str(plan),
    )
    context = ActionContext(
        origin="claude_code",
        event="PreToolUse.Edit",
        tool_name="Edit",
        tool_args={},
        repo_root=str(tmp_path),
        session_name="executor",
        target_path="color.txt",
        new_content="COBALT",
    )
    return config, context, log


def test_native_allow_and_deny_use_one_invoker_with_immutable_audit(native_review):
    config, context, log = native_review
    lane = LaneRecord("codex", "chatgpt", "gpt-6.1-sol")
    before = config.native_source
    policy = SemanticSupervisorPolicy(config=config, lane_record=lane)
    for _ in range(2):
        decision = policy.evaluate(context)
        assert decision.decision == "allow" and not decision.fail_open and not decision.cached, decision
    denied = run_supervisor_check(config, replace(context, new_content="FORBIDDEN_EDIT"), lane_record=lane)
    assert denied.decision.decision == "deny", denied.decision
    assert denied.decision.violations[0].verified_citations[0].text == "Use COBALT."
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(calls) == 3
    for call in calls:
        assert "FORBIDDEN_EDIT" not in " ".join(call["argv"])
        assert call["stdin_chars"] > 100 and call["cwd"] == context.repo_root
        assert not {"FORGE_SESSION", "FORGE_ROOT_RUN_ID", "FORGE_RUN_ID", "FORGE_DEV"} & set(call["env_keys"])
        assert call["argv"].index('forced_login_method="chatgpt"') > call["argv"].index("fork")
        for control in (
            "agents.enabled=false",
            "memories.use_memories=false",
            "memories.generate_memories=false",
        ):
            assert call["argv"].index(control) > call["argv"].index("fork")
        assert "--ignore-user-config" in call["argv"] and "--ignore-rules" in call["argv"]
        disabled = [value for flag, value in zip(call["argv"], call["argv"][1:]) if flag == "--disable"]
        assert disabled == ["hooks", "multi_agent", "apps", "plugins"]
    records = read_attempts("executor")
    assert len(records) == 3
    for record in records:
        native = record["native_review"]
        assert record["schema_version"] == 3 and record["state"] == "completed"
        assert native["inputs_preserved"] and native["inputs_current"] and native["independence"] == "separate"
        assert native["reviewer_thread_id"] != native["source_thread_id"]
        assert native["review_usage"]["input_tokens"] == 162211
        assert native["terminal_usage"]["input_tokens"] == 974814
        assert "synthetic-account" not in json.dumps(record)
    assert config.native_source == before


@pytest.mark.parametrize("changed", ["plan", "source", "configuration"])
def test_changed_input_during_native_review_makes_verdict_unavailable(native_review, monkeypatch, changed):
    from pathlib import Path

    from forge.core.invoker.codex import CodexHeadlessInvoker

    config, context, log = native_review
    invoke = CodexHeadlessInvoker.run

    def change_after_dispatch(self, request):
        result = invoke(self, request)
        if changed == "plan":
            Path(config.plan_override_path).write_text("Use AMBER instead.\n")
        elif changed == "source":
            with Path(config.native_source.rollout_path).open("ab") as stream:
                stream.write(b'{"type":"event_msg","payload":{"type":"task_started","turn_id":"changed"}}\n')
        else:

            def no_longer_current(*args):
                raise ValueError("Changed binding")

            monkeypatch.setattr("forge.policy.semantic.native_codex._verify_current_config", no_longer_current)
        return result

    monkeypatch.setattr(CodexHeadlessInvoker, "run", change_after_dispatch)
    result = run_supervisor_check(config, context, lane_record=LaneRecord("codex", "chatgpt", "gpt-6.1-sol"))
    assert result.dispatched and result.decision.fail_open
    assert len(log.read_text().splitlines()) == 1
    assert read_attempts("executor")[0]["native_review"]["inputs_current"] is False


def test_native_refusal_never_falls_back_or_spends_a_call(native_review):
    config, context, log = native_review
    lane = LaneRecord("codex", "chatgpt", "gpt-6.1-sol")
    result = run_supervisor_check(config, replace(context, origin="forge_cli"), lane_record=lane)
    assert result.decision.fail_open and result.dispatched is False
    assert not log.exists()
    result = run_supervisor_check(config, context, lane_record=lane, usage_command="supervisor-shadow")
    assert result.decision.fail_open and not log.exists()


@pytest.mark.parametrize(
    "output", ["not a verdict", '{"type":"turn.failed","error":{"message":"usage limit reached"}}']
)
def test_native_malformed_or_quota_output_never_retries(native_review, monkeypatch, output):
    from forge.core.invoker.codex import CodexHeadlessInvoker
    from forge.core.invoker.types import HeadlessResult

    config, context, _ = native_review
    calls = []

    def failed(self, request):
        calls.append(request)
        quota = "turn.failed" in output
        return HeadlessResult(
            stdout=output if not quota else "",
            returncode=0,
            runtime_session_id=CHILD,
            runtime_is_error=quota,
            stderr="usage limit reached" if quota else "",
        )

    monkeypatch.setattr(CodexHeadlessInvoker, "run", failed)
    result = run_supervisor_check(config, context, lane_record=LaneRecord("codex", "chatgpt", "gpt-6.1-sol"))
    assert len(calls) == 1 and result.decision.fail_open


@pytest.mark.parametrize("interactive", [False, True])
def test_native_stop_keeps_global_ignores_and_one_correction(native_review, tmp_path, monkeypatch, interactive):
    from forge.core.native_review_types import NativeReviewBoundary
    from forge.policy.semantic import stop_review
    from tests.fixtures.stop_review import changed
    from tests.fixtures.stop_review import context as make_context
    from tests.fixtures.stop_review import deadline

    config, _, log = native_review
    ctx = make_context(tmp_path)
    executor = synthetic_rows(ctx.thread_id, complete=False)
    executor[1]["payload"]["turn_id"] = ctx.turn_id
    if interactive:
        executor[0]["payload"].update(originator="codex_cli_rs", source="cli")
    rollout = write_rollout(tmp_path / "source", executor)
    # Executor histories are evidence of identity only; old turns are not fork input.
    with rollout.open("ab") as stream:
        stream.write(b'{"type":"event_msg","payload":{"text":"' + b"x" * 2_000_000 + b'"}}\n')
    ctx = replace(
        ctx,
        config=replace(config, review_trigger="stop"),
        lane=LaneRecord("codex", "chatgpt", "gpt-6.1-sol"),
        native_boundary=NativeReviewBoundary(ctx.thread_id, ctx.turn_id, str(rollout), "Stop", "BOUNDARY_DONE"),
    )
    excludes = tmp_path / "global-ignore"
    excludes.write_text("private-fixture.env\n")
    global_config = tmp_path / "global.gitconfig"
    global_config.write_text(f"[core]\n    excludesFile = {excludes}\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    (ctx.checkout / "private-fixture.env").write_text("GLOBAL_IGNORE_SENTINEL\n")
    changed(ctx, "FORBIDDEN_EDIT\n")
    first = stop_review.review_stop(ctx, deadline=deadline(), current_config=lambda: ctx.config_digest)
    assert first.correction and first.decision is not None and first.decision.decision == "deny", first
    repeated = stop_review.review_stop(ctx, deadline=deadline(), current_config=lambda: ctx.config_digest)
    assert not repeated.correction
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(calls) == 1 and not calls[0]["global_ignore_leaked"]


def test_two_sessions_wait_for_one_login_and_each_dispatch_once(native_review, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from forge.core.invoker.codex import CodexHeadlessInvoker

    config, context, log = native_review
    lane = LaneRecord("codex", "chatgpt", "gpt-6.1-sol")
    first_entered, second_started, release = Event(), Event(), Event()
    invoke = CodexHeadlessInvoker.run

    def held_invoker(self, request):
        if not first_entered.is_set():
            first_entered.set()
            assert release.wait(timeout=5)
        return invoke(self, request)

    def second_review():
        second_started.set()
        return run_supervisor_check(config, replace(context, session_name="second"), lane_record=lane)

    monkeypatch.setattr(CodexHeadlessInvoker, "run", held_invoker)
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(run_supervisor_check, config, replace(context, session_name="first"), lane_record=lane)
        try:
            assert first_entered.wait(timeout=5)
            second = workers.submit(second_review)
            assert second_started.wait(timeout=5)
            # A busy store is still locally ready and the second review waits.
            assert reviewer.auth_status()["ready"]
            assert not second.done()
        finally:
            release.set()
        for result in (first.result(timeout=10), second.result(timeout=10)):
            assert result.dispatched and not result.decision.fail_open, result
    assert len(log.read_text().splitlines()) == 2
    assert len(read_attempts("first")) == len(read_attempts("second")) == 1
