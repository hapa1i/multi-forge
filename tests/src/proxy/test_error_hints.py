"""Tests for error hint enrichment."""

from forge.proxy.error_hints import enrich_error_content


class TestEditHints:
    """Tests for Edit tool error hints."""

    def test_noop_edit_gets_hint(self):
        error = "No changes to make: old_string and new_string are exactly the same."
        result = enrich_error_content("Edit", error)
        assert result.startswith(error)
        assert "HINT:" in result
        assert "Read instead of Edit" in result

    def test_not_unique_match_gets_hint(self):
        error = "Found 2 matches of the string to replace, but replace_all is false."
        result = enrich_error_content("Edit", error)
        assert result.startswith(error)
        assert "HINT:" in result
        assert "replace_all=true" in result

    def test_unrelated_edit_error_no_hint(self):
        error = "Some other Edit error."
        result = enrich_error_content("Edit", error)
        assert result == error


class TestBashHints:
    """Tests for Bash tool error hints."""

    def test_ruff_f401_gets_hint(self):
        error = "Exit code 1\nF401 [*] `sys` imported but unused\n  --> src/utils.py:14:8\nFound 1 error."
        result = enrich_error_content("Bash", error)
        assert result.startswith(error)
        assert "HINT:" in result
        assert "unused import" in result

    def test_ruff_f811_gets_hint(self):
        error = "Exit code 1\nF811 [*] redefinition of unused `foo` from line 5\nFound 1 error."
        result = enrich_error_content("Bash", error)
        assert result.startswith(error)
        assert "HINT:" in result
        assert "duplicate definition" in result

    def test_unrelated_bash_error_no_hint(self):
        error = "Exit code 1\ncommand not found: foobar"
        result = enrich_error_content("Bash", error)
        assert result == error


class TestTaskOutputHints:
    """Tests for TaskOutput tool error hints."""

    def test_invalid_task_id_gets_hint(self):
        error = "No task found with ID: bd7517f.txt"
        result = enrich_error_content("TaskOutput", error)
        assert result.startswith(error)
        assert "HINT:" in result
        assert "file extensions" in result

    def test_unrelated_task_error_no_hint(self):
        error = "Task timed out after 30000ms"
        result = enrich_error_content("TaskOutput", error)
        assert result == error


class TestReadHints:
    """Tests for Read tool error hints."""

    def test_file_not_found_gets_hint(self):
        error = "File does not exist. Note: your current working directory is /foo/bar."
        result = enrich_error_content("Read", error)
        assert result.startswith(error)
        assert "HINT:" in result
        assert "Glob" in result


class TestEdgeCases:
    """Tests for edge cases and safeguards."""

    def test_none_tool_name_no_crash(self):
        error = "Some error"
        result = enrich_error_content(None, error)
        assert result == error

    def test_none_tool_name_fallback_edit_noop(self):
        """Edit no-op pattern matches even when tool_name is None (fallback rule)."""
        error = "No changes to make: old_string and new_string are exactly the same."
        result = enrich_error_content(None, error)
        assert "HINT:" in result
        assert "Read instead of Edit" in result

    def test_none_tool_name_fallback_task_id(self):
        """TaskOutput bad ID pattern matches even when tool_name is None (fallback rule)."""
        error = "No task found with ID: bd7517f.txt"
        result = enrich_error_content(None, error)
        assert "HINT:" in result
        assert "file extensions" in result

    def test_empty_error_content(self):
        result = enrich_error_content("Edit", "")
        assert result == ""

    def test_no_double_append(self):
        """If HINT: is already present, don't append another."""
        error = "old_string and new_string are exactly the same.\n\nHINT: Already enriched."
        result = enrich_error_content("Edit", error)
        assert result == error
        assert result.count("HINT:") == 1

    def test_wrong_tool_no_match(self):
        """Edit-specific pattern should not match for Bash tool (fallback catches it)."""
        error = "No changes to make: old_string and new_string are exactly the same."
        result = enrich_error_content("Bash", error)
        # Fallback rule with tool_name=None still matches
        assert "HINT:" in result

    def test_bare_hint_in_error_does_not_block(self):
        """Bare 'HINT:' in error content should NOT block enrichment (only exact prefix does)."""
        error = "Exit code 1\nF401 [*] `sys` imported but unused\nHINT: use --fix"
        result = enrich_error_content("Bash", error)
        assert result != error
        assert "Remove the unused import" in result

    def test_passthrough_on_no_match(self):
        """Completely unknown error passes through unchanged."""
        error = "Something totally unexpected happened."
        result = enrich_error_content("UnknownTool", error)
        assert result == error
