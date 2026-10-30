# Effective effort verification

Initial PR head `b6d65fca`, recorded 2026-10-30 on macOS arm64. Tests use local fixtures and synthetic upstream
responses; no paid inference was required. These results concern Claude's session inputs and Forge's outbound request
construction, not provider-side execution.

## Native stdin and request probes

[native-probes.json](native-probes.json) retains the relevant stdin fields and newly captured requests at each stage for
Claude Code 2.1.245 (the runtime pin) and 2.1.314 (the latest package on the probe date). Each version was launched in a
PTY with an isolated home, project and settings, no user credentials, empty MCP/tool configuration, and a loopback
Anthropic HTTP/SSE stub. The sequence was startup, a synthetic turn, `/effort low` with confirmation,
`/model claude-sonnet-4-6`, and another synthetic turn.

Both versions supplied `effort.level` at startup. `/effort` and `/model` updated stdin before the next conversation
request. Opus's stdin model ID included `[1m]`; its outbound request omitted that suffix. The request after the two
changes used Sonnet and `low`. Model-selection validation requests omitted effort. The pinned CLI also issued a title
request with `high` effort, illustrating why a launch/tier observation cannot identify the main conversation request.

A second run on each version started Sonnet 4.6 with `max`. Both stdin and outbound requests retained `max` against the
stub. This does **not** establish native clamping or provider acceptance. The direct bar therefore describes the
Claude-reported session level. Missing fields remain covered by unit fixtures, not inferred from these versions.

The JSON contains hashes of the original extracted files. Full local probe transcripts and the temporary harness are
under `/tmp/forge-effective-effort-20261030/`; they are diagnostic scratch files and are not retained by this commit.
The acceptance observations themselves are retained in the JSON.

## Integration checks

| Command                                                                                                                           | Result                                     | Observable assertion                                                                                                                                                                       |
| --------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `./scripts/test-integration.sh tests/integration/proxy/test_effort_observation_e2e.py`                                            | 8 passed, 6.42s                            | Real proxy subprocess reports the captured final HTTP body for Argon, OpenRouter, GPT-5 tools, and native passthrough override, each streaming and non-streaming.                          |
| `./scripts/test-integration.sh tests/integration/docker/test_session_routing.py tests/integration/sidecar/test_launch_headers.py` | 4 passed, 31.93s (final helper extraction) | Host/resume launch header matches the confirmed routing commitment; direct launch omits it. Actual sidecar Docker launcher preserves multiline launch/effort headers and starts its proxy. |

The integration runner warned that `GEMINI_API_KEY` was absent. These selected tests use local upstream fixtures and
passed without skips. Local full logs are `proxy-integration-final.log` and `launch-integration-final.log` in the
scratch directory above.

## Non-passing attempts and corrections

- The first proxy integration fixture used an uncatalogued synthetic GPT-5 name and failed before testing the intended
  tools behavior. Using the catalogued legacy GPT-5 model exercised the adapter's actual stripping path; all eight cases
  then passed.
- Initial native harness attempts missed onboarding configuration, suppressed status-line execution with
  `disableAllHooks`, or sent `/model` while the effort confirmation was pending. Correcting the isolated harness
  produced the four retained runs; these were harness failures, not product failures.
- The first aggregate unit run had 11,412 passes and two repository-state failures: cached document token hashes were
  stale, and the moved card linked an unstaged checklist. The final checks refresh the cache and stage the new card
  files before auditing candidate Git state.
- The first full pre-commit run normalized imports and identified an un-narrowed test value plus the lifecycle module's
  line ceiling. The test now validates the captured launch ID's type; shared hint state lives in the hint module.

Aggregate results and independent review are recorded in [the checklist](../checklist.md).

[Owner review corrections](review-revisions.md) describe the subsequent fixes and their verification.
