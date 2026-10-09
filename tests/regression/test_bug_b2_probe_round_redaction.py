"""B2: sanitize the selected round root literally, regardless of its name."""

from __future__ import annotations

import os
import subprocess

import pytest

from tests.fixtures.codex_probe import PROBES

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("selected", ["/private/tmp/recheck [a.b]+|fixture", "/private/tmp/round@review"])
def test_sanitize_uses_literal_round_root_with_regex_characters(tmp_path, selected):
    capture = tmp_path / "captures"
    capture.mkdir()
    (capture / "result.txt").write_text(f"{selected}/captures/one\n/private/tmp/forge-b2-20261009/unchanged\n")
    result = subprocess.run(
        ["/bin/bash", str(PROBES / "sanitize.sh")],
        env={**os.environ, "CODEX_HOOKS_CAPTURE_DIR": str(capture), "PROBE_ROUND_ROOT": selected},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (capture / "sanitized/result.txt").read_text() == (
        "<ROUND_ROOT>/captures/one\n/private/tmp/forge-b2-20261009/unchanged\n"
    )
