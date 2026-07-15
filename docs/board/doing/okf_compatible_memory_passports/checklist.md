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

Phase 0 — characterization pins against unmodified production code.

## Phase 0: Characterization pins (no behavior change)

**Acceptance rows advanced**: AT-05, AT-07, AT-09, AT-11, AT-12, AT-13, AT-15, AT-16.

- [ ] Hand-author a passport-only doc; prove `scan_passported_docs` returns it without outer OKF fields
  (`tests/src/session/test_project_memory.py`). Do not seed this fixture through a writer later taught to emit
  envelopes.
- [ ] Prove an OKF-only doc (`type`, no `forge_memory`) and an OKF bundle `docs/index.md` are silently ignored by the
  scanner (`tests/src/session/test_project_memory.py`).
- [ ] Prove valid outer fields do not weaken strict `forge_memory` validation (`tests/src/session/test_passport.py`).
- [ ] Pin parsed-value preservation of custom outer values through `write_passport`; document comments, anchors,
  quoting, key order, scalar spelling, line endings, and timestamp spelling as out of contract without asserting their
  loss (`tests/src/session/test_passport.py`).
- [ ] Characterize a real existing-passport update (changed strategy/writers and direct→propose) as a Forge-only rewrite
  before adding envelope behavior (`tests/src/cli/test_memory.py`).
- [ ] Characterize non-mapping, leading-BOM, and EOF-delimiter third-party frontmatter through direct extraction, scans,
  and transfer parsing so Phase 1 cannot change results or add warning noise (`tests/src/session/test_passport.py`,
  `tests/src/session/test_project_memory.py`, `tests/src/session/test_transfer.py`).
- [ ] Pin existing reserved and non-Markdown passport read/show/remove/re-track behavior and `.md`-only discovery
  (`tests/src/session/test_project_memory.py`, `tests/src/cli/test_memory.py`).

## Phase 1: Mutation-safe frontmatter and file modes

**Acceptance rows advanced**: AT-08, AT-09, AT-10, AT-18.

- [ ] Add a mutation-specific mapping-frontmatter extractor. No delimiters and empty/comment-only frontmatter remain
  writable; mapping roots remain writable; list and scalar roots (string/int/bool/null/`~`) raise `PassportError` with a
  `frontmatter` field path.
- [ ] Use a syntax-aware YAML node check so explicit null is not conflated with empty/comment-only frontmatter.
- [ ] Detect leading-BOM frontmatter and a closing delimiter at EOF as unsupported delimiter-like inputs and fail
  byte-identically rather than treating them as absent frontmatter.
- [ ] Route `write_passport`, `remove_passport`, and the later upgrade primitive through the strict mutation extractor;
  keep `extract_frontmatter` permissive for read/scanner/transfer callers.
- [ ] Preserve removal of a mapping-root but schema-invalid `forge_memory` block; change only non-mapping-root removal
  from no-op to a clear, byte-identical failure.
- [ ] Make every failed frontmatter-rewriting path byte-identical with no second frontmatter block.
- [ ] Preserve the existing target mode through atomic passport write/remove operations; provide the same helper for
  upgrade.
- [ ] Add regression files with file-level marks:
  - `tests/regression/test_bug_okf_nonmapping_frontmatter_double_block.py`
  - `tests/regression/test_bug_passport_atomic_write_mode.py`
  - both declare `pytestmark = pytest.mark.regression` and reproduce the old behavior before the fix.
- [ ] Run focused unit and regression tests immediately after the slice; do not defer the new regression files to
  closeout.

## Phase 2: OKF envelope builder

**Acceptance rows advanced**: AT-03, AT-04, AT-05, AT-08, AT-14, AT-16.

- [ ] Builder adds only missing `type` / `title` / `description`; never emits `resource`, `tags`, or `timestamp`.
- [ ] Required `type` policy: generate when absent, preserve any non-empty string, fail byte-identically when present
  but null/non-string/empty/whitespace-only.
- [ ] Exact title derivation: first non-empty CommonMark-style ATX H1 outside backtick/tilde fenced blocks (up to three
  leading spaces, one `#`, required following whitespace, optional closing hashes stripped); otherwise normalize the
  logical project-relative final stem by replacing `_`/`-` runs and collapsing whitespace without changing remaining
  character case. Omit generated title when the normalized stem is empty.
- [ ] Description derives from parsed passport intent with whitespace collapsed to one ASCII space.
- [ ] Existing optional outer values remain producer-owned and are never repaired or overwritten.
- [ ] Add a side-effect-free reserved/Markdown path validator: the logical project-relative final component needs exact
  `.md`; its logical basename and the resolved target basename must not be `index.md`/`log.md`.
- [ ] Unit-test exact output values, fenced fake headings, no-H1 fallback, multiline intent, invalid type matrix,
  acronym/mixed-case and separator-only stems, existing unknown type, unknown outer values, logical/resolved reserved
  names, and symlink suffix policy (`tests/src/session/test_passport.py`).

## Phase 3: `forge memory track` creation-only envelope

**Acceptance rows advanced**: AT-01, AT-02, AT-03, AT-07, AT-10, AT-13, AT-14, AT-16, AT-19.

- [ ] Newly tracked direct doc receives the envelope and strict `forge_memory` in one atomic rewrite; successful CLI
  wiring is tested in `tests/src/cli/test_memory.py` (builder details remain in session unit tests).

- [ ] Before every `_track_propose` shadow write, prepare and validate the complete effective passport; for a document
  without a passport, also prepare the complete envelope. An invalid writer/effective-passport combination on any flow,
  or a blank intent, invalid type, invalid Markdown suffix, or reserved path on new creation, leaves both the official
  document and shadow tree unchanged. Existing-passport flows still do not validate or migrate outer metadata.

- [ ] Validate the raw `--intent` option before `synthesize_passport`: omission selects the strategy default, while
  explicit `""` and whitespace-only values fail before direct or proposal side effects.

- [ ] New `--propose` writes the envelope/passport only on the official doc; auto-created shadow gets no frontmatter.

- [ ] Existing passport paths bypass envelope generation. Test real changed strategy/writers and direct→propose updates,
  not only a no-op re-track.

- [ ] Existing reserved/non-Markdown passports retain read/remove/re-track compatibility without being advertised as
  OKF-compatible; new tracking refuses those paths.

- [ ] `remove_passport` continues to delete only `forge_memory`; outer metadata and file mode survive for both valid and
  schema-invalid passport values.

- [ ] Update `docs/design_workflows.md` §§5.2/6.2 and `docs/end-user/memory.md` with the shipped track output, field
  ownership, invalid-type behavior, representation contract, and timestamp/tag deferral in this phase.

- [ ] Replace the bundled QA `head -5 ... grep forge_memory` assertion with full-file semantic checks for non-empty
  type, `forge_memory`, and absent generated `resource`/`tags`/`timestamp`. Update the checklist version, machine
  test-count/last-updated headers, and human **Last updated** summary; derive and reconcile the count with the bundled
  `walkthrough-state.py ... index` command, then bump the version and set the date explicitly.

- [ ] Update walkthrough §11.5 to inspect the envelope semantically rather than relying on key order. Update its
  version/test-count/last-updated headers: derive and reconcile the count with the bundled
  `walkthrough-state.py ... index` result, then bump the version and set the date explicitly.

- [ ] Update `tests/src/review/test_skill_content.py` assertions for the new QA and walkthrough contracts.

- [ ] Run the required targeted integration now:

  ```bash
  ./scripts/test-integration.sh tests/integration/cli/test_handoff_integration.py -v
  ```

  Extend its existing track→scan→writer case to assert the envelope remains discoverable and processable.

## Phase 4: `forge memory passport upgrade <path>`

**Acceptance rows advanced**: AT-03, AT-05, AT-06, AT-08, AT-12, AT-14, AT-16, AT-17, AT-18.

- [ ] Add an explicit leaf under `forge memory passport`; update group/root examples and the subgroup docstring to
  “inspect, upgrade, and remove.”
- [ ] Apply the same Forge-root, safe-path, existence, and `enforce_target_project_compatibility` guards as existing
  project-owned memory mutations before reading or writing the target.
- [ ] Require an existing valid `forge_memory` passport, exact `.md` suffix on the logical project-relative path, and
  non-reserved logical/resolved basenames.
- [ ] Parse and validate `forge_memory` but mutate the raw frontmatter mapping. Test omitted optional fields and
  accepted legacy `inherit_on_fork` remain value-identical.
- [ ] Add missing outer fields only. A complete envelope is an exit-0, byte-identical no-op; report added fields on
  stdout.
- [ ] Invalid/missing passport, invalid type, unsafe/missing path, incompatible/malformed/newer project pin, non-mapping
  or unsupported BOM/EOF-delimiter frontmatter, reserved name, and non-Markdown path fail before modification.
- [ ] Route recovery output through `forge.cli.output` on stderr; keep primary success/no-op results on stdout. No
  `--json` is required for this mutating leaf.
- [ ] Add command/help/output tests in `tests/src/cli/test_memory.py` and include the command-tree invariant suite in
  `tests/src/cli/test_command_tree_invariants.py` in the focused verification.
- [ ] Add a QA case that hand-authors a legacy passport, upgrades it twice, checks generated outer values and raw
  `forge_memory` preservation, and proves the second invocation byte-identical. Add a short guided upgrade example to
  walkthrough §11.5; recalculate both asset indexes and update `tests/src/review/test_skill_content.py`.
- [ ] Update `docs/design_workflows.md` §5.7, `docs/cli_reference.md`, `docs/end-user/memory.md`, and
  `docs/board/README.md` with the new leaf and migration semantics in this phase.

## Phase 5: Architecture, packaging, and closeout sync

**Acceptance rows advanced**: all.

- [ ] Update `docs/design.md` and `docs/design_appendix.md` with the outer-field ownership boundary or an explicit
  pointer to the normative workflow section, per the repository architecture/file-ownership rule.

- [ ] Re-read every affected design/end-user/board/CLI/QA/walkthrough claim against shipped behavior; remove ordering or
  byte-preservation promises not enforced by tests.

- [ ] Add a focused full-profile installer integration in `tests/integration/docker/test_installer.py` that installs the
  bundled extension and asserts the updated QA and walkthrough content. Run it before closeout:

  ```bash
  ./scripts/test-integration.sh tests/integration/docker/test_installer.py -k full_profile_memory_passport_assets -v
  ```

- [ ] Run `make pre-commit` and `git diff --check` before producing the final artifacts. If either changes files, repeat
  the checks before building.

- [ ] Because the QA/walkthrough assets under `src/skills/` are bundled extensions, run `uv build`, then verify the
  wheel and sdist separately. For each artifact, use a separate clean virtual environment, temporary `HOME`, and
  temporary local project; install from that artifact, run `forge extension enable --scope user --profile full`, and
  verify the installed `skills/qa` and `skills/walkthrough` resources. Run
  `forge extension enable --scope local --root <temp-project> --profile full`, then smoke-test
  `forge memory passport --help` and a real legacy-passport upgrade with the artifact-installed CLI.

- [ ] Update card risks/decisions and the acceptance table if implementation evidence forces a contract change.

## Deferred work (unchanged)

- `timestamp` ownership and maintenance across human/agent edits.
- Bundle declaration/conformance, bundle-root `okf_version`, generated `index.md`, and `log.md` maintenance.
- Round-trip YAML representation preservation for comments, anchors, quoting, ordering, scalar spelling, and line
  endings.
- Read/round-trip support for leading-BOM frontmatter and a closing delimiter at EOF; this card only guarantees
  byte-identical mutation refusal for those shapes.
- Any generated `resource` or `tags` policy.

## Closeout

- [ ] Every AT-01…AT-19 row is implemented and green, with verification recorded before ticking.
- [ ] Focused unit suites and CLI command-tree/output tests clean.
- [ ] `make test-unit` clean.
- [ ] `make test-regression` clean, including both new regression files.
- [ ] Targeted memory integration clean with the exact Phase 3 command.
- [ ] Targeted full-profile installer integration clean with the exact Phase 5 command.
- [ ] `make pre-commit` and `git diff --check` clean on the final source tree.
- [ ] Final `uv build` plus separate isolated wheel and sdist CLI/extension verification clean.
- [ ] Compact completed-work entry in `docs/board/change_log.md`; durable lessons proposed for `impl_notes.md` through
  shadow review.
- [ ] Card moved `doing/` → `done/`; inbound links repointed; design/end-user/board/QA docs verified against shipped
  behavior.
