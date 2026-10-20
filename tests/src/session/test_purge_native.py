"""Synthetic ownership and race cases; these fixtures are not native probe evidence."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from forge.session import purge_native as native
from forge.session.claude.paths import encode_project_path
from forge.session.models import (
    AdoptionConfirmed,
    CodexConfirmed,
    Derivation,
    LaunchIntent,
    SessionState,
)

THREAD = "01a12b5c-ce1a-72c2-ad3f-05d75f3fba00"
OTHER = "01a12b73-202d-7dd0-a058-f74ec9375dd2"


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    project = root / "project"
    project.mkdir()
    claude = root / "claude"
    codex = root / "codex"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    monkeypatch.setenv("CLAUDE_HOME", str(claude))
    monkeypatch.setenv("CODEX_HOME", str(codex))
    monkeypatch.setattr(native, "check_native_inactivity", lambda runtime: ())
    state = SessionState(
        3,
        "subject",
        "2026-10-20T00:00:00Z",
        "2026-10-20T00:00:00Z",
        forge_root=str(project),
    )
    state.confirmed.claude_project_root = str(project)
    state.confirmed.claude_session_id = THREAD
    return state, project, claude, codex


def claude_bytes(cwd, session_id=THREAD, **extra):
    row = {
        "type": "user",
        "sessionId": session_id,
        "cwd": str(cwd),
        "version": "2.1.245",
        **extra,
    }
    return json.dumps(row).encode() + b"\n"


def write_claude(home, cwd, data=None, session_id=THREAD):
    path = home / "projects" / encode_project_path(str(cwd)) / f"{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if data is not None else claude_bytes(cwd, session_id))
    return path


def write_codex(home, launch_cwd, thread=THREAD, version="0.162.1", **extra):
    path = home / "sessions" / "2026" / "10" / "20" / f"rollout-2026-10-20T00-00-00-{thread}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"id": thread, "cwd": str(launch_cwd), "cli_version": version}
    if version == "0.162.1":
        metadata.update(session_id=thread, history_mode="paginated")
    path.write_text(json.dumps({"type": "session_meta", "payload": {**metadata, **extra}}) + "\n")
    return path


def set_codex(state, path):
    state.intent.launch = LaunchIntent(runtime="codex")
    state.confirmed.claude_session_id = None
    state.confirmed.codex = CodexConfirmed(thread_id=THREAD, rollout_path=str(path))


def test_exact_original_rollover_and_nested_subagent(inventory):
    state, project, home, _ = inventory
    main = write_claude(home, project)
    rollover = write_claude(home, project, session_id=OTHER)
    state.confirmed.artifacts["transcripts"] = [{"session_id": OTHER}]
    agent = main.parent / THREAD / "subagents" / "agent-abc123.jsonl"
    agent.parent.mkdir(parents=True)
    agent.write_bytes(claude_bytes(project, agentId="abc123", isSidechain=True))
    unrelated = main.parent / "agent-other.jsonl"
    unrelated.write_bytes(claude_bytes(project, OTHER, agentId="other", isSidechain=True))
    plan = native.plan_native_purge(state)
    assert plan.refusals == ()
    assert {file.path for file in plan.files} == {
        str(main),
        str(rollover),
        str(agent),
        str(unrelated),
    }
    assert [file.provenance for file in plan.files].count("subagent") == 2
    before = {file.path: Path(file.path).read_bytes() for file in plan.files}
    assert before == {file.path: Path(file.path).read_bytes() for file in plan.files}


def test_legacy_subagent_content_substring_is_not_identity(inventory):
    state, project, home, _ = inventory
    main = write_claude(home, project)
    unrelated = main.parent / "agent-other.jsonl"
    unrelated.write_bytes(claude_bytes(project, OTHER, agentId="other", isSidechain=True, text=THREAD))
    plan = native.plan_native_purge(state)
    assert not plan.refusals
    assert [file.path for file in plan.files] == [str(main)]
    native.unlink_native_file(plan.files[0])
    assert unrelated.exists()


def test_adopted_original_is_labelled_and_removable(inventory):
    state, project, home, _ = inventory
    path = write_claude(home, project)
    state.confirmed.adoption = AdoptionConfirmed(source_runtime="claude_code", source_path=str(path))
    plan = native.plan_native_purge(state)
    assert not plan.refusals
    assert plan.files[0].created_outside_forge
    assert native.unlink_native_file(plan.files[0]) is True
    assert native.unlink_native_file(plan.files[0]) is False


@pytest.mark.parametrize("change", ["session", "cwd", "version", "incomplete", "empty"])
def test_invalid_claude_identity_refuses(inventory, change):
    state, project, home, _ = inventory
    rows = {
        "session": claude_bytes(project, OTHER),
        "cwd": claude_bytes(project.parent),
        "version": claude_bytes(project, version="9.9.9"),
        "incomplete": claude_bytes(project).rstrip(b"\n"),
        "empty": b"",
    }
    path = write_claude(home, project, rows[change])
    plan = native.plan_native_purge(state)
    assert plan.refusals
    assert not plan.files
    assert path.read_bytes() == rows[change]


@pytest.mark.parametrize("link_kind", ["leaf", "directory", "hard"])
def test_symlink_or_hardlink_cannot_authorize_native_deletion(inventory, link_kind):
    state, project, home, _ = inventory
    path = write_claude(home, project)
    outside = project / "unrelated.jsonl"
    outside.write_bytes(path.read_bytes())
    if link_kind == "leaf":
        path.unlink()
        path.symlink_to(outside)
    elif link_kind == "hard":
        path.unlink()
        os.link(outside, path)
    else:
        namespace = path.parent
        moved = namespace.with_name("moved")
        namespace.rename(moved)
        namespace.symlink_to(moved, target_is_directory=True)
    plan = native.plan_native_purge(state)
    assert plan.refusals
    assert outside.exists()


def test_missing_at_preview_cannot_silently_enter_apply(inventory):
    state, project, home, _ = inventory
    plan = native.plan_native_purge(state)
    assert not plan.refusals
    assert plan.files[0].fingerprint is None
    path = write_claude(home, project)
    with pytest.raises(native.NativePurgeError, match="changed"):
        native.unlink_native_file(plan.files[0])
    assert path.exists()


@pytest.mark.parametrize("replacement", [False, True])
def test_changed_or_replaced_after_preview_refuses(inventory, replacement):
    state, project, home, _ = inventory
    path = write_claude(home, project)
    plan = native.plan_native_purge(state)
    if replacement:
        saved = path.read_bytes()
        alternate = path.with_suffix(".tmp")
        alternate.write_bytes(saved)
        alternate.replace(path)
    else:
        path.write_bytes(path.read_bytes() + claude_bytes(project))
    with pytest.raises(native.NativePurgeError, match="changed"):
        native.unlink_native_file(plan.files[0])
    assert path.exists()


def test_runtime_started_after_preview_refuses(inventory, monkeypatch):
    state, project, home, _ = inventory
    path = write_claude(home, project)
    plan = native.plan_native_purge(state)
    monkeypatch.setattr(native, "check_native_inactivity", lambda runtime: ("Native client is running",))
    with pytest.raises(native.NativePurgeError, match="running"):
        native.unlink_native_file(plan.files[0])
    assert path.exists()


@pytest.mark.parametrize("provenance", ["relocated", "rewind"])
def test_copy_provenance_uses_source_bytes_not_filename_identity(inventory, provenance):
    state, project, home, _ = inventory
    parent = project.parent / "parent"
    source = parent / ".forge/artifacts/ancestor/transcripts/parent.jsonl"
    source.parent.mkdir(parents=True)
    first = claude_bytes(parent, OTHER)
    source.write_bytes(first + claude_bytes(parent, OTHER, type="assistant"))
    copy_id = OTHER if provenance == "relocated" else str(uuid4())
    state.confirmed.claude_session_id = None
    state.confirmed.derivation = Derivation(
        parent_session="ancestor",
        parent_forge_root=str(parent),
        parent_transcript=str(source.relative_to(parent)),
        relocated_parent_session_id=copy_id if provenance == "relocated" else None,
        rewind_relocated_session_id=copy_id if provenance == "rewind" else None,
    )
    path = write_claude(
        home,
        project,
        source.read_bytes() if provenance == "relocated" else first,
        copy_id,
    )
    plan = native.plan_native_purge(state)
    assert not plan.refusals
    assert plan.files[0].provenance == provenance
    native.unlink_native_file(plan.files[0])
    assert not path.exists()
    assert source.exists()


def test_rewind_without_source_evidence_refuses(inventory):
    state, project, home, _ = inventory
    state.confirmed.claude_session_id = None
    state.confirmed.derivation = Derivation("ancestor", rewind_relocated_session_id=THREAD)
    path = write_claude(home, project, claude_bytes(project, OTHER))
    plan = native.plan_native_purge(state)
    assert plan.refusals
    assert path.exists()


def test_codex_exact_header_and_retry_roundtrip(inventory):
    state, project, _, home = inventory
    path = write_codex(home, project)
    set_codex(state, path)
    plan = native.plan_native_purge(state)
    assert not plan.refusals
    restored = native.NativePurgePlan.from_dict(json.loads(json.dumps(plan.to_dict())))
    assert restored == plan
    assert native.unlink_native_file(restored.files[0])
    assert not path.exists()


@pytest.mark.parametrize(
    "header",
    [
        {"id": OTHER},
        {"session_id": OTHER},
        {"cli_version": "9.9.9"},
        {"cwd": "/wrong"},
        {"history_base": {"thread_id": OTHER}},
    ],
)
def test_codex_header_disagreement_refuses(inventory, header):
    state, project, _, home = inventory
    path = write_codex(home, project, **header)
    set_codex(state, path)
    assert native.plan_native_purge(state).refusals
    assert path.exists()


def test_codex_unmanaged_native_descendant_refuses(inventory):
    state, project, _, home = inventory
    path = write_codex(home, project)
    child = write_codex(
        home,
        project,
        OTHER,
        forked_from_id=THREAD,
        history_base={
            "thread_id": THREAD,
            "end_ordinal_exclusive": 2,
            "end_byte_offset": 45,
        },
    )
    set_codex(state, path)
    plan = native.plan_native_purge(state)
    assert any(OTHER in reason and "descendant" in reason for reason in plan.refusals)
    assert path.exists() and child.exists()


def test_codex_unreadable_unknown_ancestry_refuses(inventory):
    state, project, _, home = inventory
    path = write_codex(home, project)
    write_codex(home, project, OTHER, version="9.9.9")
    set_codex(state, path)
    assert any("version" in reason for reason in native.plan_native_purge(state).refusals)


def test_codex_duplicate_thread_copy_refuses(inventory):
    state, project, _, home = inventory
    path = write_codex(home, project)
    duplicate = path.with_name(path.name.replace("00-00-00", "01-00-00"))
    duplicate.write_bytes(path.read_bytes())
    set_codex(state, path)
    assert any("Ambiguous" in reason for reason in native.plan_native_purge(state).refusals)


def test_inventory_deserialization_rejects_path_injection(inventory):
    state, project, home, _ = inventory
    write_claude(home, project)
    record = native.plan_native_purge(state).files[0].to_dict()
    record["path"] = str(project / "unrelated.jsonl")
    with pytest.raises(ValueError):
        native.NativePurgeFile.from_dict(record)


def test_inventory_deserialization_rejects_unknown_fields(inventory):
    state, project, home, _ = inventory
    write_claude(home, project)
    record = native.plan_native_purge(state).files[0].to_dict()
    record["erase_everything"] = True
    with pytest.raises(native.NativePurgeError):
        native.NativePurgeFile.from_dict(record)


@pytest.mark.parametrize(
    ("runtime", "line"),
    [
        ("claude", "987654 /usr/local/bin/claude claude --resume anything"),
        (
            "claude",
            "987654 /usr/local/bin/node node /usr/lib/node_modules/@anthropic-ai/claude-code/cli.js",
        ),
        (
            "codex",
            "987654 /Applications/Codex.app/Contents/MacOS/Codex codex app-server",
        ),
    ],
)
def test_census_detects_unmanaged_runtime(monkeypatch, runtime, line):
    monkeypatch.setattr(
        native.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, line, ""),
    )
    assert "987654" in native.check_native_inactivity(runtime)[0]


@pytest.mark.parametrize("result", ["", "not a valid census", "12 python"])
def test_unknown_process_census_refuses(monkeypatch, result):
    monkeypatch.setattr(
        native.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, result, ""),
    )
    assert native.check_native_inactivity("claude")


def test_census_failure_refuses(monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("ps", 5)

    monkeypatch.setattr(native.subprocess, "run", fail)
    assert native.check_native_inactivity("codex")


def test_unrelated_command_mentioning_runtime_is_not_a_writer(monkeypatch):
    result = subprocess.CompletedProcess([], 0, "987654 python python -m pytest test_claude.py", "")
    monkeypatch.setattr(native.subprocess, "run", lambda *args, **kwargs: result)
    assert native.check_native_inactivity("claude") == ()


def test_noncanonical_case_variant_uuid_refuses_purge(inventory):
    state, project, home, _ = inventory
    original = write_claude(home, project)
    state.confirmed.claude_session_id = THREAD.upper()
    plan = native.plan_native_purge(state)
    assert any("canonical UUID" in refusal for refusal in plan.refusals)
    assert original.exists()


def test_restored_inventory_cannot_add_another_native_conversation(inventory):
    state, project, home, _ = inventory
    write_claude(home, project)
    write_claude(home, project, session_id=OTHER)
    plan = native.plan_native_purge(state)
    unrelated = native.NativePurgeFile(
        str(home / "projects" / encode_project_path(str(project)) / f"{OTHER}.jsonl"),
        str(home),
        "claude",
        "original",
        OTHER,
        str(project),
        False,
        None,
    )
    with pytest.raises(native.NativePurgeError, match="not owned"):
        native.validate_native_purge_scope(native.NativePurgePlan((*plan.files, unrelated)), state)


def write_agent_metadata(home, project):
    """Mirror the four-field object and Agent request captured on Claude 2.1.245."""
    metadata = {
        "agentType": "purge-probe",
        "description": "Purge probe acknowledgement",
        "toolUseId": "toolu_01TZMbA95QHcPqqPRuQs1ygA",
        "spawnDepth": 1,
    }
    request = {
        "type": "tool_use",
        "id": metadata["toolUseId"],
        "name": "Agent",
        "input": {"subagent_type": metadata["agentType"], "description": metadata["description"]},
    }
    main = write_claude(home, project, claude_bytes(project, message={"content": [request]}))
    agent = main.parent / THREAD / "subagents" / "agent-abc123.jsonl"
    agent.parent.mkdir(parents=True)
    agent.write_bytes(claude_bytes(project, agentId="abc123", isSidechain=True))
    companion = agent.with_suffix(".meta.json")
    companion.write_text(json.dumps(metadata))
    return main, agent, companion


def test_characterized_metadata_roundtrip_and_partial_retry(inventory):
    state, project, home, _ = inventory
    main, agent, companion = write_agent_metadata(home, project)
    plan = native.plan_native_purge(state)
    assert not plan.refusals
    assert [file.path for file in plan.files] == [str(companion), str(agent), str(main)]
    restored = native.NativePurgePlan.from_dict(json.loads(json.dumps(plan.to_dict())))
    native.validate_native_purge_scope(restored, state)
    for file in restored.files:
        assert native.unlink_native_file(file)
        native.validate_native_purge_scope(restored, state)
    assert all(not Path(file.path).exists() for file in restored.files)
    assert all(not native.unlink_native_file(file) for file in restored.files)


@pytest.mark.parametrize(
    "change",
    [
        {"unknown": "content"},
        {"spawnDepth": 2},
        {"spawnDepth": True},
        {"toolUseId": "toolu_absent"},
        {"agentType": "different"},
        {"description": "different"},
    ],
)
def test_unknown_metadata_or_parent_disagreement_refuses(inventory, change):
    state, project, home, _ = inventory
    paths = write_agent_metadata(home, project)
    companion = paths[-1]
    companion.write_text(json.dumps({**json.loads(companion.read_text()), **change}))
    assert native.plan_native_purge(state).refusals
    assert all(path.exists() for path in paths)


@pytest.mark.parametrize("missing", ["main", "agent"])
def test_orphan_metadata_cannot_authorize_removal(inventory, missing):
    state, project, home, _ = inventory
    main, agent, companion = write_agent_metadata(home, project)
    (main if missing == "main" else agent).unlink()
    assert native.plan_native_purge(state).refusals
    assert companion.exists()


def test_changed_metadata_after_preview_is_retained(inventory):
    state, project, home, _ = inventory
    main, agent, companion = write_agent_metadata(home, project)
    plan = native.plan_native_purge(state)
    companion.write_text(companion.read_text() + " ")
    with pytest.raises(native.NativePurgeError, match="changed"):
        native.unlink_native_file(plan.files[0])
    assert main.exists() and agent.exists() and companion.exists()


def test_restored_metadata_path_must_belong_to_recorded_parent(inventory):
    state, project, home, _ = inventory
    write_agent_metadata(home, project)
    record = native.plan_native_purge(state).files[0].to_dict()
    record["path"] = record["path"].replace(THREAD, OTHER)
    with pytest.raises(native.NativePurgeError, match="Unsupported Claude subagent path"):
        native.NativePurgeFile.from_dict(record)
