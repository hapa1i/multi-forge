# windowed_incremental_curation -- bound curation calls and reuse unchanged evidence digests

**Epic**: [epic_native_multiagent](../epic_native_multiagent/card.md) (M4 -- affordable curation of retained history).

**Lane**: `proposed/`. Depends on M2 and M3a's normalized source interface/Claude adapter. No dependency on M6 or M3b.
May run alongside M6 after M3a; optional batch C sequences M4 then M5 on one branch. Standalone acceptance is
Claude-source curation; the epic owner verifies Codex parity at P1 after M3b.

## Problem (verified 2026-09-06)

- `MAX_TRANSCRIPT_CHARS = 50000` in `src/forge/session/transfer.py` truncates AI-curated input; `full` fails over its
  context budget. Neither provides bounded curation of all retained evidence in a long session.
- Claude boundaries/summaries and Codex compaction records coexist with earlier retained source records. The runtime's
  replacement context is not a sufficient input. M3a supplies the common interface and Claude adapter; M3b supplies the
  Codex adapter independently.
- The current curated contract has goal, decisions, current state, files and open questions, but no dead ends.
- Caching map outputs alone leaves a reducer whose input grows with session age. A single merge of all digests would
  reproduce the same context-limit problem and would still incur work on every repeat.

## Design

### Windows and evidence

Read M3a's normalized sources in physical append order. Split at compaction boundaries, then deterministically into
bounded windows within each compaction span. Preserve original source-qualified coordinates; do not restart citations at
zero in each window. Oversized text records may be split into bounded map fragments with the same source anchor and
explicit character spans; this does not modify the captured JSONL.

Include available native compaction summaries as labeled cross-checks. They neither replace earlier evidence nor supply
missing encrypted content. Coverage distinguishes all retained eligible records from material the source adapter could
not capture.

Extract failed tool observations deterministically with citations. Mark a reverted edit only with a verified revert
relationship. A non-zero exit alone is an attempt outcome, not proof that the approach was abandoned; a `dead_ends`
entry needs an explicit abandonment/revert or supported explanation from subsequent evidence. Preserve this distinction
in the prompt and validation; do not manufacture intent from an error flag.

### Bounded map and reduce

Use the shared LLM invocation path and existing auth/preflight behavior. `transfer.curation.map_model` selects the map
model; the existing curation model remains the reducer.

Initial defaults: map evidence input up to 8,000 tokens and output up to 1,200; reduction fan-in at most 8, total input
up to 12,000 tokens and output up to 2,400. These are ceilings, additionally bounded by the selected model's context
after prompt/output reserves. Validate settings and split smaller when necessary; reject a model/configuration unable to
fit even one bounded input. No call may receive every digest from an arbitrarily long session.

Map windows into the curated contract. Reduce through an ordered tree of bounded groups until one digest remains. Cache
intermediate reduction nodes as well as maps. A changed tail recomputes its map and affected tree ancestors; unchanged
runs reuse the final digest. An earlier edit invalidates the affected windows and ancestors. Do not promise that a
repeat makes only one map call, or that a growing reduction frontier is free.

### Cache, failures and output

- Cache under `<artifacts>/<session>/transfer/windows/` and `transfer/reductions/`. Keys include normalized content or
  child-digest hashes, source/coverage identity, adapter/summarizer version, prompt/schema version, selected model, and
  settings affecting output. Snapshot version alone must not invalidate unchanged windows.
- Validate cached JSON, references and coverage before use; corrupt or incompatible entries become cache misses with a
  diagnostic. Writes are atomic. Parent-root caches may be read for a derived session; native directories are not a
  cache dependency.
- Add `dead_ends: [{text, citation}]` to the curated contract and render a Dead ends section. Use M3a's shared citation
  formatter. A missing citation cannot be repaired by guessing a turn.
- Preserve bounded structured fallback when a map/reduce call fails; report which windows lack a valid digest and that
  fallback occurred. Do not label partial work as complete curation. If the fallback itself exceeds the launch budget,
  require a smaller explicit strategy instead of silently truncating.
- `transfer show` reports covered/omitted source ranges, window counts, cache hits, actual call usage and fallback
  status. Summarization is lossy: every eligible retained record must enter a map window, but the final prose need not
  cite every turn. Parent `minimal` and `full` retain their existing size semantics.

## Non-goals

No child selection, native orchestration or search UI. M5 applies this machinery to selected child sources. No claim
that deterministic extraction can establish every dead end or that cache reuse makes model synthesis lossless.

The runtime-neutral interface handles unavailable evidence and original coordinates now. Actual Codex rollout curation
is P1 in the [epic parity table](../epic_native_multiagent/card.md#codex-parity-closeout), owned by the epic integrator
after M3b/M4. That gate does not prevent this card from shipping verified Claude curation.

## Acceptance

| Test                           | Fixture and assertion                                                                                            | Test file                                                                  |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Window boundaries and coverage | Multiple compactions, long span and oversized record; every eligible retained record/fragment mapped once        | `tests/src/session/test_transfer.py`                                       |
| Bounded reduction              | Hundreds of windows; inspect every mocked call's input/output limits and fan-in, including final reduction       | `tests/src/session/test_transfer.py`                                       |
| Incremental reuse              | Unchanged run makes no LLM calls; tail/earlier edit recomputes only changed maps and affected reduction nodes    | `tests/src/session/test_transfer.py`                                       |
| Cache validity                 | Model/prompt/schema changes and corrupt/partial cache entries invalidate safely; writes remain atomic            | `tests/src/session/test_transfer.py`                                       |
| Dead-end evidence              | Failure followed by success is not abandonment; explicit abandoned approach and verified revert retain citations | `tests/src/session/test_transfer.py`                                       |
| Source-coordinate conformance  | Synthetic normalized unavailable/partial records retain M3a coverage and original-coordinate citations           | `tests/src/session/test_transfer.py`                                       |
| Failure and budget             | Partial map/reduce failure yields labeled bounded fallback or actionable refusal, never false full coverage      | `tests/src/session/test_transfer.py`, `tests/src/cli/test_transfer_cli.py` |
| Regression                     | A transcript above the old cap retains early and late evidence in map inputs without an unbounded reducer        | New `tests/regression/test_bug_curation_long_history_loss.py`              |
| Runtime path                   | Targeted Docker/session flow exercises transfer generation and existing curation auth/failure behavior           | Extend `tests/integration/cli/test_artifact_hooks_integration.py`          |

## Design-doc sync

`docs/design_sessions.md` §3.9 and §H (schema, budgets, coordinates, caches and fallback); `docs/end-user/transfer.md`
(dead-end meaning, settings, cost expectations and coverage).
