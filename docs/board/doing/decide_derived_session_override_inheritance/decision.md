# Derived-session override inheritance decision

**Status:** Selected by the maintainer on 2026-10-27: keep the fork/fresh versus relaunch distinction. Current behavior
was checked on `32df0219`; see [evidence](evidence.md). The layer contract already exists; uniform validation is
unshipped work in [the implementation card](../../proposed/validate_derived_session_overrides/card.md).

## Selected contract

Keep explicit derivation distinct from relaunch-as-child. Fork and fresh resume establish a new baseline using the
existing field-specific inheritance rules. Relaunch preserves the parent's valid live toggles as a separate override
layer, so restarting work does not unexpectedly reactivate disabled policy and the child can still reset those toggles.

| Operation         | Baseline            | Generic overrides    | Memory                                   |
| ----------------- | ------------------- | -------------------- | ---------------------------------------- |
| Fork              | Selected raw intent | Empty                | Effective `auto_update` becomes baseline |
| Fresh resume      | Selected raw intent | Empty                | Effective `auto_update` becomes baseline |
| Relaunch as child | Selected raw intent | Copy valid overrides | Preserve baseline and override layers    |
| Ordinary reattach | Same session        | Retain in place      | Retain in place                          |

The distinction follows the Forge operation, not the transcript transport. A same-directory native fork and a
`resume --fresh --resume-mode native` still use explicit-derivation rules. Relaunch is the internal child path reached
by `resume --force` against an active resumable Claude session and the existing non-resumable fallback; it is not a new
CLI verb. Ordinary inactive resume normally reattaches without deriving anything. Codex reattach and
`start --runtime codex --resume-from` keep their existing separate contracts; this decision does not make them inherit
Claude policy.

## Field and reset rules

**Baseline selection.** Retain the existing allowlist for subprocess proxy, policy, system prompt, verification,
consumer lanes and launch preferences. Preserve the existing proxy/model-route selection and explicit child routing
rules. Do not replace this with a whole-manifest copy or `compute_effective_intent(parent)` assigned as child intent.
The historical `agent` field and runtime dispatch remain under their current owners.

**Temporary policy and verification changes.** A parent with baseline policy enabled and `%policy disable` produces
policy-enabled fork/fresh children and a policy-disabled relaunch child. The inverse follows the same layer rule: a live
enable does not change the baseline inherited by fork/fresh. Supervisor suspension and verification bypass follow that
rule too. A terminal policy command that changes baseline intent propagates as baseline. Explain this difference in the
session and policy guides.

**Memory exception.** Fork/fresh materialize only the parent's effective `memory.auto_update` configuration, including
enabled, mode, proxy, direct, minimum turns and effort. Other memory fields take fresh defaults. An explicit
`--memory on` keeps the selected configuration and enables it; `--memory off` writes the existing explicit disabled
default configuration. A cleared effective memory section stays absent without an explicit flag. Relaunch copies the
original memory baseline and valid overrides, without materializing them.

**Reset.** A child's generic reset removes only its own override layer. For fork/fresh, inherited memory activation is
already baseline, so `reset --all` does not restore the parent's earlier memory setting. For relaunch, reset restores
the copied parent baseline, including memory and policy. Later parent set/reset operations never update an existing
child. Explicit child baseline choices remain baseline after reset.

**Consumer lanes.** Inherit `intent.consumer_lanes` for all four consumers, including absence after `lane clear`. Never
copy `confirmed.consumer_lanes`, degradation state or the parent's other execution facts as configuration. Each child
commits its own lane at the existing consumer-specific boundary. A cleared parent intent must not be resurrected from a
still-frozen parent binding. Generic overrides cannot select or clear lanes.

**Lifecycle-owned fields.** Runtime dispatch identity, resolved model routes, authority and native supervisor source
identity continue to use their typed owners. No generic override can redefine them through derivation. Advisory
authority and its tier inherit; producer authority drops; explicit child designation wins. Per-launch effort and native
argument tails remain transient and are not added to session inheritance.

**Supervisor admission.** Retain the existing checks of both the parent's effective supervisor and the actual child
configuration/lane, including Stop/sidecar restrictions. Readiness applies to each enabled, active candidate. A relaunch
that remains disabled must not require a live reviewer, while a fork/fresh child that restores enabled baseline policy
must satisfy the existing admission checks. Do not copy frozen review ownership or spent turn allowances.

## Invalid legacy overrides

Validate before child publication, new worktree creation or transfer inference. This is a change from the current
relaunch path, which can publish a child with invalid scalar types or obsolete runtime overrides.

- Unknown keys, malformed containers and unsupported manifest versions retain strict read refusal and no-write behavior.
  Keep existing explicit compatibility migrations; add no broad cleanup migration.
- Known-key values must form a valid effective configuration. Reject a malformed parent rather than dropping values
  implicitly because the selected child path would otherwise omit generic overrides.
- Reject stored overrides targeting lifecycle-owned fields, including `launch.runtime`, `launch.model_route`,
  `authority`, `consumer_lanes` and native supervisor source identity. Validate paths and nested object contents; do not
  treat a permitted nullable parent such as `launch: null` as if it explicitly supplied an immutable descendant.
- Report the offending path and leave parent bytes and owned artifacts intact. For a readable manifest, use the existing
  keyed reset where supported or `session reset --all`. If strict decoding already refuses the manifest, explain that
  generic reset cannot read it and require explicit repair or restoration of that manifest.

Validation is structural and respects existing typed admission; it must not launch a reviewer, resolve a live catalog or
obtain credentials merely to check an unrelated override. Preserve each lifecycle's current locks and rollback
boundaries. This decision does not promise an atomic snapshot across concurrent parent mutations.

## Alternatives

- **Discard generic overrides for every child:** simpler operation matrix, but relaunch would reactivate suspended
  policy/verification and break explicit existing regression expectations. It would need a deliberate compatibility
  change and revised recovery behavior.
- **Copy generic overrides for every child:** retains reset provenance, but propagates temporary suspension and bypass
  into explicit forks and fresh sessions. Memory's existing materialization would need separate reconciliation.
- **Materialize all effective values:** erases the distinction between baseline and temporary changes. Reset can no
  longer undo inherited suspension, and effective values can conflict with immutable runtime and lane ownership.

## Implementation handoff

The [validation follow-up](../../proposed/validate_derived_session_overrides/card.md) owns pre-derivation admission and
the fixture-grounded regression matrix. Current inheritance and reset behavior is documented in the session design and
user guides with this decision. The follow-up must update their validation limitation when its code ships. It preserves
memory, lane and supervisor ownership and requires targeted Docker lifecycle checks; this decision-only investigation
does not establish new native-runtime behavior.
