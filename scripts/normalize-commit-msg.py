#!/usr/bin/env python3
"""Normalize emoji and phrases in commit messages.

- Replaces emoji with configured text equivalents
- Replaces/deletes configured phrases
- If phrase is entire line, deletes the line (including newline)

Mappings loaded from config/normalize-text-mapping.json (relative to this script's repo).

Usage: normalize-commit-msg <commit-message-file>
       normalize-commit-msg --filter  (stdin → stdout)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Locate config file relative to this script
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR.parent / "config" / "normalize-text-mapping.json"


def load_maps(keep_labels: bool = False) -> tuple[dict[str, str], dict[str, str]]:
    """Load emoji and phrase maps from JSON config.

    By default, strips [bracketed] labels (e.g., 🔥 maps to empty, not [fire]).
    Set keep_labels=True to preserve them (fallback for emoji-only messages).
    """
    if not CONFIG_FILE.exists():
        print(f"normalize-commit-msg: warning: config not found: {CONFIG_FILE}", file=sys.stderr)
        return {}, {}

    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)

        raw_emoji_map = data.get("emoji", {})

        if keep_labels:
            emoji_map = raw_emoji_map
        else:
            # Strip [bracketed] labels by default (same as normalize-text)
            emoji_map = {
                src: ("" if dst.startswith("[") and dst.endswith("]") else dst) for src, dst in raw_emoji_map.items()
            }

        return emoji_map, data.get("phrases", {})

    except Exception as e:
        print(f"normalize-commit-msg: warning: failed to load config: {e}", file=sys.stderr)
        return {}, {}


def normalize(text: str, emoji_map: dict[str, str], phrase_map: dict[str, str]) -> str:
    """Replace emoji and phrases. Delete lines that become empty after replacements."""

    # Build space-fix patterns for emoji that map to empty
    # Avoids double spaces: "🔥 fix" + "🔥→''" not "  fix"
    space_fixes = {}
    for src, dst in emoji_map.items():
        if dst == "":
            space_fixes[f" {src} "] = " "  # middle: " 🔥 " → " "
            space_fixes[f"{src} "] = ""  # start:  "🔥 " → ""
            space_fixes[f" {src}"] = ""  # end:    " 🔥" → ""

    lines = text.split("\n")
    result_lines = []

    for line in lines:
        original_stripped = line.strip()

        # Preserve intentionally blank lines
        if original_stripped == "":
            result_lines.append(line)
            continue

        # Get leading whitespace to preserve indentation
        leading_ws = line[: len(line) - len(line.lstrip())]

        # Check if entire line matches a phrase
        phrase_matched = False
        for phrase, replacement in phrase_map.items():
            if original_stripped == phrase:
                phrase_matched = True
                if replacement == "":
                    line = ""  # Mark for deletion
                else:
                    line = leading_ws + replacement  # Preserve indentation
                break

        # Apply phrase replacements inline (if not already matched as whole line)
        if not phrase_matched:
            for phrase, replacement in phrase_map.items():
                if phrase in line:
                    line = line.replace(phrase, replacement)

        # Apply space-fixes first (for emoji mapping to empty)
        for src, dst in space_fixes.items():
            line = line.replace(src, dst)

        # Apply emoji replacements
        for src, dst in emoji_map.items():
            line = line.replace(src, dst)

        # Delete line only if it BECAME empty (was not originally blank)
        if line.strip() == "":
            continue

        result_lines.append(line)

    return "\n".join(result_lines)


def main():
    # Filter mode: read stdin, write stdout (for piping in scripts)
    if len(sys.argv) == 2 and sys.argv[1] == "--filter":
        msg = sys.stdin.read()
        emoji_map, phrase_map = load_maps(keep_labels=False)
        normalized = normalize(msg, emoji_map, phrase_map)

        # Edge case: if message becomes empty, keep labels
        if not normalized.strip():
            emoji_map_with_labels, _ = load_maps(keep_labels=True)
            normalized = normalize(msg, emoji_map_with_labels, phrase_map)

        print(normalized, end="")
        return 0

    if len(sys.argv) < 2:
        print("Usage: normalize-commit-msg <commit-message-file>", file=sys.stderr)
        print("       normalize-commit-msg --filter  (stdin → stdout)", file=sys.stderr)
        return 0

    msg_file = Path(sys.argv[1])

    if not msg_file.exists():
        return 0

    # Load maps from config (default: strip bracketed labels)
    emoji_map, phrase_map = load_maps(keep_labels=False)

    if not emoji_map and not phrase_map:
        return 0  # Nothing to do

    try:
        original = msg_file.read_text(encoding="utf-8")
    except Exception as e:
        print(f"normalize-commit-msg: warning: unable to read: {e}", file=sys.stderr)
        return 0

    normalized = normalize(original, emoji_map, phrase_map)

    # Edge case: if message becomes empty (e.g., was just "🔥"), keep labels
    if not normalized.strip():
        emoji_map_with_labels, _ = load_maps(keep_labels=True)
        normalized = normalize(original, emoji_map_with_labels, phrase_map)

    if normalized != original:
        try:
            msg_file.write_text(normalized, encoding="utf-8")
            print("normalize-commit-msg: normalized commit message")
        except Exception as e:
            print(f"normalize-commit-msg: warning: unable to write: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
