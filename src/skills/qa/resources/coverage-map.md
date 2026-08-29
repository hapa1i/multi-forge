# Forge v1.0.0 QA Coverage Map

This map separates product-contract ownership from the bounded release journey. The default `/forge:qa` selection runs
`clean-wheel-smoke` and `human-acceptance`; `--extended` additionally runs `extended-exploratory`. `automated-suite`
entries are references only and are never credited as commands executed by a manual run.

| Surface                                | Authoritative automated owner                                                                                                    | Installed release seam                                                                | Lane                                                              |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| Exact wheel and packaged resources     | `tests/integration/docker/test_qa_release_artifact.py`                                                                           | provenance preflight before step 0                                                    | clean-wheel-smoke                                                 |
| Managed Claude lifecycle               | `tests/integration/docker/test_real_claude_hooks.py`                                                                             | 6.10 reuses the paid parent turn from 5.6                                             | clean-wheel-smoke                                                 |
| Managed Codex lifecycle                | `tests/integration/core/test_codex_session_start.py`                                                                             | 5.24 and 6.12                                                                         | clean-wheel-smoke                                                 |
| Codex enrolled hook firing             | `tests/integration/docker/test_real_authority.py`; `tests/integration/docker/test_policy_hooks.py`                               | static registration only in 6.12                                                      | automated-suite                                                   |
| Model-first routing                    | `tests/integration/docker/test_session_routing.py`                                                                               | 5.25 and 9.11                                                                         | clean-wheel-smoke                                                 |
| Artifact authority                     | `tests/integration/docker/test_real_authority.py`                                                                                | 5.25                                                                                  | clean-wheel-smoke                                                 |
| Native adoption                        | `tests/integration/docker/test_adopt_native_conversation.py`                                                                     | 5.26                                                                                  | clean-wheel-smoke                                                 |
| Session repair and degraded visibility | `tests/integration/docker/test_session_lifecycle.py`                                                                             | 5.26                                                                                  | clean-wheel-smoke                                                 |
| Rewind and ancestry                    | `tests/integration/docker/test_rewind_native_contract.py`                                                                        | 10.8                                                                                  | clean-wheel-smoke                                                 |
| Consumer lanes and billing             | `tests/src/cli/test_session_lane.py`; `tests/src/cli/test_policy_supervisor.py`; `tests/src/core/usage/test_billing.py`          | 5.27 proves keyed direct `api`; automated owners cover `unknown` and proxied branches | clean-wheel-smoke plus automated-suite                            |
| Keyless Claude Max billing             | `tests/src/core/usage/test_billing.py`                                                                                           | deliberately absent from keyed QA container                                           | automated-suite                                                   |
| Backend lifecycle                      | `tests/integration/backend/test_backend_cli.py`                                                                                  | 4.27                                                                                  | clean-wheel-smoke                                                 |
| Provider trace                         | `tests/integration/proxy/test_provider_trace_e2e.py`                                                                             | 4.25 and OpenRouter-only 4.28                                                         | clean-wheel-smoke                                                 |
| Policy source modes                    | `tests/integration/cli/test_policy_cli_contract_integration.py`                                                                  | 13.5                                                                                  | clean-wheel-smoke                                                 |
| Transfer strategies                    | `tests/src/session/test_transfer.py`; `tests/src/cli/test_transfer_cli.py`; `tests/integration/docker/test_session_lifecycle.py` | 5.7 and 10.2-10.8                                                                     | clean-wheel-smoke plus human-acceptance plus extended-exploratory |
| Extension lifecycle and preservation   | `tests/integration/docker/test_installer.py`                                                                                     | sections 2 and 18-20, with final review at 19.4                                       | clean-wheel-smoke plus human-acceptance                           |
| Workflow fan-out and portable skills   | `tests/integration/cli/test_workflow_integration.py`; `tests/src/install/test_skill_compiler.py`                                 | 15.5                                                                                  | human-acceptance                                                  |

## Non-blocking checklist ownership

The comments below are machine-checked. Each step excluded from the blocking selection names an existing test owner.

<!-- evidence-owner: 4.6,4.7 | tests/integration/docker/test_real_claude_hooks.py -->

<!-- evidence-owner: 4.17 | tests/src/config/test_loader.py -->

<!-- evidence-owner: 4.26 | tests/integration/proxy/test_anthropic_passthrough_headers_e2e.py -->

<!-- evidence-owner: 5.15 | tests/integration/docker/test_session_lifecycle.py -->

<!-- evidence-owner: 6.3,6.4,6.5,6.6,6.7,6.8,6.9 | tests/integration/docker/test_policy_hooks.py -->

<!-- evidence-owner: 6.11 | tests/integration/hooks/test_worktree_create.py -->

<!-- evidence-owner: 7.10 | tests/src/proxy/test_passthrough.py -->

<!-- evidence-owner: 10.5 | tests/src/session/test_transfer.py -->

<!-- evidence-owner: 13.7 | tests/src/cli/test_policy_supervisor.py -->

<!-- evidence-owner: 14.2,14.3,14.4,14.5,14.6,14.7,14.8,14.9,14.10,14.11,14.12 | tests/integration/cli/test_workflow_integration.py -->

<!-- evidence-owner: 15.3,15.4,15.6,15.8 | tests/src/install/test_skill_compiler.py -->

<!-- evidence-owner: 16.2,16.3,16.4 | tests/integration/docker/test_real_claude_memory.py -->

The planner-to-supervisor-to-executor demonstration (13.7) declares five prompted turns/checks; live Anthropic
passthrough metadata (4.26), the spend-cap warning probe (7.10), and live AI curation (10.5) each declare one request.
They remain exploratory because they are provider-variance-prone and add paid or multi-session work without owning the
underlying contract. They are useful during a focused investigation, but they do not gate the pinned release verdict.
