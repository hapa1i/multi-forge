# B1 PR review corrections, 2026-10-08

These corrections to [PR #260](https://github.com/hapa1i/multi-forge/pull/260) supersede the original implementation's
exact Claude version pin, unconditional schema-v3 writes, and shadow-v5 contract. The earlier dated runtime captures
remain historical evidence. No host logout, login-token copy, or account/settings mutation was used for this review.

## Corrected contracts

| Review concern                       | Correction and proof                                                                                                                                                                                                                                                                                                 |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Checkout-controlled watchdog imports | Both helpers run Python `-I` from `/`; the actual reviewer keeps its original CWD. Planted `json.py`, `random.py`, `token.py`, `typing.py`, and `forge/` can no longer forge stdout. `test_bug_b1_watchdog_imports.py` exercises real subprocesses.                                                                  |
| Evidence failure after a deny        | Final persistence failure retains the computed verdict and adds a warning; the durable start projects as incomplete. `test_bug_b1_evidence_verdict.py` fails the second atomic write for both stages and all verdicts.                                                                                               |
| Unsupported flags and auto-updates   | Require Claude 2.x >=2.1.248 plus every isolation flag. Persist positive and negative capability results by executable identity; a changed executable is reprobed without inference. Setup, host launch, and status report incompatibility. Auth remains checked per subscription dispatch.                          |
| Inherited settings credentials       | Project only auth environment and user-settings `apiKeyHelper`; pass helper settings through an anonymous inherited descriptor. Hooks, permissions, plugins and tools stay excluded. Checkout-specific helpers refuse with recovery guidance. Real Docker inference covers user helper and settings-env credentials. |
| Legacy state and overrides           | Keep tuning overrides, normalize v1/v2 positive timeouts above 45s, remove formerly ignored Claude proxy fields from old Codex bindings, and avoid decoding unrelated partial proxy overrides during launch preference reads. Lane/model/auth validation precedes mutation and freezing.                             |
| Sidecar upgrades and inherited plans | Lossless manifests remain v2. Explicit new fields require v3. Before launch mounts state, an isolated image probe verifies schema and reviewer capabilities. Cascade, reload and launch refuse sidecar plans with recovery guidance.                                                                                 |
| Audit identity and replay            | Attempt schema v2 marks live versus shadow; ambiguous old records do not become live verdicts. Shadow v6 freezes the explicit, lane, proxy-tier, environment or restored-transcript model and its source. Unresolvable candidates do not dispatch; pre-dispatch reconstruction errors do not consume the cap.        |
| Smaller regressions                  | Catalog-backed Claude selectors, handled reload errors, bounded attempt retention (200 per session/root, 30 days), immediate successful watchdog cleanup, and production cache invalidation all have regression coverage.                                                                                            |

The inherited auth projection preserves supported credential sources, but does not promise arbitrary project helper
execution. Move that helper to user settings or export its credential. Operational review failures retain the existing
fail-open policy and report unavailable; setup and launch refuse an unsupported runtime before work begins. Claude
2.1.291 is measured evidence, not the only admitted patch release. Future major versions require a Forge contract
update. Old sidecar images with an active supervisor must be rebuilt to gain the new isolated reviewer.

## Verification

Docker uses disposable identities and explicit API credentials; these runs do not claim subscription billing. The
existing host subscription and protected-settings assertions remain in the [dated record](README.md).

- `make test-regression`: **1,382 passed** on the final code tree, including all **51 B1 regressions**.
- `make test-unit`: **10,593 passed, 1 failed, 117 deselected**. The sole failure is
  `test_shipped_provider_cache_matches_exact_file_bytes`; the changed telemetry/workflow docs need a token-cache
  refresh.
- The native plan, hook-expiry and sidecar-hook suites passed **20** cases. The initial combined run also had five
  fixture failures; the corrected fixtures are covered by the next command.
- `./scripts/test-integration.sh tests/integration/docker/test_reviewer_compatibility.py tests/integration/docker/test_supervisor_auth_isolation.py tests/integration/docker/test_plan_file_supervision.py -k 'not real_executor_hook_expiry'`:
  **6 passed, 8 deselected**. The eight lifetime cases had already passed separately. This covers real settings/helper
  inference, real Claude 2.1.245 refusal, subscription isolation and both deterministic hook adapters.
- Existing real-Claude resumed supervision and policy CLI suites pass **5** cases. The deterministic conversation and
  cascade suite initially failed seven cases because its fake advertised version `99.99.99` without the required help
  flags; after correcting the harness, `./scripts/test-integration.sh tests/integration/docker/test_supervisor_e2e.py`
  passes all **10**. That makes **41 unique passing Docker/integration cases** across these runs.
- `make build` and the [final clean-wheel smoke](2026-10-08-wheel.json) pass. The smoke uses no `.env` or inference and
  covers all four lane consumers, plan lifecycle, policy file/diff, activity, billing labels and the packaged watchdog
  with a planted checkout module. The production image-admission probe also accepts the built sidecar with no mounts or
  network.
- Formatting, type checks, secret scanning, Markdown links, local file line limits and diff whitespace pass.
  `SKIP=file-size-limits make pre-commit` passes; the full file-size gate remains pending.

Automatic approval review rejected the token-counter upload because it sends the full revised design documents to
Anthropic's `count_tokens` endpoint. Explicit approval was requested. The content-matched token cache and the related
unit assertion remain unresolved; these results do not claim a green full pre-commit or unit run. The PR remains draft
until that gate is completed. The previously recorded document counts describe the earlier bytes only.
