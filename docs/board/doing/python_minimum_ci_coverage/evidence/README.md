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

Both pinned wheel smokes use an explicit `FORGE_WHEEL_SMOKE_PYTHON`, isolated environments and separate local ports.
They check hash-constrained dependency installation, local LiteLLM startup/health, process-group shutdown and temporary
directory removal. No provider inference or dependency changes are involved.

Compact results and exact-identity comparison summaries are retained beside this file. Full local reports and logs under
`/tmp/forge-python-minimum-ci-20261030/` are temporary. CI uploads full reports and a compact comparison summary with
30-day retention; completed acceptance summaries belong in this directory rather than relying on those expiring files.
