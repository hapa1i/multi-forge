# Wave 8 verified residual maintenance checklist

Current focus: order 4 `harden_worktree_config_copy_safety` is active; orders 5--19 remain parked.

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
- [ ] Ship and close order 4 independently before activating order 5.
