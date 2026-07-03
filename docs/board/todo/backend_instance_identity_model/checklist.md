# Checklist -- backend_instance_identity_model

**Lane**: `todo/` -- draft only. Move this card to `doing/`, create/switch to its execution branch, and re-verify this
checklist before ticking items.

## Phase 0 -- Activation

- [ ] Create or switch to the execution branch.
- [ ] Move `docs/board/todo/backend_instance_identity_model/` to `docs/board/doing/backend_instance_identity_model/`.
- [ ] Re-read `doing/cli_style_ux_compliance` C2/OQ-2 so the migration does not undo the CLI terminology decision.
- [ ] Re-verify current backend identity surfaces before changing code.

## Phase 1 -- Inventory current contracts

- [ ] Enumerate persisted fields and JSON keys: `source_id`, `backend_id`, `runtime_instance`, `proxy.source`, backend
  registry files, telemetry ledgers, and proxy templates. **Assertion:** every reader/writer has an owner and migration
  risk noted.
- [ ] Enumerate human-facing terms in CLI help, end-user docs, design docs, and board implementation notes.
  **Assertion:** the inventory separates public terminology drift from machine-contract names.
- [ ] Capture local LiteLLM sharing behavior. **Assertion:** the design explicitly handles one local process backing
  multiple existing source/catalog rows.

## Phase 2 -- Design decision

- [ ] Decide whether the target model is a rename of `ModelSource` or a split into backend kind + backend instance.
  **Assertion:** examples cover `openrouter`, `claude-max`, future duplicate remotes, and local `litellm-4000`.
- [ ] Decide telemetry identity semantics. **Assertion:** downstream `backend_id` meaning is explicit for singleton
  remotes, duplicate remotes, and local managed LiteLLM.
- [ ] Decide config compatibility. **Assertion:** `proxy.source` and any proposed successor have a read/write migration
  plan and user-facing error behavior for ambiguous aliases.

## Phase 3 -- Implementation slices

- [ ] Land schema/domain changes behind compatibility readers first.
- [ ] Migrate CLI help and docs only after machine contracts are clear.
- [ ] Add alias/ambiguity tests before removing or deprecating old names.
- [ ] Keep remote backend instances connection/auth-only unless a later card adds remote CRUD.

## Verification

| Test area                 | Fixture                                      | Assertion                                                       |
| ------------------------- | -------------------------------------------- | --------------------------------------------------------------- |
| Compatibility readers     | old `proxy.source` / old JSON fields         | old configs still load or fail with a migration tip             |
| Remote duplicate identity | two instances of the same remote kind        | instance ids disambiguate; singleton aliases do not mis-route   |
| Local LiteLLM sharing     | one local process backs multiple source rows | telemetry/config behavior remains deliberate and documented     |
| Runtime terminology guard | CLI/docs surfaces                            | `runtime` means agent/frontend runtime, not backend instance    |
| Telemetry migration       | pre- and post-migration records              | readers expose documented backend identity without silent drift |

## Closeout

- [ ] Design docs and end-user docs updated for shipped behavior.
- [ ] `docs/board/impl_notes.md` updated only with durable invariants after human review.
- [ ] `docs/board/change_log.md` entry added when code ships.
- [ ] Card moved to `done/` after verification and review.
