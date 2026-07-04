# Checklist -- backend_instance_identity_model

**Branch**: `feat/backend-instance-identity-model` - **Card**: [`card.md`](card.md)

**Current focus**: Phase 1 inventory. Phase 0 activation is complete. Next action: enumerate the machine-readable
backend identity surfaces into `inventory.md` (this card dir) before choosing the schema/domain migration shape. No
`src/` change until Phase 2 fixes the target model.

## Invariants (do not violate during migration)

- **Do not undo C2.** `done/cli_style_ux_compliance` C2 shipped public backend / backend-instance / adapter wording
  while deliberately keeping `source_id`, `runtime_instance`, `BackendInstance.backend_id`, and telemetry `backend_id`
  stable. Any change to those machine names must be a deliberate, compat-guarded migration in this card -- never an
  incidental rename riding along a wording pass.
- **Runtime vocabulary stays the lane runtime axis.** `runtime` means the `forge.core.runtime_vocab` axis -- agent
  runtimes `claude_code` / `codex` / `gemini` plus the in-process `core_llm` -- never a model backend (kind, instance,
  or local process).
- **Local lifecycle stays local-only.** Remote backend instances gain no fake start/stop semantics; managed PID/port
  state attaches only to local instances.
- **`proxy.yaml` `source` (and any successor) is a system boundary** (user-owned): unknown values warn-and-degrade on
  the runtime `proxy.yaml` read path. The strict reject-on-unknown contract is scoped to the **template load path**
  (`_apply_template_source`) -- shipped *or* user templates, since `read_template` prefers the user copy -- not the
  runtime `proxy.yaml` read path.

## Phase 0 -- Activation (complete)

- [x] Create or switch to the execution branch.
- [x] Move `docs/board/todo/backend_instance_identity_model/` to `docs/board/doing/backend_instance_identity_model/`.
- [x] Re-read `done/cli_style_ux_compliance` C2/OQ-2 so the migration does not undo the CLI terminology decision
  (captured as the first Invariant above).

## Phase 1 -- Inventory current contracts

**Deliverable**: `inventory.md` (this card dir) -- the raw work-product Phase 2 decides from. Inventory stays in the
card dir; it is not promoted to design docs.

- [ ] Enumerate persisted fields and JSON keys with their reader(s) and writer(s): `ModelSource.id`, `source_id`,
  `source_kind`, `BackendInstance.backend_id`, `runtime_instance`, telemetry `backend_id`, `proxy.source`, the backend
  registry (`~/.forge/backends/index.json`), telemetry ledgers, and proxy templates. **Assertion:** every reader/writer
  is named with a file path and a boundary tag -- strict durable state vs system boundary vs display-only -- so Phase 2
  knows which fields can clean-break and which need compat readers.
- [ ] Enumerate human-facing terms in CLI help, end-user docs, design docs, and board notes. **Assertion:** the
  inventory separates already-migrated public terminology (C2) from still-legacy machine-contract names, so Phase 3
  never re-touches a C2 surface.
- [ ] Capture local LiteLLM sharing behavior. **Assertion:** the inventory shows the concrete many-to-one case -- one
  `litellm-4000` process backing both `litellm-gemini-local` and `litellm-openai-local` -- and names
  `_local_source_matches_backend_config` (`cli/backend.py`) as **display-only**, never a telemetry-attribution source.

## Phase 2 -- Design decision

**Deliverable**: decisions recorded in `card.md` as the chosen target architecture; promoted to `design.md` /
`design_appendix.md §A.2.1` only when the corresponding code ships (board contract: cards are aspirational, design docs
are contract).

- [ ] **OQ-1 -- object shape.** Decide whether the target is a rename of `ModelSource` or a split into backend kind +
  backend instance. **Assertion:** worked through concrete examples -- `openrouter`, `claude-max`, a hypothetical second
  remote of the same kind, and local `litellm-4000` -- each landing on exactly one canonical object.
- [ ] **OQ-2 -- telemetry identity.** Decide what downstream `backend_id` means post-migration. **Assertion:** the
  meaning is stated for singleton remotes, duplicate remotes, and shared local LiteLLM, and says whether existing
  records need a read-path alias or backfill (no silent attribution drift; keep `backend_id` distinct from the
  `source_id`/`source_kind` origin axis).
- [ ] **OQ-3/OQ-4 -- config + ambiguity.** Decide the config spelling and the singleton-to-duplicate transition.
  **Assertion:** `proxy.source` and any successor have a read/write migration plan, and a second instance of a kind
  makes the bare kind name **fail loudly**, not mis-route to one instance.
- [ ] **OQ-5 -- scope boundary.** Decide foundation-only vs remote-instance CRUD, explicitly and with rationale.
  **Assertion:** the card states the choice (non-goals currently lean foundation-only -- confirm or overturn, do not
  leave it implicit in a Phase 3 guardrail), and the Phase 3 slice list matches it.

## Phase 3 -- Implementation slices (PROVISIONAL -- expand after Phase 2)

These are ordering guardrails, not fixture-grounded slices. Do not tick or expand them into real slices until the Phase
2 decision fixes the schema -- expanding now would bake in the wrong slices.

_Slice-ordering guardrails:_

- Land schema/domain changes behind compatibility readers first.
- Migrate CLI help and docs only after machine contracts are clear.
- Add alias/ambiguity tests before removing or deprecating old names.
- Keep remote backend instances connection/auth-only unless a later card adds remote CRUD.

_Remaining Phase 3 task:_

- [ ] Expand this phase into fixture-grounded slices (each with an assertion and a test file) once Phase 2 lands, and
  fill the Verification table's `Test File` column as those slices ship.

## Verification (PROVISIONAL -- fixtures/files pending the Phase 2 schema decision)

| Test area                 | Fixture                                | Assertion                                                                                         | Test File |
| ------------------------- | -------------------------------------- | ------------------------------------------------------------------------------------------------- | --------- |
| Compatibility readers     | old `proxy.source` / old JSON fields   | old configs load, or fail with a migration tip naming the successor                               | TBD       |
| Remote duplicate identity | two instances of one remote kind       | distinct instance ids resolve; the bare kind name errors, not mis-routes                          | TBD       |
| Local LiteLLM sharing     | one process backs multiple source rows | `list`/`show` still mark the instance `(shared)`; telemetry attribution follows the OQ-2 decision | TBD       |
| Runtime terminology guard | CLI/docs help surfaces                 | `runtime` never labels a backend instance (guard/grep test)                                       | TBD       |
| Telemetry migration       | pre- and post-migration records        | both shapes read the documented backend identity; no silent attribution loss                      | TBD       |

## Closeout

- [ ] Design docs and end-user docs updated for shipped behavior.
- [ ] `docs/board/impl_notes.md` updated only with durable invariants after human review.
- [ ] `docs/board/change_log.md` entry added when code ships.
- [ ] Card moved to `done/` after verification and review.
