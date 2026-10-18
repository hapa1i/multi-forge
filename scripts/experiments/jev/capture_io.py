"""Bounded private persistence and public-catalog preflight for one diagnostic capture."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from forge.core.reactive.env import RunIdentity

STABLE_ENDPOINT_FIELDS = (
    "name",
    "model_id",
    "model_name",
    "provider_name",
    "tag",
    "service_tier",
    "quantization",
    "context_length",
    "max_prompt_tokens",
    "max_completion_tokens",
    "pricing",
    "supported_parameters",
    "status",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encoded_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n").encode()


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def private_directory(path: Path) -> None:
    """Create a private directory or verify its existing owner/type/mode."""
    try:
        path.mkdir(mode=0o700)
        fsync_directory(path.parent)
    except FileExistsError:
        pass
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise ValueError("Capture directory must be a private, owned directory without symlinks")


def write_exclusive(path: Path, value: Any) -> None:
    """An existing claim is terminal, including an incomplete claim from a crashed process."""
    data = encoded_json(value)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        fsync_directory(path.parent)
    except BaseException:
        # Never remove an uncertain claim: interruption cannot renew the proposal.
        raise


def atomic_json(path: Path, value: Any, limit: int) -> None:
    """Bound bytes before writing, then durably replace the complete artifact."""
    data = encoded_json(value)
    if len(data) > limit:
        raise ValueError("response_or_journal_overflow")
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ValueError("unsafe_persistence")
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fsync_directory(path.parent)


def persist_telemetry(
    home: Path,
    row: dict[str, Any],
    identity: RunIdentity,
    plan: dict[str, Any],
    limit: int,
) -> None:
    """Verify and sync the existing emitter's joined records instead of accepting best-effort loss."""
    from diagnostic_results import emit_telemetry

    emit_telemetry(row, plan, identity)
    for relative, key, expected in (
        ("telemetry/downstream", "downstream_event_id", row["downstream_event_id"]),
        ("usage/events", "event_id", row["event_id"]),
    ):
        directory = home / relative
        found = False
        total = 0
        for path in directory.glob("*.jsonl"):
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as stream:
                metadata = os.fstat(stream.fileno())
                total += metadata.st_size
                if not stat.S_ISREG(metadata.st_mode) or total > limit:
                    raise ValueError("response_or_journal_overflow")
                for line in stream:
                    if len(line) > 65536:
                        raise ValueError("unsafe_persistence")
                    record = json.loads(line)
                    if record.get(key) == expected:
                        found = record.get("forge_run_id", record.get("run_id")) == identity.run_id
                        if relative == "telemetry/downstream":
                            found = found and record.get("request_id") == row["request_id"]
                os.fsync(stream.fileno())
            fsync_directory(directory)
        if not found:
            raise ValueError("unsafe_persistence")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate catalog key")
        result[key] = value
    return result


def stable_endpoint(endpoint: dict[str, Any]) -> dict[str, Any]:
    result = {key: endpoint.get(key) for key in STABLE_ENDPOINT_FIELDS}
    parameters = result["supported_parameters"]
    if not isinstance(parameters, list) or any(not isinstance(item, str) for item in parameters):
        raise ValueError("Invalid catalog supported parameters")
    if len(set(parameters)) != len(parameters) or type(result["status"]) is not int or result["status"] != 0:
        raise ValueError("Selected catalog endpoint is unavailable or ambiguous")
    result["supported_parameters"] = sorted(parameters)
    return result


async def bounded_response(response: httpx.Response, limit: int) -> bytes:
    """Apply the cap to decoded bytes; no unbounded response is retained."""
    chunks = bytearray()
    async for chunk in response.aiter_bytes(chunk_size=16_384):
        if len(chunks) + len(chunk) > limit:
            raise ValueError("response_or_journal_overflow")
        chunks.extend(chunk)
    return bytes(chunks)


async def refresh_catalog(client: httpx.AsyncClient, catalog: dict[str, Any], limit: int) -> dict[str, Any]:
    """Refresh only three public GETs; compare selected stable fields and retain no unrelated rows."""
    refreshed: dict[str, Any] = {"sources": [], "arms": {}}
    documents: dict[str, Any] = {}
    for source in catalog["sources"]:
        async with client.stream("GET", source["url"], headers={"Accept": "application/json"}) as response:
            if response.status_code != 200:
                raise ValueError("Catalog preflight did not return HTTP 200")
            raw = await bounded_response(response, limit)
        document = json.loads(raw, object_pairs_hook=unique_object)
        encoded_json(document)
        documents[source["id"]] = document
        refreshed["sources"].append(
            {
                "id": source["id"],
                "url": source["url"],
                "retrieved_at": utc_now(),
                "response_bytes": len(raw),
                "response_sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    for arm, selected in catalog["arms"].items():
        projected = {}
        for field, source_id in (
            ("endpoint", selected["endpoint_source"]),
            ("zdr_endpoint", selected["zdr_source"]),
        ):
            data = documents[source_id].get("data")
            endpoints = data.get("endpoints") if isinstance(data, dict) else data
            if not isinstance(endpoints, list):
                raise ValueError("Catalog endpoint list is missing")
            matches = [
                row
                for row in endpoints
                if isinstance(row, dict)
                and row.get("model_id") == selected["requested_model"]
                and row.get("tag") == selected["provider_slug"]
            ]
            if len(matches) != 1:
                raise ValueError("Selected endpoint is absent or ambiguous in refreshed catalog")
            actual = stable_endpoint(matches[0])
            if actual != stable_endpoint(selected[field]):
                raise ValueError("Selected catalog identity, pricing, parameters or bounds changed")
            projected[field] = actual
        refreshed["arms"][arm] = projected
    return refreshed
