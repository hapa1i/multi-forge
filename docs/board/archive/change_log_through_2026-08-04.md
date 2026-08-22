# Change Log: Through 2026-08-04

Verbatim archived and previously compacted entries from the project change log.

[Current entries](../change_log.md) ·
[Entries from 2026-08-05 through 2026-08-14](change_log_2026-08-05_to_2026-08-14.md)

---

## Maintenance

- Updated by the memory writer with `strategy=changelog`, and by humans when closing a phase.
- Add compact entries for completed work only. Pending tasks belong in card checklists.
- Follow `docs/developer/board_contract.md` "Change Log Policy": each entry needs Goal, Key changes, and Verification.
- Keep entries short. Do not list every file unless the file list is the point of the work.
- Use newest-first order so active work stays near the top.
- When this file approaches the documentation size limits, compact the oldest entries at the bottom into a dated summary
  that preserves decisions, verification, and deferred items. Archive detailed old entries only if the summary is still
  too large.
- Check size before long sessions or when the file feels slow to scan:

```bash
wc -l docs/board/change_log.md
./scripts/count-tokens.py docs/board/change_log.md
```

## Entries

> Format: `## YYYY-MM-DD`, then `### Phase X.Y: Short Title`, with `**Goal**:`, `**Key changes**:` as bullets, and
> `**Verification**:`. Use newest-first order. See `docs/developer/board_contract.md` "Change Log Policy" for the full
> spec.

## 2026-07-22 -- 2026-08-04 (compacted)

Session transaction safety, runtime-scoped extensions, proxy/config seams, workspace/adoption surfaces, model and
workflow refreshes, and the repository-maintenance decision gate. Detailed history remains in the matching done cards
and PRs; this summary preserves the contracts, verification anchors, compatibility decisions, and deferred items.

- **Maintenance decision and policy boundaries (08-04):** approved the Stop verification, missing-worktree liveness,
  downstream retention, and evidence-based deletion gates; admitted 13 bounded members while keeping shipped design docs
  authoritative until implementation. Semantic supervisor verdicts became exact and observable, malformed confidence
  degrades safely, throttle reuse accepts only clean aligned/1.0 state, and terminal bundle re-enable preserves
  session-owned supervisor configuration. Verification covered 321 focused policy/supervision, 47 hook-adapter, 8,702
  unit (one skip), 632 regression, 21 Docker policy-hook checks, Markdown, links, lanes, and pre-commit.
- **Git-derived workspace worktrees (08-03):** added strict porcelain-z worktree parsing, common-directory identity,
  occupancy joins, and `forge workspace worktrees [--json]` without persisting a second workspace identity; Git
  discovery moved to an acyclic shared leaf. Activity aggregation and `workspace status` remained gated on root-scoped
  telemetry. PR #122 (`a5aee0a9`) passed 99 focused, 8,680 unit (one skip), 38 integration, and pre-commit checks.
- **Proxy ingress and config wiring (08-02):** centralized wire shapes and proxy-block coercion/field registration,
  extracted Anthropic passthrough ingress, and moved `forge info` to its CLI owner. The guards exposed and fixed dropped
  template costs, a missing GPT-5.5 Pro catalog entry, and an unrouted local-LiteLLM fixture. Verification: 8,655 unit,
  12 proxy/session integration, and pre-commit.
- **Session orphan repair (08-02):** added preview-default, root-scoped `forge session repair` with explicit repairable,
  missing-worktree, collision, corrupt, unreadable, and unrepairable outcomes; apply uses hash-verified transactional
  publication and fails closed on raced identity or bindings. PR #120 passed 8,639 unit, 117 component integration, 22
  Docker lifecycle/adoption checks, and pre-commit.
- **Crash-atomic session creation and serialized deletion (08-01--08-02):** made index-row-first `create_session_txn`
  span all five creation sites with in-lock compensation and residue retry; strengthened binding scans, replacement
  ownership, adoption rollback, and force-fork/delete coordination. Terminal deletion now holds index then manifest
  locks and removes the manifest before its row. Review reproduced and fixed seven transaction defects; 9,176
  unit/regression (one skip), 117 component integration, 22 Docker session/adoption checks, focused deletion coverage,
  and pre-commit passed. Pre-existing orphan repair shipped separately the next day.
- **Runtime-scoped extension ownership and disable (07-30--07-31):** schema-v3 `(module, runtime)` attribution now
  drives enable, sync, status, and partial removal while legacy unattributed rows remain non-targetable. Runtime-scoped
  disable uses reversible settings/sidecar unmerge, guarded Codex marker removal, truthful partial reconciliation, and
  recovery when tracking writes fail. A changed `CODEX_HOME` refuses before mutation and names both config paths; older
  already-orphaned blocks remain a manual limitation. Verification peaked at 3,366 focused, 8,581 unit (one skip, 117
  deselected), 551 regression, 21 Docker lifecycle checks, builds, and pre-commit.
- **README capability truth (07-28):** corrected worktree placement, clean preview behavior, opt-in memory, and proxy
  auto-start guidance; documented Codex-supervised Claude execution, consumer lanes, cost/wire control, skills, and all
  CLI groups. Links, anchors, live help, lane labels, and Markdown passed. The documented Codex-supervisor sequence
  remained code-verified rather than live, and the preflight-cache TTL nuance stayed omitted.
- **Native session adoption (07-27):** added evidence-selected Claude/Codex adoption, directory verification, global
  conversation locking plus index binding uniqueness, exclusive manifest reservation, and native transcript preservation
  on deletion. PR coverage included 9,034 unit/regression (one environmental skip), 45 integrations, and two real-Claude
  Docker gates. Crash atomicity across manifest/index was deferred here and closed by the 08-01 transaction work.
- **July model refresh (07-26):** promoted Claude Opus 5, Kimi K3, Qwen3.7, and Gemini 3.6 Flash; clamped derived
  reasoning to catalog-supported efforts, retained displaced models as alternatives, removed dead Gemini 2.0 Flash
  defaults, and raised LiteLLM to 1.88.0 while relying on remote pricing until v1.94. Live Opus/Kimi/Gemini checks
  passed; Qwen remained blocked by account data-policy settings and one local OpenAI control failed identically on
  `main`. Unit, regression, build, live LiteLLM, and pre-commit gates passed.
- **Policy shared-library seam (07-24):** shared provider-aware direct-LLM transport without moving caller-owned
  parsing, telemetry, or failure behavior; consolidated confidence/citation, lane, and resume-ID rules; applied the D7
  team threshold, pre-commit routing, and executor model-pin contracts. Verification: 449 focused, 8,314 unit (one skip,
  117 deselected), 529 regression, 32 Docker policy/team-hook checks, mypy, pyright, and pre-commit.
- **Runtime-neutral workflow workers (07-22--07-23):** added opt-in read-only Codex workers, one invocation readiness
  snapshot, grouped mixed-runtime lifecycle ownership, runtime-native auth/billing/error attribution, and nine portable
  workflow packages without changing Claude defaults or quorum. PR #110 merged as `26122901`; 731 focused, 8,277 unit
  (one skip, 117 deselected), Codex/mixed/Claude integrations, clean runtime-scoped wheel lifecycles, QA/walkthrough,
  build, pre-commit, link, and lane checks passed.
- **Unmanaged skill packages (07-22):** added one-snapshot discovery, per-package recovery, status schema v2, and
  provenance/tree/ownership-gated cleanup; unsafe roots remain report-only, while the marker digest and status top-level
  shape were explicit research-preview breaks. PR #109 merged as `cbb58e16`; 289 acceptance, 170 related, 8,230 unit
  (one skip), 522 regression, one wheel Docker lifecycle, build, pre-commit, QA/walkthrough, link, lane, and diff checks
  passed.

## 2026-07-10 -- 2026-07-17 (compacted)

Global-runtime closeout, cross-runtime skill packaging, model-catalog refresh, and memory-passport hardening. Detailed
execution history remains in the matching done cards and PRs; this summary preserves the goals, decisions, verification
anchors, and deferred items.

- **Cross-runtime skill packages (07-16--07-17):** compiled one typed neutral skill source into native Claude and Codex
  packages, with five portable skills and six explicit Claude-only skills; added runtime/scope/profile planning,
  content-addressed caching, schema-v2 ownership tracking, rollback, duplicate classification, and clean wheel/sdist
  lifecycles. Review hardening made explicit runtime narrowing preserve omitted packages, rejected symlinked roots and
  descendants, cross-validated canonical file ledgers, required successful exact-evidence Codex probes, and kept model
  family selection host-authoritative. Durable selection, compiler, ownership, symlink, and cache invariants were
  promoted at closeout. Verification peaked at 381 affected, 8,158 unit (one skip), and 521 regression tests, plus two
  Docker lifecycle cases, real-Codex stages, QA v1.0.30/589 assertions, builds, and pre-commit. Shipped in PR #107
  (d2a94bf7).
- **GPT-5.6 catalog and Sol defaults (07-16):** added Sol, Terra, and Luna profiles and aliases, promoted Sol across
  bundled OpenAI defaults/templates and fresh LiteLLM routes, preserved existing user-owned snapshots, and synchronized
  workflows, skills, docs, and package assets. Verification covered 611 focused tests, 8k-scale unit runs, two targeted
  provider integrations, builds, clean wheel/sdist installs, and pre-commit. Live direct OpenAI validation remained
  environment-limited by a 401 key response, and remote LiteLLM credentials were unavailable.
- **Memory-passport CLI preflight (07-16):** consolidated project-root, compatibility, path-safety, and file preflight
  behind a structured private resolver while preserving leaf wording, rendering, mutation, and stream precedence.
  Focused CLI (228), unit (7,907 with one skip), pre-commit, Markdown, and diff checks passed. Shipped in PR #105
  (9288bed2).
- **OKF-compatible memory passports (07-14--07-15):** added creation-only OKF v0.1 concept envelopes and an explicit
  idempotent passport upgrade while keeping ordinary re-track non-migrating and avoiding bundle-conformance claims.
  Remediation unified delimiter parsing, rejected blank intent and unsafe frontmatter, case-folded logical/resolved
  reserved targets, preserved modes through atomic writes, and blocked existing shadow-only reserved paths before any
  mutation. The proposed non-identical CLI preflight cleanup shipped separately in PR #105. Verification across commits
  fae54345 and 58b7e97 included 7.8k-scale unit runs, 500-plus regressions, handoff/installer integration, builds,
  isolated wheel/sdist enables, packaged walkthrough smokes, pre-commit, and diff checks. The reviewed mutation-boundary
  lessons remain proposed in `.forge/memory/shadow_impl_notes.md` pending promotion.
- **Global Forge runtime epic (07-13):** closed the five shipped hook-ownership, binary-resolution, migration, and
  execution-environment seams; synchronized normative docs and inbound links; added the retired lane and retired
  unshipped T2 as superseded. GUI-safe status-line reachability remained a standalone proposed follow-up. PR #99
  (168b7db7), 285 focused tests (one skip), 17 Docker installer cases, 86 closeout checks, pre-commit, link, lane, and
  diff sweeps verified the closeout.
- **Project compatibility mutator sweep (07-12):** enforced each target state owner's Forge root across session, policy,
  transfer, memory, search, cleanup, hook, and detached-writer mutations while retaining narrow global registry and
  proven-stale index exemptions. Managed-worktree refusal became atomic, and partial cleanup reports compatibility skips
  truthfully. PR #98 (aa45114d), 7,724 unit tests (one skip), 151 targeted integrations, 35 focused regressions, and
  pre-commit passed. The real Claude-to-Codex bridge stopped at an isolated CODEX_HOME key-readiness gate; host
  preflight was healthy and no product change remained pending.
- **Checkout runtime override (07-12):** added process-scoped FORGE_DEV checkout dispatch with fail-closed
  invalid-target exit 127, preserved stable custom launchers through a four-step recording transition, diagnosed
  override validity/effectiveness, and synchronized public environment guidance. PR #97 (46ff9ef6), 308 focused tests,
  17 Docker cases, wheel/sdist and uv-tool smokes, live valid/invalid dispatcher checks, pre-commit, Markdown, link, and
  lane checks verified implementation and closeout.
- **Hook migration cleanup (07-10--07-11):** added explicit preview/apply cleanup for pre-user-scope installations,
  selected one tracked root without implicitly mutating others, migrated canonical Claude/Codex ownership with backup
  and re-trust guidance, enrolled the root last with backfill provenance, and surfaced independent cleanup state without
  broadening genuine double-hook diagnostics. PR #96 (93312179), 320 migration tests, 68 CLI guards, 7,556 unit tests
  (one skip), Docker and real-Claude migration coverage, an isolated walkthrough, pre-commit, Markdown, link, lane, and
  diff checks verified implementation and closeout. T8 remained parked at that closeout and shipped separately the next
  day.
- **Sidecar hook resolution (07-10):** restored Forge runtime hooks inside Claude sidecars through canonical persisted
  hook staging, idempotent entrypoint auth merging, image PATH resolution, and a host-drainable deferred queue with path
  normalization and container drain suppression. Stale-image skew and PATH breadth remained explicit follow-ups.
  Verification included 7,517 unit tests (one skip), three targeted sidecar integrations, pre-commit, all PR #94 GitHub
  checks, Markdown, and post-merge link/lane scans.

## 2026-07-01 -- 2026-07-08 (compacted)

Global-runtime foundations, session/rewind work, CLI boundary cleanup, and model/backend changes. Detailed execution
history remains in the matching `docs/board/done/` cards and PRs; this summary preserves the goals, decisions,
verification anchors, and deferred items.

- **Global install and runtime hooks (07-06--07-08)**: made global-tool installation the Day-1 path and added read-only
  `forge extension doctor` install-kind/PATH diagnostics; removed the untracked `forge hook enable|disable` writer;
  single-sourced Forge hook matching and pinned registered command bytes; then shipped the fail-open
  `~/.forge/bin/forge-hook` dispatcher and moved Claude/Codex runtime-hook ownership to user scope. Project/local
  installs retained project settings such as `statusLine`, old project/local hook rows stayed removable, and detection
  accepted both dispatcher and legacy command forms while diagnosing logical double-fire risk. Decisions: minimal-PATH
  status is a reported fact, dispatcher drift is doctor-owned, and legacy user-local settings were a clean break. At
  closeout, T10 sidecar resolution and T6 migration cleanup were next and T8 remained parked. Verification: full unit
  runs around 7.5k tests, focused install/hook/doctor/regression suites, Docker installer and real-Claude hook
  integrations, dispatcher latency characterization, and `make pre-commit`.
- **Project and environment contracts (07-07)**: established `~/.forge/projects.json` as the locked trusted-root
  registry and `.forge/project.toml` as an opt-in hand-edited compatibility pin enforced by extension/session paths and
  surfaced by doctor. Uncovered confirmed-state, memory-writer, and proxy/backend mutators moved to the accepted
  `forge_project_compat_mutator_sweep` follow-up. The public/internal `FORGE_*` vocabulary was documented and guarded
  across CLI and user docs so normal guidance names sessions and CLI flags rather than internal wiring. Verification:
  355-test and 38-test focused suites, three named Docker checks, 169 env-vocabulary/CLI tests, pyright, Markdown hooks,
  and `make pre-commit`.
- **Shared proxy, policy, and test seams (07-06)**: single-sourced raw tier-word detection while deliberately preserving
  display-name fallback behavior; unified message/count-token model resolution and loopback port probing without
  changing routing, cost, or caller exception contracts; moved policy-supervisor mutations behind UI-free ops; and
  consolidated session inheritance, runtime/lane, TDD-sort, supervisor-option, and hook-capture twins. Test mirrors and
  support helpers were reorganized, fixing the surfaced status-line role-alias miscount and malformed transcript-path
  leak. Verification: focused suites from 392 to 1,045 tests, a 7,379-test unit run, proxy/status-line/policy/hook
  Docker integrations, and `make pre-commit`.
- **Durable state and session-test structure (07-05)**: hoisted atomic byte/text writes, JSONL append/retention, and
  versioned reads into core leaves while keeping telemetry planes and schemas separate; unreadable search state now maps
  to domain errors and all-scope search skips unreadable project indexes. The 4,933-line session CLI test catch-all was
  split by command family with a narrow shared launcher fixture. Verification: focused state/search/install/backend
  suites, full unit tests, targeted search/proxy/backend integrations, merged PR #77 layout checks, and
  `make pre-commit`.
- **Rewind and session-layer extraction (07-02--07-05)**: shipped PR #66 rewind resume/fork using a fresh UUID,
  turn-boundary-truncated native history, and an AI code delta over dropped turns; interleaved history fails closed,
  code-delta failure falls back to native relocation, and fork rewind remains worktree/`--into` only. PR #68 then
  excluded `rewind` from transfer-context parsers before expensive preflight. A real-Claude Docker gate later closed the
  disclosed truncated-prefix gap without mutating the prefix. In parallel, session preflight/model-pin helpers and fork
  supervisor wiring moved behind core seams, the parent CLI shim was retired, and sidecar sandbox confirmation was
  delayed until immediately before launch. Verification: rewind/fork units, 2,681 CLI/regression tests, 21 lifecycle and
  10 supervisor Docker tests, the real-Claude rewind integration, and `make pre-commit`.
- **CLI and backend boundaries (07-03--07-04)**: routed top-level errors/diagnostics to stderr; made bare
  `policy enable` fail loudly without `--bundle`; replaced activity `--days|--all` with `--period today|week|month|all`;
  split logs into scriptable `show` and preview-default `clean`; and normalized help/lane errors. Backend stop now
  targets live runtime instance ids, while delete remains adapter-config ownership. The backend identity clean break
  made `proxy.backend` canonical, upgraded backend/downstream schemas to v2, and separated backend instance, managed
  process, and telemetry origin fields. Verification: 2,207 CLI tests, 7.3k unit tests, 482 regressions, focused
  command/help/stream tests, targeted integration, and `make pre-commit`.
- **Accidental-complexity closeout (07-01--07-04)**: removed verified dead code and duplicate workflow templates/search
  scoring/secrets plumbing, narrowed proxy providers to `litellm|openrouter`, and made malformed legacy proxy/template
  config fail contextually. Fixed backend delete's double-stop, live session activity reporting, the auth-retry
  provider-trace hole, and fail-open supervisor exit status; demoted the test-only workflow policy surface and corrected
  the marker schema to v1. Decisions: retain `SearchDocument.tokens`, accept-and-ignore the legacy passport key, keep
  the real Env+File credential chain, and put shared telemetry vocabulary in a neutral leaf to avoid a cycle. Deferred:
  a durable `server.py` extraction and a separately proposed workflow-policy CLI graduation. Verification: full unit
  runs from 7,222 tests upward, focused suites and integration checks, manual malformed-config repros, adversarial
  review, static checks, and `make pre-commit`.
- **Model catalog and defaults (07-01)**: added Claude Sonnet 5, promoted Sonnet 5/Opus 4.8 across Anthropic and
  OpenRouter defaults/templates, retained older models as alternatives, updated context-estimator defaults, and allowed
  any Claude pin through Anthropic passthrough. Verification: 7,231 unit tests, 470 focused tests, two Docker model-pin
  smokes, the passthrough regression, and `make pre-commit`. Shipped in PR #64.
- **Consumer lanes closeout (07-01--07-02)**: completed the lane contract and the memory-writer Codex dispatch arm.
  Memory writing resolves its runtime before Claude availability, uses read-only or workspace-write Codex sandboxes,
  degrades asynchronously, and leaves spawned-run telemetry to the invoker. Team-supervisor Codex dispatch was carved
  out because Codex lacks Claude's resume-based plan context; runtime-neutral plan/context delivery remained the
  explicit follow-up rather than holding the lane substrate open. Verification: 189 unit/bridge tests, two live Codex
  E2Es with one subscription-quota event and no duplicate upstream row, board-link checks, and `make pre-commit`.

## 2026-06-22 -- 2026-06-30 (compacted)

Consumer lanes, state boundaries, CLI taxonomy, and Codex proxy launch. Detailed evidence remains in the matching done
cards and PRs.

- **Consumer lanes T0--T7:** added `chatgpt`/`claude-max` subscription sources, pure lane vocabulary, frozen bindings,
  lane CLI, Codex supervisor/curation dispatch, billing, and sticky fail-open fallback. Runtime-native auth remained
  endpoint semantics; direct lanes bypass proxies; aux bindings freeze on dispatch. Memory-writer/team-supervisor Codex
  work and live exhaustion/release checks stayed deferred. Focused suites, ~7k unit tests, Docker real-Claude, and a
  host Codex curation smoke passed.
- **State boundaries:** split corruption from transient unreadability, added guarded cleanup/recovery, and made targeted
  paths propagate actionable failures while best-effort scans may degrade. Corrupt/unreadable regressions, 6.9k--7.3k
  unit/regression runs, review fixes, and pre-commit passed.
- **CLI cleanup:** moved session/telemetry/model commands to their durable taxonomy, removed stale aliases/surfaces,
  normalized groups, errors, destructive prompts, config parity, and JSON streams. Kept aliases are
  `ext`/`sess`/`mem`/`cfg`; clean breaks use Click errors. CLI invariants, Docker integration, build, and pre-commit
  passed.
- **Codex proxy launch:** shipped status, byte-preserving Responses ingress, and proxied start with capability and proxy
  identity gates, generation-only accounting, and proxy-owned auth. Unit/CLI suites, a real Codex-to-Forge request, and
  pre-commit passed; a live 200 reasoning round-trip remained blocked by the unavailable key.
- **Checker fixture:** corrected the plan from create to overwrite; the Docker supervisor E2E passed 10/10 and repeated
  real-checker runs.

## 2026-06-18 -- 2026-06-20 (compacted)

Telemetry backend-attribution and remote-reconciliation arc; detailed history remains in the matching done cards.

- Split telemetry into downstream attempts and upstream outcomes, added two-pane activity/shared measurement, and made
  cap bootstrap use the maximum durable source. `ModelSource` owns endpoint/auth/lifecycle; backend identity stays
  distinct from writer origin and local LiteLLM is display-only.
- Generalized provider grouping and metadata-only remote reconciliation; failures render unavailable, direct grouping
  has one global opt-in, and per-proxy preview keys were removed. Custom-template credential preflight stayed deferred.
  Focused/live provider-trace and sidecar Docker checks, static checks, and pre-commit verified PR #39.

## 2026-05-22 -- 2026-06-16 (compacted)

Runtime, Codex frontend, transfer, proxy observability, and status-line foundations; detailed history remains in the
matching done cards and PRs.

- Added rooted run/usage identity, shared invocation, frozen actions, schema-backed transfer, passports, native
  relocation, Codex lifecycle/TUI/hooks, supervisor controls, redacted provider traces, and status-line health.
  Initial-message delivery and scoped enrollment stayed canonical; costs became reported-or-unavailable.
- Deferred app-server transport, upstream fail-open, PermissionRequest research, path rewriting, sidecar/default native
  relocation, direct provider callers, and parse/auth fail-opens. Roughly 6.1k--6.4k unit tests, regressions, static and
  pre-commit checks, plus focused real provider/Codex policy, transfer, generation, cancellation, and launch paths
  verified the arc.
