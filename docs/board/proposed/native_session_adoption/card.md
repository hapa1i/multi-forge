# Adopt native Claude Code / Codex sessions (`forge session adopt`)

**Lane**: `proposed/` -- design sketch, not yet accepted for execution. Standalone (not an `epic_global_forge_runtime`
member); relates to the session identity model (design.md §3.3/§3.5) and complements
[`workspace_scope`](../workspace_scope/card.md), whose identity table says a native Claude session is "bound to a Forge
session **when launched**" -- this card adds binding **after the fact**.

**Origin**: user request (2026-07-07) -- pick up a session started outside Forge (bare `claude`, bare `codex`) and
resume it as a managed Forge session. Primary driver: **native Claude** pickup; Codex is a structured second phase.

**Revised 2026-07-07** after a grounding-verified doc review -- all cited code claims were confirmed against current
source. This revision adds the Stop-hook `claude_session_id`-rewrite risk, a Claude-side recorded-`cwd` cross-check
(symmetric to the Codex arm), pins where `direct_model` takes effect, states the native-reattach durability caveat plus
adopt write ordering, and corrects two precision points (`rollout_source` is an unvalidated `str`; refreshed drifted
line refs).

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
- `SessionManager.start_session` already accepts an injected `claude_session_id` (`session/manager.py:421`, set at
  `:620-621`) -- only the CLI op layer lacks a way to pass an existing UUID (`start_claude_session` always generates a
  fresh one, `core/ops/claude_session.py:544`).
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
   implicit surprise: infer it from transcript metadata when present, accept `--model` as an override, and otherwise
   warn that Forge will persist the current direct default as the model used for subsequent Forge resumes. This is
   load-bearing on the **reattach** path, not only `--fresh`/fork: `direct_model` is applied as an `ANTHROPIC_MODEL` env
   pin in the shared launch env-builder (`core/ops/claude_session.py:1411-1416`, the `runtime_base_url is None` branch),
   and `_reconnect_in_place` threads it into the RECONNECT plan (`cli/session_lifecycle.py:1658`), so a wrong value
   silently changes which model continues the conversation on the first plain `--resume`. Pre-seed
   `confirmed.claude_project_root` (precedent: relocate and rewind both pre-seed it, `cli/session_fork.py:896`,
   `cli/session_rewind.py:214`).
4. **Provenance schema:** add a strict dataclass field for `confirmed.adoption` (for example
   `{source_runtime, adopted_at, source_path}`) and model/store round-trip tests. `confirmed_by="cli:adopt"` alone is
   insufficient -- the next Stop hook overwrites `confirmed_by` (`hook:stop`) **and rewrites
   `confirmed.claude_session_id` from the Stop payload** (`cli/hooks/commands.py:146-158`), so adoption provenance needs
   its own field to survive (see the Stop-rewrite risk). CLI-written confirmed fields are established precedent
   (`derivation`, `launch`, `confirmed.codex` -- design.md §3.5).
5. **Transcript artifact copy at adopt time** (reason `"adopt"`, same entry shape as the Stop hook's,
   `cli/hooks/commands.py:133-144`): makes the history immediately available to transfer and durable against native-side
   cleanup. The copy protects only **transfer / `--fresh`** (which read Forge's artifact); native
   `claude --resume <uuid>` reads Claude's own `~/.claude/projects` store, so plain reattach still requires the original
   native JSONL to survive (a limitation, not a gap -- see Risks). Queue the normal search-index marker for that copied
   artifact, or otherwise index it through the same idempotent path as Stop; do **not** enqueue memory-writer work at
   adopt time. Memory remains tied to a successful Stop handoff; StopFailure captures and indexes only. The first
   Forge-managed successful Stop after adoption therefore queues curation of the complete transcript when session memory
   is enabled.
6. **Index entry** via `add_from_state` (copies the UUID, `session/index.py:485`), so UUID-collision checks and
   `session show <uuid>` work immediately.

**Write ordering (fail-closed atomicity).** Validate every precondition first (steps 1-2), then construct the manifest
(3-4), copy the artifact (5), and add the index entry (6) last. A failure before the index write must leave no
UUID-bound session (the reject tests assert this), so on any mid-sequence error remove a partially written
manifest/artifact and let the user re-run cleanly. Re-adopting an already-bound UUID is the *already-bound reject* path,
never a silent overwrite.

### Discovery (`forge session adopt` bare)

Scan `~/.claude/projects/<encode_project_path(current cwd)>/*.jsonl` (`session/claude/paths.py:74`) for UUIDs not bound
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
  `cli/session_lifecycle.py:1340`; defined in `cli/session_codex.py:237`), cross-CWD by design.
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

## Grounding (verified 2026-07-07)

- Resume evidence accepts transcript-backed sessions without hook confirmation: `cli/session_lifecycle.py:159-206`.
- `start_session(claude_session_id=...)` exists and sets `confirmed.claude_session_id`:
  `session/manager.py:421,620-621`.
- No code today reads native `~/.claude/projects` JSONLs for a session without a manifest; no scan/glob for unmanaged
  sessions exists (only manifest-keyed readers + `find_agent_logs`).
- `encode_project_path` handles the `/`, `.`, `_` -> `-` mapping (underscore pinned against Claude Code 2.1.158; mapping
  `session/claude/paths.py:74`, comment `:53`, `get_transcript_path` signature `:79`).
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
  Mitigation lean: warn (require confirm) when the transcript mtime is recent; Forge cannot detect this reliably.
- **Stop hook rewrites the binding:** the first Forge-managed Stop unconditionally rewrites
  `confirmed.claude_session_id` (from the Stop payload's `session_id`) and `confirmed_by` to `hook:stop`
  (`cli/hooks/commands.py:146-158`). Adoption relies on the invariant that a plain `--resume <uuid>` reattach reports
  the **same** `session_id`, so the rewrite is idempotent; if a resumed conversation ever reports a different id the
  binding drifts after one turn. `confirmed_by` is *expected* to change -- that is why provenance lives in a dedicated
  `confirmed.adoption` field, not `confirmed_by`.
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
  threads it, `cli/session_lifecycle.py:1658`; env-build `core/ops/claude_session.py:1411-1416`) -- so a wrong value
  silently changes which model continues the conversation on the **first reattach**, not only on `--fresh`/fork.
  Adoption must make the model explicit (inferred, `--model`, or warned-and-persisted default).
- **What adoption cannot confer:** pre-adoption plan snapshots (ExitPlanMode hooks never fired), pre-adoption usage
  attribution (native interactive traffic is untracked by design -- parity with Forge-born sessions), and hook-confirmed
  history. Document as limitations, not gaps to backfill.

## Open questions

- **Verb**: `adopt` vs `import` (lean: `adopt` -- lifecycle-verb family, no file-format connotation).
- **Discovery shape**: bare `adopt` lists (preview-default precedent: `session clean`) vs an explicit `--list` flag.
- **Recent-mtime threshold** for the double-attach warning, and warn-vs-block.
- **Runtime ambiguity** (Phase 2): an id matching both a Claude transcript and a codex rollout requires `--runtime`.
- **Passive sighting** (explicitly deferred): post-epic (T3 registry + T5 user-scope hooks), a SessionStart hook firing
  in an enrolled project *could* record native-session sightings to make discovery instant -- that changes the normative
  "hooks use `FORGE_SESSION` only" rule and belongs to a future card, gated on the epic landing.

## Out of scope

- Adopt-and-relocate into a different worktree (v2; `relocate_transcript` exists and is proven).
- Backfilling plan snapshots or usage events from transcript content.
- Incognito adoption; sidecar sessions (`_has_resumable_transcript` correctly refuses `is_sandboxed`).
- Any hook behavior change.

## Acceptance tests

| Test                              | Fixture                                                                                  | Assertion                                                                                                           | Test File                                       |
| --------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| Adopt binds + reattach            | native `<uuid>.jsonl` in exact encoded cwd                                               | manifest has `claude_session_id=<uuid>` + `claude_project_root`; resume argv `--resume <uuid>`, no `--fork-session` | `tests/src/cli/test_session_adopt.py` (new)     |
| Adopted model is explicit         | native transcript with model metadata / no metadata                                      | inferred or `--model` value persists; no-metadata path warns and persists the direct default used for future resume | same                                            |
| Adoption schema round trip        | adopted manifest read through `SessionStore.read`                                        | strict read/write preserves `confirmed.adoption`; unknown ad hoc keys are not required                              | `tests/src/session/test_models.py` or same      |
| Adopt queues search indexing      | adopted transcript artifact                                                              | copied artifact is passed through the normal index marker/index path; `search query` can find it after processing   | same                                            |
| Adopt does not run memory writer  | memory-enabled adopted session before any Forge Stop                                     | no handoff marker is created at adopt; first simulated Stop enqueues memory work with the full transcript snapshot  | same                                            |
| Already-bound reject              | UUID present in index / a manifest                                                       | error names the owning session; no state created                                                                    | same                                            |
| Missing transcript reject         | UUID with no JSONL on disk                                                               | fail-closed error; no manifest, no index entry                                                                      | same                                            |
| Outside Forge project reject      | cwd without `.forge/`                                                                    | error names `forge extension enable`                                                                                | same                                            |
| Project compatibility guard       | incompatible `.forge/project.toml`                                                       | command-path mutation blocks before manifest/artifact/index writes; missing file remains compatible                 | same                                            |
| Discovery lists unbound only      | two native transcripts in exact cwd, one already bound                                   | listing shows the unbound one only and names the cwd scanned                                                        | same                                            |
| Subdir exact-CWD guidance         | native transcript launched from subdir, command run at root                              | root preview/adopt does not misattribute; diagnostic says to run from the native launch directory                   | same                                            |
| Provenance survives Stop          | adopted session, then simulated Stop capture                                             | `confirmed.adoption` intact and `confirmed.claude_session_id` unchanged while `confirmed_by` becomes `hook:stop`    | same                                            |
| Adopted transfer works            | adopted manifest, `resume --fresh`                                                       | transfer context assembled from the native transcript                                                               | same                                            |
| Codex adopt binds (Phase 2)       | rollout fixture with matching head cwd                                                   | `confirmed.codex.thread_id` set, `rollout_source="adopted"`; resume dispatches `codex resume <thread>`              | same                                            |
| Codex rollout mismatch reject     | rollout fixtures with wrong cwd / duplicate matching cwd                                 | adoption rejects cwd mismatch and multiple candidates instead of silently choosing newest                           | same                                            |
| Claude cwd cross-check reject     | native transcript whose recorded `cwd` differs from the run cwd (lossy-encoding sibling) | adoption rejects on recorded-`cwd` mismatch instead of binding the sibling's transcript                             | same                                            |
| Partial-failure leaves no binding | adopt fails after the manifest write, before the index entry                             | no UUID-bound session remains; re-running `adopt` succeeds cleanly                                                  | same                                            |
| Real-Claude adoption gate         | bare-`claude` conversation created in container                                          | adopt + `claude --resume <uuid>` continues the conversation (manifest Forge never launched)                         | `tests/integration/docker/` (slow, real Claude) |
