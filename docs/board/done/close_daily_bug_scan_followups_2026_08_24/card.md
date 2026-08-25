# Close Daily Bug Scan Follow-ups 2026-08-24

**Lane**: `done/`

## Goal

Close the six reproducible cleanup, model-route, and Markdown-enforcement gaps left after PR #245.

## Scope

- Preserve shared native-relocate transcripts when force-deleting a schema-invalid manifest.
- Reclaim Claude agent logs in the repository-documented nested subagent layout.
- Reject model-route selection when runtime configuration resolves the launch to sidecar mode.
- Keep blank stored proxy templates from acquiring same-URL registry identity during bare replay.
- Preserve internal symlink spelling when a supplied Markdown source uses an external repository alias.
- Run the repository-wide Markdown audit for deletion-only commits.

## Constraints

- Keep the final transcript ownership scan and unlink under the existing publication lock.
- Treat raw corrupt-manifest fields as untrusted and accept only the narrow native-relocate shape needed for safe
  cleanup.
- Reject unsupported sidecar routing before proxy realization or session-state mutation.
- Preserve explicit model-route replacement as the recovery path for malformed stored routing.
- Preserve resolved containment checks and lexical Git candidate identity in Markdown validation.
- Avoid unrelated refactoring or public CLI changes.

## Acceptance

1. A late sibling published while force-deleting a schema-invalid aliased native-relocate session retains its
   transcript.
2. Unowned nested `<uuid>/subagents/agent-*.jsonl` logs are reclaimed with the aliased transcript.
3. Config-derived sidecar mode rejects fresh and replayed model routes before route side effects.
4. Bare replay rejects a blank stored proxy template even when a same-URL registry entry exists.
5. External repository aliases do not erase an internal symlink spelling during manual Markdown validation.
6. A deletion-only Markdown change invokes the repository Markdown hook and detects broken links.
