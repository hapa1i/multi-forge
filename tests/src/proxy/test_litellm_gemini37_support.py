"""Pin packaged LiteLLM support for Gemini 3.7 Flash.

Google released gemini-3.7-flash on 2026-08-13. LiteLLM 1.98.0 is the first
published release whose bundled cost map contains the model; older releases
can only learn it from LiteLLM's remote cost-map refresh. Forge requires the
packaged entry so routing, capabilities, and cost accounting do not depend on
that mutable network fetch.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
import subprocess
import sys

# First LiteLLM release whose packaged cost map contains the model.
FIRST_PACKAGED_SUPPORT = (1, 98, 0)

MODEL_KEY = "gemini/gemini-3.7-flash"


def _installed_litellm_version() -> tuple[int, int, int]:
    parts = importlib.metadata.version("litellm").split(".")[:3]
    numeric = []
    for part in parts:
        match = re.match(r"\d+", part)
        numeric.append(int(match.group()) if match else 0)
    while len(numeric) < 3:
        numeric.append(0)
    return (numeric[0], numeric[1], numeric[2])


def _model_in_packaged_cost_map() -> bool:
    # Subprocess so this probe owns litellm's first import: the env var is
    # read at import time, and in-process the module may already be loaded
    # (e.g. proxy_orchestrator._check_proxy_dependencies imports litellm).
    result = subprocess.run(
        [sys.executable, "-c", f"import litellm, json; print(json.dumps({MODEL_KEY!r} in litellm.model_cost))"],
        env={**os.environ, "LITELLM_LOCAL_MODEL_COST_MAP": "true"},
        capture_output=True,
        text=True,
        check=True,
    )
    return bool(json.loads(result.stdout.strip().splitlines()[-1]))


def test_gemini_37_flash_has_packaged_cost_map_support() -> None:
    version = _installed_litellm_version()
    in_packaged_map = _model_in_packaged_cost_map()

    assert (
        version >= FIRST_PACKAGED_SUPPORT
    ), f"litellm {version} predates packaged {MODEL_KEY} support; require at least {FIRST_PACKAGED_SUPPORT}"
    assert in_packaged_map, f"litellm {version} should package {MODEL_KEY} pricing and capability metadata"
