# Project compatibility mutator sweep

**Origin**: standalone follow-up split from the T7 [`forge_project_compat`](../../done/forge_project_compat/card.md)
closeout. **Reclassified 2026-07-11: not a member of
[`epic_global_forge_runtime`](../../doing/epic_global_forge_runtime/card.md)** and does not hold the epic open -- the
sweep touches none of the epic's five seams and has no sequencing dependence on its members (precedent: the
consumer_lanes epic re-filed its team-supervisor follow-on as a standalone card).

**Lane**: `todo/` -- accepted, parked. No execution branch yet.

## Goal

Finish the `.forge/project.toml` enforcement coverage that T7 deliberately left visible: every remaining project-state
mutator either observes the compatibility guardrail or records a narrow exemption with rationale.

## Background

T7 `forge_project_compat` shipped the file reader, fail-open hook helper, extension lifecycle guards, shared session
repo-root guards, and doctor surfacing. Its first slice did **not** cover the full mutator family named in the card:

- hook confirmed-state writes
- memory-writer doc writes
- proxy/backend registry mutations

The helper `check_project_compatibility_for_hook()` is contract-first until this sweep wires its first production hook
caller. If this follow-up does not wire a hook caller before release, move that helper with its first caller rather than
letting unused contract code linger across releases.

## Design Rules

- Reuse `src/forge/install/project_compat.py`; do not reparse `.forge/project.toml` at call sites.
- Preserve T7's three-state posture: missing file is compatible/unconstrained; malformed or unsupported state fails
  clear on command/operator mutation paths; session/context hook paths fail open with a degraded diagnostic.
- Prefer small named guard points over sprinkling checks across leaf mutators. If a family is not actually project-local
  state, document the exemption in the checklist and design docs if user-facing behavior depends on it.
- Do not add `.forge/project.toml` authoring. v1 remains hand-edit only.
- `forge_dev_runtime_override` bypass decision -- **resolved by T8 (2026-07-11): T8 adds no special bypass.** A
  `FORGE_DEV`-resolved forge keeps the existing compatibility posture unchanged, and hook-path pin enforcement remains
  this sweep's scope (`check_project_compatibility_for_hook` currently has no production caller; strict enforcement is
  `cli/guards.py` plus direct `cli/extensions.py` command paths).

## Acceptance Tests

| Test                       | Fixture                                             | Assertion                                                                 | Test File |
| -------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------- | --------- |
| Confirmed-state guard      | incompatible `.forge/project.toml`, hook write path | session/context hook path degrades per T7 matrix without bricking session | TBD       |
| Memory-writer posture      | incompatible pin during doc write                   | command/background behavior matches the chosen guard posture              | TBD       |
| Proxy/backend posture      | incompatible pin near registry mutation             | project-local mutations block or exemption is documented                  | TBD       |
| Helper has caller or moves | production tree after sweep                         | no unused lenient helper ships without its first caller                   | TBD       |
