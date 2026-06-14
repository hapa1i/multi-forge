"""Regression: blocked hook actions must not persist collected policy state.

Bug (codex_frontend Phase 3 review, finding 1): both hook commands persisted
engine-collected policy state BEFORE checking whether the composed decision
blocks the action. A blocked action never lands -- Claude denies the Write/Edit,
Codex rejects the whole apply_patch (all-or-nothing) -- so persisting e.g. TDD
``tests_touched`` from it let a later impl-only action through tests-before-impl
even though no test ever landed.

Root cause: PolicyEngine.evaluate runs ALL policies without short-circuiting on
deny, so tests-before-impl records a test path even when a sibling policy
(tdd.no-skip-tests) denies the same action; the persist call then ran
unconditionally before the deny branch.

Affected: src/forge/cli/hooks/commands.py (policy_check, codex_policy_check),
src/forge/cli/hooks/policy.py (_persist_policy_state).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.hooks.commands import hooks
from forge.session import SessionStore, create_session_state
from forge.session.models import PolicyIntent

pytestmark = pytest.mark.regression


def _make_tdd_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SessionStore:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORGE_SESSION", "blocked-state-session")
    monkeypatch.setenv("FORGE_FORGE_ROOT", str(tmp_path))

    store = SessionStore(str(tmp_path), "blocked-state-session")
    manifest = create_session_state("blocked-state-session", worktree_path=str(tmp_path))
    manifest.forge_root = str(tmp_path)
    manifest.intent.policy = PolicyIntent(enabled=True, bundles=["tdd"])
    store.write(manifest)
    return store


def _codex_payload(patch_command: str, cwd: str) -> str:
    return json.dumps(
        {
            "session_id": "019eb075-fd3f-7381-9008-9ef8df491237",
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": patch_command},
            "cwd": cwd,
        }
    )


def _patch_cmd(*sections: str) -> str:
    return "*** Begin Patch\n" + "\n".join(sections) + "\n*** End Patch"


def _claude_payload(file_path: str, content: str) -> str:
    return json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": file_path, "content": content},
        }
    )


class TestCodexBlockedPatchState:
    def test_denied_patch_with_clean_test_file_does_not_mark_tests_touched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A clean test file riding in a denied patch never lands, so a follow-up
        impl-only patch must still deny (no tests actually touched)."""
        store = _make_tdd_session(tmp_path, monkeypatch)
        # File 1 is a clean test (allows, records tests_touched in-engine);
        # file 2 carries a skip marker (tdd.no-skip-tests denies). apply_patch is
        # all-or-nothing: the deny rejects BOTH files.
        blocked = _codex_payload(
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

        result = CliRunner().invoke(hooks, ["codex-policy-check"], input=blocked)
        assert result.exit_code == 0
        wire = json.loads(result.stdout)
        assert wire["hookSpecificOutput"]["permissionDecision"] == "deny"

        # Decision-log entries persist (audit trail) but policy state must not.
        manifest = store.read()
        assert manifest.confirmed.policy is not None
        assert len(manifest.confirmed.policy.decisions) == 2
        assert "tdd.tests-before-impl" not in manifest.confirmed.policy.policy_states

        # The bug let this through: impl-only follow-up must still deny.
        follow_up = _codex_payload(_patch_cmd("*** Add File: src/foo.py", "+x = 1"), cwd=str(tmp_path))
        result2 = CliRunner().invoke(hooks, ["codex-policy-check"], input=follow_up)
        assert result2.exit_code == 0
        wire2 = json.loads(result2.stdout)
        assert wire2["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "[tdd.tests-before-impl]" in wire2["hookSpecificOutput"]["permissionDecisionReason"]

    def test_allowed_patch_still_persists_state(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Control: the gate only drops state for blocked patches."""
        store = _make_tdd_session(tmp_path, monkeypatch)
        allowed = _codex_payload(
            _patch_cmd("*** Add File: tests/test_clean.py", "+def test_clean(): pass"),
            cwd=str(tmp_path),
        )

        result = CliRunner().invoke(hooks, ["codex-policy-check"], input=allowed)
        assert result.exit_code == 0
        assert result.stdout == ""

        manifest = store.read()
        assert manifest.confirmed.policy is not None
        tdd_state = manifest.confirmed.policy.policy_states["tdd.tests-before-impl"]
        assert "tests/test_clean.py" in tdd_state["tests_touched"]


class TestClaudeDeniedWriteState:
    def test_denied_test_write_does_not_mark_tests_touched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Single-action variant: a test Write denied by tdd.no-skip-tests never
        lands, yet tests-before-impl recorded it in the same evaluation. A later
        impl-only Write must still deny."""
        store = _make_tdd_session(tmp_path, monkeypatch)
        denied_test = _claude_payload(
            "tests/test_skipped.py",
            "import pytest\n@pytest.mark.skip\ndef test_s(): pass\n",
        )

        result = CliRunner().invoke(hooks, ["policy-check"], input=denied_test)
        assert result.exit_code == 2  # Claude deny wire: stderr + exit 2

        manifest = store.read()
        assert manifest.confirmed.policy is not None
        assert len(manifest.confirmed.policy.decisions) == 1
        assert "tdd.tests-before-impl" not in manifest.confirmed.policy.policy_states

        impl_only = _claude_payload("src/foo.py", "x = 1\n")
        result2 = CliRunner().invoke(hooks, ["policy-check"], input=impl_only)
        assert result2.exit_code == 2
        assert "[tdd.tests-before-impl]" in result2.stderr  # Claude deny text rides stderr

    def test_allowed_test_write_still_persists_state(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Control: a clean test Write persists tests_touched as before."""
        store = _make_tdd_session(tmp_path, monkeypatch)
        clean_test = _claude_payload("tests/test_clean.py", "def test_clean(): pass\n")

        result = CliRunner().invoke(hooks, ["policy-check"], input=clean_test)
        assert result.exit_code == 0

        manifest = store.read()
        assert manifest.confirmed.policy is not None
        tdd_state = manifest.confirmed.policy.policy_states["tdd.tests-before-impl"]
        assert "tests/test_clean.py" in tdd_state["tests_touched"]
