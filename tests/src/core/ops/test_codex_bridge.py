"""Tests for the Claude->Codex bridge (Slice 5e).

The bridge composes shipped Phase 5 parts (curated transfer + ``CodexHeadlessInvoker``) into
the "plan in Claude -> implement in Codex" hop. These tests are hermetic: the curation LLM and
the ``codex exec`` subprocess are both mocked, and the autouse ``isolate_forge_home`` gives a
clean usage ledger so the run-tree join can be asserted. The real-codex stack is covered in
``tests/integration/core/test_claude_to_codex_resume.py``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from forge.core.ops.codex_bridge import (
    CodexBridgeResult,
    _temporary_run_env,
    bridge_session_to_codex,
    compose_codex_handoff_context,
    compose_codex_initial_message,
    compose_codex_interactive_context,
)
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import ForgeOpError
from forge.core.reactive.env import RunIdentity
from forge.core.runtime.codex_preflight import CodexPreflight
from forge.core.usage.ledger import read_usage_events
from forge.session.models import SessionState, create_session_state
from forge.session.transfer import parse_transfer_frontmatter

_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "codex"
_SUCCESS_STREAM = (_FIXTURES / "exec_json_success.jsonl").read_text()

_CURATED = {
    "goal": "Ship the cross-runtime bridge",
    "decisions": [{"text": "Curated transfer is the only cross-runtime substrate", "citation": "turn 1"}],
    "current_state": "Bridge wired; demo pending",
    "files": ["src/forge/core/ops/codex_bridge.py"],
    "open_questions": ["Sandbox default?"],
}


def _preflight() -> CodexPreflight:
    """A ready ``codex_store`` preflight -- ``prepare_codex_request`` injects no key for it."""
    return CodexPreflight(
        installed=True,
        version="0.137.0",
        version_ok=True,
        auth_method="chatgpt_tokens",
        auth_source="codex_store",
        billing_mode="subscription_quota",
        ready=True,
        blocking_reason=None,
        hook_seam="unknown",
        proxy_responses="native_direct",
        doctor_status="ok",
    )


def _mock_codex_proc(stdout: str = _SUCCESS_STREAM) -> MagicMock:
    proc = MagicMock()
    proc.communicate.return_value = (stdout, "")
    proc.returncode = 0
    proc.poll.return_value = 0
    proc.pid = 4242
    proc.wait.return_value = 0
    return proc


def _fake_completion(text: str) -> Any:
    return SimpleNamespace(text=text, usage={"prompt_tokens": 200, "completion_tokens": 40})


def _write_transcript(path: Path) -> None:
    lines = [
        json.dumps(
            {
                "requestId": "r1",
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {"role": "user", "content": [{"type": "text", "text": "Plan the bridge."}]},
            }
        ),
        json.dumps(
            {
                "requestId": "r1",
                "timestamp": "2026-01-01T00:00:01Z",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "Curated transfer is it."}]},
            }
        ),
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _planner_state(tmp_path: Path, transcript: Path) -> SessionState:
    state = create_session_state(name="planner", worktree_path=str(tmp_path))
    state.confirmed.transcript_path = str(transcript)
    return state


def _ctx(tmp_path: Path, *, forge_root: Path | None) -> ExecutionContext:
    return ExecutionContext(cwd=tmp_path, worktree_root=tmp_path, project_root=tmp_path, forge_root=forge_root)


# --- compose_codex_initial_message ------------------------------------------------------


# The default delivery path's exact bytes: hook-mode staging (Phase 4) reuses the framing
# half, so this golden pins that the split refactor never changes the initial message.
_GOLDEN_INITIAL_MESSAGE = (
    "# Handoff context (curated transfer from a prior planning session)\n"
    "\n"
    "The section below is curated context -- decisions, current state, relevant files, and\n"
    "open questions -- distilled from a planning session in another agent runtime. Reasoning\n"
    "state does not transfer across runtimes, so treat this as your authoritative context.\n"
    "\n"
    "CURATED-BODY\n"
    "\n"
    "# Your task\n"
    "\n"
    "TASK-TEXT\n"
)


class TestComposeInitialMessage:
    def test_body_precedes_task_with_codex_framing(self) -> None:
        msg = compose_codex_initial_message("CURATED-BODY", "TASK-TEXT")
        assert "# Handoff context" in msg
        assert "# Your task" in msg
        assert msg.index("CURATED-BODY") < msg.index("TASK-TEXT")
        # No leftover transfer frontmatter delimiter leaks into the prompt.
        assert not msg.lstrip().startswith("---")

    def test_strips_surrounding_whitespace(self) -> None:
        msg = compose_codex_initial_message("  body  ", "  task  ")
        assert "body" in msg and "task" in msg

    def test_initial_message_bytes_pinned(self) -> None:
        assert compose_codex_initial_message("CURATED-BODY", "TASK-TEXT") == _GOLDEN_INITIAL_MESSAGE

    def test_handoff_context_plus_task_equals_initial_message(self) -> None:
        body, task = "CURATED-BODY", "TASK-TEXT"
        expected = compose_codex_handoff_context(body) + "\n# Your task\n\n" + f"{task.strip()}\n"
        assert compose_codex_initial_message(body, task) == expected


class TestComposeInteractiveContext:
    """Phase 5: the TUI positional prompt starts a model turn, so the framing must hold it."""

    def test_framed_body_with_hold_instructions(self) -> None:
        msg = compose_codex_interactive_context("CURATED-BODY")
        assert msg.startswith(compose_codex_handoff_context("CURATED-BODY"))
        assert "# Hold for instructions" in msg
        assert "WAIT for the user's instruction" in msg
        assert "# Your task" not in msg  # no task suffix -- the human types in the TUI

    def test_headless_compose_functions_unchanged(self) -> None:
        # The interactive variant must not perturb the golden-pinned headless framing.
        assert compose_codex_initial_message("CURATED-BODY", "TASK-TEXT") == _GOLDEN_INITIAL_MESSAGE


# --- _temporary_run_env -----------------------------------------------------------------


class TestTemporaryRunEnv:
    def test_sets_scrubs_parent_then_restores_prior_absence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FORGE_RUN_ID", raising=False)
        monkeypatch.delenv("FORGE_ROOT_RUN_ID", raising=False)
        monkeypatch.setenv("FORGE_PARENT_RUN_ID", "stale_parent")
        monkeypatch.delenv("FORGE_SESSION", raising=False)

        ident = RunIdentity(run_id="run_x", parent_run_id=None, root_run_id="run_x")
        with _temporary_run_env(ident, "sess"):
            assert os.environ["FORGE_RUN_ID"] == "run_x"
            assert os.environ["FORGE_ROOT_RUN_ID"] == "run_x"
            assert os.environ["FORGE_SESSION"] == "sess"
            assert "FORGE_PARENT_RUN_ID" not in os.environ  # scrubbed -- a fresh root has no parent

        # Restored exactly: absent run ids stay absent, the stale parent is put back, no session.
        assert "FORGE_RUN_ID" not in os.environ
        assert "FORGE_ROOT_RUN_ID" not in os.environ
        assert os.environ["FORGE_PARENT_RUN_ID"] == "stale_parent"
        assert "FORGE_SESSION" not in os.environ

    def test_restores_pre_existing_values_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORGE_RUN_ID", "outer")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "outer_root")

        ident = RunIdentity(run_id="inner", parent_run_id=None, root_run_id="inner")
        with pytest.raises(RuntimeError):
            with _temporary_run_env(ident, "sess"):
                assert os.environ["FORGE_RUN_ID"] == "inner"
                raise RuntimeError("boom")

        # Nested pre-existing values restored even though the block raised.
        assert os.environ["FORGE_RUN_ID"] == "outer"
        assert os.environ["FORGE_ROOT_RUN_ID"] == "outer_root"

    def test_forge_root_set_and_restored_to_absence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FORGE_FORGE_ROOT", raising=False)
        ident = RunIdentity(run_id="run_x", parent_run_id=None, root_run_id="run_x")
        with _temporary_run_env(ident, "sess", forge_root="/child/root"):
            assert os.environ["FORGE_FORGE_ROOT"] == "/child/root"
        assert "FORGE_FORGE_ROOT" not in os.environ

    def test_forge_root_restores_pre_existing_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORGE_FORGE_ROOT", "/outer/root")
        ident = RunIdentity(run_id="run_x", parent_run_id=None, root_run_id="run_x")
        with _temporary_run_env(ident, "sess", forge_root="/child/root"):
            assert os.environ["FORGE_FORGE_ROOT"] == "/child/root"
        assert os.environ["FORGE_FORGE_ROOT"] == "/outer/root"

    def test_forge_root_omitted_leaves_env_untouched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORGE_FORGE_ROOT", "/outer/root")
        ident = RunIdentity(run_id="run_x", parent_run_id=None, root_run_id="run_x")
        with _temporary_run_env(ident, "sess"):
            assert os.environ["FORGE_FORGE_ROOT"] == "/outer/root"
        assert os.environ["FORGE_FORGE_ROOT"] == "/outer/root"

    def test_overlapping_use_raises_and_guard_releases(self) -> None:
        """os.environ is process-global: overlapping bridge runs must fail loudly (never
        silently cross-attribute), and the guard must release on both normal exit and
        exception so sequential runs keep working."""
        ident = RunIdentity(run_id="run_x", parent_run_id=None, root_run_id="run_x")

        with _temporary_run_env(ident, "sess"):
            with pytest.raises(RuntimeError, match="already active"):
                with _temporary_run_env(ident, "sess"):
                    pass  # pragma: no cover -- entry must raise

        # Released on normal exit: a sequential run works.
        with _temporary_run_env(ident, "sess"):
            pass

        # Released after an exception inside the block, too.
        with pytest.raises(ValueError):
            with _temporary_run_env(ident, "sess"):
                raise ValueError("boom")
        with _temporary_run_env(ident, "sess"):
            pass


# --- bridge_session_to_codex ------------------------------------------------------------


class TestBridgeSessionToCodex:
    @pytest.mark.parametrize("strategy", ["bogus", "rewind"])
    def test_unknown_strategy_raises(self, tmp_path: Path, strategy: str) -> None:
        with pytest.raises(ForgeOpError, match="Unknown strategy"):
            bridge_session_to_codex(
                ctx=_ctx(tmp_path, forge_root=tmp_path),
                parent="planner",
                task="t",
                cwd=str(tmp_path),
                strategy=strategy,
            )

    def test_no_forge_root_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ForgeOpError, match="Forge project"):
            bridge_session_to_codex(ctx=_ctx(tmp_path, forge_root=None), parent="planner", task="t", cwd=str(tmp_path))

    def test_bridge_runs_codex_with_curated_transfer_under_one_run_tree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FORGE_RUN_ID", raising=False)
        monkeypatch.delenv("FORGE_ROOT_RUN_ID", raising=False)

        transcript = tmp_path / "transcript.jsonl"
        _write_transcript(transcript)
        state = _planner_state(tmp_path, transcript)

        manager = MagicMock()
        manager.get_session.return_value = state
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = _fake_completion(json.dumps(_CURATED))

        with (
            patch("forge.core.ops.codex_bridge.SessionManager", return_value=manager),
            patch("forge.core.ops.codex_bridge.assert_codex_ready", return_value=_preflight()),
            patch("forge.core.llm.SyncAdapter", return_value=mock_adapter),
            patch("forge.core.llm.get_client"),
            patch("forge.core.invoker._lifecycle.subprocess.Popen", return_value=_mock_codex_proc()) as mock_popen,
        ):
            result = bridge_session_to_codex(
                ctx=_ctx(tmp_path, forge_root=tmp_path),
                parent="planner",
                task="Implement the parser",
                cwd=str(tmp_path),
                strategy="ai-curated",
            )

        # Codex ran and completed the handed-off task.
        assert isinstance(result, CodexBridgeResult)
        assert result.codex.success
        assert result.codex.stdout == "OK"
        assert result.curation_ran is True

        # Per-run unique child key (a fixed name would re-feed Codex a stale snapshot).
        assert result.child.startswith("planner-codex-")
        assert result.child.endswith(result.root_run_id[-6:])

        # The transfer fed to Codex is Codex-targeted.
        frontmatter, body, _ = parse_transfer_frontmatter(result.transfer_path.read_text(encoding="utf-8"))
        assert frontmatter is not None
        assert frontmatter["target_runtime"] == "codex"
        assert "## Runtime Hints" in body
        assert "codex exec" in body

        # The composed initial message prepended the transfer body before the task.
        codex_input = mock_popen.return_value.communicate.call_args.kwargs["input"]
        assert "# Handoff context" in codex_input
        assert codex_input.index("Implement the parser") > codex_input.index("# Handoff context")

        # Both sides under one run tree, same session (default = parent name).
        events = read_usage_events(root_run_id=result.root_run_id)
        by_route = {e.route: e for e in events}
        assert set(by_route) == {"core_llm", "codex_exec"}
        assert by_route["core_llm"].command == "transfer-curate"
        assert by_route["core_llm"].runtime == "forge_cli"
        assert by_route["codex_exec"].command == "codex-bridge"
        assert {e.session for e in events} == {"planner"}

        # The bridge is a transient root: os.environ run identity was restored after.
        assert "FORGE_RUN_ID" not in os.environ
        assert "FORGE_ROOT_RUN_ID" not in os.environ

        # The seed thread_id from the fixture stream surfaces on the result (Phase 2).
        assert result.thread_id == "019eaa51-6920-7c41-ae34-d4f7f368d55a"


def _run_bridge(tmp_path: Path, **bridge_kwargs: Any) -> tuple[CodexBridgeResult, MagicMock]:
    """Run the bridge with the standard hermetic mocks; return (result, assert_ready mock)."""
    transcript = tmp_path / "transcript.jsonl"
    _write_transcript(transcript)
    state = _planner_state(tmp_path, transcript)

    manager = MagicMock()
    manager.get_session.return_value = state
    mock_adapter = MagicMock()
    mock_adapter.complete.return_value = _fake_completion(json.dumps(_CURATED))

    with (
        patch("forge.core.ops.codex_bridge.SessionManager", return_value=manager),
        patch("forge.core.ops.codex_bridge.assert_codex_ready", return_value=_preflight()) as mock_ready,
        patch("forge.core.llm.SyncAdapter", return_value=mock_adapter),
        patch("forge.core.llm.get_client"),
        patch("forge.core.invoker._lifecycle.subprocess.Popen", return_value=_mock_codex_proc()),
    ):
        result = bridge_session_to_codex(
            ctx=_ctx(tmp_path, forge_root=tmp_path),
            parent="planner",
            task="Implement the parser",
            cwd=str(tmp_path),
            strategy="ai-curated",
            **bridge_kwargs,
        )
    return result, mock_ready


class TestBridgeHookDelivery:
    """Phase 4 staging param: hook mode stages the framed body; default is byte-identical."""

    def _run(self, tmp_path: Path, **bridge_kwargs: Any) -> tuple[CodexBridgeResult, dict[str, Any]]:
        """Like _run_bridge, but the Popen mock snapshots staging state + env at spawn time."""
        transcript = tmp_path / "transcript.jsonl"
        _write_transcript(transcript)
        state = _planner_state(tmp_path, transcript)

        manager = MagicMock()
        manager.get_session.return_value = state
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = _fake_completion(json.dumps(_CURATED))

        staged_path = bridge_kwargs.get("staged_context_path")
        spawn_snapshot: dict[str, Any] = {}

        def _popen(*args: Any, **kwargs: Any) -> MagicMock:
            # The hook fires DURING the codex turn, so the staged file must exist (with
            # final content) by the time the child process is spawned.
            if staged_path is not None:
                spawn_snapshot["staged_exists"] = staged_path.exists()
                spawn_snapshot["staged_content"] = staged_path.read_text() if staged_path.exists() else None
            spawn_snapshot["env"] = dict(kwargs["env"])
            proc = _mock_codex_proc()
            spawn_snapshot["proc"] = proc
            return proc

        with (
            patch("forge.core.ops.codex_bridge.SessionManager", return_value=manager),
            patch("forge.core.ops.codex_bridge.assert_codex_ready", return_value=_preflight()),
            patch("forge.core.llm.SyncAdapter", return_value=mock_adapter),
            patch("forge.core.llm.get_client"),
            patch("forge.core.invoker._lifecycle.subprocess.Popen", side_effect=_popen),
        ):
            result = bridge_session_to_codex(
                ctx=_ctx(tmp_path, forge_root=tmp_path),
                parent="planner",
                task="Implement the parser",
                cwd=str(tmp_path),
                strategy="ai-curated",
                **bridge_kwargs,
            )
        return result, spawn_snapshot

    def test_hook_mode_stages_framed_body_and_sends_raw_task(self, tmp_path: Path) -> None:
        staged = tmp_path / "sessions" / "impl" / "codex" / "pending-context.md"
        result, snapshot = self._run(tmp_path, staged_context_path=staged, child="impl")

        assert result.codex.success
        # Staged at Popen time with the framed transfer body (no task section).
        assert snapshot["staged_exists"] is True
        staged_content = snapshot["staged_content"]
        assert staged_content.startswith("# Handoff context")
        assert "# Your task" not in staged_content
        assert "Implement the parser" not in staged_content
        # The staged content is exactly the framing of the composed child body.
        composed_body = parse_transfer_frontmatter(result.transfer_path.read_text(encoding="utf-8"))[1]
        assert staged_content == compose_codex_handoff_context(composed_body)
        # The prompt carries ONLY the raw task; the hook env can root the session store.
        assert snapshot["proc"].communicate.call_args.kwargs["input"] == "Implement the parser"
        assert snapshot["env"]["FORGE_FORGE_ROOT"] == str(tmp_path)

    def test_default_mode_stages_nothing_and_prompt_unchanged(self, tmp_path: Path) -> None:
        result, snapshot = self._run(tmp_path)
        assert result.codex.success
        assert list(tmp_path.glob("**/pending-context.md")) == []
        # Default prompt is the full composed initial message (golden-pinned shape).
        codex_input = snapshot["proc"].communicate.call_args.kwargs["input"]
        assert codex_input.startswith("# Handoff context")
        assert codex_input.rstrip().endswith("Implement the parser")
        assert snapshot["env"]["FORGE_FORGE_ROOT"] == str(tmp_path)


class TestBridgePhase2Extensions:
    """Phase 2 bridge params: explicit child key, provided preflight, output_root."""

    def test_explicit_child_key_honored(self, tmp_path: Path) -> None:
        result, _ = _run_bridge(tmp_path, child="impl")
        assert result.child == "impl"
        snapshot = tmp_path / ".forge" / "prev_sessions" / "planner" / "children" / "impl.md"
        assert snapshot.is_file()
        assert result.transfer_path == snapshot

    def test_provided_preflight_short_circuits_assert(self, tmp_path: Path) -> None:
        _, mock_ready = _run_bridge(tmp_path, preflight=_preflight())
        mock_ready.assert_not_called()

    def test_output_root_places_snapshot_under_child_root(self, tmp_path: Path) -> None:
        child_root = tmp_path / "wt"
        child_root.mkdir()
        result, _ = _run_bridge(tmp_path, child="impl", output_root=child_root)
        snapshot = child_root / ".forge" / "prev_sessions" / "planner" / "children" / "impl.md"
        assert snapshot.is_file()
        assert result.transfer_path == snapshot
        # Nothing was written under the invocation root.
        assert not (tmp_path / ".forge" / "prev_sessions" / "planner" / "children" / "impl.md").exists()
