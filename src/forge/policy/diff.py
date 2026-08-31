"""Shared parsing for policy checks over unified diffs."""

from __future__ import annotations

import re

from forge.policy.deterministic.base import tests_first_sort_key

_DIFF_GIT_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)
_DIFF_PLUS_HEADER_RE = re.compile(r"^\+\+\+ (?:(?:b/(.+?)(?:\t.*)?)|(/dev/null))$", re.MULTILINE)


def split_diff_per_file(diff: str) -> list[tuple[str, str]]:
    """Split a multi-file unified diff into non-deleted ``(path, chunk)`` pairs."""
    if not diff or not diff.strip():
        return []

    headers = list(_DIFF_GIT_HEADER_RE.finditer(diff))
    if not headers:
        plus_headers = list(_DIFF_PLUS_HEADER_RE.finditer(diff))
        return [
            (
                path,
                diff[match.start() : plus_headers[index + 1].start() if index + 1 < len(plus_headers) else len(diff)],
            )
            for index, match in enumerate(plus_headers)
            if (path := match.group(1).strip() if match.group(1) else "")
        ]

    results: list[tuple[str, str]] = []
    for index, match in enumerate(headers):
        start = match.start()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(diff)
        chunk = diff[start:end]
        path = match.group(2).strip()

        if not path:
            plus_match = _DIFF_PLUS_HEADER_RE.search(chunk)
            if plus_match:
                path = plus_match.group(1).strip() if plus_match.group(1) else ""

        if not path or path == "/dev/null" or "\n+++ /dev/null" in chunk:
            continue
        results.append((path, chunk))

    return results


def sort_tests_first(file_diffs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Order tests before implementation so stateful TDD policies see an atomic change."""
    return sorted(file_diffs, key=lambda item: tests_first_sort_key(item[0]))
