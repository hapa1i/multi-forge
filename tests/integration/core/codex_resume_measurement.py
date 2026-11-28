"""Independent counter observations for the real native session test."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from forge.cli.main import main
from forge.core.ops.codex_session import (
    CodexSessionResumeResult,
    CodexSessionStartResult,
)
from forge.core.telemetry.downstream import DownstreamRecord, read_downstream_records
from forge.core.usage.ledger import UsageEvent, read_usage_events

_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens")


def _recorded_tokens(record: UsageEvent | DownstreamRecord) -> dict[str, int | None]:
    return {
        "input_tokens": record.input_tokens,
        "cached_input_tokens": record.cached_tokens,
        "output_tokens": record.output_tokens,
    }


def sample_rollout(path: Path, start_offset: int | None = None) -> dict[str, Any]:
    """Read the test thread's raw totals; attribute request records only within this launch's suffix."""
    data = path.read_bytes()
    header = json.loads(data.split(b"\n", 1)[0])["payload"]
    sample: dict[str, Any] = {
        "thread_id": header["id"],
        "model_provider": header.get("model_provider"),
        "model": None,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "total_token_usage": None,
        "sample_offset": None,
    }
    requests = []
    turn_ids = []
    offset = 0
    for line in data.splitlines(keepends=True):
        row = json.loads(line)
        payload = row["payload"]
        if row["type"] == "turn_context" and payload.get("model"):
            sample["model"] = payload["model"]
        if row["type"] == "event_msg" and payload.get("type") == "token_count":
            total = (payload.get("info") or {}).get("total_token_usage")
            if total is not None:
                sample.update(
                    total_token_usage={key: total.get(key) for key in _FIELDS},
                    sample_offset=offset,
                )
        if start_offset is not None and offset >= start_offset:
            if row["type"] == "token_usage_record":
                requests.append(payload.get("usage") or {})
            if row["type"] == "event_msg" and payload.get("type") == "task_started":
                turn_ids.append(payload.get("turn_id"))
            if row["type"] == "event_msg" and payload.get("type") == "task_complete":
                error = payload.get("error") or {}
                if isinstance(error, dict) and isinstance(code := error.get("codex_error_info"), str):
                    sample["completion_error_code"] = code
        offset += len(line)
    if start_offset is not None:
        sample["turn_ids_in_suffix"] = turn_ids
        sample["request_usage_sum"] = (
            {
                key: (sum(req[key] for req in requests) if all(type(req.get(key)) is int for req in requests) else None)
                for key in _FIELDS
            }
            if requests
            else None
        )
    return sample


class NativeResumeMeasurement:
    """Save each observation before assertions, so an inconclusive run retains its raw numeric evidence."""

    def __init__(self, directory: Path, version: str | None) -> None:
        self.path = directory / "native-resume-usage.json"
        self.receipt: dict[str, Any] = {
            "codex_version": version,
            "route": "runtime_native",
            "billing_mode": "subscription_quota",
            "auth_source": "codex_store",
            "provider": "openai",
            "launches": [],
        }

    def observe(
        self,
        label: str,
        launch: CodexSessionStartResult | CodexSessionResumeResult,
        stdout: str,
        before: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        stream = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        terminals = [row["usage"] for row in stream if row.get("type") == "turn.completed" and row.get("usage")]
        row = {
            "launch": label,
            "root_run_id": launch.root_run_id,
            "run_id": launch.codex.run_id,
            "bound_thread_id": before["thread_id"] if before else None,
            "returned_thread_id": launch.codex.runtime_session_id,
            "returncode": launch.codex.returncode,
            "stream_events": [r["type"] for r in stream],
            "before": before,
            "terminal_usage": ({key: terminals[-1].get(key) for key in _FIELDS} if terminals else None),
            "after": (
                sample_rollout(Path(launch.rollout_path), before["bytes"] if before else 0)
                if launch.rollout_path
                else None
            ),
        }
        self.receipt["launches"].append(row)
        self._save()
        assert len(terminals) <= 1
        (event,) = (e for e in read_usage_events(root_run_id=launch.root_run_id) if e.route == "codex_exec")
        (attempt,) = read_downstream_records(forge_run_id=event.run_id, kind="attempt")
        row.update(
            ts=event.ts,
            status=event.status,
            event_id=event.event_id,
            attempt_id=attempt.downstream_event_id,
            usage_event=_recorded_tokens(event),
            downstream_attempt=_recorded_tokens(attempt),
        )
        self._save()
        assert launch.codex.run_id == event.run_id
        assert attempt.forge_root_run_id == event.root_run_id == launch.root_run_id
        assert event.billing_mode == "subscription_quota" and event.proxy_id is None and event.provider == "openai"
        assert attempt.reporter == event.reporter == "codex_jsonl"
        assert attempt.cost_micros is None and event.cost_micro_usd is None
        assert event.confidence == "unavailable" and event.measurement_source == "runtime_native"
        assert attempt.failed == (not launch.codex.success)
        return row

    def check_activity(self) -> None:
        cli = CliRunner().invoke(main, ["telemetry", "activity", "impl", "--period", "all", "--json"])
        assert cli.exit_code == 0, cli.output
        activity = json.loads(cli.output)["downstream"]
        self.receipt["activity"] = activity
        self._save()
        _check_launch_totals(self.receipt["launches"], activity)

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.receipt, indent=2) + "\n", encoding="utf-8")


def _check_launch_totals(launches: list[dict[str, Any]], activity: dict[str, Any]) -> None:
    # Curation is a separate event on the start's run tree. Failed Codex work has unknown tokens.
    totals = {"input_tokens": 350, "output_tokens": 80}
    by_command: dict[str, dict[str, int]] = {}
    for row in launches:
        if row["status"] == "success":
            pre = row["before"]
            post = row["after"]
            delta = {
                key: post["total_token_usage"][key] - (pre["total_token_usage"][key] if pre else 0) for key in _FIELDS
            }
            assert row["returned_thread_id"] == post["thread_id"]
            assert post["model_provider"] == "openai"
            assert post["sample_offset"] >= (pre["bytes"] if pre else 0)
            assert row["terminal_usage"] in (post["total_token_usage"], delta)
            for key, observed in (post["request_usage_sum"] or {}).items():
                if observed is not None:
                    assert observed == delta[key], (row["launch"], key)
            command = "codex-resume" if pre else "codex-bridge"
            per_command = by_command.setdefault(command, dict.fromkeys(_FIELDS, 0))
            for key in _FIELDS:
                per_command[key] += delta[key]
            for key in totals:
                totals[key] += delta[key]
        else:
            assert row["terminal_usage"] is None
            delta = dict.fromkeys(_FIELDS)
        assert row["usage_event"] == row["downstream_attempt"] == delta, row["launch"]
    for command_row in activity["rows"]:
        if command_row["command"] in by_command:
            expected = by_command.pop(command_row["command"])
            assert command_row["input_tokens"] == expected["input_tokens"]
            assert command_row["cached_tokens"] == expected["cached_input_tokens"]
            assert command_row["output_tokens"] == expected["output_tokens"]
    assert not by_command
    assert activity["total_input_tokens"] == totals["input_tokens"]
    assert activity["total_output_tokens"] == totals["output_tokens"]
