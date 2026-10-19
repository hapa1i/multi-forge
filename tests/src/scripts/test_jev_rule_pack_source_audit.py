"""Synthetic native records exercise source auditing without reading user stores."""

import copy
import importlib.util
import json
import re
import sys
from pathlib import Path
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[3]
SECRET = "PRIVATE_NATIVE_SOURCE_SENTINEL"


@pytest.fixture
def source_audit(monkeypatch):
    path = ROOT / "scripts/experiments/jev/rule-pack-source-audit.py"
    spec = importlib.util.spec_from_file_location("jev_rule_pack_source_audit", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sources(tmp_path, source_audit):
    home, repo = tmp_path / "home", tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    registry = home / ".forge/sessions"
    registry.mkdir(parents=True)

    def create(runtimes=("claude_code",)):
        index, paths = {}, []
        for number, runtime in enumerate(runtimes):
            name = f"native-{number:02d}"
            native_id = str(UUID(int=number + 1))
            key = name + "|" + source_audit.inventory.digest(str(repo).encode())[:12]
            if runtime == "claude_code":
                source = (
                    home
                    / ".claude/projects"
                    / str(repo).replace("/", "-").replace(".", "-").replace("_", "-")
                    / f"{native_id}.jsonl"
                )
                records = [
                    {
                        "type": "assistant",
                        "sessionId": native_id,
                        "cwd": str(repo),
                        "timestamp": "2026-10-15T10:00:00Z",
                        "isSidechain": False,
                        "message": {
                            "stop_reason": "end_turn",
                            "content": [{"type": "text", "text": SECRET}],
                        },
                    }
                ]
            else:
                source = home / ".codex/sessions/2026/10/15" / f"rollout-2026-10-15T10-00-00-{native_id}.jsonl"
                records = [{"type": "session_meta", "payload": {"id": native_id, "cwd": str(repo), "text": SECRET}}]
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(jsonl(records))
            paths.append(source)
            manifest = {
                "schema_version": 5,
                "name": name,
                "forge_root": str(repo),
                "worktree": None,
                "intent": {"launch": {"mode": "host", "runtime": runtime}},
                "confirmed": {
                    "claude_session_id": native_id if runtime == "claude_code" else None,
                    "claude_project_root": str(repo),
                    "transcript_path": str(source),
                    "codex": {"thread_id": native_id, "rollout_path": str(source)} if runtime == "codex" else None,
                },
            }
            manifest_path = repo / ".forge/sessions" / name / "forge.session.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(manifest))
            index[key] = {
                "project_root": str(repo),
                "forge_root": str(repo),
                "worktree_path": str(repo),
                "last_accessed_at": f"2026-10-15T10:{number:02d}:00Z",
                "claude_session_id": native_id if runtime == "claude_code" else None,
                "codex_thread_id": native_id if runtime == "codex" else None,
            }
        (registry / "index.json").write_text(json.dumps({"version": 1, "sessions": index}))
        (registry / "active.json").write_text(json.dumps({"version": 1, "sessions": {}}))
        _, ledger = source_audit.inventory.inventory_availability(repo, home, {str(repo)})
        return ledger, paths, home, repo

    return create


def jsonl(records):
    return b"".join(json.dumps(record).encode() + b"\n" for record in records)


def scan_row():
    return {"runtime": "claude_code", "native_id": str(UUID(int=1)), "expected_cwd": "/fixture/repository"}


def test_scan_counts_only_controlled_categories_and_never_admits_actions(source_audit):
    row = scan_row()
    records = [
        {
            "type": "assistant",
            "sessionId": row["native_id"],
            "cwd": row["expected_cwd"],
            "isSidechain": False,
            "timestamp": "2026-10-01T00:00:00Z",
            "message": {
                "stop_reason": "end_turn",
                "content": [
                    {"type": "tool_use", "name": "Edit", "input": {"old_string": SECRET}},
                    {"type": "tool_use", "name": "Write", "input": {"content": SECRET}},
                    {"type": "tool_use", "name": SECRET, "input": {"api_key": SECRET}},
                ],
            },
        },
        {
            "type": "system",
            "subtype": "turn_duration",
            "sessionId": row["native_id"],
            "cwd": row["expected_cwd"],
            "isSidechain": True,
            "timestamp": "2026-09-30T23:59:59Z",
        },
        {"type": SECRET, "subtype": SECRET, "isSidechain": SECRET, "timestamp": "2026-10-18T00:00:00Z"},
        {"type": "assistant", "message": {"stop_reason": SECRET}, "timestamp": SECRET},
        {"type": "system", "subtype": SECRET},
    ]
    result = source_audit.scan_source(jsonl(records), row)
    assert result["records"] == 5
    assert result["record_types"] == {
        "user": 0,
        "assistant": 2,
        "system": 2,
        "progress": 0,
        "queue-operation": 0,
        "file-history-snapshot": 0,
        "summary": 0,
        "other": 1,
    }
    assert result["identity"] == {"match": 2, "missing": 3, "conflict": 0}
    assert result["cwd"] == {"match": 2, "missing": 3, "conflict": 0}
    assert result["sidechain"] == {"true": 1, "false": 1, "missing": 2, "other": 1}
    assert result["assistant_stop_reasons"]["end_turn"] == 1
    assert result["assistant_stop_reasons"]["other"] == 1
    assert result["system_subtypes"]["turn_duration"] == 1
    assert result["system_subtypes"]["other"] == 1
    assert result["tool_uses"] == {"Edit": 1, "Write": 1, "other": 1}
    assert result["timestamps"] == {"in_window": 1, "before_window": 1, "after_window": 1, "missing": 1, "invalid": 1}
    assert result["completion_boundary_verified"] is False
    assert result["actions_admitted"] == 0
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"type":"user","type":"assistant"}\n',
        b'{"nested":{"secret":1,"secret":2}}\n',
        b'{"secret":NaN}\n',
        b'{"secret":Infinity}\n',
        b'{"secret":-Infinity}\n',
        b'{"secret":1e999}\n',
        b'{"secret":"\\ud800"}\n',
        b'{"secret":"\xff"}\n',
        b"[]\n",
        b'{"secret":',
    ],
)
def test_scan_refuses_malformed_records_without_echoing_source(source_audit, raw):
    with pytest.raises(source_audit.Refusal) as exc:
        source_audit.scan_source(raw, scan_row())
    assert re.fullmatch(r"[a-z][a-z0-9_]*", str(exc.value))
    assert "secret" not in str(exc.value)


def test_record_size_bound_includes_unknown_record_payload(source_audit):
    raw = jsonl([{"type": "progress", "text": SECRET + "x" * (1024 * 1024)}])
    with pytest.raises(source_audit.Refusal) as exc:
        source_audit.scan_source(raw, scan_row())
    assert re.fullmatch(r"[a-z][a-z0-9_]*", str(exc.value))
    assert SECRET not in str(exc.value)


def test_audit_reads_frozen_source_once_without_retaining_content(source_audit, sources, monkeypatch):
    ledger, paths, _, _ = sources()
    native_reads = []
    original_read = source_audit.inventory.read_regular

    def read(path, limit):
        if path in paths:
            native_reads.append((path, limit))
        return original_read(path, limit)

    monkeypatch.setattr(source_audit.inventory, "read_regular", read)
    summary, private = source_audit.audit(ledger)
    assert native_reads == [(paths[0], 20 * 1024 * 1024)]
    assert summary["native_files_read"] == 1
    assert summary["native_bytes_read"] == paths[0].stat().st_size
    assert summary["source_refusals"] == {}
    assert len(summary["sources"]) == 1
    assert summary["sources"][0]["session_id"] == "session-01"
    assert SECRET not in json.dumps((summary, private))
    assert str(paths[0]) not in json.dumps(summary)
    assert ledger["selected"][0]["native_id"] not in json.dumps(summary)


@pytest.mark.parametrize("field,reason", [("sessionId", "source_identity_conflict"), ("cwd", "source_cwd_conflict")])
def test_conflicting_native_identity_or_cwd_refuses_source(source_audit, sources, field, reason):
    ledger, paths, _, _ = sources()
    record = json.loads(paths[0].read_bytes())
    record[field] = SECRET
    raw = jsonl([record])
    row = ledger["selected"][0]
    paths[0].write_bytes(raw)
    row["source"] = source_audit.inventory.admit_source(row, Path(ledger["home"]))
    summary, private = source_audit.audit(ledger)
    assert summary["source_refusals"] == {reason: 1}
    assert summary["sources"][0]["status"] == "refused"
    assert summary["sources"][0]["reason"] == reason
    assert SECRET not in json.dumps((summary, private))


@pytest.mark.parametrize("field,reason", [("sessionId", "source_identity_missing"), ("cwd", "source_cwd_missing")])
def test_absent_native_identity_or_cwd_is_not_verified(source_audit, sources, field, reason):
    ledger, paths, _, _ = sources()
    record = json.loads(paths[0].read_bytes())
    del record[field]
    row = ledger["selected"][0]
    paths[0].write_bytes(jsonl([record]))
    row["source"] = source_audit.inventory.admit_source(row, Path(ledger["home"]))
    summary, _ = source_audit.audit(ledger)
    assert summary["source_refusals"] == {reason: 1}
    assert summary["sources"][0]["status"] == "refused"


@pytest.mark.parametrize("count", [4, 7])
def test_edited_selection_caps_refuse_before_native_read(source_audit, sources, monkeypatch, count):
    ledger, paths, _, _ = sources()
    ledger["selected"] = [copy.deepcopy(ledger["selected"][0]) for _ in range(count)]
    original_read = source_audit.inventory.read_regular

    def read_metadata_only(path, limit):
        assert path not in paths, "Selection limits must be checked before native reads"
        return original_read(path, limit)

    monkeypatch.setattr(source_audit.inventory, "read_regular", read_metadata_only)
    with pytest.raises(source_audit.Refusal, match="metadata_selection_limit"):
        source_audit.audit(ledger)


def test_codex_source_is_refused_without_native_read(source_audit, sources, monkeypatch):
    ledger, paths, _, _ = sources(("codex",))
    original_read = source_audit.inventory.read_regular

    def read_metadata_only(path, limit):
        assert path not in paths, "This audit has no admitted Codex record parser"
        return original_read(path, limit)

    monkeypatch.setattr(source_audit.inventory, "read_regular", read_metadata_only)
    summary, _ = source_audit.audit(ledger)
    assert summary["native_files_read"] == 0
    assert summary["native_bytes_read"] == 0
    assert summary["sources"][0]["status"] == "refused"
    assert sum(summary["source_refusals"].values()) == 1


@pytest.mark.parametrize("field", ["path", "device", "inode", "size"])
def test_frozen_source_metadata_change_refuses_before_native_read(source_audit, sources, monkeypatch, field):
    ledger, paths, _, _ = sources()
    source = ledger["selected"][0]["source"]
    source[field] = source[field] + 1 if field != "path" else str(paths[0].with_name("unselected.jsonl"))
    original_read = source_audit.inventory.read_regular

    def read_metadata_only(path, limit):
        assert path not in paths, "Changed frozen metadata must refuse before native reads"
        return original_read(path, limit)

    monkeypatch.setattr(source_audit.inventory, "read_regular", read_metadata_only)
    with pytest.raises(source_audit.Refusal, match="frozen_source_changed"):
        source_audit.audit(ledger)


def test_stable_read_identity_must_still_match_frozen_selection(source_audit, sources, monkeypatch):
    ledger, paths, _, _ = sources()
    original_read = source_audit.inventory.read_regular

    def changed_identity(path, limit):
        raw, identity = original_read(path, limit)
        if path in paths:
            identity["st_ino"] += 1
        return raw, identity

    monkeypatch.setattr(source_audit.inventory, "read_regular", changed_identity)
    summary, private = source_audit.audit(ledger)
    assert summary["native_files_read"] == 1
    assert summary["source_refusals"] == {"frozen_source_changed": 1}
    assert summary["sources"][0]["status"] == "refused"
    assert "counters" not in summary["sources"][0]
    assert private["sources"][0]["source_sha256"] == source_audit.inventory.digest(paths[0].read_bytes())
    assert SECRET not in json.dumps((summary, private))


def test_failed_stable_read_preserves_unknown_partial_byte_accounting(source_audit, sources, monkeypatch):
    ledger, paths, _, _ = sources()
    original_read = source_audit.inventory.read_regular

    def changed_read(path, limit):
        if path in paths:
            raise source_audit.Refusal("changed_read")
        return original_read(path, limit)

    monkeypatch.setattr(source_audit.inventory, "read_regular", changed_read)
    summary, private = source_audit.audit(ledger)
    assert summary["native_read_attempts"] == 1
    assert summary["native_read_failures"] == 1
    assert summary["native_files_read"] == 0
    assert summary["known_native_bytes_read"] == 0
    assert summary["native_bytes_read"] is None
    assert summary["source_refusals"] == {"changed_read": 1}
    assert "source_sha256" not in private["sources"][0]
    assert "counters" not in summary["sources"][0]


@pytest.mark.parametrize("limit", ["native", "total"])
def test_byte_caps_refuse_before_native_read(source_audit, sources, monkeypatch, limit):
    ledger, paths, _, _ = sources()
    if limit == "native":
        ledger["selected"][0]["source"]["size"] = 20 * 1024 * 1024 + 1
        reason = "native_file_size_limit"
    else:
        assert source_audit.MAX_TOTAL_BYTES == 120 * 1024 * 1024
        monkeypatch.setattr(source_audit, "MAX_TOTAL_BYTES", paths[0].stat().st_size - 1)
        reason = "total_source_size_limit"
    original_read = source_audit.inventory.read_regular

    def read_metadata_only(path, limit):
        assert path not in paths, "Byte caps must be checked before native reads"
        return original_read(path, limit)

    monkeypatch.setattr(source_audit.inventory, "read_regular", read_metadata_only)
    with pytest.raises(source_audit.Refusal, match=reason):
        source_audit.audit(ledger)


@pytest.mark.parametrize("active_kind", ["selected_key", "native_identity", "malformed"])
def test_active_registry_rechecked_before_native_read(source_audit, sources, monkeypatch, active_kind):
    ledger, paths, home, repo = sources()
    row = ledger["selected"][0]
    key = row["canonical_identity"]
    active = {
        "forge_root": str(repo),
        "worktree_path": str(repo),
        "started_at": "2026-10-19T10:00:00Z",
    }
    if active_kind == "native_identity":
        key = "another-session|" + source_audit.inventory.digest(str(repo).encode())[:12]
        active["claude_session_id"] = row["native_id"]
    elif active_kind == "malformed":
        active["started_at"] = SECRET
    (home / ".forge/sessions/active.json").write_text(json.dumps({"version": 1, "sessions": {key: active}}))
    original_read = source_audit.inventory.read_regular

    def read_metadata_only(path, limit):
        assert path not in paths, "Liveness must be checked before native reads"
        return original_read(path, limit)

    monkeypatch.setattr(source_audit.inventory, "read_regular", read_metadata_only)
    reason = "uncertain_active_registry" if active_kind == "malformed" else "selected_source_active"
    with pytest.raises(source_audit.Refusal, match=reason) as exc:
        source_audit.audit(ledger)
    assert SECRET not in str(exc.value)


def test_current_active_snapshot_digest_is_retained_without_refreezing_selection(source_audit, sources):
    ledger, _, home, repo = sources()
    key = "unselected-session|" + source_audit.inventory.digest(str(repo).encode())[:12]
    active_path = home / ".forge/sessions/active.json"
    active_path.write_text(
        json.dumps(
            {
                "version": 1,
                "sessions": {
                    key: {
                        "forge_root": str(repo),
                        "worktree_path": str(repo),
                        "started_at": "2026-10-19T10:00:00Z",
                    }
                },
            }
        )
    )
    frozen = copy.deepcopy(ledger)
    summary, private = source_audit.audit(ledger)
    assert summary["native_files_read"] == 1
    assert private["active_index_sha256"] == source_audit.inventory.digest(active_path.read_bytes())
    assert private["active_index_sha256"] != ledger["active_index_sha256"]
    assert ledger == frozen


@pytest.fixture
def cli_input(source_audit, sources, tmp_path, monkeypatch):
    ledger, paths, home, repo = sources()
    directory = tmp_path / "private-audit"
    directory.mkdir(mode=0o700)
    input_path = directory / "availability-private.json"
    source_audit.inventory.private_write(input_path, ledger)
    monkeypatch.setattr(source_audit, "REPOSITORY", repo)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(source_audit.inventory, "verified_worktrees", lambda path: {str(repo)})
    monkeypatch.setattr(sys, "argv", ["rule-pack-source-audit.py", "--audit", str(input_path)])
    return input_path, paths


def test_cli_writes_private_outputs_exclusively_beside_input(source_audit, cli_input, capsys, monkeypatch):
    input_path, paths = cli_input
    assert source_audit.main() == 0
    output = capsys.readouterr()
    summary = json.loads(output.out)
    assert output.err == ""
    assert SECRET not in output.out
    assert str(paths[0]) not in output.out
    private_path = input_path.parent / "source-audit-private.json"
    summary_path = input_path.parent / "source-audit-summary.json"
    assert set(path.name for path in input_path.parent.iterdir()) == {
        "availability-private.json",
        "source-audit-private.json",
        "source-audit-summary.json",
    }
    assert private_path.stat().st_mode & 0o777 == summary_path.stat().st_mode & 0o777 == 0o600
    assert json.loads(summary_path.read_bytes()) == summary
    before = private_path.read_bytes(), summary_path.read_bytes()

    def forbid_second_read(*args):
        raise AssertionError("Existing audit outputs must refuse before reading any input")

    monkeypatch.setattr(source_audit.inventory, "read_regular", forbid_second_read)
    with pytest.raises(SystemExit) as exc:
        source_audit.main()
    assert exc.value.code == 2
    assert "audit_output_exists" in capsys.readouterr().err
    assert (private_path.read_bytes(), summary_path.read_bytes()) == before


@pytest.mark.parametrize("public_target", ["input", "directory"])
def test_cli_rejects_nonprivate_input_before_reading_native_source(source_audit, cli_input, public_target, capsys):
    input_path, _ = cli_input
    if public_target == "input":
        input_path.chmod(0o644)
    else:
        input_path.parent.chmod(0o755)
    with pytest.raises(SystemExit) as exc:
        source_audit.main()
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "unapproved_private_input" in output.err
    assert SECRET not in output.err
    assert not (input_path.parent / "source-audit-private.json").exists()
