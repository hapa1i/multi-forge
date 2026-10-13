"""QA filtered selections must include their transitive setup prerequisites."""

import pytest

from tests.src.skills.test_qa_selection import (
    CHECKLIST,
    SELECTION,
    STATE_SCRIPT,
    _resolve,
)

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("category", list(SELECTION.CATEGORIES))
def test_filtered_selection_contains_step_and_section_prerequisites(category):
    parsed = SELECTION._load_state_script(STATE_SCRIPT).parse_checklist(str(CHECKLIST))
    sections = {section["id"]: section for section in parsed["sections"]}
    selected = {step["id"] for step in _resolve(categories=[category])["steps"]}
    for step in parsed["_all_subs"]:
        if step["id"] in selected:
            assert set(step["prereqs"] + sections[step["section_id"]]["prereqs"]) <= selected
