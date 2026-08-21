"""Strict, authority-neutral session event journals.

The envelope and append mechanics are shared by session evidence domains. Each
domain keeps its own journal and supplies its own event/payload validator.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from forge.core.run_id import is_valid_run_id
from forge.core.runtime_vocab import AGENT_RUNTIME_IDS
from forge.core.state import file_lock_for_target, parse_iso, utc_timestamp_z

from .exceptions import ForgeSessionError, InvalidSessionNameError
from .validation import validate_name

SESSION_EVENT_SCHEMA_VERSION = 1
SESSION_EVENT_DOMAINS = frozenset({"authority", "routing"})
SESSION_EVENT_ORIGINS = frozenset(
    {
        "external_cli",
        "session_derivation",
        "launcher",
        "claude_authority_hook",
        "codex_policy_hook",
    }
)
SESSION_EVENT_OPERATIONS = frozenset(
    {
        "start",
        "resume",
        "fork",
        "incognito",
        "set",
        "clear",
        "tool_request",
        "runtime_event",
    }
)
SESSION_EVENT_OUTCOMES = frozenset({"success", "denied", "refused", "cancelled", "error"})
SESSION_EVENT_LOCK_TIMEOUT_S = 5.0

_EVENT_ID_RE = re.compile(r"^sevt_[0-9a-f]{32}$")
_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_RFC3339_UTC_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|\+00:00)$")
_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "timestamp",
        "session",
        "runtime",
        "event_type",
        "run_id",
        "origin_surface",
        "operation",
        "outcome",
        "reason_code",
        "payload",
    }
)


class SessionEventError(ForgeSessionError):
    """Base error for strict session-event state."""


class SessionEventPathError(SessionEventError):
    """The requested journal path is outside the supported contained shape."""


class SessionEventValidationError(SessionEventError):
    """A session-event record violates the shared envelope contract."""

    def __init__(self, reason: str, *, record: int | None = None, field: str | None = None) -> None:
        prefix = f"session event record {record}" if record is not None else "session event"
        if field is not None:
            prefix += f" field '{field}'"
        super().__init__(f"{prefix}: {reason}")
        self.record = record
        self.field = field
        self.reason = reason


class SessionEventWriteError(SessionEventError):
    """A required event append did not durably complete."""


class SessionEventReadError(SessionEventError):
    """A journal could not be read as a complete ordered event sequence."""


@dataclass(frozen=True)
class SessionEvent:
    """Schema-v1 shared event envelope with a domain-owned payload."""

    schema_version: int
    event_id: str
    timestamp: str
    session: str
    runtime: str
    event_type: str
    run_id: str | None
    origin_surface: str
    operation: str | None
    outcome: str
    reason_code: str | None
    payload: dict[str, Any]


SessionEventPayloadValidator = Callable[[str, dict[str, Any]], None]
SessionEventValidator = Callable[[SessionEvent], None]


def mint_session_event_id() -> str:
    """Mint an opaque id shared by all session-journal domains."""
    return f"sevt_{uuid.uuid4().hex}"


def new_session_event(
    *,
    session: str,
    runtime: str,
    event_type: str,
    run_id: str | None,
    origin_surface: str,
    operation: str | None,
    outcome: str,
    reason_code: str | None,
    payload: dict[str, Any],
    payload_validator: SessionEventPayloadValidator | None = None,
    event_validator: SessionEventValidator | None = None,
) -> SessionEvent:
    """Construct and validate one event using current id and UTC time."""
    event = SessionEvent(
        schema_version=SESSION_EVENT_SCHEMA_VERSION,
        event_id=mint_session_event_id(),
        timestamp=utc_timestamp_z(),
        session=session,
        runtime=runtime,
        event_type=event_type,
        run_id=run_id,
        origin_surface=origin_surface,
        operation=operation,
        outcome=outcome,
        reason_code=reason_code,
        payload=payload,
    )
    return validate_session_event(
        asdict(event),
        expected_session=session,
        payload_validator=payload_validator,
        event_validator=event_validator,
    )


def validate_session_event(
    record: dict[str, Any],
    *,
    expected_session: str | None = None,
    payload_validator: SessionEventPayloadValidator | None = None,
    event_validator: SessionEventValidator | None = None,
    record_number: int | None = None,
) -> SessionEvent:
    """Validate one shared envelope and its optional domain payload contract."""
    if not isinstance(record, dict):
        raise SessionEventValidationError("expected a JSON object", record=record_number)

    unknown = set(record) - _ENVELOPE_FIELDS
    missing = _ENVELOPE_FIELDS - set(record)
    if unknown:
        raise SessionEventValidationError(f"unknown field(s): {', '.join(sorted(unknown))}", record=record_number)
    if missing:
        raise SessionEventValidationError(f"missing field(s): {', '.join(sorted(missing))}", record=record_number)

    schema_version = record["schema_version"]
    if type(schema_version) is not int or schema_version != SESSION_EVENT_SCHEMA_VERSION:
        raise SessionEventValidationError(
            f"unsupported schema version {schema_version!r}; expected {SESSION_EVENT_SCHEMA_VERSION}",
            record=record_number,
            field="schema_version",
        )

    _require_string(record, "event_id", record_number)
    if _EVENT_ID_RE.fullmatch(record["event_id"]) is None:
        raise SessionEventValidationError("must match sevt_<32 lowercase hex>", record=record_number, field="event_id")

    timestamp = _require_string(record, "timestamp", record_number)
    try:
        parse_iso(timestamp)
    except ValueError as exc:
        raise SessionEventValidationError(
            "must be an RFC 3339 timestamp", record=record_number, field="timestamp"
        ) from exc
    if _RFC3339_UTC_RE.fullmatch(timestamp) is None:
        raise SessionEventValidationError("must be an RFC 3339 UTC timestamp", record=record_number, field="timestamp")

    session = _require_string(record, "session", record_number)
    try:
        validate_name(session)
    except InvalidSessionNameError as exc:
        raise SessionEventValidationError(str(exc), record=record_number, field="session") from exc
    if expected_session is not None and session != expected_session:
        raise SessionEventValidationError(
            f"does not match journal session {expected_session!r}",
            record=record_number,
            field="session",
        )

    runtime = _require_string(record, "runtime", record_number)
    if runtime not in AGENT_RUNTIME_IDS:
        raise SessionEventValidationError(
            f"must be one of: {', '.join(AGENT_RUNTIME_IDS)}",
            record=record_number,
            field="runtime",
        )

    event_type = _require_token(record, "event_type", record_number)
    run_id = record["run_id"]
    if run_id is not None and (not isinstance(run_id, str) or not is_valid_run_id(run_id)):
        raise SessionEventValidationError("must be null or a valid Forge run id", record=record_number, field="run_id")

    origin = _require_string(record, "origin_surface", record_number)
    if origin not in SESSION_EVENT_ORIGINS:
        raise SessionEventValidationError(
            f"must be one of: {', '.join(sorted(SESSION_EVENT_ORIGINS))}",
            record=record_number,
            field="origin_surface",
        )

    operation = record["operation"]
    if operation is not None and (not isinstance(operation, str) or operation not in SESSION_EVENT_OPERATIONS):
        raise SessionEventValidationError(
            f"must be null or one of: {', '.join(sorted(SESSION_EVENT_OPERATIONS))}",
            record=record_number,
            field="operation",
        )

    outcome = _require_string(record, "outcome", record_number)
    if outcome not in SESSION_EVENT_OUTCOMES:
        raise SessionEventValidationError(
            f"must be one of: {', '.join(sorted(SESSION_EVENT_OUTCOMES))}",
            record=record_number,
            field="outcome",
        )

    reason_code = record["reason_code"]
    if reason_code is not None and (not isinstance(reason_code, str) or _TOKEN_RE.fullmatch(reason_code) is None):
        raise SessionEventValidationError(
            "must be null or a lowercase machine token",
            record=record_number,
            field="reason_code",
        )

    payload = record["payload"]
    if not isinstance(payload, dict):
        raise SessionEventValidationError("must be an object", record=record_number, field="payload")
    try:
        _validate_strict_json_value(payload, path="payload")
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SessionEventValidationError(
            f"must contain only strict JSON values: {exc}",
            record=record_number,
            field="payload",
        ) from exc
    if payload_validator is not None:
        try:
            payload_validator(event_type, payload)
        except SessionEventValidationError as exc:
            if record_number is None or exc.record is not None:
                raise
            raise SessionEventValidationError(
                exc.reason,
                record=record_number,
                field=exc.field or "payload",
            ) from exc
        except (TypeError, ValueError) as exc:
            raise SessionEventValidationError(str(exc), record=record_number, field="payload") from exc

    validated = SessionEvent(
        schema_version=schema_version,
        event_id=record["event_id"],
        timestamp=timestamp,
        session=session,
        runtime=runtime,
        event_type=event_type,
        run_id=run_id,
        origin_surface=origin,
        operation=operation,
        outcome=outcome,
        reason_code=reason_code,
        payload=dict(payload),
    )
    if event_validator is not None:
        try:
            event_validator(validated)
        except SessionEventValidationError as exc:
            if record_number is None or exc.record is not None:
                raise
            raise SessionEventValidationError(
                exc.reason,
                record=record_number,
                field=exc.field,
            ) from exc
        except (TypeError, ValueError) as exc:
            raise SessionEventValidationError(str(exc), record=record_number) from exc
    return validated


def get_session_event_journal_path(forge_root: str | Path, session: str, domain: str) -> Path:
    """Return the contained journal path without creating it."""
    if domain not in SESSION_EVENT_DOMAINS:
        raise SessionEventPathError(f"unsupported session-event domain: {domain!r}")
    try:
        validate_name(session)
    except InvalidSessionNameError as exc:
        raise SessionEventPathError(f"invalid journal session {session!r}: {exc}") from exc

    root = Path(forge_root).expanduser()
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise SessionEventPathError(f"Forge root cannot be resolved: {root}: {exc}") from exc
    if not resolved_root.is_dir():
        raise SessionEventPathError(f"Forge root is not a directory: {resolved_root}")

    journal = resolved_root / ".forge" / "artifacts" / session / domain / "events.jsonl"
    if not journal.is_relative_to(resolved_root):
        raise SessionEventPathError(f"journal path escapes Forge root: {journal}")
    _reject_existing_symlinks(resolved_root, journal)
    return journal


def append_session_event(
    forge_root: str | Path,
    domain: str,
    event: SessionEvent | dict[str, Any],
    *,
    payload_validator: SessionEventPayloadValidator | None = None,
    event_validator: SessionEventValidator | None = None,
    timeout_s: float = SESSION_EVENT_LOCK_TIMEOUT_S,
) -> Path:
    """Durably append one complete validated event under a dedicated lock."""
    raw = asdict(event) if isinstance(event, SessionEvent) else event
    session_value = raw.get("session") if isinstance(raw, dict) else None
    if not isinstance(session_value, str):
        raise SessionEventValidationError("must be a string", field="session")
    validated = validate_session_event(
        raw,
        expected_session=session_value,
        payload_validator=payload_validator,
        event_validator=event_validator,
    )
    journal = get_session_event_journal_path(forge_root, validated.session, domain)

    try:
        _ensure_journal_directories(Path(forge_root).expanduser().resolve(strict=True), journal.parent)
        serialized = json.dumps(asdict(validated), separators=(",", ":"), sort_keys=True, allow_nan=False)
        encoded = (serialized + "\n").encode("utf-8")
        with file_lock_for_target(target_path=journal, timeout_s=timeout_s):
            flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            fd = os.open(journal, flags, 0o600)
            try:
                metadata = os.fstat(fd)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise OSError("session-event journal must be a singly linked regular file")
                os.fchmod(fd, 0o600)
                offset = 0
                while offset < len(encoded):
                    written = os.write(fd, encoded[offset:])
                    if written <= 0:
                        raise OSError("short write while appending session event")
                    offset += written
                os.fsync(fd)
            finally:
                os.close(fd)
            _fsync_directory(journal.parent)
    except SessionEventError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise SessionEventWriteError(f"required session-event append failed at '{journal}': {exc}") from exc
    return journal


def read_session_events(
    forge_root: str | Path,
    session: str,
    domain: str,
    *,
    payload_validator: SessionEventPayloadValidator | None = None,
    event_validator: SessionEventValidator | None = None,
) -> list[SessionEvent]:
    """Read and strictly validate every journal record in append order."""
    journal = get_session_event_journal_path(forge_root, session, domain)
    if not journal.exists():
        return []
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        fd = os.open(journal, flags)
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise OSError("session-event journal must be a singly linked regular file")
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                fd = -1
                lines = stream.readlines()
        finally:
            if fd >= 0:
                os.close(fd)
    except (OSError, UnicodeError) as exc:
        raise SessionEventReadError(f"cannot read session-event journal '{journal}': {exc}") from exc

    if lines and not lines[-1].endswith("\n"):
        raise SessionEventValidationError("truncated JSONL record (missing newline)", record=len(lines))

    events: list[SessionEvent] = []
    event_ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise SessionEventValidationError("blank JSONL record", record=line_number)
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SessionEventValidationError(f"invalid JSON: {exc.msg}", record=line_number) from exc
        if not isinstance(raw, dict):
            raise SessionEventValidationError("expected a JSON object", record=line_number)
        event = validate_session_event(
            raw,
            expected_session=session,
            payload_validator=payload_validator,
            event_validator=event_validator,
            record_number=line_number,
        )
        if event.event_id in event_ids:
            raise SessionEventValidationError(
                f"duplicate event id {event.event_id!r}",
                record=line_number,
                field="event_id",
            )
        event_ids.add(event.event_id)
        events.append(event)
    return events


def _require_string(record: dict[str, Any], field: str, record_number: int | None) -> str:
    value = record[field]
    if not isinstance(value, str) or not value:
        raise SessionEventValidationError("must be a non-empty string", record=record_number, field=field)
    return value


def _require_token(record: dict[str, Any], field: str, record_number: int | None) -> str:
    value = _require_string(record, field, record_number)
    if _TOKEN_RE.fullmatch(value) is None:
        raise SessionEventValidationError("must be a lowercase machine token", record=record_number, field=field)
    return value


def _validate_strict_json_value(
    value: object,
    *,
    path: str,
    containers: set[int] | None = None,
) -> None:
    """Reject values that JSON would coerce instead of representing exactly."""
    if value is None or type(value) in {bool, int, str}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return

    active = containers if containers is not None else set()
    if type(value) is list:
        container_id = id(value)
        if container_id in active:
            raise ValueError(f"{path} contains a circular reference")
        active.add(container_id)
        try:
            for index, item in enumerate(value):
                _validate_strict_json_value(item, path=f"{path}[{index}]", containers=active)
        finally:
            active.remove(container_id)
        return
    if type(value) is dict:
        container_id = id(value)
        if container_id in active:
            raise ValueError(f"{path} contains a circular reference")
        active.add(container_id)
        try:
            for key, item in value.items():
                if type(key) is not str:
                    raise TypeError(f"{path} contains a non-string object key")
                _validate_strict_json_value(item, path=f"{path}.{key}", containers=active)
        finally:
            active.remove(container_id)
        return
    raise TypeError(f"{path} contains unsupported value type {type(value).__name__}")


def _reject_existing_symlinks(root: Path, target: Path) -> None:
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise SessionEventPathError(f"cannot inspect journal path component '{current}': {exc}") from exc
        if stat.S_ISLNK(mode):
            raise SessionEventPathError(f"journal path contains a symlink: {current}")


def _ensure_journal_directories(root: Path, parent: Path) -> None:
    current = root
    for part in parent.relative_to(root).parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            try:
                current.mkdir(mode=0o700)
                _fsync_directory(current.parent)
                continue
            except FileExistsError:
                # Another appender may have created this exact component after
                # lstat. Inspect it below instead of treating the benign race as
                # a required-write failure.
                mode = current.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise SessionEventPathError(f"journal directory is not a real directory: {current}")


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
