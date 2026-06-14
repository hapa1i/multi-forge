"""Hook-level tests for `forge hook codex-policy-check`.

Wire invariant under test: stdout carries ONLY strict deny JSON (Codex fails OPEN
on malformed hook output) and diagnostics ride stderr -- but only once a Forge
session is resolved. An unresolvable session is a fully silent allow (a user-scope
registration fires for every Codex session; "no session" means Forge is not
managing this turn). Assertions use ``result.stdout`` / ``result.stderr``
separately (Click 8.2+ separates streams; ``result.output`` would blur exactly
the invariant these tests pin).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from forge.cli.hooks.commands import hooks
from forge.policy.semantic.plan_check import PlanCheckVerdict
from forge.policy.types import PolicyDecision, Violation
from forge.session import SessionStore, create_session_state
from forge.session.models import PolicyIntent, SupervisorConfig


def _make_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    bundles: list[str] | None = None,
    supervisor: SupervisorConfig | None = None,
    set_forge_root_env: bool = True,
) -> SessionStore:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORGE_SESSION", "codex-test-session")
    if set_forge_root_env:
        monkeypatch.setenv("FORGE_FORGE_ROOT", str(tmp_path))
    else:
        monkeypatch.delenv("FORGE_FORGE_ROOT", raising=False)

    store = SessionStore(str(tmp_path), "codex-test-session")
    manifest = create_session_state("codex-test-session", worktree_path=str(tmp_path))
    manifest.forge_root = str(tmp_path)
    manifest.intent.policy = PolicyIntent(
        enabled=True,
        bundles=bundles or [],
        supervisor=supervisor,
    )
    store.write(manifest)
    return store


def _patch_cmd(*sections: str) -> str:
    return "*** Begin Patch\n" + "\n".join(sections) + "\n*** End Patch"


def _payload(patch_command: str, *, tool_name: str = "apply_patch", cwd: str | None = None) -> str:
    data = {
        "session_id": "019eb075-fd3f-7381-9008-9ef8df491237",  # Codex thread UUID, not in Claude index
        "transcript_path": "/tmp/rollout.jsonl",
        "hook_event_name": "PreToolUse",
        "model": "gpt-5.5",
        "permission_mode": "bypassPermissions",
        "turn_id": "019eb075-fd77-7992-b35d-73a30bfe9614",
        "tool_name": tool_name,
        "tool_input": {"command": patch_command},
        "tool_use_id": "call_test",
    }
    if cwd is not None:
        data["cwd"] = cwd
    return json.dumps(data)


def _invoke(payload: str):  # type: ignore[no-untyped-def]
    return CliRunner().invoke(hooks, ["codex-policy-check"], input=payload)


def _deny_wire(stdout: str) -> dict:
    """Parse stdout as exactly one strict deny JSON object (the wire invariant)."""
    wire = json.loads(stdout)
    assert set(wire.keys()) == {"hookSpecificOutput"}
    return wire["hookSpecificOutput"]


class TestCodexPolicyCheckDeny:
    def test_impl_without_tests_emits_deny_json_exit_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_session(tmp_path, monkeypatch, bundles=["tdd"])
        payload = _payload(_patch_cmd("*** Add File: src/x.py", "+x = 1"), cwd=str(tmp_path))

        result = _invoke(payload)

        assert result.exit_code == 0  # Codex deny is stdout JSON, never an exit code
        out = _deny_wire(result.stdout)
        assert out["hookEventName"] == "PreToolUse"
        assert out["permissionDecision"] == "deny"
        assert "[tdd.tests-before-impl]" in out["permissionDecisionReason"]
        assert "Note: This policy was configured by the project owner." in out["permissionDecisionReason"]

    def test_multi_file_deny_reason_names_only_denying_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_session(tmp_path, monkeypatch, bundles=["tdd"])
        # docs file allows; src file denies (no tests touched).
        payload = _payload(
            _patch_cmd("*** Add File: docs/note.md", "+note", "*** Add File: src/x.py", "+x = 1"),
            cwd=str(tmp_path),
        )

        result = _invoke(payload)

        out = _deny_wire(result.stdout)
        assert "src/x.py:" in out["permissionDecisionReason"]
        assert "docs/note.md:" not in out["permissionDecisionReason"]

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    @patch("forge.policy.semantic.plan_check.run_plan_check")
    def test_deny_wins_over_needs_review_across_files(
        self, mock_check: MagicMock, mock_invoke: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cross-file precedence: a denying file's wire wins over another's unresolved review."""
        plan = tmp_path / "plan.md"
        plan.write_text("# Plan")
        _make_session(
            tmp_path,
            monkeypatch,
            bundles=["tdd"],
            supervisor=SupervisorConfig(resume_id="planner", direct=True, cascade=True, plan_override_path=str(plan)),
        )
        # Tier-1 escalates everything; the supervisor stays unresolved (needs_review).
        mock_check.return_value = PlanCheckVerdict(aligned=False, reason="unsure")
        mock_invoke.return_value = PolicyDecision(decision="needs_review", policy_id="semantic.supervisor")
        # docs file: tdd inapplicable -> final needs_review; src file: tdd denies.
        payload = _payload(
            _patch_cmd("*** Add File: docs/note.md", "+note", "*** Add File: src/x.py", "+x = 1"),
            cwd=str(tmp_path),
        )

        result = _invoke(payload)

        out = _deny_wire(result.stdout)
        assert out["permissionDecision"] == "deny"
        assert "[tdd.tests-before-impl]" in out["permissionDecisionReason"]
        assert "Policy review required" not in out["permissionDecisionReason"]


class TestTelemetrySourceLabel:
    def test_summary_names_denying_policy_not_first_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The stderr summary labels the decisive (denying) result. file_results[0]
        here is an allowing test file -- deriving from it would route the label
        helper down the non-deny branch and name tdd.tests-before-impl instead of
        the actual blocker, tdd.no-skip-tests."""
        _make_session(tmp_path, monkeypatch, bundles=["tdd"])
        payload = _payload(
            _patch_cmd(
                "*** Add File: tests/test_clean.py",
                "+def test_clean(): pass",
                "*** Add File: tests/test_skipped.py",
                "+import pytest",
                "+@pytest.mark.skip",
                "+def test_s(): pass",
            ),
            cwd=str(tmp_path),
        )

        result = _invoke(payload)

        out = _deny_wire(result.stdout)
        assert out["permissionDecision"] == "deny"
        assert "against tdd.no-skip-tests (blocked" in result.stderr


class TestCodexPolicyCheckAllow:
    def test_test_file_add_allows_with_empty_stdout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_session(tmp_path, monkeypatch, bundles=["tdd"])
        payload = _payload(_patch_cmd("*** Add File: tests/test_x.py", "+def test_x(): pass"), cwd=str(tmp_path))

        result = _invoke(payload)

        assert result.exit_code == 0
        assert result.stdout == ""  # allow emits NO stdout (allow-feedback delivery unprobed)

    def test_atomic_test_plus_impl_patch_allows(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Tests-first ordering: one patch adding test + impl together passes TDD."""
        _make_session(tmp_path, monkeypatch, bundles=["tdd"])
        # Impl section listed FIRST; the sort must evaluate the test file first anyway.
        payload = _payload(
            _patch_cmd(
                "*** Add File: src/x.py",
                "+x = 1",
                "*** Add File: tests/test_x.py",
                "+def test_x(): pass",
            ),
            cwd=str(tmp_path),
        )

        result = _invoke(payload)

        assert result.exit_code == 0
        assert result.stdout == ""

    def test_delete_only_patch_allows(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_session(tmp_path, monkeypatch, bundles=["tdd"])
        payload = _payload(_patch_cmd("*** Delete File: src/x.py"), cwd=str(tmp_path))

        result = _invoke(payload)

        assert result.exit_code == 0
        assert result.stdout == ""
        assert "no evaluable file operations" in result.stderr


class TestCodexPolicyCheckFailOpen:
    def test_bash_tool_passes_through(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_session(tmp_path, monkeypatch, bundles=["tdd"])
        payload = _payload("echo hi", tool_name="Bash", cwd=str(tmp_path))

        result = _invoke(payload)

        assert result.exit_code == 0
        assert result.stdout == ""

    def test_wrong_event_passes_through(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_session(tmp_path, monkeypatch, bundles=["tdd"])
        data = json.loads(_payload(_patch_cmd("*** Add File: src/x.py", "+1"), cwd=str(tmp_path)))
        data["hook_event_name"] = "PostToolUse"

        result = _invoke(json.dumps(data))

        assert result.exit_code == 0
        assert result.stdout == ""

    def test_invalid_stdin_passes_through(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_session(tmp_path, monkeypatch, bundles=["tdd"])

        result = _invoke("not json at all")

        assert result.exit_code == 0
        assert result.stdout == ""

    def test_no_session_passes_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Regression: a user-scope registration fires for every Codex session, so an
        unresolvable session (any non-Forge Codex turn) must emit NO stderr -- the
        diagnostic rides the debug log only."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FORGE_SESSION", raising=False)
        monkeypatch.delenv("FORGE_FORGE_ROOT", raising=False)
        caplog.set_level(logging.DEBUG, logger="forge.cli.hooks.commands")
        payload = _payload(_patch_cmd("*** Add File: src/x.py", "+1"), cwd=str(tmp_path))

        result = _invoke(payload)

        assert result.exit_code == 0
        assert result.stdout == ""
        assert result.stderr == ""
        assert "no session resolved" in caplog.text

    def test_malformed_patch_passes_through(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_session(tmp_path, monkeypatch, bundles=["tdd"])
        payload = _payload("not a patch", cwd=str(tmp_path))

        result = _invoke(payload)

        assert result.exit_code == 0
        assert result.stdout == ""
        assert "no evaluable file operations" in result.stderr


class TestWireStrictness:
    def test_nonempty_stdout_is_exactly_one_hook_specific_output_object(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: Codex fails OPEN on malformed output -- whenever stdout is
        non-empty it must parse as one JSON object whose only top-level key is
        hookSpecificOutput (no diagnostics may leak into stdout)."""
        _make_session(tmp_path, monkeypatch, bundles=["tdd"])
        payload = _payload(_patch_cmd("*** Add File: src/x.py", "+x = 1"), cwd=str(tmp_path))

        result = _invoke(payload)

        assert result.stdout.strip() != ""
        wire = json.loads(result.stdout)  # raises if any stderr-bound text leaked
        assert set(wire.keys()) == {"hookSpecificOutput"}


class TestPersistence:
    def test_decision_log_one_entry_per_file_with_codex_confirmed_by(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _make_session(tmp_path, monkeypatch, bundles=["tdd"])
        payload = _payload(
            _patch_cmd(
                "*** Add File: tests/test_x.py",
                "+def test_x(): pass",
                "*** Add File: src/x.py",
                "+x = 1",
            ),
            cwd=str(tmp_path),
        )

        result = _invoke(payload)
        assert result.exit_code == 0

        manifest = store.read()
        assert manifest.confirmed.policy is not None
        assert manifest.confirmed.confirmed_by == "hook:codex-policy-check"
        summaries = [e["context_summary"] for e in manifest.confirmed.policy.decisions]
        assert "apply_patch:tests/test_x.py" in summaries
        assert "apply_patch:src/x.py" in summaries

    def test_state_aggregated_across_files_not_last_file_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: evaluate() clears collected state per call, so a one-shot
        end-of-loop read would drop tests_touched when the LAST file (docs/note.md)
        doesn't trigger TDD -- and the next hook turn would wrongly deny."""
        store = _make_session(tmp_path, monkeypatch, bundles=["tdd"])
        payload = _payload(
            _patch_cmd(
                "*** Add File: tests/test_x.py",
                "+def test_x(): pass",
                "*** Add File: docs/note.md",
                "+note",
            ),
            cwd=str(tmp_path),
        )

        result = _invoke(payload)
        assert result.exit_code == 0
        assert result.stdout == ""

        manifest = store.read()
        assert manifest.confirmed.policy is not None
        assert len(manifest.confirmed.policy.decisions) == 2
        tdd_state = manifest.confirmed.policy.policy_states.get("tdd.tests-before-impl")
        assert tdd_state is not None
        assert "tests/test_x.py" in tdd_state["tests_touched"]

        # The persisted state must carry into the next invocation: impl now allowed.
        follow_up = _payload(_patch_cmd("*** Add File: src/x.py", "+x = 1"), cwd=str(tmp_path))
        result2 = _invoke(follow_up)
        assert result2.exit_code == 0
        assert result2.stdout == ""


class TestPayloadCwdRooting:
    def test_session_resolved_via_payload_cwd_not_process_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: session-store rooting must use the payload cwd. The manifest
        is written via SessionStore directly (never indexed) and FORGE_FORGE_ROOT is
        unset, so neither the index fallback nor the env can rescue a wrong cwd --
        only the payload-cwd forge_root derivation finds the manifest."""
        project = tmp_path / "project"
        project.mkdir()
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()

        _make_session(project, monkeypatch, bundles=["tdd"], set_forge_root_env=False)
        monkeypatch.chdir(elsewhere)  # process CWD points away from the project

        payload = _payload(_patch_cmd("*** Add File: src/x.py", "+x = 1"), cwd=str(project))
        result = _invoke(payload)

        # A deny wire proves the manifest was found -- impossible via process CWD.
        out = _deny_wire(result.stdout)
        assert out["permissionDecision"] == "deny"


class TestCascadeSharedWiring:
    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    @patch("forge.policy.semantic.plan_check.run_plan_check")
    def test_short_circuit_skips_supervisor(
        self, mock_check: MagicMock, mock_invoke: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The extracted register_supervisor_and_restore serves codex-policy-check:
        tier-1 aligned short-circuits without a frontier invocation."""
        plan = tmp_path / "plan.md"
        plan.write_text("# Plan")
        _make_session(
            tmp_path,
            monkeypatch,
            supervisor=SupervisorConfig(resume_id="planner", direct=True, cascade=True, plan_override_path=str(plan)),
        )
        mock_check.return_value = PlanCheckVerdict(aligned=True, reason="covered")
        payload = _payload(_patch_cmd("*** Add File: src/x.py", "+x = 1"), cwd=str(tmp_path))

        result = _invoke(payload)

        assert result.exit_code == 0
        assert result.stdout == ""
        assert mock_check.call_count == 1
        mock_invoke.assert_not_called()

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    @patch("forge.policy.semantic.plan_check.run_plan_check")
    def test_escalation_supervisor_deny_emits_deny_wire(
        self, mock_check: MagicMock, mock_invoke: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An escalated check the supervisor denies emits the Codex deny JSON."""
        plan = tmp_path / "plan.md"
        plan.write_text("# Plan")
        _make_session(
            tmp_path,
            monkeypatch,
            supervisor=SupervisorConfig(resume_id="planner", direct=True, cascade=True, plan_override_path=str(plan)),
        )
        mock_check.return_value = PlanCheckVerdict(aligned=False, reason="touches unplanned files")
        mock_invoke.return_value = PolicyDecision(
            decision="deny",
            policy_id="semantic.supervisor",
            violations=[
                Violation(
                    rule_id="semantic.supervisor.alignment",
                    message="Divergent from plan",
                    severity="high",
                    citations=["Plan section 1"],
                )
            ],
        )
        payload = _payload(_patch_cmd("*** Add File: src/x.py", "+x = 1"), cwd=str(tmp_path))

        result = _invoke(payload)

        assert result.exit_code == 0
        out = _deny_wire(result.stdout)
        assert "[semantic.supervisor.alignment] Divergent from plan" in out["permissionDecisionReason"]
        assert mock_invoke.call_count == 1
