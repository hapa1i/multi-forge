# B4 attribution and lifecycle follow-up — 2026-10-11

Ten ordinary-use regression cases failed against `aa1e0c4d` before these fixes. The first follow-up's broad claims about
carry and recovery were not supported by its tests. Its native captures and validation remain dated history.

Each new prompt uses the current checkout as its starting context. Only pending changes through the last observed tool
outcome or Stop carry forward. Between-turn changes are unattributed and excluded from correction scope. A pending path
also changed by the operator becomes an explicit gap. Unknown newer Stops record missing tracking without inventing
authorship. Commits between turns become baseline metadata; commits observed within unfinished work remain coverage
gaps. Denied requests do not manufacture missing outcomes.

Available incomplete evidence can receive a partial review. Its verdict cannot approve omitted work or trigger an
automatic correction. Unreviewed exclusions remain visible after later successful reviews; they no longer make every
later turn incomplete. Empty/unreviewable scope records the gap without a call. Carry and reset retain their bounded
watermarks, and the Stop notice reports `carry_limit` at the cap.

Every session creation gets a random review owner. Retained artifacts from a deleted name stay historical, even when
that name is recreated immediately or in another checkout. Old hooks cannot modify the replacement session. Missing
owner files and older B4 checkpoint schemas require restoration or a new session rather than a refunded allowance.

Setup validates the effective merged configuration before runtime admission and checks it again under the write lock.
Accepted plan symlinks resolve to the actual source. Patch moves check both paths, and unterminated unified-diff lines
retain their boundaries.

| Regression owner                                                                           | Covered failure                                                                                                 |
| ------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------- |
| [Turn attribution](../../../../../tests/regression/test_bug_b4_turn_attribution.py)        | Manual edits, question-only turns, commits, Finder metadata, suspended intervals, pending work and unknown Stop |
| [Evidence recovery](../../../../../tests/regression/test_bug_b4_evidence_recovery.py)      | Large reads, unsupported changes, later normal reviews and unterminated diff lines                              |
| [Session lifetime](../../../../../tests/regression/test_bug_b4_session_lifetime.py)        | Real deletion/recreation, identical timestamps, changed checkout, lost owner and stale hook                     |
| [Effective configuration](../../../../../tests/regression/test_bug_b4_effective_config.py) | Conflicting overrides and a concurrent trigger change before commit                                             |
| [Review inputs](../../../../../tests/regression/test_bug_b4_review_inputs.py)              | Out-of-scope move sources and symlinked approved plans                                                          |

## Validation

The [native record](attribution-native.json) verifies a new independent login and exactly **eight reserved Codex
units**: one trust ceremony without a model prompt, one empirical enrollment, and six TUI turns (the initial transfer
plus five explicit prompts). All three captures exited successfully. The retained Codex 0.162.1 binary has SHA-256
`74c6a6d263f40d65f99c27a815275f5b4ed0bcc2baecc396b4cf3255498bdfc0`. All four reviewer calls used the local
admission-compatible stub; no real reviewer or API inference ran. The original 32-unit round remains closed.

| Native prompt                                                         | Observed result                                                                                |
| --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Create `work.txt`                                                     | One complete review, one Stop                                                                  |
| Question only, after the operator creates `notes.txt` and `.DS_Store` | No reviewer call; both paths reported as unattributed                                          |
| Append to `work.txt`, after the operator commits its prior version    | One complete review of only that append                                                        |
| Read a 7,500-byte file                                                | One partial review with `tool_evidence_byte_limit`, no correction, exclusion marked unreviewed |
| Append to `work.txt` again                                            | One complete review; the earlier exclusion remains visibly unreviewed                          |

The reviewer prompts contain neither manual path. The manual file remains unchanged. The native sequence tests recovery
and admission/delivery with aligned stub verdicts, not real model review quality. A regression separately verifies that
a partial deny cannot request a correction. Suspended intervals, unknown Stops, missing baselines, session recreation,
configuration races and hostile patch sources have automated coverage; this native round does not claim those cases.

Each capture retains raw streams privately, along with exact source/helper hashes. The execution helpers in
`attribution-native.json` match the publication tree. Two missing-tracking branches in `stop_review.py` were tightened
after the native run: a failed baseline remains outstanding until exclusion, and an unknown newer Stop counts an
unfinished preceding turn in excluded history. The record lists both source hashes and this drift explicitly. The new
automated regressions pass; no native result is relabelled as testing these later changes. The offline verifier/exporter
was added after capture and is hashed separately.

The fixture was closed after validation. No recorded processes survived before cleanup, its independent `auth.json` was
removed, and recorded normal-host config hashes matched. This does not prove remote token validity or revocation.

The focused B4 suite and candidate-state link check passed **93 tests**. The broader integration runner passed **60
tests**, with one real-inference control deselected:

```bash
PYTHON_DOTENV_DISABLED=1 ./scripts/test-integration.sh \
  tests/integration/core/test_codex_stop_recovery.py \
  tests/integration/docker/test_installer.py::TestCodexHooksModule \
  tests/integration/docker/test_installer.py::TestCrossRuntimeSkillLifecycle \
  tests/integration/docker/test_installer.py::TestHookDispatcherRuntime \
  tests/integration/cli/test_stop_verification_integration.py \
  tests/integration/docker/test_supervisor_auth_isolation.py \
  tests/integration/docker/test_supervisor_e2e.py \
  tests/integration/docker/test_session_lifecycle.py -m 'not slow'
```

The recovery integration passed again after the final missing-tracking changes. The
[clean-wheel report](attribution-wheel.json) matches all **380 product Python files** and the QA hook checklist. Enable,
doctor, sync, status, reset help and disable passed with isolated homes, a discovery-only runtime stub and no
`FORGE_DEV`. The wheel SHA-256 is `bc0ef8ef8ef5f33a8b887fe9bd8b395c757025b24961aa4d00e3f5de0decd25e`.

The first aggregate unit run had 10,670 passes and two failures: the old symlink-preservation expectation and a link to
the new, then-unstaged evidence file. Both are corrected. The first pre-commit pass identified test typing, script modes
and formatting; none of its checks were disabled. Final `make test-unit`: **10,672 passed, 117 deselected**. Final
`make test-regression`: **1,541 passed**. Full `make pre-commit` passes with every hook enabled.

The documentation checker was initially rejected by automatic approval review because it can call a provider. The
explicit local-only counter accepted the execution and end-user guides. Only the already-authorized telemetry document
needed Anthropic's count-only API; its cache was refreshed after formatting. No unauthorized document upload occurred.
