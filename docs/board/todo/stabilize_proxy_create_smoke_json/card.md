# Stabilize proxy create smoke-test JSON

**Epic**: [`epic_cli_proxy_runtime_correctness`](../../doing/epic_cli_proxy_runtime_correctness/card.md).

**Finding**: D016 (HIGH) in [`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Lane**: `todo/` -- accepted Wave 5 member, parked behind active O002.

## Goal

Make `forge proxy create --json --smoke-test` emit one parseable result and return failure when upstream verification
fails, while retaining the successfully created proxy.

## Design Authority

- [`cli_style_guidelines.md` scripting/output rules](../../../developer/cli_style_guidelines.md#output-streams): JSON is
  one stable result on stdout, diagnostics use stderr, and failed leaves exit non-zero.
- [`docs/design.md` §3.6.3](../../../design.md#363-proxy-lifecycle-ux): create owns proxy creation and optional
  lifecycle verification.

## Evidence

Rechecked on `3f3a3c6d` with a successful mocked create and a failed smoke probe. JSON mode printed the proxy object and
a second smoke-test object as separate documents, then exited 0. The human branch already exits 1 for the same failed
probe.

## Expected Behavior

- With `--smoke-test`, JSON mode emits exactly one object containing proxy creation facts and the smoke result.
- A passed probe exits 0; a failed probe exits non-zero while honestly reporting that creation succeeded and
  verification failed.
- Without `--smoke-test`, the existing create JSON fields and exit behavior remain compatible.

## Acceptance Criteria

- Add a marked D016 regression covering one-document parsing and failed-probe exit status.
- Cover spawn/reuse/adopt creation sources, smoke success/failure, JSON/human modes, and output streams.
- Run focused proxy CLI/output tests, targeted proxy integration for the smoke path, and `make pre-commit`.

## Compatibility and Exclusions

- Do not roll back or delete a proxy merely because its optional upstream smoke test failed.
- Do not change `proxy start --smoke-test`, template selection, port allocation, or proxy registry semantics.
