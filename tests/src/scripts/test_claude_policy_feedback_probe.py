"""The native permission trial is explicit, bounded and unable to pass without receipt evidence."""

import importlib.util
import io
import json
from pathlib import Path

import pytest


@pytest.fixture
def probe():
    path = Path(__file__).resolve().parents[3] / "scripts/experiments/claude-hooks/policy-feedback.py"
    spec = importlib.util.spec_from_file_location("claude_policy_feedback_probe", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_and_native_command_caps(probe, tmp_path):
    plan = probe.manifest()
    assert len(plan["cases"]) == plan["max_invocations"] == 8
    assert len({case["canary"] for case in plan["cases"]}) == 8
    for case in plan["cases"]:
        args = probe.command("claude", case, tmp_path / "settings.json")
        assert args[args.index("--max-turns") + 1] == "4"
        assert args[args.index("--max-budget-usd") + 1] == "0.10"
        assert args[args.index("--permission-mode") + 1] == "manual"
        assert args[args.index("--permission-prompts") + 1] == "none"
        assert "--dangerously-skip-permissions" not in args and "--bare" not in args
        assert case["canary"] not in case["prompt"]


def test_dry_run_never_resolves_auth_or_starts_a_process(probe, monkeypatch, capsys):
    def unexpected(*args, **kwargs):
        pytest.fail("Dry run must not resolve auth or start a child")

    monkeypatch.setattr(probe.subprocess, "run", unexpected)
    monkeypatch.setattr(probe.subprocess, "Popen", unexpected)
    monkeypatch.setattr("forge.core.auth.template_secrets.resolve_env_or_credential", unexpected)
    monkeypatch.setattr("sys.argv", ["policy-feedback.py"])
    assert probe.main() == 0
    assert len(json.loads(capsys.readouterr().out)["cases"]) == 8


@pytest.mark.parametrize("feedback", [True, False])
def test_hook_only_emits_context_and_refuses_a_second_action(probe, tmp_path, monkeypatch, capsys, feedback):
    case = {**probe.manifest()["cases"][0], "feedback": feedback}
    target = tmp_path / "fixture.txt"
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"case": case, "target": str(target)}))
    payload = {
        "hook_event_name": "PreToolUse",
        "permission_mode": "default",
        "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": probe.AFTER},
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert probe.hook(spec) == 0
    captured = capsys.readouterr()
    assert "operator notice" in captured.err
    wire = json.loads(captured.out)
    assert "permissionDecision" not in wire.get("hookSpecificOutput", {})
    assert bool(wire.get("hookSpecificOutput", {}).get("additionalContext")) is feedback
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert probe.hook(spec) == 2
    assert not target.exists()


def test_hook_parse_failure_blocks_instead_of_failing_open(probe, tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["policy-feedback.py", "--hook", str(tmp_path / "missing.json")])
    assert probe.main() == 2


@pytest.mark.parametrize(
    "failure",
    [
        "permission",
        "receipt",
        "mode",
        "cost",
        "missing_cost",
        "hook_approval",
        "extra_attempt",
    ],
)
def test_evidence_validation_cannot_pass_from_exit_status_alone(probe, failure):
    case = probe.manifest()["cases"][0]
    wire = {"hookSpecificOutput": {"additionalContext": "FORGE_CONTEXT_TOKEN=" + case["canary"]}}
    events = [{"tool": "Write", "permitted": True, "permission_mode": "default", "wire": wire}]
    report = {"result": case["canary"], "total_cost_usd": 0.001}
    content = probe.AFTER
    if failure == "permission":
        case = {**case, "allow_rule": False}
    elif failure == "receipt":
        report["result"] = "No marker received"
    elif failure == "mode":
        events[0]["permission_mode"] = "bypassPermissions"
    elif failure == "cost":
        report["total_cost_usd"] = 1.0
    elif failure == "missing_cost":
        report.pop("total_cost_usd")
    elif failure == "extra_attempt":
        events.append({"tool": "Read", "permitted": False})
    else:
        wire["hookSpecificOutput"]["permissionDecision"] = "allow"
    with pytest.raises(ValueError):
        probe.validate_case(case, report, events, content)


def test_changed_manifest_refuses_before_auth_or_output_creation(probe, tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("A changed manifest must not start native work")

    monkeypatch.setattr(probe.subprocess, "run", unexpected)
    plan = probe.manifest()
    plan["max_invocations"] = 9
    output = tmp_path / "run"
    with pytest.raises(ValueError, match="changed"):
        probe.run(plan, output)
    assert not output.exists()


def test_full_trial_with_fake_native_processes_is_isolated_and_runs_each_case_once(probe, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(probe.shutil, "which", lambda name: "/fake/claude")
    monkeypatch.setattr(
        probe.subprocess,
        "run",
        lambda *a, **kw: type("Version", (), {"stdout": "2.1.296 (Claude Code)"})(),
    )
    monkeypatch.setattr(
        "forge.core.auth.template_secrets.resolve_env_or_credential",
        lambda name: "synthetic-key",
    )
    monkeypatch.setattr(probe.os, "killpg", lambda *args: None)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "must-not-inherit")
    monkeypatch.setenv("FORGE_SESSION", "must-not-inherit")

    class Native:
        pid = 12345
        returncode = 0

        def __init__(self, argv, *, cwd, env, **kwargs):
            assert "ANTHROPIC_AUTH_TOKEN" not in env and "FORGE_SESSION" not in env
            assert env["ANTHROPIC_BASE_URL"] == "https://api.anthropic.com"
            self.private = Path(argv[argv.index("--settings") + 1]).parent
            spec = json.loads((self.private / "spec.json").read_text())
            case = spec["case"]
            calls.append(case["id"])
            target = Path(spec["target"])
            if case["allow_rule"]:
                target.write_text(probe.AFTER)
            wire = {"hookSpecificOutput": {"additionalContext": case["canary"]}} if case["feedback"] else {}
            event = {
                "tool": case["tool"],
                "permitted": True,
                "permission_mode": "default",
                "wire": wire,
            }
            (self.private / "hooks.jsonl").write_text(json.dumps(event) + "\n")
            self.result = {
                "total_cost_usd": 0.001,
                "result": case["canary"] if case["feedback"] else "NO_CONTEXT_TOKEN",
                "permission_denials": ([] if case["allow_rule"] else [{"tool_name": case["tool"]}]),
            }

        def communicate(self, **kwargs):
            return json.dumps(self.result), "synthetic-key"

        def wait(self, **kwargs):
            return self.returncode

    monkeypatch.setattr(probe.subprocess, "Popen", Native)
    output = tmp_path / "trial"
    probe.run(probe.manifest(), output)
    assert len(calls) == len(set(calls)) == 8
    assert len(list(output.glob("*/private/verified.json"))) == 8
    assert all(path.read_text() == "[REDACTED]" for path in output.glob("*/private/stderr.txt"))
    with pytest.raises(FileExistsError):
        probe.run(probe.manifest(), output)
    assert len(calls) == 8


@pytest.mark.parametrize("timeout", [False, True])
def test_native_failure_retains_partial_evidence_and_never_starts_the_next_case(probe, tmp_path, monkeypatch, timeout):
    calls = []
    signals = []
    monkeypatch.setattr(probe.shutil, "which", lambda name: "/fake/claude")
    monkeypatch.setattr(
        probe.subprocess,
        "run",
        lambda *a, **kw: type("Version", (), {"stdout": "2.1.296 (Claude Code)"})(),
    )
    monkeypatch.setattr(
        "forge.core.auth.template_secrets.resolve_env_or_credential",
        lambda name: "synthetic-key",
    )
    monkeypatch.setattr(probe.os, "killpg", lambda pid, signal: signals.append(signal))

    class Native:
        pid = 12345
        returncode = 1

        def __init__(self, *args, **kwargs):
            calls.append(args)
            self.communications = 0

        def communicate(self, **kwargs):
            self.communications += 1
            if timeout and self.communications <= 2:
                raise probe.subprocess.TimeoutExpired("claude", kwargs["timeout"])
            return "partial native output", "synthetic-key"

        def wait(self, **kwargs):
            return self.returncode

    monkeypatch.setattr(probe.subprocess, "Popen", Native)
    output = tmp_path / "trial"
    with pytest.raises(ValueError, match="wall deadline" if timeout else "failed"):
        probe.run(probe.manifest(), output)
    assert len(calls) == 1
    assert len(list(output.glob("*/private/started.json"))) == 1
    assert not list(output.glob("*/private/verified.json"))
    assert next(output.glob("*/private/stdout.txt")).read_text() == "partial native output"
    assert next(output.glob("*/private/stderr.txt")).read_text() == "[REDACTED]"
    assert probe.signal.SIGKILL in signals
    if timeout:
        assert probe.signal.SIGTERM in signals
