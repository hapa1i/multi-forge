"""Tests for the Codex hook adapter + responder (cli/hooks/codex_policy.py).

Adapter cases are driven by the real captured payload at
``tests/fixtures/codex/hooks/pre_tool_use.stdin.json`` (codex-cli 0.138.0) with
``tool_name``/``tool_input`` swapped per case; responder cases pin the wire JSON
against the probe-verified shape in ``scripts/experiments/codex-hooks/responses/``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from forge.cli.hooks.codex_policy import CodexHookAdapter, CodexHookResponder
from forge.policy.types import CompositeDecision, PolicyDecision, Violation

_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "codex" / "hooks"


def _make_manifest(name: str = "codex-session") -> MagicMock:
    m = MagicMock()
    m.name = name
    return m


def _payload(tool_name: str, command: str, cwd: str | None = None) -> dict:
    payload = json.loads((_FIXTURES / "pre_tool_use.stdin.json").read_text())
    payload["tool_name"] = tool_name
    payload["tool_input"] = {"command": command}
    if cwd is not None:
        payload["cwd"] = cwd
    return payload


def _patch(*sections: str) -> str:
    return "*** Begin Patch\n" + "\n".join(sections) + "\n*** End Patch"


class TestCodexHookAdapter:
    def test_bash_yields_no_contexts(self, tmp_path: Path) -> None:
        payload = _payload("Bash", "echo PROBE-RT-1", cwd=str(tmp_path))
        assert CodexHookAdapter().build_contexts(payload, "Bash", _make_manifest()) == []

    def test_add_file_normalizes_to_write(self, tmp_path: Path) -> None:
        payload = _payload("apply_patch", _patch("*** Add File: src/x.py", "+x = 1"), cwd=str(tmp_path))
        contexts = CodexHookAdapter().build_contexts(payload, "apply_patch", _make_manifest())
        assert len(contexts) == 1
        ctx = contexts[0]
        assert ctx.origin == "codex"
        assert ctx.tool_name == "Write"  # normalized so policy applies_to gates match
        assert ctx.event == "PreToolUse.Write"
        assert ctx.target_path == "src/x.py"
        assert ctx.new_content == "x = 1"
        assert ctx.raw_diff is None  # an Add's full content already is new_content
        assert ctx.repo_root == str(tmp_path.resolve())
        assert ctx.session_name == "codex-session"
        assert ctx.tool_args == {
            "codex_tool_name": "apply_patch",
            "path": "src/x.py",
            "move_to": None,
            "kind": "add",
        }

    def test_update_file_normalizes_to_edit_with_raw_diff(self, tmp_path: Path) -> None:
        patch_cmd = _patch("*** Update File: src/x.py", "@@ def f():", "-    return 1", "+    return 2")
        payload = _payload("apply_patch", patch_cmd, cwd=str(tmp_path))
        contexts = CodexHookAdapter().build_contexts(payload, "apply_patch", _make_manifest())
        assert len(contexts) == 1
        ctx = contexts[0]
        assert ctx.tool_name == "Edit"
        assert ctx.event == "PreToolUse.Edit"
        assert ctx.new_content == "    return 2"
        assert ctx.raw_diff is not None
        assert "-    return 1" in ctx.raw_diff

    def test_move_to_targets_post_op_path(self, tmp_path: Path) -> None:
        patch_cmd = _patch("*** Update File: src/old.py", "*** Move to: src/new.py", "+x = 1")
        payload = _payload("apply_patch", patch_cmd, cwd=str(tmp_path))
        contexts = CodexHookAdapter().build_contexts(payload, "apply_patch", _make_manifest())
        assert contexts[0].target_path == "src/new.py"
        assert contexts[0].tool_args["move_to"] == "src/new.py"

    def test_delete_only_patch_yields_no_contexts(self, tmp_path: Path) -> None:
        payload = _payload("apply_patch", _patch("*** Delete File: gone.txt"), cwd=str(tmp_path))
        assert CodexHookAdapter().build_contexts(payload, "apply_patch", _make_manifest()) == []

    def test_multi_file_patch_order_preserved(self, tmp_path: Path) -> None:
        patch_cmd = _patch(
            "*** Add File: tests/test_x.py",
            "+def test_x(): pass",
            "*** Update File: src/x.py",
            "+x = 1",
            "*** Delete File: old.txt",
        )
        payload = _payload("apply_patch", patch_cmd, cwd=str(tmp_path))
        contexts = CodexHookAdapter().build_contexts(payload, "apply_patch", _make_manifest())
        assert [(c.tool_name, c.target_path) for c in contexts] == [
            ("Write", "tests/test_x.py"),
            ("Edit", "src/x.py"),
        ]

    def test_absolute_path_relativized_against_payload_cwd(self, tmp_path: Path) -> None:
        patch_cmd = _patch(f"*** Add File: {tmp_path}/deep/file.py", "+x = 1")
        payload = _payload("apply_patch", patch_cmd, cwd=str(tmp_path))
        contexts = CodexHookAdapter().build_contexts(payload, "apply_patch", _make_manifest())
        assert contexts[0].target_path == "deep/file.py"

    def test_content_truncated_at_5000(self, tmp_path: Path) -> None:
        long_line = "x" * 5001
        payload = _payload("apply_patch", _patch("*** Add File: big.txt", f"+{long_line}"), cwd=str(tmp_path))
        contexts = CodexHookAdapter().build_contexts(payload, "apply_patch", _make_manifest())
        assert contexts[0].new_content is not None
        assert "truncated" in contexts[0].new_content

    def test_malformed_patch_yields_no_contexts(self, tmp_path: Path) -> None:
        payload = _payload("apply_patch", "not a patch at all", cwd=str(tmp_path))
        assert CodexHookAdapter().build_contexts(payload, "apply_patch", _make_manifest()) == []

    def test_non_dict_tool_input_yields_no_contexts(self, tmp_path: Path) -> None:
        payload = _payload("apply_patch", "ignored", cwd=str(tmp_path))
        payload["tool_input"] = "not a dict"
        assert CodexHookAdapter().build_contexts(payload, "apply_patch", _make_manifest()) == []

    def test_non_string_command_yields_no_contexts(self, tmp_path: Path) -> None:
        payload = _payload("apply_patch", "ignored", cwd=str(tmp_path))
        payload["tool_input"] = {"command": 42}
        assert CodexHookAdapter().build_contexts(payload, "apply_patch", _make_manifest()) == []


def _deny_result() -> CompositeDecision:
    return CompositeDecision(
        final_decision="deny",
        decisions=[
            PolicyDecision(
                decision="deny",
                policy_id="tdd",
                violations=[
                    Violation(
                        rule_id="tdd.tests-first",
                        message="write a test first",
                        severity="high",
                        suggested_fix="add a test",
                    )
                ],
                intent="enforce TDD",
            )
        ],
    )


def _review_result() -> CompositeDecision:
    return CompositeDecision(
        final_decision="needs_review",
        decisions=[PolicyDecision(decision="needs_review", policy_id="semantic.plan_check", intent="check the plan")],
    )


class TestCodexHookResponder:
    def test_deny_wire_matches_probe_pinned_shape(self) -> None:
        # Key set pinned by scripts/experiments/codex-hooks/responses/pretooluse-deny.json
        wire = json.loads(CodexHookResponder().format_deny(_deny_result()))
        assert set(wire.keys()) == {"hookSpecificOutput"}
        out = wire["hookSpecificOutput"]
        assert set(out.keys()) == {"hookEventName", "permissionDecision", "permissionDecisionReason"}
        assert out["hookEventName"] == "PreToolUse"
        assert out["permissionDecision"] == "deny"
        assert "[tdd.tests-first] write a test first" in out["permissionDecisionReason"]
        assert "Intent: enforce TDD" in out["permissionDecisionReason"]
        assert "Note: This policy was configured by the project owner." in out["permissionDecisionReason"]

    def test_deny_multi_prefixes_file_sections(self) -> None:
        wire = json.loads(
            CodexHookResponder().format_deny_multi([("src/a.py", _deny_result()), ("src/b.py", _deny_result())])
        )
        reason = wire["hookSpecificOutput"]["permissionDecisionReason"]
        assert "src/a.py:\nPolicy violation(s):" in reason
        assert "src/b.py:\nPolicy violation(s):" in reason

    def test_needs_review_wire_is_deny_shaped(self) -> None:
        wire = json.loads(CodexHookResponder().format_needs_review(_review_result()))
        out = wire["hookSpecificOutput"]
        assert out["permissionDecision"] == "deny"
        assert "Policy review required" in out["permissionDecisionReason"]
        assert "[semantic.plan_check] requested review" in out["permissionDecisionReason"]

    def test_allow_feedback_shape(self) -> None:
        out = CodexHookResponder().allow_feedback("ok")
        assert out == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "additionalContext": "ok",
            }
        }

    def test_exit_codes(self) -> None:
        # Codex deny rides in stdout JSON; both paths exit 0 (contrast Claude's 2).
        assert CodexHookResponder.BLOCK_EXIT == 0
        assert CodexHookResponder.ALLOW_EXIT == 0
