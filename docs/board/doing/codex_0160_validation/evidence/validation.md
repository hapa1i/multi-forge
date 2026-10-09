# B2 validation, 2026-10-09

Codex reservations: **95/100**, including failed launches and retries. Real Claude reviewer allocation and calls: **0**.
No model calls used API credentials. Natural Codex quota-exhaustion detection is unverified.

| Check                                                                                                                                          | Result                                                           |
| ---------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| `make test-unit`                                                                                                                               | 10,603 passed; 117 deselected                                    |
| `make test-regression`                                                                                                                         | 1,382 passed                                                     |
| Focused preflight, QA matrix, hook, installer, harness tests                                                                                   | 171 passed                                                       |
| `./scripts/test-integration.sh tests/integration/docker/test_policy_hooks.py tests/integration/cli/test_policy_cli_contract_integration.py -q` | 32 passed                                                        |
| `./scripts/test-integration.sh tests/integration/core/test_codex_exec_smoke.py tests/integration/core/test_codex_session_start.py -q`          | 2 passed; three real Codex turns                                 |
| `make build`                                                                                                                                   | Wheel and sdist built                                            |
| Clean wheel                                                                                                                                    | Dispatcher, deterministic deny, preflight and QA resource passed |
| `make pre-commit`                                                                                                                              | Passed after formatting                                          |

The host integration runner honored `PYTHON_DOTENV_DISABLED=1`; the missing Gemini-key warning did not affect these
selected tests. The two-turn session test mocks only the curation call. The smoke test originally used an empty per-test
Codex home; adding the existing `real_codex_home` fixture restored the explicitly supplied independent login. Before
that fix the selected run had one failure and one pass. No credential copy or API fallback was used.

An earlier complete unit run had 10,602 passes and 117 deselections. The integrated rerun had 10,602 passes and one
repository-link failure while evidence was unstaged and a link had one extra parent traversal. A second run caught two
newly split evidence files before they were staged. With the evidence stable and staged, all 10,603 tests passed; final
results above supersede those attempts without hiding them. Regression: 1,382 passes.

[artifact.json](artifact.json) records the candidate wheel SHA-256, commands, and actual hook-side module/launcher
paths. The clean private install had **no `FORGE_DEV` or checkout `PYTHONPATH`**. Its durable launcher lived outside the
venv, was recorded by the installer, and imported Forge from wheel `site-packages`. The policy check used a synthetic
payload directly against that dispatcher; it does not claim a second native enrollment ceremony. Preflight reused the
same independent Codex login in place. The installed QA resource retained release pin 0.149.1, Claude pin and shared
validation metadata, with general ceiling 0.161.0. The first artifact inspection used the wrong resource subdirectory;
the corrected check reads the wheel's actual `_extensions/skills/qa` package path.

The [private follow-up helper sources](helper-sources.json) retain the exact concurrent/tool retries, cold replay, real
integration wrapper, wheel inspection, original exporter, teardown and stub-admission commands with path placeholders.

## Harness and publication provenance

The harness committed in `85359aed` post-dates the live round. None of the 19 recorded whole-harness snapshots matches
that committed tree. Every recorded 97 case used an earlier `b2-terminal.py`; the relevant 89–96 cases used earlier
`b2-run.py`/`b2-forks.py`. The committed `sitecustomize.py` hash appears in no run. Comparing the retained Python 3.13
cache with that committed source finds identical normalized executable code after excluding filename/line positions.
This establishes equivalence for that cached module only. Older terminal/run/fork source bodies were not retained, so
their behavioral equivalence is unverified. [The drift audit](harness-drift.json) gives the hashes and case mapping.

The original `export.py` omitted product directories containing `failure`, `missing-login` or `env-`, and TUI
directories containing `failure`. [The selection record](export-selection.json) lists them explicitly. Available
command/process records remain in `provenance.json`, and the results page describes their disposition. These filtered
attempts are not successful observations or negative hook-delivery evidence.

The original ad hoc commands that added `product.json.file_contents` and the first four helper sources were not
retained. The committed [exporter](../../../../../scripts/experiments/codex-hooks/export-evidence.py) reconstructs those
steps and includes all seven historical helpers, the native feedback checks, selection rules and drift audit. Its
private frozen inputs were copied only after all 480 original source hashes matched; no credentials were copied. It
reproduced all 13 unaffected original artifacts byte-for-byte, including `product.json`, the original provenance and all
19 snapshots. New source hashes cover the supplementary inputs. Historical run identities remain unchanged.

Reproduce with Python 3.13:

```bash
python scripts/experiments/codex-hooks/export-evidence.py \
  <round-root>/review-20261010/historical/export-inputs <new-output-directory>
```

The corrected harness preserves auth while refusing destructive baseline reruns after enrollment, captures custom-hook
stdout/stderr/result, and uses the clean launcher for second-terminal trust commands. The three existing auth
regressions now live in `tests/regression/`, alongside the new reset, environment and redaction regressions.

## Review follow-up, 2026-10-10

| Check                                                         | Result                                                                                   |
| ------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `make test-unit`                                              | 10,600 passed; 117 deselected                                                            |
| `make test-regression`                                        | 1,400 passed, including the relocated auth regressions                                   |
| Focused harness regressions, preflight and QA contract checks | 98 passed                                                                                |
| Selected policy Docker/CLI integrations listed above          | 32 passed; no model calls                                                                |
| `make pre-commit`                                             | Passed after Markdown formatting                                                         |
| Frozen-input export                                           | 13 unaffected original artifacts reproduced byte-for-byte; helper/source hashes verified |

The first focused run caught incorrect literal `|` handling in the new round-root substitution. The corrected sanitizer
passes cases containing regex metacharacters and its substitution delimiter. The lower unit count reflects the three
auth tests moving to the regression suite.

A fresh stage 88 and one 97 TUI case on the corrected committed harness remain **pending** the operator's independent
fixture login. Teardown removed that login, and the operator was asked to restore it. No live turn was launched for this
follow-up; the original reservation ledger remains **95/100**. These reruns must use separate capture names and record
their own committed revision. The historical source-drift qualification above remains in force.

The [results](README.md#non-passing-attempts-and-repairs) retain setup, auth, terminal-driver and concurrency failures.
No failed turn counts as negative delivery evidence. Raw artifacts stay in the private round directory; sanitized
selected evidence is in this directory. The sanitizer and staged secret scan passed. The final process sweep was empty,
the fixture auth file was removed, and the retained executable hash was unchanged; [artifact.json](artifact.json)
records teardown.

Final teardown removes only the independently owned fixture auth file, retains the round executable and captures, and
checks registered process identities. Whole-round host-file equality is **unverified** because no initial hash baseline
was captured. Isolated path provenance is available; unchanged file bytes would not prove refresh-token validity anyway.

B1 closeout `79563944` was fast-forward pushed to `origin/main`. B2 stays in `doing/` until PR review and merge; the
changelog and lane move remain merge closeout work. B3–B5 remain proposed with linked measured handoffs.
