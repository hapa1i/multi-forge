# Repository-Owned Context Limits Checklist

Activation base: `0bc42799` (`main`, 2026-08-22).

## Policy tooling

- [ ] Add root policy, repository checker, pre-commit registration, and tests.
- [ ] Align `count-tokens.py` with the configured Opus-first chain while retaining explicit local mode.
- [ ] Document config precedence, provider disclosure, targets, hard limits, and the historical exception.

## Design migration ledger

Every original level-2 through level-4 section must be assigned below before the appendix is deleted. `Integrated` means
its complete unique contract is represented at the destination; it never means discarded.

| Original section                                                       | Destination              | Disposition |
| ---------------------------------------------------------------------- | ------------------------ | ----------- |
| `design.md` §1-§2                                                      | `design.md`              | Pending     |
| `design.md` §3 prelude, project identity, context model, §3.1-§3.2     | `design.md`              | Pending     |
| `design.md` §3.3, §3.8-§3.10, §3.13                                    | `design_sessions.md`     | Pending     |
| `design.md` §3.4, proxy portions of §3.6, §3.7, §7                     | `design_runtime.md`      | Pending     |
| `design.md` §3.14                                                      | `design_telemetry.md`    | Pending     |
| `design.md` configuration/install portions of §3.6 and §5.1, §5.3-§5.4 | `design_installation.md` | Pending     |
| `design.md` §3.11-§3.12, §4, §5.2, §6                                  | `design.md`              | Pending     |
| Appendix §A.1-§A.5, §A.10                                              | `design_runtime.md`      | Pending     |
| Appendix §A.6-§A.7b                                                    | `design_installation.md` | Pending     |
| Appendix §A.8-§A.9, §A.11-§A.14                                        | `design_telemetry.md`    | Pending     |
| Appendix §B                                                            | `design_sessions.md`     | Pending     |
| Appendix §C-§D                                                         | `design_installation.md` | Pending     |
| Appendix §E, §G                                                        | `design_runtime.md`      | Pending     |
| Appendix §F                                                            | `design_workflows.md`    | Pending     |
| Appendix §H-§J                                                         | `design_sessions.md`     | Pending     |

## Other oversized documents

- [ ] Extract the memory architecture from `design_workflows.md` into `design_memory.md`.
- [ ] Rotate complete changelog entries into dated archives without shortening them.
- [ ] Partition implementation notes by domain behind a compact index.
- [ ] Partition the combined review into overview, finding inventories, and execution ledger without dropping findings.

## Link and fidelity verification

- [ ] Rewrite all appendix and moved-section links, including links in closed cards.
- [ ] Verify all tracked local Markdown paths and fragments resolve and no `design_appendix.md` reference remains.
- [ ] Audit unique code fences, tables, identifiers, normative statements, edge cases, and examples against the
  activation-base sources; mark every migration-ledger row `Moved` or `Integrated`, never `Dropped`.
- [ ] Record authoritative Opus counts for each resulting living/context document.

## Verification and closeout

- [ ] Run focused script/link tests, unit, regression, Markdown pre-commit, full pre-commit, and `git diff --check`.
- [ ] Update the change log, close the card, push the branch, and open the PR.
