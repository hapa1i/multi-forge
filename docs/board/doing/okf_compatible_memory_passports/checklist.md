# Checklist: OKF-compatible memory passports

Execution plan for [card.md](card.md) on branch `okf-compatible-memory-passports`. The card's
[Acceptance Tests table](card.md#acceptance-tests) is the acceptance authority; each phase names the rows it advances,
and no row is complete until every operation in that row is green.

Resolved review decisions:

- compatibility is for newly tracked and explicitly upgraded Markdown docs, not every legacy doc or a formal bundle;
- envelope generation validates `type`, adds only `type`/`title`/`description`, and generates no
  tags/timestamp/resource;
- upgrade validates but never reconstructs the raw `forge_memory` mapping;
- frontmatter-rewriting operations (`write`, `remove`, `upgrade`) use strict root parsing while scanner/transfer reads
  stay permissive;
- new tracking/upgrade reject non-`.md`, `index.md`, and `log.md` before all direct or shadow side effects;
- scanner compatibility and title fallback use the logical project-relative path; resolved paths remain safety checks;
- every proposal validates its complete effective passport (and, for a new passport, its envelope) before materializing
  a shadow;
- passport writes preserve the existing file mode;
- representation normalization is outside the contract and tests never require it.

## Current focus

Reopened on 2026-07-15 — remediate the verified post-closeout findings, rerun affected gates, and close the card again.

## Phase 0: Characterization pins (no behavior change)

**Acceptance rows advanced**: AT-05, AT-07, AT-09, AT-11, AT-12, AT-13, AT-15, AT-16.

- [x] Hand-author a passport-only doc; prove `scan_passported_docs` returns it without outer OKF fields
  (`tests/src/session/test_project_memory.py`). Do not seed this fixture through a writer later taught to emit
  envelopes.
- [x] Prove an OKF-only doc (`type`, no `forge_memory`) and an OKF bundle `docs/index.md` are silently ignored by the
  scanner (`tests/src/session/test_project_memory.py`).
- [x] Prove valid outer fields do not weaken strict `forge_memory` validation (`tests/src/session/test_passport.py`).
- [x] Pin parsed-value preservation of custom outer values through `write_passport`; document comments, anchors,
  quoting, key order, scalar spelling, line endings, and timestamp spelling as out of contract without asserting their
  loss (`tests/src/session/test_passport.py`).
- [x] Characterize a real existing-passport update (changed strategy/writers and direct→propose) as a Forge-only rewrite
  before adding envelope behavior (`tests/src/cli/test_memory.py`).
- [x] Characterize non-mapping, leading-BOM, and EOF-delimiter third-party frontmatter through direct extraction, scans,
  and transfer parsing so Phase 1 cannot change results or add warning noise (`tests/src/session/test_passport.py`,
  `tests/src/session/test_project_memory.py`, `tests/src/session/test_transfer.py`).
- [x] Pin existing reserved and non-Markdown passport read/show/remove/re-track behavior and `.md`-only discovery
  (`tests/src/session/test_project_memory.py`, `tests/src/cli/test_memory.py`).

## Phase 1: Mutation-safe frontmatter and file modes

**Acceptance rows advanced**: AT-08, AT-09, AT-10, AT-18.

- [x] Add a mutation-specific mapping-frontmatter extractor. No delimiters and empty/comment-only frontmatter remain
  writable; mapping roots remain writable; list and scalar roots (string/int/bool/null/`~`) raise `PassportError` with a
  `frontmatter` field path.
- [x] Use a syntax-aware YAML node check so explicit null is not conflated with empty/comment-only frontmatter.
- [x] Detect leading-BOM frontmatter and a closing delimiter at EOF as unsupported delimiter-like inputs and fail
  byte-identically rather than treating them as absent frontmatter.
- [x] Route `write_passport`, `remove_passport`, and the later upgrade primitive through the strict mutation extractor;
  keep `extract_frontmatter` permissive for read/scanner/transfer callers.
- [x] Preserve removal of a mapping-root but schema-invalid `forge_memory` block; change only non-mapping-root removal
  from no-op to a clear, byte-identical failure.
- [x] Make every failed frontmatter-rewriting path byte-identical with no second frontmatter block.
- [x] Preserve the existing target mode through atomic passport write/remove operations; provide the same helper for
  upgrade.
- [x] Add regression files with file-level marks:
  - `tests/regression/test_bug_okf_nonmapping_frontmatter_double_block.py`
  - `tests/regression/test_bug_passport_atomic_write_mode.py`
  - both declare `pytestmark = pytest.mark.regression` and reproduce the old behavior before the fix.
- [x] Run focused unit and regression tests immediately after the slice; do not defer the new regression files to
  closeout.

## Phase 2: OKF envelope builder

**Acceptance rows advanced**: AT-03, AT-04, AT-05, AT-08, AT-14, AT-16.

- [x] Builder adds only missing `type` / `title` / `description`; never emits `resource`, `tags`, or `timestamp`.
- [x] Required `type` policy: generate when absent, preserve any non-empty string, fail byte-identically when present
  but null/non-string/empty/whitespace-only.
- [x] Exact title derivation: first non-empty CommonMark-style ATX H1 outside backtick/tilde fenced blocks (up to three
  leading spaces, one `#`, required following whitespace, optional closing hashes stripped); otherwise normalize the
  logical project-relative final stem by replacing `_`/`-` runs and collapsing whitespace without changing remaining
  character case. Omit generated title when the normalized stem is empty.
- [x] Description derives from parsed passport intent with whitespace collapsed to one ASCII space.
- [x] Existing optional outer values remain producer-owned and are never repaired or overwritten.
- [x] Add a side-effect-free reserved/Markdown path validator: the logical project-relative final component needs exact
  `.md`; its logical basename and the resolved target basename must not be `index.md`/`log.md`.
- [x] Unit-test exact output values, fenced fake headings, no-H1 fallback, multiline intent, invalid type matrix,
  acronym/mixed-case and separator-only stems, existing unknown type, unknown outer values, logical/resolved reserved
  names, and symlink suffix policy (`tests/src/session/test_passport.py`).

## Phase 3: `forge memory track` creation-only envelope

**Acceptance rows advanced**: AT-01, AT-02, AT-03, AT-07, AT-10, AT-13, AT-14, AT-16, AT-19.

- [x] Newly tracked direct doc receives the envelope and strict `forge_memory` in one atomic rewrite; successful CLI
  wiring is tested in `tests/src/cli/test_memory.py` (builder details remain in session unit tests).

- [x] Before every `_track_propose` shadow write, prepare and validate the complete effective passport; for a document
  without a passport, also prepare the complete envelope. An invalid writer/effective-passport combination on any flow,
  or a blank intent, invalid type, invalid Markdown suffix, or reserved path on new creation, leaves both the official
  document and shadow tree unchanged. Existing-passport flows still do not validate or migrate outer metadata.

- [x] Validate the raw `--intent` option before `synthesize_passport`: omission selects the strategy default, while
  explicit `""` and whitespace-only values fail before direct or proposal side effects.

- [x] New `--propose` writes the envelope/passport only on the official doc; auto-created shadow gets no frontmatter.

- [x] Existing passport paths bypass envelope generation. Test real changed strategy/writers and direct→propose updates,
  not only a no-op re-track.

- [x] Existing reserved/non-Markdown passports retain read/remove/re-track compatibility without being advertised as
  OKF-compatible; new tracking refuses those paths.

- [x] `remove_passport` continues to delete only `forge_memory`; outer metadata and file mode survive for both valid and
  schema-invalid passport values.

- [x] Update `docs/design_workflows.md` §§5.2/6.2 and `docs/end-user/memory.md` with the shipped track output, field
  ownership, invalid-type behavior, representation contract, and timestamp/tag deferral in this phase.

- [x] Replace the bundled QA `head -5 ... grep forge_memory` assertion with full-file semantic checks for non-empty
  type, `forge_memory`, and absent generated `resource`/`tags`/`timestamp`. Update the checklist version, machine
  test-count/last-updated headers, and human **Last updated** summary; derive and reconcile the count with the bundled
  `walkthrough-state.py ... index` command, then bump the version and set the date explicitly.

- [x] Update walkthrough §11.5 to inspect the envelope semantically rather than relying on key order. Update its
  version/test-count/last-updated headers: derive and reconcile the count with the bundled
  `walkthrough-state.py ... index` result, then bump the version and set the date explicitly.

- [x] Update `tests/src/review/test_skill_content.py` assertions for the new QA and walkthrough contracts.

- [x] Run the required targeted integration now:

  ```bash
  ./scripts/test-integration.sh tests/integration/cli/test_handoff_integration.py -v
  ```

  Add a case that runs real `forge memory track` in the container before the scan and memory-writer run, then assert the
  generated envelope remains discoverable and processable end to end.

## Phase 4: `forge memory passport upgrade <path>`

**Acceptance rows advanced**: AT-03, AT-05, AT-06, AT-08, AT-12, AT-14, AT-16, AT-17, AT-18.

- [x] Add an explicit leaf under `forge memory passport`; update group/root examples and the subgroup docstring to
  “inspect, upgrade, and remove.”
- [x] Apply the same Forge-root, safe-path, existence, and `enforce_target_project_compatibility` guards as existing
  project-owned memory mutations before reading or writing the target.
- [x] Require an existing valid `forge_memory` passport, exact `.md` suffix on the logical project-relative path, and
  non-reserved logical/resolved basenames.
- [x] Parse and validate `forge_memory` but mutate the raw frontmatter mapping. Test omitted optional fields and
  accepted legacy `inherit_on_fork` remain value-identical.
- [x] Add missing outer fields only. A complete envelope is an exit-0, byte-identical no-op; report added fields on
  stdout.
- [x] Invalid/missing passport, invalid type, unsafe/missing path, incompatible/malformed/newer project pin, non-mapping
  or unsupported BOM/EOF-delimiter frontmatter, reserved name, and non-Markdown path fail before modification.
- [x] Route recovery output through `forge.cli.output` on stderr; keep primary success/no-op results on stdout. No
  `--json` is required for this mutating leaf.
- [x] Add command/help/output tests in `tests/src/cli/test_memory.py` and include the command-tree invariant suite in
  `tests/src/cli/test_command_tree_invariants.py` in the focused verification.
- [x] Add a QA case that hand-authors a legacy passport, upgrades it twice, checks generated outer values and raw
  `forge_memory` preservation, and proves the second invocation byte-identical. Add a short guided upgrade example to
  walkthrough §11.5; recalculate both asset indexes and update `tests/src/review/test_skill_content.py`.
- [x] Update `docs/design_workflows.md` §5.7, `docs/cli_reference.md`, `docs/end-user/memory.md`, and
  `docs/board/README.md` with the new leaf and migration semantics in this phase.

## Phase 5: Architecture, packaging, and closeout sync

**Acceptance rows advanced**: all.

- [x] Update `docs/design.md` and `docs/design_appendix.md` with the outer-field ownership boundary or an explicit
  pointer to the normative workflow section, per the repository architecture/file-ownership rule.

- [x] Re-read every affected design/end-user/board/CLI/QA/walkthrough claim against shipped behavior; remove ordering or
  byte-preservation promises not enforced by tests.

- [x] Add a focused full-profile installer integration in `tests/integration/docker/test_installer.py` that installs the
  bundled extension and asserts the updated QA and walkthrough content. Run it before closeout:

  ```bash
  ./scripts/test-integration.sh tests/integration/docker/test_installer.py -k full_profile_memory_passport_assets -v
  ```

- [x] Run `make pre-commit` and `git diff --check` before producing the final artifacts. If either changes files, repeat
  the checks before building.

- [x] Because the QA/walkthrough assets under `src/skills/` are bundled extensions, run `uv build`, then verify the
  wheel and sdist separately. For each artifact, use a separate clean virtual environment, temporary `HOME`, and
  temporary local project; install from that artifact, run `forge extension enable --scope user --profile full`, and
  verify the installed `skills/qa` and `skills/walkthrough` resources. Run
  `forge extension enable --scope local --root <temp-project> --profile full`, then smoke-test
  `forge memory passport --help` and a real legacy-passport upgrade with the artifact-installed CLI.

- [x] Update card risks/decisions and the acceptance table if implementation evidence forces a contract change.

## Reopened remediation (2026-07-15)

Post-closeout review found two acceptance-breaking parser/path gaps, two reachable surface failures, and several bounded
hardening opportunities. The 2026-07-14 verification remains the baseline; the following items require fresh evidence.

- [ ] RF-01: make mutation frontmatter boundary selection agree with permissive reads without losing writable truly
  empty/comment-only frontmatter; cover the exact three-delimiter corruption shape across read/write/remove/upgrade.
- [ ] RF-02: compare logical and resolved reserved basenames case-insensitively while preserving the exact lowercase
  `.md` suffix rule; cover mixed-case direct/proposal/upgrade aliases on the Darwin development filesystem.
- [ ] RF-03: reject logical and resolved `index.md`/`log.md` custom shadow targets before official or shadow side
  effects, including mixed-case and symlink aliases.
- [ ] RF-04: make walkthrough §11.5 host-stdlib-only while retaining order-independent envelope, migration, raw
  passport, idempotence, and removal checks.
- [ ] RF-05: make `synthesize_passport` distinguish omitted intent from explicit blank/whitespace intent; keep the CLI
  preflight for failure before proposal side effects.
- [ ] RF-06: add opt-in preserve-existing-mode support to the shared atomic writer, migrate passport and Codex config
  rewrites to it, and consolidate passport render/apply tails without changing explicit `0600`/`0755` callers.
- [ ] RF-07: avoid preparing discarded passport rewrites on unchanged shadow-only re-track/propose flows; retain
  effective-passport validation before shadow materialization when values change.
- [ ] RF-08: bring the two card regression module docstrings into the documented bug-ID/root-cause/affected-file form.
- [ ] RF-09: rerun focused/full/regression/integration/pre-commit/build/artifact checks affected by remediation, update
  closeout records, and move the card back to `done/`.

Deferred from this remediation: extracting the non-identical track/show/upgrade/remove CLI preflight blocks. That
cleanup must preserve read-versus-mutation compatibility semantics and the upgrade leaf's deliberate recovery-output
contract, so it is tracked in
[`memory_passport_cli_preflight_cleanup`](../../proposed/memory_passport_cli_preflight_cleanup/card.md) rather than this
correctness patch.

## Deferred work (unchanged)

- `timestamp` ownership and maintenance across human/agent edits.
- Bundle declaration/conformance, bundle-root `okf_version`, generated `index.md`, and `log.md` maintenance.
- Round-trip YAML representation preservation for comments, anchors, quoting, ordering, scalar spelling, and line
  endings.
- Read/round-trip support for leading-BOM frontmatter and a closing delimiter at EOF; this card only guarantees
  byte-identical mutation refusal for those shapes.
- Any generated `resource` or `tags` policy.

## Original closeout baseline (2026-07-14; superseded as final evidence)

This evidence records the original implementation closeout. The reopened remediation requires the fresh RF-09 evidence
above before the card returns to `done/`.

- `make test-unit`: `7846 passed, 1 skipped, 117 deselected`.

- `make test-regression`: `507 passed`, including both new file-level regression cases.

- `./scripts/test-integration.sh tests/integration/cli/test_handoff_integration.py -v`: `10 passed`.

- `./scripts/test-integration.sh tests/integration/docker/test_installer.py -k full_profile_memory_passport_assets -v`:
  `1 passed, 17 deselected`.

- `make pre-commit` and `git diff --check`: clean after formatting normalization.

- `uv build`: wheel and sdist built successfully. Each artifact was reinstalled into its own isolated environment;
  full-profile user/local enable, packaged QA/walkthrough resources, the upgrade help surface, a real legacy upgrade,
  raw `inherit_on_fork` preservation, absent deferred fields, byte-identical second upgrade, and explicit empty-writer
  refusal were verified.

- Reusable mutation-boundary lessons were proposed in the gitignored `.forge/memory/shadow_impl_notes.md`; promotion to
  `docs/board/impl_notes.md` remains subject to human review.

- [x] Every AT-01…AT-19 row is implemented and green, with verification recorded before ticking.

- [x] Focused unit suites and CLI command-tree/output tests clean.

- [x] `make test-unit` clean.

- [x] `make test-regression` clean, including both new regression files.

- [x] Targeted memory integration clean with the exact Phase 3 command.

- [x] Targeted full-profile installer integration clean with the exact Phase 5 command.

- [x] `make pre-commit` and `git diff --check` clean on the final source tree.

- [x] Final `uv build` plus separate isolated wheel and sdist CLI/extension verification clean.

- [x] Compact completed-work entry in `docs/board/change_log.md`; durable lessons proposed for `impl_notes.md` through
  shadow review.

- [x] Card moved `doing/` → `done/`; inbound links repointed; design/end-user/board/QA docs verified against shipped
  behavior.
