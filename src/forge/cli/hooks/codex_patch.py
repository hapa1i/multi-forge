"""Parser for Codex's apply_patch envelope (PreToolUse ``tool_input.command``).

System boundary: the patch text arrives in a Codex hook payload (external data),
so the parser is strict but the caller fails open -- ``None`` means "not a patch
Forge can reason about", and the hook allows the action rather than guessing.
Codex's own apply_patch rejects input outside this grammar, so failing open on
malformed text converges with native behavior.

Grammar (codex-cli 0.138.0; witness fixture in ``tests/fixtures/codex/hooks/``)::

    *** Begin Patch
    *** Add File: <path> | *** Update File: <path> | *** Delete File: <path>
    *** Move to: <path>        (only immediately after an Update header)
    <body lines prefixed +, -, space, or @@; blank lines are context>
    *** End of File            (tolerated inside add/update sections)
    *** End Patch
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from forge.policy.types import extract_added_lines

PatchOpKind = Literal["add", "update", "delete"]

_BEGIN = "*** Begin Patch"
_END = "*** End Patch"
_EOF_MARKER = "*** End of File"
_MOVE_TO = "*** Move to: "
_HEADERS: tuple[tuple[str, PatchOpKind], ...] = (
    ("*** Add File: ", "add"),
    ("*** Update File: ", "update"),
    ("*** Delete File: ", "delete"),
)


@dataclass(frozen=True)
class PatchFileOp:
    """One file operation parsed from an apply_patch envelope.

    ``path`` is the post-op path (the "Move to" target when present) -- policies
    judge where content lands, not where it came from. The pre-move path is
    recoverable from ``raw_section``.
    """

    kind: PatchOpKind
    path: str
    move_to: str | None
    added_content: str  # introduced lines ("" for delete)
    raw_section: str  # verbatim header + body (raw_diff source)


@dataclass
class _Section:
    kind: PatchOpKind
    path: str
    move_to: str | None = None
    header_lines: list[str] = field(default_factory=list)
    body: list[str] = field(default_factory=list)

    def finalize(self) -> PatchFileOp:
        body = "\n".join(self.body)
        return PatchFileOp(
            kind=self.kind,
            path=self.move_to or self.path,
            move_to=self.move_to,
            added_content="" if self.kind == "delete" else extract_added_lines(body),
            raw_section="\n".join(self.header_lines + self.body),
        )


def parse_apply_patch(command: str) -> list[PatchFileOp] | None:
    """Parse an apply_patch envelope into per-file operations.

    Returns None for anything outside the known grammar (caller fails open);
    an empty envelope (Begin + End only) returns [].
    """
    lines = [line.rstrip("\r") for line in command.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines or lines[0] != _BEGIN or lines[-1] != _END or len(lines) < 2:
        return None

    ops: list[PatchFileOp] = []
    current: _Section | None = None

    for line in lines[1:-1]:
        header = _match_header(line)
        if header is not None:
            kind, path = header
            if not path:
                return None
            if current is not None:
                ops.append(current.finalize())
            current = _Section(kind=kind, path=path, header_lines=[line])
        elif line.startswith(_MOVE_TO):
            # Only valid immediately after an Update header (no body yet, one move max).
            target = line[len(_MOVE_TO) :].strip()
            if current is None or current.kind != "update" or current.body or current.move_to or not target:
                return None
            current.move_to = target
            current.header_lines.append(line)
        elif line == _EOF_MARKER:
            if current is None or current.kind == "delete":
                return None
            current.body.append(line)  # kept verbatim in raw_section; extract_added_lines ignores it
        elif current is None:
            return None  # body line before any section header
        elif current.kind == "delete":
            return None  # Delete sections are bodyless in the grammar
        elif line == "" or line.startswith(("+", "-", " ", "@@")):
            current.body.append(line)
        else:
            return None

    if current is not None:
        ops.append(current.finalize())
    return ops


def _match_header(line: str) -> tuple[PatchOpKind, str] | None:
    for prefix, kind in _HEADERS:
        if line.startswith(prefix):
            return kind, line[len(prefix) :].strip()
    return None
