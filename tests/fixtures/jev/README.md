# Jev response fixtures

These JSON responses were captured from OpenRouter Decisions with synthetic state and `provider.zdr: true` on
2026-10-14. The provider was TypeSafe and successful responses resolved to `typesafe/jev-1.13-20260917`.

- `choice.json`, `noul.json`, `score.json`, `malformed.json`: the four-request early capture.
- `rounded-score.json`: measurement request `shared-three-3`; score 0.99 versus displayed weighted mean 0.98.
- `over-limit.json`: the separate 120,234-byte wire control; HTTP 400 with `max_tokens_exceeded`.

The malformed response's account `user_id` is redacted. Provider response IDs remain for provenance. See
[the A1 evidence](../../../docs/board/doing/jev_client_probes/evidence/README.md) for manifests, interruptions and full
captures. Constructed malformed and boundary cases live in tests and are not presented as captured provider behavior.
