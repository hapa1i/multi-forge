#!/usr/bin/env python3
"""B4 no-inference reviewer: synthetic personal auth plus B3's recorded verdict/sleep controls."""

import json
import os
import runpy
import sys
from pathlib import Path


def main() -> None:
    if "auth" in sys.argv and "status" in sys.argv:
        print(
            json.dumps(
                {
                    "loggedIn": os.environ.get("B4_STUB_LOGGED_OUT") != "1",
                    "authMethod": "claude.ai",
                    "apiProvider": "firstParty",
                    "apiKeySource": "none",
                    "subscriptionType": "max",
                    "fixture": "synthetic; no credentials or inference",
                }
            )
        )
        return
    runpy.run_path(str(Path(__file__).with_name("b3-reviewer.py")), run_name="__main__")


if __name__ == "__main__":
    main()
