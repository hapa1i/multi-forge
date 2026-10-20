"""Exact native-file inventories for session purge.

Discovery is read-only. Recorded paths are candidates, never deletion authority:
content, layout, containment and the preview fingerprint must agree at unlink.
The process census is deliberately conservative, including unmanaged clients.
It observes inactivity; external runtimes do not participate in Forge's locks.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from forge.core.runtime.codex_review_source import directory_fd
from forge.core.runtime.codex_rollouts import codex_home, parse_rollout_filename
from forge.session.claude.paths import (
    encode_project_path,
    get_claude_home,
    resolve_claude_project_root,
)
from forge.session.models import SessionState, session_runtime

NativeRuntime = Literal["claude", "codex"]
NativeProvenance = Literal["original", "rollover", "relocated", "rewind", "subagent", "subagent-metadata", "rollout"]
MAX_NATIVE_BYTES = 128 * 1024 * 1024
MAX_STORE_FILES = 10000
MAX_HEADER_BYTES = 1024 * 1024
CLAUDE_VERSIONS = frozenset({"2.1.245"})
CODEX_VERSIONS = frozenset({"0.162.1"})
OUTSIDE_SCOPE = (
    "Provider-side request copies",
    "Project memory documents and Git history",
    "Global Forge telemetry",
    "Claude history.jsonl, file-history, and other uncharacterized runtime state",
    "Codex indexes, archived stores, and other uncharacterized runtime state",
    "Native copies outside the recorded runtime store",
)


class NativePurgeError(ValueError):
    """The native file or inactivity evidence does not authorize removal."""


@dataclass(frozen=True)
class NativeFingerprint:
    device: int
    inode: int
    size: int
    mtime_ns: int
    sha256: str
    parent_device: int
    parent_inode: int


@dataclass(frozen=True)
class NativePurgeFile:
    path: str
    store_root: str
    runtime: NativeRuntime
    provenance: NativeProvenance
    native_id: str
    expected_cwd: str
    created_outside_forge: bool
    fingerprint: NativeFingerprint | None
    source_path: str | None = None
    source_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the exact preview identity for a durable retry inventory."""
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> NativePurgeFile:
        """Reject malformed retry inventories instead of inferring ownership."""
        fields = set(cls.__dataclass_fields__)
        if not isinstance(value, dict) or set(value) != fields:
            raise NativePurgeError("Malformed native purge file inventory")
        text_fields = ("path", "store_root", "native_id", "expected_cwd")
        if any(not isinstance(value[key], str) or not value[key] for key in text_fields):
            raise NativePurgeError("Malformed native purge path or identity")
        if value["runtime"] not in ("claude", "codex") or value["provenance"] not in (
            "original",
            "rollover",
            "relocated",
            "rewind",
            "subagent",
            "subagent-metadata",
            "rollout",
        ):
            raise NativePurgeError("Unknown native purge provenance")
        if type(value["created_outside_forge"]) is not bool:
            raise NativePurgeError("Malformed native adoption identity")
        for key in ("source_path", "source_sha256"):
            if value[key] is not None and not isinstance(value[key], str):
                raise NativePurgeError("Malformed native source identity")
        raw = value["fingerprint"]
        fingerprint = None
        if raw is not None:
            if not isinstance(raw, dict) or set(raw) != set(NativeFingerprint.__dataclass_fields__):
                raise NativePurgeError("Malformed native file fingerprint")
            if any(type(raw[key]) is not int or raw[key] < 0 for key in raw if key != "sha256"):
                raise NativePurgeError("Malformed native file stat identity")
            if not isinstance(raw["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", raw["sha256"]):
                raise NativePurgeError("Malformed native file digest")
            fingerprint = NativeFingerprint(**raw)
        answer = cls(**{**value, "fingerprint": fingerprint})
        _validate_candidate(answer)
        return answer


@dataclass(frozen=True)
class NativePurgePlan:
    files: tuple[NativePurgeFile, ...] = ()
    refusals: tuple[str, ...] = ()
    outside_scope: tuple[str, ...] = OUTSIDE_SCOPE

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible preview and retry inventory."""
        return {
            "files": [file.to_dict() for file in self.files],
            "refusals": list(self.refusals),
            "outside_scope": list(self.outside_scope),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> NativePurgePlan:
        """Restore a validated inventory without rediscovering new targets."""
        if not isinstance(value, dict) or set(value) != {
            "files",
            "refusals",
            "outside_scope",
        }:
            raise NativePurgeError("Malformed native purge plan")
        if not isinstance(value["files"], list):
            raise NativePurgeError("Malformed native purge file list")
        for key in ("refusals", "outside_scope"):
            if not isinstance(value[key], list) or any(not isinstance(item, str) for item in value[key]):
                raise NativePurgeError("Malformed native purge diagnostic list")
        files = tuple(NativePurgeFile.from_dict(item) for item in value["files"])
        if len({file.path for file in files}) != len(files):
            raise NativePurgeError("Duplicate native purge path")
        return cls(files, tuple(value["refusals"]), tuple(value["outside_scope"]))


def plan_native_purge(state: SessionState) -> NativePurgePlan:
    """Inventory only the session's recorded native identities and exact paths."""
    runtime: NativeRuntime = "codex" if session_runtime(state) == "codex" else "claude"
    files: list[NativePurgeFile] = []
    refusals = list(check_native_inactivity(runtime))
    try:
        candidates = _codex_candidates(state) if runtime == "codex" else _claude_candidates(state)
        for candidate in candidates:
            try:
                captured = _capture(candidate)
                if candidate.fingerprint is not None and captured.fingerprint != candidate.fingerprint:
                    raise NativePurgeError("Native companion changed while establishing its ownership")
                files.append(captured)
            except (OSError, ValueError) as exc:
                refusals.append(f"{candidate.path}: {exc}")
        if runtime == "codex" and candidates:
            refusals.extend(_codex_dependents(Path(candidates[0].store_root), candidates[0].native_id))
    except (OSError, ValueError) as exc:
        refusals.append(str(exc))
    return NativePurgePlan(tuple(files), tuple(dict.fromkeys(refusals)))


def validate_native_purge_scope(plan: NativePurgePlan, state: SessionState) -> None:
    """Bind restored paths to the saved session and the currently selected native home."""
    candidates = _codex_candidates(state) if session_runtime(state) == "codex" else _claude_candidates(state)
    by_path = {candidate.path: replace(candidate, fingerprint=None) for candidate in candidates}
    for file in plan.files:
        expected = by_path.get(file.path)
        if expected is None and file.provenance in {"subagent", "subagent-metadata"}:
            # Removed agents no longer appear in discovery on a partial retry.
            parent = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.runtime == "claude"
                    and candidate.native_id == file.native_id
                    and candidate.provenance not in {"subagent", "subagent-metadata"}
                ),
                None,
            )
            if parent is not None:
                expected = replace(
                    parent,
                    path=file.path,
                    provenance=file.provenance,
                    source_path=None,
                    source_sha256=None,
                )
        if expected is None or replace(file, fingerprint=None) != expected:
            raise NativePurgeError(f"Native inventory path is not owned by its saved session: {file.path}")
        _validate_candidate(file)


def check_native_inactivity(runtime: NativeRuntime) -> tuple[str, ...]:
    """Refuse any observed client of the same runtime, including outside Forge.

    A runtime may close its transcript while waiting for input, so an empty lsof
    result is insufficient. A failed or unparseable census is unknown activity.
    """
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,comm=,args="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode or not result.stdout.strip():
            return (f"Cannot establish native {runtime} inactivity: process census failed",)
        pids: list[int] = []
        for line in result.stdout.splitlines():
            fields = line.strip().split(None, 2)
            if len(fields) != 3 or not fields[0].isdigit():
                return (f"Cannot establish native {runtime} inactivity: incomplete process census",)
            pid = int(fields[0])
            if pid == os.getpid():
                continue
            executable = Path(fields[1]).name.lower()
            args = fields[2]
            try:
                argv = shlex.split(args)
            except ValueError:
                argv = []
            first = Path(argv[0]).name.lower() if argv else executable
            native = runtime in (executable, first)
            if runtime == "codex":
                native = native or executable in {"codex-app", "codex.app"} or first == "codex-app"
            elif executable.startswith("node") or first.startswith("node"):
                native = any("@anthropic-ai/claude-code/" in arg or arg.endswith("/claude/cli.js") for arg in argv[:3])
            if native:
                pids.append(pid)
        if pids:
            return (
                f"Native {runtime} process(es) may write conversations: PIDs {', '.join(map(str, sorted(pids)))}; "
                "exit those clients before purging",
            )
        return ()
    except (OSError, UnicodeError, subprocess.SubprocessError):
        return (f"Cannot establish native {runtime} inactivity: process census unavailable",)


def revalidate_native_file(file: NativePurgeFile, *, allow_missing: bool = False) -> None:
    """Reject substitutions or writes since preview, including parent replacement."""
    _validate_candidate(file)
    current = _capture(file)
    if allow_missing and current.fingerprint is None:
        return
    if current.fingerprint != file.fingerprint:
        raise NativePurgeError(f"Native file changed since preview: {file.path}; preview again")


def unlink_native_file(file: NativePurgeFile) -> bool:
    """Remove one verified leaf; return false when an earlier attempt removed it.

    Callers must retain the durable inventory and their session/dependency locks.
    This function never follows symlinks or recursively removes native directories.
    """
    refusals = check_native_inactivity(file.runtime)
    if refusals:
        raise NativePurgeError("; ".join(refusals))
    if file.runtime == "codex":
        dependents = _codex_dependents(Path(file.store_root), file.native_id)
        if dependents:
            raise NativePurgeError("; ".join(dependents))
    revalidate_native_file(file, allow_missing=True)
    path = Path(file.path)
    refusals = check_native_inactivity(file.runtime)
    if refusals:
        raise NativePurgeError("; ".join(refusals))
    try:
        with directory_fd(path.parent) as parent:
            try:
                current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                return False
            expected = file.fingerprint
            parent_stat = os.fstat(parent)
            if (
                expected is None
                or not stat.S_ISREG(current.st_mode)
                or (
                    current.st_dev,
                    current.st_ino,
                    current.st_size,
                    current.st_mtime_ns,
                    current.st_nlink,
                    parent_stat.st_dev,
                    parent_stat.st_ino,
                )
                != (
                    expected.device,
                    expected.inode,
                    expected.size,
                    expected.mtime_ns,
                    1,
                    expected.parent_device,
                    expected.parent_inode,
                )
            ):
                raise NativePurgeError(f"Native file replaced immediately before unlink: {path}")
            os.unlink(path.name, dir_fd=parent)
            return True
    except FileNotFoundError:
        return False


def _absolute(path: str | Path) -> Path:
    result = Path(path).expanduser()
    if not result.is_absolute() or ".." in result.parts:
        raise NativePurgeError("Native inventory requires absolute paths without parent traversal")
    return result


def _uuid(value: str) -> str:
    if str(UUID(value)) != value:
        raise NativePurgeError("Native identity must be a canonical UUID")
    return value


def _validate_candidate(file: NativePurgeFile) -> None:
    path, store = _absolute(file.path), _absolute(file.store_root)
    relative = path.relative_to(store)
    _uuid(file.native_id)
    _absolute(file.expected_cwd)
    if file.runtime == "codex":
        parsed = parse_rollout_filename(path)
        if (
            file.provenance != "rollout"
            or len(relative.parts) != 5
            or relative.parts[0] != "sessions"
            or not all(
                re.fullmatch(pattern, part)
                for pattern, part in zip((r"\d{4}", r"\d{2}", r"\d{2}"), relative.parts[1:4], strict=True)
            )
            or parsed is None
            or parsed.thread_id != file.native_id
        ):
            raise NativePurgeError("Recorded Codex path is outside the supported rollout layout")
    else:
        if len(relative.parts) < 3 or relative.parts[0] != "projects":
            raise NativePurgeError("Recorded Claude path is outside the project transcript store")
        if relative.parts[1] != encode_project_path(file.expected_cwd):
            raise NativePurgeError("Claude project namespace does not match the launch directory")
        if file.provenance in {"subagent", "subagent-metadata"}:
            nested = len(relative.parts) == 5 and relative.parts[2:4] == (
                file.native_id,
                "subagents",
            )
            legacy = len(relative.parts) == 3
            pattern = (
                r"agent-[A-Za-z0-9_-]+\.meta\.json"
                if file.provenance == "subagent-metadata"
                else r"agent-[A-Za-z0-9_-]+\.jsonl"
            )
            if not (nested or (legacy and file.provenance == "subagent")) or not re.fullmatch(pattern, path.name):
                raise NativePurgeError("Unsupported Claude subagent path")
        elif len(relative.parts) != 3 or path.name != f"{file.native_id}.jsonl":
            raise NativePurgeError("Claude filename does not match the recorded identity")
        if file.provenance in ("relocated", "rewind") and not file.source_path:
            raise NativePurgeError("Relocated/rewind transcript lacks recorded source evidence")


def _read(
    path: Path, *, limit: int = MAX_NATIVE_BYTES, header_only: bool = False, jsonl: bool = True
) -> tuple[bytes, NativeFingerprint]:
    with directory_fd(path.parent) as parent:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise NativePurgeError("Native input must be a regular file without hard links")
            data = stream.readline(limit + 1) if header_only else stream.read(limit + 1)
            after = os.fstat(fd)
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ino,
            ):
                raise NativePurgeError("Native file changed while inspecting it")
            parent_stat = os.fstat(parent)
    if len(data) > limit or not data or (jsonl and not data.endswith(b"\n")):
        raise NativePurgeError("Native file exceeds the read bound or has an incomplete JSONL boundary")
    return data, NativeFingerprint(
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        hashlib.sha256(data).hexdigest(),
        parent_stat.st_dev,
        parent_stat.st_ino,
    )


def _rows(data: bytes) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in data.splitlines()]
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise NativePurgeError("Native transcript contains an unsupported record")
    return rows


def _capture(file: NativePurgeFile) -> NativePurgeFile:
    _validate_candidate(file)
    try:
        metadata = file.provenance == "subagent-metadata"
        data, fingerprint = _read(Path(file.path), limit=65536 if metadata else MAX_NATIVE_BYTES, jsonl=not metadata)
    except FileNotFoundError:
        return NativePurgeFile(**{**file.__dict__, "fingerprint": None})
    if metadata:
        _metadata_object(data)
        return replace(file, fingerprint=fingerprint)
    rows = _rows(data)
    if file.runtime == "codex":
        _codex_header(rows[0], file.native_id, expected_cwd=file.expected_cwd)
        if sum(row.get("type") == "session_meta" for row in rows) != 1:
            raise NativePurgeError("Codex transcript has ambiguous session metadata")
    else:
        _verify_claude(file, data, rows)
    return NativePurgeFile(**{**file.__dict__, "fingerprint": fingerprint})


def _verify_claude(file: NativePurgeFile, data: bytes, rows: list[dict[str, Any]]) -> None:
    identified = [row for row in rows if "sessionId" in row]
    if not identified:
        raise NativePurgeError("Claude transcript has no session identity")
    if file.provenance in ("relocated", "rewind"):
        if not file.source_path:
            raise NativePurgeError("Missing Claude source prefix")
        source, _ = _read(_absolute(file.source_path))
        if hashlib.sha256(source).hexdigest() != file.source_sha256:
            raise NativePurgeError("Recorded Claude source evidence changed")
        matches = data == source if file.provenance == "relocated" else source.startswith(data)
        if not matches:
            raise NativePurgeError("Claude relocated/rewind copy does not match its recorded source bytes")
        source_rows = _rows(source)
        expected_ids = {row.get("sessionId") for row in source_rows if "sessionId" in row}
        if not expected_ids or any(not isinstance(value, str) for value in expected_ids):
            raise NativePurgeError("Claude source prefix has no valid session identity")
        for value in expected_ids:
            if not isinstance(value, str):
                raise NativePurgeError("Claude source prefix has an invalid session identity")
            _uuid(value)
        if file.provenance == "relocated" and file.native_id not in expected_ids:
            raise NativePurgeError("Relocated filename identity is absent from the source")
        if file.provenance == "rewind" and file.native_id in expected_ids:
            raise NativePurgeError("Rewind filename must be distinct from source identities")
    else:
        if any(row.get("sessionId") != file.native_id for row in identified):
            raise NativePurgeError("Claude transcript contains a different session identity")
        cwds = {row.get("cwd") for row in identified if row.get("cwd") is not None}
        if not cwds or any(
            not isinstance(cwd, str) or Path(cwd).resolve() != Path(file.expected_cwd).resolve() for cwd in cwds
        ):
            raise NativePurgeError("Claude transcript CWD does not match the recorded launch directory")
    versions = {row.get("version") for row in identified if row.get("version") is not None}
    if not versions or not versions.issubset(CLAUDE_VERSIONS):
        raise NativePurgeError("Claude transcript version has no admitted purge layout")
    if file.provenance == "subagent":
        agent_id = Path(file.path).stem.removeprefix("agent-")
        if any(row.get("isSidechain") is not True or row.get("agentId") != agent_id for row in identified):
            raise NativePurgeError("Claude subagent metadata does not match its exact filename")


def _source_evidence(state: SessionState) -> tuple[str | None, str | None]:
    derivation = state.confirmed.derivation
    if not derivation or not derivation.parent_transcript or not derivation.parent_forge_root:
        return None, None
    root = _absolute(derivation.parent_forge_root)
    path = Path(derivation.parent_transcript)
    path = path if path.is_absolute() else root / path
    expected = root / ".forge" / "artifacts" / derivation.parent_session / "transcripts"
    _absolute(path).relative_to(expected)
    data, _ = _read(path)
    return str(path), hashlib.sha256(data).hexdigest()


def _claude_candidates(state: SessionState) -> list[NativePurgeFile]:
    cwd = state.confirmed.claude_project_root or resolve_claude_project_root(state)
    _absolute(cwd)
    # Native Claude honors CONFIG_DIR; CLAUDE_HOME remains Forge's isolated-test convention.
    home = _absolute(os.environ.get("CLAUDE_CONFIG_DIR") or get_claude_home())
    project = home / "projects" / encode_project_path(cwd)
    adoption = state.confirmed.adoption
    adopted_path = adoption.source_path if adoption and adoption.source_runtime == "claude_code" else None
    specs: dict[str, NativeProvenance] = {}
    if state.confirmed.claude_session_id:
        specs[_uuid(state.confirmed.claude_session_id)] = "original"
    artifacts = state.confirmed.artifacts.get("transcripts", [])
    if not isinstance(artifacts, list) or any(not isinstance(item, dict) for item in artifacts):
        raise NativePurgeError("Malformed Claude transcript artifact inventory")
    for artifact in artifacts:
        value = artifact.get("session_id")
        if value is not None:
            if not isinstance(value, str):
                raise NativePurgeError("Malformed Claude rollover identity")
            specs.setdefault(_uuid(value), "rollover")
    if adopted_path:
        adopted = _absolute(adopted_path)
        if adopted.parent != project:
            raise NativePurgeError("Adopted Claude source is outside its recorded launch namespace")
        specs.setdefault(_uuid(adopted.stem), "original")
    derivation = state.confirmed.derivation
    source_path = source_digest = None
    if derivation and (derivation.relocated_parent_session_id or derivation.rewind_relocated_session_id):
        source_path, source_digest = _source_evidence(state)
        if derivation.relocated_parent_session_id:
            specs[_uuid(derivation.relocated_parent_session_id)] = "relocated"
        if derivation.rewind_relocated_session_id:
            specs[_uuid(derivation.rewind_relocated_session_id)] = "rewind"
    result: list[NativePurgeFile] = []
    for native_id, provenance in specs.items():
        path = project / f"{native_id}.jsonl"
        created_outside = bool(adopted_path and path == Path(adopted_path))
        candidate = NativePurgeFile(
            str(path),
            str(home),
            "claude",
            provenance,
            native_id,
            cwd,
            created_outside,
            None,
            source_path if provenance in ("relocated", "rewind") else None,
            source_digest if provenance in ("relocated", "rewind") else None,
        )
        result.append(candidate)
        for agent in _agent_paths(project, native_id):
            agent_candidate = NativePurgeFile(
                str(agent),
                str(home),
                "claude",
                "subagent",
                native_id,
                cwd,
                created_outside,
                None,
            )
            result.append(agent_candidate)
            metadata_path = agent.with_suffix(".meta.json")
            if metadata_path.exists() or metadata_path.is_symlink():
                if agent.parent != project / native_id / "subagents":
                    raise NativePurgeError("Uncharacterized legacy Claude agent metadata")
                result.append(_metadata_candidate(candidate, agent_candidate, metadata_path))
    recorded = state.confirmed.transcript_path
    if recorded and str(_absolute(recorded)) not in {file.path for file in result}:
        raise NativePurgeError(
            "Recorded Claude transcript path disagrees with its native identity and launch directory"
        )
    return sorted(result, key=lambda file: {"subagent-metadata": 0, "subagent": 1}.get(file.provenance, 2))


def _entries(path: Path) -> list[str]:
    try:
        with directory_fd(path) as descriptor:
            names = os.listdir(descriptor)
    except FileNotFoundError:
        return []
    if len(names) > MAX_STORE_FILES:
        raise NativePurgeError(f"Native directory exceeds the bounded inventory: {path}")
    return sorted(names)


def _agent_paths(project: Path, native_id: str) -> list[Path]:
    result: list[Path] = []
    nested = project / native_id / "subagents"
    names = _entries(nested)
    for name in names:
        if re.fullmatch(r"agent-[A-Za-z0-9_-]+\.meta\.json", name):
            if name.removesuffix(".meta.json") + ".jsonl" not in names:
                raise NativePurgeError(f"Claude subagent metadata has no corresponding transcript: {nested / name}")
            continue
        if not re.fullmatch(r"agent-[A-Za-z0-9_-]+\.jsonl", name):
            raise NativePurgeError(f"Uncharacterized Claude subagent companion: {nested / name}")
        result.append(nested / name)
    for name in _entries(project):
        if name.startswith("agent-") and name.endswith(".jsonl"):
            path = project / name
            data, _ = _read(path)
            rows = _rows(data)
            if any(row.get("sessionId") == native_id for row in rows):
                result.append(path)
    return result


def _metadata_object(data: bytes) -> dict[str, Any]:
    """Admit only the bounded four-field object observed on Claude 2.1.245."""
    value = json.loads(data)
    if (
        not isinstance(value, dict)
        or set(value) != {"agentType", "description", "toolUseId", "spawnDepth"}
        or any(not isinstance(value[key], str) or not value[key] for key in ("agentType", "description", "toolUseId"))
        or not re.fullmatch(r"toolu_[A-Za-z0-9]+", value["toolUseId"])
        or type(value["spawnDepth"]) is not int
        or value["spawnDepth"] != 1
    ):
        raise NativePurgeError("Uncharacterized Claude subagent metadata schema")
    return value


def _metadata_candidate(parent: NativePurgeFile, agent: NativePurgeFile, path: Path) -> NativePurgeFile:
    """Bind metadata to the exact validated agent and its parent's Agent tool request."""
    if _capture(parent).fingerprint is None or _capture(agent).fingerprint is None:
        raise NativePurgeError("Claude subagent metadata requires its parent and agent transcripts")
    data, fingerprint = _read(path, limit=65536, jsonl=False)
    metadata = _metadata_object(data)
    parent_data, _ = _read(Path(parent.path))
    matching: list[dict[str, Any]] = []
    for row in _rows(parent_data):
        message = row.get("message")
        blocks = message.get("content") if isinstance(message, dict) else None
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id") == metadata["toolUseId"]:
                matching.append(block)
    if len(matching) != 1:
        raise NativePurgeError("Claude subagent metadata tool use is absent or ambiguous in the parent")
    request = matching[0]
    inputs = request.get("input")
    if (
        request.get("name") != "Agent"
        or not isinstance(inputs, dict)
        or inputs.get("subagent_type") != metadata["agentType"]
        or inputs.get("description") != metadata["description"]
    ):
        raise NativePurgeError("Claude subagent metadata differs from its parent Agent request")
    return replace(agent, path=str(path), provenance="subagent-metadata", fingerprint=fingerprint)


def _codex_candidates(state: SessionState) -> list[NativePurgeFile]:
    facts = state.confirmed.codex
    if not facts:
        return []
    if not facts.thread_id and not facts.rollout_path:
        return []
    if not facts.thread_id or not facts.rollout_path:
        raise NativePurgeError("Codex purge requires both confirmed thread identity and exact rollout path")
    home = _absolute(codex_home())
    path = _absolute(facts.rollout_path)
    cwd = resolve_claude_project_root(state)
    adoption = state.confirmed.adoption
    adopted = bool(adoption and adoption.source_runtime == "codex")
    if adopted and adoption and adoption.source_path != str(path):
        raise NativePurgeError("Adopted Codex source differs from the recorded rollout")
    return [
        NativePurgeFile(
            str(path),
            str(home),
            "codex",
            "rollout",
            _uuid(facts.thread_id),
            cwd,
            adopted,
            None,
        )
    ]


def _codex_header(row: dict[str, Any], native_id: str, *, expected_cwd: str | None = None) -> dict[str, Any]:
    meta = row.get("payload")
    if row.get("type") != "session_meta" or not isinstance(meta, dict) or meta.get("id") != native_id:
        raise NativePurgeError("Codex rollout header does not match its exact thread ID")
    version = meta.get("cli_version")
    if version not in CODEX_VERSIONS:
        raise NativePurgeError("Codex rollout version has no admitted purge layout")
    if "session_id" in meta and meta["session_id"] != native_id:
        raise NativePurgeError("Codex rollout has conflicting session identities")
    cwd = meta.get("cwd")
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        raise NativePurgeError("Codex rollout has no absolute launch directory")
    if expected_cwd and Path(cwd).resolve() != Path(expected_cwd).resolve():
        raise NativePurgeError("Codex rollout CWD does not match the recorded session directory")
    parent, base = meta.get("forked_from_id"), meta.get("history_base")
    if version == "0.162.1":
        if meta.get("session_id") != native_id or meta.get("history_mode") != "paginated":
            raise NativePurgeError("Uncharacterized Codex 0.162.1 history metadata")
        if parent is not None or base is not None:
            if (
                not isinstance(base, dict)
                or set(base) != {"thread_id", "end_ordinal_exclusive", "end_byte_offset"}
                or base.get("thread_id") != parent
                or not isinstance(parent, str)
                or any(
                    type(base.get(key)) is not int or base[key] <= 0
                    for key in ("end_ordinal_exclusive", "end_byte_offset")
                )
            ):
                raise NativePurgeError("Unverifiable Codex native ancestry")
            _uuid(parent)
    elif parent is not None or base is not None:
        raise NativePurgeError("Uncharacterized Codex native fork metadata")
    return meta


def _codex_dependents(home: Path, native_id: str) -> list[str]:
    """Inspect bounded supported headers; unreadable ancestry cannot prove safety."""
    if _entries(home / "archived_sessions"):
        raise NativePurgeError("Codex archived-session ancestry is uncharacterized; cannot exclude native dependents")
    base = home / "sessions"
    seen: dict[str, Path] = {}
    refusals: list[str] = []
    count = 0
    for year in _entries(base):
        if not re.fullmatch(r"\d{4}", year):
            raise NativePurgeError(f"Unsupported Codex store entry: {base / year}")
        for month in _entries(base / year):
            if not re.fullmatch(r"\d{2}", month):
                raise NativePurgeError("Unsupported Codex month directory")
            for day in _entries(base / year / month):
                if not re.fullmatch(r"\d{2}", day):
                    raise NativePurgeError("Unsupported Codex day directory")
                directory = base / year / month / day
                for name in _entries(directory):
                    count += 1
                    if count > MAX_STORE_FILES:
                        raise NativePurgeError("Codex ancestry inventory exceeds the file bound")
                    path = directory / name
                    parsed = parse_rollout_filename(path)
                    if parsed is None:
                        raise NativePurgeError(f"Unsupported Codex store file: {path}")
                    _uuid(parsed.thread_id)
                    data, _ = _read(path, limit=MAX_HEADER_BYTES, header_only=True)
                    meta = _codex_header(_rows(data)[0], parsed.thread_id)
                    if parsed.thread_id in seen:
                        raise NativePurgeError(f"Ambiguous Codex thread copies: {parsed.thread_id}")
                    seen[parsed.thread_id] = path
                    if meta.get("forked_from_id") == native_id:
                        refusals.append(f"Native Codex descendant {parsed.thread_id} depends on this thread: {path}")
    return refusals
