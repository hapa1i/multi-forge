"""Tests for the Codex apply_patch envelope parser (cli/hooks/codex_patch.py)."""

from __future__ import annotations

from forge.cli.hooks.codex_patch import PatchFileOp, parse_apply_patch

# Literal tool_input.command from tests/fixtures/codex/hooks/post_tool_use.stdin.json
# (codex-cli 0.138.0) -- the grammar witness.
FIXTURE_ADD = "*** Begin Patch\n*** Add File: probe.txt\n+PROBE-WR-1\n*** End Patch\n"


class TestParseAddFile:
    def test_fixture_literal_single_add(self) -> None:
        ops = parse_apply_patch(FIXTURE_ADD)
        assert ops is not None
        assert len(ops) == 1
        op = ops[0]
        assert op.kind == "add"
        assert op.path == "probe.txt"
        assert op.move_to is None
        assert op.added_content == "PROBE-WR-1"
        assert op.raw_section == "*** Add File: probe.txt\n+PROBE-WR-1"

    def test_multiline_add_content(self) -> None:
        cmd = "*** Begin Patch\n*** Add File: src/x.py\n+def f():\n+    return 1\n*** End Patch"
        ops = parse_apply_patch(cmd)
        assert ops is not None
        assert ops[0].added_content == "def f():\n    return 1"


class TestParseUpdateFile:
    def test_update_with_hunk_markers_and_mixed_lines(self) -> None:
        cmd = (
            "*** Begin Patch\n"
            "*** Update File: src/x.py\n"
            "@@ def f():\n"
            " context line\n"
            "-    return 1\n"
            "+    return 2\n"
            "*** End Patch"
        )
        ops = parse_apply_patch(cmd)
        assert ops is not None
        op = ops[0]
        assert op.kind == "update"
        assert op.path == "src/x.py"
        assert op.added_content == "    return 2"
        assert "@@ def f():" in op.raw_section
        assert "-    return 1" in op.raw_section

    def test_move_to_targets_new_path(self) -> None:
        cmd = "*** Begin Patch\n" "*** Update File: src/old.py\n" "*** Move to: src/new.py\n" "+x = 1\n" "*** End Patch"
        ops = parse_apply_patch(cmd)
        assert ops is not None
        op = ops[0]
        # path is the post-op location -- policies judge where content lands.
        assert op.path == "src/new.py"
        assert op.move_to == "src/new.py"
        assert "*** Update File: src/old.py" in op.raw_section

    def test_end_of_file_marker_tolerated(self) -> None:
        cmd = "*** Begin Patch\n*** Update File: a.txt\n+tail\n*** End of File\n*** End Patch"
        ops = parse_apply_patch(cmd)
        assert ops is not None
        assert ops[0].added_content == "tail"
        assert "*** End of File" in ops[0].raw_section

    def test_blank_line_in_body_is_context(self) -> None:
        cmd = "*** Begin Patch\n*** Update File: a.txt\n+one\n\n+two\n*** End Patch"
        ops = parse_apply_patch(cmd)
        assert ops is not None
        assert ops[0].added_content == "one\ntwo"


class TestParseDeleteFile:
    def test_delete_yields_bodyless_op(self) -> None:
        cmd = "*** Begin Patch\n*** Delete File: gone.txt\n*** End Patch"
        ops = parse_apply_patch(cmd)
        assert ops is not None
        assert ops == [
            PatchFileOp(
                kind="delete",
                path="gone.txt",
                move_to=None,
                added_content="",
                raw_section="*** Delete File: gone.txt",
            )
        ]

    def test_delete_with_body_is_malformed(self) -> None:
        cmd = "*** Begin Patch\n*** Delete File: gone.txt\n+stray\n*** End Patch"
        assert parse_apply_patch(cmd) is None


class TestMultiFile:
    def test_multi_file_order_preserved(self) -> None:
        cmd = (
            "*** Begin Patch\n"
            "*** Add File: tests/test_x.py\n"
            "+def test_x(): pass\n"
            "*** Update File: src/x.py\n"
            "+x = 1\n"
            "*** Delete File: old.txt\n"
            "*** End Patch"
        )
        ops = parse_apply_patch(cmd)
        assert ops is not None
        assert [(op.kind, op.path) for op in ops] == [
            ("add", "tests/test_x.py"),
            ("update", "src/x.py"),
            ("delete", "old.txt"),
        ]


class TestEnvelope:
    def test_empty_patch_is_valid_and_empty(self) -> None:
        assert parse_apply_patch("*** Begin Patch\n*** End Patch") == []

    def test_surrounding_blank_lines_tolerated(self) -> None:
        assert parse_apply_patch("\n\n" + FIXTURE_ADD + "\n") is not None

    def test_crlf_lines_tolerated(self) -> None:
        ops = parse_apply_patch(FIXTURE_ADD.replace("\n", "\r\n"))
        assert ops is not None
        assert ops[0].added_content == "PROBE-WR-1"


class TestMalformed:
    def test_missing_begin(self) -> None:
        assert parse_apply_patch("*** Add File: x\n+1\n*** End Patch") is None

    def test_missing_end(self) -> None:
        assert parse_apply_patch("*** Begin Patch\n*** Add File: x\n+1") is None

    def test_empty_string(self) -> None:
        assert parse_apply_patch("") is None

    def test_unknown_header_is_malformed(self) -> None:
        cmd = "*** Begin Patch\n*** Rename File: a -> b\n*** End Patch"
        assert parse_apply_patch(cmd) is None

    def test_body_line_before_any_header(self) -> None:
        assert parse_apply_patch("*** Begin Patch\n+stray\n*** End Patch") is None

    def test_unprefixed_body_line_is_malformed(self) -> None:
        cmd = "*** Begin Patch\n*** Add File: x\nno prefix\n*** End Patch"
        assert parse_apply_patch(cmd) is None

    def test_move_to_without_update_is_malformed(self) -> None:
        cmd = "*** Begin Patch\n*** Add File: x\n*** Move to: y\n*** End Patch"
        assert parse_apply_patch(cmd) is None

    def test_move_to_after_body_is_malformed(self) -> None:
        cmd = "*** Begin Patch\n*** Update File: x\n+1\n*** Move to: y\n*** End Patch"
        assert parse_apply_patch(cmd) is None

    def test_second_move_to_is_malformed(self) -> None:
        cmd = "*** Begin Patch\n*** Update File: x\n*** Move to: y\n*** Move to: z\n*** End Patch"
        assert parse_apply_patch(cmd) is None

    def test_empty_path_is_malformed(self) -> None:
        assert parse_apply_patch("*** Begin Patch\n*** Add File: \n+1\n*** End Patch") is None

    def test_eof_marker_outside_section_is_malformed(self) -> None:
        assert parse_apply_patch("*** Begin Patch\n*** End of File\n*** End Patch") is None

    def test_eof_marker_in_delete_is_malformed(self) -> None:
        cmd = "*** Begin Patch\n*** Delete File: x\n*** End of File\n*** End Patch"
        assert parse_apply_patch(cmd) is None
