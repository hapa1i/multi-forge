# Preserve complete edit identity in supervision

**Epic**: [`epic_policy_supervision_correctness`](../epic_policy_supervision_correctness/card.md).

**Finding**: D005 (HIGH) in [`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Lane**: `done/` -- implemented and verified on `fix/preserve-supervisor-edit-identity`; review and merge are tracked
by the active epic before Wave 1 closes.

## Goal

Ensure the frontier supervisor and tier-1 plan checker judge and cache the complete edit, including removed content, so
two materially different edits cannot alias to one clean allow.

## Evidence

- `ClaudeHookAdapter` retains `old_string` only inside `tool_args`; `new_content` is the replacement and `raw_diff` is
  unset (`src/forge/cli/hooks/policy.py:49-68`).
- `ClaudeHookAdapter` truncates `new_content` to 5,000 characters before constructing `ActionContext`, while preserving
  the full payload only in `tool_args`; `CodexHookAdapter` truncates both added content and update `raw_diff` at the
  same boundary (`src/forge/cli/hooks/policy.py:55-63`; `src/forge/cli/hooks/codex_policy.py:79-101`). A fingerprint
  built from the presentation fields after this step would still alias actions that differ only beyond the prompt limit.
- The frontier prompt uses only `raw_diff or new_content` (`src/forge/policy/semantic/supervisor.py:779-783`), so Claude
  edit deletions and matched context are omitted.
- Frontier and tier-1 cache keys both use only tool name, target path, and `new_content` (`supervisor.py:237-241`;
  `plan_check.py:541-551`) even though tier-1's prompt correctly includes both edit fragments.
- For Codex same-path `Update File` hunks that only delete text, raw diffs differ while `new_content` is `None`; both
  base keys are therefore identical. Whole-file `Delete File` operations are a separate adapter behavior and are not in
  this card.

## Expected Behavior

Per `docs/design_workflows.md` §1.2, prompts include the semantically relevant action and cached results are reused only
for identical edits. Claude fragment edits include matched and replacement text; Codex updates use their raw diff. The
frontier and tier-1 derive cache identity from the same complete, pre-truncation canonical action representation while
retaining their existing plan, route, budget, effort, target-metadata, and throttle dimensions. Prompt truncation
remains an independent bounded-presentation concern and must not reduce cache identity.

## Scope

- Define one runtime-neutral action fingerprint for LLM policy caches.
- Include Claude `old_string` and `new_string`, Codex/on-demand `raw_diff`, and Write content in the relevant normalized
  representation with unambiguous field boundaries.
- Derive or hash that identity at each adapter boundary before the 5,000-character prompt truncation. The adapter may
  retain only the digest rather than duplicate unbounded raw content in the normalized context.
- Use the richer edit representation in the frontier prompt without changing deterministic policies' `new_content`
  semantics.
- Apply the action identity consistently to the semantic supervisor and plan-check cache paths.

## Acceptance Criteria

- Same-path Claude edits with the same replacement but different matched text invoke independent checks.
- Claude frontier prompts contain both matched and replacement fragments within existing prompt bounds.
- Same-path Codex delete-only update hunks with different removed text have distinct cache identities and prompts retain
  the raw diff.
- Actions with identical first 5,000 characters but different tails have distinct cache identities on both Claude and
  Codex paths, while their prompts remain bounded by the existing truncation policy.
- Byte-identical actions still hit clean-allow caches; warnings, failures, and denials remain uncached.
- Plan edits, checker route/model/budget/effort changes, and target metadata continue to invalidate tier-1 cache
  entries.
- Shadow sampling remains deterministic for one canonical action identity and freezes that identity for replay.

## Compatibility and Exclusions

Cache contents are runtime-only and may be invalidated; no durable migration is required. Do not change hook wire
formats, deterministic regex-policy inputs, multi-file ordering, whole-file deletion handling, or cache TTL policy.
Avoid placing raw action content in logs or persisted cache keys; hash the canonical representation. Shadow
configuration reconstruction is outside this member: [D026](../../review_combined.md#design-conformance-findings) and
its omitted `supervisor_effort` remain separately owned and must not be partially fixed here.

## Outcome

Claude and Codex adapters now hash one versioned, canonical action representation before truncating presentation fields.
The semantic supervisor and plan checker use that digest as their shared base cache identity while preserving their
existing plan, route, budget, effort, target-metadata, TTL, and clean-allow-only dimensions. On-demand policy paths use
the same representation, and shadow candidates freeze the digest used by the live decision for deterministic replay.

The frontier prompt now presents both matched and replacement fragments for Claude Edits and retains bounded Codex diff
context. Raw action content is not placed in cache keys; only the SHA-256 digest is persisted. Older runtime-only shadow
records fall back to identity reconstructed from their stored fields, and no durable migration is required. D026's
configuration replay gap and whole-file delete behavior remain unchanged.

## Verification

- Pre-fix D005 regression: `9 failed`, reproducing Claude removed-text aliases, Codex delete-only aliases,
  post-truncation aliases on both runtimes, and the missing Claude frontier fragment.
- Focused identity, adapter, supervisor, plan-check, shadow, and D005 regression suite: `304 passed`.
- `make test-regression`: `641 passed`.
- `make test-unit`: `8,709 passed, 1 skipped, 118 deselected`.
- `./scripts/test-integration.sh tests/integration/docker/test_policy_hooks.py`: `21 passed`.
- `make pre-commit`: passed.
