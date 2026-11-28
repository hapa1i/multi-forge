"""Bound-rollout evidence for ordinary native headless resume accounting."""

import json
from pathlib import Path

import pytest

from forge.core.runtime.codex_resume_usage import capture_native_resume
from forge.core.runtime.codex_usage import CodexUsageBaseline

_THREAD = "d73669f8-e44c-482a-9b3c-4df19ef708c5"
_BEFORE = CodexUsageBaseline(100, 10, 20)
_AFTER = CodexUsageBaseline(130, 12, 25)


def _row(kind, **payload):
    return {"type": kind, "payload": payload}


def _event(kind, **payload):
    return _row("event_msg", type=kind, **payload)


def _counts(value):
    return {
        "input_tokens": value.input_tokens,
        "cached_input_tokens": value.cached_tokens,
        "output_tokens": value.output_tokens,
    }


def _sample(value):
    return _event("token_count", info={"total_token_usage": _counts(value)})


def _append(path, *rows):
    with path.open("ab") as stream:
        for row in rows:
            stream.write(json.dumps(row).encode() + b"\n")


@pytest.fixture
def rollout(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    day = tmp_path / "sessions/2026/11/28"
    day.mkdir(parents=True)
    path = day / f"rollout-2026-11-28T12-34-56-{_THREAD}.jsonl"
    _append(
        path,
        _row(
            "session_meta",
            id=_THREAD,
            model_provider="openai",
            originator="Codex Desktop",
        ),
        _row("world_state", state={}),
        _sample(_BEFORE),
    )
    return path


def test_adopted_history_and_multiple_native_requests(rollout):
    # A rejected launch appended no usage. The Desktop prefix did not use exec's turn grammar.
    _append(
        rollout,
        _event("task_started", turn_id="rejected"),
        _event("task_complete", turn_id="rejected"),
    )
    before = capture_native_resume(_THREAD, str(rollout))
    assert before is not None
    _append(
        rollout,
        _row("turn_context", turn_id="new"),
        _row(
            "token_usage_record",
            thread_id=_THREAD,
            turn_id="new",
            usage=_counts(CodexUsageBaseline(10, 1, 0)),
        ),
        _sample(CodexUsageBaseline(110, 11, 20)),
        _row(
            "token_usage_record",
            thread_id=_THREAD,
            turn_id="new",
            usage=_counts(CodexUsageBaseline(20, 1, 5)),
        ),
        _sample(_AFTER),
    )
    assert before.verified_baseline(_THREAD, _AFTER.as_dict()) == _BEFORE


def test_genuine_zero_and_distinct_returned_thread(rollout):
    before = capture_native_resume(_THREAD, str(rollout))
    assert before is not None
    assert before.verified_baseline(_THREAD, _BEFORE.as_dict()) is None
    _append(rollout, _row("turn_context", turn_id="new"), _sample(_BEFORE))
    assert before.verified_baseline(_THREAD, _BEFORE.as_dict()) == _BEFORE
    assert before.verified_baseline("other", _BEFORE.as_dict()) is None


@pytest.mark.parametrize(
    "rows",
    [
        [_row("compacted")],
        [_event("thread_rolled_back")],
        [_row("response_item", type="message", role="assistant")],
        [
            _event("task_started", turn_id="interrupted"),
            _event("item_completed", turn_id="interrupted", item={"type": "AgentMessage"}),
            _event("turn_aborted", turn_id="interrupted"),
        ],
        [_row("response_item", type="function_call")],
        [_row("token_usage_record", turn_id="interrupted", usage=_counts(_AFTER))],
        [_event("token_count", info={"total_token_usage": {"input_tokens": 20}})],
        [_row("event_msg", type=[])],
        [_sample(CodexUsageBaseline(90, 10, 10))],
    ],
)
def test_incomparable_prefix(rollout, rows):
    _append(rollout, *rows)
    assert capture_native_resume(_THREAD, str(rollout)) is None


@pytest.mark.parametrize(
    "rows",
    [
        [_event("task_started", turn_id="other")],
        [_row("session_meta", id=_THREAD, model_provider="openai")],
        [_row("compacted")],
        [_event("context_compacted")],
        [
            _event(
                "thread_settings_applied",
                thread_settings={"model_provider_id": "forge_proxy"},
            )
        ],
        [_row("turn_context", thread_id="another-thread")],
        [_row("token_usage_record", turn_id="new", session_id="other")],
        [_row("token_usage_record", turn_id="new", root_turn_id="other")],
        [_row("event_msg", type={})],
        [_event("turn_aborted", turn_id="new")],
        [
            _event(
                "task_complete",
                turn_id="new",
                error={"codex_error_info": "model_not_found"},
            )
        ],
        [_sample(_AFTER), _event("task_started", turn_id="new")],
        [
            _sample(_AFTER),
            _event("task_complete", turn_id="new"),
            _row("turn_context", turn_id="new"),
        ],
        [
            _row(
                "token_usage_record",
                turn_id="new",
                usage=_counts(CodexUsageBaseline(1, 1, 0)),
            )
        ],
        [_sample(CodexUsageBaseline(40, 1, 4))],
        [_sample(CodexUsageBaseline(102, 100, 110))],
    ],
)
def test_incomparable_suffix(rollout, rows):
    before = capture_native_resume(_THREAD, str(rollout))
    assert before is not None
    _append(rollout, _event("task_started", turn_id="new"), *rows, _sample(_AFTER))
    assert before.verified_baseline(_THREAD, _AFTER.as_dict()) is None


@pytest.mark.parametrize("damage", ["truncated", "rewritten", "replaced", "duplicate", "partial"])
def test_prefix_continuity(rollout, damage):
    before = capture_native_resume(_THREAD, str(rollout))
    assert before is not None
    data = rollout.read_bytes()
    if damage == "truncated":
        rollout.write_bytes(b"")
    elif damage == "rewritten":
        # Same path, inode, length, thread and token counts.
        rollout.write_bytes(data.replace(b"Codex Desktop", b"Codex DESKTOP"))
    elif damage == "replaced":
        replacement = rollout.with_suffix(".replacement")
        replacement.write_bytes(data)
        replacement.replace(rollout)
    elif damage == "duplicate":
        Path(str(rollout).replace("12-34-56", "12-34-57")).write_bytes(data)
    _append(rollout, _event("task_started", turn_id="new"), _sample(_AFTER))
    if damage == "partial":
        with rollout.open("ab") as stream:
            stream.write(b'{"type":')
    assert before.verified_baseline(_THREAD, _AFTER.as_dict()) is None


@pytest.mark.parametrize(
    "key,value",
    [("id", "foreign"), ("model_provider", "forge_proxy"), ("history_base", {})],
)
def test_unbound_header(rollout, key, value):
    header = {"id": _THREAD, "model_provider": "openai", key: value}
    rollout.write_bytes(b"")
    _append(rollout, _row("session_meta", **header), _sample(_BEFORE))
    assert capture_native_resume(_THREAD, str(rollout)) is None
