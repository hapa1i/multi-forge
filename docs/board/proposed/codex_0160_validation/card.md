# Codex 0.160.1 test round

Epic: [Codex supervisor](../../doing/epic_codex_supervisor/card.md). Member **B2**. No new-card dependency; can run
alongside [B1](../../doing/plan_file_supervision/card.md). Supplies evidence for B3, B4 and B5.

## Problem and outcome

The installed CLI is 0.160.1, while Forge's general validated ceiling is 0.149.1. Current documentation and local help
expose useful hook and native fork behavior, but availability is not an end-to-end result. Extend the existing
[Codex probe harness](../../../../scripts/experiments/codex-hooks/README.md) and record which contracts hold on 0.160.1.

The [research](../../doing/epic_codex_supervisor/research.md#installed-codex-versus-verified-forge-contracts) separates
current source claims from local observations. This card is an experiment and compatibility update, not implementation
of the downstream features.

## Probe matrix

| Area                     | Required evidence                                                                                                                                                                                                           |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Allowed-action warnings  | Model demonstrably consumes a nonce carried by the documented `additionalContext` shape; compare Forge's current shape containing `permissionDecision: allow`; the action still executes                                    |
| Operator warnings        | Test PreToolUse `systemMessage` and stderr separately in the interactive UI and event stream; identify operator visibility independently of model-context delivery                                                          |
| Hook timeout             | Deliberately exceed the registered PreToolUse timeout; observe action allow/deny behavior, warning delivery, child-process cleanup and surviving attempt/usage records; compare a controlled earlier Forge timeout          |
| Catch-all coverage/cost  | Count hook deliveries and measure dispatch wall time for `apply_patch`, `update_plan`, MCP, `spawn_agent`, shell commands and long-running `exec_command`/`write_stdin` sessions; distinguish hook overhead from paid calls |
| Background delivery      | Record delivery during a live turn and after a turn, ordering, cancellation, and whether completion starts any new turn; do not use it as an enforcement mechanism                                                          |
| Native planning fork     | Exercise `codex exec fork` with `--ephemeral` and `--output-schema` together, including option placement, source immutability, inherited context, emitted identity and output validation                                    |
| Shared source thread     | Fork an executor thread after both planning and implementation sentinels; observe inherited reasoning, concurrent-source behavior and fork boundary; do not assume an earlier-turn selector exists                          |
| Read-only and recursion  | Prove the fork cannot write to the action checkout; observe which Forge hooks fire inside it and whether depth/consumer markers prevent self-supervision                                                                    |
| Plan events              | Capture actual `update_plan` tool names, payloads, turn identity and completeness; distinguish an agent's plan update from user approval                                                                                    |
| Stop continuation        | Use a single controlled block; capture the follow-up prompt, `stop_hook_active`, turn IDs and repeated Stop events so B4 can bound calls                                                                                    |
| Existing relied-on paths | Recheck trusted registration, SessionStart context, `apply_patch` deny, malformed responses, multi-file behavior, resume and the relevant interactive path                                                                  |

## Method and deliverables

Pin the binary version in each capture. Reuse isolated projects and the harness's operator-approved trust fixture;
synthetic prompts and sentinel outputs must distinguish actual delivery from a hook merely exiting successfully. Keep
raw captures outside the repository and publish sanitized fixtures and a concise results matrix with pass, fail,
unsupported and inconclusive outcomes. Never count an unsuccessful model turn as evidence that a hook does not fire.

Use the selected subscription authentication for the probe set, identify its quota use in advance, and avoid implicit
API fallback. Do not change the user's real hook/trust configuration as a side effect of a headless test.

The catch-all registration also runs Forge's artifact-authority guard **before** the `apply_patch` filter. Any proposal
to narrow it must preserve authority enforcement for other tools, with explicit ownership of any replacement hook. The
registration's timeout and matcher are part of its trusted definition; changed fixtures require enrollment. Measure
non-patch dispatch with semantic supervision both disabled and configured, and verify that skipped policy actions make
no reviewer calls. Record timeout behavior as observed, without assuming the runtime fails open or closed.

## Acceptance and validation

- Every matrix row has a reproducible command, exact version, positive control and retained result. Confirm native-fork
  read-only behavior empirically rather than inferring it from an accepted flag. Report per-tool hook counts and
  latency, and separate operator-only warnings from model-visible content in the results.
- Raise `CODEX_VERSION_VALIDATED` to 0.160.1 only after the existing contracts on which Forge relies pass. Update the QA
  runtime matrix, affected assertions and documentation consistently. Keep the independently validated proxy contract
  ceiling unchanged unless separately tested.
- Negative results for new behavior gate the corresponding B3/B4/B5 design; they are valid experiment results, not
  reasons to claim feature support. Record any fixes or follow-up blockers explicitly before closing this card.
- Re-run only affected probe stages and targeted integration tests after fixes. CLI help inspection alone is not a
  passing test round.
