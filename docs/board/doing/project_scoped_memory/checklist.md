# Project-Scoped Memory Checklist

Manual multi-session plan for executing [`card.md`](./card.md).

This card is in `doing/` on branch `project-scoped-memory`. Move the whole `project_scoped_memory/` directory to
`docs/board/done/` after closeout (final merge to `main`).

## Maintenance

- Update this file during implementation sessions and once before ending a session.
- Keep tasks high-level, with concrete assertions that prove completion.
- Tick a task only when the assertion is satisfied and verification is recorded.
- Add short blocker notes inline under the relevant phase.
- Move completed-session details to `docs/board/change_log.md`; keep only active plan state here.
- Promote durable lessons to `docs/board/impl_notes.md` after human review.
- Update design docs per-phase as code ships (design docs are normative, not aspirational).
- Move the card directory to `docs/board/done/<slug>/` after the card is fully executed.

```bash
wc -l docs/board/doing/project_scoped_memory/checklist.md
./scripts/count-tokens.py --model <agent-model> docs/board/doing/project_scoped_memory/checklist.md
```

## Current Focus

Slice 1: make project memory activation real via a checkout-local `.forge/memory.yaml` and one shared activation gate
consulted at both the Stop-hook enqueue site and the detached runner. Additive, no schema break, no `track` change.

## Phase 0 - Baseline & Decisions

- [x] Verify the card's load-bearing code references (record file:line).
  - Verification: enqueue gate `src/forge/cli/hooks/commands.py:520` (`effective.memory.auto_update.enabled`); detached
    re-check `src/forge/cli/handoff.py:64` (`store.exists()` no-op) and `:74-79` (`auto_update.enabled`); writer
    selector `src/forge/session/passport.py:681` `check_writer_access`; `MemoryStrategy` enum `:35`;
    `validate_writer_spec` `:641` (rejects `lineage:`/`role:`); incognito read `src/forge/session/shadow_curation.py:70`
    (`list_sessions(include_incognito=False)`). No `memory.yaml` references exist anywhere yet (net-new state).
- [ ] Re-confirm the second incognito read the card cites as `memory.py:743`.
  - Assertion: identify the exact file/line (likely `cli/memory.py` `status_cmd`) or correct the card reference. Do not
    trust the citation as written.
- [ ] Anchor Phase 1 test sites.
  - Assertion: locate the Stop-hook enqueue test covering `commands.py:520` and the `run_cmd` test in
    `tests/src/cli/test_handoff.py`; name them in the Slice-1 acceptance table.
- [ ] Settle the two Slice-1 gating decisions (the rest defer to Phase 2/Open Decisions).
  - Assertion: (a) scan-root default + how it is configured (project-config key vs fixed convention); (b) bare
    `forge memory enable` semantics -- project config vs ambient session (see Phase 1 enable task). Incognito exclusion
    is already decided by the card (Risks: resolver excludes `is_incognito`), not open. Record decisions before writing
    resolver code.

## Phase 1 - Slice 1: Project Activation + Shared Gate (additive, no schema break)

- [ ] Add versioned project-scoped `<forge_root>/.forge/memory.yaml`.
  - Assertion: modeled on strict durable-state readers -- `SessionStore` (`store.py:40` `_SUPPORTED_SCHEMA_VERSIONS`,
    `:262-269` raises `ManifestCorruptedError` on unsupported version) and the session index (`index.py:109-116`,
    "Delete this file and retry"). NOT `runtime_config.py`, which is intentionally optional/fail-open/unversioned and
    ignores unknown keys -- the wrong precedent for Forge-owned durable state. Mandatory `version`, strict
    deserialization, clear unsupported-version error (coding-standards §5). Holds operational state only
    (`auto_update: {enabled, mode, min_turns, proxy}`); no `docs:` list.
- [ ] Implement the shared resolver `memory_activation(session, project) -> ActivationConfig | None`.
  - Assertion: project config plus a *sparse field-wise* session override; returns `None` for `is_incognito` sessions.
  - Implementation note: derive the session override from a tri-state source -- raw `intent`/`overrides` leaf-key
    presence (overrides are persisted per-leaf-key, e.g. `memory.auto_update.enabled`, `memory.py:208`). Do NOT read
    `compute_effective_intent()`: it materializes `HandoffConfig` defaults (`models.py:95-99`: `enabled=False`,
    `mode="augment"`, `min_turns=5`), collapsing "unset" into "explicit false/default". Both gates currently consume the
    materialized config (`handoff.py:69`, `memory.py:187`); the resolver must not.
- [ ] Wire the resolver into **both** gates.
  - Assertion: the enqueue gate (`commands.py:520`) and the detached `run_cmd` (`handoff.py:74-79`) both call the single
    resolver. Load-bearing: if the hook does not enqueue, the runner never runs, so a project enable is inert unless
    both sites consult it.
- [ ] Stop discovery = scan + select.
  - Assertion: a session-layer discovery helper scans bounded memory roots for `forge_memory` frontmatter (unit-testable
    in isolation); `run_cmd` unions it with session `designated_docs` and de-dupes by passport source / write path at
    `handoff.py:97` (today `designated_docs = effective.memory.designated_docs`, passed to `run_handoff_agent` at
    `:106`). `run_handoff_agent` is unchanged -- selection stays via `check_writer_access` (already covered by
    `TestWriterFiltering` in `tests/src/session/test_handoff_agent.py`).
- [ ] Bound the scan.
  - Assertion: walk only configured roots (default `docs/`, `.forge/memory/`); never `.git/`, `node_modules/`, etc.
- [ ] `forge memory enable` (no `--session`) writes `.forge/memory.yaml`.
  - Assertion: `--review-only` sets review mode for the safe first run; consent output names the checkout; project-level
    enable removes the need for per-session enable/re-track for passported docs in this checkout.
- [ ] Pin `enable` session-vs-project semantics (behavior change, not purely additive).
  - Assertion: `enable --session X` stays session-scoped (writes the sparse override via leaf keys
    `memory.auto_update.*`, current behavior at `memory.py:179-216`). Bare `enable` writes project config and does NOT
    consult ambient `$FORGE_SESSION` (mirrors the bare-`track` rule). This shifts the meaning of in-session bare
    `enable` (today it targets the ambient session) -- call it out in the change_log. Regression test the `--session`
    path stays session-scoped.
- [ ] Design docs: update `design.md §5.6` and `design_appendix.md §G`.
  - Assertion: ownership is stated as passport (doc contract) vs project activation (checkout consent) vs session
    override (sparse). Reflects shipped Slice-1 behavior, not the full card target.

Acceptance tests (Slice 1):

| Test                         | Fixture                                  | Assertion                                    | Test File                          |
| ---------------------------- | ---------------------------------------- | -------------------------------------------- | ---------------------------------- |
| resolver project-only        | project `memory.yaml`, session silent    | returns project `ActivationConfig`           | `test_memory_activation.py`        |
| resolver sparse override     | project enabled, session `mode=review`   | merged; unset fields inherit project         | `test_memory_activation.py`        |
| resolver unset vs false      | raw override `enabled` unset vs false    | distinguishes (tri-state, pre-materialize)   | `test_memory_activation.py`        |
| resolver incognito           | `is_incognito` session                   | returns `None` (no enqueue)                  | `test_memory_activation.py`        |
| discovery helper             | 2 in-root passports, 1 out-of-root       | only in-root passports returned              | `session/test_memory_discovery.py` |
| scan bounding                | repo with `.git/`, `node_modules/`       | excluded from walk                           | `session/test_memory_discovery.py` |
| run_cmd union/dedup          | scanned passports + session `designated` | passes ∪, de-duped, into `run_handoff_agent` | `cli/test_handoff.py`              |
| enqueue gate uses resolver   | project-enabled, session silent          | Stop hook enqueues handoff marker            | (stop-hook enqueue test)           |
| run_cmd gate uses resolver   | project-enabled, session silent          | `run_cmd` proceeds (not gated out)           | `cli/test_handoff.py`              |
| enable writes project config | bare `enable`, no `--session`            | `.forge/memory.yaml` v1 written              | `cli/test_memory.py`               |
| enable --session scoped      | `enable --session X`                     | writes session override, not project file    | `cli/test_memory.py`               |
| bare enable ignores ambient  | `$FORGE_SESSION` set, bare `enable`      | writes project, not the ambient session      | `cli/test_memory.py`               |
| unsupported version          | `memory.yaml` `version: 999`             | clear error, no silent default               | `cli/test_memory.py`               |

## Phase 2 - Slice 2: Sessionless / Stateless `track`

- [ ] `track_cmd` writes/updates the passport only.
  - Assertion: drop the participation write (`memory.designated_docs` override); validate against `ctx.forge_root` (the
    path `passport_show_cmd` already uses); warn when the doc is outside the memory roots.
- [ ] Bare `track` never consults the ambient session.
  - Assertion: `forge memory track <doc>` is passport-only even when `$FORGE_SESSION` is set (no invisible
    ambient-session behavior).
- [ ] Explicit spelling for per-session manifest-only extras.
  - Assertion: a typed `--session` path (e.g. `forge memory extra add <doc> --session <name>`) records the one case the
    scan cannot express; CLI warns when a "session" doc will be project-discovered anyway.
- [ ] Authoring no longer requires a session.
  - Assertion: `enable`/`track` succeed from a bare terminal; removed coupling fails helpfully where a session is truly
    needed (coding-standards §5 clean break + changelog entry).
- [ ] Docs: rewrite `docs/board/README.md` "Handoff Agent Setup" + "Advanced Workflow" to passport-once +
  per-checkout-enable (the card's Worked Example); update `design.md §5.6`.

Acceptance tests (Slice 2):

| Test                    | Fixture                            | Assertion                                       | Test File            |
| ----------------------- | ---------------------------------- | ----------------------------------------------- | -------------------- |
| track passport-only     | doc w/o passport, `--as changelog` | passport written, no `designated_docs` override | `cli/test_memory.py` |
| track ignores ambient   | `$FORGE_SESSION` set, bare track   | no participation write                          | `cli/test_memory.py` |
| track warns out-of-root | doc outside roots                  | warning emitted                                 | `cli/test_memory.py` |
| explicit extras         | `extra add --session X`            | manifest-only entry recorded                    | `cli/test_memory.py` |

## Phase 3 - Slice 3 (optional): Decommission / Deprecate `designated_docs`

- [ ] Decide: deprecate `designated_docs` or retain it as the per-session extras escape hatch.
  - Assertion: decision recorded with rationale; if retained, it is the *only* per-session participation surface.
- [ ] Add a passport-removal path.
  - Assertion: `forge memory passport remove` (or `untrack --remove-passport`) makes "no longer a memory doc" a command,
    not hand-editing.
- [ ] If deprecating: helpful failure + changelog + reset guidance (coding-standards §5).

## Open Decisions

Tracks Forge-local execution decisions. For broader card framing, see
[`card.md` Open questions](./card.md#open-questions).

- [ ] Scan roots default + config mechanism (`docs/` + `.forge/memory/`; project-config key vs fixed convention)? —
  gates Slice 1.
- [ ] Keep `writers: all-sessions` as the synthesized default, or default to a more conservative writer to bound blast
  radius?
- [ ] Exact CLI spelling that replaces `track --session` for manifest-only extras?
- [ ] `fork --worktree`: copy the local `.forge/memory.yaml`, or only warn that the new checkout needs
  `forge memory enable`?
- [ ] Deprecate `--inherit-memory` for doc participation once git carries passports; warn on uncommitted passports
  before a worktree fork?

## Closeout (per [work-board contract](../../../developer/work-board-contract.md#closeout))

- [ ] Final compact `change_log.md` entry with verification.
- [ ] Promote durable lessons to `impl_notes.md` after human review.
- [ ] Verify `design.md §5.6`, `design_appendix.md §G`, and `docs/board/README.md` reflect all shipped changes.
- [ ] `git mv` the card directory `doing/ -> done/` after final merge to `main`.
