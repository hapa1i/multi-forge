"""Audit allowlisted metadata in frozen A2 sources; never extract or admit native actions."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import dacite


def _load_inventory() -> Any:
    spec = importlib.util.spec_from_file_location(
        "jev_source_audit_inventory", Path(__file__).with_name("rule-pack-inventory.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


inventory = _load_inventory()
Refusal = inventory.Refusal
REPOSITORY = inventory.REPOSITORY
MAX_RECORD_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 120 * 1024 * 1024
RECORD_TYPES = (
    "user",
    "assistant",
    "system",
    "progress",
    "queue-operation",
    "file-history-snapshot",
    "summary",
)
STOP_REASONS = ("end_turn", "max_tokens", "stop_sequence", "tool_use")
SYSTEM_SUBTYPES = ("turn_duration", "stop_hook_summary", "compact_boundary")
IDENTITY_FIELDS = (
    "canonical_identity",
    "repository",
    "runtime",
    "last_accessed_at",
    "worktree",
    "forge_root",
    "active",
    "native_id",
    "native_path",
    "expected_claude_path",
    "expected_cwd",
    "manifest_sha256",
    "manifest_path",
)


def _counter(*keys: str) -> dict[str, int]:
    return dict.fromkeys(keys, 0)


def _category(value: Any, allowed: tuple[str, ...]) -> str:
    return value if isinstance(value, str) and value in allowed else "other"


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise Refusal("invalid_json")
        value[key] = item
    return value


def _record(line: bytes) -> dict[str, Any]:
    if len(line) > MAX_RECORD_BYTES:
        raise Refusal("record_size_limit")
    try:
        value = json.loads(line.decode("utf-8"), object_pairs_hook=_unique)
        # Reject nonfinite numbers and lone surrogates anywhere, including discarded fields.
        json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError):
        raise Refusal("invalid_json") from None
    if not isinstance(value, dict):
        raise Refusal("unsupported_record_shape")
    return value


def scan_source(raw: bytes, row: dict[str, Any]) -> dict[str, Any]:
    """Count explicit Claude fields without treating assistant records as completed turns."""
    counters: dict[str, Any] = {
        "records": 0,
        "record_types": _counter(*RECORD_TYPES, "other"),
        "identity": _counter("match", "missing", "conflict"),
        "cwd": _counter("match", "missing", "conflict"),
        "sidechain": _counter("true", "false", "missing", "other"),
        "assistant_stop_reasons": _counter(*STOP_REASONS, "null", "other"),
        "system_subtypes": _counter(*SYSTEM_SUBTYPES, "other"),
        "tool_uses": _counter("Edit", "Write", "other"),
        "timestamps": _counter("in_window", "before_window", "after_window", "missing", "invalid"),
        "completion_boundary_verified": False,
        "actions_admitted": 0,
    }
    start = inventory.timestamp(inventory.AVAILABILITY_ACTION_WINDOW["start_inclusive"])
    end = inventory.timestamp(inventory.AVAILABILITY_ACTION_WINDOW["end_exclusive"])
    for line in raw.split(b"\n"):
        if not line:
            continue
        record = _record(line)
        counters["records"] += 1
        kind = _category(record.get("type"), RECORD_TYPES)
        counters["record_types"][kind] += 1
        for field, expected, name in (
            ("sessionId", row["native_id"], "identity"),
            ("cwd", row["expected_cwd"], "cwd"),
        ):
            value = record.get(field)
            state = "missing" if value is None else "match" if value == expected else "conflict"
            counters[name][state] += 1
        sidechain = record.get("isSidechain")
        state = (
            "missing"
            if sidechain is None
            else ("true" if sidechain is True else "false" if sidechain is False else "other")
        )
        counters["sidechain"][state] += 1
        if record.get("timestamp") is None:
            counters["timestamps"]["missing"] += 1
        else:
            try:
                stamp = inventory.timestamp(record["timestamp"])
                state = "before_window" if stamp < start else "after_window" if stamp >= end else "in_window"
            except Refusal:
                state = "invalid"
            counters["timestamps"][state] += 1
        if kind == "system":
            counters["system_subtypes"][_category(record.get("subtype"), SYSTEM_SUBTYPES)] += 1
        if kind == "assistant":
            message = record.get("message")
            if not isinstance(message, dict):
                counters["assistant_stop_reasons"]["other"] += 1
                continue
            reason = message.get("stop_reason")
            counters["assistant_stop_reasons"]["null" if reason is None else _category(reason, STOP_REASONS)] += 1
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        counters["tool_uses"][_category(block.get("name"), ("Edit", "Write"))] += 1
    return counters


def _active_snapshot(ledger: dict[str, Any]) -> str:
    active, digest = inventory._index(Path(ledger["home"]) / ".forge/sessions/active.json")
    try:
        parsed = dacite.from_dict(
            data_class=inventory.ActiveSessionIndex,
            data={"version": 1, "sessions": active},
            config=dacite.Config(strict=True),
        )
        for key, entry in parsed.sessions.items():
            inventory._name(key, entry.forge_root or entry.worktree_path)
            inventory.timestamp(entry.started_at)
            if entry.launch_mode not in ("host", "sidecar"):
                raise Refusal("uncertain_active_registry")
            if entry.launcher_pid is not None and (
                type(entry.launcher_pid) is not int or not 0 < entry.launcher_pid < 2**31
            ):
                raise Refusal("uncertain_active_registry")
    except (dacite.DaciteError, TypeError, ValueError):
        raise Refusal("uncertain_active_registry") from None
    for row in ledger["selected"]:
        if row["canonical_identity"] in active or any(
            entry.claude_session_id == row["native_id"] for entry in parsed.sessions.values()
        ):
            raise Refusal("selected_source_active")
    return digest


def _frozen_source(row: dict[str, Any], home: Path) -> dict[str, Any]:
    source = row.get("source")
    if not isinstance(source, dict) or set(source) != {
        "path",
        "size",
        "device",
        "inode",
    }:
        raise Refusal("invalid_frozen_source")
    if not isinstance(source["path"], str) or any(
        type(source[key]) is not int or source[key] < 0 for key in ("size", "device", "inode")
    ):
        raise Refusal("invalid_frozen_source")
    if source["size"] > inventory.MAX_NATIVE_BYTES:
        raise Refusal("native_file_size_limit")
    if inventory.admit_source(row, home) != source:
        raise Refusal("frozen_source_changed")
    return source


def audit(ledger: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Audit a frozen selection only; active/changed sources never authorize replacement selection."""
    inventory.validate_selection(ledger)
    if ledger.get("summary", {}).get("selection") != "availability_first_within_fixed_recency_cohort":
        raise Refusal("unsupported_selection")
    home = Path(ledger["home"])
    frozen = [_frozen_source(row, home) for row in ledger["selected"]]
    if sum(source["size"] for source in frozen) > MAX_TOTAL_BYTES:
        raise Refusal("total_source_size_limit")
    active_sha = _active_snapshot(ledger)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "stage": "native_source_metadata_audit",
        "selected_sources": len(frozen),
        "native_read_attempts": 0,
        "native_read_failures": 0,
        "native_files_read": 0,
        "native_bytes_read": 0,
        "known_native_bytes_read": 0,
        "audited_sources": 0,
        "sources": [],
        "source_refusals": {},
        "actions_admitted": 0,
        "quality_accepted": False,
        "runtime_admitted": False,
    }
    private: dict[str, Any] = {
        "schema_version": 1,
        "active_index_sha256": active_sha,
        "implementation_sha256": {
            path.name: inventory.digest(path.read_bytes()) for path in (Path(__file__), Path(inventory.__file__))
        },
        "sources": [],
        "summary": summary,
    }
    refusals: Counter[str] = Counter()
    for ordinal, (row, source) in enumerate(zip(ledger["selected"], frozen, strict=True), 1):
        public: dict[str, Any] = {
            "session_id": f"session-{ordinal:02d}",
            "runtime": row["runtime"],
            "status": "audited",
            "reason": None,
        }
        saved = {
            "session_id": public["session_id"],
            "frozen_identity": {key: row[key] for key in IDENTITY_FIELDS},
            "source": source,
        }
        private["sources"].append(saved)
        summary["sources"].append(public)
        try:
            if row["runtime"] != "claude_code":
                raise Refusal("unsupported_runtime")
            _frozen_source(row, home)
            summary["native_read_attempts"] += 1
            try:
                raw, identity = inventory.read_regular(Path(source["path"]), inventory.MAX_NATIVE_BYTES)
            except (Refusal, OSError, ValueError, TypeError):
                summary["native_read_failures"] += 1
                summary["native_bytes_read"] = None
                raise
            summary["native_files_read"] += 1
            summary["known_native_bytes_read"] += len(raw)
            if summary["native_bytes_read"] is not None:
                summary["native_bytes_read"] += len(raw)
            saved.update(source_sha256=inventory.digest(raw), read_identity=identity)
            if (identity["st_dev"], identity["st_ino"], identity["st_size"]) != (
                source["device"],
                source["inode"],
                source["size"],
            ):
                raise Refusal("frozen_source_changed")
            counters = scan_source(raw, row)
            public["counters"] = counters
            summary["audited_sources"] += 1
            for field in ("identity", "cwd"):
                if counters[field]["conflict"]:
                    raise Refusal(f"source_{field}_conflict")
                if not counters[field]["match"]:
                    raise Refusal(f"source_{field}_missing")
        except (Refusal, OSError, ValueError, TypeError, KeyError, RecursionError):
            reason = inventory.sys_exception_reason()
            refusals[reason] += 1
            public.update(status="refused", reason=reason)
    summary["source_refusals"] = dict(sorted(refusals.items()))
    return summary, private


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audit",
        type=Path,
        required=True,
        help="Frozen availability-private.json in its private directory",
    )
    args = parser.parse_args()
    try:
        source = args.audit
        directory = source.parent
        inventory.no_symlinks(source)
        if (
            not source.is_absolute()
            or source.name != "availability-private.json"
            or directory.stat().st_mode & 0o777 != 0o700
            or source.stat().st_mode & 0o777 != 0o600
        ):
            raise Refusal("unapproved_private_input")
        outputs = [
            directory / "source-audit-private.json",
            directory / "source-audit-summary.json",
        ]
        if any(path.exists() or path.is_symlink() for path in outputs):
            raise Refusal("audit_output_exists")
        raw, _ = inventory.read_regular(source, inventory.MAX_INDEX_BYTES)
        ledger = _record(raw)
        if ledger.get("repository") != str(REPOSITORY) or ledger.get("home") != str(Path.home()):
            raise Refusal("metadata_scope_mismatch")
        worktrees = inventory.verified_worktrees(REPOSITORY)
        if any(
            row.get("forge_root") not in worktrees or row.get("worktree") not in worktrees
            for row in ledger.get("selected", [])
        ):
            raise Refusal("unverified_worktree_membership")
        summary, private = audit(ledger)
        private["availability_sha256"] = inventory.digest(raw)
        inventory.private_write(outputs[0], private)
        inventory.private_write(outputs[1], summary)
        print(json.dumps(summary, indent=2, allow_nan=False))
    except (Refusal, OSError, ValueError, TypeError, KeyError, RecursionError):
        parser.error(inventory.sys_exception_reason())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
