# Checklist: Adopt native Claude Code / Codex sessions

**Card**: [card.md](card.md).

**Lane**: `doing/` -- accepted 2026-07-26 and moved `proposed/` -> `doing/` directly; the `todo/` parking step was
skipped because acceptance and activation happened in the same decision.

**Execution branch**: `feat/native-session-adoption`. Slice 0 shipped one test file
(`tests/integration/docker/test_adopt_binding_contract.py`, the P1 gate) with no `src/` change. Slice 1 shipped the
first production change: `AdoptionConfirmed` in `src/forge/session/models.py`. No CLI surface exists yet -- Slice 2 adds
the op and leaf.

**Slice numbering note**: the card uses "Phase 1 / Phase 2" for the **Claude** and **Codex arms**. This checklist uses
"Slice" numbering to avoid collision; the arm mapping is called out where it applies.

## Current focus

**Slices 0 and 1 are closed.** Slice 0's three owner decisions and all three probes (P1 gated on real Claude 2.1.220,
P2, P3) are settled and recorded in the card. Slice 1 shipped `confirmed.AdoptionConfirmed` plus its hook-survival tests
and the design.md §3.5 ownership entry; §3.3's origination sentence is deliberately deferred to Slice 2, since it would
describe a command that does not exist yet. **Cursor: Slice 2** (the adopt op and CLI leaf) -- nothing blocks it.

## Re-grounding (2026-07-26)

The card's grounding was verified 2026-07-07; five feature merges have landed since. Re-checked against `main` today:
**every cited symbol still exists and the design remains sound**, but one mechanism relocated and several line anchors
drifted.

Unchanged: `_is_resumable_session` (`cli/session_lifecycle.py:168`), `_scan_manifests_for_uuid`
(`core/ops/session_context.py:405`), `find_session_by_uuid` (`session/index.py:491`), `get_transcript_path`
(`session/claude/paths.py:79`), `assert_codex_ready` (`core/runtime/codex_preflight.py:221`), `run_codex_resume`
(`cli/session_codex.py:237`), the three `codex_rollouts.py` seams (`:52`, `:89`, `:147`), and the `rollout_source`
docstring (`session/models.py:531`).

| Drifted anchor                     | Card cites                                   | Actual today                           |
| ---------------------------------- | -------------------------------------------- | -------------------------------------- |
| `start_session` signature          | `session/manager.py:421`                     | `:411` (param `:426`, UUID `:636-637`) |
| `start_claude_session`             | `core/ops/claude_session.py:544`             | `:512`                                 |
| `add_from_state`                   | `session/index.py:485`                       | `:448`                                 |
| Stop artifact entry / UUID rewrite | `cli/hooks/commands.py:133-144` / `:146-158` | `:166-177` / `:179`                    |
| `_reconnect_in_place`              | `cli/session_lifecycle.py:1658`              | `:1624`                                |
| `encode_project_path`              | `session/claude/paths.py:74`                 | `:47`                                  |
| `claude_project_root` pre-seed     | `cli/session_fork.py:896`                    | `:908-917`                             |

**Relocated mechanism.** The card's "future resume model" risk cites the `ANTHROPIC_MODEL` env pin at
`core/ops/claude_session.py:1411-1416`. That file no longer contains the string. The pin moved to the leaf
`core/models/direct_model.py` (`apply_direct_model_env` `:86`, `direct_model_env` `:79`, `DirectModelPin` `:23`) and is
applied at `core/ops/claude_session.py:1450` (direct branch) with a second branch `_apply_direct_model_env_if_supported`
(defined `session/model_pin.py:37`, applied at `core/ops/claude_session.py:1454`) that did not exist when the card was
written. The **risk is unchanged and still real** -- the pin still reaches the plain `--resume` reattach path -- but
every citation must move to the leaf, and the proxy-supported branch needs a deliberate answer for adopted sessions.

- [x] Card corrections applied to `card.md` (2026-07-26), so the active card stops presenting stale locations as current
  grounding. Verified: `grep -nE ':421|:620-621|:544|1411-1416|:1658|:896|146-158|133-144|:485|paths.py:74'` returns
  nothing. Three substantive changes beyond line numbers: (a) the `ANTHROPIC_MODEL` pin now cites
  `core/models/direct_model.py:86` with the proxy-branch sibling named as P3's subject; (b) the "Write ordering
  (fail-closed atomicity)" paragraph no longer specifies an index-last sequence `start_session` cannot produce -- it
  delegates to the existing compensation block (`session/manager.py:666-681`) and states the observable guarantee
  instead; (c) the partial-failure acceptance row now names two constructible fixtures rather than an unreachable seam.
  A **fourth** correction landed in the table above: `cli/session_fork.py:554-558` is a *read* of `claude_project_root`,
  not the pre-seed; the actual pre-seed is `:908-917`.

## Slice 0 -- Decisions and probes (no production code)

Blocking decisions (card "Open questions") -- **all three settled 2026-07-26 and recorded in the card**:

- [x] **Verb**: **`adopt`**. Lifecycle-verb family; `import` rejected for its file-format connotation. Leaf name fixed
  before any op is written.
- [x] **Discovery shape**: **bare `adopt` previews**, no `--list` flag. The card states this **follows** the
  preview-default precedent and the leaf-does-the-sensible-action rule, rather than departing from it.
- [x] **Double-attach policy**: **warn + require confirmation** when transcript mtime is within **30 minutes**,
  skippable with `--yes` -- both a number and a posture. Not a block, because Forge is inferring liveness rather than
  observing it; the Codex-resume no-`--force` posture is explicitly not mirrored.

New probes (surfaced by the 2026-07-26 re-grounding, not in the card):

- [x] **P1 -- Stop-rewrite idempotency. ANSWERED on real Claude 2.1.220: the reattach reports the same `session_id`, so
  the Stop rewrite is idempotent and adoption's binding is safe.** The binding survives the first Forge-managed Stop
  only if a plain `claude --resume <uuid>` reports the **same** `session_id`; `cli/hooks/commands.py:179` rewrites
  `confirmed.claude_session_id` from that payload unconditionally, so a differing id would drift the binding after one
  turn, silently. Local evidence could not answer it -- every multi-capture session sampled had `resume_mode: None`, so
  no on-disk sample observes a reattach at all. Gate: `tests/integration/docker/test_adopt_binding_contract.py`
  (`integration` + `docker_in` + `slow`), `CLAUDE_VERSION_VALIDATED = "2.1.220"`. See "P1 gate result" below.
- [x] **P2 -- transcript model metadata (scope-affecting). ANSWERED: inference is viable; keep it in v1.** Over the
  **full** intended population (470 top-level transcripts, the feature's own scan shape), `message.model` is present on
  **15870/15870** assistant entries with real canonical ids (`claude-opus-5`, `claude-fable-5`, `claude-opus-4-8`).
  Scope the extractor into Slice 2 with three measured edge cases (see "Probe results"): filter the `<synthetic>`
  sentinel; tolerate transcripts with no assistant turn (**346/470**, so the no-basis path is the ordinary one and
  inference the optimization -- P3 settles that path as warn-and-leave-`None`, not warn-and-persist); and take the
  **last** real model as a required deterministic tie-break -- 2/470 do mix two real models, so a mixed-model fixture is
  mandatory.
- [x] **P3 -- adopted session on the proxy branch. ANSWERED: adoption writes `direct_model` only when it has a basis**
  (explicit `--model` or transcript inference); with neither it warns and leaves the field `None` rather than persisting
  the current direct default. Recorded in card Design step 3. Two code facts decide it: the direct branch already
  evaluates `direct_model or get_default_direct_model()` at launch (`core/ops/claude_session.py:1448-1449`), so
  persisting the default changes nothing on the direct path; and the proxy branch
  (`_apply_direct_model_env_if_supported`, applied `:1454`) reads the **stored** `intent.launch.direct_model` while the
  resume-path validation gate fires only for a pin passed on that invocation (`cli/session_lifecycle.py:1375`,
  `if direct_model_pin`) -- so a fabricated default would reach the proxy unvalidated and silently no-op
  (`session/model_pin.py:61-62`) instead of erroring. When a basis exists the pin behaves as it does for any Forge-born
  `--model` session; the silent-skip asymmetry is pre-existing and explicitly not fixed here. New acceptance row:
  "Adoption adds no model pin" -- worded around what adoption **contributes**, since `build_claude_env` starts from the
  current process environment (`core/reactive/env.py:210`) and an ambient `ANTHROPIC_MODEL` reaches Claude regardless of
  the manifest.

### P1 gate result (2026-07-26, Claude Code 2.1.220)

`tests/integration/docker/test_adopt_binding_contract.py` -- one test, 1 passed in ~27s, two real `claude --print` turns
per run.

**Observable.** Not `confirmed.claude_session_id`, which both SessionStart and Stop write (a match there would not say
which hook produced it). The Stop handler copies the payload's `session_id` verbatim into each artifact entry
(`cli/hooks/commands.py:169`) and `_append_artifact_entry` (`cli/hooks/_helpers.py:131-149`) appends without dedup, so
`confirmed.artifacts.transcripts` is an **append-only log of every Stop payload**. Claude re-invokes Stop as a
transcript grows (`commands.py:541-544`), so the gate asserts *every* recorded id matches, not a fixed entry count.

Entries are filtered to `reason in {"stop", "stop-failure"}` -- the two written by `_capture_transcript_artifact`
(`:550`, `:755`), which are exactly the paths that also rewrite the binding at `:179`. The filter is load-bearing, not
tidiness: `reason="pre-compact"` (`:875`) shares this same artifact list but **omits `session_id`**, so an unfiltered
read would surface a `None` and fail the drift check spuriously the first time a compaction fired mid-gate. An assertion
requires the filtered list to be non-empty so the filter cannot silently empty out.

| Point                           | Recorded Stop payload ids              |
| ------------------------------- | -------------------------------------- |
| after turn 1 (fresh)            | `['470b1a1b-...f2']`                   |
| after turn 2 (plain `--resume`) | `['470b1a1b-...f2', '470b1a1b-...f2']` |

The reattach turn produced a **new** Stop entry carrying the original id -- the gate is not vacuous, and an assertion
requires the entry count to grow so it cannot become vacuous later. Two corroborations: exactly one UUID-named artifact
file exists (a drifted id would create a second), and the captured transcript contains **both** prompts, proving the
reattach continued the conversation rather than starting fresh under the same id -- without which a matching
`session_id` would prove nothing.

**Consequence for Slice 2.** Adoption may rely on Stop idempotency; no drift guard is needed. The
`CLAUDE_VERSION_VALIDATED = "2.1.220"` marker is reported on failure rather than hard-asserted, so a routine CLI bump
does not red the suite while a real identity regression still fails on the payload assertions.

### Probe results (2026-07-26)

Method: read-only inspection of local evidence. Population is the **470** files matching `~/.claude/projects/*/*.jsonl`
-- the feature's own top-level scan shape (card Discovery). A recursive `find` reports 1,029, but the extra 559 are
`<uuid>/subagents/agent-*.jsonl` subagent logs that adoption never scans; an earlier draft of this section quoted that
1,029 figure in error. P2 was re-run over the full 470. P1's axes used path-ordered slices (not time-ordered). Only
entry keys, ids, and model strings were read -- never message content. No LLM calls, no Docker, no spend.

**P1 -- zero counterexamples, but none of it observes a reattach:**

| Axis                                   | Sample          | Result                                         | Bears on the contract?          |
| -------------------------------------- | --------------- | ---------------------------------------------- | ------------------------------- |
| Filename stem vs embedded `sessionId`  | 250 transcripts | 250 match, 0 mismatch, 0 files with >1 id      | structural only                 |
| Forge `stop` captures vs manifest uuid | 45 captures     | 45 match, 0 mismatch                           | weak -- see below               |
| One id spanning a long wall-clock gap  | 300 transcripts | 16 files, gaps up to 18.3h, still exactly 1 id | circumstantial                  |
| `pre-compact` mutating the binding     | code read       | never mutates it                               | removes a hazard, proves no leg |

Axis 2 is weaker than it first appears. The Stop handler writes the artifact's `session_id` and the manifest binding
from the **same payload value in one mutation** (`cli/hooks/commands.py:169` and `:179`), so the comparison is close to
self-referential. It retains some force -- the artifact list is append-only while the binding is last-write, so an id
that changed between captures would leave two distinct ids in one session's history, and none did -- but that
establishes stability across Stop events **within** a session, not across a reattach. Every multi-capture session
sampled had `resume_mode: None`.

Axis 4 corrects an earlier misreading in this checklist. `pre-compact` does **not** write a null `session_id`: the
handler exits when the payload lacks one (`:835`), and its artifact entry **omits the key entirely** (`:870`, which also
uses `snapshot_path` where `stop` uses `copied_path`). The earlier "null" reading came from a probe using
`.get("session_id")`, which cannot distinguish an absent key from a null value. The correct invariant is simply
**pre-compact never mutates the binding**; `_capture_transcript_artifact` (`:124`) is reached only from `stop` (`:544`)
and `stop-failure` (`:749`). Slice 1 still asserts it, because the Stop rewrite has no falsy guard and a future refactor
that unified the two capture paths could introduce one.

Slice 1 refined this further: pre-compact leaves `claude_session_id` alone but **does** stamp
`confirmed_by="hook:pre-compact"` (`:891`) -- found by a wrong assertion that expected `cli:adopt` to survive. So
`confirmed_by` has at least **three** writers. That turns "provenance needs its own field" from an argument into a
demonstrated fact, and it is now the reason recorded in design.md §3.5.

**P2 -- `message.model` coverage:**

| Measure                                       | Result (full 470) |
| --------------------------------------------- | ----------------- |
| assistant entries carrying `message.model`    | 15870 / 15870     |
| transcripts with exactly one real model       | 109 of 470        |
| transcripts with no assistant turn at all     | 346 of 470 (74%)  |
| transcripts with only the `<synthetic>` value | 13 of 470         |
| transcripts mixing two real model ids         | **2 of 470**      |

Two rows drive Slice 2's design. The no-assistant-turn row resizes card Design step 3: such a transcript cannot yield a
model, and it is the **majority** case, so the no-basis path is the ordinary one and inference is the optimization -- P3
then settles what that path does (warn, leave `direct_model` unset). The mixed-model row reverses an earlier claim in
this checklist that no tie-break was needed -- that came from a 120-file sample which happened to contain none. Both
real cases are `claude-fable-5 -> claude-opus-4-8`, so "take the **last** real model" is a required deterministic rule
with a mandatory fixture, not a defensive nicety. `<synthetic>` is a sentinel, not a model id, and must be filtered
before it reaches `direct_model`.

**Incidental finding (not this card's scope).** `pre-compact` artifact entries omit `session_id` while `stop` entries
include it, so the two capture shapes disagree in `confirmed.artifacts.transcripts[]`. Adoption should follow the `stop`
shape. Worth a separate card only if artifact readers care.

## Slice 1 -- Manifest provenance schema

- [x] `confirmed.adoption` added as a strict dataclass field (`{source_runtime, adopted_at, source_path, model_basis}`)
  -- `AdoptionConfirmed`, `session/models.py:555`, wired at `SessionConfirmed.adoption`. Verified in
  `tests/src/session/test_models.py::TestAdoptionConfirmed`: dacite round-trips it; a manifest without the field still
  reads (additive, defaults `None`); an ad hoc `adoption_source` key raises `UnexpectedDataError` under the strict read.
  Plain `str` fields, no `__post_init__` validation -- matching the sibling `*Confirmed` fail-open rule
  (`LaunchConfirmed`, `:498`), because a confirmed-facts class that refuses to load strands the whole session, not one
  field. Value constants stay with the writing op (`ROLLOUT_SOURCE_*` precedent, `core/ops/codex_session.py:69`), so
  they land in Slice 2.
- [x] `model_basis` records which P3 basis produced `intent.launch.direct_model`: `explicit` (`--model`), `inferred`
  (transcript metadata), or `none` (left unset). Verified: all three round-trip (parametrized), and `none` coexists with
  an unset `direct_model` -- a recorded decision, not missing data.
- [x] Provenance survives hook confirmation. Verified in
  `tests/src/cli/test_artifact_hooks.py::TestAdoptionProvenanceSurvivesHooks` against the **real** Stop handler through
  `CliRunner`, not a simulated mutation: `confirmed_by` becomes `hook:stop`, `claude_session_id` stays the adopted uuid
  (P1's idempotency, now also covered at unit speed), and every `confirmed.adoption` field survives.
- [x] Compaction cannot disturb the binding. Verified against the real `pre-compact` handler: `claude_session_id` and
  `confirmed.adoption` are untouched, and the recorded snapshot entry carries **no** `session_id` key. Pre-compact never
  mutates the binding today, so this is a guard against a future refactor unifying the two capture paths, given the Stop
  rewrite has no falsy guard. The test also pins the incidental shape difference (compaction entries omit `session_id`)
  that the P1 Docker gate has to filter around.
- [x] design.md **§3.5** sync: `confirmed.adoption` documented as CLI-owned and hook-immune, in the CLI-writes list; the
  Hooks-write list states hooks never write it and their `confirmed_by` / `claude_session_id` rewrites leave it intact.
  The entry records *why* the field exists rather than restating its shape: `confirmed_by` has **three** writers
  (`cli:adopt`, `hook:stop`, `hook:pre-compact` -- `commands.py:891`, discovered by a failing assertion in this slice),
  so origin stored there is overwritten within a turn.
- [ ] design.md **§3.3** sync **deferred to Slice 2, deliberately**: the third origination path (start **pre-seeds**,
  native fork **records**, adopt **binds**) describes a command that does not exist yet, and design docs must describe
  shipped behavior (documentation_guidelines "Design Documents"). Slice 1 shipped the schema, so §3.5 documents the
  schema; §3.3's origination sentence lands with the op. §3.5 says so explicitly ("the binding command that populates
  this field is not shipped yet; the schema and its hook-survival guarantees are") so the gap is visible in the design
  doc, not just here.

## Slice 2 -- Claude adopt op and CLI (card Phase 1)

- [ ] `core/ops/session_adopt.py` command-core op: pure logic, typed exceptions, no Click and no printing (§3.12).
  Assertion: no `click` import; the CLI leaf owns all rendering and exit codes.
- [ ] Preconditions fail-closed in the card's order: inside a Forge project; strict project-compatibility guard for a
  state-mutating command path; transcript exists; UUID not already bound. Assertion: each reject path creates **no**
  manifest, artifact, or index entry, and names the owning session when already bound.
- [ ] **Atomic UUID-unbound check inside the index write lock.** The step-1 check and the index write take the lock
  separately today -- `find_session_by_uuid` (`session/index.py:503`) and `add_session` (`:372`) each open their own
  `file_lock_for_target` -- so two concurrent `adopt` calls on one UUID can both pass and both bind. Adoption cannot
  wrap this from outside because `start_session` owns the add, so add a locked index-layer entry point (e.g.
  `add_session_if_uuid_unbound`) that re-checks uniqueness inside the write lock. Assertion: two racing adopts on one
  UUID leave exactly one binding; the loser creates no manifest and no index entry. Scope honestly: only the **index**
  becomes atomic -- the manifest-scan fallback (`core/ops/session_context.py:405`) holds no lock, so the guarantee is
  "atomic against the index, best-effort against the manifest scan".
- [ ] Recorded-`cwd` cross-check on the discovered transcript (the Claude analog of `_rollout_head_cwd`). Assertion: a
  lossy-encoding sibling's transcript (`a.b` / `a_b` / `a-b` collision) is rejected, not bound.
- [ ] Write ordering, reconciled with the actual API (**card correction owed**). The card's "index entry last" ordering
  is **not achievable** through `start_session()`, which writes the manifest and adds the index row back-to-back before
  returning (`session/manager.py:645`, `:655`) -- there is no seam to insert the artifact copy between them. Resolution:
  reuse `start_session()` and extend its **existing** best-effort compensation (`:667-680` removes the index row, then
  deletes the manifest) rather than inventing a deferred-commit seam for one caller. Ordering becomes validate ->
  `start_session()` (manifest + index, self-rolling-back) -> artifact copy, with adoption compensating manifest and
  index if the copy fails. Assertion (the invariant the card actually wants, unchanged): an injected failure at any step
  leaves no UUID-bound session, and a re-run succeeds cleanly.
- [ ] **Rollback stays narrow.** Adoption is the first op whose input is user-owned state Forge did not create, so its
  compensation removes exactly the index entry, the manifest, the artifact **copy** under `.forge/artifacts/<name>/`,
  and the queued search-index marker -- and nothing else. Assertion: after a failure injected *after* the artifact copy,
  the native `~/.claude/projects/<enc>/<uuid>.jsonl` is still present and byte-identical, no worktree or branch was
  removed, and no orphan index marker survives pointing at the deleted copy. Adoption must never pass
  `create_worktree=True`; the default is `False` (`session/manager.py:416`) and `_rollback_worktree` short-circuits on
  `if not created_worktree` (`:482`), so this is a constraint to state, not a default to lean on.
- [ ] Future-resume model made explicit per P2 and P3. Assertion: `direct_model` is persisted only when inferred (last
  real model, `<synthetic>` filtered) or supplied via `--model`; with no basis, adopt warns, leaves the field `None`,
  and records `model_basis="none"`. Covered by the "Adoption adds no model pin" acceptance row. Scope the claim to what
  adoption **contributes**: `build_claude_env` starts from the current process environment (`core/reactive/env.py:210`),
  so an ambient `ANTHROPIC_MODEL` reaches Claude regardless of the manifest. Asserting "no `ANTHROPIC_MODEL` in the
  child env" would be testing the shell, not adoption; scrubbing inherited model variables is a routing-wide change and
  belongs to a separate card.
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

Three tests are **not** in the card's table and come from the Slice 0 probes: a mixed-real-model fixture asserting the
last-model tie-break (Slice 2, from P2's 2/470 finding); compaction-preserves-binding (Slice 1); and the P1
Stop-identity gate, which runs **before** Slice 2 rather than at closeout and is distinct from Slice 5's end-to-end
adoption gate.

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
