# Verify shadow discovery during index contention

Merged as `6962a697`. Its tree matches the tested PR head `95b22ffc`. Both
[Tests](https://github.com/hapa1i/multi-forge/actions/runs/45153756635) and
[Pre-commit Checks](https://github.com/hapa1i/multi-forge/actions/runs/45153756551) passed.

| Fixture                                                                    | Expected CLI behavior                                                            |
| -------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Sibling project has a shadow passport and one legacy session, index locked | Workspace and global discovery exit nonzero with retry guidance and empty stdout |
| Current project has a shadow passport, index locked                        | Project discovery lists its proposal                                             |
| Same projects, lock released                                               | A retry finds the sibling proposal                                               |

- [x] Reproduce the successful empty result for both affected scopes before the fix.
- [x] Guard shared discovery before it selects roots. Document the retry in the
  [memory guide](../../../end-user/memory.md).
- [x] All 217 focused tests and the Docker session listing test passed. In an offline Docker check, a separate process
  held the index lock while `shadows list` and `shadows show` exercised all three scopes. Both commands found the
  sibling proposal again after release. The index bytes stayed unchanged.
- [x] Moved the card to `done/` and recorded the fix in the
  [change log](../../change_log.md#refuse-incomplete-shadow-discovery).
