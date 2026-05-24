#!/usr/bin/env python3
"""Parse the walkthrough checklist into structured JSON with state tracking.

Provides deterministic bookkeeping so the agent never does arithmetic —
it only classifies (pass/fail/skip) while this script handles structure,
counting, and progress tracking.

This script is owned by the walkthrough skill. The QA skill carries a separate
physical copy so each skill can evolve its checklist/state behavior independently.

Usage (read-only):
    python3 walkthrough-state.py <checklist> index
    python3 walkthrough-state.py <checklist> step 6.3
    python3 walkthrough-state.py <checklist> summary

Usage (state management):
    python3 walkthrough-state.py <checklist> init <state-file> [--mode M] [--force]
    python3 walkthrough-state.py <checklist> record <state-file> <step_id> <results> [--force]
    python3 walkthrough-state.py <checklist> var <state-file> set <key> <value>
    python3 walkthrough-state.py <checklist> var <state-file> get <key>
    python3 walkthrough-state.py <checklist> prereq-check <state-file> <step_id|section_id>
    python3 walkthrough-state.py <checklist> report <state-file>
    python3 walkthrough-state.py <checklist> validate <state-file> --from <step_id>
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NotRequired, Optional, TypedDict

SECTION_RE = re.compile(r"^## (\S+?)\.?\s+(.+)")
SUBSECTION_RE = re.compile(r"^### (\S+)\s+(.+)")
ANNOTATION_RE = re.compile(r"^<!--\s*(.+?)\s*-->")
PREREQ_RE = re.compile(r"^<!--\s*prereq:\s*(.+?)\s*-->")
ASSERTION_RE = re.compile(r"^- \[ \]\s+(.+)")
VERSION_RE = re.compile(r"^<!--\s*version:\s*(.+?)\s*-->")
FENCE_RE = re.compile(r"^```(\w*)")

CHECKLIST_INDEX_RE = re.compile(r"^<!--\s*checklist:\s*index\s*-->")
INDEX_SECTION_RE = re.compile(r"^<!--\s*section:\s*(\S+)\s+(.+?)\s*-->")

RESULT_CODES = {"p": "pass", "f": "fail", "s": "skip"}
EXECUTION_ANNOTATIONS = {"auto", "human:confirm", "human:guided"}


class CodeBlock(TypedDict):
    code: str
    runnable: bool


class Subsection(TypedDict):
    id: str
    title: str
    section_id: Optional[str]
    section_title: Optional[str]
    annotations: list[str]
    annotation: Optional[str]
    instructions: str
    code_blocks: list[CodeBlock]
    assertions: list[str]
    prereqs: list[str]
    next: Optional[str]
    assertion_count: int
    # Transient flag during fence parsing; popped before the subsection is returned.
    _collecting_code: NotRequired[bool]


class Section(TypedDict):
    id: str
    title: str
    prereqs: list[str]
    subsections: list[Subsection]
    assertion_count: int


class Checklist(TypedDict):
    version: Optional[str]
    total_assertions: int
    sections: list[Section]
    _all_subs: list[Subsection]


def _primary_annotation(annotations: list[str]) -> str:
    """Return the execution annotation for a step, ignoring modifier annotations."""
    for annotation in annotations:
        if annotation in EXECUTION_ANNOTATIONS:
            return annotation
    return "human:confirm"


def _parse_index_entries(index_lines: list[str]) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for line in index_lines:
        m = INDEX_SECTION_RE.match(line)
        if not m:
            continue
        section_id = m.group(1)
        relpath = m.group(2).strip()
        entries.append((section_id, relpath))
    return entries


def _next_nonblank_line(lines: list[str], start: int) -> tuple[int | None, str | None]:
    for idx in range(start, len(lines)):
        if lines[idx].strip():
            return idx, lines[idx]
    return None, None


def _parse_checklist_lines(lines: list[str], *, extract_version: bool) -> Checklist:
    version: Optional[str] = None
    sections: list[Section] = []
    current_section: Optional[Section] = None
    current_sub: Optional[Subsection] = None
    all_subs: list[Subsection] = []
    # Prereqs seen outside a subsection body apply to the next ## heading.
    pending_prereqs: list[str] = []

    in_fence = False

    for line_idx, line in enumerate(lines):
        m = FENCE_RE.match(line)
        if m:
            if in_fence:
                in_fence = False
                continue
            in_fence = True
            if current_sub is not None:
                lang = m.group(1) or None
                current_sub["_collecting_code"] = True
                current_sub["code_blocks"].append({"code": "", "runnable": lang == "bash"})
            continue

        if in_fence:
            if current_sub is not None and current_sub.get("_collecting_code"):
                block = current_sub["code_blocks"][-1]
                if block["code"]:
                    block["code"] += "\n"
                block["code"] += line
            continue

        # Prereq annotations are subsection-level when placed in the annotation block
        # directly under a ### heading. Outside that block, they are only allowed
        # immediately before a ## heading (section-level).
        m = PREREQ_RE.match(line)
        if m:
            in_subsection_annotation_block = (
                current_sub is not None
                and not current_sub["instructions"]
                and not current_sub["code_blocks"]
                and not current_sub["assertions"]
            )
            if not in_subsection_annotation_block:
                _, next_line = _next_nonblank_line(lines, line_idx + 1)
                if next_line is not None and (PREREQ_RE.match(next_line) or SECTION_RE.match(next_line)):
                    pending_prereqs = list(
                        dict.fromkeys(pending_prereqs + [p.strip() for p in m.group(1).split(",") if p.strip()])
                    )
                    continue

                if current_sub is not None:
                    print(
                        f"Error: misplaced prereq annotation inside subsection body: {current_sub['id']}",
                        file=sys.stderr,
                    )
                    print(
                        "Place it immediately below the subsection heading for a step-level prereq, "
                        "or immediately above the next ## heading for a section-level prereq.",
                        file=sys.stderr,
                    )
                else:
                    print("Error: section-level prereq must appear immediately before a ## heading.", file=sys.stderr)
                sys.exit(1)

        if version is None:
            if extract_version:
                m = VERSION_RE.match(line)
                if m:
                    version = m.group(1).strip()
                    continue

        m = SECTION_RE.match(line)
        if m:
            current_section = {
                "id": m.group(1),
                "title": m.group(2).strip(),
                "prereqs": pending_prereqs,
                "subsections": [],
                "assertion_count": 0,
            }
            pending_prereqs = []
            sections.append(current_section)
            current_sub = None
            continue

        m = SUBSECTION_RE.match(line)
        if m:
            current_sub = {
                "id": m.group(1),
                "title": m.group(2).strip(),
                "section_id": current_section["id"] if current_section else None,
                "section_title": current_section["title"] if current_section else None,
                "annotations": [],
                "annotation": None,
                "instructions": "",
                "code_blocks": [],
                "assertions": [],
                "prereqs": [],
                "next": None,
                "assertion_count": 0,
            }
            if current_section is not None:
                current_section["subsections"].append(current_sub)
            all_subs.append(current_sub)
            continue

        if current_sub is None:
            continue

        m = ANNOTATION_RE.match(line)
        if m and not current_sub["code_blocks"] and not current_sub["assertions"]:
            current_sub["annotations"].append(m.group(1))
            continue

        m = ASSERTION_RE.match(line)
        if m:
            current_sub["assertions"].append(m.group(1))
            continue

        stripped = line.strip()
        if stripped:
            if current_sub["instructions"]:
                current_sub["instructions"] += "\n"
            current_sub["instructions"] += stripped

    for sub in all_subs:
        sub.pop("_collecting_code", None)
        # Extract prereq annotations into a dedicated field
        sub_prereqs: list[str] = []
        non_prereq_annotations: list[str] = []
        for ann in sub["annotations"]:
            pm = PREREQ_RE.match(f"<!-- {ann} -->")
            if pm:
                sub_prereqs.extend(p.strip() for p in pm.group(1).split(","))
            else:
                non_prereq_annotations.append(ann)
        sub["prereqs"] = sub_prereqs
        sub["annotations"] = non_prereq_annotations
        sub["annotation"] = _primary_annotation(non_prereq_annotations)

    for section in sections:
        section["assertion_count"] = sum(len(s["assertions"]) for s in section["subsections"])
        for sub in section["subsections"]:
            sub["assertion_count"] = len(sub["assertions"])

    total = sum(s["assertion_count"] for s in sections)

    return {
        "version": version,
        "total_assertions": total,
        "sections": sections,
        "_all_subs": all_subs,
    }


def _parse_index_checklist(index_path: Path, index_lines: list[str]) -> Checklist:
    version: Optional[str] = None
    for line in index_lines:
        if version is None:
            m = VERSION_RE.match(line)
            if m:
                version = m.group(1).strip()
                continue

    if version is None:
        print(f"Error: index checklist missing version: {index_path}", file=sys.stderr)
        print("Add: <!-- version: X.Y.Z -->", file=sys.stderr)
        sys.exit(1)

    entries = _parse_index_entries(index_lines)
    if not entries:
        print(f"Error: index checklist contains no section entries: {index_path}", file=sys.stderr)
        print("Add one or more: <!-- section: <id> <relative_path> -->", file=sys.stderr)
        sys.exit(1)

    seen_ids: set[str] = set()
    sections: list[Section] = []
    all_subs: list[Subsection] = []

    for section_id, relpath in entries:
        if section_id in seen_ids:
            print(f"Error: duplicate section id in index: {section_id}", file=sys.stderr)
            sys.exit(1)
        seen_ids.add(section_id)

        section_path = index_path.parent / relpath
        if not section_path.exists():
            print(f"Error: section file not found for section {section_id}: {section_path}", file=sys.stderr)
            sys.exit(1)

        parsed = _parse_checklist_lines(section_path.read_text().splitlines(), extract_version=False)
        if len(parsed["sections"]) != 1:
            print(
                f"Error: section file must contain exactly 1 section: {section_path}",
                file=sys.stderr,
            )
            print(f"  Found: {len(parsed['sections'])}", file=sys.stderr)
            sys.exit(1)

        section = parsed["sections"][0]
        if section["id"] != section_id:
            print(
                f"Error: section id mismatch in {section_path}\n"
                f"  Index expects: {section_id}\n"
                f"  File declares: {section['id']}",
                file=sys.stderr,
            )
            sys.exit(1)

        sections.append(section)
        all_subs.extend(parsed["_all_subs"])

    for i, sub in enumerate(all_subs):
        sub["next"] = all_subs[i + 1]["id"] if i + 1 < len(all_subs) else None

    for section in sections:
        section["assertion_count"] = sum(len(s["assertions"]) for s in section["subsections"])
        for sub in section["subsections"]:
            sub["assertion_count"] = len(sub["assertions"])

    total = sum(s["assertion_count"] for s in sections)

    return {
        "version": version,
        "total_assertions": total,
        "sections": sections,
        "_all_subs": all_subs,
    }


def parse_checklist(path: str) -> Checklist:
    """Parse a checklist markdown file (or checklist index) into structured data."""
    p = Path(path)
    lines = p.read_text().splitlines()
    if any(CHECKLIST_INDEX_RE.match(line) for line in lines):
        return _parse_index_checklist(p, lines)

    data = _parse_checklist_lines(lines, extract_version=True)
    for i, sub in enumerate(data["_all_subs"]):
        sub["next"] = data["_all_subs"][i + 1]["id"] if i + 1 < len(data["_all_subs"]) else None
    return data


# --- Read-only commands (no state file) ---


def cmd_index(data: Checklist) -> dict:
    """Full index with sections, subsections, annotations, assertion counts."""
    sections = []
    for s in data["sections"]:
        subs = []
        for sub in s["subsections"]:
            sub_entry: dict = {
                "id": sub["id"],
                "title": sub["title"],
                "annotation": sub["annotation"],
                "assertion_count": sub["assertion_count"],
            }
            if sub["prereqs"]:
                sub_entry["prereqs"] = sub["prereqs"]
            subs.append(sub_entry)
        sec_entry: dict = {
            "id": s["id"],
            "title": s["title"],
            "assertion_count": s["assertion_count"],
            "subsections": subs,
        }
        if s.get("prereqs"):
            sec_entry["prereqs"] = s["prereqs"]
        sections.append(sec_entry)
    return {
        "version": data["version"],
        "total_assertions": data["total_assertions"],
        "sections": sections,
    }


def cmd_step(data: Checklist, step_id: str) -> dict:
    """Single step details."""
    for sub in data["_all_subs"]:
        if sub["id"] == step_id:
            # Merge section-level and subsection-level prereqs
            section_prereqs: list[str] = []
            for s in data["sections"]:
                if s["id"] == sub["section_id"]:
                    section_prereqs = s.get("prereqs", [])
                    break
            merged_prereqs = list(dict.fromkeys(section_prereqs + sub.get("prereqs", [])))
            result: dict = {
                "id": sub["id"],
                "title": sub["title"],
                "section": f"{sub['section_id']}. {sub['section_title']}",
                "annotation": sub["annotation"],
                "annotations": sub["annotations"],
                "instructions": sub["instructions"],
                "code_blocks": sub["code_blocks"],
                "assertions": sub["assertions"],
                "assertion_count": len(sub["assertions"]),
                "next": sub["next"],
            }
            if merged_prereqs:
                result["prereqs"] = merged_prereqs
            return result
    print(f"Error: step '{step_id}' not found.", file=sys.stderr)
    sys.exit(1)


def cmd_summary(data: Checklist) -> dict:
    """Summary template with expected counts per section."""
    sections = []
    for s in data["sections"]:
        sections.append(
            {
                "id": s["id"],
                "title": s["title"],
                "expected": s["assertion_count"],
            }
        )
    return {
        "total_assertions": data["total_assertions"],
        "sections": sections,
    }


# --- State management commands ---


def checklist_hash(path: str) -> str:
    """SHA-256 hash of the checklist content (single file or index + section files)."""
    p = Path(path)
    lines = p.read_text().splitlines()

    h = hashlib.sha256()
    h.update(b"forge-checklist-hash-v1\n")

    if any(CHECKLIST_INDEX_RE.match(line) for line in lines):
        entries = _parse_index_entries(lines)
        if not entries:
            print(f"Error: index checklist contains no section entries: {p}", file=sys.stderr)
            sys.exit(1)

        seen_ids: set[str] = set()

        h.update(b"type:index\n")
        h.update(p.read_bytes())
        for section_id, relpath in entries:
            if section_id in seen_ids:
                print(f"Error: duplicate section id in index: {section_id}", file=sys.stderr)
                sys.exit(1)
            seen_ids.add(section_id)

            section_path = p.parent / relpath
            if not section_path.exists():
                print(f"Error: section file not found for section {section_id}: {section_path}", file=sys.stderr)
                sys.exit(1)

            h.update(b"\nsection\n")
            h.update(section_id.encode("utf-8") + b"\n")
            h.update(relpath.encode("utf-8") + b"\n")
            h.update(section_path.read_bytes())
    else:
        h.update(b"type:single\n")
        h.update(p.read_bytes())

    return f"sha256:{h.hexdigest()}"


def step_hash(step: Subsection) -> str:
    """Hash the structural content of a step that affects result validity.

    Includes: ID, title, annotation, assertion texts (normalized).
    Excludes: instructions, code blocks (presentation only).
    """
    h = hashlib.sha256()
    h.update(b"forge-step-hash-v1\n")
    h.update(step["id"].encode() + b"\n")
    h.update(step["title"].strip().encode() + b"\n")
    h.update((step.get("annotation") or "").encode() + b"\n")
    for a in step["assertions"]:
        h.update(a.strip().encode() + b"\n")
    return h.hexdigest()


def _migrate_v1_to_v2(state: dict, data: Checklist, checklist_path: str) -> dict:
    """Auto-migrate v1 state (global hash) to v2 (per-step hash).

    If the v1 global hash matches the current checklist, step hashes are
    computed with full confidence. If mismatched (checklist was edited since
    init), step hashes are set to null (unverified).
    """
    old_global = state.get("checklist_hash")
    current_global = checklist_hash(checklist_path) if old_global else None
    trust = old_global is not None and old_global == current_global

    for step_id, step_data in state.get("steps", {}).items():
        if "hash" in step_data:
            continue
        if trust:
            found = find_step(data, step_id)
            step_data["hash"] = step_hash(found) if found else None
        else:
            step_data["hash"] = None

    state.pop("checklist_hash", None)
    state["schema_version"] = 2
    return state


def read_state(path: str) -> dict:
    """Read and return state JSON. Fail-closed with actionable errors."""
    p = Path(path)
    if not p.exists():
        print(f"Error: state file not found: {path}", file=sys.stderr)
        print("Run 'init' first to create the state file.", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as e:
        print(f"Error: state file is corrupt: {path}", file=sys.stderr)
        print(f"  {e}", file=sys.stderr)
        print("Delete the file and run 'init' again.", file=sys.stderr)
        sys.exit(1)


def write_state(path: str, state: dict) -> None:
    """Atomic write: write to .tmp then os.replace."""
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    tmp = path + ".tmp"
    Path(tmp).write_text(json.dumps(state, indent=2) + "\n")
    os.replace(tmp, path)


def find_step(data: Checklist, step_id: str) -> Optional[Subsection]:
    """Find a subsection by ID."""
    for sub in data["_all_subs"]:
        if sub["id"] == step_id:
            return sub
    return None


def find_section(data: Checklist, section_id: str) -> Optional[Section]:
    """Find a section by ID."""
    for section in data["sections"]:
        if section["id"] == section_id:
            return section
    return None


def resolve_step_id(data: Checklist, raw_id: str) -> str:
    """Resolve a possibly section-level ID to a subsection ID.

    Accepts '3.1' (exact subsection), '3' (section -> first subsection),
    or '3.0' (section.0 shorthand -> first subsection).
    """
    # Exact subsection match
    if find_step(data, raw_id):
        return raw_id

    # Try section-level: '3' or '3.0' -> first subsection of section 3
    section_id = raw_id.rsplit(".0", 1)[0] if raw_id.endswith(".0") else raw_id
    section = find_section(data, section_id)
    if section and section.get("subsections"):
        return section["subsections"][0]["id"]

    return raw_id  # Return as-is; caller handles the error


def _current_run_scope(state: dict) -> Optional[str]:
    """Return the current run scope, if the caller recorded one."""
    return state.get("vars", {}).get("RUN_SCOPE")


def _section_status_keys(section_id: str) -> tuple[str, str]:
    return f"SECTION_{section_id}_STATUS", f"SECTION_{section_id}_SCOPE"


def _section_state(data: Checklist, state: dict, section_id: str, *, run_scope: Optional[str] = None) -> dict:
    """Classify a section using recorded step results in the current run scope."""
    section = find_section(data, section_id)
    if section is None:
        raise ValueError(f"Unknown section: {section_id}")

    missing_steps: list[str] = []
    stale_steps: list[str] = []
    has_failure = False
    has_non_skip = False
    has_recorded_steps = False

    for sub in section["subsections"]:
        step_data = state.get("steps", {}).get(sub["id"])
        if step_data is None:
            missing_steps.append(sub["id"])
            continue

        if run_scope is not None and step_data.get("scope") != run_scope:
            stale_steps.append(sub["id"])
            continue

        results = step_data["results"]
        has_recorded_steps = True
        if any(result != "skip" for result in results):
            has_non_skip = True
        if any(result == "fail" for result in results):
            has_failure = True

    if stale_steps:
        status = "stale_run"
    elif missing_steps:
        status = "not_run"
    elif has_failure:
        status = "failed"
    elif has_recorded_steps and not has_non_skip:
        status = "skipped"
    else:
        status = "passed"

    return {
        "status": status,
        "missing_steps": missing_steps,
        "stale_steps": stale_steps,
    }


def _refresh_section_status_vars(data: Checklist, state: dict) -> None:
    """Recompute derived SECTION_* vars from the currently valid step records."""
    vars_dict = state.setdefault("vars", {})
    for key in list(vars_dict):
        if key.startswith("SECTION_") and (key.endswith("_STATUS") or key.endswith("_SCOPE")):
            del vars_dict[key]

    run_scope = _current_run_scope(state)
    for section in data["sections"]:
        section_state = _section_state(data, state, section["id"], run_scope=run_scope)
        if section_state["status"] in {"passed", "failed"}:
            status_key, scope_key = _section_status_keys(section["id"])
            vars_dict[status_key] = section_state["status"]
            if run_scope is not None:
                vars_dict[scope_key] = run_scope


def cmd_init(data: Checklist, checklist_path: str, state_path: str, mode: str, force: bool) -> dict:
    """Create initial state file."""
    if Path(state_path).exists() and not force:
        print(f"Error: state file already exists: {state_path}", file=sys.stderr)
        print("Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    first_step = data["_all_subs"][0]["id"] if data["_all_subs"] else None
    total_steps = len(data["_all_subs"])

    state: dict[str, object] = {
        "schema_version": 2,
        "checklist_version": data["version"],
        "mode": mode,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "current_step": first_step,
        "vars": {},
        "steps": {},
    }

    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    write_state(state_path, state)

    return {
        "status": "initialized",
        "sections": len(data["sections"]),
        "steps": total_steps,
        "assertions": data["total_assertions"],
        "current_step": first_step,
    }


def cmd_record(
    data: Checklist, checklist_path: str, state_path: str, step_id: str, results_csv: str, force: bool
) -> dict:
    """Record assertion results for a step."""
    state = read_state(state_path)

    # Auto-migrate v1 state files
    if state.get("schema_version", 1) < 2:
        state = _migrate_v1_to_v2(state, data, checklist_path)

    # Find the step in the checklist
    step = find_step(data, step_id)
    if step is None:
        print(f"Error: step '{step_id}' not found in checklist.", file=sys.stderr)
        sys.exit(1)

    # Reject overwrite
    if step_id in state["steps"] and not force:
        print(f"Error: step '{step_id}' already recorded. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    # Parse and validate results
    codes = [c.strip() for c in results_csv.split(",")]
    expected_count = len(step["assertions"])
    if len(codes) != expected_count:
        print(
            f"Error: step '{step_id}' expects {expected_count} assertions, got {len(codes)} results.",
            file=sys.stderr,
        )
        sys.exit(1)

    results = []
    for c in codes:
        if c not in RESULT_CODES:
            print(f"Error: invalid result code '{c}'. Use p (pass), f (fail), s (skip).", file=sys.stderr)
            sys.exit(1)
        results.append(RESULT_CODES[c])

    # Update state with per-step hash and the current run scope (if any).
    step_entry = {"results": results, "hash": step_hash(step)}
    current_scope = _current_run_scope(state)
    if current_scope is not None:
        step_entry["scope"] = current_scope
    state["steps"][step_id] = step_entry
    state["current_step"] = step["next"]
    _refresh_section_status_vars(data, state)
    write_state(state_path, state)

    # Compute progress for output
    step_pass = sum(1 for r in results if r == "pass")
    step_total = len(results)

    # Section progress
    section_id = step["section_id"]
    section_expected = 0
    section_recorded = 0
    for s in data["sections"]:
        if s["id"] == section_id:
            section_expected = s["assertion_count"]
            for sub in s["subsections"]:
                if sub["id"] in state["steps"]:
                    section_recorded += len(state["steps"][sub["id"]]["results"])
            break

    # Overall progress (only count steps that exist in the current checklist)
    checklist_ids = {sub["id"] for sub in data["_all_subs"]}
    overall_recorded = sum(len(s["results"]) for sid, s in state["steps"].items() if sid in checklist_ids)
    overall_total = data["total_assertions"]

    return {
        "step": step_id,
        "step_results": f"{step_pass}/{step_total} pass",
        "section_progress": f"{section_recorded}/{section_expected}",
        "section_status": state["vars"].get(f"SECTION_{section_id}_STATUS"),
        "overall_progress": f"{overall_recorded}/{overall_total}",
    }


def cmd_var(state_path: str, action: str, key: str, value=None) -> dict:
    """Store or retrieve a variable in state."""
    state = read_state(state_path)

    if action == "set":
        if value is None:
            print("Error: 'var set' requires a value.", file=sys.stderr)
            sys.exit(1)
        state["vars"][key] = value
        write_state(state_path, state)
        return {"action": "set", "key": key, "value": value}

    elif action == "get":
        if key not in state["vars"]:
            return {"action": "get", "key": key, "exists": False}
        return {"action": "get", "key": key, "value": state["vars"][key], "exists": True}

    else:
        print(f"Error: unknown var action '{action}'. Use 'set' or 'get'.", file=sys.stderr)
        sys.exit(1)


def _step_prereq_status(state: dict, step_id: str, run_scope: Optional[str] = None) -> str:
    """Check if a single step was completed in the current run scope."""
    step_data = state.get("steps", {}).get(step_id)
    if step_data is None:
        return "not_run"
    if run_scope is not None and step_data.get("scope") != run_scope:
        return "stale_run"
    results = step_data.get("results", [])
    if any(result == "fail" for result in results):
        return "failed"
    if results and all(result == "skip" for result in results):
        return "skipped"
    return "passed"


def cmd_prereq_check(data: Checklist, state_path: str, step_id: str) -> dict:
    """Check prerequisites for a step. Returns ok/missing/statuses."""
    state = read_state(state_path)

    # Find the step and its section
    target_sub = None
    target_section = None
    for s in data["sections"]:
        for sub in s["subsections"]:
            if sub["id"] == step_id:
                target_sub = sub
                target_section = s
                break
        if target_sub:
            break

    if target_sub is None:
        # Try as a section ID (e.g., "5" -> check first subsection's prereqs)
        for s in data["sections"]:
            if s["id"] == step_id:
                target_section = s
                if s["subsections"]:
                    target_sub = s["subsections"][0]
                break

    if target_section is None:
        print(f"Error: step or section '{step_id}' not found.", file=sys.stderr)
        sys.exit(1)

    # Merge section + subsection prereqs
    section_prereqs = target_section.get("prereqs", [])
    sub_prereqs = target_sub.get("prereqs", []) if target_sub else []
    all_prereqs = list(dict.fromkeys(section_prereqs + sub_prereqs))

    if not all_prereqs:
        return {"ok": True, "required": [], "missing": [], "blocking": [], "resolvable": [], "statuses": {}}

    # Check each prereq against the current run scope.
    run_scope = _current_run_scope(state)
    statuses: dict[str, str] = {}
    missing: list[str] = []
    blocking: list[str] = []
    for prereq_id in all_prereqs:
        if "." in prereq_id:
            # Subsection-level prereq (e.g., "3.2"): check if step was recorded
            status = _step_prereq_status(state, prereq_id, run_scope)
        else:
            # Section-level prereq (e.g., "3"): check full section completion
            section_state = _section_state(data, state, prereq_id, run_scope=run_scope)
            status = section_state["status"]
        statuses[prereq_id] = status
        if status != "passed":
            blocking.append(prereq_id)
            if status == "not_run":
                missing.append(prereq_id)

    # For each missing step-level prereq, check if it's resolvable:
    # its section prereqs are all satisfied, so the agent can run it immediately.
    resolvable: list[str] = []
    for prereq_id in missing:
        if "." not in prereq_id:
            continue  # Section-level prereqs are too broad to auto-resolve
        # Find the section this prereq step belongs to
        prereq_step = find_step(data, prereq_id)
        if prereq_step is None:
            continue
        prereq_section_id = prereq_step["section_id"]
        if prereq_section_id is None:
            continue
        prereq_section = find_section(data, prereq_section_id)
        if prereq_section is None:
            continue
        # Check if the prereq step's section prereqs are all satisfied
        section_prereqs = prereq_section.get("prereqs", [])
        all_section_prereqs_ok = True
        for sp in section_prereqs:
            if "." in sp:
                sp_status = _step_prereq_status(state, sp, run_scope)
            else:
                sp_state = _section_state(data, state, sp, run_scope=run_scope)
                sp_status = sp_state["status"]
            if sp_status != "passed":
                all_section_prereqs_ok = False
                break
        if all_section_prereqs_ok:
            resolvable.append(prereq_id)

    return {
        "ok": len(blocking) == 0,
        "required": all_prereqs,
        "missing": missing,
        "blocking": blocking,
        "resolvable": resolvable,
        "statuses": statuses,
    }


def cmd_report(data: Checklist, checklist_path: str, state_path: str) -> dict:
    """Generate final summary by joining state with checklist structure."""
    state = read_state(state_path)

    # Auto-migrate v1 state files
    if state.get("schema_version", 1) < 2:
        state = _migrate_v1_to_v2(state, data, checklist_path)
        write_state(state_path, state)

    # Per-step hash validation (fail-open: warn, don't exit)
    changed_steps = []
    unverified_steps = []
    orphaned_steps = []

    checklist_step_ids = {sub["id"] for sub in data["_all_subs"]}
    for sid, sdata in state.get("steps", {}).items():
        if sid not in checklist_step_ids:
            orphaned_steps.append(sid)
            continue
        stored_hash = sdata.get("hash")
        if stored_hash is None:
            unverified_steps.append(sid)
            continue
        found = find_step(data, sid)
        if found and step_hash(found) != stored_hash:
            changed_steps.append({"id": sid, "reason": "step content changed since recorded"})

    sections = []
    total_pass = 0
    total_fail = 0
    total_skip = 0
    failures = []
    gaps = []

    for s in data["sections"]:
        s_pass = 0
        s_fail = 0
        s_skip = 0

        for sub in s["subsections"]:
            if sub["id"] not in state["steps"]:
                gaps.append(sub["id"])
                continue

            results = state["steps"][sub["id"]]["results"]
            for i, r in enumerate(results):
                if r == "pass":
                    s_pass += 1
                elif r == "fail":
                    s_fail += 1
                    failures.append(
                        {
                            "step": sub["id"],
                            "title": sub["title"],
                            "assertion_index": i,
                            "text": sub["assertions"][i] if i < len(sub["assertions"]) else "?",
                        }
                    )
                elif r == "skip":
                    s_skip += 1

        sections.append(
            {
                "id": s["id"],
                "title": s["title"],
                "expected": s["assertion_count"],
                "pass": s_pass,
                "fail": s_fail,
                "skip": s_skip,
            }
        )
        total_pass += s_pass
        total_fail += s_fail
        total_skip += s_skip

    result: dict[str, object] = {
        "total": {
            "expected": data["total_assertions"],
            "pass": total_pass,
            "fail": total_fail,
            "skip": total_skip,
        },
        "sections": sections,
        "failures": failures,
        "gaps": gaps,
        "complete": len(gaps) == 0,
    }

    # Attach warnings (agent decides how to present these)
    if changed_steps or unverified_steps or orphaned_steps:
        warnings: dict[str, object] = {}
        if changed_steps:
            warnings["changed_steps"] = changed_steps
        if unverified_steps:
            warnings["unverified_steps"] = unverified_steps
        if orphaned_steps:
            warnings["orphaned_steps"] = orphaned_steps
        result["warnings"] = warnings

    return result


def cmd_validate(data: Checklist, checklist_path: str, state_path: str, from_step: str) -> dict:
    """Pre-flight validation for resume. Checks hashes and clears stale future steps.

    Steps before from_step: validate stored hash vs current checklist.
    Steps at/after from_step: clear from state to prevent phantom progress.
    Returns JSON with changed_steps, unverified_steps, cleared_steps.
    """
    state = read_state(state_path)

    # Auto-migrate v1 state files
    if state.get("schema_version", 1) < 2:
        state = _migrate_v1_to_v2(state, data, checklist_path)

    # Resolve section-level IDs (e.g., '3' or '3.0' -> '3.1')
    from_step = resolve_step_id(data, from_step)

    # Build step order from checklist
    step_order = [sub["id"] for sub in data["_all_subs"]]
    try:
        from_index = step_order.index(from_step)
    except ValueError:
        print(f"Error: step '{from_step}' not found in checklist.", file=sys.stderr)
        sys.exit(1)

    before_steps = set(step_order[:from_index])
    at_or_after_steps = set(step_order[from_index:])

    changed_steps = []
    unverified_steps = []
    cleared_steps = []
    orphaned_steps = []

    all_checklist_ids = set(step_order)
    for sid, sdata in list(state.get("steps", {}).items()):
        # Orphaned steps (no longer in checklist): purge
        if sid not in all_checklist_ids:
            orphaned_steps.append(sid)
            del state["steps"][sid]
            continue

        # Steps at/after resume point: clear to prevent phantom progress
        if sid in at_or_after_steps:
            cleared_steps.append(sid)
            del state["steps"][sid]
            continue

        # Steps before resume point: validate hash
        if sid in before_steps:
            stored_hash = sdata.get("hash")
            if stored_hash is None:
                unverified_steps.append(sid)
                continue
            found = find_step(data, sid)
            if found and step_hash(found) != stored_hash:
                changed_steps.append({"id": sid, "reason": "step content changed since recorded"})

    # Update current_step to the resume point
    state["current_step"] = from_step
    _refresh_section_status_vars(data, state)
    write_state(state_path, state)

    status = "ok"
    if changed_steps or unverified_steps:
        status = "warnings"

    return {
        "status": status,
        "changed_steps": changed_steps,
        "unverified_steps": unverified_steps,
        "cleared_steps": cleared_steps,
        "orphaned_steps": orphaned_steps,
    }


# --- CLI dispatch ---

COMMANDS = ["index", "step", "summary", "init", "record", "var", "prereq-check", "report", "validate"]


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <checklist> <command> [args...]", file=sys.stderr)
        print(f"Commands: {', '.join(COMMANDS)}", file=sys.stderr)
        sys.exit(1)

    checklist_path = sys.argv[1]
    command = sys.argv[2]
    rest = sys.argv[3:]

    if command not in COMMANDS:
        print(f"Error: unknown command '{command}'. Valid: {', '.join(COMMANDS)}", file=sys.stderr)
        sys.exit(1)

    # Parse checklist (needed for all commands)
    data = parse_checklist(checklist_path)

    # Read-only commands
    if command == "index":
        result = cmd_index(data)

    elif command == "step":
        if not rest:
            print("Error: 'step' requires a step ID (e.g., 6.3)", file=sys.stderr)
            sys.exit(1)
        result = cmd_step(data, rest[0])

    elif command == "summary":
        result = cmd_summary(data)

    # State commands
    elif command == "init":
        force = "--force" in rest
        mode = "walkthrough"
        positional = []
        skip_next = False
        for i, arg in enumerate(rest):
            if skip_next:
                skip_next = False
                continue
            if arg == "--force":
                continue
            if arg == "--mode" and i + 1 < len(rest):
                mode = rest[i + 1]
                skip_next = True
                continue
            positional.append(arg)
        if not positional:
            print("Error: 'init' requires a state file path.", file=sys.stderr)
            sys.exit(1)
        state_path = positional[0]
        result = cmd_init(data, checklist_path, state_path, mode, force)

    elif command == "record":
        if len(rest) < 3:
            print("Error: 'record' requires <state-file> <step_id> <results>", file=sys.stderr)
            sys.exit(1)
        state_path, step_id, results_csv = rest[0], rest[1], rest[2]
        force = "--force" in rest
        result = cmd_record(data, checklist_path, state_path, step_id, results_csv, force)

    elif command == "var":
        if len(rest) < 3:
            print("Error: 'var' requires <state-file> set|get <key> [<value>]", file=sys.stderr)
            sys.exit(1)
        state_path, action, key = rest[0], rest[1], rest[2]
        value = rest[3] if len(rest) > 3 else None
        result = cmd_var(state_path, action, key, value)

    elif command == "prereq-check":
        if len(rest) < 2:
            print("Error: 'prereq-check' requires <state-file> <step_id|section_id>", file=sys.stderr)
            sys.exit(1)
        result = cmd_prereq_check(data, rest[0], rest[1])

    elif command == "report":
        if not rest:
            print("Error: 'report' requires a state file path.", file=sys.stderr)
            sys.exit(1)
        result = cmd_report(data, checklist_path, rest[0])

    elif command == "validate":
        from_step = None
        positional = []
        skip_next = False
        for i, arg in enumerate(rest):
            if skip_next:
                skip_next = False
                continue
            if arg == "--from" and i + 1 < len(rest):
                from_step = rest[i + 1]
                skip_next = True
                continue
            positional.append(arg)
        if not positional:
            print("Error: 'validate' requires a state file path.", file=sys.stderr)
            sys.exit(1)
        if not from_step:
            print("Error: 'validate' requires --from <step_id>.", file=sys.stderr)
            sys.exit(1)
        result = cmd_validate(data, checklist_path, positional[0], from_step)
    else:
        # Unreachable: command was validated against COMMANDS above.
        raise AssertionError(f"unhandled command: {command}")

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
