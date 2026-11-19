# dnspython security update

Branch `fix/dnspython-2.9.2` from `main` at `49bb46cc`. [Card](card.md)

- [x] The revised regression failed against 2.9.0. All 11 wheel dependency floor tests passed after the update.
- [x] Only dnspython changed in the reviewed lock and runtime export. The build constraints matched.
- [x] The built wheel declares `dnspython>=2.9.2`. The clean wheel smoke passed LiteLLM startup, health, and teardown.
- [x] The rebuilt base and sidecar each imported dnspython 2.9.2 and email-validator with networking disabled.
  All 11 selected backend CLI and proxy health integration cases passed.
- [x] The full pre-commit suite passed, including dependency pins and Markdown links.
- [ ] After merge, verify alerts 69 and 70 have closed and record the change.
