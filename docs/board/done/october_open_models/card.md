# Add the October open-model shortlist

**Status**: Done, 2026-10-25. Kimi K3.1 Pro, MiniMax M3.1 Flash, and DeepSeek V4.1 Flash 1017 shipped together.
Execution branch: `codex/october-open-models`, based on `529be2aa`.

**PR**: [#281](https://github.com/hapa1i/multi-forge/pull/281), merged as `30ad379b`. The merged tree matches reviewed
head `d1edbed9`; both CI workflows passed. See the [merged closeout](checklist.md#merged-closeout).

## Scope

Add explicit catalog identities, OpenRouter routes, family-template alternatives, and workflow workers for:

| Forge model                | OpenRouter model                    |
| -------------------------- | ----------------------------------- |
| `kimi-k3.1-pro`            | `moonshotai/kimi-k3.1-pro`          |
| `minimax-m3.1-flash`       | `minimax/minimax-m3.1-flash`        |
| `deepseek-v4.1-flash-1017` | `deepseek/deepseek-v4.1-flash-1017` |

Keep family defaults, the default workflow quorum, prior model identities, and saved proxy snapshots intact. This change
provides hosted OpenRouter support; it does not add self-hosted deployment adapters. Kimi's weights are announced for
November 4; MiniMax's community-licensed and DeepSeek's MIT-licensed weights are already published.

Reported integration failures also require per-test proxy-stub cleanup and a reviewer auth transport fix: supported
Claude versions reject the anonymous settings-file path previously used for inherited helpers.

## Acceptance

- Resolve each exact model and provider alias to the intended upstream slug, including workflow fallback routes.
- Filter unsupported Kimi sampling controls and preserve the new models' supported reasoning efforts.
- Verify streaming tool calls and a subsequent tool-result turn; document the translated reasoning-history limit.
- Preserve ZDR enforcement, reported usage/cost, existing defaults, and user-owned snapshots.
- Run focused integration, unit/regression, pre-commit, and clean-wheel checks; record live-provider limits explicitly.
- Open one PR with validation evidence. Merge and board closeout remain separate.

Provider sources and verification belong in [evidence.md](evidence.md).
