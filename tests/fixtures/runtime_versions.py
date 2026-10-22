"""Select integration runtimes from the QA pins or explicit compatibility overrides."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path

RUNTIME_MATRIX = Path(__file__).resolve().parents[2] / "src/skills/qa/resources/runtime-matrix.json"
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?")


def integration_runtime_versions(
    environment: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Use reviewed defaults; require explicit environment overrides for other runtimes."""
    environment = os.environ if environment is None else environment
    pins = json.loads(RUNTIME_MATRIX.read_text(encoding="utf-8"))["tracks"]["pinned"]
    versions = []
    for runtime, name in (("claude", "CLAUDE_VERSION"), ("codex", "CODEX_VERSION")):
        pinned = pins[runtime]["version"]
        if not isinstance(pinned, str) or _VERSION.fullmatch(pinned) is None:
            raise ValueError(f"The pinned QA track must name an exact {runtime} version.")
        selected = environment.get(name, pinned)
        if selected != "latest" and _VERSION.fullmatch(selected) is None:
            raise ValueError(f"{name} must be an exact version or the explicit compatibility override 'latest'.")
        versions.append(selected)
    return versions[0], versions[1]


if __name__ == "__main__":
    print("\t".join(integration_runtime_versions()))
