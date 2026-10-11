# B5 installed product verification

The [machine-readable export](product.json) records twelve P1/P2 starts: six executors (including one enrollment turn)
and six native reviewers. The complete B5 ledger is **60/60 starts, 3/4 API starts**. There were no Claude model calls.

## Observed product behavior

| Control                | Installed result                                                                                                               |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Enrollment             | All five registered hooks delivered; Stop enrollment verified                                                                  |
| Separate source, allow | Native amber planning context allowed one amber edit; hook 8.7 s                                                               |
| Separate source, deny  | Native amber plan blocked violet; target file absent; hook 10.1 s                                                              |
| Shared active source   | Stop copied the actual active prefix, preferred approved COBALT over LIME, requested one correction; hook 9.6 s                |
| Claude adapter         | A synthetic host-Claude Write payload reached the installed adapter and a real native reviewer; aligned, about 8 s             |
| Source-only denial     | Final-wheel PreToolUse blocked violet; model received a fixed diagnostic with no unverified conversation quotation; hook 8.4 s |
| Final-wheel Stop       | Verified source/config/plan freshness, copied input, global-ignore exclusion and approved-plan-only correction; hook 10.8 s    |

Both Stop controls ended with COBALT on disk. Each had two Stop deliveries and exactly one reviewer start; the second
Stop left correction changes `unreviewed`. Feedback text was found in the executor's native history. The final control's
synthetic globally ignored sentinel was absent from reviewer stdin. The dedicated reviewer children had no executor
session, Forge root, run identity or development override, and forced ChatGPT auth on the `fork` leaf. All selected
original prefixes remained byte-identical; active executor histories naturally advanced after their hook returned.

All six live attempt records contain distinct reviewer IDs, selected-prefix hashes, input preservation, independence,
model/auth and usage baselines. Each joins exactly one `supervisor` usage event for the correct session. Delta input
counts were 14,157; 14,160; 15,582; 14,160; 14,158; and 16,857, with cached/output counters retained separately. These
are newly attributed review tokens, not inherited terminal totals or measured invoice/quota changes.

Installed terminal checks covered adoption from existing native evidence, native setup, dedicated auth status,
supervisor status, lane show/set/clear, telemetry activity, refusal without the Stop plan and explicit API
configuration. API setup refused a missing key, accepted a synthetic environment key without inference, then reported
unavailable after that key was removed. The gate's three real API starts remain the runtime billing-route evidence.

## Candidate and controls

`make build` built a wheel from the source distribution. Private clean virtualenvs installed it with independently
resolved runtime dependencies. `FORGE_DEV` was unset throughout product calls. The final wheel SHA-256 and every
installed Python-source hash are in [product.json](product.json); the exporter compared installed code, including
bundled extension scripts, byte-for-byte with the working tree and found no drift.

The fixture's second independent login was relocated into the marked product reviewer home, without duplication or
access to ordinary credentials. A private `.pth` instrument reserved starts at the actual production subprocess spawn,
including the watchdog's reviewer child; it passed argv, environment and stdin unchanged. It observed installed hooks
in-process, preserving the native parent chain. The counter refused anything beyond the existing per-case/role ceilings.

Reproduction uses `b5-product-budget.py` in an owned, separately logged-in fixture and the installed CLI commands
retained in the export. `b5-product-export.py` asserts dispatch/usage counts, selected-prefix integrity, feedback
delivery, Stop correction behavior and installed-source equality before writing the sanitized report. It copies neither
credentials nor native histories. The fixture requires a fresh explicit budget to run again.

## Qualifications

- P1 and the first P2 pair preceded the final stale-input guard. The final P2 Stop used that guard and the final wheel.
  Source, plan and config races also have installed-invoker tests that change each input after a stub completes and
  assert an unavailable outcome with exactly one dispatch. Earlier controls are evidence for the unchanged transport.
- The Claude adapter used a synthetic hook payload with a real Codex reviewer; it was not a live Claude executor. Its
  observer failed during exit on an empty byte-write probe. Native result, attempt and usage evidence survived; the
  observer was corrected before P2 without repeating inference.
- Product probes used short sources and subscription `gpt-6.1-sol`. Model/auth switching, long and genuinely compacted
  histories, sentinel retention, read-only negative controls and detached native lifetime behavior are the earlier gate
  evidence. Admission preserves those measured limits; it does not establish arbitrary native history support.
- The targeted integration runner explicitly deselected eleven legacy native cases needing separate B1/B3/B4 fixtures or
  additional paid calls. New B5 native controls compose those shipped feedback/Stop paths within this budget.
- The gate previously observed an ordinary Codex config hash change of unknown origin. No restoration was attempted;
  these captures do not claim that ordinary settings stayed unchanged across the whole gate.

Product code, documentation and review remain on the B5 branch. Shipping and board closeout require PR review, merge,
merged-tree verification and CI.

## Fixture teardown

The [teardown record](product-teardown.json) confirms no remaining fixture processes, a free reviewer lease, successful
logout of both independently obtained fixture logins, and removal of product copied histories and indexes. All three
fixture homes have no `auth.json`. The private round is marked closed at 60 starts; synthetic source histories, captures
and installed candidates remain available for audit without credentials. Ordinary credentials were not accessed during
teardown. The earlier unexplained ordinary config change remains an explicit qualification.
