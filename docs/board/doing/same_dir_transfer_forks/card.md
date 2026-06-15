# Same-Directory Transfer Forks -- make curated context explicit

**Status**: In progress (`doing/`) — execution branch `same_dir_transfer_forks`; see [checklist.md](checklist.md).
Spun out of the `supervisor_shadow_sampling` investigation on 2026-06-14, after
`forge session fork ... --strategy ai-curated --inline-plan` silently used native same-directory resume instead of an
AI-curated transfer.

**References**: `src/forge/cli/session_fork.py` same-directory native fork path, worktree transfer path, and limited
transfer-flag validation; `docs/end-user/transfer.md` strategy documentation.

**Related**: supervisor cascade/checker launch controls and effort plumbing are split into
`docs/board/proposed/supervisor_launch_controls/card.md` so this card can proceed independently.

## Problem

`ai-curated` is a transfer strategy, but the `fork` CLI makes it look like a general fork strategy.

Today `forge session fork` has two behavior families:

- **Same-directory fork**: launches Claude with `--resume <parent> --fork-session`, preserving the parent conversation
  natively. No transfer document is generated, so `--strategy` and `--inline-plan` are ignored.
- **Worktree/`--into` fork**: launches a fresh child session with a generated transfer context. This is where
  `--strategy minimal|structured|full|ai-curated` and `--inline-plan` apply.

That distinction is internally reasonable, but the user-facing command is surprising:

```bash
forge session fork neat-bloodhound \
  --name neat-bloodhound-executor \
  --supervise \
  --supervisor-proxy openrouter-openai \
  --inline-plan \
  --strategy ai-curated
```

The command accepts the transfer flags and creates a same-directory native fork anyway. In the motivating run this was
effectively silent: no transfer context was generated, no AI curation ran, and the child resumed the full parent Claude
transcript. Even where the current code emits a non-fatal tip for ignored transfer flags, that is too weak for flags
whose names imply a different context boundary.

This matters because the two modes optimize for different things:

- **Native same-directory fork**: maximum Claude continuity and no curation cost, but opaque context, no curated plan
  boundary, and potentially huge history carried into supervisor calls.
- **Transfer fork**: inspectable/editable context, inline approved plans, and portability, but no native reasoning
  state, possible curation cost, and today a coupling to worktree/`--into`.

The command surface should make that tradeoff explicit.

## Proposal

Decouple **transfer mode** from **worktree isolation**.

Same-directory forks should support an explicit fresh-transfer launch path:

```bash
forge session fork parent \
  --name child \
  --resume-mode transfer \
  --strategy ai-curated \
  --inline-plan
```

or, if the existing `--resume-mode` vocabulary is too overloaded:

```bash
forge session fork parent \
  --name child \
  --fresh-transfer \
  --strategy ai-curated \
  --inline-plan
```

In that mode Forge would:

1. Generate the parent transfer context in the current checkout.
2. Pre-seed a new child Claude session id.
3. Launch Claude without `--resume <parent> --fork-session`.
4. Pass the transfer document via the existing prompt/system-prompt-file path.
5. Persist derivation as transfer-based rather than native.

Worktree forks would keep their current default: transfer unless `--resume-mode native-relocate` is requested.
Same-directory forks would keep their current default: native resume unless transfer is requested explicitly.

> **Resolved (2026-06-15, see [checklist.md](checklist.md)):** the opt-in token is the existing `--resume-mode transfer`
> — the `--fresh-transfer` alternative above was **not** adopted. Additionally, explicit `--strategy`/`--inline-plan` on
> a same-dir fork **auto-switch** to transfer with a non-silent info line (no extra flag required).

## Design sketch

### 1. Make ignored flags a hard error or an explicit mode switch

Plain same-directory native forks must not silently ignore transfer-only flags. The current behavior should become one
of:

- hard error: `--strategy/--inline-plan require --worktree, --into, or --resume-mode transfer`
- auto-switch with a clear prompt-free message: explicit transfer flags imply same-directory transfer mode

Hard error is safer because it preserves native same-directory semantics and turns accidental flag dropping into a clear
preflight failure. Auto-switch is friendlier but changes behavior for users who expected native resume and did not
understand that `--strategy` requested a transfer.

> **Resolved (2026-06-15, see [checklist.md](checklist.md) Phase 1):** **auto-switch** was chosen, not hard error. It is
> encoded by resolving `resume_mode = "transfer"` early (only when `resume_mode is None`, so explicit
> `--resume-mode native-relocate` never auto-switches), after which every downstream branch keys uniformly on
> `resume_mode == "transfer"`.

### 2. Add same-directory transfer launch

Reuse the existing worktree transfer machinery:

- `_generate_parent_transfer_context(...)`
- `_combine_prompt_files(...)`
- `_persist_fork_transfer_derivation(...)`
- child UUID pre-seeding
- launch with `session_id=<child_uuid>` and `system_prompt_file=<transfer_context>`

The main difference is `worktree_path == Path.cwd()` and no git worktree creation.

### 3. Preserve native same-directory as default

Native same-directory forks are still valuable. They should remain the no-flag default:

```bash
forge session fork parent --name child
```

This avoids surprising users who expect exact Claude continuity and no curation bill.

### 4. Record derivation clearly

The child manifest should make the distinction obvious:

```json
{
  "confirmed": {
    "derivation": {
      "resume_mode": "transfer",
      "strategy": "ai-curated",
      "context_file": ".forge/artifacts/.../transfer.md"
    }
  }
}
```

Native same-directory forks should keep `resume_mode: "native"` and `strategy: null`.

### 5. Documentation and command help

Update:

- `forge session fork --help`
- `docs/end-user/transfer.md`

Docs should say plainly: `ai-curated` is a transfer strategy, not a native-resume strategy.

## Open questions

**All resolved 2026-06-15 — see [checklist.md](checklist.md). Kept here as the framing that produced the decisions; do
not re-open without revising the checklist.**

- Should explicit `--strategy` on same-directory fork imply transfer mode, or should the user also pass
  `--resume-mode transfer` / `--fresh-transfer`? **→ Resolved: explicit `--strategy`/`--inline-plan` AUTO-SWITCH to
  transfer (with an info line); the opt-in token is the existing `--resume-mode transfer`; no `--fresh-transfer` flag.**
- Should `--inline-plan` alone imply transfer mode? It only has meaning in a generated context document. **→ Resolved:
  yes — `--inline-plan` is a transfer flag and auto-switches a same-dir fork, same as `--strategy`.**
- Should same-directory transfer use `system_prompt_file`, an initial message, or the same composition path as worktree
  forks? **→ Resolved: the same composition path — `system_prompt_file` via `--append-system-prompt-file` (OQ3).**
- Should `--resume-mode transfer` be accepted for all forks, while `native-relocate` remains worktree-only? **→
  Resolved: yes — `transfer` is same-dir-legal; `native-relocate` stays worktree/`--into`-only.**
- How should this interact with sidecar launches, where the current sidecar branch passes `system_prompt_file` only for
  worktree forks? **→ Resolved: a `uses_fresh_transfer` predicate replaces the `is_worktree_fork` sidecar gate;
  `container.py` is unchanged (OQ5, Phase 2).**

## Risks

- Same-directory transfer creates a fresh child without native reasoning continuity. If the UX is vague, users may
  assume it is a native fork plus curation, which is impossible.
- Auto-switching on `--strategy` could silently change existing workflows from native resume to fresh transfer.
- Sidecar and host launch paths may diverge if the prompt-file plumbing remains gated on `is_worktree_fork`.
- Transfer generation can bill a model call for `ai-curated`; the CLI must make that visible before launch where
  practical.

## Acceptance sketch

- **Same-dir transfer requested**: `fork` without `--worktree`, with `--resume-mode transfer` and
  `--strategy ai-curated`, generates transfer context and launches a fresh child without parent
  `--resume --fork-session`.
- **Same-dir native default preserved**: a fork without transfer flags uses parent `resume_id` and `fork_session=True`,
  with no generated transfer context.
- **Ignored flags eliminated**: same-dir fork with `--strategy ai-curated` but no transfer mode either errors before
  creating a child or clearly switches to transfer per the chosen policy.
- **Inline plan works same-dir**: same-dir transfer with `--inline-plan` embeds approved plan text in the generated
  transfer, not only a parent plan-path reference.
- **Manifest records derivation**: a same-dir transfer child records `resume_mode == "transfer"` and
  `strategy == "ai-curated"` in confirmed derivation.
- **Sidecar parity**: sidecar same-dir transfer receives the composed transfer prompt just like host mode.
