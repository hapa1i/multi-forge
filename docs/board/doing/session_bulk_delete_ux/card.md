# Make session index contention and bulk deletion readable

A concurrent delete held the global session index lock long enough for `forge sess list` to print a Python traceback.
The delete preview printed the same nine QA and walkthrough exclusions for each of 105 sessions. Thirteen worker lease
refusals were interleaved with that inventory.

Report lock contention with the lock path and retry guidance. Give `delete --all` a compact preview and completion
count. Keep each refused session and its reason visible before confirmation, along with worktree, branch and
user-authored content removals. Offer the full per-session inventory with `--verbose`.

The [session cleanup contract](../../../design_sessions.md#session-cleanup) governs admission, confirmation and retry.
