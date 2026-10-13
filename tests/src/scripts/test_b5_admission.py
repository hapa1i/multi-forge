"""Offline refusal controls for B5's experimental native-prefix selector."""

import json

import pytest

from tests.fixtures.codex_probe import load_script

ROOT = "00000000-0000-0000-0000-000000000001"
CHILD = "00000000-0000-0000-0000-000000000002"
TURN = "synthetic-turn"


@pytest.fixture
def admission():
    return load_script("b5-admission")


def _write(home, thread=ROOT, *, meta=None, body=None):
    path = home / f"sessions/2026/10/11/rollout-2026-10-11T00-00-00-{thread}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    head = {"id": thread, "session_id": thread, "cli_version": "0.162.1", "history_mode": "paginated"}
    head.update(meta or {})
    rows = [{"type": "session_meta", "payload": head}]
    rows.extend(
        body
        if body is not None
        else [
            {"type": "event_msg", "payload": {"type": "task_started", "turn_id": TURN}},
            {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": TURN}},
        ]
    )
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def _child(home, parent, *, changes=None):
    base = {"thread_id": ROOT, "end_ordinal_exclusive": 3, "end_byte_offset": len(parent.read_bytes())}
    base.update(changes or {})
    return _write(
        home,
        CHILD,
        meta={
            "forked_from_id": ROOT,
            "forked_from_ordinal_exclusive": base["end_ordinal_exclusive"],
            "history_base": base,
        },
    )


def test_parent_growth_does_not_expand_selected_ancestry(admission, tmp_path):
    parent = _write(tmp_path)
    original = parent.read_bytes()
    child = _child(tmp_path, parent)
    with parent.open("ab") as stream:
        stream.write(b'{"type":"event_msg","payload":{"type":"task_started","turn_id":"later"}}\n')
    prefixes = admission.select_prefixes(tmp_path, CHILD)
    assert [row["thread_id"] for row in prefixes] == [CHILD, ROOT]
    assert prefixes[0]["data"] == child.read_bytes()
    assert prefixes[1]["data"] == original


@pytest.mark.parametrize(
    "fault", ["missing", "duplicate", "cycle", "ordinal", "bytes", "identity", "format", "symlink"]
)
def test_malformed_ancestry_refuses_before_copy_or_dispatch(admission, tmp_path, fault):
    parent = _write(tmp_path)
    child = _child(tmp_path, parent)
    if fault == "missing":
        parent.unlink()
    elif fault == "duplicate":
        duplicate = tmp_path / "sessions/2026/10/12" / parent.name
        duplicate.parent.mkdir()
        duplicate.write_bytes(parent.read_bytes())
    elif fault == "cycle":
        content = child.read_text().replace(ROOT, CHILD)
        child.write_text(content)
    elif fault == "ordinal":
        _child(tmp_path, parent, changes={"end_ordinal_exclusive": 2})
    elif fault == "bytes":
        _child(tmp_path, parent, changes={"end_byte_offset": parent.stat().st_size - 1})
    elif fault == "identity":
        parent.write_text(parent.read_text().replace(ROOT, CHILD))
    elif fault == "format":
        parent.write_text(parent.read_text().replace("0.162.1", "future"))
    elif fault == "symlink":
        held = tmp_path / "held"
        parent.rename(held)
        parent.symlink_to(held)
    with pytest.raises(ValueError):
        admission.select_prefixes(tmp_path, CHILD)


def test_total_closure_limit_includes_ancestors(admission, tmp_path):
    parent = _write(tmp_path)
    child = _child(tmp_path, parent)
    with pytest.raises(ValueError, match="byte limit"):
        admission.select_prefixes(tmp_path, CHILD, max_bytes=child.stat().st_size + parent.stat().st_size - 1)


def test_complete_json_line_is_not_complete_tool_exchange(admission, tmp_path):
    source = _write(tmp_path)
    with source.open("a") as stream:
        stream.write(json.dumps({"type": "response_item", "payload": {"type": "function_call", "call_id": "x"}}) + "\n")
    with pytest.raises(ValueError, match="Unfinished"):
        admission.select_prefixes(tmp_path, ROOT)


def test_stop_requires_matching_final_answer_and_current_turn(admission, tmp_path):
    source = _write(
        tmp_path,
        body=[
            {"type": "event_msg", "payload": {"type": "task_started", "turn_id": TURN}},
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "phase": "final_answer",
                    "content": [{"type": "output_text", "text": "DONE"}],
                },
            },
        ],
    )
    stop = {
        "hook_event_name": "Stop",
        "session_id": ROOT,
        "turn_id": TURN,
        "transcript_path": str(source),
        "last_assistant_message": "DONE",
    }
    assert admission.select_prefixes(tmp_path, ROOT, stop=stop)[0]["data"] == source.read_bytes()
    for override in (
        {"turn_id": "old"},
        {"last_assistant_message": "old"},
        {"session_id": CHILD},
        {"hook_event_name": "PreToolUse"},
    ):
        with pytest.raises(ValueError, match="Stop boundary"):
            admission.select_prefixes(tmp_path, ROOT, stop={**stop, **override})
    with pytest.raises(ValueError, match="not complete"):
        admission.select_prefixes(tmp_path, ROOT)


@pytest.mark.parametrize("executor,trigger", [({ROOT}, "pre_tool_use"), (None, "pre_tool_use"), ({CHILD}, "stop")])
def test_missing_plan_refuses_shared_unknown_and_stop(admission, executor, trigger):
    with pytest.raises(ValueError, match="approved plan"):
        admission.require_plan({ROOT}, executor, " \n", trigger=trigger)
    assert admission.require_plan({ROOT}, executor, "approved", trigger=trigger) in {"shared", "unknown", "separate"}


def test_separate_complete_lineage_can_omit_plan_at_pretool(admission):
    assert admission.require_plan({ROOT}, {CHILD}, "", trigger="pre_tool_use") == "separate"
