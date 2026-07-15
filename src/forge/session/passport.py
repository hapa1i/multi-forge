"""Memory-doc passport model: frontmatter parsing, validation, and resolution.

A passport is a ``forge_memory`` YAML frontmatter block embedded in a markdown
memory doc. It describes the doc's intent, update contract, and writer privileges.
Sessions store participation only; the memory writer re-reads the passport at
stop time for the authoritative contract.
"""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from enum import Enum
from io import StringIO
from pathlib import Path
from typing import Any

import yaml
from ruamel.yaml import YAML
from yaml.nodes import MappingNode

from forge.core.state.io import atomic_write_text
from forge.session.exceptions import InvalidSessionNameError, PassportError
from forge.session.models import DesignatedDoc
from forge.session.validation import validate_name

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Strategy constants (single source of truth)
# ---------------------------------------------------------------------------


class MemoryStrategy(str, Enum):
    """Built-in memory-doc augmentation strategies."""

    PROJECT_STATE = "project-state"
    CHECKLIST = "checklist"
    CHANGELOG = "changelog"
    GENERIC = "generic"


VALID_STRATEGY_NAMES: frozenset[str] = frozenset(s.value for s in MemoryStrategy)

STRATEGY_INSTRUCTIONS: dict[str, str] = {
    "project-state": (
        "Update current focus, active work, recent decisions, and handoff notes. "
        "Mark completed items as done rather than removing them. "
        "If the file does not exist, skip it and report that it was missing."
    ),
    "checklist": (
        "Mark completed tasks with [x]. Add newly discovered tasks. "
        "Do NOT remove, rewrite, or restructure existing entries. "
        "If the file does not exist, skip it and report that it was missing."
    ),
    "changelog": (
        "Add accomplishments from this session not already recorded. "
        "Follow the existing entry format. "
        "Do NOT modify or remove existing entries. "
        "If the file does not exist, skip it and report that it was missing."
    ),
    "generic": (
        "Read the file and add any NEW information from this session that is missing. "
        "Do NOT duplicate, rephrase, or remove what is already documented. "
        "If the file does not exist, skip it and report that it was missing."
    ),
}

# ---------------------------------------------------------------------------
# Passport dataclasses
# ---------------------------------------------------------------------------

PASSPORT_VERSION = 1
VALID_PASSPORT_MODES: frozenset[str] = frozenset({"direct", "shadow-only"})
VALID_APPROVAL_VALUES: frozenset[str] = frozenset({"human-promoted"})

_KNOWN_UPDATE_KEYS = frozenset(
    {
        "instruction",
        "strategy",
        "mode",
        "writers",
        "inherit_on_fork",
        "compact_when",
        "shadow_path",
        "approval",
    }
)
_KNOWN_TOP_KEYS = frozenset({"version", "intent", "captures", "excludes", "update"})


@dataclass
class PassportUpdate:
    """Update contract for a memory doc."""

    instruction: str | None = None
    strategy: str = "generic"
    mode: str = "direct"
    writers: str = "all-sessions"
    compact_when: str | None = None
    shadow_path: str | None = None
    approval: str | None = None


@dataclass
class Passport:
    """Memory-doc passport: the doc's identity and update contract."""

    version: int
    intent: str
    captures: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    update: PassportUpdate = field(default_factory=PassportUpdate)


@dataclass(frozen=True)
class PreparedPassportWrite:
    """Validated passport rewrite ready for one atomic apply."""

    text: str
    added_okf_fields: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Resolved doc spec (passport-authoritative, consumed by prompt builder)
# ---------------------------------------------------------------------------


@dataclass
class ResolvedDocSpec:
    """Passport-resolved doc update specification for prompt building.

    Produced by ``resolve_doc_spec()``; consumed by ``build_multi_doc_prompt()``.
    The prompt builder has no file I/O.
    """

    write_path: str
    official_path: str | None
    strategy_instruction: str
    custom_instruction: str | None
    intent: str | None
    captures: list[str]
    excludes: list[str]
    compact_when: str | None
    approval: str | None


# ---------------------------------------------------------------------------
# Passport source resolution
# ---------------------------------------------------------------------------


def resolve_passport_source(doc: DesignatedDoc) -> str:
    """Return the path where the passport lives for a DesignatedDoc.

    If ``doc.shadows`` is set (shadow mode), the passport lives on the
    official doc (``doc.shadows``). Otherwise it lives on ``doc.path``.
    """
    return doc.shadows or doc.path


def derive_shadow_path(official_path: str) -> str:
    """Derive a default shadow file path for an official doc.

    Encodes the immediate parent directory to reduce collisions:
    ``docs/board/notes.md`` -> ``.forge/memory/shadow_board_notes.md``.
    Top-level files omit the parent prefix.
    """
    p = Path(official_path)
    parent = p.parent.name
    if parent and parent != ".":
        return f".forge/memory/shadow_{parent}_{p.stem}.md"
    return f".forge/memory/shadow_{p.stem}.md"


# ---------------------------------------------------------------------------
# Doc resolution (passport-authoritative)
# ---------------------------------------------------------------------------


def resolve_doc_spec(
    doc: DesignatedDoc,
    passport: Passport | None,
) -> ResolvedDocSpec:
    """Resolve a DesignatedDoc + optional Passport into a prompt-ready spec.

    Passport fields are authoritative when present. DesignatedDoc fields
    serve as fallbacks for unpassported docs.
    """
    if passport is None:
        strategy_key = doc.strategy
        return ResolvedDocSpec(
            write_path=doc.path,
            official_path=doc.shadows,
            strategy_instruction=STRATEGY_INSTRUCTIONS.get(strategy_key, STRATEGY_INSTRUCTIONS["generic"]),
            custom_instruction=None,
            intent=None,
            captures=[],
            excludes=[],
            compact_when=None,
            approval=None,
        )

    strategy_key = passport.update.strategy

    passport_source = resolve_passport_source(doc)
    shadow_path = passport.update.shadow_path
    if passport.update.mode == "shadow-only":
        if not shadow_path:
            raise PassportError(
                "forge_memory.update.shadow_path",
                "required when mode is 'shadow-only'",
            )
        write_path: str = shadow_path
        official_path: str | None = passport_source
    else:
        if shadow_path:
            raise PassportError(
                "forge_memory.update.shadow_path",
                "not allowed when mode is 'direct'",
                hint="set mode to 'shadow-only' to use a shadow path",
            )
        write_path = passport_source
        official_path = None

    return ResolvedDocSpec(
        write_path=write_path,
        official_path=official_path,
        strategy_instruction=STRATEGY_INSTRUCTIONS.get(strategy_key, STRATEGY_INSTRUCTIONS["generic"]),
        custom_instruction=passport.update.instruction,
        intent=passport.intent,
        captures=list(passport.captures),
        excludes=list(passport.excludes),
        compact_when=passport.update.compact_when,
        approval=passport.update.approval,
    )


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(?P<yaml>.*?\r?\n)---[ \t]*\r?\n", re.DOTALL)
_MUTATION_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(?P<yaml>.*?)^---[ \t]*\r?\n",
    re.DOTALL | re.MULTILINE,
)
_MUTATION_FRONTMATTER_EOF_RE = re.compile(
    r"\A---[ \t]*\r?\n(?P<yaml>.*?)^---[ \t]*\Z",
    re.DOTALL | re.MULTILINE,
)


def extract_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    """Split YAML frontmatter from markdown body.

    Returns ``(frontmatter_dict_or_None, body_text)``.

    Raises:
        PassportError: If valid delimiters surround malformed YAML.
    """
    m = _FRONTMATTER_RE.match(text)
    if m is None:
        return None, text

    yaml_block = m.group("yaml")
    body = text[m.end() :]

    try:
        data = yaml.safe_load(yaml_block)
    except yaml.YAMLError as e:
        raise PassportError("forge_memory", f"malformed YAML in frontmatter: {e}") from e

    if data is None:
        return {}, body
    if not isinstance(data, dict):
        return None, text

    return data, body


def _extract_frontmatter_for_mutation(text: str) -> tuple[dict[str, Any] | None, str]:
    """Split mapping frontmatter for a write without broadening read behavior."""
    if text.startswith("\ufeff---"):
        raise PassportError(
            "frontmatter",
            "leading UTF-8 BOM before YAML frontmatter is not supported for mutation",
            hint="remove the BOM, then retry",
        )

    # Prefer the delimiter span selected by the permissive read parser. The
    # mutation-only fallback keeps a truly zero-line empty block writable,
    # which the legacy read regex intentionally does not recognize.
    match = _FRONTMATTER_RE.match(text) or _MUTATION_FRONTMATTER_RE.match(text)
    if match is None:
        if _MUTATION_FRONTMATTER_EOF_RE.match(text) is not None:
            raise PassportError(
                "frontmatter",
                "closing YAML delimiter at end of file is not supported for mutation",
                hint="add a newline after the closing '---', then retry",
            )
        return None, text

    yaml_block = match.group("yaml")
    body = text[match.end() :]
    try:
        node = yaml.compose(yaml_block)
        data = yaml.safe_load(yaml_block)
    except yaml.YAMLError as exc:
        raise PassportError("frontmatter", f"malformed YAML: {exc}") from exc

    if node is None:
        return {}, body
    if not isinstance(node, MappingNode) or not isinstance(data, dict):
        raise PassportError(
            "frontmatter",
            f"must be a mapping (got {type(data).__name__})",
            hint="replace the YAML root with a mapping before retrying",
        )
    return data, body


def parse_passport(data: Any) -> Passport:
    """Parse a ``forge_memory`` value into a Passport.

    Strict validation: rejects unknown keys, validates all fields.

    Raises:
        PassportError: With ``field_path`` and actionable message.
    """
    if not isinstance(data, dict):
        raise PassportError(
            "forge_memory",
            f"must be a mapping (got {type(data).__name__})",
            hint="expected a YAML mapping with version, intent, and update fields",
        )

    unknown_top = set(data.keys()) - _KNOWN_TOP_KEYS
    if unknown_top:
        raise PassportError(
            "forge_memory",
            f"unknown fields: {', '.join(sorted(unknown_top))}",
            hint=f"valid fields: {', '.join(sorted(_KNOWN_TOP_KEYS))}",
        )

    # version (required)
    if "version" not in data:
        raise PassportError("forge_memory.version", "required field missing")
    version = data["version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise PassportError("forge_memory.version", f"must be an integer (got {type(version).__name__})")
    if version > PASSPORT_VERSION:
        raise PassportError(
            "forge_memory.version",
            f"version {version} not supported",
            hint="written by newer Forge -- upgrade to read this passport",
        )
    if version < 1:
        raise PassportError("forge_memory.version", f"invalid version: {version}")

    # intent (required)
    if "intent" not in data:
        raise PassportError("forge_memory.intent", "required field missing")
    intent = data["intent"]
    if not isinstance(intent, str) or not intent.strip():
        raise PassportError("forge_memory.intent", "must be a non-empty string")

    # captures (optional list[str])
    captures = _parse_string_list(data.get("captures"), "forge_memory.captures")

    # excludes (optional list[str])
    excludes = _parse_string_list(data.get("excludes"), "forge_memory.excludes")

    # update (optional section, defaults apply)
    update_data = data.get("update")
    if update_data is None:
        update = PassportUpdate()
    else:
        update = _parse_update(update_data)

    return Passport(
        version=version,
        intent=intent.strip(),
        captures=captures,
        excludes=excludes,
        update=update,
    )


def _parse_string_list(value: Any, field_path: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PassportError(field_path, f"must be a list of strings (got {type(value).__name__})")
    result: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise PassportError(f"{field_path}[{i}]", f"must be a string (got {type(item).__name__})")
        result.append(item)
    return result


def _parse_update(data: Any) -> PassportUpdate:
    if not isinstance(data, dict):
        raise PassportError("forge_memory.update", f"must be a mapping (got {type(data).__name__})")

    unknown = set(data.keys()) - _KNOWN_UPDATE_KEYS
    if unknown:
        raise PassportError(
            "forge_memory.update",
            f"unknown fields: {', '.join(sorted(unknown))}",
            hint=f"valid fields: {', '.join(sorted(_KNOWN_UPDATE_KEYS))}",
        )

    strategy = data.get("strategy", "generic")
    if not isinstance(strategy, str):
        raise PassportError(
            "forge_memory.update.strategy",
            f"must be a string (got {type(strategy).__name__})",
        )
    if strategy not in VALID_STRATEGY_NAMES:
        raise PassportError(
            "forge_memory.update.strategy",
            f"unknown strategy '{strategy}'",
            hint=f"valid strategies: {', '.join(sorted(VALID_STRATEGY_NAMES))}",
        )

    mode = data.get("mode", "direct")
    if not isinstance(mode, str):
        raise PassportError(
            "forge_memory.update.mode",
            f"must be a string (got {type(mode).__name__})",
        )
    if mode not in VALID_PASSPORT_MODES:
        raise PassportError(
            "forge_memory.update.mode",
            f"unknown mode '{mode}'",
            hint=f"valid modes: {', '.join(sorted(VALID_PASSPORT_MODES))}",
        )

    shadow_path = data.get("shadow_path")
    if shadow_path is not None and not isinstance(shadow_path, str):
        raise PassportError(
            "forge_memory.update.shadow_path",
            f"must be a string (got {type(shadow_path).__name__})",
        )
    if mode == "shadow-only" and not shadow_path:
        raise PassportError(
            "forge_memory.update.shadow_path",
            "required when mode is 'shadow-only'",
        )
    if mode == "direct" and shadow_path:
        raise PassportError(
            "forge_memory.update.shadow_path",
            "not allowed when mode is 'direct'",
            hint="set mode to 'shadow-only' to use a shadow path",
        )

    writers = data.get("writers", "all-sessions")
    if not isinstance(writers, str):
        raise PassportError(
            "forge_memory.update.writers",
            f"must be a string (got {type(writers).__name__})",
        )
    validate_writer_spec(writers)

    instruction = data.get("instruction")
    if instruction is not None and not isinstance(instruction, str):
        raise PassportError(
            "forge_memory.update.instruction",
            f"must be a string (got {type(instruction).__name__})",
        )

    compact_when = data.get("compact_when")
    if compact_when is not None and not isinstance(compact_when, str):
        raise PassportError(
            "forge_memory.update.compact_when",
            f"must be a string (got {type(compact_when).__name__})",
        )

    approval = data.get("approval")
    if approval is not None and not isinstance(approval, str):
        raise PassportError(
            "forge_memory.update.approval",
            f"must be a string (got {type(approval).__name__})",
        )
    if approval is not None and approval not in VALID_APPROVAL_VALUES:
        raise PassportError(
            "forge_memory.update.approval",
            f"unknown approval '{approval}'",
            hint=f"valid approvals: {', '.join(sorted(VALID_APPROVAL_VALUES))}",
        )

    return PassportUpdate(
        instruction=instruction,
        strategy=strategy,
        mode=mode,
        writers=writers,
        compact_when=compact_when,
        shadow_path=shadow_path,
        approval=approval,
    )


def read_passport(path: Path) -> Passport | None:
    """Read a passport from a markdown file.

    Returns ``None`` if the file has no ``forge_memory`` frontmatter block.

    Raises:
        PassportError: If the frontmatter contains a malformed ``forge_memory`` block.
        FileNotFoundError: If the file does not exist.
    """
    text = path.read_text(encoding="utf-8")
    fm, _ = extract_frontmatter(text)
    if fm is None or "forge_memory" not in fm:
        return None
    return parse_passport(fm["forge_memory"])


# ---------------------------------------------------------------------------
# Frontmatter serialization
# ---------------------------------------------------------------------------


def _passport_to_dict(passport: Passport) -> dict[str, Any]:
    """Convert a Passport to a dict, omitting None-valued fields."""
    raw = asdict(passport)
    update = raw.get("update", {})
    raw["update"] = {k: v for k, v in update.items() if v is not None}
    return raw


def _dump_yaml(data: dict[str, Any]) -> str:
    ruamel = YAML()
    ruamel.default_flow_style = False
    buf = StringIO()
    ruamel.dump(data, buf)
    return buf.getvalue()


def serialize_passport(passport: Passport) -> str:
    """Serialize a passport to a YAML string (``forge_memory`` block only).

    Omits ``None``-valued fields for clean frontmatter output.
    """
    return _dump_yaml({"forge_memory": _passport_to_dict(passport)})


_RESERVED_OKF_BASENAMES = frozenset({"index.md", "log.md"})
_FENCE_OPEN_RE = re.compile(r"^[ ]{0,3}(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
_ATX_H1_RE = re.compile(r"^[ ]{0,3}#[ \t]+(?P<title>.*)$")
_ATX_CLOSING_RE = re.compile(r"[ \t]+#+[ \t]*$")


def validate_okf_reserved_basenames(logical_path: str, resolved_path: Path) -> None:
    """Reject logical or resolved paths whose basename is reserved by OKF."""
    logical = Path(logical_path)
    if logical.name.casefold() in _RESERVED_OKF_BASENAMES:
        raise PassportError(
            "path",
            f"'{logical.name}' is reserved by OKF and cannot be a memory concept document",
            hint="choose a non-reserved Markdown filename",
        )
    if resolved_path.name.casefold() in _RESERVED_OKF_BASENAMES:
        raise PassportError(
            "path",
            f"resolved target '{resolved_path.name}' is reserved by OKF",
            hint="choose a document that does not resolve to index.md or log.md",
        )


def validate_okf_memory_path(logical_path: str, resolved_path: Path) -> None:
    """Validate the scanner path and resolved target for OKF generation."""
    logical = Path(logical_path)
    if logical.suffix != ".md":
        raise PassportError(
            "path",
            f"OKF memory documents require an exact '.md' suffix: {logical_path}",
            hint="rename the document with a lowercase .md suffix, then retry",
        )
    validate_okf_reserved_basenames(logical_path, resolved_path)


def _derive_okf_title(body: str, logical_path: str) -> str | None:
    fence_char: str | None = None
    fence_length = 0
    for line in body.splitlines():
        if fence_char is not None:
            closing = re.match(rf"^[ ]{{0,3}}{re.escape(fence_char)}{{{fence_length},}}[ \t]*$", line)
            if closing is not None:
                fence_char = None
                fence_length = 0
            continue

        fence = _FENCE_OPEN_RE.match(line)
        if fence is not None:
            marker = fence.group("fence")
            if marker.startswith("~") or "`" not in fence.group("info"):
                fence_char = marker[0]
                fence_length = len(marker)
                continue

        heading = _ATX_H1_RE.match(line)
        if heading is None:
            continue
        title = heading.group("title").strip()
        if re.fullmatch(r"#+", title):
            title = ""
        else:
            title = _ATX_CLOSING_RE.sub("", title).strip()
        if title:
            return title

    stem = Path(logical_path).stem
    normalized = re.sub(r"[_-]+", " ", stem)
    normalized = " ".join(normalized.split())
    return normalized or None


def _add_okf_envelope(
    frontmatter: dict[str, Any],
    body: str,
    passport: Passport,
    logical_path: str,
) -> tuple[str, ...]:
    added: list[str] = []
    if "type" not in frontmatter:
        frontmatter["type"] = "Memory Document"
        added.append("type")
    else:
        concept_type = frontmatter["type"]
        if not isinstance(concept_type, str) or not concept_type.strip():
            raise PassportError("type", "must be a non-empty string when present")

    if "title" not in frontmatter:
        title = _derive_okf_title(body, logical_path)
        if title is not None:
            frontmatter["title"] = title
            added.append("title")

    if "description" not in frontmatter:
        frontmatter["description"] = " ".join(passport.intent.split())
        added.append("description")

    return tuple(added)


def _prepare_frontmatter_rewrite(
    frontmatter: dict[str, Any],
    body: str,
    *,
    added_okf_fields: tuple[str, ...] = (),
) -> PreparedPassportWrite:
    """Render one frontmatter mutation through the shared atomic-apply path."""
    text = f"---\n{_dump_yaml(frontmatter)}---\n{body}" if frontmatter else body
    return PreparedPassportWrite(text=text, added_okf_fields=added_okf_fields)


def prepare_passport_write(
    path: Path,
    passport: Passport,
    *,
    okf_path: str | None = None,
) -> PreparedPassportWrite:
    """Validate and render a passport rewrite without touching the file."""
    parse_passport(_passport_to_dict(passport))
    text = path.read_text(encoding="utf-8")
    frontmatter, body = _extract_frontmatter_for_mutation(text)
    if frontmatter is None:
        frontmatter = {}

    added: tuple[str, ...] = ()
    if okf_path is not None:
        validate_okf_memory_path(okf_path, path)
        added = _add_okf_envelope(frontmatter, body, passport, okf_path)

    frontmatter["forge_memory"] = _passport_to_dict(passport)
    return _prepare_frontmatter_rewrite(frontmatter, body, added_okf_fields=added)


def apply_prepared_passport_write(path: Path, prepared: PreparedPassportWrite) -> tuple[str, ...]:
    """Apply a previously validated passport rewrite atomically."""
    atomic_write_text(path, prepared.text, preserve_existing_mode=True)
    return prepared.added_okf_fields


def write_passport(
    path: Path,
    passport: Passport,
    *,
    okf_path: str | None = None,
) -> tuple[str, ...]:
    """Write or replace ``forge_memory`` frontmatter in a markdown file.

    Preserves non-``forge_memory`` frontmatter keys and markdown body.
    Uses atomic write (tempfile + rename) for crash safety.
    """
    prepared = prepare_passport_write(path, passport, okf_path=okf_path)
    return apply_prepared_passport_write(path, prepared)


def upgrade_passport_envelope(path: Path, *, logical_path: str) -> tuple[str, ...]:
    """Add missing OKF fields while preserving the raw ``forge_memory`` mapping."""
    validate_okf_memory_path(logical_path, path)
    text = path.read_text(encoding="utf-8")
    frontmatter, body = _extract_frontmatter_for_mutation(text)
    if frontmatter is None or "forge_memory" not in frontmatter:
        raise PassportError(
            "forge_memory",
            "passport not found",
            hint=f"run 'forge memory track {logical_path} --strategy <strategy>' first",
        )

    passport = parse_passport(frontmatter["forge_memory"])
    added = _add_okf_envelope(frontmatter, body, passport, logical_path)
    if not added:
        return ()

    prepared = _prepare_frontmatter_rewrite(frontmatter, body, added_okf_fields=added)
    return apply_prepared_passport_write(path, prepared)


def remove_passport(path: Path) -> bool:
    """Remove ``forge_memory`` frontmatter from a markdown file.

    Preserves unrelated frontmatter keys and the markdown body. Returns True
    when a passport key was removed, False when no passport was present.
    """
    text = path.read_text(encoding="utf-8")
    fm, body = _extract_frontmatter_for_mutation(text)

    if fm is None or "forge_memory" not in fm:
        return False

    del fm["forge_memory"]
    apply_prepared_passport_write(path, _prepare_frontmatter_rewrite(fm, body))
    return True


# ---------------------------------------------------------------------------
# Passport synthesis (Phase 2 infrastructure)
# ---------------------------------------------------------------------------

_DEFAULT_INTENTS: dict[str, str] = {
    "project-state": "Current project focus and handoff state",
    "checklist": "Active task tracking",
    "changelog": "Completed-work record",
    "generic": "Project documentation",
}


def synthesize_passport(
    *,
    strategy: str,
    intent: str | None = None,
    update_mode: str = "direct",
    shadow_path: str | None = None,
    writers: str = "all-sessions",
) -> Passport:
    """Create a starter passport from CLI-flag equivalents.

    Auto-generates intent from strategy when not provided.
    Always writes an explicit ``update`` section.
    """
    if strategy not in VALID_STRATEGY_NAMES:
        raise PassportError(
            "forge_memory.update.strategy",
            f"unknown strategy '{strategy}'",
            hint=f"valid strategies: {', '.join(sorted(VALID_STRATEGY_NAMES))}",
        )
    if update_mode not in VALID_PASSPORT_MODES:
        raise PassportError(
            "forge_memory.update.mode",
            f"unknown mode '{update_mode}'",
            hint=f"valid modes: {', '.join(sorted(VALID_PASSPORT_MODES))}",
        )

    if update_mode == "shadow-only" and not shadow_path:
        raise PassportError(
            "forge_memory.update.shadow_path",
            "required when mode is 'shadow-only'",
        )
    if update_mode == "direct" and shadow_path:
        raise PassportError(
            "forge_memory.update.shadow_path",
            "not allowed when mode is 'direct'",
            hint="set mode to 'shadow-only' to use a shadow path",
        )

    validate_writer_spec(writers)

    if intent is None:
        resolved_intent = _DEFAULT_INTENTS.get(strategy, "Project documentation")
    elif not intent.strip():
        raise PassportError("forge_memory.intent", "must be a non-empty string")
    else:
        resolved_intent = intent

    return Passport(
        version=PASSPORT_VERSION,
        intent=resolved_intent,
        update=PassportUpdate(
            strategy=strategy,
            mode=update_mode,
            writers=writers,
            shadow_path=shadow_path,
        ),
    )


# ---------------------------------------------------------------------------
# Writer validation
# ---------------------------------------------------------------------------


def validate_writer_spec(writer: str) -> None:
    """Validate a ``writers`` field value.

    Raises:
        PassportError: If the writer spec is not valid for v1.
    """
    if writer == "all-sessions":
        return

    if writer.startswith("lineage:"):
        raise PassportError(
            "forge_memory.update.writers",
            f"lineage-based writers not supported in v1 (got '{writer}')",
            hint="use 'all-sessions' or an exact session name",
        )

    if writer.startswith("role:"):
        raise PassportError(
            "forge_memory.update.writers",
            f"role-based writers not supported in v1 (got '{writer}')",
            hint="use 'all-sessions' or an exact session name",
        )

    if writer == "none":
        raise PassportError(
            "forge_memory.update.writers",
            "'none' is not a valid writer spec",
            hint="use 'forge memory passport remove' to remove the passport",
        )

    try:
        validate_name(writer)
    except InvalidSessionNameError as e:
        raise PassportError(
            "forge_memory.update.writers",
            f"invalid session name '{writer}': {e}",
            hint="use 'all-sessions' or a valid session name (lowercase alphanumeric + hyphens)",
        ) from e


def check_writer_access(writer_spec: str, session_name: str) -> bool:
    """Check if a session is authorized by the writer spec."""
    if writer_spec == "all-sessions":
        return True
    return writer_spec == session_name


# ---------------------------------------------------------------------------
# Flag-vs-passport conflict handling (Phase 2 infrastructure)
# ---------------------------------------------------------------------------


def resolve_with_overrides(
    passport: Passport,
    *,
    strategy: str | None = None,
    update_mode: str | None = None,
    shadow_path: str | None = None,
    writers: str | None = None,
) -> tuple[Passport, list[str]]:
    """Apply CLI-flag overrides to a deep copy of the passport.

    Flags win. Each override generates a warning message.

    Returns:
        ``(resolved_passport, warning_messages)``
    """
    resolved = deepcopy(passport)
    warnings: list[str] = []

    if strategy is not None and strategy != resolved.update.strategy:
        if strategy not in VALID_STRATEGY_NAMES:
            raise PassportError(
                "forge_memory.update.strategy",
                f"unknown strategy '{strategy}'",
                hint=f"valid strategies: {', '.join(sorted(VALID_STRATEGY_NAMES))}",
            )
        warnings.append(f"CLI --strategy {strategy} overrides passport strategy '{resolved.update.strategy}'")
        resolved.update.strategy = strategy

    if update_mode is not None and update_mode != resolved.update.mode:
        if update_mode not in VALID_PASSPORT_MODES:
            raise PassportError(
                "forge_memory.update.mode",
                f"unknown mode '{update_mode}'",
                hint=f"valid modes: {', '.join(sorted(VALID_PASSPORT_MODES))}",
            )
        warnings.append(f"CLI --mode {update_mode} overrides passport mode '{resolved.update.mode}'")
        resolved.update.mode = update_mode
        if update_mode == "direct" and resolved.update.shadow_path:
            warnings.append("CLI --mode direct ignores passport shadow_path " f"'{resolved.update.shadow_path}'")
            resolved.update.shadow_path = None

    if shadow_path is not None and shadow_path != resolved.update.shadow_path:
        old = resolved.update.shadow_path
        if old:
            warnings.append(f"CLI --shadow-path {shadow_path} overrides passport shadow_path '{old}'")
        resolved.update.shadow_path = shadow_path

    if writers is not None and writers != resolved.update.writers:
        validate_writer_spec(writers)
        warnings.append(f"CLI --writers {writers} overrides passport writers '{resolved.update.writers}'")
        resolved.update.writers = writers

    # Post-override invariant: shadow-only requires shadow_path
    if resolved.update.mode == "shadow-only" and not resolved.update.shadow_path:
        raise PassportError(
            "forge_memory.update.shadow_path",
            "required when mode is 'shadow-only'",
            hint="set --shadow-path or keep mode as 'direct'",
        )
    if resolved.update.mode == "direct" and resolved.update.shadow_path:
        raise PassportError(
            "forge_memory.update.shadow_path",
            "not allowed when mode is 'direct'",
            hint="set mode to 'shadow-only' to use a shadow path",
        )

    return resolved, warnings
