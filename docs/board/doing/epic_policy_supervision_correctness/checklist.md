# Policy and supervision correctness checklist

Current focus: evidence and member boundaries are complete; start D001 on its own execution branch.

- [x] Recheck D001–D005 and O028 against merged code and normative design.
- [x] Run isolated executable reproductions for every admitted finding.
- [x] Confirm the focused existing policy/supervision suite remains green.
- [x] Split state preservation, verdict hardening, and edit identity into independent members.
- [x] Exclude O044 from Wave 1 pending separate bounded-maintenance admission.
- [ ] Move `preserve_policy_intent_on_enable` to `doing/` on its implementation branch.
- [ ] Review the D001 result before starting either HIGH-severity member.
- [ ] Keep parent/member links and sequencing current as cards move lanes.
- [ ] Close only after every live member ships and the review ledger records the outcomes.

## Member Acceptance Map

| Member                               | Required fixture                                                  | Observable assertion                                                  | Planned test area                                          |
| ------------------------------------ | ----------------------------------------------------------------- | --------------------------------------------------------------------- | ---------------------------------------------------------- |
| `preserve_policy_intent_on_enable`   | Disabled policy with both supervisor configs                      | Re-enable changes bundle fields without changing supervisor intent    | `tests/src/cli/test_policy_enable.py`                      |
| `harden_supervisor_verdict_boundary` | Malformed confidence, violations, citations, and verdict literals | Visible fail-open result; no clean allow or malformed-input deny      | `tests/src/policy/semantic/test_verdict.py`, shadow/engine |
| `preserve_supervisor_edit_identity`  | Claude fragment edits and Codex delete-only update hunks          | Prompts include removed text and distinct edits cannot share an allow | supervisor, plan-check, and both hook-adapter test modules |
