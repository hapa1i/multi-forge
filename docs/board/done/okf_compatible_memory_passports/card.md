# OKF-compatible memory documents

**Status**: Done (`done/`) on 2026-07-15 after post-closeout remediation. The original implementation is `fae54345`, the
hardening commit is `58b7e97`, and fresh verification is recorded in [checklist.md](checklist.md).

**Origin**: The Open Knowledge Format (OKF) v0.1 draft at upstream commit `ee67a5ca27044ebe7c38385f5b6cffc2305a9c1a` in
`GoogleCloudPlatform/knowledge-catalog` is close to Forge's memory-doc shape: Markdown files with YAML frontmatter,
git-friendly structure, optional indexes/logs, and permissive consumer behavior. Forge already has passported Markdown
docs, but the passport is Forge-specific and is not recognizable as concept metadata to non-Forge catalog or agent
tooling.

## Goal

Make newly tracked and explicitly upgraded Forge Markdown memory docs structurally compatible with an OKF v0.1 concept
document by adding a small outer metadata envelope while keeping `forge_memory` as Forge's strict write-policy
extension.

This is **document-shape compatibility**, not a formal standalone or bundle-conformance claim. OKF defines conformance
for a bundle, and a concept's identity and absolute links are bundle-relative. Forge does not declare a bundle root or
rewrite every Markdown file in `docs/` or any other mixed tree.

For a document whose body begins `# Implementation Notes`, this command:

```bash
forge memory track docs/implementation_notes.md --strategy generic
```

generates the following frontmatter values. Serialization details, including key order, are not contractual.

```yaml
---
type: Memory Document
title: Implementation Notes
description: Project documentation
forge_memory:
  version: 1
  intent: Project documentation
  captures: []
  excludes: []
  update:
    strategy: generic
    mode: direct
    writers: all-sessions
---
```

This card deliberately does **not** generate `resource`, `tags`, or `timestamp`. Existing producer-authored values for
those fields remain untouched.

## Why

OKF provides a shallow interoperability profile without forcing a new storage system:

- concepts are UTF-8 Markdown files with YAML frontmatter;
- `type` is the only required concept frontmatter field and must be a non-empty string;
- `title`, `description`, `resource`, `tags`, and `timestamp` are optional;
- producer-defined keys are allowed, and consumers should preserve unknown values when round-tripping;
- `index.md` and `log.md` are reserved for directory discovery and update history.

This fits Forge's file-based, human-readable, agent-readable architecture while leaving Forge write safety under the
strict `forge_memory` namespace.

## Baseline Behavior (Verified Before Implementation)

Before this card, several required properties already held:

- `read_passport()` returns `None` unless a mapping frontmatter block contains `forge_memory`; an OKF-only doc is not a
  Forge memory doc.
- `scan_passported_docs()` skips `None` passports, so `index.md` or any other OKF-only Markdown file under `docs/` is
  ignored by the memory writer.
- `write_passport()` preserves non-`forge_memory` frontmatter at the parsed-value level, then re-dumps the entire block.
  Comments, anchors, quoting, key order, scalar spelling, and line endings are not a preservation contract.
- The permissive `extract_frontmatter()` treated a delimited non-mapping YAML root as if no frontmatter existed. A
  subsequent `write_passport()` could prepend a second block above the original. The corruption was in the mutation
  path; permissive reads also serve scanners and transfer parsing and should not acquire warning noise merely because an
  unrelated Markdown file uses non-mapping YAML.
- `yaml.safe_load` maps empty/comment-only frontmatter and explicit YAML null (`null` / `~`) to Python `None`; a strict
  mutation path must distinguish those syntax classes rather than checking only the loaded value.
- unquoted timestamps load as Python `datetime` values and may re-dump with different spelling. Forge therefore does not
  generate or maintain `timestamp` in this phase.
- `remove_passport()` deletes only `forge_memory` and preserves all outer frontmatter values.
- `forge memory track` accepted non-`.md` paths even though discovery scanned only `*.md`; envelope generation needed to
  close that misleading success path.
- Passport mutations called `atomic_write_text()` without the existing file mode. Because the helper replaces the target
  with a `mkstemp` file, a normal `0644` Markdown file could become `0600` after a successful passport mutation.

## Non-goals

- Do **not** replace `forge_memory` with plain OKF fields. OKF does not define writer permissions, update strategy,
  direct-vs-shadow mode, or captures/excludes constraints.
- Do **not** make Forge depend on Google Cloud Knowledge Catalog tooling.
- Do **not** require OKF metadata to read existing passports.
- Do **not** treat OKF as normative for Forge write safety.
- Do **not** declare or validate an OKF bundle, generate bundle-root metadata, or maintain `index.md` / `log.md`.
- Do **not** claim byte-level/comment-preserving YAML edits in this phase.
- Do **not** generate or maintain `timestamp`, `resource`, or `tags`.

## Design Decisions

### 1. Outer-field ownership and validation

- `forge_memory` remains the sole marker of Forge tracking and the authoritative write contract.
- Existing outer keys are producer-owned and preserved at the parsed-value level.
- Envelope generation treats `type` specially because it is required:
  - absent: generate `type: Memory Document`;
  - present non-empty string: preserve its parsed string value unchanged, including an unknown value;
  - present but null, non-string, empty, or whitespace-only: fail clearly before any write.
- Generate missing `title` and `description`; never overwrite a present value, even if that optional value is null or
  has an unexpected type.
- Do not generate tags. A strategy-derived tag would become stale after `forge_memory.update.strategy` changes, and a
  retained `forge` tag would blur the rule that active Forge ownership is expressed only by `forge_memory`.

### 2. Exact generated values

- `type` is exactly `Memory Document`.
- `title` is the first non-empty CommonMark-style ATX H1 outside backtick or tilde fenced code blocks: allow up to three
  leading spaces, require one opening `#` followed by whitespace, and strip optional closing `#` markers and surrounding
  whitespace. If no such H1 exists, derive it from the logical project-relative path's final stem by replacing runs of
  `_`/`-` with spaces and collapsing whitespace **without changing the remaining character case**. If that result is
  empty, omit the optional generated title.
- `description` is the parsed passport intent with all whitespace runs collapsed to one ASCII space.
- On new tracking, an omitted `--intent` keeps the strategy default; an explicitly empty or whitespace-only raw option
  fails before synthesis or any write. `synthesize_passport` independently preserves the same omitted-versus-blank
  distinction for non-CLI callers.

### 3. Operation semantics

- `forge memory track` on a document without a passport creates `forge_memory` and the envelope in one atomic rewrite.
  Existing valid outer values win; missing `type`/`title`/`description` are filled.
- Ordinary re-track of an existing passport never validates, repairs, or adds the OKF envelope. A no-flag re-track
  leaves the official document byte-identical while preserving existing shadow-materialization behavior; a real
  strategy/writer/mode/shadow change rewrites only the existing Forge passport behavior.
- `forge memory passport upgrade <path>` requires an existing valid passport and adds only missing envelope fields. It
  validates the raw `forge_memory` value but never serializes the parsed `Passport` back into the file. The raw
  `forge_memory` mapping must remain value-identical, including omitted optional fields and accepted legacy keys.
- Upgrade is idempotent: if nothing is missing, it performs no write and leaves the file byte-identical.
- `passport remove` continues to delete only `forge_memory`. Outer OKF metadata remains ordinary producer-owned
  metadata.
- Successful CLI output reports which fields were added; an already-complete upgrade is an exit-0 no-op. Diagnostics and
  recovery guidance go to stderr through `forge.cli.output`. The mutating leaf does not require `--json`.

### 4. Read posture versus mutation posture

- Keep the existing permissive `extract_frontmatter()` behavior for read/scanner/transfer callers.
- Add a mutation-specific mapping-frontmatter extractor used by `write_passport()`, `remove_passport()`, and upgrade:
  - no delimited frontmatter: valid, return no mapping plus the original body;
  - empty or comment-only frontmatter: valid empty mapping;
  - mapping root: valid mapping;
  - list or scalar root, including explicit YAML null: raise `PassportError` with a `frontmatter` field path.
- Use a syntax-aware YAML node check to distinguish explicit null from empty/comment-only frontmatter.
- When the permissive read parser recognizes frontmatter, mutation uses that same closing-delimiter span. The
  mutation-only zero-line fallback applies only when the read parser has no match, so genuinely empty frontmatter stays
  writable without letting a later read-visible passport survive beneath a rewritten empty block.
- Delimiter-like inputs that the current read parser does not recognize (a leading UTF-8 BOM or a closing delimiter at
  EOF) fail byte-identically instead of being treated as absent frontmatter. Broader read/round-trip support is
  deferred.
- A failed mutation is byte-identical and creates no second frontmatter block. Scanner and transfer read behavior
  remains unchanged and is characterized to prevent collateral warning changes.
- Removal validates only the outer frontmatter root, not the `forge_memory` schema, so a mapping with a schema-invalid
  passport remains removable. A non-mapping root now fails rather than reporting a successful no-op.
- Every successful passport mutation (`write`, `remove`, `upgrade`) preserves the target's existing filesystem mode
  through the shared atomic writer's explicit `preserve_existing_mode` option. Existing user-owned Codex config rewrites
  use the same option; missing targets retain the atomic writer's secure `0600` default, and explicit mode callers keep
  their existing `0600`/`0755` contracts.

### 5. Markdown and reserved-path rules

- New tracking and explicit upgrade require the logical Forge-relative path's final component to end exactly in `.md`,
  matching the scanner's `*.md` candidate glob. Resolution remains a separate containment/safety check.
- New tracking and upgrade compare logical and resolved official basenames case-insensitively against `index.md` and
  `log.md` before any official-doc or shadow write. Proposal shadows use the same basename-only guard, including custom
  git-tracked paths and symlink targets, while retaining their existing extension policy.
- The early check must run before `_track_propose()` can materialize a shadow.
- Existing Forge-only passports on reserved or legacy non-Markdown paths remain readable and removable. Ordinary
  re-track may update their Forge passport without generating an envelope; they are not advertised as OKF-compatible,
  and a logical path without a `.md` scan candidate remains undiscoverable. A logical `.md` symlink alias follows the
  scanner's candidate rule even when its resolved target has a different suffix.
- Upgrade uses the same Forge-root, safe-relative-path, existence, and project-compatibility guards as other
  project-owned memory mutations.

### 6. Timestamp and writer behavior

Forge has no authoritative way to maintain OKF's “last meaningful change” timestamp across later human and agent edits.
The memory writer gives an agent the whole file path and does not enforce a frontmatter-only/body-only edit boundary.
This card therefore neither generates nor refreshes `timestamp`; existing values are merely preserved under the
parsed-value contract.

Materialized shadow proposal files under `.forge/memory/` do not receive an envelope merely because Forge auto-created
them. `_track_propose` writes the passport and envelope on the official document; a shadow becomes a separate concept
only if a user explicitly tracks it later.

## Migration Shape

The implementation is additive for valid existing passports and explicit for legacy-envelope migration:

1. Pin current read/scanner/transfer behavior and existing passport strictness.
2. Add mutation-safe mapping extraction, byte-identical failure, and file-mode preservation.
3. Add the envelope builder with exact field derivation and invalid-`type` refusal.
4. Generate the envelope only when `forge memory track` creates a passport; preserve real existing-passport updates as
   non-migrating writes.
5. Add `forge memory passport upgrade <path>` as the explicit raw-frontmatter migration surface.
6. Preflight Markdown/reserved paths before any direct or shadow side effect.
7. Update normative design, CLI, end-user, board, QA, and walkthrough documentation with each shipped behavior slice.

There is no read-time or bulk auto-migration.

## Risks and Deferred Work

- **OKF remains draft v0.1.** The integration stays shallow and targets the pinned commit.
- **No bundle conformance.** Bundle-root/version metadata, inventory, reserved-file maintenance, cross-link validation,
  and generated indexes remain separate work.
- **Timestamp remains deferred.** Ownership and update timing require a separate design.
- **Representation preservation remains deferred.** Comments, anchors, quoting, key order, scalar spelling, and line
  endings may normalize on a successful write. Tests assert semantic values, not mandatory loss.
- **Some delimiter variants remain read-parser limitations.** Leading-BOM frontmatter and a closing delimiter at EOF are
  refused safely by mutation in this card; recognizing them on read and round-tripping them is separate work.
- **Legacy reserved/non-Markdown passports remain tolerated.** They are read/remove compatibility cases, not newly
  generated OKF documents.
- **Optional follow-up:** generate an OKF-style `index.md` for a deliberately declared bundle root. This requires a new
  bundle-level contract and is not implied by this card.

## Acceptance Tests

| ID    | Test                                     | Fixture                                                                                                                        | Assertion                                                                                                                                         | Test File                                                                                                                                                                                                                                  |
| ----- | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| AT-01 | New direct passport envelope             | body `# Foo`; `forge memory track docs/foo.md --strategy generic`                                                              | valid `type`, exact title/description, `forge_memory`; no generated resource/tags/timestamp                                                       | `tests/src/cli/test_memory.py`, `tests/src/session/test_passport.py`                                                                                                                                                                       |
| AT-02 | Proposal preflight and envelope          | valid new flow; explicit empty/whitespace intent at CLI/helper boundaries; invalid type/writer on new and existing flows       | valid official gets envelope/passport and shadow gets neither; invalid input changes neither official nor shadow tree                             | `tests/src/cli/test_memory.py`, `tests/src/session/test_passport.py`                                                                                                                                                                       |
| AT-03 | Required type policy                     | absent, valid unknown, null, empty, whitespace, bool, integer, list, mapping                                                   | absent generated; valid string preserved; every invalid present value fails byte-identically                                                      | `tests/src/session/test_passport.py`, `tests/src/cli/test_memory.py`                                                                                                                                                                       |
| AT-04 | Exact derivations                        | H1, fenced fake H1, closing hashes, multiline intent, casing-sensitive and separator-only no-H1 stems                          | exact parsed title/description values; no empty generated title                                                                                   | `tests/src/session/test_passport.py`                                                                                                                                                                                                       |
| AT-05 | Existing outer values preserved          | custom key plus existing type/title/description/tags/timestamp                                                                 | parsed values survive; comments/spelling/order are explicitly outside the assertion                                                               | `tests/src/session/test_passport.py`                                                                                                                                                                                                       |
| AT-06 | Upgrade is envelope-only and idempotent  | legacy passport omitting defaults and carrying `inherit_on_fork`                                                               | only missing outer fields added; raw `forge_memory` value unchanged; second invocation byte-identical                                             | `tests/src/cli/test_memory.py`                                                                                                                                                                                                             |
| AT-07 | Real re-track does not migrate           | legacy passport, then changed strategy/writers and direct→propose                                                              | requested Forge change lands while outer envelope remains absent                                                                                  | `tests/src/cli/test_memory.py`                                                                                                                                                                                                             |
| AT-08 | Unsafe frontmatter mutation fails safely | list/string/int/bool/null roots; BOM/EOF forms; empty controls; immediate empty delimiter before a later read-visible passport | operations reject unsupported shapes or mutate the read-selected block without duplication; empty controls remain writable                        | `tests/src/session/test_passport.py`, `tests/src/cli/test_memory.py`, `tests/regression/test_bug_okf_nonmapping_frontmatter_double_block.py`, `tests/regression/test_bug_passport_frontmatter_delimiter_selection.py`                      |
| AT-09 | Permissive read blast radius unchanged   | non-mapping, leading-BOM, and EOF-delimiter third-party docs plus transfer frontmatter                                         | existing extraction, silent-scan, and transfer best-effort result/warning contracts remain unchanged                                              | `tests/src/session/test_passport.py`, `tests/src/session/test_project_memory.py`, `tests/src/session/test_transfer.py`                                                                                                                     |
| AT-10 | Remove preserves outer metadata          | envelope plus valid or schema-invalid `forge_memory`                                                                           | remove deletes only `forge_memory`; outer values remain                                                                                           | `tests/src/session/test_passport.py`                                                                                                                                                                                                       |
| AT-11 | Existing passport-only docs still load   | only `forge_memory` frontmatter                                                                                                | scanner treats it as Forge memory without requiring outer fields                                                                                  | `tests/src/session/test_project_memory.py`                                                                                                                                                                                                 |
| AT-12 | Forge write policy remains strict        | valid outer fields plus bad `forge_memory.update.mode`                                                                         | read and upgrade fail with the existing strict validation; no outer fields are added                                                              | `tests/src/session/test_passport.py`, `tests/src/cli/test_memory.py`                                                                                                                                                                       |
| AT-13 | OKF-only docs are not Forge memory       | valid `type`, no `forge_memory`                                                                                                | scanner does not pass it to the memory writer                                                                                                     | `tests/src/session/test_project_memory.py`                                                                                                                                                                                                 |
| AT-14 | Reserved paths have no side effects      | exact/mixed-case logical or resolved `index.md`/`log.md` official and custom-shadow targets                                    | authoring fails before either write; scanners skip hand-authored reserved shadow targets; relevant files remain unchanged                         | `tests/src/cli/test_memory.py`, `tests/src/session/test_project_memory.py`, `tests/regression/test_bug_okf_reserved_memory_targets.py`                                                                                                     |
| AT-15 | Legacy reserved passports remain usable  | existing Forge-only `index.md`/`log.md` passport                                                                               | read/scan/re-track work without envelope generation; explicit upgrade still refuses                                                               | `tests/src/session/test_project_memory.py`, `tests/src/cli/test_memory.py`                                                                                                                                                                 |
| AT-16 | Markdown-only generation                 | new `.txt`/`.MD`, logical `.txt`→`.md` and `.md`→`.txt` symlink aliases, existing legacy `.txt` passport                       | logical `.txt` aliases refuse and logical `.md` aliases remain discoverable; legacy show/remove/re-track compatibility and `.md`-only scan remain | `tests/src/cli/test_memory.py`, `tests/src/session/test_project_memory.py`                                                                                                                                                                 |
| AT-17 | Upgrade mutator guards                   | outside-root/unsafe/missing path and incompatible/malformed/newer project pin                                                  | command exits non-zero before modification with actionable recovery                                                                               | `tests/src/cli/test_memory.py`                                                                                                                                                                                                             |
| AT-18 | Successful writes preserve file mode     | `0644` passport/Codex config rewrites; missing target; explicit secure/executable modes                                        | opt-in preserves existing mode; missing/default and explicit-mode contracts do not change                                                         | `tests/src/session/test_passport.py`, `tests/src/core/state/test_io.py`, `tests/src/install/test_codex_hooks.py`, `tests/regression/test_bug_passport_atomic_write_mode.py`, `tests/regression/test_bug_codex_config_atomic_write_mode.py` |
| AT-19 | Track→scan→writer integration            | container track of new doc followed by memory-writer run                                                                       | generated envelope remains scanner-compatible and the writer processes the document                                                               | `tests/integration/cli/test_handoff_integration.py`                                                                                                                                                                                        |

## References

- Pinned OKF v0.1 spec:
  `https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/ee67a5ca27044ebe7c38385f5b6cffc2305a9c1a/okf/SPEC.md`
- Current upstream OKF spec (informational only):
  `https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md`
- OKF repository: `https://github.com/GoogleCloudPlatform/knowledge-catalog`
- Forge memory design: `docs/design_workflows.md` sections 5 and 6
- Passport examples and dogfood setup: `docs/design_workflows.md` section 6.2 and `docs/board/README.md`
