"""Tests for core.state.exceptions module."""

import pytest

from forge.core.state import (
    SchemaVersionError,
    StateCorruptedError,
    StateError,
    StateNotFoundError,
)


class TestStateError:
    """Tests for StateError base class."""

    def test_is_exception(self) -> None:
        """StateError is an Exception."""
        assert issubclass(StateError, Exception)

    def test_can_instantiate_with_message(self) -> None:
        """Can create StateError with a message."""
        err = StateError("something went wrong")
        assert str(err) == "something went wrong"


class TestStateNotFoundError:
    """Tests for StateNotFoundError."""

    def test_inherits_from_state_error(self) -> None:
        """StateNotFoundError is a StateError."""
        assert issubclass(StateNotFoundError, StateError)

    def test_stores_path(self) -> None:
        """Error stores the path that was not found."""
        err = StateNotFoundError("/path/to/file.json")
        assert err.path == "/path/to/file.json"

    def test_message_includes_path(self) -> None:
        """Error message includes the path."""
        err = StateNotFoundError("/path/to/file.json")
        assert "/path/to/file.json" in str(err)
        assert "not found" in str(err)


class TestStateCorruptedError:
    """Tests for StateCorruptedError."""

    def test_inherits_from_state_error(self) -> None:
        """StateCorruptedError is a StateError."""
        assert issubclass(StateCorruptedError, StateError)

    def test_stores_path_and_reason(self) -> None:
        """Error stores path and reason."""
        err = StateCorruptedError("/path/to/file.json", "invalid JSON")
        assert err.path == "/path/to/file.json"
        assert err.reason == "invalid JSON"

    def test_message_includes_path_and_reason(self) -> None:
        """Error message includes path and reason."""
        err = StateCorruptedError("/path/to/file.json", "invalid JSON")
        msg = str(err)
        assert "/path/to/file.json" in msg
        assert "invalid JSON" in msg


class TestSchemaVersionError:
    """Tests for SchemaVersionError."""

    def test_inherits_from_state_corrupted_error(self) -> None:
        """SchemaVersionError is a StateCorruptedError."""
        assert issubclass(SchemaVersionError, StateCorruptedError)

    def test_stores_expected_and_actual_with_int(self) -> None:
        """Error stores expected (as set) and actual versions when given int."""
        err = SchemaVersionError("/path/file.json", expected=3, actual=1)
        assert err.expected == {3}
        assert err.actual == 1

    def test_stores_expected_and_actual_with_set(self) -> None:
        """Error stores expected and actual versions when given set."""
        err = SchemaVersionError("/path/file.json", expected={2, 3}, actual=1)
        assert err.expected == {2, 3}
        assert err.actual == 1

    def test_message_includes_expected_and_actual(self) -> None:
        """Error message includes expected and actual versions."""
        err = SchemaVersionError("/path/file.json", expected={2, 3}, actual=1)
        msg = str(err)
        assert "1" in msg  # actual
        assert "[2, 3]" in msg  # expected (sorted)
        assert "incompatible version" in msg

    def test_inherits_path_attribute(self) -> None:
        """SchemaVersionError has path attribute from parent."""
        err = SchemaVersionError("/path/file.json", expected=3, actual=1)
        assert err.path == "/path/file.json"


class TestExceptionHierarchy:
    """Tests for the exception inheritance hierarchy."""

    def test_can_catch_all_with_state_error(self) -> None:
        """All state exceptions can be caught with StateError."""
        exceptions = [
            StateNotFoundError("/path"),
            StateCorruptedError("/path", "reason"),
            SchemaVersionError("/path", expected=1, actual=2),
        ]
        for exc in exceptions:
            with pytest.raises(StateError):
                raise exc

    def test_can_catch_corrupted_including_schema(self) -> None:
        """SchemaVersionError can be caught as StateCorruptedError."""
        with pytest.raises(StateCorruptedError):
            raise SchemaVersionError("/path", expected=1, actual=2)
