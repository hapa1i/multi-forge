# LiteLLM backup documentation checklist

**Current focus:** Complete. PR #287 shipped on 2026-10-29; board closeout recorded on 2026-10-30.

- [x] Confirm the documented backup is inside the recursively deleted adapter directory.
- [x] Move the documented backup destination outside that directory.
- [x] Verify that the original procedure loses the backup and the corrected procedure preserves the custom bytes through
  adapter deletion and recreation, using an isolated `FORGE_HOME`.
- [x] Refresh the proxy guide's token cache and pass Markdown checks: 22,489 Opus tokens; `make pre-commit-md` passed.
- [x] After merge, record closeout and move the card to done.

The isolated CLI check created a LiteLLM adapter, appended a fixture-only customization, copied the config to each
documented destination, then deleted and recreated the adapter. The original backup disappeared; the corrected backup
retained the exact custom bytes. No backend process or provider inference was started.

## Merged closeout

[PR #287](https://github.com/hapa1i/multi-forge/pull/287) merged as `addf8f7e`, with a tree identical to reviewed head
`26ad87da`. Its [Tests](https://github.com/hapa1i/multi-forge/actions/runs/40882378147) and
[Pre-commit Checks](https://github.com/hapa1i/multi-forge/actions/runs/40882378176) workflows passed. The saved-config
procedure still stores its backup outside the deleted adapter directory on current main; `AGENTS.md` now reinforces that
requirement. Runtime behavior and architecture are unchanged, so no additional design or implementation-memory update is
needed. No inbound board links require repointing.
