# LiteLLM backup documentation checklist

**Current focus:** Review and merge the verified documentation fix.

- [x] Confirm the documented backup is inside the recursively deleted adapter directory.
- [x] Move the documented backup destination outside that directory.
- [x] Verify that the original procedure loses the backup and the corrected procedure preserves the custom bytes through
  adapter deletion and recreation, using an isolated `FORGE_HOME`.
- [x] Refresh the proxy guide's token cache and pass Markdown checks: 22,489 Opus tokens; `make pre-commit-md` passed.
- [ ] After merge, record closeout and move the card to done.

The isolated CLI check created a LiteLLM adapter, appended a fixture-only customization, copied the config to each
documented destination, then deleted and recreated the adapter. The original backup disappeared; the corrected backup
retained the exact custom bytes. No backend process or provider inference was started.
