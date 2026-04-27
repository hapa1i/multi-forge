"""Tests for effective configuration computation."""

from __future__ import annotations

import pytest

from forge.session.effective import (
    apply_overrides,
    compute_effective_intent,
    get_effective_value,
)
from forge.session.exceptions import (
    InvalidOverrideKeyError,
)
from forge.session.models import (
    SessionIntent,
    SessionState,
    create_session_state,
)


class TestDeepMerge:
    """Test apply_overrides() function."""

    def test_empty_overrides_returns_copy_of_base(self) -> None:
        """Empty overrides returns a copy of base."""
        base = {"a": 1, "b": 2}
        result = apply_overrides(base, {})
        assert result == {"a": 1, "b": 2}
        # Verify it's a copy, not the same object
        assert result is not base

    def test_scalar_override_replaces_base(self) -> None:
        """Scalar override replaces base value."""
        base = {"a": 1, "b": 2}
        overrides = {"a": 10}
        result = apply_overrides(base, overrides)
        assert result == {"a": 10, "b": 2}

    def test_new_key_in_override_added(self) -> None:
        """New keys in override are added to result."""
        base = {"a": 1}
        overrides = {"b": 2}
        result = apply_overrides(base, overrides)
        assert result == {"a": 1, "b": 2}

    def test_nested_dict_merged_recursively(self) -> None:
        """Nested dicts are merged recursively."""
        base = {"outer": {"a": 1, "b": 2}}
        overrides = {"outer": {"b": 20, "c": 3}}
        result = apply_overrides(base, overrides)
        assert result == {"outer": {"a": 1, "b": 20, "c": 3}}

    def test_deeply_nested_merge(self) -> None:
        """Deep nesting works correctly."""
        base = {"l1": {"l2": {"l3": {"value": 1}}}}
        overrides = {"l1": {"l2": {"l3": {"value": 999}}}}
        result = apply_overrides(base, overrides)
        assert result["l1"]["l2"]["l3"]["value"] == 999

    def test_list_replacement_not_concatenation(self) -> None:
        """Lists are replaced entirely, not concatenated."""
        base = {"tags": ["a", "b", "c"]}
        overrides = {"tags": ["x"]}
        result = apply_overrides(base, overrides)
        assert result == {"tags": ["x"]}

    def test_null_clears_field(self) -> None:
        """Explicit None in override clears the field."""
        base = {"a": 1, "b": 2}
        overrides = {"a": None}
        result = apply_overrides(base, overrides)
        assert result == {"a": None, "b": 2}

    def test_null_clears_nested_dict(self) -> None:
        """None can clear an entire nested dict."""
        base = {"proxy": {"template": "test", "base_url": "http://localhost"}}
        overrides = {"proxy": None}
        result = apply_overrides(base, overrides)
        assert result == {"proxy": None}

    def test_override_dict_over_scalar(self) -> None:
        """Dict override over scalar replaces."""
        base = {"a": 1}
        overrides = {"a": {"nested": "value"}}
        result = apply_overrides(base, overrides)
        assert result == {"a": {"nested": "value"}}

    def test_scalar_override_over_dict(self) -> None:
        """Scalar override over dict replaces."""
        base = {"a": {"nested": "value"}}
        overrides = {"a": 42}
        result = apply_overrides(base, overrides)
        assert result == {"a": 42}

    def test_base_not_mutated(self) -> None:
        """Original base dict is not mutated."""
        base = {"a": {"b": 1}}
        overrides = {"a": {"b": 2}}
        apply_overrides(base, overrides)
        assert base == {"a": {"b": 1}}

    def test_overrides_not_mutated(self) -> None:
        """Original overrides dict is not mutated."""
        base = {"a": 1}
        overrides = {"b": {"nested": [1, 2, 3]}}
        original_overrides = {"b": {"nested": [1, 2, 3]}}
        apply_overrides(base, overrides)
        assert overrides == original_overrides

    def test_complex_real_world_example(self) -> None:
        """Test a realistic intent + overrides merge scenario."""
        base = {
            "agent": "claude-code",
            "proxy": {
                "template": "litellm-gemini",
                "base_url": "http://localhost:8084",
            },
            "memory": {
                "auto_recall": True,
                "tags": ["project:myapp"],
            },
        }
        overrides = {
            "agent": "custom-agent",
            "memory": {
                "tags": ["project:myapp", "component:auth"],
            },
        }
        result = apply_overrides(base, overrides)

        assert result["agent"] == "custom-agent"
        assert result["proxy"]["template"] == "litellm-gemini"  # Unchanged
        assert result["memory"]["auto_recall"] is True  # Preserved
        assert result["memory"]["tags"] == ["project:myapp", "component:auth"]


class TestComputeEffectiveIntent:
    """Test compute_effective_intent() function."""

    @pytest.fixture
    def basic_manifest(self) -> SessionState:
        """Create a basic manifest for testing."""
        return create_session_state(
            "test-session",
            proxy_template="test-family",
            proxy_base_url="http://localhost:8080",
        )

    def test_no_overrides_returns_intent(self, basic_manifest: SessionState) -> None:
        """With no overrides, effective equals intent."""
        effective = compute_effective_intent(basic_manifest)
        assert effective.agent == "claude-code"

    def test_override_applies(self, basic_manifest: SessionState) -> None:
        """Override values are applied to effective."""
        basic_manifest.overrides = {"agent": "custom-agent"}
        effective = compute_effective_intent(basic_manifest)
        assert effective.agent == "custom-agent"  # Overridden

    def test_nested_override_applies(self, basic_manifest: SessionState) -> None:
        """Nested override values are applied correctly."""
        basic_manifest.overrides = {"proxy": {"template": "new-family"}}
        effective = compute_effective_intent(basic_manifest)
        assert effective.proxy is not None
        assert effective.proxy.template == "new-family"
        assert effective.proxy.base_url == "http://localhost:8080"  # Preserved

    def test_null_clears_nested_object(self, basic_manifest: SessionState) -> None:
        """Setting nested object to None clears it."""
        basic_manifest.overrides = {"proxy": None}
        effective = compute_effective_intent(basic_manifest)
        assert effective.proxy is None

    def test_empty_overrides_dict(self, basic_manifest: SessionState) -> None:
        """Empty overrides dict has no effect."""
        basic_manifest.overrides = {}
        compute_effective_intent(basic_manifest)

    def test_strict_mode_validates(self) -> None:
        """Strict mode validates merged config can become SessionIntent."""
        manifest = create_session_state(
            "test",
            proxy_template="test",
            proxy_base_url="http://localhost:8080",
        )
        # This should work - valid string value
        manifest.overrides = {"agent": "custom-agent"}
        effective = compute_effective_intent(manifest, strict=True)
        assert effective.agent == "custom-agent"

    def test_returns_session_intent_type(self, basic_manifest: SessionState) -> None:
        """compute_effective_intent returns a SessionIntent instance."""
        effective = compute_effective_intent(basic_manifest)
        assert isinstance(effective, SessionIntent)

    def test_manifest_not_mutated(self, basic_manifest: SessionState) -> None:
        """Computing effective doesn't mutate the manifest."""
        original_agent = basic_manifest.intent.agent
        basic_manifest.overrides = {"agent": "custom-agent"}
        compute_effective_intent(basic_manifest)
        assert basic_manifest.intent.agent == original_agent


class TestGetEffectiveValue:
    """Test get_effective_value() function."""

    @pytest.fixture
    def manifest_with_values(self) -> SessionState:
        """Create a manifest with various values for testing."""
        manifest = create_session_state(
            "test-session",
            proxy_template="test-family",
            proxy_base_url="http://localhost:8080",
        )
        if manifest.intent.memory is None:
            from forge.session.models import MemoryIntent

            manifest.intent.memory = MemoryIntent(
                auto_recall=True,
                tags=["tag1", "tag2"],
            )
        return manifest

    def test_simple_key(self, manifest_with_values: SessionState) -> None:
        """Get value for simple top-level key."""
        value = get_effective_value(manifest_with_values, "agent")
        assert value == "claude-code"

    def test_nested_key(self, manifest_with_values: SessionState) -> None:
        """Get value for nested dot-notation key."""
        value = get_effective_value(manifest_with_values, "proxy.template")
        assert value == "test-family"

    def test_deeply_nested_key(self, manifest_with_values: SessionState) -> None:
        """Get value for deeply nested key."""
        value = get_effective_value(manifest_with_values, "memory.auto_recall")
        assert value is True

    def test_list_value(self, manifest_with_values: SessionState) -> None:
        """Get list value."""
        value = get_effective_value(manifest_with_values, "memory.tags")
        assert value == ["tag1", "tag2"]

    def test_missing_key_returns_none(self, manifest_with_values: SessionState) -> None:
        """Missing key returns None (not an error)."""
        value = get_effective_value(manifest_with_values, "nonexistent_field")
        assert value is None

    def test_missing_nested_key_returns_none(self, manifest_with_values: SessionState) -> None:
        """Missing nested key returns None."""
        value = get_effective_value(manifest_with_values, "proxy.nonexistent")
        assert value is None

    def test_path_through_none_returns_none(self) -> None:
        """Path through None value returns None."""
        manifest = create_session_state(
            "test",
            proxy_template="test",
            proxy_base_url="http://localhost:8080",
        )
        # Set proxy to None to test path through None
        manifest.intent.proxy = None
        value = get_effective_value(manifest, "proxy.template")
        assert value is None

    def test_override_reflected_in_value(self, manifest_with_values: SessionState) -> None:
        """Overrides are reflected in returned value."""
        manifest_with_values.overrides = {"agent": "custom-agent"}
        value = get_effective_value(manifest_with_values, "agent")
        assert value == "custom-agent"

    def test_empty_key_raises(self, manifest_with_values: SessionState) -> None:
        """Empty key raises InvalidOverrideKeyError."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            get_effective_value(manifest_with_values, "")
        assert "cannot be empty" in str(exc_info.value)

    def test_empty_segment_raises(self, manifest_with_values: SessionState) -> None:
        """Empty path segment raises InvalidOverrideKeyError."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            get_effective_value(manifest_with_values, "proxy..family")
        assert "empty segment" in str(exc_info.value)

    def test_leading_dot_raises(self, manifest_with_values: SessionState) -> None:
        """Leading dot raises InvalidOverrideKeyError."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            get_effective_value(manifest_with_values, ".proxy")
        assert "empty segment" in str(exc_info.value)

    def test_trailing_dot_raises(self, manifest_with_values: SessionState) -> None:
        """Trailing dot raises InvalidOverrideKeyError."""
        with pytest.raises(InvalidOverrideKeyError) as exc_info:
            get_effective_value(manifest_with_values, "proxy.")
        assert "empty segment" in str(exc_info.value)


class TestInvalidOverrideValueError:
    """Test that InvalidOverrideValueError is raised for type mismatches."""

    def test_invalid_type_raises_custom_error(self) -> None:
        """Invalid type in override raises InvalidOverrideValueError, not raw dacite error."""
        from forge.session.exceptions import InvalidOverrideValueError

        manifest = create_session_state(
            "test",
            proxy_template="test",
            proxy_base_url="http://localhost:8080",
        )
        # Set memory.tags to a non-list value (should be list)
        manifest.overrides = {"memory": {"tags": "not-a-list"}}

        with pytest.raises(InvalidOverrideValueError) as exc_info:
            compute_effective_intent(manifest, strict=True, override_key="memory.tags")

        err = exc_info.value
        assert err.key == "memory.tags"
        assert isinstance(err.expected, str)
        assert isinstance(err.actual, str)
