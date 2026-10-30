# Python CI verification evidence

The local matrix uses Python 3.11.14 and 3.13.11 on macOS arm64, with uv 0.9.18 and the unchanged reviewed lock.
`.python-version` remains `3.13`. The 3.11 project environment is isolated from the existing development environment.

Each full-suite command sets `UV_PYTHON` and passes `--expected-python` plus `--python-evidence` through
`PYTEST_ADDOPTS` to the standard Make target. The report records the controller and every xdist worker's actual
interpreter, the exact selected node IDs, collection completeness and the final pytest exit status. The comparator
validates both lanes and compares the selected identity multisets without normalization or exceptions.

Focused tests cover real serial and xdist collection, deselection, duplicates, controller/worker mismatches before test
execution, failed or interrupted collection, report-write failure and incomplete/malformed comparison inputs. An
existing nested collection probe now clears inherited pytest options and asserts that the parent's evidence is
preserved. Independent review also corrected failed-comparison summary retention in CI.

The [first CI attempt](ci-first-attempt.json) passed interpreter selection but failed the same 18 CLI content assertions
in both lanes. Rich can capture `COLUMNS` when a console is constructed; changing the environment later does not
override that explicit width. An 80-column local control reproduced the wrapping failures with matrix evidence disabled.
The session and activity fixtures now set their intended console widths directly and restore the exact prior value.
Existing assertions are preserved, and a subprocess regression covers the three affected fixture surfaces.

The [second CI attempt](ci-second-attempt.json) passed all unit tests in both lanes, then exposed the same late-width
setup in a cross-project session regression. Its CI temporary path split `subproject` across lines. Both complete local
regression runs passed 2,258 cases under `COLUMNS=80`; different path lengths hid that assertion failure locally. The
helper now fixes the shared console width, and the subprocess guard uses an initial width narrower than `subproject` so
a different temporary path cannot hide the failure.

The [fixture correction checks](local-fixture-correction.json) retain the 217 passing focused cases and subsequent local
outcomes under `COLUMNS=80`. Concurrent full-unit reruns each hit one unrelated failure: a Markdown-link test observed
an evidence file before staging, and a Git probe exceeded its 0.5s deadline under load. Both cases and the new
regression passed sequential isolated checks on each version. The initial passing local matrix remains in
`local-checks.json` and `local-comparison.json`; final complete matrix evidence must come from the clean CI run.

Both pinned wheel smokes use an explicit `FORGE_WHEEL_SMOKE_PYTHON`, isolated environments and separate local ports.
They check hash-constrained dependency installation, local LiteLLM startup/health, process-group shutdown and temporary
directory removal. No provider inference or dependency changes are involved.

The [third CI attempt](ci-third-attempt.json) passed both complete suites but exposed the existing ten-second backend
readiness limit in both installed-wheel checks. [Controlled cold-start probes](local-cold-start.json) retain successful
and failed Linux measurements, including a healthy start after 14.206s. The adapter now gives cold startup a 30-second
monotonic readiness budget; the smoke does not prewarm imports. Delayed readiness and exhausted-budget regressions cover
the single launch and full process-group cleanup paths.

Compact results and exact-identity comparison summaries are retained beside this file. Full local reports and logs under
`/tmp/forge-python-minimum-ci-20261030/` are temporary. CI uploads full reports and a compact comparison summary with
30-day retention; completed acceptance summaries belong in this directory rather than relying on those expiring files.
