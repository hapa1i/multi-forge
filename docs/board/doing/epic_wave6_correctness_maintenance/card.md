# Epic: Wave 6 correctness maintenance

**Parent epic**: [`epic_repo_maintenance_round`](../epic_repo_maintenance_round/card.md).

**Lane**: `doing/` -- 29 of 36 findings across 11 of 13 members shipped in PRs #164--#175. O011/O017/O021/O023/O029/O030
are implementation-complete and pending independent review on `agent/preserve-session-launch-preconditions`; O036
remains parked in `todo/`. PR #169 (`ece999d4`) hardened O012 escalation and retention-status error sanitization without
adding a finding to this admission set.

## Goal

Carry the still-live MEDIUM CLI, proxy, and runtime correctness findings beyond the closed Wave 5 admission cutoff as
bounded Wave 6 implementation work, without mixing independent behavior changes or reopening Wave 5.

## Admission Record

The 36 rows that could superficially be read as additional Wave 5 CLI/proxy/runtime work were rechecked on `main` at
`246aaff1`. Current code still contains the cited behavior for 34 rows. Two claims are rejected:

- D033: `%cancel-verification` already catches malformed effective intent and falls back to raw verification intent.
- O020: the downstream pane begins with all event-backed command rows and adds downstream-only rows, so it does not
  discard non-proxy spend.

The rejections are pinned by `tests/regression/test_bug_d033_cancel_verification_escape_hatch.py` and
`tests/regression/test_bug_o020_model_pane_cost_union.py`. The 34 live rows belong here because the canonical wave table
assigns unadmitted verified MED/LOW bugs to Wave 6. Acceptance into this epic does not waive the parent admission
contract: every member must retain a failing regression or equivalent executable characterization on its execution base
before production code changes.

After PR #170 merged, follow-up verification on `22071fcd` admitted D054/D055. D054 extends the directly transported
proxy-field boundary completed in PR #168; D055 completes failed-start resource/error ownership adjacent to PR #167.
Both are independently reproduced and share one proxy load/start failure boundary.

## Members and Sequence

| Order | Findings                         | Member                                                                                                      | Review boundary                               |
| ----- | -------------------------------- | ----------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| 1     | D020                             | [`strip_direct_child_forge_headers`](../../done/strip_direct_child_forge_headers/card.md)                   | outbound correlation-header trust             |
| 2     | D023, D028, O022                 | [`align_transfer_preflight_and_cli_contract`](../../done/align_transfer_preflight_and_cli_contract/card.md) | transfer source/depth/reattach semantics      |
| 3     | D027, O012                       | [`harden_detached_process_teardown`](../../done/harden_detached_process_teardown/card.md)                   | detached process-group ownership              |
| 4     | O014, O026                       | [`close_proxy_failure_lifecycles`](../../done/close_proxy_failure_lifecycles/card.md)                       | proxy registry and stream cleanup             |
| 5     | D029, O025                       | [`complete_proxy_instance_config_wiring`](../../done/complete_proxy_instance_config_wiring/card.md)         | template-to-instance field preservation       |
| 6     | D030, O008, O015, O035           | [`restore_proxy_request_semantics`](../../done/restore_proxy_request_semantics/card.md)                     | tier authority and translated request shape   |
| 7     | D054, D055                       | [`harden_proxy_boundary_failures`](../../done/harden_proxy_boundary_failures/card.md)                       | proxy config and process-start boundaries     |
| 8     | O013, O034                       | [`align_policy_routing_context`](../../done/align_policy_routing_context/card.md)                           | policy routing/session selector consistency   |
| 9     | D031                             | [`exclude_interactive_usage_cost`](../../done/exclude_interactive_usage_cost/card.md)                       | two-plane interactive exclusion               |
| 10    | D032, D041, O005, O031--O033     | [`align_cli_failure_surfaces`](../../done/align_cli_failure_surfaces/card.md)                               | CLI exit, stream, editor, and status behavior |
| 11    | D034, D037, D038, O027           | [`harden_command_state_boundaries`](../../done/harden_command_state_boundaries/card.md)                     | hook silence and strict durable-state reads   |
| 12    | O011, O017, O021, O023, O029--30 | [`preserve_session_launch_preconditions`](../preserve_session_launch_preconditions/card.md)                 | launch preflight, rollback, and fail-open     |
| 13    | O036                             | [`harden_walkthrough_sandbox_provenance`](../../todo/harden_walkthrough_sandbox_provenance/card.md)         | sandbox provenance before code execution      |

The sequence starts with isolated trust and transfer contracts, then process/proxy lifecycle, proxy request semantics,
operator read paths, and session launch safety. O036 remains independent because it changes a bundled shell safety
boundary and requires clean-package verification.

## Shared Constraints

- Preserve the row-first session transaction, index-to-manifest lock order, and missing-worktree authority model.
- Preserve proxy/session ownership: templates and proxy instances own model routing; sessions own workflow intent.
- Keep JSON read-command results on stdout and every diagnostic, recovery hint, and failure payload on stderr.
- External and post-launch best-effort boundaries must not break an otherwise completed launch.
- Do not absorb policy-internal, performance, documentation, duplication, dead-code, or unverified findings from later
  Wave 6/7 sets.
- Run the integration tier required by the affected subsystem before a member can close.

## Closeout

This epic closes only after every live member ships independently, the review ledger points to each terminal outcome,
and relevant design/end-user documentation is synchronized. It does not affect Wave 5's closed 13-finding count.
