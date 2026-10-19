"""Read retained capture manifests without trusting publication reference paths or identities."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

MAX_MANIFEST_BYTES = 2_000_000


def retained_manifest(journal: Any, journal_path: Path, evidence_root: Path) -> dict[str, Any]:
    """Accept an embedded manifest or the bounded diagnostic publication's verified local reference."""
    if not isinstance(journal, dict):
        raise ValueError("Expected a capture journal object")
    embedded = journal.get("manifest")
    reference = journal.get("manifest_reference")
    if isinstance(embedded, dict) and reference is None:
        return embedded
    if embedded is not None or not isinstance(reference, dict) or set(reference) != {"path", "manifest_sha256"}:
        raise ValueError("Expected one embedded manifest or a verified manifest reference")
    relative, expected_digest = reference["path"], reference["manifest_sha256"]
    if (
        not isinstance(relative, str)
        or not relative
        or Path(relative).is_absolute()
        or not isinstance(expected_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
    ):
        raise ValueError("Invalid retained manifest reference")
    root = evidence_root.absolute()
    target = journal_path.parent.absolute()
    if root.resolve() != root or target.resolve() != target or not target.is_relative_to(root):
        raise ValueError("Retained manifest reference leaves the evidence root")
    for component in Path(relative).parts:
        target = target.parent if component == ".." else target / component
        if not target.is_relative_to(root):
            raise ValueError("Retained manifest reference leaves the evidence root")
        if target.is_symlink():
            raise ValueError("Retained manifest reference contains a symlink")
    descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_MANIFEST_BYTES:
            raise ValueError("Retained manifest reference must be a bounded regular file")
        raw = stream.read(MAX_MANIFEST_BYTES + 1)
        after = os.fstat(stream.fileno())

    def identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns

    if len(raw) > MAX_MANIFEST_BYTES or identity(before) != identity(after):
        raise ValueError("Retained manifest changed or exceeded its byte bound")
    try:
        manifest = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(manifest, dict) or manifest.get("proposal_kind") != "bounded_diagnostic_comparison":
            raise ValueError("Unsupported referenced capture manifest")
        content = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        encoded = json.dumps(content, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("Malformed retained manifest") from exc
    if manifest.get("manifest_sha256") != expected_digest or hashlib.sha256(encoded).hexdigest() != expected_digest:
        raise ValueError("Retained manifest reference digest does not match its contents")
    return manifest


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate retained manifest key")
        result[key] = value
    return result
