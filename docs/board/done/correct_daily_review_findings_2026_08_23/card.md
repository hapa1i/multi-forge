# Correct Daily Review Findings 2026-08-23

**Lane**: `done/`

**Delivery**: Shipped via [PR #243](https://github.com/hapa1i/multi-forge/pull/243) (merge `79342e99`, 2026-08-23) and
closed to `done/` on 2026-08-23.

## Goal

Correct the eight current-main defects verified against `0bc42799..2266534f`: two session data-loss boundaries, two
route-provenance defects, config and active-state recovery failures, stale living design references, and Markdown
candidate-state validation.

## Scope

- Retain created Codex sessions, worktrees, and transfer snapshots after route projection reaches the child boundary.
- Serialize the final relocated-transcript ownership decision and unlink with session publication.
- Record only model pins actually applied to Claude and accept valid empty optional proxy tiers.
- Compare stored skill-invocation state independently of unrelated config validation and reject unrepresentable PIDs at
  active-registry decode.
- Validate Markdown links against the candidate Git tree and repoint living references to their owning design docs.

## Constraints

- Preserve rollback for failures before successful route projection and preserve one-shot Codex hook delivery.
- Preserve conservative transcript retention on cached positive ownership and the index-to-manifest lock order.
- Preserve route-journal and proxy-identity schemas; correct values and parser acceptance only.
- Keep strict active-state reads non-mutating and repairing reads self-healing.
- Do not rewrite terminal board history or invent absent Claude skill mirrors.

## Acceptance

1. Post-projection Codex failures retain completed child work; pre-projection failures still compensate created state.
2. A sibling cannot publish between the final transcript-owner scan and unlink.
3. Claude route payloads distinguish requested from actually selected models, including Anthropic passthrough.
4. A server response with known empty optional tiers remains authoritative and exposes only usable mappings.
5. Config sync guidance and huge-PID recovery follow their existing user-facing contracts.
6. Markdown validation rejects targets absent from the candidate Git tree and audits tracked plus supplied sources.
7. Living §3.9, §3.14, and §7 references point to the session, telemetry, and runtime documents.
