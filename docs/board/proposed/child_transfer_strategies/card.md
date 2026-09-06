# child_transfer_strategies -- fold selected child evidence into a single-agent handoff

**Epic**: [epic_native_multiagent](../epic_native_multiagent/card.md) (M5 -- child strategy selection and placement).

**Lane**: `proposed/`. Depends on M2, M3a, M4, M6 and M9. Optional batch C sequences M4 then M5 on one branch.
Standalone acceptance covers Claude sources to supported receiving runtimes. Epic gate P2 owns Codex-source parity after
M3b; M9 owns reviewed-artifact lifecycle independently.

## Problem (verified 2026-09-06)

- `assemble_transfer_context` in `src/forge/session/transfer.py` does not assemble a child source inventory or
  incorporate captured child records.
- A known child-parent relationship does not always identify the spawning turn. Claude tool-use joins can establish one;
  team/background sources can lack it.
- `minimal` has pointers rather than call lines, while `ai-curated` renders semantic sections. Universal call-site
  splicing would contradict those parent strategies.
- Current summarization can retain a returned child result in the parent input. Drop/index/curate must select associated
  result blocks before parent rendering, not merely add a second child section afterward.

## Child selection and placement

Add `--children drop|result|curate|index` to supported transfer-start, fresh/fork and regeneration surfaces. One
selection applies independently to every child; this flag does not assign different policies to different children.
Default to `result` for structured/full/ai-curated parents and `index` for minimal parents.

| Parent strategy   | drop                                                                  | result                                                   | curate                                                | index                                   |
| ----------------- | --------------------------------------------------------------------- | -------------------------------------------------------- | ----------------------------------------------------- | --------------------------------------- |
| structured / full | Keep available call description; omit associated child result/content | Observed returned summary after joined call              | Replace child result with M4 digest after joined call | Sources pointer only for child evidence |
| ai-curated        | No child digest; available parent call metadata remains eligible      | Children section with returned summary and parent anchor | Children section with digest and parent anchor        | Sources pointer only for child evidence |
| minimal           | Sources only                                                          | Explicit selection rejected                              | Explicit selection rejected                           | Sources only (default)                  |
| native / rewind   | New child flags rejected before mutation                              | Rejected                                                 | Rejected                                              | Rejected                                |

Resolve associations before parent rendering/curation. Suppress associated tool-result blocks when drop/index/curate
replaces them and avoid duplicate carry under result. Full respects explicit child selection. Parent-authored text that
independently repeats a child's findings remains parent evidence; selection cannot establish semantic erasure.

For structured/full, missing or ambiguous spawning joins produce a separate Children section with known parent source
and an unavailable-join label. Never attach a child to a guessed turn. Nested sources remain attributed to their actual
parent. `--depth N|all` continues to walk Forge-session ancestry, with children under their owning ancestor.

- **Result:** use only an observed returned summary/message within the selected budget. Missing result stays
  unavailable, without implicit paid curation or an inferred conclusion. Report omitted/truncated text; full retains
  over-budget refusal.
- **Curate:** consume captured own-history events through M3a's reader and M4's bounded curation. Running/partial
  sources stay labeled partial; missing sources or unresolved prefix coverage produce explicit unavailable entries.
- **Availability:** the reader supplies plaintext, inherited or unavailable evidence. Do not parse runtime-native
  records here or infer an encrypted task from behavior/model name. M3b later supplies Codex events through this seam.
- **Sources:** every strategy inventories known children, including dropped/running/unjoined/unavailable ones, plus
  root/team/handoff inputs. Include source identity/version, available name/type/depth/description, usage coverage and
  typed anchors. Render M6's shell-quoted source-parent/root command and expose incomplete-search coverage.
- **Schema:** add `children` and `sources`; show/edit/diff use the resulting rendered transfer. Register existing
  imported sections in Sources when M8b is present, without changing import or review lifecycle.

## Review and runtime integration

Pass the completed transfer through [M9's reviewed launch selection](../reviewed_launch_artifact/card.md). M5 verifies
that removing a literal child block from that selected artifact removes those bytes from delivery. It does not create
another review file format, modify frozen snapshots, or take ownership of deferred resume and GC.

This card ships Claude-source behavior to supported destinations, including the existing Codex destination bridge.
Codex-source child prefix, encryption and placement integration belongs to P2 in the
[epic parity table](../epic_native_multiagent/card.md#codex-parity-closeout), after M3b and M5. No unchecked mandatory
Codex rows remain on a closed M5 card.

## Non-goals

No child process recreation, full transcript carry, encrypted-text reconstruction, reviewed-artifact lifecycle,
native-memory import or native-runtime source adapter.

## Acceptance

| Test                        | Fixture and assertion                                                                                                 | Test file                                                                                                                  |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Strategy matrix             | Every supported parent/child combination, defaults and invalid flags; refusal before mutation                         | `tests/src/session/test_transfer.py`, `tests/src/cli/test_session_derivation.py`                                           |
| Joined/unjoined             | Result/digest appears once at a verified call or labeled Children section; drop/index removes associated result input | `tests/src/session/test_transfer.py`                                                                                       |
| Missing/running/unavailable | No silent result-to-curate fallback; normalized coverage and actual task availability remain explicit                 | `tests/src/session/test_transfer.py`                                                                                       |
| Source conformance          | Synthetic normalized inherited/partial events never become invented own-history evidence                              | `tests/src/session/test_transfer.py`                                                                                       |
| Sources and ancestry        | Dropped/unjoined children remain discoverable under their own ancestor; M6 command executes across roots              | `tests/src/session/test_transfer.py`, `tests/integration/cli/test_search_workflow_integration.py`                          |
| Review integration          | Removed child block is absent from selected transfer delivery; M9 baseline and provenance remain correct              | `tests/src/cli/test_session_derivation.py`                                                                                 |
| Runtime delivery            | Claude-source child strategies reach both receiving runtimes through existing/M9 delivery paths                       | Extend `tests/integration/core/test_claude_to_codex_resume.py`, `tests/integration/cli/test_artifact_hooks_integration.py` |

## Design-doc sync

`docs/design_sessions.md` §3.9 and §H (strategy matrix, schema and source coverage); `docs/end-user/transfer.md`,
`docs/end-user/session.md` and `docs/cli_reference.md`. Link M9's review contract and M8b's import contract rather than
redefining either.
