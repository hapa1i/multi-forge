# Preserve unreadable JSON state classification

**Epic**: [`epic_session_durable_state_safety`](../epic_session_durable_state_safety/card.md).

**Finding**: D011 (HIGH) in [`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Lane**: `done/` -- shipped in PR #134 (`6be815bf`) on 2026-08-06.

## Goal

Keep a failed filesystem read distinguishable from malformed JSON everywhere the shared `read_json` primitive is used,
so transient I/O cannot trigger corruption handling or destructive queue outcomes.

## Design Authority

- [`coding_standards.md` §5](../../../developer/coding_standards.md#forge-owned-durable-state): Forge-owned state is
  strict on content and must surface actionable failures without inventing corruption.
- `src/forge/core/state/exceptions.py`: `StateUnreadableError` already defines failed reads as distinct from
  `StateCorruptedError` and forbids treating them as deletable corruption.
- [`docs/design.md` §3.13](../../../design.md#313-async-work-queue): queue retries and poison handling apply to work
  execution failures, not bytes that Forge could not read.

## Evidence

Rechecked on `dc963a7c`: an existing JSON object whose `open()` was made to raise `OSError` caused
`forge.core.state.read_json` to raise `StateCorruptedError`. The generic helper has five production consumers: audit
drift state, team-hook cache, spend-cap state, Codex preflight cache, and workqueue markers. The first two already
degrade through broad best-effort catches; the Codex cache catches only missing/corrupt state; the cap tracker warns and
rebuilds; the queue catches every exception as unrecoverable corruption and moves the marker immediately to `failed/`.

## Expected Behavior

- `read_json` raises `StateUnreadableError` when an attempted read raises `OSError`, `StateCorruptedError` for bad
  JSON/non-object content, and `StateNotFoundError` when the initial existence check proves absence.
- Every production caller is updated atomically: intended caches remain safe misses, cap bootstrap retains its visible
  rebuild path, and an unreadable workqueue marker stays byte-identical and pending for a later retry.
- The queue surfaces the read failure without counting it as processed or poison and without blocking later readable
  markers.

## Implementation Outcome

`read_json` now maps a failed file read to the existing `StateUnreadableError` while retaining distinct initial-absence,
malformed-JSON, and non-object outcomes. The production caller audit kept audit drift state and team-hook caches as
intentional non-destructive safe misses, added unreadable state to the Codex preflight cache-miss contract, and verified
that spend-cap bootstrap still warns and rebuilds from logs.

Workqueue drains now distinguish unreadable bytes from malformed content. An unreadable marker remains byte-identical,
does not increment retry or poison state, contributes a structured non-fatal diagnostic, and does not stop a later
selected marker. CLI startup owns rendering that diagnostic on stderr, so a foreground `--json` result stays parseable;
malformed markers still move directly to `failed/`, and handler failures keep their bounded retry behavior. The queue
processing contract is synchronized in `docs/design.md` and `docs/design_appendix.md` without implementing D021's
newer-schema outcome.

The marked D011 regression failed on the branch base with `StateCorruptedError` and passed after the fix. Focused
reader, caller, workqueue, and CLI coverage passed (198); the Docker startup-queue file passed (9), including a real
non-root permission failure; the regression suite passed (660); and the unit suite passed (8,742 with one pre-existing
platform skip and 118 deselected). Independent review found no design violations and endorsed the queue and consumer
contracts. Its amendments corrected stale GC exception documentation and admitted the separate D046 proxy YAML
follow-up. Final `make pre-commit` passed after Markdown normalization; PR #134 merged as `6be815bf`.

## Acceptance Criteria

- Add `tests/regression/test_bug_d011_unreadable_json_state.py` with `pytestmark = pytest.mark.regression` and a module
  docstring naming D011 and the `OSError` misclassification root cause.
- Unit tests pin the three exception classes at `read_json` and audit all five production callers' intended outcome.
- Workqueue coverage proves unreadable bytes are neither rewritten nor moved, while malformed JSON still moves to
  `failed/` and a later readable marker can run.
- Startup-queue unit coverage proves the foreground result remains valid, the read diagnostic uses stderr, the
  unreadable marker stays pending, and a later readable marker progresses.
- Run `tests/src/core/state/test_io.py`, `tests/src/core/workqueue/test_queue.py`,
  `tests/src/cli/test_startup_queue.py`, `tests/src/core/telemetry/test_caps.py`,
  `tests/src/core/runtime/test_codex_preflight_cache.py`, the focused audit/team-cache tests, then
  `./scripts/test-integration.sh tests/integration/cli/test_startup_queue_integration.py`, `make test-regression`, and
  `make pre-commit`.

## Compatibility and Exclusions

- This is an internal exception-contract correction; update callers in the same change rather than adding a shim.
- Preserve broad best-effort behavior only where it is already intentional and visible; do not turn strict readers into
  silent cache misses.
- Do not address newer workqueue schemas (D021), manifest liveness (D009), or non-object manifest sections (O006).
- Do not extend this JSON-reader fix into the proxy YAML loader; its analogous `OSError` misclassification is tracked
  separately as D046 and still requires runtime reproduction before implementation.
