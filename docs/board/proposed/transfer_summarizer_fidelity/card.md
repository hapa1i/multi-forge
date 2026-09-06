# transfer_summarizer_fidelity -- retain tool results and delegation descriptions

**Epic**: [epic_native_multiagent](../epic_native_multiagent/card.md) (M2 -- a bug fix that makes lossiness deliberate).

**Lane**: `proposed/`. No dependencies; small enough for a single PR with a regression test.

## Problem (verified 2026-09-06)

`_extract_turn_summary` in `src/forge/session/transfer.py` feeds `structured`, `full`, and `ai-curated` transfers. It
retains `tool_result.content` only when it is a string, so list-form Agent results lose their text. Tool-use rendering
selects file/path/command arguments; an Agent call becomes `Agent(...)`, dropping its type, description and delegation
prompt.

`src/forge/search/extractor.py` already serializes non-string tool results with JSON. The same string-only bug is absent
there. Preserve search coverage; do not introduce an unnecessary extractor rewrite.

## Design

- Join text blocks from list-form tool results in order; omit image payloads and preserve existing result truncation
  limits. Empty or unsupported blocks must not fabricate text or discard supported neighboring blocks.
- Render `Agent(type=<subagent_type>, description=<description>)`, with bounded description and available prompt. Render
  `SendMessage` recipient and description/prompt where present. Keep fields labeled so task text cannot be confused with
  a returned result.
- Preserve string-form results and existing path/command formatting. This fixes accidental loss before strategy
  selection; it does not promise unbounded result carry.
- Add a regression for a real list-form result shape and retain extractor parity coverage.

## Non-goals

No change to strategy selection, source discovery or curated JSON. M3b normalizes Codex sources; M4 and M5 own curation
and child strategy semantics.

## Acceptance

| Test                       | Fixture and assertion                                                                                | Test file                                                                 |
| -------------------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Block-list result survives | Text/image/text result keeps ordered text within the existing cap; image data absent                 | New `tests/regression/test_bug_transfer_drops_block_list_tool_results.py` |
| Delegation rendering       | Agent type, description and bounded prompt; SendMessage recipient; missing fields handled            | `tests/src/session/test_transfer.py`                                      |
| Strategy integration       | Structured/full output and mocked ai-curated input contain the available result text                 | `tests/src/session/test_transfer.py`                                      |
| Existing behavior          | String results, unsupported blocks and ordinary file/command calls retain their contracts            | `tests/src/session/test_transfer.py`                                      |
| Search parity              | Existing extractor retains list-form result text; no production change needed without a failing case | `tests/src/search/test_extractor.py`                                      |

## Design-doc sync

`docs/design_sessions.md` §3.9 (what transfer summaries retain); `docs/end-user/transfer.md` (Agent-line example, if
present). Lossiness remains bounded and documented.
