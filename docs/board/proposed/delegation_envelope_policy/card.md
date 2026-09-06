# delegation_envelope_policy -- enforce supported delegation choices at native call boundaries

**Epic**: [epic_native_multiagent](../epic_native_multiagent/card.md) (M7 -- the envelope, not counters).

**Lane**: `proposed/`. Depends on M1's Claude identity rules. Worker restrictions ship independently in
[M0](../worker_native_controls/card.md); this card owns the managed-session envelope. Codex pre-tool origin/capability
verification belongs here and does not require Codex transcript capture or transfer support.
[epic_budgeted_review_guards](../epic_budgeted_review_guards/card.md), Seam 5, owns counters and spend caps.

## Problem (verified 2026-09-06)

- `src/forge/session/authority.py` denies Agent wholesale for the advisory `shell_closed` tier. Ordinary managed
  sessions lack a delegation envelope.
- `src/forge/install/preset.py` installs the Claude policy matcher for Write/Edit, and `src/forge/cli/hooks/commands.py`
  filters other tools out. Evaluator changes alone would never see Agent calls.
- `src/forge/install/codex_hooks.py` registers PreToolUse without a matcher. Filtering belongs in the Codex policy
  handler; there is no apply_patch/Bash registration matcher to extend. Native trust enrollment also controls delivery.
- `forge policy enable` requires `--bundle` (`src/forge/cli/policy.py`). The direct-command disable handler in
  `src/forge/cli/hooks/direct_commands.py` ignores trailing arguments and disables all policy; advertising
  `%policy disable delegation` would silently disable unrelated checks.

[Claude's subagent controls](https://code.claude.com/docs/en/sub-agents#turn-fork-mode-on-or-off) distinguish ordinary
subagents from fork mode. [Workflow controls](https://code.claude.com/docs/en/workflows#turn-workflows-off) also apply
to headless runs. Codex's [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference) defines
the native multi-agent switch. Pin actual tool names and observed delivery in the acceptance probe.

## Bundle and command contract

Add session-owned `policy.bundle_config.delegation` with these defaults when enabled:

| Field      | Values                            | Default and meaning                                                |
| ---------- | --------------------------------- | ------------------------------------------------------------------ |
| teammates  | deny / allow                      | deny; Claude team creation only, not ordinary first-level children |
| nested     | deny / allow                      | deny; child-origin delegation, not every root spawn                |
| types      | null or list of native type names | null is unrestricted; empty list permits no type                   |
| isolation  | require-worktree / any            | any; validate actual supported isolation, not an agent's name      |
| background | deny / allow                      | allow; explicit policy over effective execution mode               |

Enable with `forge policy enable --bundle delegation`. Add typed `--teammates`, `--nested`, repeatable `--type`,
`--isolation` and `--background` options, valid only when delegation is selected; mirror them in
`%policy enable --bundle delegation ...`. Omitted types mean unrestricted; the persisted schema also validates an empty
list. Enable retains the existing complete-bundle-selection semantics: include existing bundles when keeping them.
Terminal activation writes intent; direct commands retain their documented override ownership.

Add `forge policy disable --bundle delegation` and `%policy disable --bundle delegation` as scoped operations. They
remove only the selected bundle from effective activation, reconcile conflicting activation overrides, and preserve
other bundles, their options, supervisor state and fail mode. Bare disable keeps its existing whole-policy meaning.
Reject positional/unknown trailing tokens before mutation. Denial recovery names the implemented scoped command.
Validate the bundle atomically through the shared policy activation/engine path.

## Per-call enforcement and delivery

- **Claude:** extend installed matcher coverage and handler filtering to native delegation/resume admission calls,
  initially Agent and SendMessage. Resolve effective kind/type/isolation/background from the tool input, native
  definition/settings and verified origin. A `name` or `agent_id` alone is not a universal classifier.
- **Background:** account for fork mode, definition frontmatter, absent parameters and native defaults. SendMessage can
  resume a stopped/completed child in the background; treat that as admission of new work, not merely messaging. Test it
  alongside direct spawns. A running-child message that admits no new work is distinct. A native foreground override may
  satisfy the restriction only if the probe verifies it for that path.
- **Codex:** verify native tool names and payloads for spawn, resume/follow-up, and messaging in the installed version;
  do not assume Forge's own collaboration API names match the runtime. Root first-level spawn remains allowed under
  `nested: deny`; evidenced child-origin spawn is denied. Claude teammate policy is not a Codex deny-all alias. Show
  fields without a runtime equivalent as not applicable; reject a requested restriction that cannot be enforced.
- **Unsupported/unknown modes:** an unknown effective mode cannot satisfy a restrictive predicate. Disable native
  workflows while the envelope is enabled until their admission controls are verified. If worktree isolation cannot
  apply to a native team, a require-worktree envelope denies that team even when teammates are allowed. Type allowlists
  constrain names; they do not prove read-only behavior.
- **Installation:** update Claude preset/registry, wheel assets, sync/disable and status. Preserve matcher-free Codex
  registration and use internal filtering. Verification includes a real denied native action through enrolled hooks.
  Handler unit tests and registration presence alone cannot establish delivery.
- **Readiness:** `forge policy status --json` separates requested envelope, supported fields, configured native controls
  and hook delivery (verified/unavailable/unknown), with runtime version and configuration/registration identity.
  Invalidate verification when those facts change. A managed launch requiring unavailable enforcement refuses with
  applicable installation/enrollment recovery; native disabling can satisfy a restriction without a hook only when
  verified. Live activation cannot report enforced until applicable delivery is established. Preserve the policy
  engine's configured error fail mode; distinguish evaluation errors from unavailable delivery.

## Independent worker and source work

M0 owns worker-native delegation/memory restrictions and their capability probe. This card must compose with that worker
profile, without applying it to ordinary managed roots.

Evaluate root/child origin from verified pre-tool/runtime evidence. If a required origin fact is unavailable, report
that restriction as unsupported or deny the unresolved admission according to the contract above. Transcript snapshots
are not an enforcement prerequisite. Coordinate overlapping Codex hook registration edits with M3b through one owner;
that is a write boundary, not a dependency on Codex-as-source launch.

## Non-goals

No worker launch profile, counters, spend caps, scheduler, teammate termination, per-role bundles, or expansion of
authority tiers. No claim of independent native reviewers based on type names or a missing child receipt.

## Acceptance

| Test                                 | Fixture and assertion                                                                                                      | Test file                                                                                                    |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Typed activation/scoped disable      | CLI and direct forms preserve unrelated effective bundles/overrides; invalid trailing tokens mutate nothing                | `tests/src/cli/test_policy_enable.py`, `tests/src/core/ops/test_policy_ops.py`                               |
| Teammate/nested/type/isolation gates | Probe-derived effective context; root child allowed under nested deny, child-origin spawn denied                           | `tests/src/cli/hooks/test_policy.py`, `tests/src/cli/hooks/test_codex_policy_check.py`                       |
| Background and resume                | Missing flag, fork mode, definition background and SendMessage resume; unknown mode cannot pass a deny predicate           | `tests/src/cli/hooks/test_policy.py`                                                                         |
| Delivery and unsupported fields      | Claude matcher includes admission tools; Codex remains matcher-free; untrusted/stale verification cannot claim enforcement | `tests/src/install/test_codex_hooks.py`, `tests/src/core/ops/test_codex_enrollment.py`                       |
| Installed-wheel enforcement          | Actual native spawn/resume is denied after hook sync/enrollment; disable/re-enable updates readiness correctly             | Extend `tests/integration/docker/test_policy_hooks.py`, `tests/integration/core/test_codex_session_start.py` |
| Scoped-disable regression            | Disabling delegation cannot turn off TDD or coding standards                                                               | New `tests/regression/test_bug_delegation_disable_other_bundles.py`                                          |

## Design-doc sync

`docs/design_workflows.md` (bundle, activation and verified policy readiness); `docs/design_sessions.md` (launch
restrictions and status facts); `docs/design_installation.md` (matcher, sync and trust ownership);
`docs/end-user/policy.md`, `docs/end-user/workflow.md`, `docs/end-user/hook.md` and `docs/cli_reference.md`.
