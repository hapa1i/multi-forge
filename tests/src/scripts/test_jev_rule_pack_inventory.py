"""The local feasibility inventory enforces bounds before touching native content."""

import importlib.util
import json
import sys
from pathlib import Path
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def inventory(monkeypatch):
    path = ROOT / "scripts/experiments/jev/rule-pack-inventory.py"
    spec = importlib.util.spec_from_file_location("jev_rule_pack_inventory", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def setup(tmp_path, inventory):
    home, repo = tmp_path / "home", tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    (home / ".forge/sessions").mkdir(parents=True)
    rows = {}

    def add(number, runtime="claude_code", **changes):
        name = f"session-{number:02d}"
        key = name + "|" + inventory.digest(str(repo).encode())[:12]
        native_id = str(UUID(int=number + 1))
        manifest = {
            "schema_version": 5,
            "name": name,
            "forge_root": str(repo),
            "worktree": None,
            "intent": {"launch": {"mode": "host", "runtime": runtime}},
            "confirmed": {
                "claude_session_id": native_id if runtime == "claude_code" else None,
                "claude_project_root": str(repo),
                "transcript_path": str(home / ".claude/projects/confirmed.jsonl"),
                "codex": (
                    {"thread_id": native_id, "rollout_path": "/unread/native.jsonl"} if runtime == "codex" else None
                ),
            },
        }
        manifest.update(changes)
        path = repo / ".forge/sessions" / name / "forge.session.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(manifest))
        rows[key] = {
            "project_root": str(repo),
            "forge_root": str(repo),
            "worktree_path": str(repo),
            "last_accessed_at": f"2026-10-15T10:{number:02d}:00Z",
            "claude_session_id": native_id if runtime == "claude_code" else None,
            "codex_thread_id": native_id if runtime == "codex" else None,
        }
        return key, path

    def save(active=None):
        (home / ".forge/sessions/index.json").write_text(json.dumps({"version": 1, "sessions": rows}))
        (home / ".forge/sessions/active.json").write_text(json.dumps({"version": 1, "sessions": active or {}}))

    return home, repo, rows, add, save


def test_metadata_selects_before_native_content_and_honors_runtime_slots(inventory, setup, monkeypatch):
    home, repo, _, add, save = setup
    for n in range(8):
        add(n, runtime="claude_code" if n < 4 else "codex")
    save()
    actual_read = inventory.read_regular
    paths = []

    def track(path, limit):
        paths.append(path)
        return actual_read(path, limit)

    monkeypatch.setattr(inventory, "read_regular", track)
    summary, ledger = inventory.inventory_metadata(repo, home, {str(repo)})
    assert summary["selected_by_runtime"] == {"codex": 3, "claude_code": 3}
    assert summary["native_files_read"] == 0
    assert len(paths) == 10
    assert all(path.name in {"index.json", "active.json", "forge.session.json"} for path in paths)
    assert [row["canonical_identity"].split("|")[0] for row in ledger["selected"]] == [
        "session-07",
        "session-06",
        "session-05",
        "session-03",
        "session-02",
        "session-01",
    ]


def test_unrelated_index_rows_are_discarded_and_never_followed(inventory, setup):
    home, repo, rows, add, save = setup
    add(1)
    rows["unrelated"] = {"project_root": "/another/repository", "secret": "PRIVATE_SENTINEL"}
    save()
    summary, ledger = inventory.inventory_metadata(repo, home, {str(repo)})
    assert summary["matching_index_rows"] == 1
    assert "PRIVATE_SENTINEL" not in json.dumps(ledger)


def test_manifests_are_capped_by_recency_before_eligibility(inventory, setup, monkeypatch):
    home, repo, _, add, save = setup
    for n in range(30):
        add(n)
    save()
    reads = []
    actual_read = inventory.read_regular

    def track(path, limit):
        reads.append(path)
        return actual_read(path, limit)

    monkeypatch.setattr(inventory, "read_regular", track)
    summary, _ = inventory.inventory_metadata(repo, home, {str(repo)})
    assert summary["metadata_candidates_within_cap"] == 24
    assert summary["metadata_candidates_beyond_cap"] == 6
    assert sum(path.name == "forge.session.json" for path in reads) == 24


def test_active_and_sidecar_sessions_are_excluded_without_repair(inventory, setup):
    home, repo, _, add, save = setup
    key, _ = add(1)
    add(2, intent={"launch": {"mode": "sidecar", "runtime": "claude_code"}})
    save({key: {"forge_root": str(repo), "worktree_path": str(repo), "started_at": "2026-10-15T10:00:00Z"}})
    before = (home / ".forge/sessions/active.json").read_bytes()
    summary, ledger = inventory.inventory_metadata(repo, home, {str(repo)})
    assert summary["metadata_exclusions"] == {"active_registry_entry": 1, "sidecar_or_unknown_launch": 1}
    assert ledger["selected"] == []
    assert (home / ".forge/sessions/active.json").read_bytes() == before


def test_missing_active_registry_refuses_uncertain_liveness(inventory, setup):
    home, repo, _, add, save = setup
    add(1)
    save()
    (home / ".forge/sessions/active.json").unlink()
    with pytest.raises(inventory.Refusal, match="missing_path"):
        inventory.inventory_metadata(repo, home, {str(repo)})


def test_missing_or_custom_source_is_selected_without_native_fallback(inventory, setup):
    home, repo, _, add, save = setup
    add(1)
    save()
    summary, ledger = inventory.inventory_metadata(repo, home, {str(repo)})
    assert summary["selected_sessions"] == 1
    assert ledger["selected"][0]["native_path"].endswith("/confirmed.jsonl")
    assert summary["native_files_read"] == 0


def test_symlink_and_unverified_worktree_cannot_expand_reads(inventory, setup, tmp_path):
    home, repo, rows, add, save = setup
    key, manifest = add(1)
    actual = tmp_path / "target"
    actual.write_bytes(manifest.read_bytes())
    manifest.unlink()
    manifest.symlink_to(actual)
    save()
    summary, _ = inventory.inventory_metadata(repo, home, {str(repo)})
    assert summary["metadata_exclusions"] == {"unreadable_or_symlinked_file": 1}
    rows[key]["worktree_path"] = "/unverified"
    save()
    summary, _ = inventory.inventory_metadata(repo, home, {str(repo)})
    assert summary["metadata_exclusions"] == {"unverified_worktree_membership": 1}


def test_metadata_allowlist_discards_manifest_user_and_auth_data(inventory, setup):
    home, repo, _, add, save = setup
    _, path = add(1)
    data = json.loads(path.read_text())
    data["intent"]["user_task"] = "PRIVATE_TASK"
    data["confirmed"]["auth"] = "PRIVATE_AUTH"
    path.write_text(json.dumps(data))
    save()
    _, ledger = inventory.inventory_metadata(repo, home, {str(repo)})
    assert "PRIVATE_" not in json.dumps(ledger)


def test_bounded_file_reads_and_private_outputs(inventory, tmp_path):
    path = tmp_path / "data.json"
    path.write_bytes(b"x" * 10)
    with pytest.raises(inventory.Refusal, match="file_size_limit"):
        inventory.read_regular(path, 9)
    out = tmp_path / "output.json"
    inventory.private_write(out, {"count": 1})
    assert out.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        inventory.private_write(out, {})


def test_index_and_manifest_schema_refusals_are_bounded(inventory, setup):
    home, repo, _, add, save = setup
    add(1, schema_version=99)
    save()
    summary, _ = inventory.inventory_metadata(repo, home, {str(repo)})
    assert summary["metadata_exclusions"] == {"unsupported_manifest_schema": 1}
    (home / ".forge/sessions/active.json").write_text('{"version":99,"sessions":{}}')
    with pytest.raises(inventory.Refusal, match="unsupported_index_schema"):
        inventory.inventory_metadata(repo, home, {str(repo)})


def test_source_admission_refuses_custom_missing_and_oversized_without_replacement(inventory, setup, monkeypatch):
    home, repo, _, add, save = setup
    _, manifest = add(1)
    data = json.loads(manifest.read_text())
    native_id = data["confirmed"]["claude_session_id"]
    expected = home / ".claude/projects" / str(repo).replace("/", "-").replace(".", "-").replace("_", "-")
    source = expected / f"{native_id}.jsonl"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"PRIVATE_SOURCE_BYTES")
    data["confirmed"]["transcript_path"] = str(source)
    manifest.write_text(json.dumps(data))
    save()
    _, metadata = inventory.inventory_metadata(repo, home, {str(repo)})
    summary, sources = inventory.inspect_sources(metadata)
    assert summary["source_files_admitted_by_metadata"] == 1
    assert summary["native_files_read"] == 0
    assert "PRIVATE_SOURCE_BYTES" not in json.dumps(sources)
    monkeypatch.setattr(inventory, "MAX_NATIVE_BYTES", 1)
    summary, sources = inventory.inspect_sources(metadata)
    assert summary["source_exclusions"] == {"native_file_size_limit": 1}
    assert sources["admitted"] == []
    source.unlink()
    summary, _ = inventory.inspect_sources(metadata)
    assert summary["source_exclusions"] == {"missing_path": 1}


def test_custom_native_paths_are_refused_before_filesystem_inspection(inventory, monkeypatch):
    row = {
        "native_path": "/custom-home/private.jsonl",
        "forge_root": "/approved/repo",
        "canonical_identity": "session-aa|identity",
        "runtime": "claude_code",
        "expected_claude_path": "/home/.claude/projects/-approved-repo/uuid.jsonl",
    }

    def forbid(path, **kwargs):
        raise AssertionError("Out-of-scope source path inspected")

    monkeypatch.setattr(inventory, "no_symlinks", forbid)
    with pytest.raises(inventory.Refusal, match="custom_or_unconfirmed_native_store"):
        inventory.admit_source(row, Path("/home"))


def test_supported_v1_metadata_keeps_its_recency_slot(inventory, setup):
    home, repo, _, add, save = setup
    for number in range(4):
        add(number, schema_version=1 if number == 3 else 5)
    save()
    summary, ledger = inventory.inventory_metadata(repo, home, {str(repo)})
    assert summary["metadata_exclusions"] == {}
    assert summary["eligible_metadata_rows"] == 4
    assert ledger["selected"][0]["canonical_identity"].startswith("session-03|")


@pytest.mark.parametrize("invalid", [{}, {"unexpected": 1}, {"launcher_pid": -1}])
def test_corrupt_active_metadata_does_not_authorize_inactive_selection(inventory, setup, invalid):
    home, repo, _, add, save = setup
    key, _ = add(1)
    active = {"forge_root": str(repo), "worktree_path": str(repo)}
    if invalid:
        active["started_at"] = "2026-10-15T10:00:00Z"
    active.update(invalid)
    save({key: active})
    before = (home / ".forge/sessions/active.json").read_bytes()
    with pytest.raises(inventory.Refusal, match="uncertain_active_registry"):
        inventory.inventory_metadata(repo, home, {str(repo)})
    assert (home / ".forge/sessions/active.json").read_bytes() == before


def test_leaf_symlink_race_refuses_before_reading(inventory, tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.write_text("approved")
    target = tmp_path / "unapproved"
    target.write_text("MUST_NOT_READ")
    original_open = inventory.os.open

    def swap_at_open(path, flags, *args, **kwargs):
        if path == source.name:
            source.unlink()
            source.symlink_to(target)
            assert flags & inventory.os.O_NOFOLLOW
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(inventory.os, "open", swap_at_open)
    with pytest.raises(inventory.Refusal, match="unreadable_or_symlinked_file"):
        inventory.read_regular(source, 100)


def test_component_symlink_race_refuses_before_leaf_open(inventory, tmp_path, monkeypatch):
    component = tmp_path / "component"
    component.mkdir()
    source = component / "source"
    source.write_text("approved")
    target = tmp_path / "unapproved"
    target.mkdir()
    (target / "source").write_text("MUST_NOT_READ")
    original_open = inventory.os.open
    leaf_opened = False

    def swap_at_open(path, flags, *args, **kwargs):
        nonlocal leaf_opened
        if path == component.name:
            component.rename(tmp_path / "original")
            component.symlink_to(target)
            assert flags & inventory.os.O_NOFOLLOW
        if path == source.name:
            leaf_opened = True
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(inventory.os, "open", swap_at_open)
    with pytest.raises(inventory.Refusal, match="unreadable_or_symlinked_file"):
        inventory.read_regular(source, 100)
    assert leaf_opened is False


def test_changed_index_snapshot_stops_before_any_manifest_read(inventory, setup, monkeypatch):
    home, repo, rows, add, save = setup
    key, _ = add(1)
    save()
    _, ledger = inventory.inventory_metadata(repo, home, {str(repo)})
    rows[key]["last_accessed_at"] = "2026-10-16T12:00:00Z"
    save()
    original_read = inventory.read_regular

    def forbid_manifests(path, limit):
        assert path.name != "forge.session.json"
        return original_read(path, limit)

    monkeypatch.setattr(inventory, "read_regular", forbid_manifests)
    with pytest.raises(inventory.Refusal, match="metadata_snapshot_changed"):
        inventory.inventory_metadata(
            repo, home, {str(repo)}, expected_hashes=(ledger["index_sha256"], ledger["active_index_sha256"])
        )


def test_source_admission_refuses_duplicate_and_excess_selected_rows(inventory, setup):
    home, repo, _, add, save = setup
    add(1)
    save()
    _, ledger = inventory.inventory_metadata(repo, home, {str(repo)})
    ledger["selected"] *= 2
    with pytest.raises(inventory.Refusal, match="duplicate_or_missing_selected_identity"):
        inventory.inspect_sources(ledger)
    ledger["selected"] *= 4
    with pytest.raises(inventory.Refusal, match="metadata_selection_limit"):
        inventory.inspect_sources(ledger)
