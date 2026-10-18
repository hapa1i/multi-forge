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


def confirm_source(home, repo, manifest, *, exists=True):
    data = json.loads(manifest.read_text())
    if data["intent"]["launch"]["runtime"] == "claude_code":
        native_id = data["confirmed"]["claude_session_id"]
        source = (
            home
            / ".claude/projects"
            / str(repo).replace("/", "-").replace(".", "-").replace("_", "-")
            / f"{native_id}.jsonl"
        )
        data["confirmed"]["transcript_path"] = str(source)
    else:
        native_id = data["confirmed"]["codex"]["thread_id"]
        source = home / ".codex/sessions/2026/10/15" / f"rollout-2026-10-15T10-00-00-{native_id}.jsonl"
        data["confirmed"]["codex"]["rollout_path"] = str(source)
    data["confirmed"]["auth"] = "PRIVATE_AUTH"
    data["intent"]["user_task"] = "PRIVATE_TASK"
    manifest.write_text(json.dumps(data))
    if exists:
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"PRIVATE_NATIVE_CONTENT")
    return source


def test_availability_allocates_after_missing_paths_without_changing_old_mode(inventory, setup, monkeypatch):
    home, repo, _, add, save = setup
    for number in range(10):
        _, manifest = add(number, runtime="claude_code" if number < 5 else "codex")
        confirm_source(home, repo, manifest, exists=number not in (4, 9))
    save()
    old_summary, old = inventory.inventory_metadata(repo, home, {str(repo)})
    assert [row["canonical_identity"].split("|")[0] for row in old["selected"]] == [
        "session-09",
        "session-08",
        "session-07",
        "session-04",
        "session-03",
        "session-02",
    ]
    assert old_summary["stage"] == "metadata"
    assert "source" not in old["selected"][0]
    assert "candidates" not in old
    reads, checked = [], []
    actual_read, actual_admit = inventory.read_regular, inventory.admit_source

    def read_metadata_only(path, limit):
        assert path.name in {"index.json", "active.json", "forge.session.json"}
        reads.append(path.name)
        return actual_read(path, limit)

    def track_source(row, source_home):
        checked.append(row["canonical_identity"])
        return actual_admit(row, source_home)

    monkeypatch.setattr(inventory, "read_regular", read_metadata_only)
    monkeypatch.setattr(inventory, "admit_source", track_source)
    summary, ledger = inventory.inventory_availability(repo, home, {str(repo)})
    assert reads.count("index.json") == reads.count("active.json") == 1
    assert reads.count("forge.session.json") == 10
    assert len(checked) == summary["native_paths_checked"] == 10
    assert summary["selected_by_runtime"] == {"codex": 3, "claude_code": 3}
    assert summary["available_sources_by_runtime"] == {"codex": 4, "claude_code": 4}
    assert summary["source_exclusions"] == {"missing_path": 2}
    assert summary["available_sources_beyond_runtime_cap"] == 2
    assert summary["runtime_shortfalls"] == {"claude_code": 0, "codex": 0}
    assert [row["canonical_identity"].split("|")[0] for row in ledger["selected"]] == [
        "session-08",
        "session-07",
        "session-06",
        "session-03",
        "session-02",
        "session-01",
    ]
    assert len(ledger["candidates"]) == 10
    assert sum(row["status"] == "selected" for row in ledger["candidates"]) == 6
    assert "PRIVATE_" not in json.dumps(ledger)


def test_availability_has_one_fixed_cohort_and_never_searches_outside_it(inventory, setup, monkeypatch):
    home, repo, rows, add, save = setup
    for number in range(30):
        _, manifest = add(number)
        confirm_source(home, repo, manifest)
    rows["unrelated"] = {
        "project_root": "/another/repository",
        "last_accessed_at": "2026-10-18T00:00:00Z",
        "secret": "PRIVATE_OTHER",
    }
    save()
    read_paths, checked = [], []
    actual_read, actual_admit = inventory.read_regular, inventory.admit_source

    def read_metadata_only(path, limit):
        assert path.name in {"index.json", "active.json", "forge.session.json"}
        read_paths.append(path)
        return actual_read(path, limit)

    def track_source(row, source_home):
        checked.append(row["canonical_identity"])
        return actual_admit(row, source_home)

    def no_discovery(*args, **kwargs):
        raise AssertionError("Inventory must not discover native files")

    monkeypatch.setattr(inventory, "read_regular", read_metadata_only)
    monkeypatch.setattr(inventory, "admit_source", track_source)
    monkeypatch.setattr(Path, "glob", no_discovery)
    monkeypatch.setattr(Path, "rglob", no_discovery)
    monkeypatch.setattr(inventory.os, "walk", no_discovery)
    summary, ledger = inventory.inventory_availability(repo, home, {str(repo)})
    assert summary["matching_index_rows"] == 30
    assert summary["metadata_candidates_within_cap"] == 24
    assert summary["metadata_candidates_beyond_cap"] == 6
    assert summary["native_paths_checked"] == len(checked) == len(ledger["candidates"]) == 24
    assert sum(path.name == "forge.session.json" for path in read_paths) == 24
    assert [key.split("|")[0] for key in checked] == [f"session-{number:02d}" for number in range(29, 5, -1)]
    assert summary["selected_sessions"] == 3
    assert summary["available_sources_beyond_runtime_cap"] == 21
    assert summary["runtime_shortfalls"] == {"claude_code": 0, "codex": 3}
    assert all("PRIVATE_" not in json.dumps(value) for value in (summary, ledger))
    assert str(home) not in json.dumps(summary) and str(repo) not in json.dumps(summary)


def test_availability_retains_metadata_refusals_and_checks_only_eligible_paths(inventory, setup, monkeypatch):
    home, repo, rows, add, save = setup
    active_key, _ = add(0)
    add(1, intent={"launch": {"mode": "sidecar", "runtime": "claude_code"}})
    bad_key, _ = add(2)
    rows[bad_key]["worktree_path"] = "/unverified"
    add(3, schema_version=99)
    add(4)
    _, manifest = add(5)
    confirm_source(home, repo, manifest)
    save({active_key: {"forge_root": str(repo), "worktree_path": str(repo), "started_at": "2026-10-15T10:00:00Z"}})
    summary, ledger = inventory.inventory_availability(repo, home, {str(repo)})
    assert summary["metadata_exclusions"] == {
        "active_registry_entry": 1,
        "sidecar_or_unknown_launch": 1,
        "unverified_worktree_membership": 1,
        "unsupported_manifest_schema": 1,
    }
    assert summary["source_exclusions"] == {"custom_or_unconfirmed_native_store": 1}
    assert summary["native_paths_checked"] == 2
    assert summary["selected_sessions"] == 1
    assert len(ledger["candidates"]) == 6
    assert all(row["status"] in {"selected", "excluded"} for row in ledger["candidates"])
    assert all(row["reason"] is not None for row in ledger["candidates"] if row["status"] == "excluded")


@pytest.mark.parametrize("unsafe", ["symlink", "oversized", "directory", "missing"])
def test_availability_rejects_unsafe_native_metadata_without_reading_contents(inventory, setup, unsafe, monkeypatch):
    home, repo, _, add, save = setup
    _, manifest = add(1)
    source = confirm_source(home, repo, manifest)
    if unsafe == "symlink":
        target = source.with_name("unapproved")
        source.rename(target)
        source.symlink_to(target)
    elif unsafe == "oversized":
        monkeypatch.setattr(inventory, "MAX_NATIVE_BYTES", 1)
    elif unsafe == "directory":
        source.unlink()
        source.mkdir()
    else:
        source.unlink()
    save()
    original_open = inventory.os.open

    def no_native_open(path, *args, **kwargs):
        assert str(path) not in {str(source), source.name}
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(inventory.os, "open", no_native_open)
    summary, ledger = inventory.inventory_availability(repo, home, {str(repo)})
    reason = {
        "symlink": "symlink_component",
        "oversized": "native_file_size_limit",
        "directory": "non_regular_file",
        "missing": "missing_path",
    }[unsafe]
    assert summary["source_exclusions"] == {reason: 1}
    assert summary["native_files_read"] == summary["native_bytes_read"] == summary["selected_sessions"] == 0
    assert ledger["selected"] == []


def test_availability_records_fixed_action_window_without_filtering_session_recency(inventory, setup):
    home, repo, rows, add, save = setup
    first, first_manifest = add(1)
    last, last_manifest = add(2, runtime="codex")
    confirm_source(home, repo, first_manifest)
    confirm_source(home, repo, last_manifest)
    rows[first]["last_accessed_at"] = "2026-09-30T23:59:59Z"
    rows[last]["last_accessed_at"] = "2026-10-19T00:00:00Z"
    save()
    summary, ledger = inventory.inventory_availability(repo, home, {str(repo)})
    assert summary["prospective_action_window"] == {
        "start_inclusive": "2026-10-01T00:00:00Z",
        "end_exclusive": "2026-10-18T00:00:00Z",
    }
    assert summary["selected_sessions"] == 2
    assert summary["action_window_verified"] is False
    assert summary["native_header_identity_verified"] is False
    assert summary["completed_turns_verified"] is False
    assert summary["native_actions_admitted"] is False
    assert summary["named_actions_selected"] == 0
    assert summary["quality_accepted"] is False and summary["runtime_admitted"] is False
    assert "retained local sources" in ledger["selection_bias"]
    for row in ledger["selected"]:
        info = Path(row["source"]["path"]).stat()
        assert row["source"] == {
            "path": row["native_path"],
            "size": info.st_size,
            "device": info.st_dev,
            "inode": info.st_ino,
        }


def test_availability_duplicate_native_identity_is_excluded_before_path_checks(inventory, setup, monkeypatch):
    home, repo, rows, add, save = setup
    first, first_manifest = add(1)
    second, second_manifest = add(2)
    source = confirm_source(home, repo, first_manifest)
    data = json.loads(second_manifest.read_text())
    data["confirmed"]["claude_session_id"] = rows[first]["claude_session_id"]
    data["confirmed"]["transcript_path"] = str(source)
    rows[second]["claude_session_id"] = rows[first]["claude_session_id"]
    second_manifest.write_text(json.dumps(data))
    save()

    def no_source(*args):
        raise AssertionError("Duplicate native identity must not be inspected")

    monkeypatch.setattr(inventory, "admit_source", no_source)
    summary, ledger = inventory.inventory_availability(repo, home, {str(repo)})
    assert summary["metadata_exclusions"] == {"duplicate_native_identity": 2}
    assert summary["native_paths_checked"] == 0
    assert ledger["selected"] == []
    assert all(row["reason"] == "duplicate_native_identity" for row in ledger["candidates"])


def test_availability_cli_uses_only_fixture_stores_and_exclusive_private_outputs(inventory, setup, monkeypatch, capsys):
    home, repo, _, add, save = setup
    _, manifest = add(1)
    confirm_source(home, repo, manifest)
    save()
    monkeypatch.setattr(inventory, "REPOSITORY", repo)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(inventory, "verified_worktrees", lambda repository: {str(repo)})
    monkeypatch.setattr(sys, "argv", ["rule-pack-inventory.py", "--availability-first"])
    assert inventory.main() == 0
    emitted = capsys.readouterr()
    summary = json.loads(emitted.out)
    directory = Path(summary.pop("private_directory"))
    try:
        assert emitted.err == ""
        assert directory.name.startswith("jev-a2-availability-")
        assert directory.stat().st_mode & 0o777 == 0o700
        assert {path.name for path in directory.iterdir()} == {"availability-private.json", "availability-summary.json"}
        private = directory / "availability-private.json"
        assert private.stat().st_mode & 0o777 == 0o600
        ledger = json.loads(private.read_text())
        assert ledger["summary"] == summary
        assert "PRIVATE_" not in emitted.out and str(home) not in emitted.out and str(repo) not in emitted.out
        with pytest.raises(FileExistsError):
            inventory.private_write(private, {})
        assert json.loads(private.read_text()) == ledger
    finally:
        for path in directory.iterdir():
            path.unlink()
        directory.rmdir()
