# Derived-session override inheritance decision

**Status:** Selected by the maintainer on 2026-10-27 and shipped with the reviewed corrections in
[PR #284](https://github.com/hapa1i/multi-forge/pull/284) on 2026-10-28. Keep the fork/fresh versus relaunch
distinction; [evidence](evidence.md) separates initial characterization from the verified fixes. Uniform validation
remains unshipped work in [the implementation card](../../doing/validate_derived_session_overrides/card.md).

## Selected contract

Keep explicit derivation distinct from relaunch-as-child. Fork and fresh resume establish a new baseline using the
existing field-specific inheritance rules. Relaunch preserves the parent's valid live toggles as a separate override
layer, so restarting work does not unexpectedly reactivate disabled policy. Reset remains subject to supervisor identity
protections.

| Operation         | Baseline                 | Generic overrides    | Memory                                   |
| ----------------- | ------------------------ | -------------------- | ---------------------------------------- |
| Fork              | Selected baseline fields | Empty                | Effective `auto_update` becomes baseline |
| Fresh resume      | Selected baseline fields | Empty                | Effective `auto_update` becomes baseline |
| Relaunch as child | Selected baseline fields | Copy valid overrides | Preserve baseline and override layers    |
| Ordinary reattach | Same session             | Retain in place      | Retain in place                          |

The distinction follows the Forge operation, not the transcript transport. A same-directory native fork and a
`resume --fresh --resume-mode native` still use explicit-derivation rules. Relaunch is the internal child path reached
by `resume --force` against an active resumable Claude session; it is not a new CLI verb. Ordinary inactive resume
normally reattaches without deriving anything. A never-launched session launches in place. Codex reattach and
`start --runtime codex --resume-from` keep their existing separate contracts; this decision does not make them inherit
Claude policy.

## Field and reset rules

**Baseline selection.** Retain the existing allowlist for subprocess proxy, policy, system prompt, verification,
consumer lanes and launch preferences. Preserve the existing proxy/model-route selection and explicit child routing
rules. Do not replace this with a whole-manifest copy or `compute_effective_intent(parent)` assigned as child intent.
The historical `agent` field and runtime dispatch remain under their current owners. Fresh resume now inherits the proxy
template and URL together from intent; the earlier confirmed proxy remains derivation metadata. The existing
compatibility projection from `confirmed.is_sandboxed` to sidecar intent still applies when launch intent is absent.

**Policy and supervisor suspension.** A parent with baseline policy enabled and `%policy disable` produces
policy-enabled fork/fresh children and a policy-disabled relaunch child. The inverse follows the same layer rule: a live
enable does not change the baseline inherited by fork/fresh. Terminal `forge policy enable|disable` changes baseline.
Both `%policy supervisor off` and `forge policy supervisor off` also change baseline, removing any suspension override.
All three child paths inherit that suspension; generic reset cannot undo it. Use supervisor `on` to resume it.

**Verification.** Shipped setup uses `session set verification.*`, which writes overrides. Fork/fresh therefore drop the
entire verification configuration, including bypass; relaunch retains it. A manually authored baseline verification
section would inherit, but no shipped setup command creates one. Do not describe dropping verification as reactivation.

**Memory exception.** Fork/fresh materialize only the parent's effective `memory.auto_update` configuration, including
enabled, mode, proxy, direct, minimum turns and effort. Other memory fields take fresh defaults. An explicit
`--memory on` keeps the selected configuration and enables it; `--memory off` writes the existing explicit disabled
default configuration. A cleared effective memory section stays absent without an explicit flag. Relaunch copies the
original memory baseline and valid overrides, without materializing them.

**Reset.** A child's generic reset removes only its own override layer. For fork/fresh, inherited memory activation is
already baseline, so `reset --all` does not restore the parent's earlier memory setting. For relaunch, an admitted reset
restores the copied baseline. Reset refuses a change to native supervisor source identity or frozen supervisor identity
(model, effort or auth mode); use supervisor remove/reconfigure for those transitions. A malformed effective supervisor
can also prevent reset. Configuration edits in either session do not update the other. This independence does not cover
plans: a child without its own plan reads its immediate parent's draft/approved snapshots live.

**Consumer lanes.** Inherit `intent.consumer_lanes` for all four consumers, including absence after `lane clear`. Never
copy `confirmed.consumer_lanes` or degradation state. Each child commits its own lane at the existing consumer-specific
boundary. A cleared parent intent must not be resurrected from a still-frozen parent binding. Generic overrides cannot
select or clear lanes.

**Lifecycle-owned fields.** Runtime dispatch identity, resolved model routes, authority and native supervisor source
identity continue to use their typed owners. No generic override can redefine them through derivation. Advisory
authority and its tier inherit; producer authority drops; explicit child designation wins. Per-launch effort and native
argument tails remain transient and are not added to session inheritance.

**Supervisor admission.** Derivation checks Stop executor compatibility and validates native-source candidates against
the parent and child lanes. Only enabled, active native Codex sources receive readiness checks there. Sidecar admission
and Claude reviewer preflight remain at launch; do not move them into derivation or make `fork --no-launch` require a
ready Claude reviewer. A disabled relaunch must not require a live reviewer. Do not copy frozen review ownership or
spent turn allowances.

## Invalid legacy overrides

The follow-up must validate before any derivation side effects. Relaunch currently can publish invalid scalar values or
obsolete runtime overrides. Fork/fresh reject some bad values indirectly during memory inheritance, too late to protect
earlier work: fresh transfer can write context files and pay for ai-curated inference, and `fork --worktree --force` can
delete the previous fork before refusing the parent. CLI routing can also start proxy or supervisor processes before
reaching the manager. Run the pure guard in fork planning and resume preflight before routing realization, as well as in
the manager paths before transfer, replacement deletion, worktree creation or child publication.

- Unknown keys, malformed containers and unsupported manifest versions retain strict read refusal and no-write behavior.
  Keep existing explicit compatibility migrations; add no broad cleanup migration.
- Known-key values must form a valid effective configuration. Reject a malformed parent rather than dropping values
  implicitly because the selected child path would otherwise omit generic overrides.
- Reject stored overrides targeting lifecycle-owned fields, including `launch.runtime`, `launch.model_route`,
  `authority`, `consumer_lanes` and native supervisor source identity. Validate paths and nested object contents; do not
  treat a permitted nullable parent such as `launch: null` as if it explicitly supplied an immutable descendant.
- Report the offending path and leave parent bytes and owned artifacts intact. Offer keyed reset or `reset --all` only
  where supervisor transition validation permits it. Malformed configured supervisors and native/frozen identity changes
  require `forge policy supervisor remove --session <name>` followed by reconfiguration. If no baseline supervisor
  exists, or strict decoding refuses the manifest, require explicit repair/restoration instead of an inapplicable reset.

Validation is structural and respects existing typed admission; it must not launch a reviewer, resolve a live catalog or
obtain credentials merely to check an unrelated override. Preserve each lifecycle's current locks and rollback
boundaries. This decision does not promise an atomic snapshot across concurrent parent mutations.

## Alternatives

- **Discard generic overrides for every child:** simpler operation matrix, but relaunch would reactivate temporarily
  disabled policy and lose override-configured verification. It would break existing regression expectations and need a
  compatibility change and revised recovery behavior.
- **Copy generic overrides for every child:** retains reset provenance, but propagates temporary policy toggles and
  bypass into explicit forks and fresh sessions. Memory's existing materialization would need separate reconciliation.
- **Materialize all effective values:** erases the distinction between baseline and temporary changes. Reset can no
  longer undo inherited toggles, and effective values can conflict with immutable runtime and lane ownership.

## Implementation handoff

The [validation follow-up](../../doing/validate_derived_session_overrides/card.md) owns pre-derivation admission and the
fixture-grounded regression matrix. Current inheritance and reset behavior is documented in the session design and user
guides with this decision. The follow-up must update their validation limitation when its code ships. It preserves
memory, lane and supervisor ownership and requires targeted Docker lifecycle checks. This PR also fixes the exposed
proxy-pair inheritance, wildcard lane authoring and reset-diagnostic bugs and removes the unreachable relaunch fallback;
those corrections do not implement the full guard.
