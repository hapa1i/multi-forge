# Align CLI failure surfaces checklist

Current focus: implementation and all verification gates are complete; obtain independent review and merge without
activating another Wave 6 member.

## Activation

- [x] Close D031 after PR #173 (`a55ab218`) and record the bookkeeping on `main` at `13ecef87`.
- [x] Start `agent/align-cli-failure-surfaces` from that merged-main cursor.
- [x] Move only D032/D041/O005/O031--O033 to `doing/` and keep the remaining three Wave 6 members parked.

## Fail-first reproduction

- [x] Prove status-line exits 0 with bounded output for valid JSON scalars, null/wrong-typed workspace, and malformed
  proxy URLs.
- [x] Prove bare `forge` and selectorless human `session show` use their documented non-zero failure shapes.
- [x] Prove unique and ambiguous cross-project hints plus JSON workflow-preflight failures stay entirely on stderr.
- [x] Prove proxy, template, runtime-config, and Claude-preset edit preserve shell-style `$EDITOR` argv.
- [x] Retain successful status-line, explicit help, ambient JSON session context, and single-token editor controls
  (`19 failed, 4 passed` on `13ecef87`).

## Implementation

- [x] Validate the status-line input boundary and make proxy URL parsing fail open without changing configured segments.
- [x] Align missing-command exits and failure streams with the shared CLI output contract.
- [x] Route all four configuration editors through one shell-style argv parser while preserving validation and recovery.

## Verification and closeout

- [x] Run focused status-line, command-tree, session, workflow, output-stream, and editor tests (`809 passed`).
- [x] Run the marked regression (`844 passed`) and unit (`9005 passed, 1 skipped, 122 deselected`) gates.
- [x] Run the targeted status-line (`17 passed`) and session-show (`2 passed`) Docker integration slices.
- [x] Run full pre-commit (all hooks passed after the expected Markdown normalization pass).
- [x] Synchronize bundled QA guidance for stderr JSON preflight failures; confirm the normative design/end-user docs
  already specify the restored contracts.
- [x] Verify the QA content guard (`81 passed`) and confirm the built wheel contains both corrected probes and the index
  update.
- [x] Record the human-mode workflow preflight stream split as separately gated D056 rather than widening O033.
- [x] Run board link/lane/size and diff checks (295 Markdown files, 723 relative links, 2 changed-document fragments, no
  missing targets, 9 done / 1 doing / 3 todo, 741 checklist tokens, and a clean diff check).
- [ ] Open an independent PR and merge before activating another Wave 6 member.

## Acceptance tests

| Test                   | Fixture                                                                   | Assertion                             | Test file           |
| ---------------------- | ------------------------------------------------------------------------- | ------------------------------------- | ------------------- |
| Status input shape     | scalar or null/wrong-typed workspace                                      | bounded output and exit 0             | retained regression |
| Proxy URL fallback     | malformed `ANTHROPIC_BASE_URL`                                            | no traceback and exit 0               | retained regression |
| Missing command        | bare root or selectorless human show                                      | help/error contract and non-zero exit | retained regression |
| Diagnostic stream      | cross-project hint or JSON preflight error                                | stdout empty; full payload on stderr  | retained regression |
| Editor argv            | four edit surfaces with a multi-token `$EDITOR`                           | program, option, then temp path       | retained regression |
| Compatibility controls | valid status input, explicit help, ambient JSON context, one-token editor | existing successful behavior remains  | retained regression |
