"""Tests for override manipulation operations."""

from __future__ import annotations

import pytest

from forge.session.exceptions import InvalidOverrideKeyError
from forge.session.overrides import (
    clear_overrides,
    delete_override,
    expand_wildcard,
    get_valid_intent_paths,
    parse_value,
    set_override,
    validate_key,
)


class TestGetValidIntentPaths:
    """Test get_valid_intent_paths() function."""

    def test_returns_set_of_strings(self) -> None:
        """get_valid_intent_paths returns a set of strings."""
        paths = get_valid_intent_paths()
        assert isinstance(paths, set)
        assert all(isinstance(p, str) for p in paths)

    def test_includes_top_level_fields(self) -> None:
        """Top-level SessionIntent fields are included."""
        paths = get_valid_intent_paths()
        # Check known top-level fields
        assert "agent" in paths
        assert "proxy" in paths
        assert "launch" in paths
        assert "memory" in paths
        assert "system_prompt" in paths
        assert "policy" in paths
        assert "llm" not in paths

    def test_includes_nested_fields(self) -> None:
        """Nested fields are included with dot notation."""
        paths = get_valid_intent_paths()
        assert "proxy.template" in paths
        assert "proxy.base_url" in paths
        assert "launch.mode" in paths
        assert "launch.sidecar.mounts" in paths
        assert "memory.auto_recall" in paths
        assert "memory.tags" in paths

    def test_cached_results(self) -> None:
        """Results are cached (same object returned)."""
        paths1 = get_valid_intent_paths()
        paths2 = get_valid_intent_paths()
        assert paths1 is paths2


class TestValidateKey:
    """Test validate_key() function for strict schema validation."""

    def test_valid_top_level_key(self) -> None:
        """Valid top-level keys pass validation."""
        assert validate_key("agent") == ["agent"]
        assert validate_key("proxy") == ["proxy"]

    def test_valid_nested_key(self) -> None:
        """Valid nested keys pass validation."""
        assert validate_key("proxy.template") == ["proxy", "template"]
        assert validate_key("proxy.base_url") == ["proxy", "base_url"]
        assert validate_key("launch.mode") == ["launch", "mode"]
        assert validate_key("memory.auto_recall") == ["memory", "auto_recall"]

    def test_custom_namespace_is_rejected(self) -> None:
        """custom.* namespace is not supported."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            validate_key("custom.my_flag")
        assert "custom.* is not supported" in str(exc_info.value)

    def test_empty_key_raises(self) -> None:
        """Empty key raises InvalidOverrideKeyError."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            validate_key("")
        assert "cannot be empty" in str(exc_info.value)

    def test_empty_segment_raises(self) -> None:
        """Empty segment in path raises InvalidOverrideKeyError."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            validate_key("proxy..family")
        assert "empty segment" in str(exc_info.value)

    def test_leading_dot_raises(self) -> None:
        """Leading dot raises InvalidOverrideKeyError."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            validate_key(".proxy")
        assert "empty segment" in str(exc_info.value)

    def test_trailing_dot_raises(self) -> None:
        """Trailing dot raises InvalidOverrideKeyError."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            validate_key("proxy.")
        assert "empty segment" in str(exc_info.value)

    def test_intent_prefix_rejected(self) -> None:
        """Keys with intent.* prefix are rejected."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            validate_key("intent.agent")
        assert "relative to intent" in str(exc_info.value)

    def test_confirmed_prefix_rejected(self) -> None:
        """Keys with confirmed.* prefix are rejected."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            validate_key("confirmed.claude_session_id")
        assert "cannot override confirmed" in str(exc_info.value)

    def test_manifest_fields_rejected(self) -> None:
        """Top-level manifest fields are rejected."""
        manifest_fields = [
            "schema_version",
            "name",
            "created_at",
            "last_accessed_at",
            "parent_session",
            "is_fork",
            "is_incognito",
            "worktree",
        ]
        for field in manifest_fields:
            with pytest.raises(InvalidOverrideKeyError) as exc_info:
                validate_key(field)
            assert "manifest field" in str(exc_info.value)

    def test_unknown_key_rejected(self) -> None:
        """Unknown keys are rejected."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            validate_key("nonexistent_field")
        assert "unknown field" in str(exc_info.value)

    def test_launch_runtime_rejected_as_immutable(self) -> None:
        """launch.runtime is immutable launch identity (dispatch reads raw intent)."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            validate_key("launch.runtime")
        assert "immutable launch identity" in str(exc_info.value)
        assert "--runtime" in str(exc_info.value)

    def test_other_launch_keys_still_valid(self) -> None:
        """Only launch.runtime is blocked; sibling launch keys keep working."""
        assert validate_key("launch.mode") == ["launch", "mode"]

    @pytest.mark.parametrize(
        "key",
        [
            "consumer_lanes",
            "consumer_lanes.supervisor",
            "consumer_lanes.supervisor.runtime_id",
        ],
    )
    def test_consumer_lanes_rejected_as_command_only(self, key: str) -> None:
        """consumer_lanes.* is set only via resolving commands, never a raw override (T1b).

        The whole subtree is blocked -- a partial leaf can't rehydrate a 3-field LaneRecord, and a
        full-object override would bypass the runtime->LaneRecord expansion + already-bound reject and,
        after first dispatch, become recorded-but-ignored (dispatch reads the frozen confirmed binding).
        """
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            validate_key(key)
        assert "set via resolving commands" in str(exc_info.value)
        assert "--supervisor-runtime" in str(exc_info.value)

    def test_unknown_nested_key_rejected(self) -> None:
        """Unknown nested keys are rejected."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            validate_key("proxy.nonexistent")
        assert "unknown field" in str(exc_info.value)

    def test_wildcard_raises_use_expand(self) -> None:
        """Wildcards in validate_key raise error directing to expand_wildcard."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            validate_key("proxy.*")
        assert "expand_wildcard" in str(exc_info.value)

    def test_error_provides_hint(self) -> None:
        """Error includes helpful hint."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            validate_key("agen")  # Close to agent
        assert exc_info.value.hint is not None


class TestExpandWildcard:
    """Test expand_wildcard() function."""

    def test_proxy_wildcard(self) -> None:
        """proxy.* expands to proxy nested fields."""
        paths = expand_wildcard("proxy.*")
        assert "proxy.template" in paths
        assert "proxy.base_url" in paths
        assert len(paths) >= 2

    def test_memory_wildcard(self) -> None:
        """memory.* expands to memory nested fields."""
        paths = expand_wildcard("memory.*")
        assert "memory.auto_recall" in paths
        assert "memory.tags" in paths

    def test_launch_wildcard(self) -> None:
        """launch.* expands to launch nested fields."""
        paths = expand_wildcard("launch.*")
        assert "launch.mode" in paths
        assert "launch.sidecar" in paths

    def test_system_prompt_wildcard(self) -> None:
        """system_prompt.* expands to system_prompt nested fields."""
        paths = expand_wildcard("system_prompt.*")
        assert "system_prompt.mode" in paths
        assert "system_prompt.file" in paths

    def test_llm_wildcard_is_unknown(self) -> None:
        """llm.* is unknown and should fail."""
        with pytest.raises(InvalidOverrideKeyError):
            expand_wildcard("llm.*")

    def test_non_wildcard_raises(self) -> None:
        """Non-wildcard pattern raises error."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            expand_wildcard("proxy.template")
        assert "not a wildcard" in str(exc_info.value)

    def test_custom_wildcard_raises(self) -> None:
        """custom.* raises error (custom namespace not supported)."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            expand_wildcard("custom.*")
        assert "custom.* is not supported" in str(exc_info.value)

    def test_unsupported_wildcard_format(self) -> None:
        """Complex wildcard patterns are rejected."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            expand_wildcard("*.family")
        assert "unsupported wildcard format" in str(exc_info.value)

    def test_unknown_prefix_raises(self) -> None:
        """Unknown prefix raises error."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            expand_wildcard("nonexistent.*")
        assert "unknown field" in str(exc_info.value)

    def test_no_nested_fields_raises(self) -> None:
        """Wildcard on field with no nested fields raises error."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            expand_wildcard("agent.*")
        assert "no nested fields" in str(exc_info.value)


class TestParseValue:
    """Test parse_value() function for JSON-first parsing."""

    def test_true_becomes_bool(self) -> None:
        """JSON 'true' becomes Python True."""
        assert parse_value("true") is True

    def test_false_becomes_bool(self) -> None:
        """JSON 'false' becomes Python False."""
        assert parse_value("false") is False

    def test_null_becomes_none(self) -> None:
        """JSON 'null' becomes Python None."""
        assert parse_value("null") is None

    def test_integer(self) -> None:
        """Integer strings become ints."""
        assert parse_value("123") == 123
        assert parse_value("-42") == -42
        assert parse_value("0") == 0

    def test_float(self) -> None:
        """Float strings become floats."""
        assert parse_value("3.14") == 3.14
        assert parse_value("-2.5") == -2.5

    def test_list(self) -> None:
        """JSON array strings become lists."""
        assert parse_value('["a", "b", "c"]') == ["a", "b", "c"]
        assert parse_value("[1, 2, 3]") == [1, 2, 3]

    def test_object(self) -> None:
        """JSON object strings become dicts."""
        assert parse_value('{"key": "value"}') == {"key": "value"}
        assert parse_value('{"enabled": true, "level": 2}') == {
            "enabled": True,
            "level": 2,
        }

    def test_fallback_to_string(self) -> None:
        """Non-JSON values become strings."""
        assert parse_value("hello") == "hello"
        assert parse_value("some text") == "some text"

    def test_quoted_string_stays_string(self) -> None:
        """JSON quoted strings stay as strings."""
        # To force string "true", use JSON string: '"true"'
        assert parse_value('"true"') == "true"
        assert parse_value('"123"') == "123"

    def test_empty_string_stays_string(self) -> None:
        """Empty string stays as empty string."""
        assert parse_value("") == ""


class TestSetOverride:
    """Test set_override() function."""

    def test_set_simple_key(self) -> None:
        """Set simple top-level key."""
        overrides: dict = {}
        set_override(overrides, "agent", "custom-agent")
        assert overrides == {"agent": "custom-agent"}

    def test_set_nested_key(self) -> None:
        """Set nested key creates intermediate dicts."""
        overrides: dict = {}
        set_override(overrides, "proxy.template", "new-family")
        assert overrides == {"proxy": {"template": "new-family"}}

    def test_set_custom_namespace_rejected(self) -> None:
        """custom.* is not supported."""
        overrides: dict = {}
        with pytest.raises(InvalidOverrideKeyError):
            set_override(overrides, "custom.feature.enabled", True)

    def test_set_overwrites_existing(self) -> None:
        """Set overwrites existing value."""
        overrides: dict = {"agent": "claude-code"}
        set_override(overrides, "agent", "custom-agent")
        assert overrides == {"agent": "custom-agent"}

    def test_set_preserves_siblings(self) -> None:
        """Set preserves sibling keys."""
        overrides: dict = {"proxy": {"template": "old"}}
        set_override(overrides, "proxy.base_url", "http://new")
        assert overrides == {"proxy": {"template": "old", "base_url": "http://new"}}

    def test_set_with_none_clears(self) -> None:
        """Set with None value clears the field."""
        overrides: dict = {}
        set_override(overrides, "proxy.template", None)
        assert overrides == {"proxy": {"template": None}}

    def test_set_wildcard_expands(self) -> None:
        """Set with wildcard expands and sets each path."""
        overrides: dict = {}
        set_override(overrides, "proxy.*", None)
        assert "proxy" in overrides
        assert overrides["proxy"]["template"] is None
        assert overrides["proxy"]["base_url"] is None

    def test_set_invalid_key_raises(self) -> None:
        """Set with invalid key raises error."""
        overrides: dict = {}
        with pytest.raises(InvalidOverrideKeyError):
            set_override(overrides, "confirmed.claude_session_id", "value")


class TestDeleteOverride:
    """Test delete_override() function."""

    def test_delete_existing_key(self) -> None:
        """Delete existing key returns True."""
        overrides: dict = {"agent": "custom-agent"}
        result = delete_override(overrides, "agent")
        assert result is True
        assert overrides == {}

    def test_delete_nonexistent_key(self) -> None:
        """Delete nonexistent key returns False."""
        overrides: dict = {}
        result = delete_override(overrides, "agent")
        assert result is False
        assert overrides == {}

    def test_delete_nested_key(self) -> None:
        """Delete nested key."""
        overrides: dict = {"proxy": {"template": "test", "base_url": "http://localhost"}}
        result = delete_override(overrides, "proxy.template")
        assert result is True
        assert overrides == {"proxy": {"base_url": "http://localhost"}}

    def test_delete_preserves_siblings(self) -> None:
        """Delete preserves sibling keys."""
        overrides: dict = {"agent": "custom-agent", "proxy": {"template": "test"}}
        delete_override(overrides, "agent")
        assert overrides == {"proxy": {"template": "test"}}

    def test_delete_wildcard_expands(self) -> None:
        """Delete with wildcard expands and deletes each matching path."""
        overrides: dict = {"proxy": {"template": "test", "base_url": "http://localhost"}}
        result = delete_override(overrides, "proxy.*")
        assert result is True
        assert overrides["proxy"] == {}

    def test_delete_invalid_key_raises(self) -> None:
        """Delete with invalid key raises error."""
        overrides: dict = {}
        with pytest.raises(InvalidOverrideKeyError):
            delete_override(overrides, "confirmed.foo")


class TestClearOverrides:
    """Test clear_overrides() function."""

    def test_clear_empty(self) -> None:
        """Clear empty overrides is no-op."""
        overrides: dict = {}
        clear_overrides(overrides)
        assert overrides == {}

    def test_clear_populated(self) -> None:
        """Clear populated overrides empties it."""
        overrides: dict = {
            "agent": "custom-agent",
            "proxy": {"template": "test"},
        }
        clear_overrides(overrides)
        assert overrides == {}
