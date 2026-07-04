---
name: refactor-audit
description: Find behavior-preserving refactoring and reorganization opportunities for a repo, module, feature, or path.
---

<!-- Keep in sync with .claude/commands/refactor_audit.md (slash-command original: same body; Codex-specific
frontmatter and invocation wording differ). -->

# Refactor Audit

Use this skill when the user asks for a refactor audit, reorganization audit, behavior-preserving extraction review,
drift-prone duplication review, module-structure audit, or code-shape audit for a repository, module, feature, or path.

Sister skill to `simplicity-audit`. That audit asks whether complexity should exist at all; this one asks whether the
code that *should* exist is shaped right. Its findings are behavior-preserving: moves, extractions, consolidations, and
boundary corrections — never deletions of unjustified structure (that is the sister's charter) and never behavior
changes.

The hand-off rule between the two is remediation shape, and the repo has shipped precedent for both directions:
`docs/board/done/session_op_layer_extraction/card.md` was carved *out* of the accidental-complexity batch because it was
"a behavior-preserving extraction, not a deletion," and that card in turn declares itself "not a deletion (there is no
dead code here) and not an over-abstraction removal." When a finding here turns out to be dead or unjustified code, hand
it to `simplicity-audit`; when a simplicity finding turns out to be justified code in the wrong shape, it belongs here.

This skill shares the sister's epistemic core — evidence-first, calibrated confidence, adversarial verification,
report-not-code — restated compactly below. This file is standalone: everything needed to run the audit is in it.

---

## Core Mindset

**Structure serves change.** The ground truth for "well organized" is not aesthetics or textbook layering — it is what
future changes will touch. Co-change history, duplication that must be hand-synced, and the file count of a typical
feature PR are the real measurements. A refactor that does not change what future PRs touch is churn.

Operating instincts:

- **Mirror in-repo exemplars; do not invent structure.** When one path already has the blessed shape
  (`core/ops/codex_session.py` for the ops split, `core/invoker/_lifecycle.py` for cross-runtime sharing,
  `forge.review.resources` for bundled resources), the finding is "bring the laggard to the exemplar," with a concrete
  mapping table. Novel structure needs far stronger evidence than pattern-completion.
- **Must-stay-identical vs allowed-to-diverge.** The central duplication question: if one copy changed without the
  other, would that be a bug? Yes → drift hazard, hoist it. No → possibly deliberate independence — this repo
  *documents* such cases (the walkthrough/QA state scripts each own their copy "so checklist/state behavior can change
  independently," `testing_guidelines.md`; telemetry responsibilities stay separated by design, `design.md` §3.14 —
  though provider-trace evidence was deliberately *folded onto* downstream records rather than kept as a standalone
  plane, `docs/board/impl_notes.md`). Flagging documented independence as duplication is this audit's signature false
  positive — and so is re-proposing a separation the repo deliberately folded.
- **Count the blast radius before proposing a move.** Tests in this repo patch through string paths — the
  `session_op_layer_extraction` seam carried **255** `patch("forge.cli.session.<name>")` sites across 13 files, which is
  why its shim existed and why its unwind needed a dedicated five-slice card. A symbol move's cost is measured in patch
  sites and importers, not diff lines.
- **Rule of three for new seams.** Two similar call sites are a coincidence; extract on the third, or earlier only when
  the copies are must-stay-identical.
- **Behavior preservation is the charter, not a preference.** Same flags, same writes in the same order, same dispatch
  semantics. Anything else is either a defect (report it as one) or a simplification (hand it to the sister).
- **One seam per card, staged in slices.** The shipped refactor precedent unwinds a single seam sequentially under one
  checklist. Do not propose big-bang reorganizations.

---

## Invocation and Boundaries

Use the user's prompt, including any text after `$refactor-audit` or references to this skill, as the audit request:

- A path or area (for example `src/forge/session`) sets the **scope**. If none is given, infer it from the conversation
  and apply the confirmation rule below.
- A mode flag sets **depth**: `--quick` (Quick Scan), `--focused` (Focused Audit), `--full` (Full Codebase Audit). If
  none is given, infer the mode from the scope and the user's ask, then state the mode you picked.

State the inferred scope and mode before expensive exploration. Ask for confirmation only when no scope was given and
answering would require a full-repository scan, or when two or more plausible scopes would materially change the result.
Otherwise proceed with the smallest reasonable scope and note the assumption.

**This skill produces a report, not code changes.** Do not edit code, open PRs, or start refactoring. The report lands
in the conversation; on explicit request, shape it into a board card at `docs/board/proposed/<slug>/card.md` per
`docs/developer/board_contract.md` — a staged refactor card modeled on `done/session_op_layer_extraction/` is the repo's
proven shape for accepted findings.

**When to stop:** Stop after Phase 4 (the report) unless the user explicitly requests implementation. Stay within the
invoked mode.

**Not a style review.** Naming, formatting, and idiom preferences are not findings. **Not a bug hunt** — though
verification often surfaces defects; report those separately (see Surfaced Defects). **Not a simplicity audit** —
deletion candidates go to the sister.

## Audit Modes

### Quick Scan

A gut check: 2–5 candidate opportunities, mostly Low/Medium confidence, framed as hypotheses ("candidate refactor" or
"question for a focused audit"), with clear caveats about what was not measured. No adversarial verification required.
Do not emit Drift hazard or Misaligned labels on unmeasured evidence.

### Focused Audit

For a named module, package, or seam: structure map for the scoped area, change-pattern evidence for each finding,
adversarial verification of every High-confidence finding, proposals with blast radius and sequencing, open questions.

### Full Codebase Audit

Comprehensive review: structure map across `src/forge/`, exemplar census (which paths follow the blessed patterns and
which lag), adversarial verification of every Drift-hazard and Misaligned candidate, prioritized batched roadmap,
explicit do-not-reorganize findings, refuted candidates with evidence.

**Fan-out contract.** Run one auditor per feature area (roughly the packages under `src/forge/` plus the
skills/extension surface), each given its paths and the authority-doc sections governing them. Additionally run one or
two **cross-cutting sweepers** — duplication and layering do not respect package boundaries, so a per-area fan-out alone
will miss copy pairs that live in different packages (the shipped card's Claude+Codex invoker finding spanned two files
one auditor might not hold together). Each auditor returns findings with classification and evidence attached, not raw
file dumps. Consolidate, dedupe, verify adversarially, then write one report.

---

## Evidence Discipline

A false positive — proposing reorganization of structure that is deliberate, or whose move cost exceeds its benefit —
erodes trust in the whole report. Treat the current organization as innocent until proven guilty, and measure before
judging.

### Step 0: Read the project's own structural decisions first

This repo's authority map:

- `docs/design.md` §3.5 (file ownership), §3.12 (command-core ops), §3.14 (telemetry plane separation) and the other
  design docs (`design_appendix.md`, `design_workflows.md`, `cli_reference.md`) — normative shipped architecture.
- `docs/developer/coding_standards.md` (§1 module structure, §5 internal clean-break rules) and
  `docs/developer/cli_style_guidelines.md` (ops are UI-agnostic; CLI owns rendering).
- `docs/developer/testing_guidelines.md` — test mirroring, monkeypatch/fixture policy, the documented
  intentional-duplication cases.
- `docs/board/impl_notes.md` and board cards in any lane — especially `done/session_op_layer_extraction/` (the refactor
  archetype) and `doing/accidental_complexity_cleanup/` (whose do-not-simplify list marks structure already judged
  Earned or Essential).

A documented organizational decision is Intentional by default; contradicting it requires evidence that its conditions
no longer hold, not that the layout looks unconventional.

### Change-pattern probes (measure, do not eyeball)

```bash
# Size outliers vs the pre-commit-enforced 2.5K-line file cap
rg --files -0 -g '*.py' src/forge | xargs -0 wc -l | sort -rn | head -20

# Layering: core must not know the UI layer
rg -l 'import click|from click|from rich|console\.print' src/forge/core/

# Ops contract (§3.12): no Click, no printing, no hook JSON in command-core
rg -n 'click|console\.print|sys\.exit' src/forge/core/ops/

# Co-change coupling: commits touching BOTH files
comm -12 <(git log --format=%h -- <fileA> | sort) <(git log --format=%h -- <fileB> | sort) | wc -l

# Drift check on a suspected copy pair: are they still identical? has one already drifted?
diff <(gsed -n '<a1>,<a2>p' <fileA>) <(gsed -n '<b1>,<b2>p' <fileB>)

# Blast radius of a symbol move: importers + string-based patch targets
rg -l 'from forge\.<dotted\.path> import|forge\.<dotted\.path>\.' src/ tests/
rg -c 'patch\(["\x27]forge\.<dotted\.path>' tests/
```

Already-happened drift is the strongest evidence a copy pair is hazardous: if `diff` shows the copies have diverged and
one side's change was a fix the other side needed, the hazard is proven, not predicted.

### Confidence

Bounded by what was measured. High confidence requires: the structural decision was checked against the authority map,
co-change or duplication evidence was actually measured, the blast radius was counted, and no in-flight card or branch
already owns the seam. Otherwise Medium or Low, with the unresolved possibility named. When in doubt, downgrade.

---

## Structural Contracts

The repo-specific rules findings are measured against. A violation is a finding; the contract is the target shape.

| Contract                                                                          | Authority                                             | Probe                                            |
| --------------------------------------------------------------------------------- | ----------------------------------------------------- | ------------------------------------------------ |
| Shared CLI/direct-command logic lives in `core/ops/`, UI-agnostic                 | `design.md` §3.12, `cli_style_guidelines.md`          | Click/print/exit greps above                     |
| Files stay under the 2.5K-line cap                                                | pre-commit (see `forge_codex_command_group` closeout) | `wc -l` outliers                                 |
| Tests mirror source 1:1 (`src/forge/x/y.py` → `tests/src/x/test_y.py`)            | `testing_guidelines.md`                               | path comparison over the scoped area             |
| 3+ identical monkeypatches → shared fixture; repeated fakes → module-level double | `testing_guidelines.md`                               | `rg 'monkeypatch\.' tests/src/<area>` clustering |
| Recovery output only via `forge.cli.output` helpers                               | `CLAUDE.md` (test-enforced)                           | already enforced; note violations only           |
| Module internal order: public before private, constants → classes → functions     | `coding_standards.md` §1                              | read the outliers                                |
| Cross-runtime shared logic lives in the runtime seam, not per-runtime copies      | `core/invoker/_lifecycle.py` precedent                | diff the runtime siblings                        |
| Bundled resources over embedded string literals                                   | `forge.review.resources` precedent                    | large string constants in CLI modules            |
| File ownership boundaries (who writes which state)                                | `design.md` §3.5                                      | writers outside their owned files                |

---

## Finding Categories

Every finding names its category; each category has shipped repo precedent.

1. **Drift-prone duplication** — copies that must stay identical by hand. Precedent: the Claude/Codex invoker
   upstream-emission tails (byte-identical, hoisted to `_lifecycle.py`), telemetry literals re-declared outside their
   schema owner, CLI-embedded templates byte-identical to skill resources. Apply the must-stay-identical test first.
2. **Wrong-layer logic** — business logic interleaved with rendering/framework where a designated home exists.
   Precedent: `session_lifecycle.py` interleaving session creation, routing resolution, and manifest writes with Rich
   rendering and `sys.exit`, resolved by mirroring the ops split.
3. **Missing seam** — the same multi-step pattern hand-rolled at 3+ sites. Precedent: a model-override helper applied 5x
   across launch/resume helpers. Rule of three gates this category — and even three copies can be a deliberate seam (see
   Classification: Intentional).
4. **Cohesion mismatch** — one file doing several jobs (cap pressure is the symptom: check current `wc -l` outliers), or
   fragments that always change together (co-change probe is the evidence).
5. **Exemplar divergence** — two implementations of the same role where one follows the blessed pattern and the other
   predates it. The finding is a mapping table from laggard to exemplar, per the archetype card's target-shape table.
6. **Contract misalignment** — a Structural Contracts violation: test-mirror gaps, fixture-policy violations, embedded
   resources, ownership-boundary leaks.

## Classification

- **Drift hazard** — must-stay-identical copies with no documented independence. Highest priority: the liability
  compounds with every edit.
- **Misaligned** — structure violates a contract or measurably fights change patterns. Act, with sequencing.
- **Intentional** — the organization is documented-deliberate or already adjudicated (state-script copies, telemetry
  planes, a shim whose unwind already has its own card, the hand-rolled proxy identity gate the cleanup card's verifier
  judged Earned — "a deliberate seam persisted through refactors," optional to consolidate only if already touching the
  file). Record it in do-not-reorganize so the next audit does not re-flag it.
- **Premature** — real pattern, insufficient evidence to act (rule of three unmet, speculative seam, benefit below
  blast-radius cost). Name the trigger that would ripen it ("extract when a third consumer appears").
- **Uncertain** — cannot tell from code and docs whether the organization is deliberate. Frame as a question.

## Caution Zones

- **Documented intentional duplication and separation** — the state scripts and telemetry separation above. Check
  `testing_guidelines.md` and `design.md` §3.14 before flagging any copy pair or "similar-looking writers."
- **Patch-target blast radius** — moving or renaming symbols breaks string-based `patch(...)` targets silently. Count
  them first; a move with hundreds of patch sites is a staged card with a compatibility plan, never a drive-by. The
  255-site precedent is the calibration point.
- **Load-bearing zones apply to moves too** — wire translation (`converters.py` is Essential; do not split it to satisfy
  the line cap), durable-state read/write seams, money/telemetry correctness paths. Reorganizing code in those zones
  needs a higher evidence bar.
- **Public surfaces** — moving Python symbols is internal clean-break territory (`coding_standards.md` §5: update all
  callers atomically). Moving or renaming CLI commands is a product decision governed by `cli_style_guidelines.md`, out
  of scope here.
- **In-flight work** — check active branches and `doing/` cards for the same files before proposing. The cleanup card
  records this exact practice ("land #6 after that branch merges to avoid rebase churn"). A correct proposal with bad
  sequencing is a bad proposal.

---

## Phase 0: Scope and Evidence Check

State the scope, the audit mode, and the available/unavailable evidence (source, tests, git history, docs, in-flight
branches). Confidence is bounded by what was measured.

**Check prior audits before searching.** Read `docs/board/impl_notes.md`, then locate prior audit and refactor cards
with `rg -il 'refactor|extraction|reorg|simplicity audit|accidental complexity|do-not-simplify' docs/board` and read
their do-not-reorganize, do-not-simplify, and refuted-candidates records. Do not re-flag a previously refuted or
already-carded finding — cite the card and move on.

## Phase 1: Structure Map

Make the current shape measurable before judging it:

- **Size table**: files in scope with LOC, flagging cap-pressure outliers.
- **Layering probes**: run the greps from Change-pattern probes over the scope; record violations.
- **Duplication scan**: candidate copy pairs (within and across packages), each tagged identical / drifted /
  similar-but-independent, with `diff` evidence.
- **Co-change clusters**: file sets that repeatedly change together across recent history; note clusters that span
  module boundaries (splitting evidence) and files that never co-change despite living together (merging evidence is
  weaker — colocation is cheap).
- **Exemplar census**: for each blessed pattern (ops split, runtime seam, bundled resources), which paths follow it and
  which lag.
- **Test-mirror check**: source files whose mirror test file is missing or misplaced.

Rough numbers are fine; the point is that every Phase 3 proposal cites a measurement from this map, not an impression.

## Phase 2: Assessment

For each candidate, ask in order:

1. **Is it documented-deliberate?** (Step 0 — if yes, classify Intentional and stop.)
2. **What is the change-pattern cost today?** Files a typical change touches, hand-sync burden, drift already incurred.
3. **What is the exemplar or contract target shape?** Name it; if no in-repo exemplar exists, the bar rises.
4. **What is the blast radius?** Importers, patch sites, CLI surface, docs. Compare against the benefit honestly.
5. **Is it ripe?** Rule of three, in-flight collisions, whether a cheaper partial move captures most of the value.

## Adversarial Verification

Before a finding enters the report as Drift hazard or Misaligned, try to kill it — every such candidate in a Full audit,
every High-confidence finding in a Focused audit, none in a Quick Scan. The refuter's briefs, in order of how often they
win:

- Find the **documented independence or deliberate decision** the first pass missed (testing guidelines, design docs,
  impl notes, an existing card that already owns the seam).
- Show the **blast radius exceeds the benefit** (patch-site count, importer count, contract surface).
- Show the copies are **allowed to diverge** — similar shape, different owners or lifecycles.
- Show the proposal **cannot be behavior-preserving** as stated (hidden ordering, state writes, dispatch invariants) —
  which either kills it or converts part of it into a Surfaced Defect.

Refuted findings move to do-not-reorganize with the refuting evidence recorded. Partially justified findings downgrade
to Premature or Uncertain — a proposal is written only for survivors. Never refute to hit a quota; on a small or clean
scope, zero refutations is a legitimate outcome.

## Phase 3: Proposals

Model every proposal on `done/session_op_layer_extraction/card.md`. Required content:

01. **Category and classification**, with the measurements that earned them.
02. **What exists now** — anchors (`file:line`), duplication counts, size, interleaving evidence.
03. **Target shape** — the in-repo exemplar being mirrored and a mapping table (new home ← current anchor), like the
    archetype's ops table.
04. **Non-goals / must-not-break** — the invariants to pin with tests *before* moving code (ordering of writes, dispatch
    precedence, rendering staying in the CLI), and the adjacent seams explicitly out of scope.
05. **Blast radius** — counted importers, counted patch sites, affected docs/tests. If the radius justifies a temporary
    re-export shim, it must be carded, named, its dependents counted, and given a scheduled deletion slice — the
    `_sess()` shim followed exactly this arc, ending in its own retirement slice. Never a silent leftover.
06. **What you verified** — step-0 docs read, probes run with results, drift/diff evidence, in-flight-work check.
07. **Adversarial verification** — survived; what the refuter checked and failed to find.
08. **Confidence / Effort / Risk / Sequencing** — including relations to other cards and branches, per the cleanup
    card's branch-awareness notes.
09. **Falsifiable prediction** — the change-cost claim a maintainer can check afterward: "changes to X should touch ~1
    file instead of ~3; confirm on the next three X PRs." A proposal that cannot make one is churn.
10. **Migration plan** — staged slices, each slice atomic per `coding_standards.md` §5 internal rules: all callers
    updated in the same commit, tests moved not skipped, `make pre-commit` and the focused test modules as the gate. The
    only exception is a declared shim slice meeting the conditions in item 5.

## Phase 4: The Report

Adapt depth to scope. Template:

```markdown
# Refactor Audit: [Area]

## Executive Summary

[2–4 sentences: what the area's structure is, where it fights change patterns, the biggest opportunities.]

## Scope and Evidence

**Scope / mode:** [...]
**Evidence measured:** [probes run, history window, in-flight branches checked]
**Evidence unavailable:** [...]
**Prior audits checked:** [cards/impl notes read; previously refuted or carded findings not re-flagged]

## Structure Map

| File / Cluster | LOC | Cap pressure | Co-change cluster | Duplication pair | Contract violations |
|---|---:|---|---|---|---|
| [...] | [N] | [ok / near cap] | [with what] | [identical / drifted / independent] | [which contract] |

**Exemplar census:** [paths following vs lagging each blessed pattern]
**Test-mirror gaps:** [...]

## Findings

### Finding [N]: [Name]

**Category:** [Drift-prone duplication / Wrong-layer logic / Missing seam / Cohesion mismatch / Exemplar divergence / Contract misalignment]
**Classification:** [Drift hazard / Misaligned / Premature / Uncertain]

**What exists now:** [anchors + measurements]
**Target shape:** [exemplar + mapping table]
**Non-goals / must-not-break:** [...]
**Blast radius:** [counted importers, patch sites, docs]
**What you verified:** [...]
**Adversarial verification:** [Survived — what the refuter checked and failed to find]
**Confidence:** [High / Medium / Low] [reason]
**Effort / Risk / Sequencing:** [...]
**Prediction:** [falsifiable change-cost claim]
**Migration plan:** [slices]

## Do-Not-Reorganize

[Intentional organization, with the documenting authority — including refuted candidates with their refuting evidence.
Written for the next audit as much as this one.]

## Surfaced Defects

[Bugs found while verifying behavior-preservation — not refactorings. Each confirmed defect fix needs a regression
test per `testing_guidelines.md`. An empty section is fine.]

## Open Questions

| Question | Area | Why it matters | Evidence checked | Who should answer |
|---|---|---|---|---|

## Recommendations

[Batched: drift hazards first (they compound), then contract violations (they teach the wrong pattern to the next
contributor), then cohesion/navigation wins. Separate act-now from needs-team-input. Note sequencing constraints.]

## Suggested Next Steps

[Per acted-on finding: the invariant-pinning tests to write first, the slice order, and the local check that confirms
the predicted gain.]
```

---

## Style and Tone

Findings are tradeoffs, not blame. Credit what the current structure did, and attribute the change to changed conditions
rather than a verdict on its author. In particular: the person who duplicated code under deadline made a reasonable
local call — the finding is that the repo now has a designated home for it, not that the copy was a mistake.

---

## Final Principle

The goal is not conformance to a diagram. It is code whose shape matches how it actually changes — where the next
feature touches one place, the next fix cannot silently miss a twin copy, and the next contributor finds the blessed
pattern by reading any path that does the same job.

A strong report says both:

> "This seam fights every change that crosses it; here is the staged unwind."

and:

> "This layout looks unconventional but is deliberate and documented; leave it alone."
