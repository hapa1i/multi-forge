# Session Launch Effort and Runtime Passthrough

**Lane**: `done/`

Completed 2026-10-06. [PR #257](https://github.com/hapa1i/multi-forge/pull/257) merged as `845811c2`; its tree matches
verified head `54f320cf`, with all five GitHub checks passing. Design and end-user docs describe the shipped behavior;
the [checklist](checklist.md) records verification and closeout evidence.

## Goal

Let a managed session launch set the runtime's reasoning effort with one Forge flag, and forward explicit runtime flags
after `--`, without weakening Forge-owned session identity, routing, or artifact-authority guarantees.

## Motivation

`forge session start|resume|fork|incognito` launch Claude or Codex with a Forge-built command line. Today the only
escape hatch is the sessionless `forge claude start -- ...` / `forge codex start -- ...`; managed sessions cannot pass
`claude --effort` or `codex -c model_reasoning_effort=...`, or any other runtime flag.

On translated proxy routes, effort set inside Claude never reaches the upstream model. Probing Claude Code 2.1.289 with
a capture stub showed it sends `output_config.effort` for Claude and non-Claude model names alike, but the translated
converter drops `output_config` and derives `adaptive -> medium`, floored by the proxy tier's `reasoning_effort`.

## Decisions

- **Launch-only.** `--effort` and `-- <args>` apply to the launch that names them. Nothing is persisted in session
  intent; bare resume uses the runtime default unless the flag is repeated.
- **Per-runtime vocabulary.** Claude accepts `low|medium|high|xhigh|max` (`claude --effort`). Codex accepts the OpenAI
  reasoning union `none|minimal|low|medium|high|xhigh|max` (`-c model_reasoning_effort="..."`); Codex 0.160 performs no
  local validation, so Forge validates and the server rejects model-unsupported levels.
- **Guarded passthrough.** Flags Forge already manages are rejected with the Forge equivalent named. Advisory-authority
  launches refuse all passthrough because runtime flags can disable the enforcement seam (`claude --bare`,
  `codex --dangerously-bypass-hook-trust`, profiles).
- **Opt-in translated effort.** A launch with `--effort` on a proxy route stamps the Forge-owned
  `X-Forge-Effort-Source: client` header. Only then does the translated proxy treat `output_config.effort` as an
  explicit request: it beats the tier floor and clamps to the mapped model's supported levels. Without the header, the
  existing derivation is unchanged, because Claude always sends a default effort (`medium` for Claude names, `high` for
  unknown names) that would otherwise override every configured tier floor or raise existing sessions' cost.
- `between_tools` and `disabled` thinking keep their existing translated approximation; client effort describes
  between-tool effort there, not up-front reasoning.

## Non-goals

- Persisting effort in session intent or inheriting it across derivation.
- Changing Anthropic-passthrough behavior: it already forwards `output_config`; an override-mode floor still applies.
- Honoring client effort on translated routes without the launch opt-in.

## Acceptance

1. All four Claude launch verbs and Codex start/resume (TUI and headless) apply `--effort` and validated passthrough.
2. `forge session start -- <args>` never binds runtime arguments to the optional session-name positional.
3. Reserved-flag and advisory refusals happen before any session, child, worktree, or proxy mutation.
4. Route-recovery commands reproduce `--effort` and the passthrough tail.
5. Translated requests honor client effort only with the header; inherited headers are scrubbed from headless children.
