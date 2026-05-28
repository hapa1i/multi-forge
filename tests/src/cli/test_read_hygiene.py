"""Tests for the read-hygiene PreToolUse hook."""

from __future__ import annotations

import json

from click.testing import CliRunner

from forge.cli.hooks.read_hygiene import (
    _is_skill_instruction_file,
    handle_read_hygiene,
)

# ---------------------------------------------------------------------------
# _is_skill_instruction_file — targeted matching
# ---------------------------------------------------------------------------


class TestIsSkillInstructionFile:
    def test_matches_code_instruction(self):
        assert _is_skill_instruction_file("/home/user/.claude/skills/review/resources/code.md")

    def test_matches_docs_default(self):
        assert _is_skill_instruction_file("/home/user/.claude/skills/understand/resources/docs.md")

    def test_matches_docs_openai(self):
        assert _is_skill_instruction_file(".claude/skills/understand/resources/docs-openai.md")

    def test_matches_code_gemini(self):
        assert _is_skill_instruction_file("src/skills/review/resources/code-gemini.md")

    def test_matches_code_anthropic(self):
        assert _is_skill_instruction_file("/abs/path/skills/review/resources/code-anthropic.md")

    def test_ignores_checklist(self):
        assert not _is_skill_instruction_file("/home/user/.claude/skills/qa/resources/checklist.md")

    def test_ignores_nested_checklist(self):
        assert not _is_skill_instruction_file("/home/user/.claude/skills/qa/resources/checklist/6-hook.md")

    def test_ignores_report_template(self):
        assert not _is_skill_instruction_file("/home/user/.claude/skills/qa/resources/report-template.md")

    def test_ignores_synthesis(self):
        assert not _is_skill_instruction_file("/home/user/.claude/skills/panel/resources/synthesis.md")

    def test_ignores_analyze_resource(self):
        assert not _is_skill_instruction_file("/home/user/.claude/skills/analyze/resources/thinkdeep.md")

    def test_ignores_debate_evaluation(self):
        assert not _is_skill_instruction_file("/home/user/.claude/skills/debate/resources/debate_evaluation.md")

    def test_ignores_nested_subdir_with_matching_basename(self):
        """Instruction files must be immediate children of resources/, not nested."""
        assert not _is_skill_instruction_file("/home/user/.claude/skills/qa/resources/subdir/code.md")

    def test_ignores_non_skill_path(self):
        assert not _is_skill_instruction_file("/project/src/forge/core/ops.py")

    def test_ignores_resources_not_under_skills(self):
        assert not _is_skill_instruction_file("/project/resources/config.yaml")


# ---------------------------------------------------------------------------
# handle_read_hygiene — main handler
# ---------------------------------------------------------------------------


def _make_payload(
    file_path: str,
    *,
    offset: int | None = None,
    limit: int | None = None,
    pages: str | None = None,
    event: str = "PreToolUse",
    tool: str = "Read",
) -> dict:
    tool_input: dict = {"file_path": file_path}
    if offset is not None:
        tool_input["offset"] = offset
    if limit is not None:
        tool_input["limit"] = limit
    if pages is not None:
        tool_input["pages"] = pages
    return {
        "hook_event_name": event,
        "tool_name": tool,
        "tool_input": tool_input,
    }


INSTRUCTION_PATH = "/home/user/.claude/skills/review/resources/code-openai.md"


class TestHandleReadHygiene:
    def test_strips_offset_limit(self):
        result = handle_read_hygiene(_make_payload(INSTRUCTION_PATH, offset=0, limit=2000))
        assert result is not None
        hook_output = result["hookSpecificOutput"]
        assert hook_output["hookEventName"] == "PreToolUse"
        assert hook_output["permissionDecision"] == "allow"
        assert "permissionDecisionReason" not in hook_output
        assert hook_output["updatedInput"] == {"file_path": INSTRUCTION_PATH}

    def test_strips_pages(self):
        path = "/home/user/.claude/skills/understand/resources/docs-gemini.md"
        result = handle_read_hygiene(_make_payload(path, pages="1"))
        assert result is not None
        assert result["hookSpecificOutput"]["updatedInput"] == {"file_path": path}

    def test_strips_all_extra_params(self):
        result = handle_read_hygiene(_make_payload(INSTRUCTION_PATH, offset=1, limit=4000, pages=""))
        assert result is not None
        assert result["hookSpecificOutput"]["updatedInput"] == {"file_path": INSTRUCTION_PATH}

    def test_passthrough_clean_call(self):
        assert handle_read_hygiene(_make_payload(INSTRUCTION_PATH)) is None

    def test_passthrough_non_skill_file(self):
        assert handle_read_hygiene(_make_payload("/project/README.md", offset=0)) is None

    def test_wrong_event(self):
        assert handle_read_hygiene(_make_payload(INSTRUCTION_PATH, offset=0, event="PostToolUse")) is None

    def test_wrong_tool_name(self):
        assert handle_read_hygiene(_make_payload(INSTRUCTION_PATH, offset=0, tool="Write")) is None

    def test_missing_tool_input(self):
        assert handle_read_hygiene({"hook_event_name": "PreToolUse", "tool_name": "Read"}) is None

    def test_missing_file_path(self):
        data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"offset": 0},
        }
        assert handle_read_hygiene(data) is None


# ---------------------------------------------------------------------------
# CLI runner tests
# ---------------------------------------------------------------------------


class TestReadHygieneCLI:
    def test_empty_stdin_exits_zero(self):
        import forge.cli.hooks.commands  # noqa: F401 — ensure @hooks.command decorators run
        from forge.cli.hooks._group import hooks

        runner = CliRunner()
        result = runner.invoke(hooks, ["read-hygiene"], input="")
        assert result.exit_code == 0

    def test_outputs_updated_input(self):
        import forge.cli.hooks.commands  # noqa: F401 — ensure @hooks.command decorators run
        from forge.cli.hooks._group import hooks

        payload = _make_payload(INSTRUCTION_PATH, offset=0, limit=2000)
        runner = CliRunner()
        result = runner.invoke(hooks, ["read-hygiene"], input=json.dumps(payload))
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["hookSpecificOutput"]["updatedInput"]["file_path"] == INSTRUCTION_PATH
        assert "offset" not in output["hookSpecificOutput"]["updatedInput"]


# ---------------------------------------------------------------------------
# Registration assertion
# ---------------------------------------------------------------------------


class TestReadHygieneRegistration:
    def test_registered_in_hook_config(self):
        from forge.cli.hooks.install import FORGE_HOOK_CONFIG

        pre_tool_use = FORGE_HOOK_CONFIG["hooks"]["PreToolUse"]
        read_entries = [e for e in pre_tool_use if e.get("matcher") == "Read"]
        assert len(read_entries) == 1, "Expected exactly one Read matcher in PreToolUse"
        commands = [h["command"] for h in read_entries[0]["hooks"]]
        assert any("forge hook read-hygiene" in cmd for cmd in commands)
