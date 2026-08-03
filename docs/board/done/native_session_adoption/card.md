# Adopt native Claude Code / Codex sessions (`forge session adopt`)

**Lane**: `done/` -- shipped and verified 2026-07-27; execution record in [checklist.md](checklist.md). Standalone (not
an `epic_global_forge_runtime` member); relates to the session identity model (design.md §3.3/§3.5) and complements
[`workspace_scope`](../../done/workspace_scope/card.md), whose identity table says a native Claude session is "bound to
a Forge session **when launched**" -- this card adds binding **after the fact**.

**Origin**: user request (2026-07-07) -- pick up a session started outside Forge (bare `claude`, bare `codex`) and
resume it as a managed Forge session. Primary driver: **native Claude** pickup; Codex is a structured second phase.

**Revised 2026-07-07** after a grounding-verified doc review -- all cited code claims were confirmed against current
source. This revision adds the Stop-hook `claude_session_id`-rewrite risk, a Claude-side recorded-`cwd` cross-check
(symmetric to the Codex arm), pins where `direct_model` takes effect, states the native-reattach durability caveat plus
adopt write ordering, and corrects two precision points (`rollout_source` is an unvalidated `str`; refreshed drifted
line refs).

**Re-grounded 2026-07-26** on activation. Every cited symbol still exists and the design holds. Two substantive
corrections: the `ANTHROPIC_MODEL` pin **relocated** out of `core/ops/claude_session.py` into
`core/models/direct_model.py`, and gained a proxy-branch sibling that did not exist when this card was written (now
tracked as checklist probe P3); and the "Write ordering" paragraph specified an index-last sequence that `start_session`
**cannot produce**, since it writes the manifest and index entry back-to-back in one try block. Line anchors throughout
were refreshed.

**Rollback mechanism resolved 2026-07-27.** The first fix for that ordering paragraph was itself wrong: it told adoption
to "extend" `start_session`'s compensation block, which is unreachable once that function returns. Compensation is now
specified as two disjoint stages, with an explicit prohibition on reaching for `SessionManager.delete_session()` --
whose default `delete_transcripts=True` would unlink the user's native transcript, since an adopted session's
`claude_session_id` is the native UUID. See "Rollback mechanism" below.

**Creation primitive and marker semantics reconciled 2026-07-27**, after review of the shipped Slice 2 code. Two points
here contradicted the implementation. The rollback table listed the search-index marker as a fourth item to unwind, but
the enqueue happens after the guarded block, so that branch was unreachable and is now removed. And the write-ordering
paragraph described only *which* of the manifest and index row goes first, not *what makes the name a reservation*: it
is `SessionStore.create_exclusive`, because `list_sessions` prunes index rows whose manifest is missing, so an index row
cannot reserve anything. Both sections below now match the code.

## Goal

`forge session adopt <claude-uuid | codex-thread-id> [--name <name>]` creates a Forge session manifest **bound to an
existing native conversation**, so future Forge-managed operations can use the regular session surface:
`forge session resume` (reattach), `resume --fresh` / `fork` (transfer), supervision, memory writer, artifacts + search,
telemetry. Adoption does **not** attach hooks, env, supervision, or telemetry to an already-running bare native client;
those surfaces begin with the next Forge-managed resume/fork. Bare `forge session adopt` lists adoptable candidates
(read-only preview, like `session clean`).

## Why

Sessions do not always start through Forge: a quick bare `claude` in a repo, an IDE-launched conversation, a `codex` TUI
run. Today those conversations are invisible to Forge -- no manifest, no artifacts, no lineage; `forge session resume`
cannot touch them and their transcripts never reach search, transfer, or the memory writer. The cost of "should have
started it through Forge" is total feature loss for that conversation. Adoption converts that hindsight into one
command.

Because transfer assembly and the memory writer both read the **full transcript when invoked**, adoption is retroactive
where it matters: transfer can assemble a `--fresh` child from the complete native history, and the first Forge-managed
Stop can curate the whole conversation (including pre-adoption turns). Search visibility comes from the adopted artifact
copy plus the normal index path; memory remains Stop-triggered rather than running merely because adoption copied a
file.

## Design

### The headline: resume is already evidence-based

The reattach machinery was built evidence-first, so adoption is "manufacture the evidence honestly," not a new resume
path:

- `_is_resumable_session` (`cli/session_lifecycle.py:168`) accepts `confirmed.claude_session_id` + **transcript on
  disk** -- no hook confirmation required. `_has_resumable_transcript` (`:179-201`) falls back to
  `get_transcript_path(claude_project_root, uuid).is_file()`, which is exactly the native transcript's location.
- `SessionManager.start_session` (`session/manager.py:411`) already accepts an injected `claude_session_id` (parameter
  `:426`, set at `:636-637`) -- only the CLI op layer lacks a way to pass an existing UUID (`start_claude_session`
  always generates a fresh one, `core/ops/claude_session.py:512`).
- After adoption, bare `forge session resume <name>` dispatches through the existing reconnect path (`--resume <uuid>`,
  no `--fork-session`) with **zero new resume code**.

### What `adopt` writes (Claude arm, Phase 1)

A new command-core op (`core/ops/session_adopt.py`), CLI leaf under `forge session`:

1. **Preconditions (fail-closed):** inside a Forge project (`forge_root` exists -- identity rule 1); run the strict
   project-compatibility guard for this state-mutating command path (missing `.forge/project.toml` is still compatible,
   per T7); the transcript exists at `get_transcript_path(<native launch cwd>, <uuid>)` **and its recorded `cwd` matches
   the current cwd** (Claude stamps `cwd` on every `user`/`assistant`/`system` entry -- verified against a real 2.1.x
   transcript -- so the Claude arm cross-checks it, the analog of the Codex arm's `_rollout_head_cwd`, and rejects a
   lossy-encoding sibling's transcript; see Risks); the UUID is not already bound (`IndexStore.find_session_by_uuid`,
   `session/index.py:491`, plus the manifest-scan fallback, `core/ops/session_context.py:405`) -- if bound, reject
   naming the owning session.

2. **Exact-CWD v1 contract:** the current working directory is treated as the native Claude launch CWD. v1 does not
   guess alternate encoded dirs inside the same Forge project. If a user ran bare `claude` from `src/foo`, they must run
   `forge session adopt` from `src/foo`; the manifest records that exact path in `confirmed.claude_project_root` so
   `_has_resumable_transcript` can find the native JSONL later. The recorded-`cwd` cross-check (step 1) confirms the
   discovered transcript actually belongs to this directory rather than a lossy-encoding sibling (Risks).

3. **Manifest:**
   `start_session(name, direct=True, claude_session_id=<native uuid>, direct_model=<resolved future-resume model>)`.
   Direct mode is honest because a native session ran without a proxy, but the future resume model must not be an
   implicit surprise. This is load-bearing on the **reattach** path, not only `--fresh`/fork: `direct_model` is applied
   as an `ANTHROPIC_MODEL` env pin by `apply_direct_model_env` (`core/models/direct_model.py:86`) on the direct branch
   of the shared launch env-builder (`core/ops/claude_session.py:1450`), and `_reconnect_in_place` threads it into the
   RECONNECT plan (`cli/session_lifecycle.py:1624`), so a wrong value silently changes which model continues the
   conversation on the first plain `--resume`. Pre-seed `confirmed.claude_project_root` (precedent: relocate and rewind
   both pre-seed it, `cli/session_fork.py:908-917`, `cli/session_rewind.py:214`).

   **Adoption writes `direct_model` only when it has a basis** (P3, resolved 2026-07-26). Two bases qualify: an explicit
   `--model` (a user request) and transcript inference (an observed fact about the conversation; viable per checklist
   probe P2). With neither, adoption **warns that the future resume model is unknown and leaves the field `None`** -- it
   does not persist the current direct default. Two code facts decide this. First, persisting the default buys nothing
   on the path adoption cares about: the direct branch already evaluates `direct_model or get_default_direct_model()` at
   launch time (`core/ops/claude_session.py:1448-1449`, `runtime_config.py:588`), so an empty field yields the same
   model. Second, it costs a real surprise on the proxy branch: `_apply_direct_model_env_if_supported`
   (`session/model_pin.py:37`, applied at `core/ops/claude_session.py:1454`) reads the **stored**
   `intent.launch.direct_model`, and the resume-path validation gate fires only for a pin supplied on that invocation
   (`cli/session_lifecycle.py:1375`, `if direct_model_pin`). A stored pin therefore reaches the proxy branch unvalidated
   and **silently no-ops** when the proxy cannot honor it (`session/model_pin.py:61-62`). Writing a default Forge
   invented would let a later `resume --proxy` quietly override the proxy's tier default with a model the user never
   chose.

   When a basis *does* exist, the stored pin behaves exactly as it does for any Forge-born `--model` session -- honored
   on a `--proxy` resume if the proxy configures that model, silently skipped otherwise. Adoption claims no new
   semantics there; the silent-skip asymmetry is pre-existing and out of scope for this card. Record which basis was
   used in `confirmed.adoption.model_basis` (step 4) so the choice is auditable rather than reconstructed.

   The claim is bounded to **what adoption contributes**, not to the final environment. `build_claude_env` starts from
   the current process environment (`core/reactive/env.py:210`), so an ambient `ANTHROPIC_MODEL` in the user's shell
   reaches Claude whatever the manifest says. Adoption's guarantee is that it *adds no pin of its own* -- with
   `direct_model` unset, neither `apply_direct_model_env` nor `_apply_direct_model_env_if_supported` is reached from the
   adopted manifest. Scrubbing inherited model variables would change routing for every session, not just adopted ones,
   and belongs to a separate card.

4. **Provenance schema:** add a strict dataclass field for `confirmed.adoption` (for example
   `{source_runtime, adopted_at, source_path, model_basis}`) and model/store round-trip tests. `model_basis` records
   which of P3's bases produced `intent.launch.direct_model` -- `explicit` (`--model`), `inferred` (transcript
   metadata), or `none` (no basis; the field was left unset) -- so a later "why is this session pinned to that model?"
   is answerable from the manifest instead of reconstructed from a transcript that may no longer exist.
   `confirmed_by="cli:adopt"` alone is insufficient -- the next Stop hook overwrites `confirmed_by` (`hook:stop`) **and
   rewrites `confirmed.claude_session_id` from the Stop payload** (`cli/hooks/commands.py:179`), so adoption provenance
   needs its own field to survive (see the Stop-rewrite risk). CLI-written confirmed fields are established precedent
   (`derivation`, `launch`, `confirmed.codex` -- design.md §3.5).

5. **Transcript artifact copy at adopt time** (reason `"adopt"`, same entry shape as the Stop hook's,
   `cli/hooks/commands.py:166-177`): makes the history immediately available to transfer and durable against native-side
   cleanup. The copy protects only **transfer / `--fresh`** (which read Forge's artifact); native
   `claude --resume <uuid>` reads Claude's own `~/.claude/projects` store, so plain reattach still requires the original
   native JSONL to survive (a limitation, not a gap -- see Risks). Queue the normal search-index marker for that copied
   artifact, or otherwise index it through the same idempotent path as Stop; do **not** enqueue memory-writer work at
   adopt time. Memory remains tied to a successful Stop handoff; StopFailure captures and indexes only. The first
   Forge-managed successful Stop after adoption therefore queues curation of the complete transcript when session memory
   is enabled.

6. **Index entry** via `add_from_state` (copies the UUID, `session/index.py:448`), so UUID-collision checks and
   `session show <uuid>` work immediately. This is **not a separate step adoption schedules** -- `start_session` already
   performs it (`session/manager.py:655`) immediately after writing the manifest (`:652`), inside one try block.

**Write ordering (fail-closed atomicity).** Validate every precondition first (steps 1-2). Everything after that is
constrained by an existing seam rather than free to sequence: because step 3 reuses `start_session`, the manifest
(`session/manager.py:681`) and the index entry (`:684`) are written back-to-back inside a single try block, so adoption
**cannot** interleave its artifact copy between them or append the index entry last. Do not specify an ordering the API
cannot produce.

The manifest goes first, via `SessionStore.create_exclusive` (`session/store.py:248`) rather than `write`. That is the
name reservation for every creation path: the index's authoritative uniqueness check lives inside its own lock, and
`IndexStore.list_sessions` prunes index rows whose manifest is missing (`session/index.py:170`), so an index row is not
a durable reservation. Creating under the manifest's own lock also makes `wrote_manifest` an ownership token, which is
what lets the rollback below delete a manifest without risking someone else's.

**Rollback mechanism (resolved 2026-07-27; marker row corrected 2026-07-27).** Compensation happens in **two disjoint
stages**, because `start_session`'s own block cannot reach adoption's work:

| Failure point                                       | Who compensates                         | How                                                                                                      |
| --------------------------------------------------- | --------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| inside `start_session` (manifest create, index add) | `start_session` itself, already shipped | its `except` block (`:696`), driven by the `wrote_manifest` / `added_to_index` flags (`:672-673`)        |
| after `start_session` returns (artifact copy)       | **the adopt op**                        | unlink the artifact copy, then `index_store.remove_session(name, forge_root=...)`, then `store.delete()` |

Both `remove_session` calls pass `forge_root`. An unscoped remove resolves the name across projects, so a same-named
session elsewhere makes the rollback either ambiguous or a delete of the wrong project's row.

An earlier draft said adoption should "extend that same compensation path rather than add a second rollback of its own".
That is **not implementable**: the `except` at `:696` is unreachable once `return state` executes at `:694`, and
adoption's artifact copy runs after that return. A second compensation is the only possible design -- and it is not the
hazard the earlier wording implied, because the two stages are **disjoint in time** and cannot both fire for one
failure.

**Do not implement stage 2 by calling `SessionManager.delete_session()`.** Its default `delete_transcripts=True` reaches
`cleanup_session` -> `delete_session_data`, which unlinks `get_transcript_path(project_root, session_id)` and the
matching agent logs (`session/claude/cleanup.py:63-80`). That path resolves into `~/.claude/projects/<encoded>/`, and
for an adopted session `claude_session_id` **is the user's native UUID** -- so the convenient rollback would delete the
very conversation the user asked Forge to adopt. Use the two narrow primitives instead: `remove_session` for the index
row and `SessionStore.delete()`, which removes only `.forge/sessions/<name>/` (`session/store.py:262-275`). Note that
`store.delete()` does **not** remove the artifact copy, which lives under a different root (`.forge/artifacts/<name>/`),
so the op must unlink that explicitly.

The user-visible contract is unchanged and is what the reject tests assert: **after any failed `adopt`, no UUID-bound
session remains, the native transcript is untouched, and re-running succeeds cleanly.** Re-adopting an already-bound
UUID is the *already-bound reject* path (step 1), never a silent overwrite.

**Rollback scope is narrow and must stay narrow.** Adoption is the first op whose inputs are *user-owned state Forge did
not create*, so its rollback removes exactly three things and nothing else:

| Rollback removes                                         | Rollback must NOT touch                                              |
| -------------------------------------------------------- | -------------------------------------------------------------------- |
| the index entry adoption added                           | the native transcript at `~/.claude/projects/...` (the adopt source) |
| the session manifest adoption created                    | any worktree or branch                                               |
| the transcript **copy** under `.forge/artifacts/<name>/` | any pre-existing session that already owned the UUID                 |
|                                                          | the `~/.claude` store -- transcripts **or** agent logs               |

The worktree column is not hypothetical safety text: `create_worktree` defaults to `False` (`session/manager.py:434`)
and `_rollback_worktree` short-circuits on `if not created_worktree` (`:506`), so adoption is already safe **provided it
never passes `create_worktree=True`**. State that as a constraint rather than relying on a default.

The search-index marker is deliberately **not** a rollback item, correcting an earlier draft that listed it as a fourth.
The concern behind that row was real -- a marker outliving its artifact points the indexer at a deleted file -- but the
enqueue happens *after* the guarded block, so a marker only ever exists on a path that already succeeded. Keeping the
row would have meant a permanently unreachable branch. Marker enqueue failure is best-effort and surfaces as
`AdoptResult.indexed=False` plus a `forge search rebuild-index` tip, not as a failed adoption.

**Already-bound is a TOCTOU today.** The step-1 check and the index write take the index lock *separately* --
`find_session_by_uuid` (`session/index.py:503`) and `add_session` (`:372`) each open their own `file_lock_for_target` --
so two concurrent `adopt` calls on one UUID can both pass the check and both bind. Closing this needs an index-layer
addition (a locked `add_session_if_uuid_unbound`, or equivalent, that re-checks UUID uniqueness inside the write lock);
adoption cannot wrap it from outside, because `start_session` owns the add. Scope the addition to the index layer in
Slice 2. Note the honest limit: only the **index** can be made atomic this way. The manifest-scan fallback
(`core/ops/session_context.py:405`) holds no lock, so the guarantee is "atomic against the index, best-effort against
the manifest scan" -- say that rather than claiming blanket atomicity.

### Discovery (`forge session adopt` bare)

Scan `~/.claude/projects/<encode_project_path(current cwd)>/*.jsonl` (`session/claude/paths.py:47`) for UUIDs not bound
to any Forge session; show mtime, turn count, first-user-message snippet, and the exact cwd being scanned, and verify
each candidate's recorded `cwd` so a lossy-encoding sibling is not listed under this directory. Discovery is
intentionally exact-CWD in v1, matching the adoption precondition above; if no candidates appear from the Forge root,
the CLI should suggest running the preview from the directory where bare `claude` was launched. This is a **CLI-only**
surface: the normative hook rule (`FORGE_SESSION` + UUID lookup only, no CWD scan -- design.md §3.10) is untouched.

### Codex arm (Phase 2)

All ingredients exist; nothing constructs a manifest *from* a rollout today:

- Locate by thread id by scanning all matching rollout files, not by inheriting `find_rollout_path`'s newest-match
  behavior blindly (`core/runtime/codex_rollouts.py:52`). Parse ids from filenames with `parse_rollout_filename`
  (`:89`); validate each candidate's recorded cwd against the current checkout with `_rollout_head_cwd` (`:147`); reject
  no-match, cwd-mismatch, and multiple-match-after-cwd-filter cases with actionable diagnostics.
- Fresh `assert_codex_ready()` preflight (the fail-closed seam every codex op runs before creating state,
  `core/runtime/codex_preflight.py:221`).
- Manifest with `intent.launch.runtime="codex"` + `confirmed.codex` (`CodexConfirmed`) carrying the thread id, rollout
  path, and a **new `rollout_source="adopted"`** (the field is an unvalidated `str | None` with no `Literal`, so this is
  a new module-level constant plus a docstring line, not a type change); `claude_session_id` and `confirmed.launch` stay
  unset (§3.5). `context_delivery` stays `None` (bare-interactive precedent).
- Resume dispatch needs zero new code: `session_runtime(manifest) == "codex"` routes to `run_codex_resume` (dispatch
  `cli/session_lifecycle.py:1348`; defined in `cli/session_codex.py:237`), cross-CWD by design.
- Fold in the known doc lag: the `CodexConfirmed.rollout_source` docstring (`session/models.py:531-533`) lists only two
  of the three existing values (`discovered_post_exit` is missing, though `design_appendix.md` §I.1 lists all three);
  add `discovered_post_exit` and `adopted` together.

### Invariant amendments (design-doc sync owed with Phase 1)

- design.md §3.3/§3.5: `claude_session_id` gains a third origination path -- start **pre-seeds**, native fork
  **records**, adopt **binds** an existing native UUID. The manifest/conversation identity remains scalar (one manifest
  per current conversation; reattach semantics identical to a used Forge-born session).
- design.md §3.5 / `session/models.py`: add `confirmed.adoption` to the strict manifest schema and document that
  adoption provenance survives later hook-confirmed facts.
- design.md §3.10 unchanged (hooks still never scan CWD); the discovery scan is a CLI command.
- `workspace_scope` identity-table line extends to "bound when launched **or adopted**".

## Grounding (verified 2026-07-07, re-verified 2026-07-26)

- Resume evidence accepts transcript-backed sessions without hook confirmation: `cli/session_lifecycle.py:168-201`.
- `start_session(claude_session_id=...)` exists and sets `confirmed.claude_session_id`:
  `session/manager.py:411,426,636-637`.
- No code today reads native `~/.claude/projects` JSONLs for a session without a manifest; no scan/glob for unmanaged
  sessions exists (only manifest-keyed readers + `find_agent_logs`).
- `encode_project_path` handles the `/`, `.`, `_` -> `-` mapping (underscore pinned against Claude Code 2.1.158; mapping
  `session/claude/paths.py:47`, comment `:53`, `get_transcript_path` signature `:79`).
- Claude transcript entries stamp `cwd` (verified present on `user`/`assistant`/`system`/`attachment` entries in a real
  2.1.x transcript, value = the launch dir), so the Claude arm can cross-check the recorded launch dir -- the analog of
  the Codex `_rollout_head_cwd` check.
- UUID reverse lookup: `find_session_by_uuid` (`session/index.py:491`) + manifest-scan fallback
  (`core/ops/session_context.py:405`); `forge session show` already accepts raw UUIDs.
- Codex: rollout filename parser, thread-id lookup, head-line cwd extraction, `CodexConfirmed` writers, and the
  runtime-dispatched resume all verified at the paths cited above.
- Manifest reads are strict (`SessionStore.read` with dacite `strict=True`), so new confirmed fields must be model
  fields, not ad hoc dict keys.
- Search indexing is work-queue/rebuild driven; copying an artifact is necessary but not sufficient unless adoption also
  queues or performs indexing through the established idempotent path. The memory writer similarly runs from a
  successful Stop's deferred handoff marker, not from artifact presence alone.

## Risks

- **Double-attach:** a native conversation may still be live in another terminal; `ActiveSessionStore` only tracks Forge
  launches, so the active-session gate cannot see it. Adopting + resuming would put two clients on one conversation.
  Forge cannot detect this reliably. Mitigation (settled 2026-07-26, see Open questions): warn and require confirmation
  when the transcript mtime is within 30 minutes, skippable with `--yes`.
- **Stop hook rewrites the binding:** the first Forge-managed Stop unconditionally rewrites
  `confirmed.claude_session_id` (from the Stop payload's `session_id`) and `confirmed_by` to `hook:stop`
  (`cli/hooks/commands.py:179`). Adoption relies on the invariant that a plain `--resume <uuid>` reattach reports the
  **same** `session_id`, so the rewrite is idempotent; a differing id would drift the binding after one turn. **Verified
  2026-07-26 against real Claude Code 2.1.220** by `tests/integration/docker/test_adopt_binding_contract.py`, which
  asserts every Stop payload across a fresh turn and a plain reattach carries the original id. No drift guard is needed;
  that gate is the standing regression watch and its `CLAUDE_VERSION_VALIDATED` marker names the last confirmed runtime.
  `confirmed_by` is *expected* to change -- that is why provenance lives in a dedicated `confirmed.adoption` field, not
  `confirmed_by`.
- **Cross-CWD Claude sessions:** a native conversation from a different directory cannot native-resume here (§3.9
  constraint). v1 treats the current cwd as the native launch cwd and rejects with guidance (adopt from that directory);
  adopt-and-relocate via `relocate_transcript` is a natural v2 flag, not v1 scope.
- **Encoded-dir ambiguity:** `encode_project_path` is lossy (`a.b`, `a_b`, `a-b` all collide to one encoded dir), so
  scanning it can surface a sibling directory's transcript. Mitigation: both arms cross-check the recorded launch `cwd`
  (Claude via the transcript's `cwd` field, Design step 1; Codex via `_rollout_head_cwd`) and reject a mismatch rather
  than bind it. Existing readers share the lossiness but do not bind trust to it, so this cross-check is the new
  requirement adoption adds.
- **Future resume model:** bare native Claude may have used a model Forge cannot infer. `direct_model` is applied as an
  `ANTHROPIC_MODEL` env pin on the shared launch path -- including the plain `--resume` reattach (`_reconnect_in_place`
  threads it, `cli/session_lifecycle.py:1624`; env-build `core/ops/claude_session.py:1450`, calling
  `apply_direct_model_env` in `core/models/direct_model.py:86`) -- so a wrong value silently changes which model
  continues the conversation on the **first reattach**, not only on `--fresh`/fork. Adoption must make the model
  explicit (inferred or `--model`) or leave the field unset with a warning -- Design step 3 resolves this against the
  sibling proxy branch `_apply_direct_model_env_if_supported` (`session/model_pin.py:37`, applied at
  `core/ops/claude_session.py:1454`), which postdates this card and reads the stored pin without a validation gate.
- **What adoption cannot confer:** pre-adoption plan snapshots (ExitPlanMode hooks never fired), pre-adoption usage
  attribution (native interactive traffic is untracked by design -- parity with Forge-born sessions), and hook-confirmed
  history. Document as limitations, not gaps to backfill.

## Open questions

**Resolved 2026-07-26** (Slice 0 owner decisions; execution detail in [checklist.md](checklist.md)):

- **Verb**: **`adopt`**. Joins the session lifecycle-verb family (`start`/`resume`/`fork`/`clean`); `import` was
  rejected for its file-format connotation. The CLI leaf name is fixed before any op is written.
- **Discovery shape**: **bare `forge session adopt` previews** adoptable candidates; no `--list` flag is added. This
  **follows** the preview-default precedent (`session clean`, `forge clean`, `extension cleanup-project`) and the
  leaf-does-the-sensible-action rule in [cli_reference.md §1](../../../cli_reference.md#1-terminal-command-reference) --
  with no UUID supplied, listing candidates is the only sensible action.
- **Double-attach**: **warn and require confirmation** when the transcript mtime is within **30 minutes**, skippable
  with `--yes`. Deliberately not a block: Forge cannot observe a live native client (`ActiveSessionStore` tracks only
  Forge launches), so refusing on a guess would reject the most common legitimate flow -- adopting a conversation that
  just ended. The Codex-resume no-`--force` posture (design.md §3.9) is **not** mirrored, because there Forge knows the
  session is live; here it is inferring. Accepted cost: a just-finished adopt will usually confirm once.

Still open:

- ~~**Runtime ambiguity** (Phase 2): an id matching both a Claude transcript and a codex rollout requires `--runtime`.~~
  **Decided in Slice 4: refuse instead, no flag.** A dual match needs one id string to name both a Claude transcript and
  a Codex thread. Claude mints v4 UUIDs and Codex v7, and the ids come from unrelated generators, so a collision means
  something is wrong with the files rather than that the user has two real conversations to choose between. A
  `--runtime` flag would let the user assert past that instead of looking. Shipped behavior is a hard refusal naming
  both matched paths (`detect_adoption_runtime`), documented in design.md §3.3.
- **Passive sighting** (explicitly deferred): post-epic (T3 registry + T5 user-scope hooks), a SessionStart hook firing
  in an enrolled project *could* record native-session sightings to make discovery instant -- that changes the normative
  "hooks use `FORGE_SESSION` only" rule and belongs to a future card, gated on the epic landing.

## Out of scope

- Adopt-and-relocate into a different worktree (v2; `relocate_transcript` exists and is proven).
- Backfilling plan snapshots or usage events from transcript content.
- Incognito adoption; sidecar sessions (`_has_resumable_transcript` correctly refuses `is_sandboxed`).
- Any hook behavior change.

## Acceptance tests

| Test                              | Fixture                                                                                                               | Assertion                                                                                                                                         | Test File                                                                     |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Adopt binds + reattach            | native `<uuid>.jsonl` in exact encoded cwd                                                                            | manifest has `claude_session_id=<uuid>` + `claude_project_root`; resume argv `--resume <uuid>`, no `--fork-session`                               | `tests/src/cli/test_session_adopt.py` (new)                                   |
| Adopted model is explicit         | native transcript with model metadata / two real models / no assistant turn                                           | inferred (**last** real model) or `--model` value persists; the no-basis path warns and leaves `direct_model` unset                               | same                                                                          |
| Adoption adds no model pin        | adopted with no model basis, then `resume --proxy <id>`                                                               | `direct_model` is `None` and `model_basis` is `none`, so the adopted manifest contributes no `ANTHROPIC_MODEL` (ambient env is out of scope)      | same                                                                          |
| Adoption schema round trip        | adopted manifest read through `SessionStore.read`                                                                     | strict read/write preserves `confirmed.adoption` incl. `model_basis`; unknown ad hoc keys are not required                                        | `tests/src/session/test_models.py` or same                                    |
| Adopt queues search indexing      | adopted transcript artifact                                                                                           | copied artifact is passed through the normal index marker/index path; `search query` can find it after processing                                 | same                                                                          |
| Adopt does not run memory writer  | memory-enabled adopted session before any Forge Stop                                                                  | no handoff marker is created at adopt; first simulated Stop enqueues memory work with the full transcript snapshot                                | same                                                                          |
| Already-bound reject              | UUID present in index / a manifest                                                                                    | error names the owning session; no state created                                                                                                  | same                                                                          |
| Missing transcript reject         | UUID with no JSONL on disk                                                                                            | fail-closed error; no manifest, no index entry                                                                                                    | same                                                                          |
| Outside Forge project reject      | cwd without `.forge/`                                                                                                 | error names `forge extension enable`                                                                                                              | same                                                                          |
| Project compatibility guard       | incompatible `.forge/project.toml`                                                                                    | command-path mutation blocks before manifest/artifact/index writes; missing file remains compatible                                               | same                                                                          |
| Discovery lists unbound only      | two native transcripts in exact cwd, one already bound                                                                | listing shows the unbound one only and names the cwd scanned                                                                                      | same                                                                          |
| Subdir exact-CWD guidance         | native transcript launched from subdir, command run at root                                                           | root preview/adopt does not misattribute; diagnostic says to run from the native launch directory                                                 | same                                                                          |
| Provenance survives Stop          | adopted session, then simulated Stop capture                                                                          | `confirmed.adoption` intact and `confirmed.claude_session_id` unchanged while `confirmed_by` becomes `hook:stop`                                  | same                                                                          |
| Adopted transfer works            | adopted manifest, `resume --fresh`                                                                                    | transfer context assembled from the native transcript                                                                                             | same                                                                          |
| Codex adopt binds (Phase 2)       | rollout fixture with matching head cwd                                                                                | `confirmed.codex.thread_id` set, `rollout_source="adopted"`; resume dispatches `codex resume <thread>`                                            | same                                                                          |
| Codex rollout mismatch reject     | rollout fixtures with wrong cwd / duplicate matching cwd                                                              | adoption rejects cwd mismatch and multiple candidates instead of silently choosing newest                                                         | same                                                                          |
| Claude cwd cross-check reject     | native transcript whose recorded `cwd` differs from the run cwd (lossy-encoding sibling)                              | adoption rejects on recorded-`cwd` mismatch instead of binding the sibling's transcript                                                           | same                                                                          |
| Partial-failure leaves no binding | (a) `add_from_state` raises inside `start_session`; (b) adoption's artifact copy raises after `start_session` returns | both leave no UUID-bound session and no manifest; re-running `adopt` succeeds cleanly                                                             | same                                                                          |
| Rollback spares the native source | adopt fails after the artifact copy                                                                                   | the native `~/.claude/projects/<enc>/<uuid>.jsonl` still exists byte-identical; no worktree/branch was removed; no manifest or index row survives | same                                                                          |
| Concurrent adopt binds once       | two `adopt` calls racing on one UUID                                                                                  | exactly one succeeds; the loser gets the already-bound reject and creates no manifest or index entry                                              | same                                                                          |
| Reattach identity (**shipped**)   | Forge session, one fresh `--print` turn, then a plain `--resume` turn                                                 | every Stop payload's `session_id` equals the original; one UUID-named artifact; both prompts in the one transcript                                | `tests/integration/docker/test_adopt_binding_contract.py` (slow, real Claude) |
| Real-Claude adoption gate         | bare-`claude` conversation created in container                                                                       | adopt + `claude --resume <uuid>` continues the conversation (manifest Forge never launched)                                                       | `tests/integration/docker/` (slow, real Claude)                               |
