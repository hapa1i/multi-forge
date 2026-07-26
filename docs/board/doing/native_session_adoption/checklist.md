# Checklist: Adopt native Claude Code / Codex sessions

**Card**: [card.md](card.md).

**Lane**: `doing/` -- accepted 2026-07-26 and moved `proposed/` -> `doing/` directly; the `todo/` parking step was
skipped because acceptance and activation happened in the same decision.

**Execution branch**: `feat/native-session-adoption`. No production code is written yet -- Slice 0 is the cursor, and
its first three items are owner decisions rather than implementation work.

**Slice numbering note**: the card uses "Phase 1 / Phase 2" for the **Claude** and **Codex arms**. This checklist uses
"Slice" numbering to avoid collision; the arm mapping is called out where it applies.

## Current focus

Slice 0. Three questions need answers before any code: two unproven card assumptions (P1, P2) and one the card predates
(P3). All three are load-bearing; none should be discovered during implementation.

## Re-grounding (2026-07-26)

The card's grounding was verified 2026-07-07; five feature merges have landed since. Re-checked against `main` today:
**every cited symbol still exists and the design remains sound**, but one mechanism relocated and several line anchors
drifted.

Unchanged: `_is_resumable_session` (`cli/session_lifecycle.py:168`), `_scan_manifests_for_uuid`
(`core/ops/session_context.py:405`), `find_session_by_uuid` (`session/index.py:491`), `get_transcript_path`
(`session/claude/paths.py:79`), `assert_codex_ready` (`core/runtime/codex_preflight.py:221`), `run_codex_resume`
(`cli/session_codex.py:237`), the three `codex_rollouts.py` seams (`:52`, `:89`, `:147`), and the `rollout_source`
docstring (`session/models.py:531`).

| Drifted anchor                     | Card cites                                   | Actual today                     |
| ---------------------------------- | -------------------------------------------- | -------------------------------- |
| `start_session` signature          | `session/manager.py:421`                     | `:411` (sets the UUID at `:637`) |
| `start_claude_session`             | `core/ops/claude_session.py:544`             | `:512`                           |
| `add_from_state`                   | `session/index.py:485`                       | `:448`                           |
| Stop artifact entry / UUID rewrite | `cli/hooks/commands.py:133-144` / `:146-158` | `:165-178` / `:179-180`          |
| `_reconnect_in_place`              | `cli/session_lifecycle.py:1658`              | `:1624`                          |
| `encode_project_path`              | `session/claude/paths.py:74`                 | `:47`                            |
| `claude_project_root` pre-seed     | `cli/session_fork.py:896`                    | `:554-558`                       |

**Relocated mechanism.** The card's "future resume model" risk cites the `ANTHROPIC_MODEL` env pin at
`core/ops/claude_session.py:1411-1416`. That file no longer contains the string. The pin moved to the leaf
`core/models/direct_model.py` (`apply_direct_model_env`, `DirectModelPin.env`) and is applied at
`core/ops/claude_session.py:1450` (direct branch) with a second branch `_apply_direct_model_env_if_supported` at `:1454`
that did not exist when the card was written. The **risk is unchanged and still real** -- the pin still reaches the
plain `--resume` reattach path -- but every citation must move to the leaf, and the proxy-supported branch needs a
deliberate answer for adopted sessions.

- [ ] Card anchors corrected in `card.md` (Design step 3, Risks "Future resume model", Grounding).

## Slice 0 -- Decisions and probes (no production code)

Blocking decisions (card "Open questions"):

- [ ] **Verb** `adopt` vs `import` ratified. Assertion: decision recorded in the card; the CLI leaf name is fixed before
  any op is written.
- [ ] **Discovery shape**: bare `adopt` previews vs an explicit `--list` flag. Assertion: one shape chosen, and the card
  states whether it follows the `session clean` preview-default precedent or deliberately departs from it.
- [ ] **Double-attach policy**: a concrete recent-mtime threshold **and** a warn-vs-block posture. Assertion: both a
  number and a posture are recorded; "warn when recent" alone is not a decision.

New probes (surfaced by the 2026-07-26 re-grounding, not in the card):

- [ ] **P1 -- Stop-rewrite idempotency (v1-blocking).** The whole binding survives the first Forge-managed Stop only if
  a plain `claude --resume <uuid>` reports the **same** `session_id` in its Stop payload; `cli/hooks/commands.py:179`
  rewrites `confirmed.claude_session_id` from that payload unconditionally. The card lists this as a risk but schedules
  no probe, and if the id ever differs the binding drifts after exactly one turn -- silently. Assertion: a real-Claude
  Docker gate (precedent: `test_native_relocate_contract.py`, `test_rewind_native_contract.py`) creates a conversation,
  reattaches by UUID, and asserts the Stop-payload `session_id` equals the original. Record the Claude version pinned,
  matching the `CLAUDE_VERSION_VALIDATED` convention.
- [ ] **P2 -- transcript model metadata (scope-affecting).** Card Design step 3 says the future-resume model can be
  inferred "from transcript metadata when present". Forge has **no** transcript-model extraction today:
  `core/transcript.py` exposes only role/turn primitives, and the sole `model` read in `src/` is the status line's proxy
  tier map. Assertion: either a named transcript field is confirmed to carry the model (and an extractor is scoped into
  Slice 2), or inference is dropped from v1 and `--model`-or-warn becomes the only path. Do not carry "infer when
  present" into implementation unproven.
- [ ] **P3 -- adopted session on the proxy branch.** Decide what an adopted (direct-mode) session does if a later resume
  supplies `--proxy`, given the new `_apply_direct_model_env_if_supported` branch. Assertion: behavior stated in the
  card; adoption records direct mode honestly and does not silently acquire a proxy model pin.

## Slice 1 -- Manifest provenance schema

- [ ] `confirmed.adoption` added as a strict dataclass field (`{source_runtime, adopted_at, source_path}`). Assertion:
  `SessionStore.read` round-trips it; a pre-adoption manifest without the field still reads (optional + defaulted); an
  ad hoc dict key is rejected by the strict reader.
- [ ] Provenance survives hook confirmation. Assertion: a simulated Stop leaves `confirmed.adoption` intact and
  `confirmed.claude_session_id` unchanged while `confirmed_by` becomes `hook:stop`.
- [ ] design.md §3.3/§3.5 sync: `claude_session_id` gains a third origination path (start **pre-seeds**, native fork
  **records**, adopt **binds**); `confirmed.adoption` documented as CLI-written. Assertion: §3.5 ownership text names
  adopt.

## Slice 2 -- Claude adopt op and CLI (card Phase 1)

- [ ] `core/ops/session_adopt.py` command-core op: pure logic, typed exceptions, no Click and no printing (§3.12).
  Assertion: no `click` import; the CLI leaf owns all rendering and exit codes.
- [ ] Preconditions fail-closed in the card's order: inside a Forge project; strict project-compatibility guard for a
  state-mutating command path; transcript exists; UUID not already bound. Assertion: each reject path creates **no**
  manifest, artifact, or index entry, and names the owning session when already bound.
- [ ] Recorded-`cwd` cross-check on the discovered transcript (the Claude analog of `_rollout_head_cwd`). Assertion: a
  lossy-encoding sibling's transcript (`a.b` / `a_b` / `a-b` collision) is rejected, not bound.
- [ ] Write ordering with partial-failure cleanup: validate -> manifest -> artifact copy -> index entry last. Assertion:
  an injected failure after the manifest write leaves no UUID-bound session and a re-run succeeds cleanly.
- [ ] Future-resume model made explicit per P2's outcome. Assertion: the persisted `direct_model` is inferred, supplied
  via `--model`, or warned-and-persisted -- never an unannounced default.
- [ ] Transcript artifact copy with reason `"adopt"`, matching the Stop entry shape (`cli/hooks/commands.py:165-178`),
  and a queued search-index marker. Assertion: the copy is indexed through the normal idempotent path, and **no**
  memory-writer handoff marker is enqueued at adopt time.
- [ ] CLI leaf under `forge session`, using `forge.cli.output` helpers. Assertion: recovery text goes through
  `print_error`/`print_tip`; no hand-rolled `Tip:` or `[red]Error:[/red]`.
- [ ] Reattach works with zero new resume code. Assertion: post-adopt `forge session resume <name>` builds argv
  `--resume <uuid>` with no `--fork-session`.

## Slice 3 -- Discovery preview

- [ ] Bare `forge session adopt` lists unbound candidates for the exact cwd, showing mtime, turn count, first-message
  snippet, and the exact directory scanned. Assertion: an already-bound UUID is excluded; a recorded-`cwd` mismatch is
  not listed.
- [ ] Subdirectory guidance. Assertion: running the preview at the Forge root when the conversation was launched from a
  subdirectory does not misattribute, and the diagnostic names the launch directory.
- [ ] Hook rule untouched. Assertion: the CWD scan exists only in the CLI; no hook gains a scan (design.md §3.10).

## Slice 4 -- Codex arm (card Phase 2)

- [ ] Thread-id lookup scans **all** matching rollouts rather than inheriting `find_rollout_path`'s newest-match
  behavior. Assertion: cwd mismatch, no match, and multiple-match-after-cwd-filter each reject with actionable
  diagnostics instead of silently choosing the newest.
- [ ] Fresh `assert_codex_ready()` preflight before any state is created.
- [ ] Manifest with `intent.launch.runtime="codex"` and `confirmed.codex` carrying `rollout_source="adopted"` as a new
  module-level constant. Assertion: `claude_session_id` and `confirmed.launch` stay unset; `context_delivery` stays
  `None`.
- [ ] `CodexConfirmed.rollout_source` docstring (`session/models.py:531`) gains **both** the missing
  `discovered_post_exit` and the new `adopted`, and `design_appendix.md` §I.1 gains `adopted`.
- [ ] Resume dispatch needs no new code. Assertion: `session_runtime(manifest) == "codex"` routes to `run_codex_resume`.

## Slice 5 -- Gates, docs, closeout

- [ ] Real-Claude adoption gate (slow, Docker): a bare-`claude` conversation created in-container is adopted and
  continued via `claude --resume <uuid>` from a manifest Forge never launched.
- [ ] Integration suites run, not deferred to closeout -- adoption touches session lifecycle, hooks, and the index, none
  of which unit tests exercise (`testing_guidelines.md`, "When to Run Integration Tests").
- [ ] `workspace_scope` identity-table line extended to "bound when launched **or adopted**"; the inbound link from that
  card still resolves.
- [ ] `cli_reference.md` session table gains the `adopt` leaf.
- [ ] Change-log entry with Goal / Key changes / Verification.
- [ ] Durable lessons proposed for `impl_notes.md` after human review (candidates: the encoded-dir lossiness cross-check
  as a binding precondition; P1's outcome as a pinned runtime contract).
- [ ] Card moved to `done/`, inbound board links repointed.

## Acceptance-test mapping

The card's "Acceptance tests" table is the authority for fixtures and assertions; this maps its rows to the slice that
proves them. New target file: `tests/src/cli/test_session_adopt.py`.

| Slice | Card test rows                                                                                                     |
| ----- | ------------------------------------------------------------------------------------------------------------------ |
| 1     | Adoption schema round trip; Provenance survives Stop                                                               |
| 2     | Adopt binds + reattach; Adopted model is explicit; Adopt queues search indexing; Adopt does not run memory writer; |
|       | Already-bound reject; Missing transcript reject; Outside Forge project reject; Project compatibility guard;        |
|       | Claude cwd cross-check reject; Partial-failure leaves no binding; Adopted transfer works                           |
| 3     | Discovery lists unbound only; Subdir exact-CWD guidance                                                            |
| 4     | Codex adopt binds; Codex rollout mismatch reject                                                                   |
| 5     | Real-Claude adoption gate                                                                                          |

## Verification commands

```bash
uv run pytest tests/src/cli/test_session_adopt.py tests/src/session/test_models.py -v
make test-unit
./scripts/test-integration.sh tests/integration/cli/test_hooks_integration.py -v
./scripts/test-integration.sh tests/integration/docker/test_native_adoption_contract.py -v
make pre-commit
```

## Deferred (card "Out of scope", restated so it is not re-litigated mid-slice)

Adopt-and-relocate into another worktree; backfilling plan snapshots or usage events; incognito and sidecar adoption;
passive SessionStart sighting (gated on `epic_global_forge_runtime`); any hook behavior change.
