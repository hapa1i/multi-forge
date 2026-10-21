"""The approved native probe cannot broaden its arguments or accidentally retry."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/experiments/session-purge/run_native_probe.py"
MANIFEST = ROOT / "docs/board/done/session_delete_and_purge/evidence/native-probe-manifest.json"
spec = importlib.util.spec_from_file_location("run_native_probe", SCRIPT)
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_only_exact_manifest_is_accepted(tmp_path: Path) -> None:
    manifest = runner.load_manifest(MANIFEST)
    assert manifest["max_native_invocations"] == 1
    manifest["native_argv"].append("--dangerous-extra-argument")
    modified = tmp_path / "manifest.json"
    modified.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="exact approved"):
        runner.load_manifest(modified)


def test_container_has_no_mount_or_persisted_auth() -> None:
    command = runner.container_argv(runner.load_manifest(MANIFEST))
    assert not {"--volume", "-v", "--mount"}.intersection(command)
    assert not any("ANTHROPIC_API_KEY" in part for part in command)
    assert command[-2:] == ["sleep", "infinity"]


def test_export_verification_detects_missing_or_changed_bytes(tmp_path: Path) -> None:
    report = tmp_path / "native-result.json"
    report.write_text('{"status": "captured_for_review"}')
    (tmp_path / "export-inventory.json").write_text(json.dumps({"native-result.json": runner._sha(report)}))
    runner.verify_export(tmp_path)
    report.write_text("changed")
    with pytest.raises(ValueError, match="changed or is incomplete"):
        runner.verify_export(tmp_path)


def test_checked_in_companion_capture_and_approved_payload_keep_exact_bytes() -> None:
    evidence = MANIFEST.parent
    manifest = runner.load_manifest(evidence / "native-companion-probe-manifest.json")
    assert runner._sha(SCRIPT.with_name("native_probe_payload.py")) == manifest["payload_sha256"]
    runner.verify_export(evidence / "native-companion-probe-20261020/container-evidence")


def test_missing_key_refuses_before_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(runner, "_command", lambda *args, **kwargs: pytest.fail("Docker must not be called"))
    with pytest.raises(ValueError, match="absent"):
        runner.run_probe(MANIFEST, tmp_path / "new")


def test_existing_container_refuses_without_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-key")
    calls = []

    def command(argv, *args, **kwargs):
        calls.append(argv)
        return "forge-native-purge-20261020\n" if "ls" in argv else "28.0"

    monkeypatch.setattr(runner, "_command", command)
    with pytest.raises(ValueError, match="existing container"):
        runner.run_probe(MANIFEST, tmp_path / "new")
    assert len(calls) == 2 and not (tmp_path / "new").exists()


def test_failed_native_call_is_not_retried_and_exports_before_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-key")
    calls = []
    output = tmp_path / "new"

    def command(argv, *args, **kwargs):
        calls.append(argv)
        if argv[-1] == "run":
            metadata = json.loads((output / "execution.json").read_text())
            assert metadata["native_invocations_dispatched"] == 1
            raise ValueError("synthetic inference failure")
        return ""

    monkeypatch.setattr(runner, "_command", command)
    with pytest.raises(ValueError, match="inference failure"):
        runner.run_probe(MANIFEST, output)
    assert sum(argv[-1] == "run" for argv in calls) == 1
    assert calls[-3][1:2] == ["cp"]
    assert calls[-2][1:2] == ["stop"]
    assert calls[-1][1:2] == ["rm"]
    assert json.loads((output / "execution.json").read_text())["status"] == "failed_no_retry"
    with pytest.raises(ValueError, match="new absolute"):
        runner.run_probe(MANIFEST, output)


def test_payload_lifecycle_with_synthetic_native_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from forge.session.claude.paths import encode_project_path

    payload_spec = importlib.util.spec_from_file_location(
        "native_probe_payload", SCRIPT.with_name("native_probe_payload.py")
    )
    assert payload_spec is not None and payload_spec.loader is not None
    payload = importlib.util.module_from_spec(payload_spec)
    payload_spec.loader.exec_module(payload)
    monkeypatch.setattr(payload, "PROBE", tmp_path)
    monkeypatch.setattr(payload, "EVIDENCE", tmp_path / "evidence")
    monkeypatch.setattr("forge.session.purge_native.check_native_inactivity", lambda runtime: ())
    monkeypatch.setattr("forge.session.deletion.check_native_inactivity", lambda runtime: ())
    root, home = tmp_path / "workspace", tmp_path / "native"
    root.mkdir()
    payload.EVIDENCE.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    native_id = "aaaa1111-2222-4333-8444-555555555555"
    project = home / "projects" / encode_project_path(str(root))
    main = project / f"{native_id}.jsonl"
    agent = project / native_id / "subagents/agent-test.jsonl"
    agent.parent.mkdir(parents=True)
    row = {"type": "user", "sessionId": native_id, "cwd": str(root), "version": "2.1.245"}
    main.write_text(json.dumps(row) + "\n")
    agent.write_text(json.dumps({**row, "isSidechain": True, "agentId": "test"}) + "\n")
    result = payload.verify_lifecycle([{"path": str(main)}, {"path": str(agent)}])
    assert result["unrelated_sentinel_preserved"]
    assert set(result["purge_removed_exact_paths"]) == {str(main), str(agent)}
    assert set(result["offline_copies"]) == {"relocated", "rewind"}
