"""Bounded, immutable native inputs for the empirically admitted Codex fork format.

Discovery reuses the native resolver, but never its newest-match shortcut. Reads
walk directory descriptors without following symlinks and pin regular files for
the duration of capture. No rendered transcript or newest-thread fallback exists.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from forge.core.invoker.codex_fork import CodexUsageBaseline
from forge.core.native_review_types import NativeReviewBoundary
from forge.core.runtime.codex_rollouts import codex_home, find_rollouts_by_thread_id
from forge.session.models import NativeSupervisorSource

MAX_PREFIX_BYTES = 1_827_328
MAX_CONTEXT_INPUT = 163_002
SHORT_PREFIX_BYTES = 80_549
MAX_FILES = 2
MAX_HEADER_BYTES = 262_144
MAX_EXECUTOR_ANCESTORS = 128
THREAD_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
ADMITTED_MODELS = {"gpt-6.1-sol", "gpt-6-sol"}
# Default instructions observed on the retained executable, not user customizations.
BASE_INSTRUCTIONS = {
    "7069420faaff7acefd4d0159ecb873af18ee9ae038d38fda93d9cef759086503",
    "0d89fa1593e7930e7186c317154ec9c352ef9b82e6c9034bf2bb62be1129941d",
}


@dataclass(frozen=True)
class NativePrefix:
    thread_id: str
    path: Path
    data: bytes = field(repr=False)
    rows: tuple[dict[str, Any], ...] = field(repr=False)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def metadata(self) -> dict[str, Any]:
        return self.rows[0]["payload"]

    def evidence(self) -> dict[str, Any]:
        return dict(thread_id=self.thread_id, sha256=self.digest, bytes=len(self.data), records=len(self.rows))


@dataclass(frozen=True)
class NativeSelection:
    prefixes: tuple[NativePrefix, ...]
    baseline: CodexUsageBaseline | None
    independence: str
    context_input: int

    def evidence(self) -> dict[str, Any]:
        return {
            "runtime": "codex",
            "prefixes": [prefix.evidence() for prefix in self.prefixes],
            "independence": self.independence,
            "source_context_input": self.context_input,
            "usage_baseline": self.baseline.as_dict() if self.baseline else None,
            "baseline_origin": "event_msg.token_count.info.total_token_usage",
        }


@contextmanager
def directory_fd(path: Path) -> Iterator[int]:
    """Pin each directory component, including the owned home itself."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Expected an absolute native-store path")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def read_regular(path: Path, *, limit: int, end: int | None = None, header_only: bool = False) -> bytes:
    """Capture a stable bounded file/prefix without following directory or leaf links."""
    if limit <= 0 or (end is not None and (type(end) is not int or not 0 < end <= limit)):
        raise ValueError("Native input exceeds the admitted byte limit")
    with directory_fd(path.parent) as parent:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ValueError("Native input must be a regular, unlinked file")
            data = stream.readline(limit + 1) if header_only else stream.read(end if end is not None else limit + 1)
            after = os.fstat(fd)
            if header_only:
                # Active executors append during PreToolUse. Pin and reread the
                # header itself; growth beyond that line does not change ancestry.
                if not data.endswith(b"\n") or os.pread(fd, len(data), 0) != data:
                    raise ValueError("Native metadata header is incomplete or changed during capture")
            elif (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("Native input changed during capture; review unavailable")
    if len(data) > limit or (end is not None and len(data) != end):
        raise ValueError("Native input exceeds limit or required prefix is missing")
    return data


def select_prefixes(
    home: Path, thread_id: str, *, boundary: NativeReviewBoundary | None = None
) -> tuple[NativePrefix, ...]:
    """Capture a root or one fork generation, verifying every byte/ordinal boundary."""
    home = home.expanduser().resolve(strict=True)
    selected: list[NativePrefix] = []
    ordinal = end = None
    while True:
        if not THREAD_ID.fullmatch(thread_id) or thread_id in {p.thread_id for p in selected}:
            raise ValueError("Unrecognized or cyclic native ancestry")
        if len(selected) >= MAX_FILES:
            raise ValueError("Native ancestry exceeds the admitted one-generation limit")
        paths = find_rollouts_by_thread_id(thread_id, home=home)
        if len(paths) != 1:
            raise ValueError("Native source is missing or ambiguous; select a confirmed full thread ID")
        path = paths[0]
        path.relative_to(home)
        data = read_regular(path, limit=MAX_PREFIX_BYTES - sum(len(p.data) for p in selected), end=end)
        if not data or not data.endswith(b"\n"):
            raise ValueError("Native source has an incomplete JSONL boundary")
        rows = tuple(json.loads(line) for line in data.splitlines())
        if any(
            not isinstance(row, dict)
            or not isinstance(row.get("payload"), dict)
            or row.get("type")
            not in (
                "session_meta",
                "event_msg",
                "response_item",
                "world_state",
                "turn_context",
                "token_usage_record",
                "compacted",
            )
            for row in rows
        ):
            raise ValueError("Malformed native source record")
        if sum(row["type"] == "session_meta" for row in rows) != 1:
            raise ValueError("Ambiguous native metadata")
        prefix = NativePrefix(thread_id, path, data, rows)
        _validate_metadata(prefix)
        if ordinal is not None and len(rows) != ordinal:
            raise ValueError("Ancestor byte and ordinal boundaries disagree")
        _check_boundary(prefix, boundary if not selected and boundary and boundary.thread_id == thread_id else None)
        selected.append(prefix)
        base = prefix.metadata.get("history_base")
        if base is None:
            if any(prefix.metadata.get(k) is not None for k in ("forked_from_id", "forked_from_ordinal_exclusive")):
                raise ValueError("Native fork is missing its history base")
            return tuple(selected)
        if not isinstance(base, dict) or set(base) != {"thread_id", "end_ordinal_exclusive", "end_byte_offset"}:
            raise ValueError("Unrecognized native history base")
        parent, ordinal, end = base["thread_id"], base["end_ordinal_exclusive"], base["end_byte_offset"]
        if (
            not isinstance(parent, str)
            or type(ordinal) is not int
            or ordinal <= 0
            or type(end) is not int
            or end <= 0
            or prefix.metadata.get("forked_from_id") != parent
            or prefix.metadata.get("forked_from_ordinal_exclusive") != ordinal
        ):
            raise ValueError("Inconsistent native ancestry")
        thread_id = parent


def bind_source(target: str, *, forge_root: str | None) -> NativeSupervisorSource:
    """Resolve a managed confirmed ID or an explicit native ID, without adoption."""
    from forge.session.manager import SessionManager
    from forge.session.models import session_runtime

    home = codex_home().expanduser().resolve(strict=True)
    name = root = None
    thread_id = target
    expected_path = None
    if not THREAD_ID.fullmatch(target):
        state = SessionManager().get_session(target, forge_root=forge_root)
        codex = state.confirmed.codex
        if session_runtime(state) != "codex" or not codex or not codex.thread_id or not codex.rollout_path:
            raise ValueError("Native source requires a managed session with a confirmed Codex rollout")
        thread_id, expected_path = codex.thread_id, codex.rollout_path
        name, root = state.name, state.forge_root or forge_root
        if not root:
            raise ValueError("Managed native source has no recorded Forge root")
    # Setup accepts only complete sources. Active Stop selection is attempt-owned.
    selected = select_prefixes(home, thread_id)
    first = selected[0]
    if expected_path and first.path != Path(expected_path).resolve(strict=True):
        raise ValueError("Managed source rollout does not match the selected native home")
    return NativeSupervisorSource(
        runtime="codex",
        thread_id=thread_id,
        home=str(home),
        rollout_path=str(first.path),
        source_cwd=first.metadata["cwd"],
        header_digest=hashlib.sha256(first.data.splitlines(keepends=True)[0]).hexdigest(),
        managed_session=name,
        managed_root=root,
    )


def select_source(
    source: NativeSupervisorSource,
    *,
    model: str,
    auth_mode: str,
    plan: str,
    trigger: str,
    executor_origin: str,
    boundary: NativeReviewBoundary | None,
) -> NativeSelection:
    """Revalidate identity, provenance, ancestry and the admitted trigger on each review."""
    if source.managed_session:
        from forge.session.manager import SessionManager
        from forge.session.models import session_runtime

        state = SessionManager().get_session(source.managed_session, forge_root=source.managed_root)
        codex = state.confirmed.codex
        if (
            session_runtime(state) != "codex"
            or not codex
            or codex.thread_id != source.thread_id
            or not codex.rollout_path
            or Path(codex.rollout_path).resolve(strict=True) != Path(source.rollout_path).resolve(strict=True)
        ):
            raise ValueError("Managed native source binding changed; remove and reconfigure supervision")
    prefixes = select_prefixes(Path(source.home), source.thread_id, boundary=boundary if trigger == "stop" else None)
    first = prefixes[0]
    if (
        first.path != Path(source.rollout_path).resolve(strict=True)
        or first.metadata["cwd"] != source.source_cwd
        or hashlib.sha256(first.data.splitlines(keepends=True)[0]).hexdigest() != source.header_digest
    ):
        raise ValueError("Native source identity changed; remove and reconfigure supervision")
    independence = "unknown"
    if executor_origin == "claude_code":
        independence = "separate"
    elif executor_origin == "codex" and boundary:
        # The installed hook/journal establishes the executor turn. Only histories
        # copied into the reviewer need source format, size and final-answer checks.
        executor_ids = _ancestry_ids(codex_home(), boundary.thread_id, transcript_path=boundary.transcript_path)
        independence = "shared" if executor_ids & {p.thread_id for p in prefixes} else "separate"
    if trigger == "pre-tool-use" and independence != "separate":
        raise ValueError("Shared or unknown native ancestry requires host Codex Stop with an approved plan")
    if trigger == "stop" and (not plan.strip() or not boundary or boundary.event != "Stop"):
        raise ValueError("Native Stop review requires an approved plan and verified executor boundary")
    models: set[str] = set()
    info: dict[str, Any] | None = None
    compacted = False
    maximum_input = 0
    for prefix in reversed(prefixes):
        for row in prefix.rows:
            payload = row["payload"]
            compacted |= row["type"] == "compacted"
            if row["type"] == "turn_context":
                value = payload.get("model")
                if not isinstance(value, str) or value not in ADMITTED_MODELS:
                    raise ValueError("Source contains an untested historical model")
                models.add(value)
            if row["type"] == "event_msg" and payload.get("type") == "token_count" and payload.get("info"):
                candidate = payload["info"]
                if not isinstance(candidate, dict) or not isinstance(candidate.get("last_token_usage"), dict):
                    raise ValueError("Unverifiable source usage counters")
                info = candidate
                current = candidate["last_token_usage"].get("input_tokens")
                if type(current) is not int or current < 0:
                    raise ValueError("Unverifiable source context size")
                maximum_input = max(maximum_input, current)
    if not models or not info or maximum_input > MAX_CONTEXT_INPUT:
        raise ValueError("Source context is unknown or exceeds the admitted token limit")
    large = compacted or sum(len(p.data) for p in prefixes) > SHORT_PREFIX_BYTES
    active = boundary and source.thread_id == boundary.thread_id
    if (large or active) and (models != {"gpt-6.1-sol"} or model != "gpt-6.1-sol" or auth_mode != "subscription-only"):
        raise ValueError("Long, compacted and active sources require subscription gpt-6.1-sol")
    usage = info.get("total_token_usage", {})
    if not isinstance(usage, dict):
        usage = {}
    values = [
        value
        for key in ("input_tokens", "output_tokens", "cached_input_tokens")
        if type(value := usage.get(key)) is int and value >= 0
    ]
    baseline = CodexUsageBaseline(values[0], values[1], values[2]) if len(values) == 3 else None
    return NativeSelection(prefixes, baseline, independence, maximum_input)


def boundary_from_hook(payload: dict[str, Any], *, admitted: bool = False) -> NativeReviewBoundary | None:
    """Accept payload identity only from the version-admitted managed executor.

    ``admitted`` skips a repeated process probe when the caller already passed it.
    """
    from forge.core.runtime.codex_feedback import stop_review_supported

    if not admitted and not stop_review_supported(os.environ):
        return None
    fields = [
        value
        for key in ("session_id", "turn_id", "transcript_path", "hook_event_name")
        if isinstance(value := payload.get(key), str) and value
    ]
    if len(fields) != 4:
        return None
    if not THREAD_ID.fullmatch(fields[0]) or not THREAD_ID.fullmatch(fields[1]) or not Path(fields[2]).is_absolute():
        return None
    answer = payload.get("last_assistant_message")
    return NativeReviewBoundary(fields[0], fields[1], fields[2], fields[3], answer if isinstance(answer, str) else None)


def _validate_metadata(prefix: NativePrefix) -> None:
    meta = prefix.metadata
    if (
        prefix.rows[0].get("type") != "session_meta"
        or meta.get("id") != prefix.thread_id
        or meta.get("session_id") != prefix.thread_id
    ):
        raise ValueError("Native metadata identity mismatch")
    if meta.get("cli_version") != "0.162.1" or meta.get("history_mode") != "paginated":
        raise ValueError("Unproven native history format; B5 admits Codex 0.162.1 paginated histories")
    if meta.get("originator") != "codex_exec" or meta.get("source") != "exec" or meta.get("model_provider") != "openai":
        raise ValueError("Unproven native source origin or provider")
    digest = hashlib.sha256(
        json.dumps(meta.get("base_instructions"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if digest not in BASE_INSTRUCTIONS:
        raise ValueError("Unproven native base-instruction customization")
    if not isinstance(meta.get("creator_account_id"), str) or not meta["creator_account_id"]:
        raise ValueError("Historical source account provenance is unavailable")
    if not isinstance(meta.get("cwd"), str) or not Path(meta["cwd"]).is_absolute():
        raise ValueError("Native source has no absolute launch directory")


def _ancestry_ids(home: Path, thread_id: str, *, transcript_path: str | None = None) -> set[str]:
    """Read only headers: the current executor's tool exchange may be unfinished."""
    home = home.expanduser().resolve(strict=True)
    seen: set[str] = set()
    while True:
        if (
            not isinstance(thread_id, str)
            or not THREAD_ID.fullmatch(thread_id)
            or thread_id in seen
            or len(seen) >= MAX_EXECUTOR_ANCESTORS
        ):
            raise ValueError("Executor ancestry cannot be verified")
        paths = find_rollouts_by_thread_id(thread_id, home=home)
        if len(paths) != 1:
            raise ValueError("Executor native rollout is missing or ambiguous")
        if not seen and transcript_path and paths[0] != Path(transcript_path).resolve(strict=True):
            raise ValueError("Executor transcript does not match its native thread")
        row = json.loads(read_regular(paths[0], limit=MAX_HEADER_BYTES, header_only=True))
        if not isinstance(row, dict) or row.get("type") != "session_meta" or not isinstance(row.get("payload"), dict):
            raise ValueError("Executor native metadata is unverified")
        meta = row["payload"]
        if meta.get("id") != thread_id or meta.get("cli_version") != "0.162.1":
            raise ValueError("Executor native identity is unverified")
        seen.add(thread_id)
        base = meta.get("history_base")
        if base is None:
            if meta.get("forked_from_id"):
                raise ValueError("Executor ancestry is incomplete")
            return seen
        if (
            not isinstance(base, dict)
            or not isinstance(base.get("thread_id"), str)
            or base["thread_id"] != meta.get("forked_from_id")
        ):
            raise ValueError("Executor ancestry is inconsistent")
        thread_id = base["thread_id"]


def _check_boundary(prefix: NativePrefix, boundary: NativeReviewBoundary | None) -> None:
    pending: set[str] = set()
    started = finished = message = None
    for row in prefix.rows:
        payload = row["payload"]
        kind = payload.get("type")
        if row["type"] == "response_item":
            if kind not in (
                "message",
                "function_call",
                "custom_tool_call",
                "function_call_output",
                "custom_tool_call_output",
            ):
                raise ValueError("Unproven native response item format")
            if kind in {"function_call", "custom_tool_call", "function_call_output", "custom_tool_call_output"}:
                call = payload.get("call_id")
                if not isinstance(call, str) or not call:
                    raise ValueError("Missing native call identity")
                if kind.endswith("_output"):
                    if call not in pending:
                        raise ValueError("Unmatched native tool output")
                    pending.remove(call)
                elif call in pending:
                    raise ValueError("Duplicate native tool call")
                else:
                    pending.add(call)
            elif kind == "message" and payload.get("role") == "assistant":
                message = payload
        elif row["type"] == "event_msg":
            if kind == "task_started":
                started, finished, message = payload.get("turn_id"), None, None
            elif kind == "task_complete":
                finished = payload.get("turn_id")
    if pending or not started:
        raise ValueError("Unfinished native tool exchange or unknown turn boundary")
    if boundary is None:
        if finished != started:
            raise ValueError("Native source turn is not complete")
        return
    text = (
        "".join(item.get("text", "") for item in message.get("content", []) if item.get("type") == "output_text")
        if message
        else None
    )
    if (
        boundary.event != "Stop"
        or boundary.turn_id != started
        or Path(boundary.transcript_path).resolve(strict=True) != prefix.path
        or finished is not None
        or not message
        or message.get("phase") != "final_answer"
        or not text
        or text != boundary.last_assistant_message
    ):
        raise ValueError("Native Stop boundary does not match the captured final answer")
