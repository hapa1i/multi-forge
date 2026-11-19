# dnspython security update

Branch `fix/dnspython-2.9.2` from `main` at `49bb46cc`. [Card](card.md)

[PR #301](https://github.com/hapa1i/multi-forge/pull/301) merged as `88630683` on 2026-11-19. Its tree matches the
tested head `f8156903`. All seven GitHub checks passed, including the Python 3.11 and 3.13 suites.

- [x] The revised regression failed against 2.9.0. All 11 wheel dependency floor tests passed after the update.
- [x] Only dnspython changed in the reviewed lock and runtime export. The build constraints matched.
- [x] The built wheel declares `dnspython>=2.9.2`. The clean wheel smoke passed LiteLLM startup, health, and teardown.
- [x] The rebuilt base and sidecar each imported dnspython 2.9.2 and email-validator with networking disabled. All 11
  selected backend CLI and proxy health integration cases passed.
- [x] The full pre-commit suite passed, including dependency pins and Markdown links.
- [x] GitHub marked Dependabot alerts [69](https://github.com/hapa1i/multi-forge/security/dependabot/69) and
  [70](https://github.com/hapa1i/multi-forge/security/dependabot/70) fixed on 2026-11-19 after the merge.
