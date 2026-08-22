# Whole-Repo Code Review — Multi-Forge (Combined: Fable 5 + Opus 5)

**Review baseline:** `0a03786fc9b333e9890a64bf80436bb09d8606cf` (`main`, recorded 2026-08-03). Findings must be
rechecked if implementation has moved since this commit.

**Scope:** all of `src/` (~114k LOC), config/packaging, skill scripts, and a structural sweep of `tests/` (~177k LOC).

**Method:** two independent whole-repo reviews (`review_fable_5.md`, `review_opus_5.md`), followed by a merge pass.
Every Opus-only claim was revisited; claims that still lacked enough evidence were retained only when explicitly marked
`(unverified)`. Every CRITICAL and HIGH row was source-checked again during the merge. Source inspection confirms that
the cited code has the described shape; it does not by itself constitute a runtime reproduction.

**Inventory:** 158 severity-ranked findings: 1 CRITICAL, 21 HIGH, 100 MEDIUM, and 36 LOW, plus unranked U001. The
original merge contained 144 ranked rows; DG1 admitted U002 as MEDIUM and U003 as LOW on 2026-08-04, and follow-up
reviews admitted D045, D046, D051, and D053--D056 as MEDIUM plus D047--D050 and D052 as LOW from 2026-08-05 through
2026-08-13. Three Opus claims were refuted and five were adjusted during the merge audit. D033 and O020 remain in the
ranked ledger for stable-ID provenance but were terminally rejected by the 2026-08-11 Wave 5 closeout; inventory counts
are historical rows, not live-work counts.

## Review Status and Execution Gate

This document is the master evidence record for a cleanup, bug-fix, refactor, and maintenance round. It is not an
execution checklist. A finding becomes executable only after it has:

1. a stable finding ID;
2. a verification state appropriate to its risk;
3. an expected behavior grounded in a named authority;
4. an observable acceptance criterion and required test tier; and
5. any linked design decision resolved.

Do not implement rows marked `(unverified)` or include them in a deletion sweep. Do not treat source-confirmed dead code
as safe to remove until its compatibility role and tests have been characterized. Convert accepted work into board cards
according to `docs/developer/board_contract.md`; keep independently shippable fixes as member cards when a shared
contract requires an epic.

**Coordination epic:** [`epic_repo_maintenance_round`](done/epic_repo_maintenance_round/card.md). It closed after owning
sequencing and disposition; this report remains the evidence ledger. Waves 1--8 are closed, with their finding counts,
corrections, and PR ranges retained in the admission records below and in the linked done cards. The residual gate on
`bad273ef` admitted 23 verified rows as 19 members under
[`epic_wave8_residual_maintenance`](done/epic_wave8_residual_maintenance/card.md); all later shipped, while D040 remains
a separate unaccepted proposal.

### Finding fields

| Field            | Meaning                                                                                                                                                                                                                         |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ID`             | Stable reference within this review: `D###` for design-conformance findings, `O###` for other code findings, `U###` for design-drift notes numbered outside the original D/O tables; unranked until a decision gate admits them |
| `Sev`            | Triage impact, not execution order                                                                                                                                                                                              |
| `Src`            | Discovery provenance: `F5`, `O5`, independent agreement `F5+O5`, or follow-up review `R`                                                                                                                                        |
| `(unverified)`   | Agent-reported claim not independently confirmed; ineligible for implementation                                                                                                                                                 |
| `(adjusted)`     | Original claim was corrected before inclusion                                                                                                                                                                                   |
| `partial`        | Only the stated subset is supported; scope must be resolved before implementation                                                                                                                                               |
| source-confirmed | The cited implementation shape was inspected; runtime impact may still need reproduction                                                                                                                                        |

### Severity rubric

| Severity | Threshold                                                                                                                             |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| CRITICAL | Silent persistent corruption or loss of a core safety/configuration guarantee, with broad impact or no safe routine workaround        |
| HIGH     | Concrete wrong behavior that can lose state, produce false success, violate a policy/safety boundary, or break a common critical path |
| MED      | Bounded correctness, reliability, performance, or maintainability defect with a practical workaround or narrower trigger              |
| LOW      | Minor correctness, hygiene, consistency, documentation, or cleanup issue with limited operational impact                              |

Severity remains provisional until the finding has an impact statement and reproduction. In particular, a CRITICAL label
asserts product impact, not just surprising code shape.

This revision reclassifies D010 and O005 from HIGH to MED under the rubric: both are bounded CLI inconsistencies with
routine workarounds. Their behavior descriptions are unchanged.

## Merge Audit — Opus-Only Claims

The original merge pass estimated that roughly 48 of 60 Opus-only claims were confirmed. Treat that figure as merge
provenance, not as the ranked inventory: rows and stable IDs are the authoritative count, and explicit `(unverified)`
markers control execution eligibility.

**Refuted (excluded from tables):**

1. *"`lane clear --consumer supervisor` leaves the sticky T7 degrade overlay"* — documented-intentional behavior.
   design_runtime.md §G states explicitly: "supervisor remove and a re-pin clear it; session lane clear does not (the
   frozen binding still dispatches codex)". A doc-visibility complaint at most, not a bug.
2. *"`stream_relay`'s `on_end` after two `__aexit__`s; a teardown raise skips cost/metrics/trace"* — `on_end` is invoked
   inside `finally:` (`proxy/stream_relay.py:91`; module docstring: "invoked exactly once in the relay's `finally` (even
   on early client disconnect)"). A teardown raise cannot skip a `finally`; accounting still runs. (The client-leak
   sub-claim on an `__aexit__` raise may hold, but the load-bearing accounting claim is wrong.)
3. *"`collect_shadow_entries` is guaranteed to return `[]`"* — refuted: live callers exist (`cli/memory.py:606`, invoked
   at `:621`, `:691`) and entries flow through the shadow-curation surface. The real residue is far smaller: the
   `session_filter` parameter is dead (every caller passes `None`) — carried as LOW below.

**Adjusted (carried with corrections):**

1. `server.py:1812` "raw tool-result error at WARNING" — the code truncates to 100 chars (`str(error_content)[:100]`).
   Carried as LOW: a content-bearing snippet at default verbosity, not unbounded.
2. `cli/info.py:97` "bare except swallows tracking corruption, exit 0" — they are `except Exception:` version probes
   (`:61`, `:80`, `:91`) degrading to `"unknown"`. Carried as LOW: silent best-effort degrade without the warning/debug
   log coding_standards §5 mandates.
3. `--by-verb` "dead flag" — the parameter value is indeed never read, but the flag exists to document the default view.
   Carried as LOW simplification; real defect is `--by-model --by-verb` silently preferring by-model.
4. `WorkflowConfig` non-strict deserialization cited at `policy/deterministic/registry.py:115` — that file validates
   strictly (`:85-87` raise `ValueError` on bad types) and `tagger_prompt` lives in
   `policy/workflow/{config,policy}.py`. Carried as (unverified) with corrected likely location.
5. Fork/resume raw-intent inheritance vs memory-effective — memory side confirmed (`memory_inheritance.py:59` uses
   `compute_effective_intent`), intent fields copied raw (`manager.py:96`), **but** at least one derivation path also
   deep-copies `overrides` (`manager.py:1723`), so the dropped-override scope may be narrower than claimed. Carried as
   partial.

## Design Mapping

- `session/`, `cli/session_*` → design.md §3.2–3.5; session design §3.3, §3.8–3.9, §H (transactions, manifest schema,
  field ownership, transfer/rewind)
- `proxy/`, `backend/`, `config/` → design.md §3.4; runtime design §3.6–3.7 and §7.x; runtime, installation, and
  telemetry design §A (wire shapes, intercept, cost, telemetry planes)
- `cli/` + `cli/hooks/` → cli_reference.md; cli_style_guidelines.md; session design §3.10 and design.md §3.11–3.12
  (hooks, `%` commands, command-core)
- `policy/`, `review/` → design_workflows.md §1–4 (fail-open mandate, citations, cascade, shadow, runners)
- `core/` → design.md §3.12 and §E; telemetry design §3.14/§A.13; session design §B; runtime design §G (state,
  workqueue, telemetry, llm, lanes)
- `install/`, `sidecar/`, `search/`, skills → installation design §5.1/§C/§D; runtime design §7
- `cli/status_line.py`, `statusline/` → telemetry design §A.8 (segment registry, lazy `RenderContext`)

Citation shorthand in the finding tables is fixed as follows: bare `§N` means `docs/design.md`; `workflows` means
`docs/design_workflows.md`; historical `appendix §X` citations route by the section map above (A by subject, B/H/I/J/M
to session design, C/D to installation design, E to core design, F to workflow design, and G/L to runtime design);
`cli_reference` means `docs/cli_reference.md`; `coding_standards` means `docs/developer/coding_standards.md`; and
`impl_notes` means `docs/board/impl_notes.md`. Board cards must expand these to full paths so moved excerpts remain
attributable.

## Conformance Summary

**Partial — strong core, drifting edges.** The hard invariants both reviews probed directly all held: session
creation/deletion transactions, ops-layer purity, fan-out lifecycle, strict config-block coercion (`PROXY_BLOCK_FIELDS`
with exact-set-equality tests), `_SAFE_KEYS` redaction, the `messages` mutation tripwire, cap bootstrap, lane freeze
guards, transcript-parse single-sourcing. Violations cluster in four shapes both reviews converged on independently:
**twins that drifted** (enable/disable, terminal/`%`, Claude/Codex, fork/resume, `list_sessions`/`get_session`, the two
passthrough transports, three verdict parsers), **guards narrower than the effect they protect** (exact-key immutability
checks, sidecar-gated cleanup, process-global latches), **filters applied to one plane of a two-plane join**
(`exclude_interactive`, pane totals, prune budgets), and **older pre-ops CLI code** predating the exit-code/output
contracts.

## Decision Gates

The four gates were approved on 2026-08-04. Their completed cards hold the target contracts; accepted implementation
members are linked from the coordination epic. Normative design documents continue to describe shipped behavior and move
with the corresponding implementation.

| Gate                                                                                     | Findings                   | Approved resolution                                                                                                                                                                   |
| ---------------------------------------------------------------------------------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [DG1 — Stop verification contract](done/stop_verification_contract/card.md)              | D006, U002–U003            | Fixed `completion_promise`/`test_suite` schema; test suite is the named latency exception; arbitrary commands are unsupported; unknown values become visible fail-open configuration. |
| [DG2 — missing-worktree authority](done/missing_worktree_authority/card.md)              | D009                       | Manifest owns durable reservation, index owns discovery, and worktree presence owns launchability; surviving sessions become degraded rather than invisible.                          |
| [DG3 — downstream retention ownership](done/downstream_retention_ownership/card.md)      | D015                       | One global downstream policy and pruner; explicit global config wins, agreeing legacy values bridge, and conflict disables pruning safely.                                            |
| [DG4 — compatibility surface for deletion](done/deletion_compatibility_contract/card.md) | O047–O052, O092–O093, O096 | Evidence rubric adopted; admitted work is split under Wave 7; O093 mapping is retained after characterization, and unverified candidates remain excluded.                             |

`D009` and `D015` are closed by their shipped implementation members. DG1 selected the remedy for D006; the
implementation outcome below records its completed code and regression work.

## Design Status and Post-Review Admissions

This section preserves the merge audit's design-status notes. Deferred items remain design status rather than defects;
the later DG1 decision promoted U002/U003 into the ranked inventory without renumbering the original 144-row table:

- `ModelHyperparameters.strict` / `handle_unsupported_param` defined but unwired (appendix §E.7 says so itself). (F5)
- Workspace activity aggregation / `forge workspace status` (blocked on root-scoped telemetry identity). (F5)
- Streaming/translated-path full-body audit **response** capture (§A.12 marks deferred). (F5)

Documented drift cross-references the ranked inventory where one exists:

- **D028 — `--depth all`:** design.md §3.9 documents it, but the CLI `type=int` rejects it.
- **U001 — `confirmed.adoption` has no read surface:** `AdoptionConfirmed` (`source_runtime`, `adopted_at`,
  `model_basis`…) is written by the adopt op but appears in neither `session show` JSON nor human view; §3.5 justifies
  `model_basis` precisely so provenance stays answerable. (O5, verified: no `adoption` reference in `session_manage.py`)
- **U002 — `custom_command` verification is documented but unsupported:** `docs/design_workflows.md` §1.3 lists
  `custom_command` and describes it as “Run any command,” but `VerificationConfig` has no command field and documents
  only `completion_promise | test_suite`. The Stop hook implements those two branches and fixes `test_suite` to
  `["uv", "run", "pytest"]` with no user-configurable command. Because `VerificationConfig.type` is a plain `str`, a
  stored `custom_command` value reaches the unknown-type branch and silently allows Stop with `(True, None)` rather than
  rejecting the manifest or running a command. (`session/models.py:239`; `cli/hooks/verification.py:43-47,126-132`)
  **Resolved decision:** MEDIUM; remove the documentation promise and implement visible fail-open validation in
  [`align_stop_verification_contract`](done/align_stop_verification_contract/card.md).
- **U003 — `on_incomplete: re_inject` is documented but unsupported:** the same workflow example names `re_inject` as
  the primary value, while `VerificationConfig` defines `block | warn | allow`. The hook handles `warn` and `allow`
  explicitly, then treats every other value as `block`, so the documented value works only by falling through the
  unknown-value path. (`design_workflows.md:296`; `session/models.py:230-244`; `cli/hooks/verification.py:123,179,193`)
  **Resolved decision:** LOW; document `block` and implement strict authoring plus legacy diagnostics in
  [`align_stop_verification_contract`](done/align_stop_verification_contract/card.md).
- **O092 subset — `IndexState.needs_reindex`:** before order-20 activation it had zero callers, so the index
  re-extracted and rewrote on every Stop even when the existing state fingerprint (`mtime` plus size) was unchanged. The
  bounded member wires that guard without treating it as byte identity; unreadable bookkeeping bypasses the optimization
  rather than gating search writes, and explicit full rebuild replaces the state in one locked write.
- **D029 — `tool_prefixes_to_ignore`:** reachable only in a `ProxyConfig` shape that no proxy file can produce.

`U001` still needs severity, acceptance criteria, and a board-card decision. U002 and U003 are now admitted into the
ranked inventory through the approved DG1 record rather than silently changing the original merge audit.

## Strengths (preserve these)

- **The transactional session core is exemplary** — row-first creation with in-lock compensation, fact-derived delete
  declines, fail-closed binding scans; verified against design.md §3.2 by both reviews independently.
- **`core/ops` is genuinely UI-free** (§3.12 holds everywhere), and the review fan-out honors every lifecycle invariant
  (five-child cap, `killpg`, input-order results, exit-0 error envelopes).
- **The guard registries work where they reach:** `PROXY_BLOCK_FIELDS` drives all four wiring sites with an
  exact-set-equality test; `_SAFE_KEYS` redaction and the `messages` SHA256 tripwire are intact; every confirmed
  silent-drop lives in a field *just outside* a registry's reach — the pattern, not the mechanism, is the gap.
- **Fail-open/fail-closed contracts are consciously differentiated** per consumer and held up under adversarial reading
  (the verdict-parser family is the exception, now catalogued above).
- **Hygiene invariants verified at scale:** zero `if TYPE_CHECKING:` blocks and zero stale `__all__` entries across 333
  modules (AST-verified); transcript parsing single-sourced in `core/transcript.py`; cost accounting never fabricates —
  `null` means unavailable, provenance stamped at every emitter.
- **Test discipline is visibly high:** ~9,400 tests, regression files per bug, characterization tests before refactors —
  and `server.py`'s three provider paths kept visibly parallel, which is exactly what makes omitted-spread bugs
  detectable by eye.

## Recurring Patterns (both reviews converged on these independently)

- **A twin that drifted.** `enable`/`disable`, terminal/`%`, Claude/Codex ops, fork/resume checks,
  `list_sessions`/`get_session` predicates, two passthrough transports, three verdict parsers, audit/trace retention.
  The unintentional divergences share a tell: no drift guard pins them equal, while impl_notes documents the
  *intentional* ones precisely so the rest stand out.
- **A guard narrower than the effect it protects.** Exact-key immutability vs parent-object writes; `use_sidecar`-gated
  cleanup for a non-sidecar leak; a process-global latch flipped by a generic regex; `[:100]`-style mitigations present
  at one site and absent at its siblings. When an effect is sticky or destructive, the predicate must be at least as
  specific as the effect.
- **A filter applied to one plane of a two-plane join.** `exclude_interactive` on events but not root-cost; pane
  subtotals overwriting joined totals; two pruners sharing one directory. Once data is assembled from two sources, every
  filter must apply at every source and totals must be functions of the joined set.
- **Contracts enforced per-site instead of at a chokepoint.** Strict-read guards covering `intent` but not `confirmed`;
  fresh-only checks covering five flags but not `--strategy`; header stripping only on the proven path; four editor
  flows re-rolling the same quoting bug. Each new site re-rolls the dice.

## Finding and execution ledgers

- [Design-conformance findings](reviews/whole_repo_design_findings.md)
- [Code and maintenance findings](reviews/whole_repo_maintenance_findings.md)
- [Backlog conversion and execution sequencing](reviews/whole_repo_execution.md)
