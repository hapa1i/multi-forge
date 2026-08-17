# Unify resume routing-reference resolution checklist

Current focus: complete -- order 24 shipped in PR #203 (`0d041b83`); orders 25--35 remain parked.

## Activation and evidence

- [x] Close order 23 on pushed `main` at `6e4038db`, create the execution branch from that exact commit, and move only
  this member to `doing/`.
- [x] Re-run source, caller, import, and test searches for `_resume_context_ref`, `_resume_fresh`,
  `_resume_fresh_native`, `_resume_fresh_rewind`, and context-limit resolution.
- [x] Confirm all three fresh-mode copies preserve inherited proxy-ID/template and direct behavior but omit template
  fallback for an explicit template-only `ResolvedRouting`.
- [x] Record the focused resume/mode/routing baseline before implementation (73 passed).

## Implementation

- [x] Route transfer, native, and rewind fresh resume through `_resume_context_ref`.
- [x] Remove the three duplicated calculations and their now-unused local imports.
- [x] Pin explicit proxy-ID precedence, explicit template fallback, inherited routing, and direct mode.
- [x] Keep routing resolution, proxy health, context-limit lookup, transfer serialization, and launch behavior otherwise
  unchanged.

## Verification and closeout

- [x] Run focused resume, native-mode, rewind, review, and routing regression tests (79 passed).
- [x] Run the full unit suite (9,220 passed, one skipped, 122 deselected), regression suite (921 passed), and targeted
  Docker session resume coverage (16 passed, 53 deselected).
- [x] Run full pre-commit and `git diff --check`; confirm `design.md` (29,974) and `design_appendix.md` (29,990) stay
  below 30,000 tokens; and audit 358 board documents, 882 local links, zero missing links, and Wave 7's 23 done / one
  doing / 11 todo lanes without a Forge workflow.
- [x] Open PR #203, merge it as `0d041b83` after all five checks pass, and close order 24 without activating order 25.
