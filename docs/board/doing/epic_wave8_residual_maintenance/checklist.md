# Wave 8 verified residual maintenance checklist

Current focus: reject unknown workflow-policy keys in active order 7; orders 8--19 remain parked.

- [x] Commit and push the bounded Wave 8 admission on `main` (`0d8eb81a`) without activating implementation.
- [x] Close the fork transfer-snapshot correction on pushed `main` (`7a2ad4c1`) before Wave 8.
- [x] Create `agent/trace-failed-provider-attempts` from `7a2ad4c1`; move this epic and only order 1 to `doing/`.
- [x] Recheck O045's Messages and Responses failure seams plus provider-trace capability and event-ID contracts.
- [x] Add fail-first coverage: four missing lifecycle assertions failed and the pre-dispatch control passed on
  `7a2ad4c1`.
- [x] Emit one capability-gated trace per failed provider attempt without changing cost, metrics, status, or body
  behavior.
- [x] Complete focused, unit, regression, targeted proxy/telemetry Docker, pre-commit, documentation-size, and board
  gates.
- [x] Ship order 1 in PR #216 (`634ff40e`) and close it independently before activating order 2.
- [x] Create `agent/offload-proxy-accounting-persistence` from pushed order-1 closeout `e3def8c3`; move only order 2 to
  `doing/`.
- [x] Pin O046's slow-I/O, serial-order, immutable-snapshot, warning, and controlled-shutdown boundaries.
- [x] Move downstream cost, provider-trace, and cap checkpoint persistence off the event loop without changing in-memory
  accounting.
- [x] Complete focused, unit, regression, targeted proxy/telemetry/cap Docker, pre-commit, documentation-size, and board
  gates.
- [x] Ship order 2 in PR #217 (`6b2e0129`) and close it independently before activating order 3.
- [x] Create `agent/strip-openai-account-response-headers` from pushed order-2 closeout `cddfe5c3`; move only order 3 to
  `doing/`.
- [x] Pin O074 in both Messages and Responses relays with mixed-case account header spellings.
- [x] Strip OpenAI organization/project response metadata at the shared header boundary while preserving safe relay
  behavior.
- [x] Complete focused, unit, regression, targeted proxy-routing Docker, pre-commit, documentation-size, and board
  gates.
- [x] Ship order 3 in PR #218 (`4cd859cb`) and close it independently before activating order 4.
- [x] Create `agent/harden-worktree-config-copy-safety` from pushed order-3 closeout `3f50012c`; move only order 4 to
  `doing/`.
- [x] Pin O089/O090's tracked-descendant cleanup and excluded-directory traversal failures.
- [x] Enforce per-file copy/cleanup ownership while preserving exact-file and dirty-retry behavior.
- [x] Complete focused, unit, regression, targeted session/worktree Docker, pre-commit, documentation-size, and board
  gates.
- [x] Ship order 4 in PR #219 (`43a3b29c`) and close it independently before activating order 5.
- [x] Create `agent/unify-cli-failure-diagnostics` from pushed order-4 closeout `2da22c2a`; move only order 5 to
  `doing/`.
- [x] Pin D056/O097's admitted workflow, extension, and policy failure-stream splits, including an auto-detected scope
  prelude before a later conflict.
- [x] Route each admitted non-zero human diagnostic wholly to stderr without changing successful or JSON output.
- [x] Complete final staged pre-commit, documentation-size, board, and diff gates after focused, unit, regression,
  targeted workflow/extension Docker, and clean-wheel verification passed.
- [x] Ship order 5 in PR #220 (`61be7d80`) and close it independently before activating order 6.
- [x] Create `agent/eliminate-runtime-test-skips` from pushed order-5 closeout `3c0a3002`; move only order 6 to
  `doing/`.
- [x] Replace O072's six runtime skips with deterministic template, symlink, and filesystem-identity coverage; the
  focused slice passes 119 tests and the 9,326-test unit suite reports zero skips.
- [x] Complete focused, zero-skip unit, regression, pre-commit, documentation-size, board, and diff gates; 119 focused,
  9,326 unit, and 961 regression tests pass.
- [x] Ship order 6 in PR #221 (`9d6deb7f`) and close it independently before activating order 7.
- [x] Reproduce the provider-dispatch, late destination-symlink, and dry-run stream regressions on pushed order-6
  closeout `113b5670`; activate only `correct_wave8_merged_regressions`.
- [x] Ship and close the corrective follow-up in PR #222 (`02e0ced9`) before deciding whether to activate order 7.
- [x] Create `agent/reject-unknown-workflow-policy-keys` from pushed corrective closeout `071cfd92`; activate only order
  7 after reverifying O083's non-strict external-config boundary.
- [ ] Ship order 7 independently in PR #223 and close it before activating order 8.
