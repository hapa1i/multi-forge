#!/usr/bin/env python3
"""Validate repository-local paths and Markdown heading fragments.

The check scans every tracked Markdown file so deleting or moving a target is
visible even when the referring document was not part of the current change.
Remote URLs and fragments on non-Markdown files are outside this check's scope.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

INLINE_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)")
REFERENCE_LINK_RE = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)")
HTML_ID_RE = re.compile(r"<(?:a|[A-Za-z][A-Za-z0-9-]*)\b[^>]*(?:id|name)=[\"']([^\"']+)[\"']", re.I)
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
REMOTE_SCHEMES = {"data", "http", "https", "mailto", "ssh", "tel"}


@dataclass(frozen=True)
class LinkFailure:
    source: Path
    line: int
    target: str
    reason: str


def github_slug(title: str) -> str:
    """Return the GitHub-style base slug used by this repository's headings."""
    title = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", title)
    title = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", title)
    title = re.sub(r"<[^>]+>", "", title)
    title = title.lower()
    title = re.sub(r"[^\w\- ]", "", title, flags=re.UNICODE)
    return re.sub(r" +", "-", title.strip())


def markdown_anchors(path: Path) -> set[str]:
    """Collect generated heading anchors and explicit HTML ids."""
    anchors: set[str] = set()
    duplicates: Counter[str] = Counter()
    in_fence: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)[0]
            if in_fence is None:
                in_fence = marker
            elif marker == in_fence:
                in_fence = None
            continue
        if in_fence is not None:
            continue
        for explicit in HTML_ID_RE.findall(line):
            anchors.add(explicit)
        match = HEADING_RE.match(line)
        if not match:
            continue
        base = github_slug(match.group(1))
        suffix = duplicates[base]
        duplicates[base] += 1
        anchors.add(f"{base}-{suffix}" if suffix else base)
    return anchors


def markdown_links(path: Path) -> list[tuple[int, str]]:
    """Return local and remote link targets outside fenced code blocks."""
    links: list[tuple[int, str]] = []
    in_fence: str | None = None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)[0]
            if in_fence is None:
                in_fence = marker
            elif marker == in_fence:
                in_fence = None
            continue
        if in_fence is not None:
            continue
        links.extend((number, target.strip("<>")) for target in INLINE_LINK_RE.findall(line))
        if reference := REFERENCE_LINK_RE.match(line):
            links.append((number, reference.group(1).strip("<>")))
    return links


def tracked_markdown(root: Path) -> list[Path]:
    """List Markdown files tracked by Git."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.md"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [root / item.decode() for item in result.stdout.split(b"\0") if item and (root / item.decode()).is_file()]


def audit_paths(root: Path, sources: list[Path]) -> list[LinkFailure]:
    """Validate local link targets and Markdown fragments for source files."""
    failures: list[LinkFailure] = []
    anchor_cache: dict[Path, set[str]] = {}
    for source in sources:
        for line, raw_target in markdown_links(source):
            parsed = urlsplit(raw_target)
            if parsed.scheme.lower() in REMOTE_SCHEMES or parsed.netloc or (not parsed.path and not parsed.fragment):
                continue
            if parsed.path:
                target_text = unquote(parsed.path)
                target = Path(target_text)
                if not target.is_absolute():
                    target = source.parent / target
            else:
                target = source
            target = target.resolve()
            try:
                target.relative_to(root.resolve())
            except ValueError:
                failures.append(LinkFailure(source, line, raw_target, "target escapes repository"))
                continue
            if not target.exists():
                failures.append(LinkFailure(source, line, raw_target, "target does not exist"))
                continue
            if parsed.fragment and target.suffix.lower() == ".md":
                anchors = anchor_cache.setdefault(target, markdown_anchors(target))
                fragment = unquote(parsed.fragment)
                if fragment not in anchors:
                    failures.append(LinkFailure(source, line, raw_target, "Markdown fragment does not exist"))
    return failures


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="Markdown sources to audit (default: all tracked files)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root_result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    root = Path(root_result.stdout.strip()).resolve()
    sources = [(root / path).resolve() for path in args.paths] if args.paths else tracked_markdown(root)
    failures = audit_paths(root, sources)
    for failure in failures:
        source = failure.source.relative_to(root)
        print(f"{source}:{failure.line}: {failure.reason}: {failure.target}")
    if failures:
        print(f"Markdown link audit failed with {len(failures)} error(s).", file=sys.stderr)
        return 1
    print(f"Markdown link audit passed for {len(sources)} source file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
