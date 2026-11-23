# LiteLLM launcher working-directory regression

| Fixture                                                 | Expected result                                              |
| ------------------------------------------------------- | ------------------------------------------------------------ |
| Empty project-local `litellm.py`                        | The adapter's launcher prints the installed LiteLLM version. |
| Clean wheel launched from `src/forge/backend/adapters/` | The backend starts, responds to its health check and stops.  |

- [x] The launcher regression failed on the original command with an import error and passed with `-P`.
- [x] The clean-wheel smoke test passed from `src/forge/backend/adapters/`, including process-group shutdown.
- [x] All 106 focused adapter, pricing and backend CLI tests and 13 integration tests passed.
- [x] `make pre-commit` passed.
- [ ] After merge, record the merge and move the card to `done/`.
