"""B5 executor ancestry must not inherit the copied source's size or origin limits."""

import json
from dataclasses import replace

import pytest

from forge.core.native_review_types import NativeReviewBoundary
from forge.core.runtime import codex_review_source as source
from tests.fixtures.native_supervisor import (
    CHILD,
    THREAD,
    TURN,
    synthetic_rows,
    write_rollout,
)
from tests.src.core.runtime.test_codex_review_source import select
from tests.src.core.runtime.test_codex_review_source import source_home as source_home

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("trigger", ["pre-tool-use", "stop"])
@pytest.mark.parametrize("interactive", [False, True])
def test_long_executor_does_not_become_a_copied_source(source_home, trigger, interactive):
    write_rollout(source_home, synthetic_rows())
    bound = source.bind_source(THREAD, forge_root=None)
    executor = synthetic_rows(CHILD, complete=False)
    if interactive:
        executor[0]["payload"].update(originator="codex_cli_rs", source="cli", base_instructions={"text": "executor"})
        executor[0]["payload"].pop("creator_account_id")
    path = write_rollout(source_home, executor)
    # The executor body is never copied. Even an unfinished line can follow its
    # valid identity header during PreToolUse; growing it must not disable review.
    with path.open("ab") as stream:
        stream.write(b"x" * (source.MAX_PREFIX_BYTES + 1))
    boundary = NativeReviewBoundary(CHILD, TURN, str(path), "Stop" if trigger == "stop" else "PreToolUse")
    selected = select(bound, trigger=trigger, plan="Approved plan", executor_origin="codex", boundary=boundary)
    assert selected.independence == "separate"
    assert [prefix.thread_id for prefix in selected.prefixes] == [THREAD]
    with pytest.raises(ValueError, match="transcript"):
        select(
            bound,
            trigger=trigger,
            plan="Approved plan",
            executor_origin="codex",
            boundary=replace(boundary, transcript_path=bound.rollout_path),
        )
    # The same unsupported history still cannot be selected as a planning source.
    with pytest.raises(ValueError):
        source.bind_source(CHILD, forge_root=None)


def test_executor_ancestry_reads_only_bounded_headers_and_follows_deeper_lineage(source_home, monkeypatch):
    write_rollout(source_home, synthetic_rows())
    parent = THREAD
    ids = {parent}
    for number in range(3):
        child = f"01a12b73-202d-7dd0-a058-{number:012d}"
        rows = synthetic_rows(child)
        rows[0]["payload"].update(history_base={"thread_id": parent}, forked_from_id=parent)
        path = write_rollout(source_home, rows)
        with path.open("ab") as stream:
            stream.write(b"x" * (source.MAX_PREFIX_BYTES + 1))
        ids.add(child)
        parent = child
    read = source.read_regular
    sizes = []

    def bounded(path, **kwargs):
        data = read(path, **kwargs)
        sizes.append(len(data))
        return data

    monkeypatch.setattr(source, "read_regular", bounded)
    assert source._ancestry_ids(source_home, parent) == ids
    assert max(sizes) < 1024
    rows[0]["payload"].update(history_base={"thread_id": parent}, forked_from_id=parent)
    write_rollout(source_home, rows)
    with pytest.raises(ValueError, match="ancestry"):
        source._ancestry_ids(source_home, parent)


@pytest.mark.parametrize("header", [b"{}\n", b"[]\n", b"x" * (source.MAX_HEADER_BYTES + 1)])
def test_malformed_executor_headers_remain_unavailable(source_home, header):
    path = write_rollout(source_home, synthetic_rows())
    path.write_bytes(header)
    with pytest.raises(ValueError):
        source._ancestry_ids(source_home, THREAD)


def test_header_capture_tolerates_body_appends(source_home, monkeypatch):
    path = write_rollout(source_home, synthetic_rows())
    original = source.os.fstat
    calls = 0

    def append_after_first_stat(fd):
        nonlocal calls
        facts = original(fd)
        calls += 1
        if calls == 1:
            with path.open("ab") as stream:
                stream.write(json.dumps({"type": "event_msg", "payload": {}}).encode() + b"\n")
        return facts

    monkeypatch.setattr(source.os, "fstat", append_after_first_stat)
    assert source._ancestry_ids(source_home, THREAD) == {THREAD}


def test_header_capture_detects_mutation_even_in_the_read_buffer(source_home, monkeypatch):
    path = write_rollout(source_home, synthetic_rows())
    original = source.os.fstat
    calls = 0

    def change_after_read(fd):
        nonlocal calls
        facts = original(fd)
        calls += 1
        if calls == 2:
            with path.open("r+b") as stream:
                data = stream.read().replace(THREAD.encode(), CHILD.encode())
                stream.seek(0)
                stream.write(data)
        return facts

    monkeypatch.setattr(source.os, "fstat", change_after_read)
    with pytest.raises(ValueError, match="changed during capture"):
        source._ancestry_ids(source_home, THREAD)
