# Remove plaintext from proxy converter logs checklist

Current focus: obtain independent review and merge O037/O038/O042.

## Activation and reproduction

- [x] Start `fix/remove-proxy-converter-plaintext-logs` from merged PR #156 at `46e6a309`.
- [x] Move the child epic and O037/O038/O042 from `todo/` to `doing/`, create their checklists, and repoint inbound
  links.
- [x] Add a marked regression covering request/schema plaintext, malformed arguments, non-function tool calls, and
  suppressed DEBUG formatting.
- [x] Confirm the retained regression fails all five cases on `46e6a309` for the reproduced O037/O038/O042 behavior.

## Metadata-only diagnostics

- [x] Replace the full intermediate-request dump with a lazy structural summary containing only counts, flags, and
  bounded identifiers.
- [x] Replace the original-schema dump with structural schema metadata and avoid formatting it when DEBUG is disabled.
- [x] Report malformed argument type/length and fallback action without logging the raw value or embedding exceptions
  that contain it.
- [x] Report non-function tool-call type/key metadata without serializing caller values.
- [x] Preserve conversion return values, raw-argument fallback objects delivered to clients, and tool sanitization.
- [x] Preserve the explicit, guarded, and capped `logging.requests.stream_chunks` raw-debug path.

## Acceptance tests

| Test                           | Fixture                                                 | Assertion                                                           |
| ------------------------------ | ------------------------------------------------------- | ------------------------------------------------------------------- |
| Request/schema confidentiality | system, message, description, schema, and stop canaries | no canary reaches converter records; metadata summary still appears |
| Malformed argument fallback    | invalid JSON string and wrong-typed arguments           | fallback output is unchanged; logs contain type/length only         |
| Non-function tool call         | caller-controlled custom tool-call mapping              | skip behavior remains; logs contain structural metadata only        |
| Suppressed DEBUG cost          | logger above DEBUG and formatting spy                   | request/schema payload formatters are not invoked                   |
| Explicit raw stream opt-in     | `stream_chunks=true`, DEBUG, bounded chunk              | existing opt-in dump remains available and capped                   |

## Verification and closeout

- [x] Run the marked O037/O038/O042 regression (5 passed), focused converter/logging tests (22 passed), and the
  converter/cache control slice (82 passed).
- [x] Run the full unit suite (8,933 passed, one skipped, 122 deselected) and all 701 marked regressions.
- [x] Run the targeted translated-proxy Docker integration through `./scripts/test-integration.sh` (2 passed).
- [x] Review normative and operator docs; no update is required because the existing metadata-only diagnostic contract
  already governs this internal log-text change.
- [x] Retain the safe local exception class on the generic malformed-argument path and admit provider-side catch-all
  exception rendering separately as D053 after reproducing both log leaks.
- [ ] After merge, synchronize the review-ledger resolution, change log, checklist, and lane links.
- [x] Resolve all 125 local paths and 7 fragments across 9 changed Markdown files; find no stale lane references;
  measure the change log at 21,858 tokens / 1,484 lines; and pass diff checks, `make pre-commit`, and explicit checks of
  all 14 changed and untracked files.
- [ ] Receive independent review and merge before activating D035.
