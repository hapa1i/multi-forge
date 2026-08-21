"""Regression coverage for positive ``proxy audit`` result limits."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from forge.cli.proxy import proxy

pytestmark = pytest.mark.regression


def _records(command: str, count: int) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for index in range(count):
        record: dict[str, object] = {
            "request_id": f"request-{index:02d}",
            "proxy_id": f"proxy-{index:02d}",
            "ts": f"2026-08-21T00:{index:02d}:00+00:00",
        }
        if command == "show":
            record.update(
                {
                    "record_type": "request",
                    "mode": "inspect",
                    "counts": {"num_messages": index, "num_tools": 0},
                }
            )
        else:
            record.update(
                {
                    "record_type": "drift",
                    "dimension": "system_prompt",
                    "previous_hash": f"sha256:{index:010d}",
                    "current_hash": f"sha256:{index + 1:010d}",
                }
            )
        records.append(record)
    return records


@pytest.mark.parametrize("command", ["show", "diff"])
@pytest.mark.parametrize("invalid_limit", ["0", "-1"])
def test_proxy_audit_rejects_non_positive_limit_before_reads(
    command: str,
    invalid_limit: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    period_bounds = Mock(side_effect=AssertionError("period bounds must not be read"))
    audit_read = Mock(side_effect=AssertionError("audit shards must not be read"))
    monkeypatch.setattr("forge.cli.proxy_audit.local_period_bounds", period_bounds)
    monkeypatch.setattr("forge.proxy.audit_logger.read_audit_logs", audit_read)

    result = CliRunner().invoke(proxy, ["audit", command, "--limit", invalid_limit])

    assert result.exit_code == 2
    assert "Invalid value for '--limit'" in result.output
    period_bounds.assert_not_called()
    audit_read.assert_not_called()


@pytest.mark.parametrize("command", ["show", "diff"])
@pytest.mark.parametrize("as_json", [False, True])
def test_proxy_audit_limit_one_keeps_the_newest_record(
    command: str,
    as_json: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("forge.proxy.audit_logger.read_audit_logs", Mock(return_value=_records(command, 3)))
    args = ["audit", command, "--period", "all", "--limit", "1"]
    if as_json:
        args.append("--json")

    result = CliRunner().invoke(proxy, args)

    assert result.exit_code == 0
    if as_json:
        assert [record["request_id"] for record in json.loads(result.output)] == ["request-02"]
    else:
        assert "proxy-02" in result.output
        assert "proxy-01" not in result.output


@pytest.mark.parametrize(("command", "default_limit"), [("show", 20), ("diff", 30)])
@pytest.mark.parametrize("as_json", [False, True])
def test_proxy_audit_default_limit_keeps_the_newest_records_in_order(
    command: str,
    default_limit: int,
    as_json: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _records(command, default_limit + 2)
    monkeypatch.setattr("forge.proxy.audit_logger.read_audit_logs", Mock(return_value=records))
    args = ["audit", command, "--period", "all"]
    if as_json:
        args.append("--json")

    result = CliRunner().invoke(proxy, args)

    assert result.exit_code == 0
    expected_ids = [f"request-{index:02d}" for index in range(2, default_limit + 2)]
    if as_json:
        assert [record["request_id"] for record in json.loads(result.output)] == expected_ids
    else:
        assert "proxy-01" not in result.output
        assert result.output.index("proxy-02") < result.output.index(f"proxy-{default_limit + 1:02d}")
