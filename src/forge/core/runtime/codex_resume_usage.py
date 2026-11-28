"""Sample the bound native rollout around a headless Codex resume for token accounting."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from forge.core.runtime.codex_rollouts import (
    RolloutEvidenceError,
    decode_rollout_row,
    open_bound_rollout,
)
from forge.core.runtime.codex_usage import CodexUsageBaseline


@dataclass(frozen=True)
class NativeUsageUnavailable:
    reason: str

    @classmethod
    def from_error(cls, error: Exception) -> NativeUsageUnavailable:
        if isinstance(error, RolloutEvidenceError):
            return cls(str(error))
        # OS, path-resolution and decoder exceptions can contain private paths or native output.
        return cls("the native rollout could not be read or decoded")


@dataclass(frozen=True)
class NativeResumeSnapshot:
    """A comparable token sample and the exact rollout prefix that supplied it."""

    thread_id: str
    path: Path
    file_id: tuple[int, int]
    offset: int
    prefix_sha256: bytes
    baseline: CodexUsageBaseline
    previous_turn: str | None

    def verified_baseline(
        self, returned_thread: str | None, terminal: dict[str, int | None]
    ) -> CodexUsageBaseline | NativeUsageUnavailable:
        """Return the baseline only when a new sample independently corroborates the terminal counters."""
        if returned_thread != self.thread_id:
            return NativeUsageUnavailable("Codex did not confirm the resumed thread ID")
        try:
            with open_bound_rollout(self.thread_id, str(self.path)) as (
                _,
                stream,
                metadata,
            ):
                if self.file_id != (metadata.st_dev, metadata.st_ino) or metadata.st_size < self.offset:
                    return NativeUsageUnavailable("the bound rollout was replaced or truncated")
                if metadata.st_size == self.offset:
                    return NativeUsageUnavailable("the rollout has no new token sample")
                # Use bounded chunks for the old bytes; only the suffix needs JSON decoding.
                digest = hashlib.sha256()
                remaining = self.offset
                while remaining:
                    chunk = stream.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        return NativeUsageUnavailable("the bound rollout was truncated")
                    digest.update(chunk)
                    remaining -= len(chunk)
                if digest.digest() != self.prefix_sha256:
                    return NativeUsageUnavailable("the rollout prefix changed during the resume")
                after, turn = _samples(_records(stream), self.thread_id, baseline=self.baseline)
                if after is None or turn is None or turn == self.previous_turn:
                    return NativeUsageUnavailable("the rollout has no verifiable token sample for a new turn")
                if after.as_dict() != terminal:
                    return NativeUsageUnavailable("the reported terminal counters do not match the rollout totals")
                return self.baseline
        except (OSError, ValueError, RuntimeError) as error:
            return NativeUsageUnavailable.from_error(error)


def capture_native_resume(thread_id: str, bound_path: str | None) -> NativeResumeSnapshot | NativeUsageUnavailable:
    """Capture best-effort accounting evidence; a direct launch never depends on a readable rollout."""
    try:
        with open_bound_rollout(thread_id, bound_path) as (path, stream, metadata):
            digest = hashlib.sha256()
            rows = _records(stream, digest.update)
            kind, header = next(rows, ("", {}))
            if kind != "session_meta" or header.get("id") != thread_id or header.get("model_provider") != "openai":
                return NativeUsageUnavailable("the rollout does not identify the expected native OpenAI thread")
            if header.get("session_id", thread_id) != thread_id:
                return NativeUsageUnavailable("the rollout belongs to a subagent session")
            if any(
                header.get(key) is not None
                for key in ("history_base", "forked_from_id", "forked_from_ordinal_exclusive")
            ):
                return NativeUsageUnavailable("the thread was forked")
            baseline, turn = _samples(rows, thread_id)
            if baseline is None:
                return NativeUsageUnavailable("the pre-launch rollout has no verifiable token sample")
            return NativeResumeSnapshot(
                thread_id,
                path,
                (metadata.st_dev, metadata.st_ino),
                stream.tell(),
                digest.digest(),
                baseline,
                turn,
            )
    except (OSError, ValueError, RuntimeError) as error:
        return NativeUsageUnavailable.from_error(error)


def _records(
    stream: BinaryIO, update_hash: Callable[[bytes], None] | None = None
) -> Iterator[tuple[str, dict[str, Any]]]:
    for line in stream:
        if update_hash is not None:
            update_hash(line)
        yield decode_rollout_row(line)


def _samples(
    rows: Iterator[tuple[str, dict[str, Any]]],
    thread: str,
    *,
    baseline: CodexUsageBaseline | None = None,
) -> tuple[CodexUsageBaseline | None, str | None]:
    """Read totals across arbitrary clients' history. The new bytes must describe one identifiable turn."""
    turn = None
    latest = None
    previous = baseline
    expected_from_requests = None
    closed = False
    pending_turn = None
    for kind, payload in rows:
        event = payload.get("type") if kind == "event_msg" else None
        if kind == "event_msg" and not isinstance(event, str):
            raise RolloutEvidenceError("malformed rollout event type")
        if kind == "compacted" or event == "context_compacted":
            raise RolloutEvidenceError("the thread history contains compaction")
        if kind == "session_meta" or event == "thread_rolled_back":
            raise RolloutEvidenceError("the rollout counter history changed")
        if event == "thread_settings_applied":
            settings = payload.get("thread_settings")
            if isinstance(settings, dict) and settings.get("model_provider_id", "openai") != "openai":
                raise RolloutEvidenceError("rollout changed provider")
        observed = _record_turn(kind, event, payload, thread)
        if baseline is None:
            # Some clients omit lifecycle records. When an explicit start is still open, its usage may arrive late.
            if event == "task_started":
                pending_turn = observed
            elif event in {"task_complete", "turn_aborted"} and observed == pending_turn:
                pending_turn = None
        else:
            if event in {"turn_aborted", "error"} or (event == "task_complete" and payload.get("error") is not None):
                raise RolloutEvidenceError("native turn did not complete successfully")
            if (event == "task_started" and turn is not None) or (
                closed and (observed is not None or event == "token_count")
            ):
                raise RolloutEvidenceError("more than one native turn in the launch window")
            closed |= event == "task_complete"
        if observed is not None:
            if baseline is not None and turn is not None and observed != turn:
                raise RolloutEvidenceError("ambiguous turn in rollout window")
            turn = observed
        if kind == "token_usage_record":
            latest = None  # Wait for the corresponding total before accepting a new baseline.
            if baseline is not None:
                usage = CodexUsageBaseline.from_total_usage(payload.get("usage"))
                if usage is None or observed is None or usage.cached_tokens > usage.input_tokens:
                    raise RolloutEvidenceError("unverifiable request usage")
                expected = expected_from_requests or baseline
                expected_from_requests = CodexUsageBaseline(
                    expected.input_tokens + usage.input_tokens,
                    expected.output_tokens + usage.output_tokens,
                    expected.cached_tokens + usage.cached_tokens,
                )
        elif _generation_evidence(kind, event, payload):
            latest = None  # An interrupted generation can end before its token_count is flushed.
        elif event == "token_count" and payload.get("info") is not None:
            sample = CodexUsageBaseline.from_token_info(payload["info"])
            if sample is None or sample.cached_tokens > sample.input_tokens:
                raise RolloutEvidenceError("malformed native token sample")
            if baseline is not None and turn is None and sample != baseline:
                raise RolloutEvidenceError("usage changed before the resumed turn was identified")
            if previous and (
                sample.input_tokens < previous.input_tokens
                or sample.output_tokens < previous.output_tokens
                or sample.cached_tokens < previous.cached_tokens
            ):
                raise RolloutEvidenceError("native counter series decreased")
            previous = sample
            latest = sample if baseline is None or turn is not None else None
    if pending_turn is not None:
        raise RolloutEvidenceError("the preceding native turn is still open")
    if expected_from_requests is not None and latest != expected_from_requests:
        raise RolloutEvidenceError("the rollout total does not match its request usage")
    return latest, turn


def _generation_evidence(kind: str, event: str | None, payload: dict[str, Any]) -> bool:
    if kind == "response_item":
        # New exec versions also write developer-role additional_tools before the request.
        return payload.get("role") not in ("user", "developer", "system")
    if event == "item_completed":
        item = payload.get("item")
        return not isinstance(item, dict) or item.get("type") != "UserMessage"
    return event in {"agent_message", "agent_reasoning"}


def _record_turn(kind: str, event: str | None, payload: dict[str, Any], thread: str) -> str | None:
    if kind not in {"turn_context", "token_usage_record"} and event not in {
        "task_started",
        "task_complete",
        "turn_aborted",
        "thread_settings_applied",
        "token_count",
        "item_completed",
    }:
        return None
    if payload.get("thread_id", thread) != thread or payload.get("session_id", thread) != thread:
        raise RolloutEvidenceError("rollout record belongs to another thread")
    observed = payload.get("turn_id")
    if observed is not None and (
        not isinstance(observed, str) or not observed or payload.get("root_turn_id", observed) != observed
    ):
        raise RolloutEvidenceError("unverifiable foreground turn identity")
    return observed
