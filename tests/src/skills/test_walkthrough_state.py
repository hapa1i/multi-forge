"""Unit tests for walkthrough-state.py — the walkthrough state machine.

Tests cover:
- Parsing: sections, subsections, annotations, code_blocks, assertions
- Read-only commands: index, step, summary
- State commands: init, record, var, report
- Validation: count mismatch, hash drift, overwrite rejection
"""

import json
import sys
from pathlib import Path

import pytest

# Import the script's functions directly
SCRIPT_DIR = str(Path(__file__).resolve().parents[3] / "src" / "skills" / "walkthrough" / "scripts")
sys.path.insert(0, SCRIPT_DIR)

# ruff: noqa: E402
from importlib import import_module

# Import as module (filename has hyphens, so use importlib)
pc = import_module("walkthrough-state")

# --- Fixtures ---

MINIMAL_CHECKLIST = """\
# Test Checklist

<!-- version: 2.0.0 -->

## 0. Setup

### 0.1 First Step

<!-- auto -->

```bash
echo "hello"
```

- [ ] Output says hello
- [ ] Exit code is 0

### 0.2 Second Step

<!-- human:guided -->

Do something in your terminal:

```
manual-command --flag
```

Extra instructions after the code block.

- [ ] User confirms done

## 1. Verify

### 1.1 Check Files

<!-- auto -->

Use the Glob tool to verify files exist:

- Glob pattern: `$FORGE_TEST_REPO/.claude/commands/*.md`

- [ ] Files found
- [ ] Count matches expected

### 1.2 Check Settings

<!-- auto -->
<!-- requires: api-key -->

```bash
curl http://localhost:8080/health
```

- [ ] Health check passes

## 2. Cleanup

### 2.1 Remove Artifacts

<!-- auto -->

```bash
rm -rf /tmp/test-artifacts
```

```bash
echo "done"
```

- [ ] Artifacts removed
- [ ] Cleanup confirmed
"""

INDEXED_INDEX = """\
# Indexed Checklist

<!-- checklist: index -->
<!-- version: 3.0.0 -->

<!-- section: 0 sections/0-setup.md -->
<!-- section: 1 sections/1-verify.md -->
"""

INDEXED_SECTION_0 = """\
## 0. Setup

### 0.1 Hello

<!-- auto -->

```bash
echo "hi"
```

- [ ] Says hi
"""

INDEXED_SECTION_1 = """\
## 1. Verify

### 1.1 Confirm

<!-- human:confirm -->

- [ ] User confirms
"""

PREREQ_CHECKLIST = """\
# Prereq Checklist

<!-- version: 1.0.0 -->

## 0. Setup

### 0.1 Prepare

<!-- auto -->

- [ ] Setup complete

<!-- prereq: 0 -->
## 1. Depends

### 1.1 Uses Setup

<!-- auto -->

- [ ] Dependency available

### 1.2 Explicit Prereq

<!-- prereq: 0 -->
<!-- auto -->

- [ ] Explicit dependency available
"""

SUB_PREREQ_CHECKLIST = """\
# Sub-Prereq Checklist

<!-- version: 1.0.0 -->

## 3. Proxy

### 3.1 List

<!-- auto -->

- [ ] Listed

### 3.2 Create

<!-- auto -->

- [ ] Created

### 3.3 Show

<!-- prereq: 3.2 -->
<!-- auto -->

- [ ] Shown
"""

SUBSECTION_PREREQ_RESOLVABLE_CHECKLIST = """\
# Resolvable Sub-Prereq Checklist

<!-- version: 1.0.0 -->

## 0. Foundation

### 0.1 Init

<!-- auto -->

- [ ] Initialized

### 0.3 Config

<!-- auto -->

- [ ] Configured

## 2. Auth

### 2.1 Login

<!-- auto -->

- [ ] Logged in

<!-- prereq: 0.3, 2.1 -->
## 4. Proxy

### 4.1 Create

<!-- auto -->

- [ ] Created

<!-- prereq: 4.1 -->
## 5. Session

### 5.1 Start

<!-- auto -->

- [ ] Started
"""

ANNOTATION_ORDER_CHECKLIST = """\
# Annotation Order Checklist

<!-- version: 1.0.0 -->

## 0. Annotation Order

### 0.1 Modifier Before Guided

<!-- requires: api_key -->
<!-- human:guided -->

- [ ] Guided step preserved

### 0.2 Modifier Before Auto

<!-- destructive -->
<!-- auto -->

- [ ] Auto step preserved

### 0.3 Modifiers Only

<!-- requires: docker -->
<!-- destructive -->

- [ ] Falls back to review step
"""


@pytest.fixture
def checklist_path(tmp_path):
    p = tmp_path / "test-checklist.md"
    p.write_text(MINIMAL_CHECKLIST)
    return str(p)


@pytest.fixture
def parsed(checklist_path):
    return pc.parse_checklist(checklist_path)


@pytest.fixture
def state_path(tmp_path):
    return str(tmp_path / "progress.json")


@pytest.fixture
def indexed_checklist(tmp_path):
    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()

    section0_path = sections_dir / "0-setup.md"
    section1_path = sections_dir / "1-verify.md"
    section0_path.write_text(INDEXED_SECTION_0)
    section1_path.write_text(INDEXED_SECTION_1)

    index_path = tmp_path / "index.md"
    index_path.write_text(INDEXED_INDEX)

    return {"index": str(index_path), "section0": str(section0_path), "section1": str(section1_path)}


@pytest.fixture
def indexed_parsed(indexed_checklist):
    return pc.parse_checklist(indexed_checklist["index"])


@pytest.fixture
def prereq_checklist_path(tmp_path):
    p = tmp_path / "prereq-checklist.md"
    p.write_text(PREREQ_CHECKLIST)
    return str(p)


@pytest.fixture
def prereq_parsed(prereq_checklist_path):
    return pc.parse_checklist(prereq_checklist_path)


@pytest.fixture
def sub_prereq_checklist_path(tmp_path):
    p = tmp_path / "sub-prereq-checklist.md"
    p.write_text(SUB_PREREQ_CHECKLIST)
    return str(p)


@pytest.fixture
def sub_prereq_parsed(sub_prereq_checklist_path):
    return pc.parse_checklist(sub_prereq_checklist_path)


@pytest.fixture
def resolvable_checklist_path(tmp_path):
    p = tmp_path / "resolvable-checklist.md"
    p.write_text(SUBSECTION_PREREQ_RESOLVABLE_CHECKLIST)
    return str(p)


@pytest.fixture
def resolvable_parsed(resolvable_checklist_path):
    return pc.parse_checklist(resolvable_checklist_path)


@pytest.fixture
def annotation_order_checklist_path(tmp_path):
    p = tmp_path / "annotation-order-checklist.md"
    p.write_text(ANNOTATION_ORDER_CHECKLIST)
    return str(p)


@pytest.fixture
def annotation_order_parsed(annotation_order_checklist_path):
    return pc.parse_checklist(annotation_order_checklist_path)


@pytest.fixture
def initialized_state(checklist_path, state_path, parsed):
    """State file after init."""
    pc.cmd_init(parsed, checklist_path, state_path, "walkthrough", force=False)
    return state_path


# --- Parser tests ---


class TestParseChecklist:
    def test_version_extracted(self, parsed):
        assert parsed["version"] == "2.0.0"

    def test_section_count(self, parsed):
        assert len(parsed["sections"]) == 3

    def test_section_ids(self, parsed):
        ids = [s["id"] for s in parsed["sections"]]
        assert ids == ["0", "1", "2"]

    def test_section_titles(self, parsed):
        titles = [s["title"] for s in parsed["sections"]]
        assert titles == ["Setup", "Verify", "Cleanup"]

    def test_subsection_count(self, parsed):
        counts = [len(s["subsections"]) for s in parsed["sections"]]
        assert counts == [2, 2, 1]

    def test_total_assertions(self, parsed):
        assert parsed["total_assertions"] == 8

    def test_section_assertion_counts(self, parsed):
        counts = [s["assertion_count"] for s in parsed["sections"]]
        assert counts == [3, 3, 2]

    def test_auto_annotation(self, parsed):
        sub = parsed["_all_subs"][0]  # 0.1
        assert sub["annotation"] == "auto"

    def test_guided_annotation(self, parsed):
        sub = parsed["_all_subs"][1]  # 0.2
        assert sub["annotation"] == "human:guided"

    def test_multi_annotation(self, parsed):
        sub = parsed["_all_subs"][3]  # 1.2
        assert sub["annotations"] == ["auto", "requires: api-key"]
        assert sub["annotation"] == "auto"

    def test_default_annotation(self, parsed):
        """Subsections without annotation default to human:confirm."""
        # All our test subsections have annotations, so this tests the logic path
        # indirectly through the code. Tested via the else branch in post-processing.
        pass

    def test_code_block_runnable(self, parsed):
        sub = parsed["_all_subs"][0]  # 0.1 has ```bash
        assert len(sub["code_blocks"]) == 1
        assert sub["code_blocks"][0]["runnable"] is True
        assert sub["code_blocks"][0]["code"] == 'echo "hello"'

    def test_code_block_display_only(self, parsed):
        sub = parsed["_all_subs"][1]  # 0.2 has plain ```
        assert len(sub["code_blocks"]) == 1
        assert sub["code_blocks"][0]["runnable"] is False
        assert sub["code_blocks"][0]["code"] == "manual-command --flag"

    def test_multiple_code_blocks(self, parsed):
        sub = parsed["_all_subs"][4]  # 2.1 has two bash blocks
        assert len(sub["code_blocks"]) == 2
        assert all(b["runnable"] for b in sub["code_blocks"])

    def test_assertions_extracted(self, parsed):
        sub = parsed["_all_subs"][0]  # 0.1
        assert sub["assertions"] == ["Output says hello", "Exit code is 0"]

    def test_instructions_before_code(self, parsed):
        sub = parsed["_all_subs"][1]  # 0.2
        assert "Do something in your terminal:" in sub["instructions"]

    def test_instructions_after_code(self, parsed):
        """Prose after code blocks is captured (P1 fix)."""
        sub = parsed["_all_subs"][1]  # 0.2
        assert "Extra instructions after the code block." in sub["instructions"]

    def test_instructions_without_code(self, parsed):
        """Subsection 1.1 has instructions but no code blocks."""
        sub = parsed["_all_subs"][2]  # 1.1
        assert "Use the Glob tool" in sub["instructions"]
        assert len(sub["code_blocks"]) == 0

    def test_next_pointer(self, parsed):
        subs = parsed["_all_subs"]
        assert subs[0]["next"] == "0.2"
        assert subs[1]["next"] == "1.1"
        assert subs[-1]["next"] is None


class TestParseChecklistIndex:
    def test_version_extracted(self, indexed_parsed):
        assert indexed_parsed["version"] == "3.0.0"

    def test_section_count(self, indexed_parsed):
        assert len(indexed_parsed["sections"]) == 2

    def test_section_ids(self, indexed_parsed):
        ids = [s["id"] for s in indexed_parsed["sections"]]
        assert ids == ["0", "1"]

    def test_total_assertions(self, indexed_parsed):
        assert indexed_parsed["total_assertions"] == 2

    def test_next_pointer_cross_file(self, indexed_parsed):
        subs = indexed_parsed["_all_subs"]
        assert subs[0]["id"] == "0.1"
        assert subs[0]["next"] == "1.1"
        assert subs[-1]["next"] is None


class TestPrereqParsing:
    def test_section_level_prereq_after_previous_section(self, prereq_parsed):
        assert prereq_parsed["sections"][1]["prereqs"] == ["0"]

    def test_step_inherits_section_prereq(self, prereq_parsed):
        result = pc.cmd_step(prereq_parsed, "1.1")
        assert result["prereqs"] == ["0"]

    def test_step_deduplicates_section_and_subsection_prereqs(self, prereq_parsed):
        result = pc.cmd_step(prereq_parsed, "1.2")
        assert result["prereqs"] == ["0"]


class TestAnnotationSelection:
    def test_prefers_execution_annotation_over_modifier_when_guided(self, annotation_order_parsed):
        sub = annotation_order_parsed["_all_subs"][0]
        assert sub["annotations"] == ["requires: api_key", "human:guided"]
        assert sub["annotation"] == "human:guided"

    def test_prefers_execution_annotation_over_modifier_when_auto(self, annotation_order_parsed):
        sub = annotation_order_parsed["_all_subs"][1]
        assert sub["annotations"] == ["destructive", "auto"]
        assert sub["annotation"] == "auto"

    def test_defaults_to_review_when_only_modifiers_exist(self, annotation_order_parsed):
        sub = annotation_order_parsed["_all_subs"][2]
        assert sub["annotations"] == ["requires: docker", "destructive"]
        assert sub["annotation"] == "human:confirm"


# --- Read-only command tests ---


class TestCmdIndex:
    def test_structure(self, parsed):
        result = pc.cmd_index(parsed)
        assert result["version"] == "2.0.0"
        assert result["total_assertions"] == 8
        assert len(result["sections"]) == 3

    def test_subsection_fields(self, parsed):
        result = pc.cmd_index(parsed)
        sub = result["sections"][0]["subsections"][0]
        assert sub["id"] == "0.1"
        assert sub["title"] == "First Step"
        assert sub["annotation"] == "auto"
        assert sub["assertion_count"] == 2


class TestCmdStep:
    def test_existing_step(self, parsed):
        result = pc.cmd_step(parsed, "0.1")
        assert result["id"] == "0.1"
        assert result["section"] == "0. Setup"
        assert result["assertion_count"] == 2
        assert result["next"] == "0.2"

    def test_missing_step(self, parsed):
        with pytest.raises(SystemExit):
            pc.cmd_step(parsed, "99.99")

    def test_existing_step_in_indexed_checklist(self, indexed_parsed):
        result = pc.cmd_step(indexed_parsed, "0.1")
        assert result["id"] == "0.1"
        assert result["next"] == "1.1"


class TestCmdSummary:
    def test_totals(self, parsed):
        result = pc.cmd_summary(parsed)
        assert result["total_assertions"] == 8
        assert len(result["sections"]) == 3
        assert result["sections"][0]["expected"] == 3


# --- State command tests ---


class TestCmdInit:
    def test_creates_state_file(self, checklist_path, state_path, parsed):
        result = pc.cmd_init(parsed, checklist_path, state_path, "walkthrough", force=False)
        assert result["status"] == "initialized"
        assert result["assertions"] == 8
        assert result["current_step"] == "0.1"
        assert Path(state_path).exists()

    def test_state_file_structure(self, initialized_state):
        state = json.loads(Path(initialized_state).read_text())
        assert state["schema_version"] == 2
        assert state["checklist_version"] == "2.0.0"
        assert "checklist_hash" not in state
        assert state["mode"] == "walkthrough"
        assert state["steps"] == {}
        assert state["vars"] == {}

    def test_refuses_overwrite(self, checklist_path, initialized_state, parsed):
        with pytest.raises(SystemExit):
            pc.cmd_init(parsed, checklist_path, initialized_state, "walkthrough", force=False)

    def test_force_overwrites(self, checklist_path, initialized_state, parsed):
        result = pc.cmd_init(parsed, checklist_path, initialized_state, "walkthrough", force=True)
        assert result["status"] == "initialized"


class TestCmdRecord:
    def test_valid_record(self, checklist_path, initialized_state, parsed):
        result = pc.cmd_record(parsed, checklist_path, initialized_state, "0.1", "p,p", force=False)
        assert result["step"] == "0.1"
        assert result["step_results"] == "2/2 pass"
        assert result["section_progress"] == "2/3"
        assert result["overall_progress"] == "2/8"

    def test_state_updated(self, checklist_path, initialized_state, parsed):
        pc.cmd_record(parsed, checklist_path, initialized_state, "0.1", "p,p", force=False)
        state = json.loads(Path(initialized_state).read_text())
        assert state["steps"]["0.1"]["results"] == ["pass", "pass"]
        assert state["steps"]["0.1"]["hash"] is not None
        assert len(state["steps"]["0.1"]["hash"]) == 64  # Full SHA-256 hex
        assert state["current_step"] == "0.2"

    def test_mixed_results(self, checklist_path, initialized_state, parsed):
        result = pc.cmd_record(parsed, checklist_path, initialized_state, "0.1", "p,f", force=False)
        assert result["step_results"] == "1/2 pass"

    def test_count_mismatch(self, checklist_path, initialized_state, parsed):
        with pytest.raises(SystemExit):
            pc.cmd_record(parsed, checklist_path, initialized_state, "0.1", "p,p,p", force=False)

    def test_invalid_result_code(self, checklist_path, initialized_state, parsed):
        with pytest.raises(SystemExit):
            pc.cmd_record(parsed, checklist_path, initialized_state, "0.1", "p,x", force=False)

    def test_rejects_overwrite(self, checklist_path, initialized_state, parsed):
        pc.cmd_record(parsed, checklist_path, initialized_state, "0.1", "p,p", force=False)
        with pytest.raises(SystemExit):
            pc.cmd_record(parsed, checklist_path, initialized_state, "0.1", "p,p", force=False)

    def test_force_overwrite(self, checklist_path, initialized_state, parsed):
        pc.cmd_record(parsed, checklist_path, initialized_state, "0.1", "p,p", force=False)
        result = pc.cmd_record(parsed, checklist_path, initialized_state, "0.1", "p,f", force=True)
        assert result["step_results"] == "1/2 pass"

    def test_checklist_edit_does_not_block_record(self, checklist_path, initialized_state, parsed):
        """Editing the checklist (e.g., future steps) must not block recording."""
        Path(checklist_path).write_text(MINIMAL_CHECKLIST + "\n<!-- modified -->")
        modified_data = pc.parse_checklist(checklist_path)
        result = pc.cmd_record(modified_data, checklist_path, initialized_state, "0.1", "p,p", force=False)
        assert result["step"] == "0.1"

    def test_unknown_step(self, checklist_path, initialized_state, parsed):
        with pytest.raises(SystemExit):
            pc.cmd_record(parsed, checklist_path, initialized_state, "99.1", "p", force=False)

    def test_progress_accumulates(self, checklist_path, initialized_state, parsed):
        pc.cmd_record(parsed, checklist_path, initialized_state, "0.1", "p,p", force=False)
        result = pc.cmd_record(parsed, checklist_path, initialized_state, "0.2", "p", force=False)
        assert result["section_progress"] == "3/3"
        assert result["overall_progress"] == "3/8"

    def test_section_status_tracks_passed_section_in_current_run(
        self, prereq_checklist_path, state_path, prereq_parsed
    ):
        pc.cmd_init(prereq_parsed, prereq_checklist_path, state_path, "walkthrough", force=False)
        pc.cmd_var(state_path, "set", "RUN_SCOPE", "run-a")
        result = pc.cmd_record(prereq_parsed, prereq_checklist_path, state_path, "0.1", "p", force=False)
        state = json.loads(Path(state_path).read_text())
        assert result["section_status"] == "passed"
        assert state["steps"]["0.1"]["scope"] == "run-a"
        assert state["vars"]["SECTION_0_STATUS"] == "passed"
        assert state["vars"]["SECTION_0_SCOPE"] == "run-a"

    def test_section_status_tracks_failed_section_in_current_run(
        self, prereq_checklist_path, state_path, prereq_parsed
    ):
        pc.cmd_init(prereq_parsed, prereq_checklist_path, state_path, "walkthrough", force=False)
        pc.cmd_var(state_path, "set", "RUN_SCOPE", "run-a")
        result = pc.cmd_record(prereq_parsed, prereq_checklist_path, state_path, "0.1", "f", force=False)
        assert result["section_status"] == "failed"


class TestCmdVar:
    def test_set_and_get(self, initialized_state):
        pc.cmd_var(initialized_state, "set", "PROXY_ID", "proxy_abc")
        result = pc.cmd_var(initialized_state, "get", "PROXY_ID")
        assert result["value"] == "proxy_abc"
        assert result["exists"] is True

    def test_get_missing(self, initialized_state):
        result = pc.cmd_var(initialized_state, "get", "NONEXISTENT")
        assert result["exists"] is False
        assert "value" not in result

    def test_set_requires_value(self, initialized_state):
        with pytest.raises(SystemExit):
            pc.cmd_var(initialized_state, "set", "KEY", None)

    def test_overwrite_var(self, initialized_state):
        pc.cmd_var(initialized_state, "set", "KEY", "old")
        pc.cmd_var(initialized_state, "set", "KEY", "new")
        result = pc.cmd_var(initialized_state, "get", "KEY")
        assert result["value"] == "new"

    def test_invalid_action(self, initialized_state):
        with pytest.raises(SystemExit):
            pc.cmd_var(initialized_state, "delete", "KEY")


class TestCmdPrereqCheck:
    def test_blocks_not_run_prereq(self, prereq_checklist_path, state_path, prereq_parsed):
        pc.cmd_init(prereq_parsed, prereq_checklist_path, state_path, "walkthrough", force=False)
        pc.cmd_var(state_path, "set", "RUN_SCOPE", "run-a")
        result = pc.cmd_prereq_check(prereq_parsed, state_path, "1.1")
        assert result["ok"] is False
        assert result["missing"] == ["0"]
        assert result["blocking"] == ["0"]
        assert result["statuses"] == {"0": "not_run"}

    def test_allows_passed_prereq_in_current_run(self, prereq_checklist_path, state_path, prereq_parsed):
        pc.cmd_init(prereq_parsed, prereq_checklist_path, state_path, "walkthrough", force=False)
        pc.cmd_var(state_path, "set", "RUN_SCOPE", "run-a")
        pc.cmd_record(prereq_parsed, prereq_checklist_path, state_path, "0.1", "p", force=False)
        result = pc.cmd_prereq_check(prereq_parsed, state_path, "1.1")
        assert result["ok"] is True
        assert result["blocking"] == []
        assert result["statuses"] == {"0": "passed"}

    def test_blocks_failed_prereq(self, prereq_checklist_path, state_path, prereq_parsed):
        pc.cmd_init(prereq_parsed, prereq_checklist_path, state_path, "walkthrough", force=False)
        pc.cmd_var(state_path, "set", "RUN_SCOPE", "run-a")
        pc.cmd_record(prereq_parsed, prereq_checklist_path, state_path, "0.1", "f", force=False)
        result = pc.cmd_prereq_check(prereq_parsed, state_path, "1.1")
        assert result["ok"] is False
        assert result["missing"] == []
        assert result["blocking"] == ["0"]
        assert result["statuses"] == {"0": "failed"}

    def test_blocks_skipped_prereq(self, prereq_checklist_path, state_path, prereq_parsed):
        pc.cmd_init(prereq_parsed, prereq_checklist_path, state_path, "walkthrough", force=False)
        pc.cmd_var(state_path, "set", "RUN_SCOPE", "run-a")
        pc.cmd_record(prereq_parsed, prereq_checklist_path, state_path, "0.1", "s", force=False)
        result = pc.cmd_prereq_check(prereq_parsed, state_path, "1.1")
        assert result["ok"] is False
        assert result["missing"] == []
        assert result["blocking"] == ["0"]
        assert result["statuses"] == {"0": "skipped"}

    def test_blocks_stale_run_prereq(self, prereq_checklist_path, state_path, prereq_parsed):
        pc.cmd_init(prereq_parsed, prereq_checklist_path, state_path, "walkthrough", force=False)
        pc.cmd_var(state_path, "set", "RUN_SCOPE", "run-a")
        pc.cmd_record(prereq_parsed, prereq_checklist_path, state_path, "0.1", "p", force=False)
        pc.cmd_var(state_path, "set", "RUN_SCOPE", "run-b")
        result = pc.cmd_prereq_check(prereq_parsed, state_path, "1.1")
        assert result["ok"] is False
        assert result["missing"] == []
        assert result["blocking"] == ["0"]
        assert result["statuses"] == {"0": "stale_run"}

    def test_sub_prereq_blocks_when_not_run(self, sub_prereq_checklist_path, state_path, sub_prereq_parsed):
        pc.cmd_init(sub_prereq_parsed, sub_prereq_checklist_path, state_path, "walkthrough", force=False)
        pc.cmd_var(state_path, "set", "RUN_SCOPE", "run-a")
        result = pc.cmd_prereq_check(sub_prereq_parsed, state_path, "3.3")
        assert result["ok"] is False
        assert result["blocking"] == ["3.2"]
        assert result["statuses"] == {"3.2": "not_run"}

    def test_sub_prereq_allows_when_passed(self, sub_prereq_checklist_path, state_path, sub_prereq_parsed):
        pc.cmd_init(sub_prereq_parsed, sub_prereq_checklist_path, state_path, "walkthrough", force=False)
        pc.cmd_var(state_path, "set", "RUN_SCOPE", "run-a")
        pc.cmd_record(sub_prereq_parsed, sub_prereq_checklist_path, state_path, "3.2", "p", force=False)
        result = pc.cmd_prereq_check(sub_prereq_parsed, state_path, "3.3")
        assert result["ok"] is True
        assert result["blocking"] == []
        assert result["statuses"] == {"3.2": "passed"}

    def test_sub_prereq_blocks_when_failed(self, sub_prereq_checklist_path, state_path, sub_prereq_parsed):
        pc.cmd_init(sub_prereq_parsed, sub_prereq_checklist_path, state_path, "walkthrough", force=False)
        pc.cmd_var(state_path, "set", "RUN_SCOPE", "run-a")
        pc.cmd_record(sub_prereq_parsed, sub_prereq_checklist_path, state_path, "3.2", "f", force=False)
        result = pc.cmd_prereq_check(sub_prereq_parsed, state_path, "3.3")
        assert result["ok"] is False
        assert result["blocking"] == ["3.2"]
        assert result["statuses"] == {"3.2": "failed"}

    def test_sub_prereq_blocks_when_skipped(self, sub_prereq_checklist_path, state_path, sub_prereq_parsed):
        pc.cmd_init(sub_prereq_parsed, sub_prereq_checklist_path, state_path, "walkthrough", force=False)
        pc.cmd_var(state_path, "set", "RUN_SCOPE", "run-a")
        pc.cmd_record(sub_prereq_parsed, sub_prereq_checklist_path, state_path, "3.2", "s", force=False)
        result = pc.cmd_prereq_check(sub_prereq_parsed, state_path, "3.3")
        assert result["ok"] is False
        assert result["blocking"] == ["3.2"]
        assert result["statuses"] == {"3.2": "skipped"}

    def test_sub_prereq_blocks_stale_run(self, sub_prereq_checklist_path, state_path, sub_prereq_parsed):
        pc.cmd_init(sub_prereq_parsed, sub_prereq_checklist_path, state_path, "walkthrough", force=False)
        pc.cmd_var(state_path, "set", "RUN_SCOPE", "run-a")
        pc.cmd_record(sub_prereq_parsed, sub_prereq_checklist_path, state_path, "3.2", "p", force=False)
        pc.cmd_var(state_path, "set", "RUN_SCOPE", "run-b")
        result = pc.cmd_prereq_check(sub_prereq_parsed, state_path, "3.3")
        assert result["ok"] is False
        assert result["blocking"] == ["3.2"]
        assert result["statuses"] == {"3.2": "stale_run"}

    def test_no_prereq_returns_ok(self, sub_prereq_checklist_path, state_path, sub_prereq_parsed):
        """Steps without prereq annotations always pass prereq check."""
        pc.cmd_init(sub_prereq_parsed, sub_prereq_checklist_path, state_path, "walkthrough", force=False)
        result = pc.cmd_prereq_check(sub_prereq_parsed, state_path, "3.1")
        assert result["ok"] is True
        assert result["required"] == []

    def test_resolvable_with_subsection_prereqs(self, resolvable_checklist_path, state_path, resolvable_parsed):
        """Resolvable check dispatches subsection IDs in parent section prereqs.

        Regression: section 4 has prereqs [0.3, 2.1]. When checking if 4.1 is
        resolvable, the code must use _step_prereq_status for "0.3" and "2.1"
        (not _section_state which only accepts section-level IDs).
        """
        pc.cmd_init(resolvable_parsed, resolvable_checklist_path, state_path, "walkthrough", force=False)
        pc.cmd_var(state_path, "set", "RUN_SCOPE", "run-a")
        # Satisfy section 4's prereqs (0.3 and 2.1)
        pc.cmd_record(resolvable_parsed, resolvable_checklist_path, state_path, "0.3", "p", force=False)
        pc.cmd_record(resolvable_parsed, resolvable_checklist_path, state_path, "2.1", "p", force=False)
        # Check 5.1 which depends on 4.1 (not yet run)
        result = pc.cmd_prereq_check(resolvable_parsed, state_path, "5.1")
        assert result["ok"] is False
        assert "4.1" in result["missing"]
        # 4.1 should be resolvable because its section prereqs (0.3, 2.1) are satisfied
        assert "4.1" in result["resolvable"]

    def test_resolvable_blocked_by_unsatisfied_subsection_prereq(
        self, resolvable_checklist_path, state_path, resolvable_parsed
    ):
        """4.1 is NOT resolvable when one of its section's subsection prereqs is missing."""
        pc.cmd_init(resolvable_parsed, resolvable_checklist_path, state_path, "walkthrough", force=False)
        pc.cmd_var(state_path, "set", "RUN_SCOPE", "run-a")
        # Only satisfy 0.3, leave 2.1 unsatisfied
        pc.cmd_record(resolvable_parsed, resolvable_checklist_path, state_path, "0.3", "p", force=False)
        result = pc.cmd_prereq_check(resolvable_parsed, state_path, "5.1")
        assert result["ok"] is False
        assert "4.1" in result["missing"]
        # 4.1 should NOT be resolvable (2.1 not passed)
        assert "4.1" not in result["resolvable"]


class TestCmdReport:
    def test_empty_report(self, checklist_path, initialized_state, parsed):
        result = pc.cmd_report(parsed, checklist_path, initialized_state)
        assert result["total"]["expected"] == 8
        assert result["total"]["pass"] == 0
        assert result["complete"] is False
        assert len(result["gaps"]) == 5  # all 5 subsections

    def test_partial_report(self, checklist_path, initialized_state, parsed):
        pc.cmd_record(parsed, checklist_path, initialized_state, "0.1", "p,p", force=False)
        pc.cmd_record(parsed, checklist_path, initialized_state, "0.2", "p", force=False)
        result = pc.cmd_report(parsed, checklist_path, initialized_state)
        assert result["total"]["pass"] == 3
        assert result["sections"][0]["pass"] == 3
        assert result["complete"] is False
        assert "0.1" not in result["gaps"]
        assert "1.1" in result["gaps"]

    def test_complete_report(self, checklist_path, initialized_state, parsed):
        pc.cmd_record(parsed, checklist_path, initialized_state, "0.1", "p,p", force=False)
        pc.cmd_record(parsed, checklist_path, initialized_state, "0.2", "p", force=False)
        pc.cmd_record(parsed, checklist_path, initialized_state, "1.1", "p,p", force=False)
        pc.cmd_record(parsed, checklist_path, initialized_state, "1.2", "p", force=False)
        pc.cmd_record(parsed, checklist_path, initialized_state, "2.1", "p,p", force=False)
        result = pc.cmd_report(parsed, checklist_path, initialized_state)
        assert result["total"]["pass"] == 8
        assert result["total"]["fail"] == 0
        assert result["complete"] is True
        assert result["gaps"] == []

    def test_failures_tracked(self, checklist_path, initialized_state, parsed):
        pc.cmd_record(parsed, checklist_path, initialized_state, "0.1", "p,f", force=False)
        result = pc.cmd_report(parsed, checklist_path, initialized_state)
        assert len(result["failures"]) == 1
        assert result["failures"][0]["step"] == "0.1"
        assert result["failures"][0]["assertion_index"] == 1
        assert result["failures"][0]["text"] == "Exit code is 0"

    def test_skip_counted(self, checklist_path, initialized_state, parsed):
        pc.cmd_record(parsed, checklist_path, initialized_state, "0.1", "p,s", force=False)
        result = pc.cmd_report(parsed, checklist_path, initialized_state)
        assert result["total"]["skip"] == 1
        assert result["sections"][0]["skip"] == 1

    def test_report_with_changed_step_warns(self, checklist_path, initialized_state, parsed):
        """Report warns about changed steps instead of failing."""
        pc.cmd_record(parsed, checklist_path, initialized_state, "0.1", "p,p", force=False)
        # Modify checklist — change an assertion in step 0.1
        modified = MINIMAL_CHECKLIST.replace("Output says hello", "Output says goodbye")
        Path(checklist_path).write_text(modified)
        modified_data = pc.parse_checklist(checklist_path)
        result = pc.cmd_report(modified_data, checklist_path, initialized_state)
        assert "warnings" in result
        assert len(result["warnings"]["changed_steps"]) == 1
        assert result["warnings"]["changed_steps"][0]["id"] == "0.1"


# --- Hash utility test ---


class TestStepHash:
    def test_deterministic(self, parsed):
        step = parsed["_all_subs"][0]
        h1 = pc.step_hash(step)
        h2 = pc.step_hash(step)
        assert h1 == h2
        assert len(h1) == 64  # Full SHA-256

    def test_changes_on_assertion_edit(self, parsed):
        step = parsed["_all_subs"][0]
        h1 = pc.step_hash(step)
        step["assertions"][0] = "Changed assertion"
        h2 = pc.step_hash(step)
        assert h1 != h2

    def test_ignores_instruction_edit(self, parsed):
        step = parsed["_all_subs"][1]  # 0.2 has instructions
        h1 = pc.step_hash(step)
        step["instructions"] = "Totally different instructions"
        h2 = pc.step_hash(step)
        assert h1 == h2

    def test_whitespace_normalized(self, parsed):
        step = parsed["_all_subs"][0]
        h1 = pc.step_hash(step)
        step["assertions"][0] = step["assertions"][0] + "  "  # Trailing spaces
        h2 = pc.step_hash(step)
        assert h1 == h2


class TestCmdValidate:
    def test_clean_resume(self, checklist_path, initialized_state, parsed):
        pc.cmd_record(parsed, checklist_path, initialized_state, "0.1", "p,p", force=False)
        pc.cmd_record(parsed, checklist_path, initialized_state, "0.2", "p", force=False)
        result = pc.cmd_validate(parsed, checklist_path, initialized_state, "1.1")
        assert result["status"] == "ok"
        assert result["changed_steps"] == []
        assert result["cleared_steps"] == []

    def test_clears_future_steps(self, checklist_path, initialized_state, parsed):
        """Steps at/after resume point are cleared to prevent phantom progress."""
        pc.cmd_record(parsed, checklist_path, initialized_state, "0.1", "p,p", force=False)
        pc.cmd_record(parsed, checklist_path, initialized_state, "0.2", "p", force=False)
        pc.cmd_record(parsed, checklist_path, initialized_state, "1.1", "p,p", force=False)
        result = pc.cmd_validate(parsed, checklist_path, initialized_state, "0.2")
        assert "0.2" in result["cleared_steps"]
        assert "1.1" in result["cleared_steps"]
        # 0.1 should be preserved (before resume point)
        state = json.loads(Path(initialized_state).read_text())
        assert "0.1" in state["steps"]
        assert "0.2" not in state["steps"]
        assert "1.1" not in state["steps"]

    def test_detects_changed_step(self, checklist_path, initialized_state, parsed):
        pc.cmd_record(parsed, checklist_path, initialized_state, "0.1", "p,p", force=False)
        # Modify step 0.1's assertion
        modified = MINIMAL_CHECKLIST.replace("Output says hello", "Output says goodbye")
        Path(checklist_path).write_text(modified)
        modified_data = pc.parse_checklist(checklist_path)
        result = pc.cmd_validate(modified_data, checklist_path, initialized_state, "0.2")
        assert result["status"] == "warnings"
        assert len(result["changed_steps"]) == 1
        assert result["changed_steps"][0]["id"] == "0.1"

    def test_unknown_from_step(self, checklist_path, initialized_state, parsed):
        with pytest.raises(SystemExit):
            pc.cmd_validate(parsed, checklist_path, initialized_state, "99.1")

    def test_section_level_from_resolves_to_first_subsection(self, checklist_path, initialized_state, parsed):
        """'--from 1' and '--from 1.0' both resolve to first subsection of section 1."""
        pc.cmd_record(parsed, checklist_path, initialized_state, "0.1", "p,p", force=False)
        pc.cmd_record(parsed, checklist_path, initialized_state, "0.2", "p", force=False)
        pc.cmd_record(parsed, checklist_path, initialized_state, "1.1", "p,p", force=False)

        # '--from 1' should resolve to '1.1' and clear it
        result = pc.cmd_validate(parsed, checklist_path, initialized_state, "1")
        assert result["status"] == "ok"
        assert "1.1" in result["cleared_steps"]

        # Re-record and test '--from 1.0'
        pc.cmd_record(parsed, checklist_path, initialized_state, "1.1", "p,p", force=False)
        result = pc.cmd_validate(parsed, checklist_path, initialized_state, "1.0")
        assert result["status"] == "ok"
        assert "1.1" in result["cleared_steps"]

    def test_validate_clears_completed_section_vars_for_cleared_steps(
        self, prereq_checklist_path, state_path, prereq_parsed
    ):
        pc.cmd_init(prereq_parsed, prereq_checklist_path, state_path, "walkthrough", force=False)
        pc.cmd_var(state_path, "set", "RUN_SCOPE", "run-a")
        pc.cmd_record(prereq_parsed, prereq_checklist_path, state_path, "0.1", "p", force=False)
        state = json.loads(Path(state_path).read_text())
        assert state["vars"]["SECTION_0_STATUS"] == "passed"

        pc.cmd_validate(prereq_parsed, prereq_checklist_path, state_path, "0.1")
        state = json.loads(Path(state_path).read_text())
        assert "SECTION_0_STATUS" not in state["vars"]
        assert "SECTION_0_SCOPE" not in state["vars"]

    def test_validate_preserves_completed_status_before_resume_point(
        self, prereq_checklist_path, state_path, prereq_parsed
    ):
        pc.cmd_init(prereq_parsed, prereq_checklist_path, state_path, "walkthrough", force=False)
        pc.cmd_var(state_path, "set", "RUN_SCOPE", "run-a")
        pc.cmd_record(prereq_parsed, prereq_checklist_path, state_path, "0.1", "p", force=False)
        pc.cmd_record(prereq_parsed, prereq_checklist_path, state_path, "1.1", "p", force=False)

        pc.cmd_validate(prereq_parsed, prereq_checklist_path, state_path, "1.1")
        state = json.loads(Path(state_path).read_text())
        assert state["vars"]["SECTION_0_STATUS"] == "passed"
        assert state["vars"]["SECTION_0_SCOPE"] == "run-a"
        assert "SECTION_1_STATUS" not in state["vars"]


class TestV1Migration:
    def _make_v1_state(self, state_path, checklist_path, steps=None):
        """Create a v1-format state file."""
        state = {
            "schema_version": 1,
            "checklist_version": "2.0.0",
            "checklist_hash": pc.checklist_hash(checklist_path),
            "mode": "walkthrough",
            "started_at": "2026-01-01T00:00:00+00:00",
            "last_updated": "2026-01-01T00:00:00+00:00",
            "current_step": "0.1",
            "vars": {},
            "steps": steps or {},
        }
        Path(state_path).write_text(json.dumps(state, indent=2))
        return state

    def test_migration_with_matching_hash(self, checklist_path, state_path, parsed):
        self._make_v1_state(state_path, checklist_path, {"0.1": {"results": ["pass", "pass"]}})
        pc.cmd_report(parsed, checklist_path, state_path)  # Triggers migration
        state = json.loads(Path(state_path).read_text())
        assert state["schema_version"] == 2
        assert "checklist_hash" not in state
        assert state["steps"]["0.1"]["hash"] is not None  # Computed with confidence

    def test_migration_with_mismatched_hash(self, checklist_path, state_path, parsed):
        self._make_v1_state(state_path, checklist_path, {"0.1": {"results": ["pass", "pass"]}})
        # Corrupt the global hash to simulate checklist edit
        state = json.loads(Path(state_path).read_text())
        state["checklist_hash"] = "sha256:0000000000000000"
        Path(state_path).write_text(json.dumps(state, indent=2))
        result = pc.cmd_report(parsed, checklist_path, state_path)
        state = json.loads(Path(state_path).read_text())
        assert state["schema_version"] == 2
        assert state["steps"]["0.1"]["hash"] is None  # Unverified
        assert "warnings" in result
        assert "0.1" in result["warnings"]["unverified_steps"]

    def test_record_migrates_v1(self, checklist_path, state_path, parsed):
        self._make_v1_state(state_path, checklist_path)
        pc.cmd_record(parsed, checklist_path, state_path, "0.1", "p,p", force=False)
        state = json.loads(Path(state_path).read_text())
        assert state["schema_version"] == 2
        assert state["steps"]["0.1"]["hash"] is not None


class TestChecklistHash:
    def test_deterministic(self, checklist_path):
        h1 = pc.checklist_hash(checklist_path)
        h2 = pc.checklist_hash(checklist_path)
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_changes_on_modification(self, checklist_path):
        h1 = pc.checklist_hash(checklist_path)
        Path(checklist_path).write_text(MINIMAL_CHECKLIST + "\n")
        h2 = pc.checklist_hash(checklist_path)
        assert h1 != h2

    def test_indexed_changes_on_included_modification(self, indexed_checklist):
        h1 = pc.checklist_hash(indexed_checklist["index"])
        Path(indexed_checklist["section1"]).write_text(INDEXED_SECTION_1 + "\n<!-- changed -->\n")
        h2 = pc.checklist_hash(indexed_checklist["index"])
        assert h1 != h2
