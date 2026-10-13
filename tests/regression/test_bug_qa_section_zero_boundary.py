"""QA range selection must preserve the state script's section .0 shorthand."""

import pytest

from tests.src.skills.test_qa_selection import _resolve

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("boundary", ["from_id", "to_id"])
def test_section_zero_boundary_matches_bare_section(boundary):
    assert _resolve(**{boundary: "1.0"})["steps"] == _resolve(**{boundary: "1"})["steps"]
