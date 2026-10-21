"""Print the proposed companion-metadata follow-up; never invoke a native client."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = Path(__file__).resolve()


def manifest() -> dict[str, Any]:
    """Keep the first approved workload fixed and add bounded metadata export."""
    value = json.loads(
        (ROOT / "docs/board/doing/session_delete_and_purge/evidence/native-probe-manifest.json").read_text()
    )
    value.update(
        status="proposal_only_not_authorized_or_executed",
        harness_sha256=hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
        payload_sha256=hashlib.sha256(SCRIPT.with_name("native_probe_payload.py").read_bytes()).hexdigest(),
        probe_kind="companion_metadata_only",
        container_name="forge-native-purge-companion-20261020",
        max_companion_bytes=65536,
        observations=[
            "Record exact synthetic native files, JSONL metadata, SHA-256 and runtime PID census",
            "Observe census refusal while the native process lives and admission after it exits",
            "Export parent and agent JSONL plus generated subagents/*.meta.json objects of at most 64 KiB each",
            "Verify exported evidence against its generated SHA-256 inventory before container removal",
            "Stop after capture for offline review; do not widen purge admission or invoke another model",
        ],
        export=(
            "Only synthetic transcripts and generated companion JSON, redacted metadata, arguments, "
            "image/binary identity and assertions. Never export auth/config files outside projects."
        ),
        cleanup=(
            "Remove the disposable /probe/home after evidence capture, stop only the exact named container, "
            "and remove it only after successful execution and verified evidence export. "
            "On failure retain the stopped container's /probe/evidence for diagnosis; no automatic inference retry."
        ),
    )
    return value


if __name__ == "__main__":
    print(json.dumps(manifest(), indent=2))
