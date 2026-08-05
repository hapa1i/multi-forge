# Policy and supervision correctness checklist

Current focus: Wave 1 is closed; all three members shipped and the parent epic and review ledger point to their
outcomes.

- [x] Recheck D001–D005 and O028 against merged code and normative design.
- [x] Run isolated executable reproductions for every admitted finding.
- [x] Confirm the focused existing policy/supervision suite remains green.
- [x] Split state preservation, verdict hardening, and edit identity into independent members.
- [x] Exclude O044 from Wave 1 pending separate bounded-maintenance admission.
- [x] Move `preserve_policy_intent_on_enable` to `doing/` on its implementation branch.
- [x] Review and merge the D001 result before starting either HIGH-severity member.
- [x] Keep parent/member links and sequencing current as D001 moves to `done/`.
- [x] Move `harden_supervisor_verdict_boundary` to `doing/` on its implementation branch.
- [x] Complete D002–D004 and O028 with dedicated regressions and move the member to `done/`.
- [x] Review and merge the D002–D004 and O028 result before starting D005 (PR #126).
- [x] Move `preserve_supervisor_edit_identity` to `doing/` on its implementation branch.
- [x] Complete D005 with a marked regression and move the verified member to `done/`.
- [x] Review and merge the D005 result before closing this epic (PR #127).
- [x] Close only after every live member ships and the review ledger records the outcomes.

## Member Acceptance Map

| Member                               | Required fixture                                                  | Observable assertion                                                  | Planned test area                                                 |
| ------------------------------------ | ----------------------------------------------------------------- | --------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `preserve_policy_intent_on_enable`   | Disabled policy with both supervisor configs                      | Re-enable changes bundle fields without changing supervisor intent    | `tests/regression/test_bug_d001_policy_enable_supervisor_loss.py` |
| `harden_supervisor_verdict_boundary` | Malformed confidence, violations, citations, and verdict literals | Visible fail-open result; no clean allow or malformed-input deny      | `tests/src/policy/semantic/test_verdict.py`, shadow/engine        |
| `preserve_supervisor_edit_identity`  | Claude fragment edits and Codex delete-only update hunks          | Prompts include removed text and distinct edits cannot share an allow | supervisor, plan-check, and both hook-adapter test modules        |
