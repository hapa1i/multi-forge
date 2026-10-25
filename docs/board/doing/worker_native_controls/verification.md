# Worker native-control verification -- 2026-10-25

The pinned native probes ran from a clean `multi_forge-1.1.3-py3-none-any.whl` install under `/opt/forge-qa`, using
Claude Code **2.1.245** and Codex CLI **0.149.1**. The release-QA image recipe installed hash-checked locked
dependencies; the runtime container used `--network none`, fresh homes, synthetic credentials and a deterministic local
upstream. [Machine-readable evidence](evidence/native-worker-controls-20261025.json) records the wheel SHA-256, emitted
arguments, fixed environment values, native tool outcomes and fixture hashes.

## Native admission

| Probe                                                    | Observed result                                                                                                              |
| -------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Claude proposal controls, fork-context Skill             | Skill admitted; one native child transcript created. Denying Agent alone did not close this path.                            |
| Claude review worker, injected Agent or Skill            | Native tool unavailable; no child transcript. Skill also rejected in API-key bare mode.                                      |
| Claude consumer, injected Workflow, SendMessage or Skill | Native tool unavailable after hostile inherited settings, caller overrides and late environment unsets; no child transcript. |
| Codex ordinary root                                      | Tool search discovered `multi_agent_v1.spawn_agent`; the namespaced call returned a native child ID.                         |
| Codex fresh and resumed workers                          | Tool search exposed no native agent tools; the same namespaced spawn call was rejected.                                      |

The Codex positive control matters: an unnamespaced `spawn_agent` call is rejected even by an unrestricted root. The
final fixture exercises the actual discovery/namespace path, rather than treating that rejection as evidence of worker
isolation. The Claude fork-skill positive control likewise establishes that the fixture can create a native child.

Hostile Claude `settings.env` could re-enable auto-memory despite the process environment's disable switch. The final
profile repeats the fixed environment through CLI `--settings`, including when projecting an auth helper. The pinned
probe checks that the auto-memory system prompt is present in the positive control and absent in protected workers. Both
Codex memory overrides are present in emitted requests; that verifies configuration, not historical absence of memory
use. Resumed conversation text is retained. Native controls do not restrict external programs invoked through Bash or
MCP, and this card does not add a managed-root delegation policy. Native Codex fork reviewers retain their existing
hook/plugin/app and auth isolation controls.

## Validation

- Focused unit/regression runs: 457 passed across workers and consumer lanes; 38 passed across invoker retry,
  native-control regressions and subscription auth. Final settings/auth-helper regressions: 13 passed.
- Final `make test-unit`: **11,172 passed, one failed, 120 deselected**. The failure is the exact-content provider-cache
  assertion for the edited `docs/design_workflows.md`; all implementation tests passed. After explicit user approval,
  its provider count was refreshed and the cache-consistency test rerun passed (**1 passed**). Final
  `make test-regression`: **2,167 passed**. An earlier sandboxed focused run hit six process-fixture permission errors;
  the aggregate run with process access resolved those errors.
- `CLAUDE_VERSION=2.1.245 CODEX_VERSION=0.149.1 PYTHON_DOTENV_DISABLED=1 env -u GEMINI_API_KEY ./scripts/test-integration.sh tests/integration/docker/test_worker_native_controls.py tests/integration/core/test_codex_fork_supervisor.py -q -s`:
  **11 passed**, including the clean wheel and native fork-supervisor composition.
- `make build`: wheel and source distribution built with pinned build constraints.
- Live CLI: `forge workflow list-models --available --json`, `forge runtime preflight codex --json`, and blind panels
  with `-m codex` and `-m claude-opus,codex`. Host Claude **2.1.304**, Codex **0.164.0**; all three worker results were
  `WORKER_OK`. The final settings-precedence fix also passed a fresh preflight and mixed panel with both results
  `WORKER_OK`. Codex used ChatGPT subscription auth. Mixed panels used the standard dotenv setup; the preflight reported
  the installed Codex version as beyond its validated 0.161.0 matrix.
- No-dotenv path: Codex panel succeeded. Direct Claude refused before dispatch with an actionable missing
  `ANTHROPIC_API_KEY` diagnostic; the isolated credentials-file fallback also had no Anthropic credential. No auth
  configuration was changed.
- Full `make pre-commit`: **passed**, including type checks, secret scanning, Markdown links and file-size limits. The
  approved workflow count is **27,121 tokens**, above the 25,000 target but below the 30,000 hard limit. Four unchanged
  documents also retain target warnings. The exact-content provider cache is current.

The early fixture runs failed during clean dependency setup and then on a Codex positive-control assumption. The final
passing run uses the existing release-QA install recipe and the discovered native namespace. Those fixture corrections
did not change the production controls.
