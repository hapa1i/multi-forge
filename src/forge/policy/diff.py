"""Shared parsing for policy checks over unified diffs."""

from __future__ import annotations

import os
import re

from forge.policy.deterministic.base import tests_first_sort_key

_DIFF_FILE_HEADER_RE = re.compile(r"^diff --(?P<kind>git|cc|combined) (?P<body>.+)$", re.MULTILINE)
_DIFF_MINUS_HEADER_RE = re.compile(r"^--- (?P<path>.+)$", re.MULTILINE)
_DIFF_PLUS_HEADER_RE = re.compile(r"^\+\+\+ (?P<path>.+)$", re.MULTILINE)
_DIFF_RENAME_TO_RE = re.compile(r"^rename to (?P<path>.+)$", re.MULTILINE)
_DIFF_COPY_TO_RE = re.compile(r"^copy to (?P<path>.+)$", re.MULTILINE)
_DIFF_DELETED_FILE_MODE_RE = re.compile(r"^deleted file mode \d+\r?$", re.MULTILINE)
_UNIFIED_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,(?P<old_count>\d+))? \+\d+(?:,(?P<new_count>\d+))? @@")
_GIT_C_ESCAPES = {
    "a": 0x07,
    "b": 0x08,
    "t": 0x09,
    "n": 0x0A,
    "v": 0x0B,
    "f": 0x0C,
    "r": 0x0D,
    '"': 0x22,
    "\\": 0x5C,
}


class DiffParseError(ValueError):
    """A non-deletion diff chunk could not be attributed to a path."""

    def __init__(self, unattributed_chunks: int) -> None:
        self.unattributed_chunks = unattributed_chunks
        noun = "file chunk" if unattributed_chunks == 1 else "file chunks"
        super().__init__(
            f"Diff could not be parsed completely: {unattributed_chunks} {noun} could not be attributed to a path"
        )


def _quoted_token_end(value: str, start: int = 0) -> int | None:
    """Return the exclusive end of one C-quoted token."""
    if start >= len(value) or value[start] != '"':
        return None
    index = start + 1
    while index < len(value):
        if value[index] == "\\":
            index += 2
            continue
        if value[index] == '"':
            return index + 1
        index += 1
    return None


def _split_git_header_tokens(value: str) -> tuple[str, str] | None:
    """Return the two raw paths from a ``diff --git`` header.

    Git C-quotes paths containing bytes controlled by ``core.quotePath``, but
    ordinary spaces remain unquoted. The unquoted form is therefore not a
    whitespace-tokenized format: its only structural delimiter is the `` b/``
    destination prefix. When a same-path header contains that text inside the
    filename, prefer the split whose two prefix-stripped paths agree; otherwise
    preserve the historical first-delimiter behavior deterministically.
    """
    value = value.strip()
    if not value:
        return None

    if value.startswith('"'):
        source_end = _quoted_token_end(value)
        if source_end is None:
            return None
        source = value[:source_end]
        destination = value[source_end:].lstrip()
        if not destination:
            return None
        if destination.startswith('"') and _quoted_token_end(destination) != len(destination):
            return None
        return source, destination

    # A quoted destination is unambiguous even when the unquoted source has spaces.
    quoted_destination_marker = ' "b/'
    marker_index = value.rfind(quoted_destination_marker)
    if marker_index >= 0:
        destination = value[marker_index + 1 :]
        if _quoted_token_end(destination) == len(destination):
            return value[:marker_index], destination

    candidates: list[tuple[str, str]] = []
    marker = " b/"
    search_from = 0
    while (marker_index := value.find(marker, search_from)) >= 0:
        source = value[:marker_index]
        destination = value[marker_index + 1 :]
        if source.startswith("a/") and len(source) > 2 and len(destination) > 2:
            candidates.append((source, destination))
        search_from = marker_index + len(marker)
    if not candidates:
        return None
    for source, destination in candidates:
        if source[2:] == destination[2:]:
            return source, destination
    return candidates[0]


def _decode_git_path_token(token: str) -> str | None:
    """Decode one raw Git path token, including Git's C-style byte escapes."""
    if not token.startswith('"'):
        return token
    if len(token) < 2 or not token.endswith('"'):
        return None

    encoded = bytearray()
    value = token[1:-1]
    index = 0
    while index < len(value):
        char = value[index]
        if char != "\\":
            encoded.extend(os.fsencode(char))
            index += 1
            continue

        index += 1
        if index == len(value):
            return None
        escaped = value[index]
        if escaped in "01234567":
            end = index + 1
            while end < min(index + 3, len(value)) and value[end] in "01234567":
                end += 1
            octal = value[index:end]
            byte = int(octal, 8)
            if byte > 0xFF:
                return None
            encoded.append(byte)
            index = end
            continue
        if escaped not in _GIT_C_ESCAPES:
            return None
        encoded.append(_GIT_C_ESCAPES[escaped])
        index += 1

    return os.fsdecode(bytes(encoded))


def _git_header_destination(match: re.Match[str]) -> str:
    tokens = _split_git_header_tokens(match.group("body"))
    if tokens is None:
        return ""
    destination = _decode_git_path_token(tokens[1])
    if destination is None or not destination.startswith("b/"):
        return ""
    return destination[2:]


def _combined_header_destination(match: re.Match[str]) -> str:
    """Decode the unprefixed path from one combined-diff header."""
    raw_path = match.group("body").removesuffix("\r")
    return _decode_git_path_token(raw_path) or ""


def _plus_header_path(match: re.Match[str]) -> str | None:
    raw_path = match.group("path").split("\t", 1)[0].strip()
    path = _decode_git_path_token(raw_path)
    if path is None or path == "/dev/null":
        return path
    if not path.startswith("b/"):
        return None
    return path[2:]


def _headerless_plus_headers(diff: str) -> list[tuple[re.Match[str], str | None]]:
    """Return structural destination headers and any paths that can be decoded.

    A hunk can add source text that itself looks exactly like ``+++ b/path``
    or ``+++ /dev/null``. Recognize later destination headers only when they
    are paired with a source header outside a counted hunk. The first
    standalone destination remains supported for the historical single-file
    input accepted by ``policy check --diff``.
    """
    headers: list[tuple[re.Match[str], str | None]] = []
    source_header_pending = False
    old_remaining: int | None = None
    new_remaining: int | None = None
    offset = 0

    for line in diff.splitlines(keepends=True):
        text = line.rstrip("\r\n")
        if old_remaining is not None and new_remaining is not None:
            if text.startswith("\\"):
                offset += len(line)
                continue
            prefix = text[:1]
            if prefix in {" ", "-"}:
                old_remaining -= 1
            if prefix in {" ", "+"}:
                new_remaining -= 1
            if old_remaining <= 0 and new_remaining <= 0:
                old_remaining = None
                new_remaining = None
            offset += len(line)
            continue

        hunk_match = _UNIFIED_HUNK_HEADER_RE.match(text)
        if hunk_match is not None:
            old_remaining = int(hunk_match.group("old_count") or "1")
            new_remaining = int(hunk_match.group("new_count") or "1")
            if old_remaining == 0 and new_remaining == 0:
                old_remaining = None
                new_remaining = None
            source_header_pending = False
            offset += len(line)
            continue

        plus_match = _DIFF_PLUS_HEADER_RE.match(diff, offset)
        if plus_match is not None:
            path = _plus_header_path(plus_match)
            if source_header_pending or not headers:
                headers.append((plus_match, path))
            else:
                # A later standalone destination is not a valid boundary. Keep
                # it visible as malformed instead of folding it into a valid file.
                headers.append((plus_match, None))
            source_header_pending = False
            offset += len(line)
            continue

        source_header_pending = _DIFF_MINUS_HEADER_RE.match(diff, offset) is not None
        offset += len(line)

    return headers


def _metadata_destination(match: re.Match[str]) -> str:
    raw_path = match.group("path").removesuffix("\r")
    return _decode_git_path_token(raw_path) or ""


def split_diff_per_file(diff: str) -> list[tuple[str, str]]:
    """Split a diff into non-deleted pairs, refusing silent attribution loss."""
    if not diff or not diff.strip():
        return []

    headers = list(_DIFF_FILE_HEADER_RE.finditer(diff))
    if not headers:
        plus_headers = _headerless_plus_headers(diff)
        plus_results: list[tuple[str, str]] = []
        unattributed_chunks = 0
        for index, (match, path) in enumerate(plus_headers):
            if path is None:
                unattributed_chunks += 1
                continue
            if path == "/dev/null":
                continue
            end = plus_headers[index + 1][0].start() if index + 1 < len(plus_headers) else len(diff)
            plus_results.append((path, diff[match.start() : end]))
        if unattributed_chunks:
            raise DiffParseError(unattributed_chunks)
        return plus_results

    results: list[tuple[str, str]] = []
    unattributed_chunks = 0
    for index, match in enumerate(headers):
        start = match.start()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(diff)
        chunk = diff[start:end]
        path = ""

        plus_match = _DIFF_PLUS_HEADER_RE.search(chunk)
        if plus_match:
            plus_path = _plus_header_path(plus_match)
            if plus_path == "/dev/null":
                continue
            path = plus_path or ""
        if _DIFF_DELETED_FILE_MODE_RE.search(chunk):
            continue
        if not path:
            rename_match = _DIFF_RENAME_TO_RE.search(chunk)
            if rename_match:
                path = _metadata_destination(rename_match)
        if not path:
            copy_match = _DIFF_COPY_TO_RE.search(chunk)
            if copy_match:
                path = _metadata_destination(copy_match)
        if not path:
            path = (
                _git_header_destination(match) if match.group("kind") == "git" else _combined_header_destination(match)
            )

        if not path:
            unattributed_chunks += 1
            continue
        results.append((path, chunk))

    if unattributed_chunks:
        raise DiffParseError(unattributed_chunks)
    return results


def sort_tests_first(file_diffs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Order tests before implementation so stateful TDD policies see an atomic change."""
    return sorted(file_diffs, key=lambda item: tests_first_sort_key(item[0]))
