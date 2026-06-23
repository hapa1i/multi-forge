# Checklist: Forge CLI Cleanup And Taxonomy

**Card**: [card.md](card.md) - **Branch**: `forge_cli_cleanup` - **Lane**: doing

Accepted 2026-06-23 at user request and moved `proposed/ -> doing/` directly. This first branch commit only starts the
execution lane; no command surface changes yet.

## Current focus

Start with a taxonomy decision slice before touching live commands. The card proposes a large clean break across
top-level command groups, so the first implementation work should reduce ambiguity rather than rename surfaces
piecemeal.

## Phase 0 - Board start

- [x] Create execution branch `forge_cli_cleanup`.
- [x] Move card from `docs/board/proposed/forge_cli_cleanup/` to `docs/board/doing/forge_cli_cleanup/`.
- [x] Update card status and references for the accepted lane.
- [x] Add this initial checklist.
- [x] Commit initial board-start state on the branch.

## Phase 1 - Taxonomy decision slice

- [ ] Confirm final command tree for:
  - `forge telemetry activity|trace|costs`;
  - `forge model backend`;
  - `forge session transfer`;
  - top-level `memory`, `runtime`, `proxy`, and `codex` boundaries.
- [ ] Decide whether `forge proxy audit show|diff` stays under `proxy` or moves under `telemetry`.
- [ ] Decide whether session memory activation/reporting moves under `session memory`.
- [ ] Decide user-facing hook-management surface (`extension` vs visible `hook` vs docs removal).
- [ ] Decide alias policy, including `auth` versus `authentication`.
- [ ] Record resolved decisions in the checklist before implementation slices start.

## Phase 2 - Implementation slices

- [ ] Session-scope move: `forge session transfer ...` and any chosen session-memory surfaces.
- [ ] Telemetry move: activity, provider trace, and costs under the chosen telemetry namespace.
- [ ] Model/backend move under the chosen model namespace while preserving lifecycle/auth/reconcile behavior.
- [ ] Clean-break removals, including `forge session context`.
- [ ] Read-output consistency: missing `--json`, `as_json` destination normalization, stdout/stderr policy, and
  `forge search query` human default.
- [ ] Config-object parity across `config`, `proxy`, `claude preset`, `proxy template`, and backend config.
- [ ] Destructive cleanup semantics pass.
- [ ] Policy supervisor naming/action cleanup.
- [ ] Recovery-output helper cleanup.
- [ ] Non-leaf group normalization.
- [ ] Smaller surface cleanup pass.

## Docs and verification

- [ ] Update `docs/cli_reference.md`.
- [ ] Update relevant `docs/end-user/*` guides.
- [ ] Update `docs/developer/cli_style_guidelines.md` for new taxonomy/output/alias rules.
- [ ] Update `docs/design.md` if ownership boundaries change.
- [ ] Add migration notes/changelog naming moved live commands.
- [ ] Run targeted CLI tests for old/new paths, help, JSON, and stream behavior.
- [ ] Run `make pre-commit` before closeout.

## Open decisions carried from the card

- [ ] Scope flags for `telemetry activity|costs|trace`.
- [ ] Final placement of proxy audit.
- [ ] Final backend namespace and churn budget.
- [ ] Placement of memory report/enable/disable/status.
- [ ] Hook-management visibility.
- [ ] Whether workspace-level telemetry waits for `workspace_scope`.
- [ ] Whether any `--json` destinations intentionally remain `json_output`.
- [ ] Human read-output stdout/stderr rule and exceptions.
- [ ] Canonical `auth` vs `authentication`.
- [ ] Alias rule for new top-level groups.
