# Close CLI Enforcement and Recovery Gaps Checklist

Current focus: implement #4, #9, and #14 as the first contiguous batch series.

## Policy Diff Enforcement

- [ ] Add quoted-path fixtures that place the quoted file first, last, and beside an unquoted file.
- [ ] Decode Git C-quoted headers and preserve one chunk per file.
- [ ] Prove non-ASCII Python violations cannot bypass terminal per-file policy evaluation.

## Targeted Recovery

- [ ] Add an explicit-root local Codex recovery regression and bind the disable command to that root.
- [ ] Add durable model-route replay health-failure coverage for restart and explicit reroute commands.
- [ ] Reuse the persisted-proxy recovery renderer without changing route refusal semantics.

## Verification

- [ ] Run focused policy, extension CLI, model-route, resume, and regression tests.
- [ ] Run required targeted session integration coverage.
- [ ] Record commands and results for batch closeout.

## Acceptance Tests

| Test                   | Fixture                               | Assertion                                | Test File                                  |
| ---------------------- | ------------------------------------- | ---------------------------------------- | ------------------------------------------ |
| Quoted diff boundary   | adjacent C-quoted and ordinary paths  | each file is evaluated independently     | `tests/src/policy/test_diff.py`            |
| Root-bound recovery    | local Codex enable with explicit root | recovery targets the same project        | `tests/src/cli/test_extensions.py`         |
| Durable route recovery | unavailable persisted proxy route     | restart and reroute commands are printed | `tests/src/cli/test_session_model_pins.py` |
