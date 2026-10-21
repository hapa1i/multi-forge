"""Container-only execution and evidence capture for one approved native probe."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.claude.paths import encode_project_path
from forge.session.deletion import apply_session_deletion, plan_session_deletion
from forge.session.models import Derivation, SessionState
from forge.session.purge_native import (
    check_native_inactivity,
    plan_native_purge,
    unlink_native_file,
)

PROBE = Path("/probe")
EVIDENCE = PROBE / "evidence"
MANIFEST = PROBE / "manifest.json"


def preflight() -> dict[str, Any]:
    """Check isolation, binary identity, and real process census before inference."""
    manifest = json.loads(MANIFEST.read_text())
    if not Path("/.dockerenv").exists() or Path.cwd() != Path(manifest["container_workspace"]):
        raise ValueError("Probe must run in the isolated container workspace")
    for key, value in manifest["container_environment"].items():
        if os.environ.get(key) != value:
            raise ValueError(f"Unexpected isolated environment: {key}")
    if Path(".git").exists() or any(Path("/probe/home").iterdir()):
        raise ValueError("Native preflight requires an empty probe home and a non-repository workspace")
    version = subprocess.run(
        ["claude", "--version"], check=True, capture_output=True, text=True, timeout=15
    ).stdout.strip()
    if version.split()[0] != manifest["runtime"]["claude"]:
        raise ValueError("Claude version differs from the approved manifest")
    executable = Path(shutil.which("claude") or "").resolve(strict=True)
    refusals = check_native_inactivity("claude")
    if refusals:
        raise ValueError("; ".join(refusals))
    result = {"claude_version": version, "executable": str(executable), "executable_sha256": _sha(executable)}
    _save(EVIDENCE / "preflight.json", result)
    return result


def run_native() -> None:
    """Perform exactly one subprocess invocation; retain failures without retry."""
    manifest = json.loads(MANIFEST.read_text())
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("Missing explicitly forwarded API key")
    marker = PROBE / "invocation-started.json"
    with marker.open("x") as stream:
        json.dump({"argv": manifest["native_argv"], "no_retry": True}, stream)
    result: dict[str, Any] = {"native_argv": manifest["native_argv"], "status": "running"}
    started = time.monotonic()
    process = subprocess.Popen(
        manifest["native_argv"],
        cwd=manifest["container_workspace"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        result["live_pid"] = process.pid
        result["live_census_refusals"] = check_native_inactivity("claude")
        result["live_census"] = _census()
        try:
            stdout, stderr = process.communicate(
                timeout=max(1, manifest["wall_seconds"] - (time.monotonic() - started))
            )
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=5)
            result["timed_out"] = True
        result.update(
            returncode=process.returncode,
            elapsed_seconds=round(time.monotonic() - started, 3),
            stdout=_redact(stdout),
            stderr=_redact(stderr),
            exited_census_refusals=check_native_inactivity("claude"),
            exited_census=_census(),
        )
        companion_probe = manifest.get("probe_kind") == "companion_metadata_only"
        files = _capture_files(include_companions=companion_probe)
        result["native_files"] = files
        if process.returncode != 0 or result.get("timed_out"):
            raise ValueError("The single native invocation failed; retry is prohibited")
        if not result["live_census_refusals"] or result["exited_census_refusals"]:
            raise ValueError("Native process census did not refuse live and admit exited state")
        if companion_probe:
            response = json.loads(stdout)
            stats = response.get("subagent_stats", {})
            if response.get("is_error") is not False or stats.get("spawned") != 1 or stats.get("completed") != 1:
                raise ValueError("Native response did not confirm exactly one completed subagent; no retry")
            if sum(bool(file.get("metadata_exported")) for file in files) != 1:
                raise ValueError("Expected one synthetic companion metadata file; no retry")
            result["status"] = "captured_for_review"
            return
        result["lifecycle"] = verify_lifecycle(files)
        result["status"] = "passed"
    except Exception as error:
        result["status"] = "failed_no_retry"
        result["error"] = _redact(str(error))
        raise
    finally:
        _save(EVIDENCE / "native-result.json", result)
        _save(
            EVIDENCE / "export-inventory.json",
            {str(path.relative_to(EVIDENCE)): _sha(path) for path in sorted(EVIDENCE.rglob("*")) if path.is_file()},
        )


def verify_lifecycle(files: list[dict[str, Any]]) -> dict[str, Any]:
    """Exercise deletion and exact purge using the captured native bytes offline."""
    native_home = Path(os.environ["CLAUDE_CONFIG_DIR"])
    workspace = PROBE / "workspace"
    project = native_home / "projects" / encode_project_path(str(workspace))
    mains = [
        Path(item["path"]) for item in files if Path(item["path"]).parent == project and item["path"].endswith(".jsonl")
    ]
    if len(mains) != 1:
        raise ValueError(f"Expected one native parent transcript, found {len(mains)}")
    main = mains[0]
    state = _state("probe-original", workspace, main.stem, main)
    inventory = plan_native_purge(state)
    _save(EVIDENCE / "native-preview.json", inventory.to_dict())
    if inventory.refusals:
        raise ValueError("; ".join(inventory.refusals))
    agents = [file for file in inventory.files if file.provenance == "subagent"]
    if len(agents) != 1:
        raise ValueError(f"Expected exactly one requested subagent, found {len(agents)}; no retry")
    selected = {file.path: _sha(Path(file.path)) for file in inventory.files}
    source = main.read_bytes()
    source_artifact = workspace / ".forge/artifacts/probe-original/transcripts/source.jsonl"
    source_artifact.parent.mkdir(parents=True)
    source_artifact.write_bytes(source)
    copies: dict[str, Any] = {}
    for mode in ("relocated", "rewind"):
        child_cwd = PROBE / mode
        child_cwd.mkdir()
        copied_id = main.stem if mode == "relocated" else str(uuid4())
        copied = native_home / "projects" / encode_project_path(str(child_cwd)) / f"{copied_id}.jsonl"
        copied.parent.mkdir(parents=True)
        # Preserve complete lines and include an identity-bearing row in the rewind prefix.
        lines = source.splitlines(keepends=True)
        identity_line = next(i for i, line in enumerate(lines) if json.loads(line).get("version"))
        data = source if mode == "relocated" else b"".join(lines[: identity_line + 1])
        copied.write_bytes(data)
        child = _state(f"probe-{mode}", child_cwd, copied_id, copied)
        child.confirmed.derivation = Derivation(
            parent_session="probe-original",
            parent_forge_root=str(workspace),
            parent_transcript=str(source_artifact),
            resume_mode="native-relocate",
            relocated_parent_session_id=copied_id if mode == "relocated" else None,
            rewind_relocated_session_id=copied_id if mode == "rewind" else None,
        )
        planned = plan_native_purge(child)
        if planned.refusals:
            raise ValueError(f"{mode}: {planned.refusals}")
        assert {file.path for file in planned.files} == {str(copied)}
        assert all(unlink_native_file(file) for file in planned.files)
        assert not copied.exists() and main.read_bytes() == source
        copies[mode] = {"preview": planned.to_dict(), "removed": True, "source_preserved": True}
    sentinel = project / "unrelated-sentinel.txt"
    sentinel.write_text("preserve this unrelated synthetic native file\n")
    sentinel_hash = _sha(sentinel)
    index = IndexStore()
    _publish(index, state, workspace)
    deletion = plan_session_deletion(index, state.name, forge_root=str(workspace), delete_worktree=False)
    assert not deletion.refusals, deletion.refusals
    apply_session_deletion(index, deletion)
    assert all(_sha(Path(path)) == digest for path, digest in selected.items())
    assert not source_artifact.exists()
    assert not SessionStore(str(workspace), state.name).exists()
    replacement = _state("probe-purge", workspace, main.stem, main)
    _publish(index, replacement, workspace)
    purge = plan_session_deletion(index, replacement.name, forge_root=str(workspace), purge=True, delete_worktree=False)
    _save(EVIDENCE / "purge-preview.json", purge.preview_dict())
    assert not purge.refusals, purge.refusals
    assert purge.native and {file.path for file in purge.native.files} == set(selected)
    apply_session_deletion(index, purge)
    assert all(not Path(path).exists() for path in selected)
    assert _sha(sentinel) == sentinel_hash
    assert not SessionStore(str(workspace), replacement.name).exists()
    return {
        "delete_preserved_native_hashes": selected,
        "purge_removed_exact_paths": list(selected),
        "unrelated_sentinel_preserved": True,
        "offline_copies": copies,
    }


def _state(name: str, root: Path, native_id: str, transcript: Path) -> SessionState:
    state = create_session_state(name, worktree_path=str(root))
    state.forge_root = str(root)
    state.confirmed.claude_project_root = str(root)
    state.confirmed.claude_session_id = native_id
    state.confirmed.transcript_path = str(transcript)
    return state


def _publish(index: IndexStore, state: SessionState, root: Path) -> None:
    store = SessionStore(str(root), state.name)
    index.create_session_txn(
        state, str(root), forge_root=str(root), write_manifest=lambda: store.create_exclusive(state)
    )


def _capture_files(*, include_companions: bool = False) -> list[dict[str, Any]]:
    home = Path(os.environ["CLAUDE_CONFIG_DIR"])
    files: list[dict[str, Any]] = []
    for path in sorted(home.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(home)
        row: dict[str, Any] = {"path": str(path), "size": path.stat().st_size, "sha256": _sha(path)}
        if relative.parts[0] == "projects" and path.suffix == ".jsonl":
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            fields = ("type", "sessionId", "agentId", "isSidechain", "cwd", "version", "parentUuid", "uuid")
            row["records"] = [{key: item[key] for key in fields if key in item} for item in rows]
            target = EVIDENCE / "synthetic-transcripts" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_redact(path.read_text()))
        elif (
            include_companions
            and len(relative.parts) == 5
            and relative.parts[0] == "projects"
            and relative.parts[3] == "subagents"
            and path.name.endswith(".meta.json")
        ):
            if path.stat().st_size > 65536:
                raise ValueError("Synthetic companion exceeds the approved 64 KiB export bound")
            metadata = json.loads(path.read_bytes())
            if not isinstance(metadata, dict):
                raise ValueError("Synthetic companion is not a JSON object")
            target = EVIDENCE / "synthetic-transcripts" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_redact(path.read_text()))
            row["metadata_exported"] = True
        files.append(row)
    return files


def _census() -> str:
    return subprocess.run(["ps", "-axo", "pid=,comm=,args="], capture_output=True, text=True, check=True).stdout


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _redact(text: str) -> str:
    secret = os.environ.get("ANTHROPIC_API_KEY")
    return text.replace(secret, "[REDACTED]") if secret else text


def _save(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


if __name__ == "__main__":
    if sys.argv[1:] == ["preflight"]:
        print(json.dumps(preflight()))
    elif sys.argv[1:] == ["run"]:
        run_native()
    else:
        raise SystemExit("Expected preflight or run")
