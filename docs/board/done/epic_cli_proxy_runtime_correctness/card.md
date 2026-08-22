# Epic: CLI, proxy, and runtime correctness

**Parent epic**: [`epic_repo_maintenance_round`](../epic_repo_maintenance_round/card.md).

**Lane**: `done/` -- all seven bounded HIGH members shipped independently in PRs #148--#154; the coordinated outcome
closed on 2026-08-09.

## Goal

Make shared downstream retention, machine-readable CLI outcomes, proxy lifecycle state, request/response metadata, and
status-line source discovery tell one observable truth without combining seven independently reviewable fixes.

## Design Authority

- [`downstream_retention_ownership`](../downstream_retention_ownership/card.md) (DG3): the shared downstream directory
  has one global policy and one pruner, with fail-closed conflict handling.
- [`cli_style_guidelines.md`](../../../developer/cli_style_guidelines.md#output-streams): scriptable output is one
  stable JSON result, diagnostics/errors use stderr, and failed leaves exit non-zero.
- [`docs/design_runtime.md` §3.6.3](../../../design_runtime.md#363-proxy-lifecycle-ux): proxy configuration and process
  lifecycle are owned by the proxy surface.
- [`docs/design_telemetry.md` §A.8](../../../design_telemetry.md#a8-status-line-guidance-3611): status-line sources are
  selected to serve configured segments and runtime truth.
- [`docs/design_telemetry.md` §A.11](../../../design_telemetry.md#a11-intercept-audit-and-request-logging-configuration-7x)
  and [§A.14](../../../design_telemetry.md#a14-provider-lifecycle-fields-in-downstream-telemetry-314): audit/provider
  records share downstream shards, while request diagnostics remain separate.
- [`review_combined.md`](../../review_combined.md): D015--D018 and O001--O004. O003 already shipped in Wave 3 and is not
  readmitted here.

## Reproduction Record

The seven remaining HIGH findings were rechecked on merged `main` at `3f3a3c6d`. One disposable pytest module passed
seven broken-behavior characterizations and was removed after evidence capture.

| Finding | Fixture                                                                   | Observed result                                                            |
| ------- | ------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| D015    | one 30-day-old downstream shard; audit 90d pass, then provider-trace 14d  | the first policy preserved the shard; the second deleted it                |
| D016    | `proxy create --json --smoke-test`; injected failed smoke probe           | two top-level JSON documents were printed and the command exited 0         |
| D017    | corrupt search BM25/document stores; query/status in human and JSON modes | query exited 0 twice; status exited 1 only in JSON mode                    |
| D018    | status line configured with only `path` and `branch`                      | both eager proxy and session discovery functions still ran                 |
| O001    | translated LiteLLM model plus the route's User-Agent gate                 | detector returned `litellm`; the gate accepts only other literals          |
| O002    | stop helper forced to return `error` for `proxy stop` and `proxy delete`  | stop exited 0; delete removed ownership, printed `Deleted`, and exited 0   |
| O004    | Anthropic passthrough returned 429 with retry/rate-limit headers          | status/body survived; both upstream control headers were absent downstream |

## Members and Sequence

| Order | Finding | Member                                                                                            | Review boundary                                      |
| ----- | ------- | ------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| 1     | D015    | [`unify_downstream_retention`](../unify_downstream_retention/card.md)                             | global policy, compatibility resolver, single pruner |
| 2     | O002    | [`preserve_proxy_ownership_on_stop_failure`](../preserve_proxy_ownership_on_stop_failure/card.md) | process stop, registry/config ownership, exit truth  |
| 3     | D016    | [`stabilize_proxy_create_smoke_json`](../stabilize_proxy_create_smoke_json/card.md)               | one JSON document and smoke-test result status       |
| 4     | D017    | [`align_search_corruption_failures`](../align_search_corruption_failures/card.md)                 | corruption diagnostics and exit parity               |
| 5     | O001    | [`forward_litellm_user_agent`](../forward_litellm_user_agent/card.md)                             | translated request metadata gate                     |
| 6     | O004    | [`relay_anthropic_response_headers`](../relay_anthropic_response_headers/card.md)                 | safe upstream response-header relay                  |
| 7     | D018    | [`make_statusline_sources_segment_lazy`](../make_statusline_sources_segment_lazy/card.md)         | segment dependencies and status-line hot-path I/O    |

D015 goes first because two startup passes can delete shared telemetry under a policy the operator did not choose, and
DG3 already resolves its broader config/migration contract. O002 follows because a failed stop currently discards or
misreports process ownership. D016 and D017 then establish the machine-readable failure contract before the two
independent proxy metadata fixes. D018 ships last because its lazy source plan must preserve the default bar while
declaring segment dependencies across the registry.

This child epic is intentionally bounded to the seven remaining HIGH findings admitted above. Any MEDIUM correctness
rows later accepted into canonical Wave 5 require a separately reviewed admission record and execution cards; they do
not expand this epic's member count or closeout condition.

All seven members shipped as separate review boundaries. D015 through D017 and O001/O002/O004 established global
retention ownership, truthful CLI/process outcomes, and safe request/response metadata in PRs #148--#153. D018 then made
shared status-line source acquisition segment-lazy without changing the default bar and shipped in PR #154 (`c4f14037`).
Each member retained its fail-first regression and passed the verification required by its scope: focused coverage,
targeted Docker coverage where applicable, packaging, and pre-commit; independent review completed before every merge.

## Drift Constraints

- A smoke-test failure does not roll back an otherwise successful proxy creation; it reports created-but-unverified in
  one JSON object and exits non-zero.
- Intentional process survivors (`--no-kill`, adopted default behavior, or shared-port ownership) remain successful and
  explicitly named; only an attempted/refused/failed stop is an error.
- Search not-built and empty-result outcomes remain successful; corruption is distinct from absence in every mode.
- Keep inbound credentials and Forge correlation headers out of upstream forwarding. Preserve existing User-Agent
  sanitization and do not broaden the Anthropic passthrough request allowlist.
- Relay only safe upstream response headers; strip hop-by-hop, security-sensitive, and proxy-owned correlation fields,
  and preserve Anthropic response bytes and streaming teardown.
- A configured status-line segment may trigger only its declared sources. The empty/default layout remains
  byte-compatible and existing per-segment fail-open behavior remains local to that segment.
- Every member retains a marked regression that fails on its merged-`main` base. Proxy runtime changes run targeted
  Docker integration; CLI members extend stream/JSON contract tests where applicable.
- O002 does not serialize `proxy stop`'s shared-port decision with process signaling; locking parity is separate
  concurrency work that requires its own reproduction and admission before implementation.

## Closeout

All seven members shipped independently with marked regressions and the verification required by each member's scope,
including targeted Docker coverage where applicable. The review ledger, member cards, normative design, operator
guidance, and change log record the coordinated retention, scriptability, lifecycle-truth, metadata-relay, and
status-line source contracts. Later Wave 5 MEDIUM correctness rows remain outside this closed epic and return to the
parent maintenance epic for a separate admission review.
