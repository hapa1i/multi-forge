# Simplify the count-tokens mode selector checklist

Current focus: complete -- order 22 shipped in PR #201 (`b350b4d5`); orders 23--35 remain parked.

## Activation and evidence

- [x] Close order 21 on pushed `main` at `78678e18`, create the execution branch from that exact commit, and move only
  this member to `doing/`.
- [x] Re-run source, help, documentation, and test searches for `--local`, `--provider-api`, `args.local`, and the token
  counting script.
- [x] Confirm omitted mode and `--local` produce the same local result, an OpenAI-shaped provider invocation exercises
  provider selection without network access, and the conflicting pair remains an argparse exit-two error.
- [x] Confirm the activation baseline had no direct script test pinning the four invocation shapes or retained help
  text.
- [x] Confirm `claude-opus-5` is the catalog's canonical Opus default and both Claude IDs use the same local
  `cl100k_base` fallback.

## Implementation

- [x] Make both mutually exclusive flags write one `mode` destination with local as the explicit default.
- [x] Route provider selection from that one destination without changing `count_tokens` or provider fallback behavior.
- [x] Add hermetic subprocess tests for omitted, explicit-local, provider, conflicting, and help invocations.
- [x] Refresh the omitted `--model` default to `claude-opus-5` and pin it through output and help contracts.
- [x] Keep output schemas, exit behavior, provider routing/fallback, and offline local behavior unchanged.

## Verification and closeout

- [x] Run the focused direct script tests (six passed) and real default, explicit-local, and provider repository
  token-count smokes.
- [x] Run the full unit suite (9,216 passed, 1 skipped, 122 deselected) and regression suite (915 passed).
- [x] Run full pre-commit and `git diff --check`; confirm `design.md` (29,986) and the former consolidated design
  appendix (29,987) stay below 30,000 tokens; and audit 356 board documents, 882 local links, zero missing links, and
  Wave 7's 21 done / one doing / 13 todo lanes without a Forge workflow.
- [x] Open PR #201, merge it as `b350b4d5` after all five checks pass, and close order 22 without activating order 23.
