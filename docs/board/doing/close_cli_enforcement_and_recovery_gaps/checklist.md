# Close CLI Enforcement and Recovery Gaps Checklist

Current focus: post-review hardening is implemented; current-head focused and integration reruns remain pending.

## Policy Diff Enforcement

- [x] Add quoted-path fixtures that place the quoted file first, last, and beside an unquoted file.
- [x] Decode Git C-quoted headers and preserve one chunk per file.
- [x] Prove non-ASCII Python violations cannot bypass terminal per-file policy evaluation.

## Targeted Recovery

- [x] Add an explicit-root local Codex recovery regression and bind the disable command to that root.
- [x] Add durable model-route replay health-failure coverage for restart and explicit reroute commands.
- [x] Reuse the persisted-proxy recovery renderer without changing route refusal semantics.

## Post-review Hardening

- [x] Preserve unquoted paths with spaces for pure rename, copy, mode-only, and binary diffs.
- [x] Prefer `+++`, `rename to`, and `copy to` destination metadata before deterministic header fallback.
- [x] Include the replay-equivalent `--model`, and `--model-tier` only when needed, in durable reroute commands.
- [x] Route planning-stage replay failures through the shared refusal renderer without mutation or launch.
- [x] Render recovery commands literally so Rich-like bracketed roots and `[1m]` model suffixes remain exact.

## Verification

- [ ] Run focused policy, extension CLI, model-route, resume, and regression tests.
- [ ] Run required targeted session integration coverage.
- [ ] Record commands, results, and the integrated SHA for batch closeout.

## Acceptance Tests

| Test                    | Fixture                               | Assertion                                | Test File                                  |
| ----------------------- | ------------------------------------- | ---------------------------------------- | ------------------------------------------ |
| Quoted diff boundary    | adjacent C-quoted and ordinary paths  | each file is evaluated independently     | `tests/src/policy/test_diff.py`            |
| Root-bound recovery     | local Codex enable with explicit root | recovery targets the same project        | `tests/src/cli/test_extension_enable.py`   |
| Durable route recovery  | unavailable persisted proxy route     | restart and reroute commands are printed | `tests/src/cli/test_session_model_pins.py` |
| Combined-diff boundary  | ordinary plus combined diff headers   | each patch remains a separate file       | `tests/src/policy/test_diff.py`            |
| Replay planning refusal | stored route fails during planning    | shared recovery; no mutation or launch   | `tests/src/cli/test_session_model_pins.py` |
| Intent-based replay     | stale confirmation and valid intent   | recovery follows durable route intent    | `tests/src/cli/test_session_model_pins.py` |
| Identity mismatch       | wrong process answers stored endpoint | restart is not offered as sufficient     | `tests/src/cli/test_session_model_pins.py` |
| Invalid route request   | malformed stored model projection     | replacement guidance remains actionable  | `tests/src/cli/test_session_model_pins.py` |
| Full route projection   | recorded `[1m]` model request         | model and tier survive command rendering | `tests/src/cli/test_session_model_pins.py` |
| Literal recovery output | bracketed root and `[1m]` model       | copyable command text remains exact      | `tests/src/cli/test_output.py`             |

## Evidence

Current-head evidence is pending the integrated final SHA.
