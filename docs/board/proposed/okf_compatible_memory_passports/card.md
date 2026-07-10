# OKF-compatible memory documents

**Status**: Proposed.

**Origin**: The Open Knowledge Format (OKF) v0.1 draft at upstream commit `ee67a5ca27044ebe7c38385f5b6cffc2305a9c1a` in
`GoogleCloudPlatform/knowledge-catalog` looks very close to Forge's memory-doc shape: a directory of Markdown files with
YAML frontmatter, git-friendly structure, optional indexes/logs, and permissive consumer behavior. Forge already has
passported Markdown docs as a concept, but the passport is Forge-specific and not recognizable to non-Forge catalog or
agent tooling.

## Goal

Make each Forge memory doc a valid OKF concept document by adding a small outer metadata envelope while keeping
`forge_memory` as Forge's strict write-policy extension.

This is **document-level compatibility**, not a claim that `docs/`, the repository, or any other mixed Markdown tree is
an OKF-conformant bundle. OKF bundle conformance requires every non-reserved Markdown file in the bundle to carry a
non-empty `type`; Forge does not own or rewrite every Markdown file in those trees.

The target shape:

```yaml
---
type: Memory Document
title: Implementation Notes
description: Human-approved durable implementation memory for future Forge sessions.
tags: [forge, memory, implementation-notes]

forge_memory:
  version: 1
  intent: "Human-approved durable implementation memory for future Forge sessions."
  captures: [stable decisions, non-obvious invariants, recurring bug causes]
  excludes: [raw session summaries, pending tasks, unverified hunches]
  update:
    strategy: generic
    mode: shadow-only
    writers: all-sessions
---
```

## Why

OKF gives individual Forge memory docs an interoperable, self-describing shape without forcing a new storage system:

- OKF concepts are Markdown files with YAML frontmatter.
- `type` is the only required frontmatter field for concept docs.
- `title`, `description`, `resource`, `tags`, and `timestamp` are recommended but optional.
- Additional producer-defined keys are allowed; consumers should preserve unknown keys and not reject the document
  because of them.
- `index.md` and `log.md` provide progressive-disclosure and update-history conventions that line up with Forge's
  existing memory and board habits.

This is a clean fit for Forge's "file-based, human-readable, agent-readable" architecture.

## Current Behavior (Verified)

The proposal is narrower than "teach the scanner about OKF." Several required properties already hold:

- `read_passport()` returns `None` unless the frontmatter contains `forge_memory`; an OKF-only doc is not a Forge memory
  doc.
- `scan_passported_docs()` skips `None` passports, so `index.md` or any other OKF-only Markdown file under `docs/` is
  ignored by the memory writer today.
- `write_passport()` already preserves non-`forge_memory` frontmatter keys at the **value** level, then re-dumps the
  whole frontmatter block.
- The preservation contract is **not byte-level** today: `yaml.safe_load` discards comments and coerces YAML scalars,
  then ruamel dumps a plain dict. A third-party OKF file with commented frontmatter will lose those comments if
  `forge memory track` rewrites the passport.
- Delimited frontmatter whose YAML root is not a mapping exposes a pre-existing write bug: `extract_frontmatter()`
  returns `(None, full_text)`, so `write_passport()` treats the document as having no frontmatter and prepends a second
  block above the original one. OKF upgrade increases exposure to third-party frontmatter, so Phase 1 fixes this in the
  shared parser/write path: a delimited non-mapping root fails clearly and leaves the file byte-identical.
- The current parser coerces unquoted ISO timestamps such as `2026-07-08T00:00:00Z` into Python `datetime` objects, and
  the writer re-dumps them as `2026-07-08 00:00:00+00:00`. Phase 1 therefore does not generate or maintain `timestamp`.
- `remove_passport()` currently deletes only the `forge_memory` key and preserves all other frontmatter. The proposal
  keeps that behavior: generated defaults are ordinary OKF metadata, while only `forge_memory` declares Forge tracking.

## Non-goals

- Do **not** replace `forge_memory` with plain OKF fields. OKF does not define writer permissions, update strategy,
  direct-vs-shadow mode, or captures/excludes constraints.
- Do **not** make Forge depend on Google Cloud Knowledge Catalog tooling.
- Do **not** make OKF conformance a hard requirement for reading existing passports.
- Do **not** treat OKF as normative for Forge write safety. The `forge_memory` block remains the authoritative write
  contract.

## Design Sketch

Adopt OKF as an outer metadata profile:

- `forge memory track` emits OKF-compatible frontmatter for new passports.
- Re-running `forge memory track` keeps its current semantics: it writes only when it creates a passport or changes the
  effective Forge passport. It does not double as a metadata migration command.
- `forge memory passport upgrade <path>` is the explicit path for adding missing OKF metadata to an existing legacy
  passport. OKF envelope generation is the leaf's only action, so it needs no format selector. The command is idempotent
  and does not rewrite already-complete metadata.
- Existing passport-only docs continue to load.
- `forge_memory` remains namespaced and strict:
  - unknown update strategies fail clear
  - unknown modes fail clear
  - invalid writer declarations fail clear
  - missing `forge_memory` means the file is not a Forge memory doc, even if it is OKF-compatible
- OKF outer fields are permissive:
  - missing `title`/`description`/`tags` does not block Forge
  - unknown non-Forge frontmatter keys are preserved at value level
  - existing OKF fields, including an unknown non-empty `type`, are user/producer-owned and are never overwritten merely
    because Forge tracks the document
- Use the generic generated type `Memory Document` when a newly tracked or explicitly upgraded document has no type.
  Forge ownership is represented only by the namespaced `forge_memory` block. Outer fields remain ordinary OKF metadata,
  so `passport remove` deletes only `forge_memory` and never has to infer whether Forge or a human authored `type`,
  `title`, `description`, or `tags`.
- Generate only missing outer fields. Derive `title` from the document heading or filename, `description` from passport
  intent, and tags from `forge`, `memory`, and the strategy. Do not refresh or replace existing values during track or
  upgrade.
- Do not emit `timestamp` in Phase 1. OKF defines it as the last meaningful document change, while passport writes do
  not observe later human edits and the memory writer currently changes bodies without rewriting frontmatter. Timestamp
  support requires a separate ownership/update design.
- Treat `index.md` and `log.md` as reserved for OKF-envelope generation. New tracking and explicit OKF upgrade of those
  basenames fail clearly rather than emitting concept frontmatter into a reserved document. Existing Forge-only
  passports on those names continue to load for backward compatibility but are not advertised as OKF-compatible.
- Materialized shadow proposal files under `.forge/memory/` should not receive OKF envelopes merely because they were
  auto-created. `_track_propose` writes the passport on the official doc; shadows are untracked runtime/proposal files
  unless a user explicitly tracks one as a separate memory doc.
- Optional follow-up: generate or maintain an OKF-style `index.md` for passported docs to support progressive disclosure
  before opening large memory files.

## Migration Shape

Phase 1 can be additive and low-risk:

1. Define the OKF envelope builder: add only missing `type`, `title`, `description`, and `tags`; preserve every existing
   outer value; never emit `timestamp`.
2. Pin value-level preservation as the Phase 1 contract. Comments, anchors, quoting, and scalar spelling may be
   normalized by a write. Byte-level/comment preservation would require moving extraction and mutation to a real ruamel
   round-trip representation and is separate work.
3. Make delimited frontmatter with a non-mapping YAML root a `PassportError` rather than “no frontmatter.” Pin that both
   track and upgrade fail without modifying the file; absence of frontmatter remains valid and writable.
4. Update `forge memory track` to add the envelope only when creating a new passport. Preserve its existing no-op and
   effective-change behavior for existing passports.
5. Add the explicit, idempotent upgrade command for existing passports:

```bash
forge memory passport upgrade docs/board/impl_notes.md
```

6. Reject new envelope generation for `index.md` and `log.md` with an actionable reserved-filename error.
7. Keep existing passport-only docs valid without an OKF envelope; these are regression pins, not scanner work.

Do not auto-rewrite all memory docs on ordinary reads; frontmatter churn should be explicit.

## Risks / Open Questions

- **OKF is draft v0.1.** Keep the integration shallow so future OKF changes do not force a Forge migration.
- **No bundle-conformance claim.** Forge emits valid concept-document metadata only. A separate feature would be needed
  to declare a bundle root, inventory every Markdown file, maintain reserved files, and validate bundle-wide
  conformance.
- **Timestamp deferred.** Unquoted YAML timestamps currently become Python `datetime` objects and re-dump differently,
  but formatting is secondary to ownership: Forge cannot honestly maintain last-meaningful-change metadata across human
  and memory-writer edits today.
- **Outer metadata ownership.** Existing outer fields are producer-owned and preserved. Forge supplies missing defaults
  but does not record ownership or remove them later; only `forge_memory` declares Forge tracking.
- **Reserved files.** OKF reserves both `index.md` and `log.md`. Phase 1 blocks new envelope generation for both while
  continuing to read any pre-existing Forge passport for backward compatibility.
- **Strictness split.** A parser bug here could make Forge too permissive about write controls. Tests must distinguish
  OKF-field tolerance from `forge_memory` strictness.
- **Comment preservation.** Current writes are not round-trip YAML edits; comments in outer frontmatter are lost. Either
  document value-level preservation as the contract or explicitly take on ruamel round-trip parsing.

## Acceptance Tests

| Test                                   | Status              | Fixture                                                      | Assertion                                                                                                  | Test File                                                            |
| -------------------------------------- | ------------------- | ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| New passport is OKF-compatible         | New                 | `forge memory track docs/foo.md`                             | frontmatter includes non-empty `type` plus `forge_memory`; recommended fields are populated when available | `tests/src/session/test_passport.py`                                 |
| Timestamp is not generated             | New                 | newly tracked doc                                            | generated envelope omits optional `timestamp`                                                              | `tests/src/session/test_passport.py`                                 |
| Explicit upgrade adds missing envelope | New                 | legacy passport, then `passport upgrade`                     | command adds only missing OKF fields and a second invocation is byte-identical                             | `tests/src/cli/test_memory.py`                                       |
| Re-track preserves current no-op       | New regression      | legacy passport plus unchanged `--strategy` or `--writers`   | track remains a no-op; it does not implicitly upgrade outer metadata                                       | `tests/src/cli/test_memory.py`                                       |
| Non-mapping frontmatter fails safely   | New regression      | delimited YAML list/scalar, then track and upgrade           | both commands fail clearly; file stays byte-identical and no second frontmatter block appears              | `tests/src/session/test_passport.py`, `tests/src/cli/test_memory.py` |
| Remove preserves outer metadata        | New                 | doc with `type: Memory Document` and `forge_memory`          | remove deletes only `forge_memory`; valid producer-owned OKF metadata remains                              | `tests/src/session/test_passport.py`                                 |
| Unknown OKF fields are value-preserved | Existing + expanded | doc with `type`, custom outer key, comment, and passport     | custom key/value round-trips; Phase 1 explicitly does not preserve comments or scalar spelling             | `tests/src/session/test_passport.py`                                 |
| Existing passport-only docs still load | Existing regression | doc with only `forge_memory` frontmatter                     | scanner treats it as a Forge memory doc without requiring OKF fields                                       | `tests/src/session/test_project_memory.py`                           |
| Forge write policy stays strict        | Existing regression | doc with valid OKF fields but bad `forge_memory.update.mode` | passport read fails with the existing clear validation error                                               | `tests/src/session/test_passport.py`                                 |
| OKF-only docs are not memory docs      | Existing regression | doc with `type` but no `forge_memory`                        | memory scanner does not pass it to the memory writer                                                       | `tests/src/session/test_project_memory.py`                           |
| Reserved OKF files cannot be enveloped | New                 | track or upgrade `docs/index.md` and `docs/log.md`           | command fails clearly without changing either file                                                         | `tests/src/cli/test_memory.py`                                       |
| Reserved index metadata is ignored     | Existing regression | `docs/index.md` with OKF bundle metadata, no `forge_memory`  | memory scanner does not treat it as a memory doc                                                           | `tests/src/session/test_project_memory.py`                           |

## References

- Target OKF v0.1 spec (pinned):
  `https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/ee67a5ca27044ebe7c38385f5b6cffc2305a9c1a/okf/SPEC.md`
- Current upstream OKF spec (informational only):
  `https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md`
- OKF repository: `https://github.com/GoogleCloudPlatform/knowledge-catalog`
- Forge memory design: `docs/design_workflows.md` section 5 and section 6
- Passport examples and dogfood setup: `docs/design_workflows.md` section 6.2 and `docs/board/README.md` project memory
  examples
