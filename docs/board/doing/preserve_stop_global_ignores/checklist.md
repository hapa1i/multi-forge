# Preserve global ignores in Stop evidence

Current focus: PR review of the verified B4 evidence correction on `codex/preserve-stop-global-ignores`, based on `main`
`5613b185`. B5 planning is committed independently at `a5428554`; no B5 runtime probes or implementation are part of
this branch.

## Capture contract

- [x] Reproduce the bug with a disposable repository and synthetic `.env`: ordinary Git omits it, while current capture
  stores it and later comparison emits its changed contents.
- [x] Resolve effective `core.excludesFile` through a bounded, data-only Git config query, including normal config
  precedence, includes, path expansion, and worktree config. Strip inherited repository/index selectors.
- [x] Keep global/system config suppressed for evidence enumeration. Supply only a bounded private copy of the resolved
  ignore rules; retain disabled hooks/fsmonitor and raw reads without filters, textconv, or external diff.
- [x] Preserve Git defaults (`XDG_CONFIG_HOME/git/ignore`, then `HOME/.config/git/ignore`), explicit empty overrides,
  repository-relative paths, and optional missing files. Refuse unreadable, invalid, oversized, or special-file inputs
  within the existing capture deadline. Do not fall back to enumeration without exclusions after a read error.
- [x] Keep tracked files and explicit tool payload semantics unchanged; ignores are not a general secret filter.

## Acceptance evidence

| Test                        | Fixture                                                                                                            | Assertion                                                                                              | Test file                                                 |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------ | --------------------------------------------------------- |
| Original regression         | Temporary global config, synthetic ignored `.env`, normal changed work                                             | Ignored contents absent from snapshots, blobs, and outgoing Stop evidence; normal work reviewed        | `tests/regression/test_bug_stop_global_ignores.py`        |
| Config precedence and paths | Global includes, system/default rules, local override, empty override, tilde/relative path, linked worktree config | Capture's untracked names agree with ordinary Git; tracked files retained                              | `tests/src/policy/semantic/test_turn_evidence_ignores.py` |
| Input failure               | Missing, unreadable, malformed, oversized and FIFO ignore/config inputs                                            | Missing files retain Git semantics; other failures refuse bounded capture before content storage       | `tests/src/policy/semantic/test_turn_evidence_ignores.py` |
| Helper isolation            | Global executable helper settings and trace destinations with marker files                                         | Config lookup and enumeration produce no helper or trace side effects                                  | `tests/src/policy/semantic/test_turn_evidence_ignores.py` |
| Stop composition            | Native-shaped hook inputs, isolated session and Git config, recording reviewer stub                                | Turn-start/tool/Stop lifecycle sends normal work but no ignored content; failures dispatch no reviewer | `tests/integration/core/test_codex_stop_ignores.py`       |

## Verification and review

- [x] Focused tests include a demonstrated failure before the fix and pass afterward.
- [x] Run targeted integration through `scripts/test-integration.sh` with Docker prerequisites; use synthetic evidence
  and a stub reviewer, with no native/model inference.
- [x] Run aggregate unit and regression suites, full pre-commit, and board/link checks; record any failures or skips.
- [x] Update design and end-user evidence-scope documentation with precedence, failure behavior, and scope limits.
- [x] Review the standalone implementation diff; B5 planning changes are excluded.
- [ ] Merge/CI and closeout: verify the merged tree, record completed work, move this card to done, and reconcile B5's
  proposal and prerequisite link before continuing B5.

## Recorded evidence

- Original regression failed against the pre-fix tree: the outgoing Stop review contained both synthetic ignored values.
  After the fix, it passes and checks snapshots and private blobs as well as reviewer input.
- Focused capture/regression checks: 35 passed (9 existing raw-capture tests, 25 exclusion cases, 1 regression). The
  conditional-include fixture was corrected to match the actual Git directory without a trailing slash.
- `make test-unit`: 10,697 passed, 117 integration cases deselected.
- `make test-regression`: 1,542 passed.
- `make pre-commit`: passed, including type, size, link and Markdown checks after formatting.
- Integration covers real hook processes with stubbed admission proof and reviewer dispatch. It does not claim a new
  native Codex run or model/auth validation. Its initial run passed failure cases and recovery; the success assertion
  used the wrong public status key (`status` instead of `state`) and was corrected. The rerun passed all 4 tests.
  Command:
  `env -u GEMINI_API_KEY PYTHON_DOTENV_DISABLED=1 ./scripts/test-integration.sh tests/integration/core/test_codex_stop_ignores.py tests/integration/core/test_codex_stop_recovery.py -q --tb=short`.
