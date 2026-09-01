# Walkthrough Journey Map

This map keeps the walkthrough educational. A human seam exists only where a person must operate or observe a live
runtime; automated owners carry exhaustive behavior. `default` means always selected. Optional rows are selected only by
their named flag. QA evidence lanes are deliberately not used here.

| Step | User question                             | Human seam                      | Automated owner                                   | Selection / prerequisite               | Boundary                            |
| ---- | ----------------------------------------- | ------------------------------- | ------------------------------------------------- | -------------------------------------- | ----------------------------------- |
| 0.1  | Will my real extensions stay untouched?   | None                            | `test_walkthrough_protected_paths.py`             | default                                | Digest facts, never source bytes    |
| 0.2  | Is this really the sandbox?               | None                            | `test_bug_o036_walkthrough_sandbox_provenance.py` | default                                | Canonical marked root only          |
| 0.3  | Are helpers and the Claude shim present?  | None                            | wheel + Claude-shim regressions                   | default                                | Installed package, not checkout     |
| 1.1  | How do I enter the sandbox?               | One Terminal checkpoint         | sandbox provenance regression                     | default                                | Bare `forge` only after this proof  |
| 2.1  | Which Forge install answers?              | None                            | extension-doctor unit/integration                 | default                                | Launcher and dispatcher facts       |
| 2.2  | Where do runtime hooks belong?            | None                            | installer runtime-scope integration               | default                                | Sandboxed user scope                |
| 2.3  | Where do project assets belong?           | None                            | installer local-scope integration                 | default                                | Marked walkthrough project          |
| 3.1  | Are both installs healthy?                | None                            | extension-status schema tests                     | default / 2.2, 2.3                     | Summary, not package inventory      |
| 3.2  | What does each scope own?                 | None                            | installer ownership tests                         | default / 2.2, 2.3                     | Hooks user; status line local       |
| 3.3  | Is ownership tracked?                     | None                            | installation-registry tests                       | default / 2.2, 2.3                     | Scope/count facts only              |
| 4.1  | Did setup touch my real system?           | None                            | `test_walkthrough_protected_paths.py`             | default / 0.1                          | Labels only on mismatch             |
| 5.1  | How is the CLI organized?                 | None                            | CLI help/content tests                            | default                                | No exhaustive command count         |
| 5.2  | What makes a session managed?             | None                            | session CLI/integration                           | default                                | Bare launchers are sessionless      |
| 6.1  | Does proxy health prove upstream access?  | None                            | proxy smoke-test integration                      | default                                | Display-only; no provider call      |
| 6.3  | How do I pin a direct model?              | None                            | session-routing integration                       | default                                | No launch or completion             |
| 6.4  | What exists before launch?                | None                            | `test_session_model.py`                           | default / 6.3                          | Intent present, commit absent       |
| 7.1  | How do I launch the managed parent?       | Live Claude launch/status       | session lifecycle integration                     | default / 6.4                          | No prompt yet                       |
| 7.3  | How do I know launch really happened?     | None                            | hook and routing integration                      | default / 7.1                          | Hook evidence, not UUID presence    |
| 8.1  | Which commands bypass the model?          | Live direct-command observation | direct-command integration                        | default / 7.1                          | Zero completions                    |
| 9.1  | How is policy attached?                   | None                            | policy CLI/session tests                          | default / 7.1                          | Named managed-session intent        |
| 9.2  | What does policy intent feel like?        | One prompted Claude turn        | policy hook integration                           | default / 9.1                          | Paid operations: 1                  |
| 10.1 | How do I close cleanly?                   | Live `/exit`                    | artifact-hook integration                         | default                                | Lets lifecycle hooks finish         |
| 10.2 | Where is transcript evidence?             | None                            | artifact-hook integration                         | default / 10.1                         | Stable `session show` surface       |
| 10.4 | How is search rebuilt?                    | None                            | search workflow integration                       | default / 10.2                         | Published artifacts only            |
| 10.5 | Can I find the conversation?              | None                            | search CLI tests                                  | default / 10.4                         | Managed session ownership           |
| 10.7 | What Forge activity is attributable?      | None                            | telemetry activity tests                          | default / 10.2                         | Honest sparse model-call pane       |
| 10.8 | Where do costs come from?                 | None                            | telemetry cost tests                              | default                                | Proxy-scoped spend only             |
| 11.1 | What context will a child receive?        | None                            | transfer integration                              | default / 10.2                         | Structured, no AI curation          |
| 11.2 | Can a fresh child continue?               | One launch and grounded prompt  | resume/transfer integration                       | default / 11.1                         | Paid operations: 1                  |
| 11.3 | What relationship was recorded?           | None                            | session show/resume tests                         | default / 11.2                         | Child evidence separate             |
| 11.4 | Can I remove only the child?              | None                            | session deletion tests                            | default / 11.3                         | Parent survives                     |
| 11.5 | How does memory differ from transfer?     | None                            | memory/passport unit tests                        | default                                | Orientation, no schema exercise     |
| 11.6 | What does incognito promise?              | None                            | session CLI/integration                           | default                                | No-op launcher, trapped cleanup     |
| 12.1 | Is sidecar infrastructure ready?          | None                            | sidecar Docker/auth integration                   | `--sidecar` / Docker + OpenRouter auth | Fixed-id proxy; no default probe    |
| 12.4 | How do I launch a sidecar?                | Live sidecar launch             | sidecar lifecycle integration                     | `--sidecar` / 12.1                     | Packaged template; owned container  |
| 12.5 | What crosses the container boundary?      | None                            | sidecar mount integration                         | `--sidecar` / 12.4                     | One container/mount observation     |
| 12.7 | How does the sidecar stop?                | Live sidecar exit               | sidecar lifecycle integration                     | `--sidecar` / 12.5                     | Cleanup owner: section 13           |
| 12.8 | Is direct Codex ready?                    | None                            | Codex preflight tests                             | `--codex`                              | No enrollment probe                 |
| 12.9 | Can Codex consume parent context?         | None (headless)                 | `test_codex_session_start.py`                     | `--codex` / ready 12.8                 | Initial-message; paid operations: 1 |
| 13.1 | What exactly will be removed?             | One cleanup approval            | interrupted-cleanup regressions                   | always                                 | Reports saved first                 |
| 13.2 | Is runtime cleanup scoped?                | None                            | session/sidecar cleanup tests                     | always / 13.1                          | Named runtime and transfer state    |
| 13.3 | Are installs and runtime residue removed? | None                            | installer/auth-ingress regressions                | always / 13.1                          | Sandbox paths and fixed source only |
| 13.4 | Did cleanup preserve everything else?     | None                            | sandbox and snapshot regressions                  | always / 13.2, 13.3                    | Repeatable final proof              |

Inventory matrices, legacy migration, passport schema internals, supervisor fan-out, and interactive Claude-to-Codex
handoffs remain covered by QA and focused automated suites. They are useful follow-up topics, but they do not answer a
new Day 1 question strongly enough to justify more default checkpoints.
