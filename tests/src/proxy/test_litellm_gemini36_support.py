"""Pin the packaged-cost-map expectation for gemini-3.6-flash per litellm version.

gemini-3.6-flash (released 2026-07-21) is newer than every stable LiteLLM
release at the time of this commit (latest: v1.93.0, 2026-07-19). Day-0
packaged pricing landed in litellm commit 59ebe043 (merge of #34106) and first
ships in the v1.94 line. Until the installed litellm reaches that line,
production cost tracking for this model relies on LiteLLM's default remote
cost-map refresh; the integration gate in
tests/integration/proxy/test_proxy_local_litellm_e2e.py proves that posture
end to end. This test flips to a hard presence assert once the installed
litellm reaches v1.94.0, so a future dependency bump cannot silently keep
relying on the remote map for packaged-era models.
"""

from __future__ import annotations

import importlib.metadata
import re
import sys

import pytest

# First litellm release line whose packaged cost map contains
# gemini/gemini-3.6-flash (commit 59ebe043, merged 2026-07-21).
FIRST_PACKAGED_SUPPORT = (1, 94, 0)

MODEL_KEY = "gemini/gemini-3.6-flash"


def _installed_litellm_version() -> tuple[int, int, int]:
    parts = importlib.metadata.version("litellm").split(".")[:3]
    numeric = []
    for part in parts:
        match = re.match(r"\d+", part)
        numeric.append(int(match.group()) if match else 0)
    while len(numeric) < 3:
        numeric.append(0)
    return (numeric[0], numeric[1], numeric[2])


def test_gemini_36_flash_packaged_cost_map_matches_version(monkeypatch: pytest.MonkeyPatch) -> None:
    # The env var is read at first import; nothing else in Forge imports
    # litellm in-process (it runs as a subprocess backend), so this test owns
    # the first import in the suite.
    assert "litellm" not in sys.modules, "litellm pre-imported; packaged-map check would be nondeterministic"
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "true")
    import litellm

    version = _installed_litellm_version()
    in_packaged_map = MODEL_KEY in litellm.model_cost

    if version >= FIRST_PACKAGED_SUPPORT:
        assert in_packaged_map, (
            f"litellm {version} should package {MODEL_KEY} pricing (litellm commit 59ebe043); "
            "if the packaging moved to a later release, update FIRST_PACKAGED_SUPPORT"
        )
    else:
        assert not in_packaged_map, (
            f"packaged map unexpectedly contains {MODEL_KEY} on litellm {version}; "
            "packaged support arrived earlier than recorded — update FIRST_PACKAGED_SUPPORT "
            "and drop the remote-map caveats in backends/litellm.yaml and the change log"
        )
