# Verify shadow discovery during index contention

Branch `codex/complete-shadow-discovery`, based on `main` at `14db060e`.

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
- [ ] After merge, record the shipped fix in the board change log and close the card.
