#!/usr/bin/env python3
"""Regenerate the qa/ copy of walkthrough-state.py from the canonical walkthrough/ copy.

src/skills/walkthrough/scripts/walkthrough-state.py is the canonical copy.
src/skills/qa/scripts/walkthrough-state.py is generated from it (the two skills
can't share a file because each resolves scripts via ${CLAUDE_SKILL_DIR}).

Default: regenerate the qa copy if it differs, then exit 0 (safe to run anytime).
--check: regenerate if it differs, but exit 1 when a change was made, so the
         sync-walkthrough-state pre-commit hook fails and you re-stage the file.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CANONICAL = REPO_ROOT / "src/skills/walkthrough/scripts/walkthrough-state.py"
GENERATED = REPO_ROOT / "src/skills/qa/scripts/walkthrough-state.py"


def _in_sync() -> bool:
    if not GENERATED.exists():
        return False
    if GENERATED.read_bytes() != CANONICAL.read_bytes():
        return False
    return (GENERATED.stat().st_mode & 0o777) == (CANONICAL.stat().st_mode & 0o777)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync the qa copy of walkthrough-state.py.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the qa copy had to be regenerated (for pre-commit)",
    )
    args = parser.parse_args()

    if _in_sync():
        return 0

    shutil.copyfile(CANONICAL, GENERATED)
    shutil.copymode(CANONICAL, GENERATED)
    rel = GENERATED.relative_to(REPO_ROOT)
    print(f"Regenerated {rel} from {CANONICAL.relative_to(REPO_ROOT)}.")
    if args.check:
        print(f"Re-stage it: git add {rel}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
