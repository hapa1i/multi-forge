# Restore proxy request semantics checklist

Current focus: closed after merge in PR #170 (`acae1b9e`) without activating the next member.

## Activation and prior-member closeout

- [x] Merge D029/O025 independently in PR #168 (`9b18edc3`).
- [x] Record D029/O025 and PR #169 follow-up closeout on `main` at `7f705aad`.
- [x] Start `agent/restore-proxy-request-semantics` from that merged-main cursor.
- [x] Move only this member to `doing/`, create this checklist, and repoint inbound board links.
- [x] Resolve D030's authority ambiguity: undocumented tier-hyperparameter direct env reads are not the generic
  config/env layer; `_MODEL` tier inference stays parked under O051, and credential/connection env precedence is out of
  scope.

## Fail-first reproduction

- [x] Prove tier-specific hyperparameter environment variables override proxy-owned instance settings.
- [x] Prove an authentication retry rebuilds the client without the already resolved tier.
- [x] Prove force-enabling thinking retains incompatible `temperature`, `top_p`, and `top_k` request fields.
- [x] Prove Anthropic `tool_choice:any` translates to optional OpenAI `auto` rather than required tool use (the final
  regression artifact collects `6 failed, 3 passed` on `7f705aad`; D030 is parametrized for both providers, and the
  configured-but-satisfied reasoning-floor control contributes the third pass).
- [x] Follow O035 beyond the cited converter and retain downstream fail-first seams proving that the core adapter and
  GPT Responses client both discarded the translated choice; the adapter seam is included in the final-file count.
- [x] Retain controls for request-explicit sampling without a reasoning mutation, `auto`/named/`none` tool choice,
  credential env resolution, and same-tier client-cache identity.

## Implementation

- [x] Remove undocumented tier-specific hyperparameter environment precedence without changing `_MODEL` fallback tier
  inference.
- [x] Forward `resolved_tier` through authentication invalidation/retry so cache and hyperparameters retain one shape.
- [x] Remove incompatible sampling fields only when the proxy force-enables or raises thinking, and record key names
  only in mutation metadata.
- [x] Translate Anthropic `any` to OpenAI `required`, carry it through Chat Completions and GPT Responses clients, and
  preserve other tool-choice mappings.
- [x] Synchronize normative proxy precedence/request-shape docs and end-user behavior.

## Verification and closeout

- [x] Run focused client-factory, server, intercept, converter, adapter, and GPT Responses tests (`204 passed`).
- [x] Run translated-proxy Docker integration coverage for request conversion (`4 passed`) and the focused auth-retry
  seam regression.
- [x] Run full unit (`9001 passed, 1 skipped, 122 deselected`) and marked regression (`773 passed`) gates.
- [x] Run final pre-commit and board link/lane/size/diff checks (289 files, 713 relative links, zero missing/stale
  targets, 5 `done` / 1 `doing` / 6 `todo`, and 22,273 change-log tokens).
- [x] Open independent draft PR #170 without activating the next Wave 6 member.
- [x] Review and merge PR #170 (`acae1b9e`) before activating another Wave 6 member.
