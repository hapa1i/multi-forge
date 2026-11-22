# Make session index contention and bulk deletion readable

A concurrent delete held the global session index lock long enough for `forge sess list` to print a Python traceback.
The delete preview printed the same nine QA and walkthrough exclusions for each of 105 sessions. Thirteen worker lease
refusals were interleaved with that inventory.

Keep session listings available during cleanup in another project and identify a contended snapshot with a hint. Report
a lock timeout on commands that require exclusive access. Give `delete --all` and `purge --all` a compact preview and
completion count. Show each refused session and its reason alongside worktree, branch and user-authored content
removals. Purge also shows exact native paths and adopted conversations. Offer the full per-session inventory with
`--verbose`. An apply failure can offer a noninteractive retry only when Forge has saved the approved inventory.

The [session cleanup contract](../../../design_sessions.md#session-cleanup) governs admission, confirmation and retry.
