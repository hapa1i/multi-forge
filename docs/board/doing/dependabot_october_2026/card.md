# Patch the October dependency alerts

**Status**: Doing, 2026-10-22. Owner requested one PR for all open
[Dependabot alerts](https://github.com/hapa1i/multi-forge/security/dependabot). Branch: `codex/dependabot-october-2026`,
based on `9e42e15d`.

## Scope

The captured inventory contains 27 alerts in `uv.lock`: one critical, 12 high, 13 medium and one low, covering six
packages. A complete lock audit found six additional advisories: one in certifi and five newer virtualenv issues.
[The alert inventory](evidence/alerts.json) and [additional advisories](evidence/additional-advisories.json) preserve
all 33 advisory identities; [verification](evidence/verification.md) records dependency paths and validation.

| Package    | Alerts               | Required floor | Ownership                  |
| ---------- | -------------------- | -------------- | -------------------------- |
| PyJWT      | 14                   | 2.15.0         | Runtime, packaged floor    |
| aiohttp    | 3                    | 3.14.4         | Runtime, packaged floor    |
| multidict  | 1                    | 6.9.1          | Runtime, packaged floor    |
| oauthlib   | 2                    | 4.0.0          | Runtime, packaged floor    |
| urllib3    | 3                    | 2.8.0          | Runtime, packaged floor    |
| virtualenv | 4 + 5 audit findings | 21.14.12       | Development, uv constraint |
| certifi    | 1 audit finding      | 2026.10.19     | Runtime, packaged floor    |

Runtime floors must survive a wheel installation outside `uv.lock`. Preserve the existing LiteLLM pin and
FastAPI/Starlette compatibility bounds. OAuthlib's major upgrade needs a local client compatibility check; the removed
server-side JSONP feature is not used by Forge's SSO dependency.

Virtualenv 21.14.9 covers the additional launcher advisories; 21.14.12 also seeds pip 26.2.2 with patched certifi.
Certifi 2026.10.19 removes compromised trust roots while restoring unaffected roots removed in the previous release.

## Acceptance

- Every captured alert's affected range excludes the resolved version; inspect incomplete advisory metadata against
  upstream source rather than dismissing alerts.
- Distribution metadata enforces all six affected runtime floors; virtualenv remains development-only.
- Lock changes are limited to the affected packages and required transitive updates.
- Unit, regression, applicable Docker integration, pre-commit, build and clean-wheel runtime checks pass without paid
  provider calls.
- Open one reviewable PR with exact validation and limitations. Alerts remain open on the default branch until GitHub
  processes the merged dependency graph; opening a PR is not alert closure.

This is dependency maintenance with no new configuration ownership or CLI behavior. Existing design and end-user
contracts remain applicable. The separate unpublished `AGENTS.md` guidance commit on local `main` is outside this PR.
