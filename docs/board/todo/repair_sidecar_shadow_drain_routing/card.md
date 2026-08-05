# Repair sidecar shadow-drain routing

**Epic**: [`epic_stop_artifact_correctness`](../epic_stop_artifact_correctness/card.md).

**Finding**: D039 (MEDIUM) in [`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Lane**: `todo/` -- accepted Wave 2 implementation work, parked.

## Goal

Let a sidecar Stop hook detect pending supervisor-shadow candidates through the mounted project root while continuing to
enqueue a marker whose paths the later host drain can resolve.

## Design Authority

- [`docs/design.md` §7](../../../design.md#7-isolation-and-proxy-modes): the sidecar sees project `.forge/` through its
  `/workspace` mount while pending-work markers retain host checkout and Forge-root paths.
- [`docs/design.md` §3.10](../../../design.md#310-hook-handlers) and
  [`docs/design_workflows.md` §1.2](../../../design_workflows.md#12-semantic-policy-the-supervisor): Stop enqueues a
  shadow marker when a pending candidate exists; a later host CLI drains it.

## Evidence

Rechecked on merged `main` at `86fa53da`:

- `src/forge/cli/hooks/commands.py:113-121` deliberately translates deferred marker paths to host paths in sidecar mode,
  but `:640` reuses that host-only Forge root for the in-container `has_pending_candidates` filesystem probe.
- `src/forge/policy/semantic/shadow.py:157-169` checks `<forge_root>/.forge/artifacts/<session>/shadow/*.json` directly;
  the host checkout path is not mounted at that location in the container.
- An executable characterization created a candidate under the container-visible project root and supplied distinct
  sidecar host-path environment values. The current effective-root probe returned false; probing the mounted project
  root returned true.

## Expected Behavior

- Candidate discovery uses the container-visible manifest/project root that owns `.forge/artifacts`.
- A resulting shadow marker retains the host worktree and Forge-root paths required by the host queue drain.
- Host-mode behavior is unchanged, rate-zero/no-candidate sessions enqueue nothing, and probe/enqueue failures remain
  best-effort and visible only through existing diagnostics.

## Scope

- Separate the filesystem probe root from the deferred marker payload roots at the Stop shadow-enqueue seam.
- Cover both distinct-root sidecar mode and ordinary host mode without changing shadow candidate or marker schemas.
- Keep `docs/design.md` §7 and `docs/design_workflows.md` §1.2 synchronized if implementation clarifies the path split.

## Acceptance Criteria

- `tests/regression/test_bug_d039_sidecar_shadow_drain_routing.py` reproduces distinct container/host paths and asserts
  exactly one host-resolvable shadow marker when a mounted candidate exists.
- The regression module has `pytestmark = pytest.mark.regression` and a module docstring naming D039 and its root cause,
  per the Regression Test Mandate.
- Focused unit coverage asserts no marker for no candidate and unchanged host-mode path behavior.
- Targeted Docker integration in `tests/integration/sidecar/test_sidecar_hook_inject.py` exercises the sidecar Stop hook
  and host-side drain visibility through `./scripts/test-integration.sh`.
- The focused hook/shadow tests, required integration runner, `make test-regression`, and `make pre-commit` pass.

## Compatibility and Exclusions

- Preserve the existing pending-work marker schema, atomic claim/drain lifecycle, at-most-once frontier billing, and
  `queued_shadow` JSON field.
- Do not change sampling, candidate caps, replay reconstruction, D025 atomic candidate writes, or D026 effort fidelity.
