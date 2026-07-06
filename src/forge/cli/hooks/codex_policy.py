"""Codex halves of the hook seam: payload -> ActionContexts, decision -> stdout JSON.

The Codex counterparts of ``ClaudeHookAdapter``/``ClaudeHookResponder`` (policy.py),
filling the runtime-neutral protocols in ``protocols.py``. Probe-pinned facts this
module encodes (codex_frontend Phase 1, codex-cli 0.138.0):

- Codex file writes arrive as ``tool_name="apply_patch"`` with the patch envelope in
  ``tool_input.command``; shell commands arrive as ``tool_name="Bash"``.
- Every Forge policy's ``applies_to`` gates on ``tool_name in ("Write", "Edit")``, so
  the adapter normalizes patch operations to those names (Add File -> Write,
  Update File -> Edit). The runtime truth stays in ``origin="codex"`` + ``tool_args``.
- Codex FAILS OPEN on malformed hook output, so the responder emits only
  ``json.dumps`` of literal dicts -- never hand-assembled wire strings.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from forge.cli.hooks.codex_patch import PatchFileOp, parse_apply_patch
from forge.cli.hooks.policy import format_deny_text, format_needs_review_text
from forge.policy.deterministic.base import tests_first_sort_key
from forge.policy.types import ActionContext, CompositeDecision

_MAX_CONTENT_CHARS = 5000  # same truncation convention as ClaudeHookAdapter


class CodexHookAdapter:
    """Normalize a Codex PreToolUse payload into ``ActionContext``s (origin="codex").

    Only ``apply_patch`` actions are evaluable (Codex's file-write tool); anything
    else -- including ``Bash`` -- yields ``[]`` so the hook command fails open, the
    same posture as Claude's hook skipping non-Write/Edit tools. A multi-file patch
    yields one context per non-delete file operation, in patch order; deletions are
    skipped (no policy evaluates them -- there is no introduced content).
    """

    ORIGIN = "codex"

    def build_contexts(self, payload: dict[str, Any], tool_name: str, manifest: Any) -> list[ActionContext]:
        """Build per-file ``ActionContext``s from a Codex PreToolUse payload ([] if unbuildable)."""
        if tool_name != "apply_patch":
            return []
        tool_input = payload.get("tool_input", {})
        if not isinstance(tool_input, dict):
            return []
        command = tool_input.get("command")
        if not isinstance(command, str):
            return []

        ops = parse_apply_patch(command)
        if ops is None:
            return []  # malformed patch: fail open, like Claude's unbuildable payload

        # Payload cwd is where Codex resolves apply_patch paths; the hook process's
        # own CWD is unpinned, so prefer the payload's.
        payload_cwd = payload.get("cwd")
        cwd = Path(payload_cwd) if isinstance(payload_cwd, str) and payload_cwd else Path(os.getcwd())
        cwd = cwd.resolve()

        return [self._context_for_op(op, cwd, manifest) for op in ops if op.kind != "delete"]

    def _context_for_op(self, op: PatchFileOp, cwd: Path, manifest: Any) -> ActionContext:
        # Normalize to the tool names every policy's applies_to expects.
        normalized_tool = "Write" if op.kind == "add" else "Edit"

        target_path = op.path
        try:
            p = Path(target_path)
            if p.is_absolute():
                target_path = str(p.relative_to(cwd))
        except (ValueError, RuntimeError):
            pass  # Keep as-is if can't make relative

        new_content: str | None = op.added_content
        if new_content and len(new_content) > _MAX_CONTENT_CHARS:
            new_content = new_content[:_MAX_CONTENT_CHARS] + "\n... (truncated)"

        # raw_diff only for updates: an Add's full content already is new_content,
        # while an update section genuinely is a diff (richer LLM-policy context).
        raw_diff = op.raw_section[:_MAX_CONTENT_CHARS] if op.kind == "update" else None

        return ActionContext(
            origin=self.ORIGIN,
            event=f"PreToolUse.{normalized_tool}",
            tool_name=normalized_tool,
            tool_args={
                "codex_tool_name": "apply_patch",
                "path": op.path,
                "move_to": op.move_to,
                "kind": op.kind,
            },
            repo_root=str(cwd),
            session_name=manifest.name,
            target_path=target_path,
            new_content=new_content or None,
            raw_diff=raw_diff,
        )


class CodexHookResponder:
    """Serialize a composed policy decision into Codex's PreToolUse wire contract.

    Codex blocks on a strict stdout JSON ``hookSpecificOutput`` with
    ``permissionDecision: "deny"`` and exits 0 (probe-pinned; the exit-2 form also
    blocks but the JSON form carries the reason in-band). Codex fails OPEN on
    malformed output, so every wire string is ``json.dumps`` of a literal dict.
    """

    BLOCK_EXIT = 0  # deny is stdout JSON, not an exit code (contrast Claude's 2)
    ALLOW_EXIT = 0

    def format_deny(self, result: CompositeDecision) -> str:
        """Render the deny wire JSON for a single composed decision."""
        return self.format_deny_multi([(None, result)])

    def format_needs_review(self, result: CompositeDecision) -> str:
        """Render the deny wire JSON for a single unresolved ``needs_review``."""
        return self.format_needs_review_multi([(None, result)])

    def format_deny_multi(self, file_results: list[tuple[str | None, CompositeDecision]]) -> str:
        """Render one deny wire JSON covering every denying file of a patch."""
        reason = self._join_sections(file_results, format_deny_text)
        return self._deny_wire(reason)

    def format_needs_review_multi(self, file_results: list[tuple[str | None, CompositeDecision]]) -> str:
        """Render one deny wire JSON for the unresolved-review files of a patch."""
        reason = self._join_sections(file_results, format_needs_review_text)
        return self._deny_wire(reason)

    def format_error_deny(self, reason: str) -> str:
        """Render the deny wire JSON for a fail-closed evaluation error (no decision)."""
        return self._deny_wire(reason)

    def allow_feedback(self, additional_context: str) -> dict[str, Any]:
        """Build the allow JSON (protocol conformance only).

        Not emitted in Phase 3: PreToolUse ``additionalContext`` delivery on allow is
        unprobed (only SessionStart's is confirmed), so the command allows silently.
        """
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "additionalContext": additional_context,
            }
        }

    @staticmethod
    def _deny_wire(reason: str) -> str:
        return json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )

    @staticmethod
    def _join_sections(
        file_results: list[tuple[str | None, CompositeDecision]],
        format_text: Callable[[CompositeDecision], str],
    ) -> str:
        sections = []
        for path, result in file_results:
            text = format_text(result)
            sections.append(f"{path}:\n{text}" if path else text)
        return "\n\n".join(sections)


def sort_contexts_tests_first(contexts: list[ActionContext]) -> list[ActionContext]:
    """Order contexts so tests/ paths evaluate before src/ paths.

    Optimistic ordering for TDD stateful evaluation: an atomic patch adding test +
    implementation together passes tests-before-impl (the test file populates
    ``tests_touched`` first). Uses ``is_under_directory`` -- the SAME nested-aware rule
    the TDD policy's ``applies_to`` gates on -- so a nested ``pkg/tests`` / ``pkg/src``
    layout is reordered too. A top-level-only prefix match would leave both nested files
    in one bucket and false-deny an impl-first atomic patch. ``sorted`` is stable, so
    patch order is preserved within each bucket.
    """

    return sorted(contexts, key=lambda ctx: tests_first_sort_key(ctx.target_path))
