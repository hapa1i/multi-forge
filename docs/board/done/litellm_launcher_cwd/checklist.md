# LiteLLM launcher working-directory regression

Merged into `main` on 2026-11-23 as `fee340c7`. Its tree matches PR head `61edd4d9`. Both Python test lanes, the
test-selection comparison, pre-commit and CodeQL passed.
[PR #309 checks](https://github.com/hapa1i/multi-forge/pull/309/checks)

| Fixture                                                 | Expected result                                              |
| ------------------------------------------------------- | ------------------------------------------------------------ |
| Empty project-local `litellm.py`                        | The adapter's launcher prints the installed LiteLLM version. |
| Clean wheel launched from `src/forge/backend/adapters/` | The backend starts, responds to its health check and stops.  |

- [x] The launcher regression failed on the original command with an import error and passed with `-P`.
- [x] The clean-wheel smoke test passed from `src/forge/backend/adapters/`, including process-group shutdown.
- [x] All 106 focused adapter, pricing and backend CLI tests and 13 integration tests passed.
- [x] `make pre-commit` passed.
- [x] Moved the card to `done/` and recorded the fix in the
  [change log](../../change_log.md#start-litellm-from-projects-with-a-local-litellmpy).
