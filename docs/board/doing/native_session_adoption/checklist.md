# Checklist: Adopt native Claude Code / Codex sessions

**Card**: [card.md](card.md).

**Lane**: `doing/` -- accepted 2026-07-26 and moved `proposed/` -> `doing/` directly (the `todo/` parking step was
skipped because acceptance and activation happened in the same decision). Moved to `done/` on 2026-07-27 and **moved
back the same day**: review found the lesson-review step (closeout item 3) is a precondition for the lane move, not
something a `done/` card may still be waiting on, and found four binding-safety defects alongside it.

**Execution branch**: `feat/native-session-adoption`. Slice 0 shipped the P1 gate
(`tests/integration/docker/test_adopt_binding_contract.py`) with no `src/` change; Slice 1 the manifest schema
(`AdoptionConfirmed`); Slice 2 the `forge session adopt` op and CLI leaf; Slice 3 the bare-`adopt` discovery preview.
The Claude arm is usable end to end: bare `adopt` to find a conversation, `adopt <id>` to bind it, `resume` to continue.

**Slice numbering note**: the card uses "Phase 1 / Phase 2" for the **Claude** and **Codex arms**. This checklist uses
"Slice" numbering to avoid collision; the arm mapping is called out where it applies.

## Current focus

**Slices 0, 1 and 2 are closed.** Slice 0 settled the three owner decisions and all three probes (P1 gated on real
Claude 2.1.220, P2, P3). Slice 1 shipped `confirmed.AdoptionConfirmed`. Slice 2 shipped `forge session adopt` -- the
command-core op, the CLI leaf, and the locked index guard that closes the already-bound TOCTOU -- with design.md §3.3
and §3.5 and `cli_reference.md` synced. Slice 3 shipped the bare-`adopt` discovery preview, completing the settled
discovery decision. Slice 4 shipped the Codex arm with evidence-based runtime detection, and Slice 4a closed the
one-thread/one-manifest hole review found in it. Slice 5 shipped the end-to-end Docker gate and the doc sync.

**Slice 5a -- third review round (2026-07-27).** The card was moved to `done/` prematurely and is back in `doing/`. Four
defects, all reproduced before fixing:

- **Cross-project name collision hid the current project's orphan manifest.** Both collectors deduped manifest reads by
  bare session name, but names are project-scoped: an indexed `same` in project A stopped project B's orphan `same` from
  ever being read, so its conversation looked free. Now keyed by `(resolved root, name)`.
- **Orphan window still allowed a genuine double-bind.** Slice 4a's index-lock guard cannot see a binding that never
  reached the index. Reproduced: a scan running before a killed adopt's manifest appeared published a second binding,
  and the orphan scan could then only refuse the *third* attempt. Fixed with `conversation_lock`, a global per-
  conversation `flock` spanning the final scan and the commit, applied to both arms. This retires the "orphan scan
  covers the adoption invariant" claim made in the previous round, which was too strong.
- **The filename parser was called but its answer discarded.** The rollout glob matches any name *ending* in the id, so
  `rollout-<ts>-not-the-thread-<wanted>.jsonl` was a candidate; the filter only checked that parsing succeeded. Fixed at
  the source in `find_rollouts_by_thread_id`, so runtime detection and provenance lookup get exactness too.
- **Codex thread drift left the index column stale.** Both continuation paths record a re-bound thread id in the
  manifest; neither updated the index, so the in-lock guard protected an abandoned id. `codex_thread_id` now mirrors the
  manifest at all four Codex write sites, which also makes the column's contract statable in one line.

Two smaller items from the same review: the dual-runtime refusal now names both matched paths (the card promised that
diagnostic), and the concurrency regression no longer accepts zero surviving bindings.

**Still open.** The `impl_notes.md` promotion (closeout item 3) needs human review before this card can move to `done/`;
its four candidates are listed under Slice 5. Carried forward as debt needing its own card: session creation is not
crash-atomic across manifest and index. `conversation_lock` bounds the *adoption* consequence of that, but the orphan
manifest itself still survives a kill.

**Slice 2 review remediation (2026-07-27).** An external review of `60f010d8..93b2908f` found seven defects; all seven
were reproduced against source before fixing, and each is closed with a regression or unit test. Two were data-loss
bugs, so Slice 2's original "closed" note above understated the risk it shipped with:

- **Unvalidated conversation id deleted arbitrary files** (critical). Reproduced end to end: `Path(base) / "/abs"`
  discards `base`, so the read and the artifact copy aliased to one file and rollback unlinked the source.
  `normalize_conversation_id` now anchors canonical UUID shape before any path is built. Test:
  `tests/regression/test_bug_adopt_id_traversal.py`.
- **Adopted native transcript exposed to cleanup.** Worse than reported: `auto_clean_old_sessions` passes
  `delete_transcripts=True` on CLI startup (`cleanup.py:225`), so this fired with no explicit delete.
  `_is_adopted_session` protects the bound UUID through the existing shared-transcript filter. Test:
  `tests/regression/test_bug_adopt_transcript_retention.py`.
- **Same-name concurrent create orphans the winner.** Real, but **not adoption-specific** -- it is pre-existing in
  `start_session` and needs both the index pre-check (`:498`) and the manifest pre-check (`:599`) to miss. The first fix
  reserved the index name first; see the second-round entry below for why that was wrong and what replaced it. Test:
  `tests/regression/test_bug_start_session_name_race.py`.
- **Missing manifest-scan fallback** (card step 1). Confirmed. `scan_manifests_for_uuid`, promoted from private, now
  runs after the index lookup. Test: `test_binding_recorded_only_in_a_manifest_still_blocks_adoption`.
- **No revalidation after the double-attach prompt.** Confirmed, and the docstring claimed otherwise.
  `_check_still_adoptable` is now shared by plan and write. Test:
  `test_transcript_deleted_during_the_prompt_aborts_before_writing`.
- **Model values bypass `resolve_direct_model_pin`.** Confirmed, with a consequence the review missed: an unresolvable
  stored pin makes a later `resume --proxy` raise at `model_pin.py:61`. Both sources now normalize to `env_model`. Test:
  `TestModelBasis` (4 cases).
- **Dead `marker_uuid` rollback branch.** Confirmed unreachable; the parameter is removed.

Deliberate deviation from the review on the model finding: it implied uniform validation. `claude-3-5-sonnet-20241022`
resolves in real transcripts but not in Forge's catalog, so uniform validation would make genuine conversations
un-adoptable. Explicit `--model` is a user assertion (fail loudly); an inferred model is evidence about a conversation
that really ran (degrade to no pin).

**Second-round remediation (2026-07-27).** A follow-up review found six more issues; all six were verified against
source. One was a regression introduced by the first round:

- **Index-first reservation was not durable** (regression, first round). `IndexStore.list_sessions` prunes index rows
  whose manifest is missing (`index.py:170`) -- precisely the window the reservation opened -- so a concurrent
  `session list` could delete a reservation out from under its creator. Its own comment ("worst case is a false-positive
  prune that gets re-added on the next session start") was only true while manifests were written first. Replaced with
  `SessionStore.create_exclusive`, which claims the name under the manifest's own lock, and applied to all four true
  creation paths: `start_session`, fork, resume-child, relaunch. `_restore_previous_target_state` and the deliberate
  stale-fork-target replacement keep `write`, since both intend to overwrite.
- **Unscoped rollback `remove_session`.** Confirmed: with `forge_root=None`, `resolve_key_strict` scans by name prefix,
  so a same-named session in another project makes the rollback raise `AmbiguousSessionError` or delete the wrong
  project's row. Latent before the first round made the branch reachable; now scoped.
- **Adoption protection keyed only on the bound UUID.** Nothing pins `claude_session_id` to the adoption source once
  hooks reconcile it, and the source UUID also sits in the artifact list. Now protects every tracked id -- over-
  protecting leaks a Forge-written transcript, under-protecting destroys a user's conversation. Test:
  `test_protection_survives_the_bound_uuid_drifting_from_the_adopted_one`.
- **Case-sensitive UUID identity.** The already-bound check is a string equality, so `AAAA...` and `aaaa...` would bind
  twice to one conversation -- and on macOS both resolve to the same transcript file. Now folded to lowercase, which is
  safe because 0 of 470 local transcripts carry an upper-case hex digit. This corrects a first-round comment that
  asserted, without evidence, that Claude emits both casings. Test:
  `test_uppercase_cannot_double_bind_an_adopted_conversation`.
- **No invariant recheck in `adopt_session`.** `AdoptPlan` is an ordinary dataclass, so a hand-built plan could reach
  the same read-and-copy the unvalidated-id defect exploited. `_check_plan_invariants` re-derives the canonical id and
  transcript path and re-enforces project compatibility.
- **Card contradicted the implementation.** The rollback table listed the index marker as a fourth unwind item (the
  enqueue is outside the guarded block, so that branch was unreachable), and the write-ordering section did not say what
  makes a name reserved. Both reconciled, with the marker's best-effort semantics stated explicitly.

One correction to the review's framing on the creation primitive: it asked for "one creation primitive across start,
fork, resume-child, and relaunch." Applied to those four, but **not** blanket-applied --
`_restore_previous_target_state` restores a prior manifest and the fork path deliberately replaces a stale target, so
both are real overwrites and `create_exclusive` would be wrong there.

Flipping the primitive also exposed that `_generate_resume_name` consulted only the index, so a collision retry could
regenerate the same taken name; it now checks the manifest too, via `_name_is_taken`. That changed which mechanism
`test_bug_resume_autoname_context_retry.py`'s third case exercises -- the name is now sidestepped rather than collided
on -- so that test was updated to inject the winner between name generation and the create, the only interleaving that
still reaches the collision branch. Its assertions were kept, not weakened, and it was re-verified to fail when the
primitive is made non-exclusive.

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
every citation moved to the leaf (done), and the proxy-supported branch got its answer in P3 below.

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

**Shape divergence -- now in scope, not incidental.** `pre-compact` artifact entries omit `session_id` while `stop`
entries include it, so the two capture shapes disagree inside one `confirmed.artifacts.transcripts[]` list. First
recorded here as an aside; it turned out to matter twice. The P1 Docker gate must filter to
`reason in {stop, stop-failure}` or read a `None` as drift, and a Slice 1 unit test now pins the divergence
(`test_pre_compact_leaves_the_binding_untouched`) so it cannot change unnoticed. Adoption's own entry follows the `stop`
shape. Unifying the two shapes is still a separate card.

## Slice 1 -- Manifest provenance schema

- [x] `confirmed.adoption` added as a strict dataclass field (`{source_runtime, adopted_at, source_path, model_basis}`)
  -- `AdoptionConfirmed`, `session/models.py:555`, wired at `SessionConfirmed.adoption`. Verified in
  `tests/src/session/test_models.py::TestAdoptionConfirmed` at the **real storage boundary**, not just dacite:
  `SessionStore.write` -> `read` restores the record and the on-disk JSON carries all four keys verbatim -- an in-memory
  `asdict` -> `from_dict` exercises neither JSON serialization nor the pre-parse strip helpers. A manifest without the
  field still reads (additive, defaults `None`); an ad hoc `adoption_source` key raises `UnexpectedDataError` under the
  strict read. Round-trips compare the **whole record**, so a field added later that fails to persist cannot slip past a
  per-field assertion. Plain `str` fields, no `__post_init__` validation -- matching the sibling `*Confirmed` fail-open
  rule (`LaunchConfirmed`, `:498`), because a confirmed-facts class that refuses to load strands the whole session, not
  one field. Value constants stay with the writing op (`ROLLOUT_SOURCE_*` precedent, `core/ops/codex_session.py:69`), so
  they land in Slice 2.
- [x] `model_basis` records which P3 basis produced `intent.launch.direct_model`: `explicit` (`--model`), `inferred`
  (transcript metadata), or `none` (left unset). Verified: all three round-trip (parametrized), and `none` coexists with
  an unset `direct_model` -- a recorded decision, not missing data.
- [x] Provenance survives hook confirmation. Verified in
  `tests/src/cli/test_artifact_hooks.py::TestAdoptionProvenanceSurvivesHooks` against the **real** Stop handler through
  `CliRunner`, not a simulated mutation: `confirmed_by` becomes `hook:stop`, `claude_session_id` stays the adopted uuid
  (P1's idempotency, now also covered at unit speed), and the `confirmed.adoption` record compares **equal as a whole**
  after the hook runs -- a per-field check would tolerate the hook clearing a field the test happens not to name.
- [x] Compaction cannot disturb the binding. Verified against the real `pre-compact` handler: `claude_session_id` and
  `confirmed.adoption` are untouched, and the recorded snapshot entry carries **no** `session_id` key. Pre-compact never
  mutates the binding today, so this is a guard against a future refactor unifying the two capture paths, given the Stop
  rewrite has no falsy guard. The test also pins the incidental shape difference (compaction entries omit `session_id`)
  that the P1 Docker gate has to filter around.
- [x] design.md **§3.5** sync: `confirmed.adoption` documented as CLI-owned and hook-immune, in the CLI-writes list; the
  Hooks-write list states hooks never write it and their `confirmed_by` / `claude_session_id` rewrites leave it intact.
  The entry records *why* the field exists rather than restating its shape: `confirmed_by` has **three** writers
  (`cli:adopt`, `hook:stop`, `hook:pre-compact` -- `commands.py:891`, discovered by a failing assertion in this slice),
  so origin stored there is overwritten within a turn. §3.3's origination sentence is **deliberately not** a Slice 1
  item -- see the matching Slice 2 task. Design docs must describe shipped behavior (documentation_guidelines "Design
  Documents"), and that sentence describes a command that did not exist when Slice 1 shipped.

## Slice 2 -- Claude adopt op and CLI (card Phase 1)

**Shipped 2026-07-27.** `core/ops/session_adopt.py` (op), `cli/session_adopt.py` (leaf), plus the locked index guard.
Verification: `tests/src/core/ops/test_session_adopt.py` (22) and `tests/src/cli/test_session_adopt.py` (8) pass; full
unit suite 8408 passed / 1 pre-existing skip; `test_session_lifecycle.py` 21 passed in Docker; `make pre-commit` clean.

Two conventions the implementation had to discover rather than assume:

- The op splits into read-only `plan_adoption` and mutating `adopt_session`. The double-attach decision needs a
  confirmation point **before** any write, which one combined function cannot offer.

- `print_error` / `print_error_with_tip` must **not** receive the stdout `console`; they default to the error console.
  An AST guard (`tests/src/cli/test_output_streams.py::test_error_helpers_do_not_pass_stdout_console`) caught six
  violations that line-based greps would have missed.

- [x] `core/ops/session_adopt.py` command-core op: pure logic, typed exceptions, no Click and no printing (§3.12).
  Assertion: no `click` import; the CLI leaf owns all rendering and exit codes.

- [x] Preconditions fail-closed in the card's order: inside a Forge project; strict project-compatibility guard for a
  state-mutating command path; transcript exists; UUID not already bound. Assertion: each reject path creates **no**
  manifest, artifact, or index entry, and names the owning session when already bound.

- [x] **Atomic UUID-unbound check inside the index write lock.** The step-1 check and the index write take the lock
  separately today -- `find_session_by_uuid` (`session/index.py:503`) and `add_session` (`:372`) each open their own
  `file_lock_for_target` -- so two concurrent `adopt` calls on one UUID can both pass and both bind. Adoption cannot
  wrap this from outside because `start_session` owns the add, so add a locked index-layer entry point (e.g.
  `add_session_if_uuid_unbound`) that re-checks uniqueness inside the write lock. Assertion: two racing adopts on one
  UUID leave exactly one binding; the loser creates no manifest and no index entry. Scope honestly: only the **index**
  becomes atomic -- the manifest-scan fallback (`core/ops/session_context.py:405`) holds no lock, so the guarantee is
  "atomic against the index, best-effort against the manifest scan".

- [x] Recorded-`cwd` cross-check on the discovered transcript (the Claude analog of `_rollout_head_cwd`). Assertion: a
  lossy-encoding sibling's transcript (`a.b` / `a_b` / `a-b` collision) is rejected, not bound.

- [x] Write ordering: validate -> `start_session()` (manifest + index, self-rolling-back) -> artifact copy -> index
  marker. The card's original "index entry last" ordering is not achievable, since `start_session()` writes the manifest
  and adds the index row back-to-back before returning (`session/manager.py:652`, `:655`) with no seam between.
  Assertion: an injected failure at any step leaves no UUID-bound session, and a re-run succeeds cleanly.

- [x] **Rollback: two disjoint stages, resolved 2026-07-27** (card "Rollback mechanism"). Stage 1 is `start_session()`'s
  own `except` (`:666-681`) for failures **inside** it -- already shipped, nothing to build. Stage 2 is adoption's own
  compensation for everything **after** `start_session()` returns. A second compensation is not optional and not a
  hazard: the stage-1 block is unreachable once `return state` executes at `:664`, so the two stages are disjoint in
  time and cannot both fire for one failure. An earlier draft said to "extend that same compensation path rather than
  add a second rollback", which is not implementable.

- [x] **Stage 2 must not call `SessionManager.delete_session()`.** Its default `delete_transcripts=True` reaches
  `cleanup_session` -> `delete_session_data`, which unlinks `get_transcript_path(project_root, session_id)` plus the
  matching agent logs (`session/claude/cleanup.py:63-80`) -- a path that resolves into `~/.claude/projects/<encoded>/`.
  For an adopted session `claude_session_id` **is the user's native UUID**, so the convenient rollback deletes the
  conversation the user asked Forge to adopt. Use the narrow primitives: unlink the marker and the artifact copy, then
  `IndexStore.remove_session(name)`, then `SessionStore.delete()` -- which removes only `.forge/sessions/<name>/`
  (`session/store.py:262-275`) and therefore does **not** reach the artifact copy under `.forge/artifacts/<name>/`.
  Assertion: after a failure injected *after* the artifact copy, the native `~/.claude/projects/<enc>/<uuid>.jsonl` is
  present and byte-identical, its agent logs are intact, no worktree or branch was removed, and no orphan index marker
  survives. Adoption must never pass `create_worktree=True`; the default is `False` (`session/manager.py:416`) and
  `_rollback_worktree` short-circuits on `if not created_worktree` (`:482`), so this is a constraint to state, not a
  default to lean on.

- [x] Future-resume model made explicit per P2 and P3. Assertion: `direct_model` is persisted only when inferred (last
  real model, `<synthetic>` filtered) or supplied via `--model`; with no basis, adopt warns, leaves the field `None`,
  and records `model_basis="none"`. Covered by the "Adoption adds no model pin" acceptance row. Scope the claim to what
  adoption **contributes**: `build_claude_env` starts from the current process environment (`core/reactive/env.py:210`),
  so an ambient `ANTHROPIC_MODEL` reaches Claude regardless of the manifest. Asserting "no `ANTHROPIC_MODEL` in the
  child env" would be testing the shell, not adoption; scrubbing inherited model variables is a routing-wide change and
  belongs to a separate card.

- [x] Transcript artifact copy with reason `"adopt"`, matching the Stop entry shape (`cli/hooks/commands.py:165-178`),
  and a queued search-index marker. Assertion: the copy is indexed through the normal idempotent path, and **no**
  memory-writer handoff marker is enqueued at adopt time.

- [x] CLI leaf under `forge session`, using `forge.cli.output` helpers. Assertion: recovery text goes through
  `print_error`/`print_tip`; no hand-rolled `Tip:` or `[red]Error:[/red]`.

- [x] Reattach works with zero new resume code. Assertion: post-adopt `forge session resume <name>` builds argv
  `--resume <uuid>` with no `--fork-session`.

- [x] design.md **§3.3** sync, carried over from Slice 1: `claude_session_id` gains a third origination path -- start
  **pre-seeds**, native fork **records**, adopt **binds** an existing native UUID. Held until now because design docs
  describe shipped behavior and the sentence names a command. Assertion: §3.3 lists all three paths, and §3.5's caveat
  ("the binding command that populates this field is not shipped yet") is removed in the same change, since leaving it
  would then be false.

## Slice 3 -- Discovery preview

- [x] Bare `forge session adopt` lists unbound candidates for the exact cwd, showing mtime, turn count, first-message
  snippet, and the exact directory scanned. Assertion: an already-bound UUID is excluded; a recorded-`cwd` mismatch is
  not listed. Verified by `TestDiscovery` (6 cases) and `TestAdoptPreview` (3 cases); `agent-<uuid>.jsonl` sidecars are
  excluded too.
- [x] Subdirectory guidance. Assertion: running the preview at the Forge root when the conversation was launched from a
  subdirectory does not misattribute, and the diagnostic names the launch directory. Verified by
  `test_bare_adopt_with_nothing_here_points_at_the_launch_directory`; the scanned directory prints on both the empty and
  non-empty branches.
- [x] Hook rule untouched. Assertion: the CWD scan exists only in the CLI; no hook gains a scan (design.md §3.10).
  Verified by `tests/src/cli/test_hook_no_cwd_scan.py`, an import guard over every hook module, checked non-vacuous by
  temporarily importing `get_project_encoded_dir` into `hooks/commands.py`.

Two decisions this slice settled, both grounded in the local 470-transcript corpus rather than assumption:

- **Turn count excludes tool results.** Claude types tool results as `user` entries -- 612 of 662 user entries across a
  200-transcript sample -- so counting every `user` entry would report mostly machine traffic. A turn is a `user` entry
  whose content is a plain string or carries a `text` block.
- **The preview skips synthetic wrappers.** `<command-message>`, `<local-command-caveat>`, `<local-command-stdout>`,
  `<task-notification>`, `<bash-input>`, `<bash-stdout>` open many real transcripts (~187 tagged against 608 plain
  messages) and identify nothing, so the preview takes the first untagged human message.

Discovery also collapsed `read_transcript_cwd` and `infer_transcript_model` into one `summarize_transcript`. Both were
full-file readers over the same format, so `plan_adoption` was opening each transcript twice; discovery needs cwd, turns
and preview from the same pass anyway.

**Third-round remediation (2026-07-27).** A conformance review found seven design violations plus four standard issues;
all were reproduced against source before fixing. Three were HIGH:

- **Crash between manifest create and index publish double-bound a UUID.** Reproduced: killing the process after
  `create_exclusive` left a manifest bound to the conversation, invisible to every binding check because all of them
  enumerated through the index -- so the preview listed it and a second adopt succeeded, leaving two manifests on one
  conversation. This was the direct consequence of the second round's manifest-first ordering, and
  `scan_manifests_for_uuid`'s own docstring already admitted the enumeration limit. `collect_bound_uuids(forge_root)`
  now also scans manifest directories under the project root. Test:
  `test_orphan_manifest_from_a_crashed_adopt_blocks_a_second_bind`.
- **Force-fork rollback restored its stale target over a concurrent winner.** `replaced_target_state` is set before the
  name is claimed, so a losing `create_exclusive` still ran `_restore_previous_target_state`, whose unconditional
  `write()` clobbered the winner. Restoration is now guarded on `wrote_manifest` (the ownership token) and a free path.
  Test: `tests/regression/test_bug_fork_restore_clobbers_winner.py`.
- **Mutation persisted a stale inferred model.** `_check_still_adoptable` returned a fresh summary that `adopt_session`
  discarded. Changing the transcript's model between plan and adopt persisted the planned one -- the first-resume
  surprise the pin exists to prevent. The pin is now re-resolved from the mutation-time summary; an explicit `--model`
  is never re-derived. Test: `test_model_is_re_resolved_from_the_transcript_at_write_time`.

The MEDIUM and standard fixes: the preview no longer mutates the index (`read()` instead of the pruning `list_sessions`)
and fails closed on an unreadable index; `--json` added and binding flags refused in preview mode; a same-UUID name
collision now reports the owner-aware already-bound rejection instead of `SessionExistsError`; deletion protection
narrowed from every tracked id to the provenance-named source (`adoption.source_path` plus the `reason="adopt"`
artifact); `SessionStore` validates the session name before creating any directory (an absolute name previously created
a directory outside the project -- the same `Path / "/abs"` trap as the Slice 2 critical); transcript text and paths
render as literal `Text` so Rich cannot interpret `[...]` from a conversation; and `user_turns` no longer counts
machine-output wrappers, matching what it documents.

`ADOPT_ARTIFACT_REASON` moved from the op to `session/artifacts.py`: `session.manager` reads it during deletion and the
session layer cannot import from `core.ops`. A deliberate exception to the constants-live-with-the-writing-op
convention, recorded so it does not read as drift.

**Open debt -- creation is still not crash-atomic.** The fix above removes the double-bind, not the orphan. A process
killed between `create_exclusive` and `add_from_state` still leaves a manifest with no index row: invisible to
`session list`, yet still owning its name. The review's recommendation is to hold the index lock across both writes so
the crash windows become "prunable row" or "both present". That is the right shape -- nothing nests manifest->index
today, so index->manifest introduces no deadlock -- but it restructures `IndexStore.add_session` into a transaction form
used by all four creation paths, which is broader than this card. Not attempted here; carry as its own card.

## Slice 4 -- Codex arm (card Phase 2)

- [x] Thread-id lookup scans **all** matching rollouts rather than inheriting `find_rollout_path`'s newest-match
  behavior. Assertion: cwd mismatch, no match, and multiple-match-after-cwd-filter each reject with actionable
  diagnostics instead of silently choosing the newest. Verified by `TestRolloutLookup` (5 cases). `find_rollout_path`
  now delegates to a new public `find_rollouts_by_thread_id`, so the newest-wins tie-break lives in one place and
  adoption opts out of it rather than reimplementing the glob.
- [x] Fresh `assert_codex_ready()` preflight before any state is created. Verified by
  `test_an_unready_codex_creates_no_state`.
- [x] Manifest with `intent.launch.runtime="codex"` and `confirmed.codex` carrying `rollout_source="adopted"` as a new
  module-level constant. Assertion: `claude_session_id` and `confirmed.launch` stay unset; `context_delivery` stays
  `None`. Verified by `test_binds_the_thread_without_claude_fields`.
- [x] `CodexConfirmed.rollout_source` docstring gains **both** the missing `discovered_post_exit` and the new `adopted`,
  and `design_appendix.md` §I.1 gains `adopted`.
- [x] Resume dispatch needs no new code. Assertion: `session_runtime(manifest) == "codex"` routes to `run_codex_resume`.
  Verified by `test_adopted_session_routes_to_codex_resume_with_no_new_dispatch` against the existing branch at
  `cli/session_lifecycle.py:1345`.

**Runtime detection is evidence-based, not id-shaped.** Both runtimes name conversations with UUIDs, so
`forge session adopt <id>` has to decide which arm to use. Measured locally, Codex thread ids are UUIDv7 (458/458) and
Claude session ids are v4 (470/471, with one v3) -- tempting, but that is an undocumented detail of two third-party
tools and the lone v3 already breaks the pattern. `detect_adoption_runtime` instead asks the filesystem: a Claude
transcript in this cwd's encoded directory, or a rollout matching the thread id. A match in both is refused rather than
guessed, matching the arm's own no-guessing rule.

Two smaller decisions:

- **No artifact copy on the Codex arm.** `confirmed.codex.rollout_path` points at the live rollout, which is how every
  other Codex session records it; copying would invent a second convention. Search indexing of Codex threads is not part
  of this card. Verified by `test_the_rollout_is_never_copied_or_moved`.
- **`--model` is refused for Codex, not ignored.** Codex resolves its own model per turn, so accepting the flag would
  imply a pin that nothing reads.

### Slice 4a -- one-thread/one-manifest made atomic (review follow-up, 2026-07-27)

Review of the shipped Slice 4 found the card's core invariant still breakable. Confirmed by reproduction before fixing:
a barrier-gated probe released two differently-named adopts after each had seen the thread id as free, and **both
bound**.

- [x] Codex thread identity is committed by the write that publishes the session. Assertion: two interleaved adopts of
  one thread produce exactly one binding and one `UuidAlreadyBoundError`; a published Codex session never has
  `confirmed.codex = None`. Verified by `tests/regression/test_bug_codex_adopt_double_bind.py` (2 cases), confirmed
  non-vacuous by removing the index derivation and watching both fail.
- [x] Binding discovery fails closed on manifests, not just on the index. Assertion: an unparseable manifest raises
  `BindingLookupError` naming the directory to repair, rather than reporting the conversation as free. Verified by
  `TestBindingCollectionFailsClosed` (3 cases, including that an absent sessions dir is still empty, not an error).
- [x] An unreadable rollout head keeps the candidate set ambiguous instead of being dropped, and the filename parser --
  not the looser glob -- decides what counts as a rollout. Verified by
  `test_an_unreadable_head_keeps_a_verified_match_ambiguous` and `test_ignores_a_file_whose_name_is_not_a_rollout`.
- [x] Success output reports the re-resolved rollout path (`CodexAdoptResult`), not the planning-time one.
- [x] CLI help and `docs/end-user/session.md` cover both arms; the transcript-copy claim is scoped to Claude.
- [x] Card's "requires `--runtime`" open item closed as a recorded decision (refuse, no flag).

**Why the fix is in `start_session` rather than the op.** The pre-check and the binding write took different locks (the
index's vs. the session's own manifest lock), so no ordering of them inside `codex_adopt.py` could exclude a concurrent
adopt. The index write lock is the only lock shared across session names, which means the thread id has to be *in* the
index row to be checkable there -- hence the new `codex_thread_id` column and `require_uuid_unbound` covering both
bindings. Handing the whole `CodexConfirmed` to `start_session` also removes the second write, so
`_rollback_codex_adoption` became unreachable and was deleted.

**Not fixed here, still open debt:** session creation remains non-atomic across manifest and index (a kill between
`create_exclusive` and `add_from_state` leaves an orphan manifest). The orphan manifest scan in
`collect_bound_codex_threads` covers the adoption invariant against it, but the general fix -- an index-lock-spanning
transaction -- is broader than this card and needs its own.

## Slice 5 -- Gates, docs, closeout

- [x] Real-Claude adoption gate (slow, Docker): a bare-`claude` conversation created in-container is adopted and
  continued via `claude --resume <uuid>` from a manifest Forge never launched.
  `tests/integration/docker/test_adopt_native_conversation.py`, green on Claude Code 2.1.220. The conversation is
  created with `FORGE_SESSION` unset so no hook writes anything; the gate then asserts the `--json` preview finds
  exactly one candidate (a never-launched Forge session is the control that must not appear), the 30-minute
  double-attach guard fires on a conversation that ended seconds ago, `_is_resumable_session` accepts a transcript Forge
  never wrote, and the resumed turn recalls a number stated only before adoption -- continuity, not just exit 0. Also
  asserts the native transcript still exists afterwards.
- [x] Integration suites run, not deferred to closeout -- adoption touches session lifecycle, hooks, and the index, none
  of which unit tests exercise (`testing_guidelines.md`, "When to Run Integration Tests"). Ran
  `test_session_commands_integration.py` (43 passed) and both Docker adoption gates.
- [x] `workspace_scope` identity-table line extended to "bound when launched **or adopted**"; the outbound link from
  this card to that one keeps the same depth under `done/`, so it needs no repoint.
- [x] `cli_reference.md` session table gains the `adopt` leaf. Verified at line 131 -- already synced during Slice 2 and
  extended for the Codex arm in Slice 4; re-read rather than assumed.
- [ ] Change-log entry with Goal / Key changes / Verification. Drafted and then **withdrawn** when the card returned to
  `doing/`: `change_log.md` records completed work, so an entry for an open card is a false completion record. Re-add at
  the real closeout.
- [ ] Durable lessons proposed for `impl_notes.md` after human review. Candidates, awaiting review:
  1. **`Path(base) / "/abs"` discards `base`.** Hit three times on this card (adoption id, `SessionStore` session name).
     Any caller-supplied path component needs shape validation *before* it is joined, not after.
  2. **Uniqueness must be enforced under the lock that publishes the row.** A pre-check plus a later write under a
     different lock is not exclusion, however carefully ordered. If an id must be unique across sessions, it belongs in
     the index row, because the index write lock is the only lock shared across session names.
  3. **The encoded-project-directory encoding is lossy** (`/`, `.`, `_` all fold to `-`), so a transcript found under it
     must still be cross-checked against the `cwd` recorded inside the file.
  4. **A swallowed read is not an absent record.** Binding/uniqueness lookups must fail closed on every source they
     consult, not just the first one.
- [ ] Card moved to `done/`. Attempted 2026-07-27 and reverted the same day (see Slice 5a): the lesson review above is a
  precondition, not a parallel task. No inbound board links to repoint -- verified by grep across `docs/`; the outbound
  link to `workspace_scope` keeps the same relative depth either way.

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
