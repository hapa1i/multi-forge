# Codex runtime test round

Epic: [Codex supervisor](../../doing/epic_codex_supervisor/card.md). Member **B2**. No new-card dependency.
[B1](../../done/plan_file_supervision/card.md) has shipped; this card supplies broader runtime evidence for B3, B4 and
B5. Completed 2026-10-10 after [PR #261](https://github.com/hapa1i/multi-forge/pull/261) merged to `main` as `2a15c087`.
The [merged closeout](checklist.md#merged-closeout) records verification and remaining evidence limits; the
[2026-10-09 results](evidence/README.md) cover retained Codex 0.161.0. B3-B5 remain proposed.

## Problem and outcome

At activation, Forge's general validated ceiling was 0.149.1. The round tested and retained the installed Codex 0.161.0
executable, then raised only the general ceiling; the blocking QA pin remains 0.149.1. Documentation and CLI help are
leads, not end-to-end evidence. The extended
[Codex probe harness](../../../../scripts/experiments/codex-hooks/README.md) records which contracts hold on the
selected binary. The checklist retains the dated installation observation; the slug and execution branch name stay
unchanged.

The [research](../../doing/epic_codex_supervisor/research.md#installed-codex-versus-verified-forge-contracts) separates
current source claims from local observations. This card is an experiment and compatibility update, not implementation
of the downstream features.

## Probe matrix

| Area                     | Required evidence                                                                                                                                                                                                           |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Allowed-action warnings  | Model consumes a nonce from `additionalContext`; compare current product stdout and Forge's explicit-allow feedback helper; the action still executes                                                                       |
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

Record the binary path, SHA-256, and version in each capture, using the retained round copy. Reuse isolated projects and
an operator-approved trust fixture with its own login. Synthetic prompts and sentinel outputs must distinguish actual
delivery from a hook merely exiting successfully. Keep raw captures outside the repository and publish sanitized
fixtures and a concise results matrix with pass, fail, unsupported and inconclusive outcomes. Never count an
unsuccessful model turn as evidence that a hook does not fire.

Use the selected subscription authentication for the Codex probe set, identify its quota use in advance, and avoid
implicit API fallback. Do not clone the host's refreshing auth cache or change real hook/trust configuration. Nested
semantic reviewers default to an admitted Claude stub; any required real Claude review uses B1's subscription-only
policy and separately budgeted quota. The checklist defines build provenance and cleanup gates.

The catch-all registration also runs Forge's artifact-authority guard **before** the `apply_patch` filter. Any proposal
to narrow it must preserve authority enforcement for other tools, with explicit ownership of any replacement hook. The
registration's timeout and matcher are part of its trusted definition; changed fixtures require enrollment. Measure
non-patch dispatch with semantic supervision both disabled and configured, and verify that skipped policy actions make
no reviewer calls. Record timeout behavior as observed, without assuming the runtime fails open or closed.

## Acceptance and validation

- Every matrix row has a reproducible command, exact version, positive control and retained result. Confirm native-fork
  read-only behavior empirically rather than inferring it from an accepted flag. Report per-tool hook counts and
  latency, and separate operator-only warnings from model-visible content in the results.
- Advance `CODEX_VERSION_VALIDATED` to the recorded round version only after the selected relied-on contracts pass,
  including Forge preflight, enrollment receipts, and usage attribution. Update the QA matrix's `general_probe_ceiling`
  only; preserve its release pin, probe records, and shared provenance. Keep the independent proxy-contract floor
  unchanged. Record B2's evidence and live quota-exhaustion limitation separately.
- Negative results for new behavior gate the corresponding B3/B4/B5 design; they are valid experiment results, not
  reasons to claim feature support. Record any fixes or follow-up blockers explicitly before closing this card.
- Re-run only affected probe stages and targeted integration tests after fixes. CLI help inspection alone is not a
  passing test round.
