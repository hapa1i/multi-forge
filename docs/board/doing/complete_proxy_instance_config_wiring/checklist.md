# Complete proxy instance config wiring checklist

Current focus: open the independently verified D029/O025 draft PR without activating the next member.

## Activation and prior-member closeout

- [x] Merge O014/O026 independently in PR #167 (`33e3db7f`).
- [x] Record its post-merge closeout on `main` at `7c76a099`.
- [x] Start `agent/complete-proxy-instance-config-wiring` from merged `main` at `7c76a099`.
- [x] Move O014/O026 to `done/`, activate only this member, and repoint inbound board links.

## Fail-first reproduction

- [x] Prove template `tool_prefixes_to_ignore` cannot survive proxy creation and runtime projection.
- [x] Prove template `prompt_caching` and `auto_cache_min_tokens` revert to instance defaults at proxy creation
  (`3 failed`, with 2 controls passing on unchanged production code from `7c76a099`).
- [x] Retain controls for absent-field compatibility defaults and unrelated proxy config wiring.

## Implementation

- [x] Carry tool-ignore configuration through the instance schema, serialized proxy file, and runtime projection.
- [x] Carry provider prompt-cache policy and threshold from the selected template provider into the proxy instance.
- [x] Extend the structural wiring guard so future shared/provider fields cannot silently skip a hop.

## Verification and closeout

- [x] Run the config/proxy unit slice plus retained and prior shared-block regressions (`1,015 passed`).
- [x] Run targeted Docker proxy-creation integration coverage (`6 passed`, 24 deselected).
- [x] Run full unit (`8,986 passed`, one existing platform skip, 122 deselected) and marked regression (`758 passed`)
  gates.
- [x] Run pre-commit and final board integrity, lane, link, size, and diff checks (288 files, 713 local links, zero
  missing targets; Wave 6 lanes 4 done/1 doing/7 todo).
- [x] Synchronize design/end-user contracts and record the implementation evidence.
- [ ] Open an independent draft PR without activating the next Wave 6 member.
