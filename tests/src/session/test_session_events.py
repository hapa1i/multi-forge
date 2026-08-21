"""Contract tests for the shared strict session-event journal."""

from __future__ import annotations

import json
import multiprocessing
import os
from dataclasses import asdict
from pathlib import Path

import pytest

from forge.session.events import (
    SessionEventPathError,
    SessionEventReadError,
    SessionEventValidationError,
    SessionEventWriteError,
    append_session_event,
    get_session_event_journal_path,
    new_session_event,
    read_session_events,
    validate_session_event,
)


def _event(session: str = "planner"):
    return new_session_event(
        session=session,
        runtime="claude_code",
        event_type="launch_preflight",
        run_id="run_0123456789ab",
        origin_surface="launcher",
        operation="start",
        outcome="success",
        reason_code=None,
        payload={"domain": "authority"},
    )


def _append_process(root: str, index: int) -> None:
    event = new_session_event(
        session="planner",
        runtime="claude_code",
        event_type="runtime_event",
        run_id=None,
        origin_surface="launcher",
        operation="runtime_event",
        outcome="success",
        reason_code=None,
        payload={"index": index},
    )
    append_session_event(root, "authority", event)


def test_event_round_trips_strictly(tmp_path: Path) -> None:
    (tmp_path / ".forge").mkdir()
    event = _event()

    path = append_session_event(tmp_path, "authority", event)

    assert path == tmp_path / ".forge" / "artifacts" / "planner" / "authority" / "events.jsonl"
    assert read_session_events(tmp_path, "planner", "authority") == [event]
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.read_text(encoding="utf-8").endswith("\n")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("event_id", "evt_bad"),
        ("timestamp", "2026-08-21T12:00:00"),
        ("timestamp", "2026-08-21T13:00:00+01:00"),
        ("timestamp", "2026-08-21T12:00:00,123Z"),
        ("session", "../escape"),
        ("runtime", "other"),
        ("event_type", "Bad Event"),
        ("run_id", "run_bad"),
        ("origin_surface", "other"),
        ("operation", "other"),
        ("operation", []),
        ("outcome", "other"),
        ("reason_code", "Not Stable"),
        ("payload", []),
    ],
)
def test_invalid_required_field_names_the_field(field: str, value: object) -> None:
    raw = asdict(_event())
    raw[field] = value

    with pytest.raises(SessionEventValidationError, match=field):
        validate_session_event(raw)


def test_unknown_and_missing_fields_are_errors() -> None:
    unknown = asdict(_event()) | {"extra": True}
    missing = asdict(_event())
    del missing["outcome"]

    with pytest.raises(SessionEventValidationError, match="unknown field.*extra"):
        validate_session_event(unknown)
    with pytest.raises(SessionEventValidationError, match="missing field.*outcome"):
        validate_session_event(missing)


@pytest.mark.parametrize("session", ["../planner", "/absolute", "a/b", ".", "a"])
def test_unsafe_session_paths_are_rejected_before_creation(tmp_path: Path, session: str) -> None:
    (tmp_path / ".forge").mkdir()

    with pytest.raises(SessionEventPathError):
        get_session_event_journal_path(tmp_path, session, "authority")

    assert not (tmp_path / ".forge" / "artifacts").exists()


def test_unknown_domain_is_rejected_without_creating_routing_path(
    tmp_path: Path,
) -> None:
    (tmp_path / ".forge").mkdir()

    with pytest.raises(SessionEventPathError, match="unsupported"):
        get_session_event_journal_path(tmp_path, "planner", "unknown")

    append_session_event(tmp_path, "authority", _event())
    assert not (tmp_path / ".forge" / "artifacts" / "planner" / "routing").exists()


def test_symlinked_artifact_component_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".forge").mkdir()
    os.symlink(outside, tmp_path / ".forge" / "artifacts")

    with pytest.raises(SessionEventPathError, match="symlink"):
        append_session_event(tmp_path, "authority", _event())

    assert list(outside.iterdir()) == []


def test_strict_reader_never_skips_a_bad_line(tmp_path: Path) -> None:
    (tmp_path / ".forge").mkdir()
    path = append_session_event(tmp_path, "authority", _event())
    with path.open("a", encoding="utf-8") as stream:
        stream.write("not json\n")

    with pytest.raises(SessionEventValidationError, match="record 2.*invalid JSON"):
        read_session_events(tmp_path, "planner", "authority")


def test_non_utf8_journal_is_a_typed_read_error(tmp_path: Path) -> None:
    (tmp_path / ".forge" / "artifacts" / "planner" / "authority").mkdir(parents=True)
    journal = tmp_path / ".forge" / "artifacts" / "planner" / "authority" / "events.jsonl"
    journal.write_bytes(b"\xff\n")

    with pytest.raises(SessionEventReadError, match="cannot read session-event journal"):
        read_session_events(tmp_path, "planner", "authority")


def test_strict_reader_rejects_missing_terminal_newline_and_duplicate_ids(
    tmp_path: Path,
) -> None:
    (tmp_path / ".forge").mkdir()
    path = append_session_event(tmp_path, "authority", _event())
    complete = path.read_text(encoding="utf-8")
    path.write_text(complete.rstrip("\n"), encoding="utf-8")

    with pytest.raises(SessionEventValidationError, match="truncated.*missing newline"):
        read_session_events(tmp_path, "planner", "authority")

    path.write_text(complete + complete, encoding="utf-8")
    with pytest.raises(SessionEventValidationError, match="record 2.*duplicate event id"):
        read_session_events(tmp_path, "planner", "authority")


def test_hard_linked_journal_is_rejected_without_external_write(tmp_path: Path) -> None:
    (tmp_path / ".forge" / "artifacts" / "planner" / "authority").mkdir(parents=True)
    external = tmp_path / "external.txt"
    external.write_text("outside\n", encoding="utf-8")
    journal = tmp_path / ".forge" / "artifacts" / "planner" / "authority" / "events.jsonl"
    os.link(external, journal)

    with pytest.raises(SessionEventWriteError, match="singly linked regular file"):
        append_session_event(tmp_path, "authority", _event())

    assert external.read_text(encoding="utf-8") == "outside\n"


def test_append_rejects_non_json_payload_without_stringifying_it(
    tmp_path: Path,
) -> None:
    (tmp_path / ".forge").mkdir()
    raw = asdict(_event())
    raw["payload"] = {"secret": object()}

    with pytest.raises(SessionEventValidationError, match="strict JSON"):
        append_session_event(tmp_path, "authority", raw)

    assert not (tmp_path / ".forge" / "artifacts").exists()


@pytest.mark.parametrize(
    "payload",
    [
        {1: "coerced-key"},
        {"tuple": ("coerced", "array")},
        {"infinite": float("inf")},
    ],
)
def test_append_rejects_values_json_would_coerce_or_relax(tmp_path: Path, payload: dict[object, object]) -> None:
    (tmp_path / ".forge").mkdir()
    raw = asdict(_event())
    raw["payload"] = payload

    with pytest.raises(SessionEventValidationError, match="strict JSON"):
        append_session_event(tmp_path, "authority", raw)

    assert not (tmp_path / ".forge" / "artifacts").exists()


def test_reader_adds_record_context_to_domain_payload_error(tmp_path: Path) -> None:
    (tmp_path / ".forge").mkdir()
    path = append_session_event(tmp_path, "authority", _event())

    def reject_payload(_event_type: str, _payload: dict[str, object]) -> None:
        raise SessionEventValidationError("domain mismatch", field="payload")

    with pytest.raises(SessionEventValidationError, match="record 1 field 'payload'.*domain mismatch"):
        read_session_events(
            tmp_path,
            "planner",
            "authority",
            payload_validator=reject_payload,
        )

    assert path.is_file()


def test_concurrent_process_appends_are_complete_and_unique(tmp_path: Path) -> None:
    (tmp_path / ".forge").mkdir()
    process_count = 12
    context = multiprocessing.get_context("spawn")
    processes = [context.Process(target=_append_process, args=(str(tmp_path), index)) for index in range(process_count)]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    path = get_session_event_journal_path(tmp_path, "planner", "authority")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == process_count
    assert all(isinstance(json.loads(line), dict) for line in lines)
    events = read_session_events(tmp_path, "planner", "authority")
    assert len({event.event_id for event in events}) == process_count
    assert {event.payload["index"] for event in events} == set(range(process_count))


def test_required_open_failure_is_typed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".forge").mkdir()

    def fail_open(*args: object, **kwargs: object) -> int:
        raise OSError("disk unavailable")

    monkeypatch.setattr(os, "open", fail_open)

    with pytest.raises(SessionEventWriteError, match="disk unavailable"):
        append_session_event(tmp_path, "authority", _event())
