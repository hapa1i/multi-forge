#!/usr/bin/env python3
"""Validate the B4 no-inference reviewer's real capability and subscription admission paths."""

import json
import os
import time
from pathlib import Path

from forge.core.reactive.supervisor_auth import (
    preflight_subscription,
    subscription_environment,
)


def main() -> None:
    root = Path(os.environ["PROBE_ROUND_ROOT"])
    binary = preflight_subscription(
        env=subscription_environment(),
        cwd=str(root / "project"),
        deadline=time.monotonic() + 20,
    )
    result = {
        "synthetic": True,
        "no_inference": True,
        "admitted": True,
        "binary": binary,
    }
    (root / "stub-admission.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
