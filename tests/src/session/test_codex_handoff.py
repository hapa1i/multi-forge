"""Tests for the staged-handoff files behind Codex SessionStart hook delivery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.session import codex_handoff
from forge.session.codex_handoff import (
    DeliveryReceipt,
    clear_pending_context,
    consume_pending_context,
    pending_context_path,
    read_receipt,
    receipt_path,
    stage_pending_context,
)

_BODY = "# Handoff context\n\nCURATED-BODY with unicode — and trailing spaces  \n"


def _consume(session_dir: Path) -> str | None:
    return consume_pending_context(
        session_dir,
        session_id="thread-uuid-1",
        transcript_path="/codex/sessions/rollout-thread-uuid-1.jsonl",
        source="startup",
    )


class TestStageAndConsume:
    def test_roundtrip_returns_staged_bytes_verbatim(self, tmp_path: Path) -> None:
        stage_pending_context(tmp_path, _BODY)
        assert _consume(tmp_path) == _BODY

    def test_stage_creates_parent_dirs(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "sessions" / "deep" / "name"
        path = stage_pending_context(session_dir, "x")
        assert path == pending_context_path(session_dir)
        assert path.read_text() == "x"

    def test_consume_writes_receipt_and_removes_pending(self, tmp_path: Path) -> None:
        stage_pending_context(tmp_path, _BODY)
        _consume(tmp_path)
        assert not pending_context_path(tmp_path).exists()
        data = json.loads(receipt_path(tmp_path).read_text())
        assert data["session_id"] == "thread-uuid-1"
        assert data["transcript_path"] == "/codex/sessions/rollout-thread-uuid-1.jsonl"
        assert data["source"] == "startup"
        assert data["delivered_at"]

    def test_consume_is_one_shot(self, tmp_path: Path) -> None:
        stage_pending_context(tmp_path, _BODY)
        assert _consume(tmp_path) == _BODY
        assert _consume(tmp_path) is None

    def test_consume_without_staging_returns_none_and_writes_no_receipt(self, tmp_path: Path) -> None:
        assert _consume(tmp_path) is None
        assert not receipt_path(tmp_path).exists()

    def test_receipt_write_failure_leaves_pending_intact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Receipt-before-consume: an unreceipted delivery would read as hook_undelivered,
        # so a failed receipt write must deliver nothing and keep the staged file.
        stage_pending_context(tmp_path, _BODY)

        def _boom(*args: object, **kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(codex_handoff, "atomic_write_json", _boom)
        assert _consume(tmp_path) is None
        assert pending_context_path(tmp_path).read_text() == _BODY
        assert not receipt_path(tmp_path).exists()


class TestClearPendingContext:
    def test_removes_staged_file(self, tmp_path: Path) -> None:
        stage_pending_context(tmp_path, _BODY)
        assert clear_pending_context(tmp_path) is True
        assert not pending_context_path(tmp_path).exists()

    def test_absent_returns_false(self, tmp_path: Path) -> None:
        assert clear_pending_context(tmp_path) is False


class TestReadReceipt:
    def test_missing_returns_none(self, tmp_path: Path) -> None:
        assert read_receipt(tmp_path) is None

    @pytest.mark.parametrize("raw", ["not json", "[]", "42", '{"transcript_path": "x"}', '{"session_id": ""}'])
    def test_malformed_returns_none(self, tmp_path: Path, raw: str) -> None:
        receipt_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        receipt_path(tmp_path).write_text(raw)
        assert read_receipt(tmp_path) is None

    def test_valid_roundtrip(self, tmp_path: Path) -> None:
        stage_pending_context(tmp_path, _BODY)
        _consume(tmp_path)
        receipt = read_receipt(tmp_path)
        assert isinstance(receipt, DeliveryReceipt)
        assert receipt.session_id == "thread-uuid-1"
        assert receipt.transcript_path == "/codex/sessions/rollout-thread-uuid-1.jsonl"
        assert receipt.source == "startup"

    def test_wrong_typed_optional_fields_degrade_to_none(self, tmp_path: Path) -> None:
        receipt_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        receipt_path(tmp_path).write_text(
            json.dumps(
                {
                    "session_id": "tid",
                    "delivered_at": "2026-06-11T00:00:00Z",
                    "transcript_path": 7,
                    "source": ["startup"],
                }
            )
        )
        receipt = read_receipt(tmp_path)
        assert receipt is not None
        assert receipt.transcript_path is None
        assert receipt.source is None
