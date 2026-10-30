"""Launch observation lookup must not accept the newline allowed by regex '$'."""

import pytest

from forge.core.run_id import is_valid_run_id

pytestmark = pytest.mark.regression


def test_launch_lookup_id_rejects_terminal_newline() -> None:
    assert is_valid_run_id("run_aaaaaaaaaaaa")
    assert not is_valid_run_id("run_aaaaaaaaaaaa\n")
