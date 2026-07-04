---
description: Separate essential from accidental complexity and propose the simplest trustworthy design, evidence-first.
argument-hint: '[scope path] [--quick | --focused | --full]'
---

<!-- Keep in sync with .agents/skills/simplicity-audit/SKILL.md (Codex port: same body; only frontmatter and the
Invocation lead-in differ). -->

# Simplicity Audit

Strip a codebase down to what it actually does, then figure out the simplest trustworthy way to do it.

Most codebases accumulate complexity over time: abstractions added speculatively, patterns adopted because they are
conventional rather than necessary, indirection that solved a problem that no longer exists, configuration that encodes
imaginary variation, and operational machinery whose original purpose is no longer obvious.

This audit cuts through that by starting from the ground truth of what the software actually accomplishes, then
reasoning from first principles about how to achieve the same results with less.

This is not a bug hunt or a conventional architecture review. It asks a harder question:

> Given what the software actually needs to do, is the overall approach still the right one?

The goal is not minimalism for its own sake. The goal is to separate **essential complexity** from **accidental
complexity**, preserve the former, and remove or reduce the latter without breaking behavior, contracts, reliability, or
team trust.

The document is principles-first (mindset, evidence discipline, classification), then process (Phases 0–4, with an
adversarial verification step between assessment and proposals).

---

## Core Mindset

The central tension in software design is between:

- **Essential complexity**: the irreducible difficulty of the problem domain.
- **Accidental complexity**: difficulty introduced by implementation choices, historical baggage, speculative
  generality, or unnecessary indirection.

Every real codebase has both.

A good simplicity audit does not reflexively delete abstractions. It asks:

1. What does this software actually do?
2. What concepts must exist for it to do that correctly?
3. Which concepts, layers, states, configurations, or dependencies are not carrying their weight?
4. What simpler design would preserve the important behavior?
5. How do we know the proposed simplification is safe?

Important instincts:

- **Convention is not justification.** "This is how you do it in React/Rails/Go/Spring/etc." is not enough. The question
  is whether the pattern serves this specific codebase.
- **Count the concepts.** Every abstraction, type, mode, lifecycle hook, config option, and indirection layer is
  something a maintainer must hold in their head.
- **Respect what works.** Some complexity exists because the problem is genuinely complex. Identifying essential
  complexity is a valid and valuable finding.
- **Think about the 90% case.** Many codebases are shaped by their hardest edge case. Sometimes the simpler design
  handles the common path directly and treats rare edge cases explicitly.
- **Prefer boring clarity over clever compression.** Fewer lines of code is not the same as simpler code.
- **Simplification must be behavior-preserving unless explicitly stated otherwise.** If a proposal changes behavior,
  contracts, or guarantees, say so directly.
- **Complexity can move rather than disappear.** A change that simplifies one module while making deployment,
  operations, user support, or call sites harder is not automatically a win.

---

## Invocation and Boundaries

This runs as a slash command. Read `$ARGUMENTS` before anything else:

- A path or area (for example `src/forge/proxy`) sets the **scope**. If none is given, infer it from the conversation
  and apply the confirmation rule below.
- A mode flag sets **depth**: `--quick` (Quick Scan), `--focused` (Focused Audit), `--full` (Full Codebase Audit). If
  none is given, infer the mode from the scope and the user's ask, then state the mode you picked.

State the inferred scope and mode before expensive exploration. Ask for confirmation only when no scope was given and
answering would require a full-repository scan, or when two or more plausible scopes would materially change the result.
Otherwise proceed with the smallest reasonable scope and note the assumption.

**This command produces a report, not code changes.** Do not edit code, open PRs, or start refactoring. The report lands
in the conversation; on explicit request, shape it into a board card at `docs/board/proposed/<slug>/card.md` per
`docs/developer/board_contract.md` — that is this repo's sink for accepted audit output.

**When to stop:** Stop after Phase 4 (the report) unless the user explicitly requests implementation. Stay within the
invoked mode — do not expand a Quick Scan into a full-codebase sweep without being asked.

**Not a style review.** Do not treat naming, formatting, framework idioms, or file organization as simplification
findings on their own. They count only when they create measurable cognitive, navigational, behavioral, operational,
change, or failure complexity (see Complexity Dimensions).

**Not a reorganization review.** When a finding's remediation is purely a behavior-preserving move, extraction, or
consolidation with nothing to delete, hand it to the sibling refactor audit (`.claude/commands/refactor_audit.md`;
precedent: the `session_op_layer_extraction` carve-out).

## Audit Modes

Adapt the depth of the audit to the scope and evidence available.

### Quick Scan

Use when the user wants a gut check or high-level sense of where accidental complexity may exist.

Expected output:

- 2–5 candidate simplification opportunities.
- Mostly Low or Medium confidence.
- Lightweight inventory rather than exhaustive mapping.
- Clear caveats about what was not checked.

Do not overstate certainty in this mode.

In Quick Scan mode, treat findings as candidate hypotheses unless enough evidence was actually checked to classify them.
Prefer "candidate simplification" or "question for a focused audit" over Accidental or Legacy when the Justification
Search was incomplete — a lightweight mode must not emit the doc's most confident labels on the least evidence. No
adversarial verification pass is required; the hypothesis framing already carries the uncertainty.

### Focused Audit

Use when the user points to a module, feature, service, package, or directory.

Expected output:

- Functionality inventory for the scoped area.
- Dependency and call-path analysis.
- Justification Search for each concrete proposal.
- Adversarial verification (see Adversarial Verification) of every High-confidence finding.
- Actionable recommendations with confidence, risk, and effort.
- Open questions where code alone does not explain the design.

### Full Codebase Audit

Use when the user asks for a comprehensive simplification review.

Expected output:

- Feature-area inventory across the codebase.
- Complexity budget table.
- First-principles assessment by feature area.
- Adversarial verification of every Accidental and Legacy candidate.
- Prioritized simplification roadmap, grouped into batches.
- Explicit "do not simplify" / essential-complexity findings.
- Refuted candidates with the refuting evidence.
- Open questions requiring team input.

**Fan-out contract.** A full audit exceeds one pass's working context. Run one auditor per feature area (in this repo,
roughly the packages under `src/forge/` plus the skills/extension surface), and give each auditor two things: its area's
paths, and the authority-doc sections that govern that area — so Justification Search step 0 runs against the right
design docs, not from memory. Each auditor returns findings with classification and the Justification Search evidence
attached, not raw file dumps. Consolidate and dedupe across auditors, run the adversarial verification pass on every
Accidental/Legacy candidate, then write one coherent report.

---

## Epistemic Discipline

This audit lives or dies on the accuracy of its judgments.

A false positive — recommending removal of complexity that exists for a good reason — is far more damaging than a false
negative. A bad recommendation does not merely waste refactoring time; it erodes trust in the entire audit.

Before classifying any complexity as Accidental or Legacy, actively try to justify its existence.

Treat the code as innocent until proven guilty.

---

## The Justification Search

For every piece of complexity you are tempted to flag, systematically check the following. This checklist is the audit's
single evidence bar: High confidence, an Accidental or Legacy classification, and a proposal's "What You Verified"
section all mean "the Justification Search was completed" — they reference this section rather than defining separate
standards.

### 0. Read the project's own architectural decisions first

Before treating any complexity as a candidate, check whether the project already decided it is intentional.

This repo's authority map:

- `docs/design.md`, `docs/design_appendix.md`, `docs/design_workflows.md`, `docs/cli_reference.md` — normative shipped
  architecture.
- `CLAUDE.md` and `docs/developer/coding_standards.md` — standing directives, including the boundary framework and the
  research-preview clean-break policy (§5) that governs remediation shape.
- `docs/board/impl_notes.md` — human-approved durable decisions; the record most refuted findings lean on.
- `docs/board/` cards in any lane, plus `docs/board/change_log.md` — the why behind recent changes.

A documented, deliberate architectural decision is strong evidence the complexity was intentional — treat it as Earned
or Essential by default, unless newer code, history, or documentation shows the original conditions no longer apply.
Contradicting an intentional decision requires that kind of evidence, not merely that the code looks conventionally
over-abstracted. This project also treats user-defined concepts as first-class architectural concepts (`CLAUDE.md`);
"this named concept could be an implementation detail" is not a finding here. Skipping this step is the fastest way to
produce confident false positives against abstractions the team chose on purpose.

### 1. Search for non-obvious consumers

Look beyond the immediate module. `rg '<symbol>' src/ tests/ docs/` catches direct imports, test fixtures, configuration
references, and documentation examples in one pass; follow up on what a literal search can miss — dynamic/string-based
references, CLI wiring, scripts and CI jobs, generated code, and downstream/public API consumers.

Abstractions often exist because something outside the obvious call chain depends on them.

### 2. Read git history

Check the history for the files, abstractions, config options, or call paths involved:

```bash
git log -S '<symbol>' --oneline    # when it was added/changed and why
git log --follow --oneline <file>  # the file's life, across renames
git blame <file>                   # which commit last touched the suspicious region
```

Look for commit messages mentioning bug fixes, incidents, edge cases, rollbacks, compatibility, performance, race
conditions, security, migrations, "temporary" workarounds, or previous failed simplification attempts.

Complexity added in response to a bug, incident, or production failure is often essential or earned. Someone may have
learned the hard way that the simpler approach did not work. Conversely, in this repo `git log -S` pointing at the
initial release commit with no later activity is the signature of speculative scaffolding that never grew a consumer.

### 3. Check for external constraints

Some constraints are invisible from the implementation alone. Scan the README, docs, ADRs, comments, API schemas,
deployment/CI config, release notes, and changelogs for: public API contracts, backwards-compatibility promises,
compliance/audit/data-retention requirements, performance SLAs, availability requirements, multi-tenant isolation,
customer-specific behavior, client version compatibility, and legal/billing/entitlement constraints.

### 4. Look for the test that explains the abstraction

A test may reveal why an abstraction exists. Evidence that an abstraction may be earned: tests swap implementations or
exercise multiple strategies; tests verify failure, retry, or backwards-compatibility behavior; tests encode subtle edge
cases; the abstraction makes otherwise painful integration tests fast and reliable.

But also be skeptical: sometimes tests merely mirror over-engineered production design. If the test file is larger than
the implementation, ask whether the abstraction pays for itself or whether the tests are preserving accidental
complexity.

### 5. Consider runtime conditions not visible in code

Infrastructure code often looks excessive until production conditions are understood.

Treat complexity in the load-bearing zones catalogued under **Special Caution Zones** below — caching, retries,
idempotency, locks, backpressure, migration paths, feature flags, permission and security boundaries, audit logs,
observability, and the rest — as load-bearing until evidence says otherwise. Assume it exists for a reason unless the
Justification Search turns up none.

### 6. Check whether complexity has moved elsewhere

Before proposing removal, ask whether the complexity would simply relocate:

- From code into configuration.
- From runtime behavior into deployment process.
- From one module into many call sites.
- From explicit checks into implicit conventions.
- From developers into users.
- From application code into operations.
- From a central abstraction into duplicated local policies.

A simplification is strongest when it reduces total system complexity, not just local complexity.

---

## Confidence Calibration

Confidence reflects how thoroughly the claim was investigated, not how obvious it seemed at first glance.

### High Confidence

Use only when the full Justification Search (steps 0–6) was completed and found no credible justification, the proposal
has clear behavioral equivalence criteria, and you can explain why likely counterarguments do not apply.

High confidence should be rare and earned.

### Medium Confidence

Use when:

- Obvious consumers and tests were checked.
- Some history or documentation was inspected.
- The simplification looks plausible.
- There are still plausible reasons the complexity might be intentional.
- Missing evidence prevents full certainty.

State the unresolved possibilities explicitly.

Example:

> Medium confidence: the `PaymentProvider` interface has only one implementation and no in-repo consumers require
> substitutability. However, external plugin consumers are not visible in this repository, so the team should confirm
> this is not part of a public extension contract.

### Low Confidence

Use when:

- Something looks suspicious, but context is insufficient.
- Important evidence is unavailable.
- You cannot rule out valid reasons.
- The finding should be framed as a question rather than a recommendation.

Example:

> Low confidence: this retry layer appears redundant with the queue retry policy, but production retry settings were not
> available. The team should confirm whether both layers are needed for different failure modes.

When in doubt, downgrade confidence.

A report full of well-calibrated Medium findings is more useful than one full of overconfident High findings.

---

## What To Do When Uncertain

If you cannot determine whether complexity is essential or accidental, say so directly.

A valuable uncertain finding has this shape:

> This abstraction exists, and I cannot determine why from the code alone. I checked consumers, tests, docs, and git
> history. I found no clear justification, but production/runtime constraints may explain it. The team should answer:
> [specific question].

This is not a failure. It is intellectual honesty, and it tells the reader exactly where to focus their attention.

---

## Classification

For every significant piece of complexity examined, classify it.

Classification must reflect evidence gathered during the Justification Search, not the initial impression.

### Essential

The complexity exists because the problem is genuinely hard.

Removing it would lose functionality, correctness, safety, compatibility, performance, or reliability.

Examples:

- Complex permission logic reflecting real product rules.
- Migration compatibility needed for old clients.
- Idempotency logic preventing duplicate payments.
- State machine required by an external protocol.
- Retry/backoff logic required for unreliable dependencies.

Call these out explicitly. They show that the audit is not reflexively anti-complexity.

### Earned

The complexity is not strictly essential, but it serves a real purpose and the tradeoff is reasonable.

Examples:

- An interface with one implementation that isolates a volatile third-party API.
- Dependency injection that makes slow integration tests fast.
- A cache layer justified by documented latency requirements.
- A feature flag system still needed for active staged rollouts.
- A small abstraction that encodes an important domain boundary.

State the purpose it serves and the evidence found.

### Accidental

The complexity does not serve current requirements.

Use this only when the full Justification Search was completed, found no justification, and likely counterarguments were
considered.

Examples:

- Plugin registry with one plugin and no external extension contract.
- Configuration options always set to the same value.
- Pass-through service layer adding no behavior or boundary.
- Strategy pattern around three cases that are fixed and simple.
- Generated abstractions for a framework no longer used.

### Legacy

The complexity served past requirements that no longer apply. Kept distinct from Accidental because the remediation
differs: Legacy is dead support to delete with cited historical evidence, whereas Accidental is live-but-unjustified
structure to redesign.

Use this when there is evidence that:

- The feature it supported was removed.
- The external integration was deprecated.
- A migration completed.
- A rollout flag is permanently enabled.
- Compatibility with old clients is no longer required.
- A previous architecture was replaced but its support code remained.

Cite the evidence.

Example:

> Legacy: the `LegacyWebhookAdapter` supported the v1 webhook format. Git history shows v1 webhook support was removed
> in commit `abc123`, tests no longer cover v1 payloads, and docs only mention v2.

### Uncertain

You suspect the complexity may be unnecessary, but cannot rule out valid reasons from code alone.

Use this when:

- Production constraints are missing.
- External consumers are not visible.
- Git history is unavailable.
- Tests are inconclusive.
- Docs do not explain the design.
- The risk of being wrong is meaningful.

Frame these as questions for the team, not recommendations.

---

## Special Caution Zones

This is the canonical catalogue of load-bearing zones referenced by the Justification Search (step 5) and the
Earned-complexity heuristics. Default to caution here: the evidence bar for calling anything in these areas Accidental
is higher, because they often carry scar tissue from real failures.

- **Security and access:** authentication, authorization, security boundaries, permission checks, multi-tenant
  isolation.
- **Money and entitlements:** billing, payments, entitlements, audit logging, compliance, data retention.
- **Contracts and compatibility:** public APIs, serialization formats, backwards compatibility, mobile/client
  compatibility, compatibility layers.
- **Reliability and distribution:** retries, idempotency, race-condition prevention, distributed locks, caching,
  connection pools, rate limiting, backpressure, queue consumers, dead-letter handling, data consistency safeguards.
- **Change and rollout:** data migrations and migration-compatibility paths, feature flags and rollout machinery, test
  seams around expensive dependencies, interfaces around genuinely volatile third-party systems.
- **Generated and framework-owned code:** generated clients, schema bindings, migration artifacts, framework bootstrap
  files, and code whose shape is dictated by external tooling. Often looks absurd read as human-authored code, but is
  not meaningfully simplifiable inside the application — regenerate or reconfigure at the source instead.
- **Operability:** observability and tracing, incident-response tooling.

Repo-specific zones — this codebase's load-bearing discipline. Read the referenced doc before flagging anything in them:

- **Forge-owned durable state** (`docs/developer/coding_standards.md` §5): versioned schemas, strict deserialization,
  atomic temp+rename writes, explicit reset/migration paths. What looks like ceremony is the durable-state contract.
- **Fail-open policy composition** (`docs/design_workflows.md` §1.2): policy/supervisor paths that deliberately degrade
  to "aligned" rather than block the coding session. The asymmetric error handling is the design.
- **Wire translation and passthrough** (`docs/design.md` §7.x): signature-safety, thinking-block preservation,
  redaction-before-persistence ordering. Byte-level care here is a contract, not paranoia.
- **Telemetry separation** (`docs/design.md` §3.14, `docs/board/impl_notes.md`): telemetry responsibilities stay
  deliberately separated (downstream model-call evidence, upstream operation outcomes, usage attribution — joined by run
  tree), while provider-trace evidence deliberately lives as fields on downstream records, not a standalone plane. Both
  "merge the similar-looking JSONL writers" and "re-extract provider-trace into its own plane" are documented
  anti-goals.

Simplification in these zones is still possible, but the evidence bar is higher.

---

## Complexity Dimensions

Do not rely on lines of code alone.

LOC is useful, but weak. A 300-line explicit implementation may be simpler than an 80-line generic framework.

Track complexity across six dimensions, each a distinct lens:

- **Cognitive** — what a maintainer must understand: domain concepts, abstractions, interfaces, type hierarchies,
  invariants, state machines, lifecycle phases, modes, permissions, failure cases.
- **Navigational** — how hard the code is to follow: number of files and directories, import chains, call depth,
  pass-through layers, framework magic, dynamic dispatch, code generation, naming mismatches.
- **Behavioral** — how many behaviors exist: user-facing behaviors, edge cases, state transitions,
  configuration-dependent behavior, retry paths, error-handling paths, partial failure modes, backwards-compatibility
  branches.
- **Operational** — what must be managed outside normal code flow: runtime configuration, environment variables,
  deployment dependencies, queues, caches, databases, cron jobs, feature flags, monitoring, external services, secrets,
  migration order.
- **Change** — how hard it is to modify safely: files modified together, duplicate policies, hidden coupling, test
  burden, migration requirements, coordination across services, risk of breaking external contracts.
- **Failure** — how many ways it can fail: partial writes, stale cache states, race conditions, retries causing
  duplicates, idempotency gaps, version skew, timeout behavior, dependency outages.

A good simplification usually reduces several dimensions at once.

---

## What Counts as a Concept?

A concept is anything a maintainer must understand to safely change the system: a domain entity, service, repository,
controller, adapter, provider, strategy, registry, plugin, or middleware; a lifecycle hook, state-machine state,
cache-invalidation rule, serialization format, or permission boundary; a feature flag, retry policy, event type,
background job, or config mode; an external integration, naming convention, generated artifact, or data-migration phase.

When proposing simplification, name the concepts being removed.

Example:

> This removes three concepts: `AuthStrategy`, `StrategyRegistry`, and the provider lifecycle. Authentication becomes a
> direct function with explicit branches for the three supported methods.

---

## Phase 0: Scope and Evidence Check

Before judging complexity, establish what can actually be known.

State the scope: the codebase, service, module, feature area, or file set under audit; the user-facing behaviors
included; areas explicitly out of scope; and the audit mode.

State the available and the unavailable evidence, one compact list each — source code, tests, git history,
documentation/ADRs, deployment/CI/runtime configuration, monitoring or incident history, production usage, downstream
consumers. Confidence must be bounded by available evidence: do not claim High confidence for a simplification if key
evidence needed to validate it was unavailable.

**Check prior audits before searching.** Read `docs/board/impl_notes.md`, then locate prior audit cards with
`rg -il 'simplicity audit|accidental complexity|refuted|do-not-simplify' docs/board` and read their do-not-simplify and
refuted-candidates records. Do not re-flag a previously refuted finding without new evidence — cite the prior refutation
and move on. This is what keeps repeated audits convergent instead of cyclical.

---

## Phase 1: Functionality Inventory

Before simplifying, determine what the software actually does.

Not what the README claims. Not what an architecture diagram suggests. What the code actually accomplishes from a user's
perspective.

A "user" may be a human using a UI, a caller of an API, a CLI user, a scheduled job, another service, a downstream
package, an operator, or a developer using this as a library.

### Step 1: Identify User-Facing Behaviors

Map every distinct observable behavior.

Be concrete.

Weak:

> Handles authentication.

Better:

> Lets users sign in with email/password, Google OAuth, and magic links; issues JWTs; refreshes tokens automatically;
> invalidates sessions on logout; enforces role-based access in API middleware.

For each behavior, note the trigger (user action, API call, CLI command, cron job, event, webhook, queue message), the
output (response, data mutation, side effect, emitted event, notification), the files/modules involved, the tests
covering it, and the external dependencies and configuration involved.

### Step 2: Map the Dependency Landscape

For each feature area, trace what infrastructure it uses: databases, external APIs, queues, caches, object storage, the
file system, search indexes, auth providers, background workers, internal shared modules, runtime configuration,
environment variables, state stores, and feature flags.

Distinguish between dependencies that are essential and dependencies that may be accidental.

### Step 3: Measure the Complexity Budget

For each feature area, estimate: lines of code, files, directories/packages, abstractions, concepts a new maintainer
must understand, external dependencies, configuration knobs, meaningful states/modes, and typical call depth for the
common path.

Rough estimates are acceptable. The goal is to make complexity visible.

Example table:

| Feature Area   | Behaviors |   LOC | Files | Abstractions | Config Knobs | External Dependencies | Key Concepts                                                                            |
| -------------- | --------: | ----: | ----: | -----------: | -----------: | --------------------: | --------------------------------------------------------------------------------------- |
| Authentication |         6 | 1,200 |    14 |            8 |           11 |                     3 | JWT, OAuth flow, magic link, session store, middleware chain, role policy               |
| CSV Import     |         3 |   800 |     6 |            4 |            5 |                     2 | Schema validation, streaming parser, row errors, chunked upload                         |
| Notifications  |         5 | 1,500 |    21 |           12 |           17 |                     4 | Template registry, delivery strategy, retry policy, provider adapter, suppression rules |

This table is the foundation of the audit. It makes the cost of each feature visible.

---

## Phase 2: First-Principles Assessment

For each feature area, ask:

> Knowing what this needs to do, how would I build it today if I were starting from scratch and preserving the required
> behavior?

Then compare that simple design to the current design.

### 1. Is the abstraction level right?

Ask:

- Are there abstractions with only one implementation?
- Is there evidence of known near-term variation?
- Is the abstraction part of a public or external contract?
- Does it provide test leverage that outweighs its cognitive cost?
- Does it isolate a genuinely volatile dependency?
- Does it encode a useful domain boundary?
- Could two or three abstractions collapse into one?
- Does the abstraction hide essential detail or clarify it?

Single-implementation abstractions are suspect, but not automatically wrong.

Prefer this question:

> Does this abstraction earn its existence through current requirements, known volatility, testability, external
> contracts, or meaningful boundary-setting?

### 2. Is the indirection necessary?

Trace a typical request or operation from entry to completion.

Ask:

- How many layers does the common path pass through?
- Which layers add behavior?
- Which layers merely forward calls?
- Which layers translate names without changing meaning?
- Which layers exist only to satisfy framework convention?
- Is dependency injection helping, or is it present because the framework encourages it?
- Could direct calls make the system easier to understand?
- Is dynamic dispatch needed, or would explicit branching be clearer?

Pass-through layers are often accidental unless they enforce policy, isolate dependencies, improve testability, or mark
a real boundary.

### 3. Is the generality earned?

Ask:

- Are configurable behaviors only ever configured one way?
- Are there plugin systems with one plugin?
- Are there strategy patterns with one strategy?
- Are there registries with one registered thing?
- Are there generic data models representing only one concrete shape?
- Are there options that no user or deployment uses?
- Is the code optimized for hypothetical future variation?

Hardcoding current behavior is often simpler when variation is imaginary.

But known volatility matters. If the team has a concrete reason to expect variation, preserve or reshape the abstraction
rather than deleting it reflexively.

### 4. Is the decomposition helping?

Ask:

- Are modules always modified together?
- Are files so small that navigation overhead exceeds organizational benefit?
- Does the folder structure reveal the system or obscure it?
- Are names aligned with domain concepts?
- Are implementation details split across distant locations?
- Do boundaries match ownership or change patterns?
- Are tests organized around behavior or implementation fragments?

A codebase can be over-decomposed. Too many tiny files can make a simple flow feel complex.

### 5. Could a different approach eliminate whole categories of complexity?

Step back.

Ask:

- Could a simpler data model eliminate transformation code?
- Could derived values replace stored state?
- Could a naming convention replace explicit configuration?
- Could a platform feature replace hand-rolled infrastructure?
- Could a library replace custom parsing, scheduling, retrying, caching, serialization, or validation?
- Could direct database constraints replace application-level consistency code?
- Could a single queue/job replace several event bus layers?
- Could sync execution replace async machinery for the common path?
- Could an explicit special case replace an overly general framework?
- Could deleting a feature flag after rollout remove branching everywhere?
- Could reducing supported modes simplify the entire system?

When proposing a library or platform feature, account for the complexity it *adds*: versioning and upgrade cadence,
security patching, licensing, operational and runtime behavior, team familiarity, and whether the library's abstraction
is larger than the problem. "Just use a library" can relocate complexity into dependency management rather than remove
it.

This is the highest-value part of the audit. Look for changes that remove entire categories of complexity, not just
local code cleanup.

### 6. Does the proposed simplification preserve global simplicity?

Ask:

- Does it make call sites more complex?
- Does it duplicate policy across modules?
- Does it move behavior into config files?
- Does it burden operators?
- Does it make testing harder overall?
- Does it hide important behavior behind convention?
- Does it increase support burden?
- Does it weaken observability?
- Does it make future migrations harder?

A simplification that only improves one file may not be worth it.

---

## Adversarial Verification

Before a candidate finding enters the report as Accidental or Legacy, try to kill it. Scale by mode: every
Accidental/Legacy candidate in a Full audit, every High-confidence finding in a Focused audit, none in a Quick Scan. In
Full mode, verify before writing full proposals — killing a candidate early saves a proposal's worth of work; in Focused
mode, verifying the drafted proposal is fine.

- Run a verifier whose brief is to **refute** the finding — a fresh subagent per finding when parallel execution is
  available, otherwise a deliberate second pass. The verifier searches consumers repo-wide, reads git history, and
  checks tests and design docs for the justification the first pass missed. It is trying to win, not to confirm.
- Refuted findings move to the do-not-simplify list **with the refuting evidence recorded** — that record is what stops
  the next audit from re-litigating them.
- Partially justified findings get downgraded or reframed as Uncertain and move to Open Questions — a proposal is
  written only for survivors.
- Calibration: the first full audit of this codebase (2026-07-01) refuted 13 of 33 candidates (39%) as load-bearing. In
  a broad audit with many candidates, zero refutations warrants a second look at the verifier's rigor; on a small or
  already-clean scope it is a legitimate outcome. Never refute to hit a quota — the target is accuracy, not a kill rate.
- Verification often surfaces real defects while hunting for justifications (a path that skips its telemetry write, a
  guard that can never fire). File these under **Surfaced Defects** in the report — they are bugs, not simplifications,
  and per `docs/developer/testing_guidelines.md` a confirmed defect fix requires a regression test.

---

## Phase 3: Simplification Proposals

For each finding classified as Accidental or Legacy that survived adversarial verification, propose a concrete
simplification.

A proposal must be specific enough that an engineer can evaluate it.

Avoid vague recommendations like:

> Simplify the auth layer.

Prefer:

> Replace `AuthProvider`, `AuthStrategy`, and `AuthStrategyRegistry` with a single `authenticate()` function that
> explicitly handles the three supported methods: password, Google OAuth, and magic link. The strategies are never
> swapped at runtime, all call sites use the default registry, and tests can cover the same behavior at the function
> boundary.

Each proposal should include the following.

### 1. What Exists Now

Describe the current approach and its cost: files involved, LOC estimate, concepts and abstractions involved,
configuration involved, call-path depth, and how common changes are made today.

Example:

> Authentication currently routes through
> `AuthController -> AuthService -> AuthProvider -> AuthStrategyRegistry -> AuthStrategy`. There are three strategy
> classes, but they are never selected dynamically outside a fixed enum. The common login path crosses five layers and
> requires understanding provider registration, strategy lookup, and request context injection.

### 2. What It Could Be Instead

Describe the simpler alternative concretely: the proposed shape of the code, what gets deleted or collapsed, how
behavior remains represented, how edge cases are handled, and how tests would be organized.

Example:

> Replace the registry and strategy classes with one `authenticate(method, credentials)` function. Use an explicit
> switch over `password`, `google_oauth`, and `magic_link`. Keep provider-specific helper functions where they contain
> real logic. Preserve the existing public API and controller behavior.

### 3. Behavioral Equivalence and Intentional Changes

Define what must remain true after the simplification — and, separately, state anything that would intentionally change.
Most proposals preserve behavior; Legacy findings often remove dead behavior or an unsupported mode on purpose, and that
removal must be explicit, not a silent side effect.

Must remain true:

- User-facing behavior that must not change.
- API responses that must remain stable.
- Data shapes that must remain compatible.
- Error behavior that must be preserved.
- Performance or reliability properties that must not regress.
- Tests that should continue passing.
- New characterization tests needed before refactoring.

Intentionally removed (if any): name the behavior, mode, compatibility path, or guarantee being dropped, and why it is
safe to drop now.

Example:

> Equivalence requirements: existing login responses remain unchanged; token refresh behavior remains unchanged; failed
> OAuth callback handling returns the same error codes; session invalidation on logout still removes active refresh
> tokens; all current auth integration tests pass. Intentionally removed: none — this proposal preserves all behavior.

### 4. What You Would Gain

Be explicit. Possible gains: fewer concepts, files, and LOC; shallower call path; less configuration; fewer hidden
dependencies; easier onboarding and testing; fewer places to update when behavior changes; lower operational burden;
fewer partial failure modes.

Example:

> Removes two abstractions, three files, one registry concept, and roughly 180 LOC. The login path becomes direct enough
> to read from controller to token issuance in one pass.

Where possible, turn one gain into a falsifiable prediction the team can check locally after the change — a leading
indicator tied to this refactor, not a lagging org metric:

> Prediction: changes to notification delivery should touch ~1 file instead of ~4. Confirm by sampling the next three
> notification PRs.

Do not credit lagging, confounded metrics (CI time, pager volume, onboarding time) to a single simplification.

### 5. What You Would Lose

Be honest about tradeoffs. Possible losses: less conventional framework structure; less ability to swap implementations;
larger functions; some tests moving up a level; less mockability; more explicit branching; reduced future flexibility;
team familiarity costs; migration risk.

Example:

> Loses the ability to add a new auth method by registering a strategy class. A new method would require editing the
> switch directly. Given the low frequency of auth-method additions, this appears acceptable.

### 6. What You Verified

Record the Justification Search results concretely — name what was searched and what was found, not just "checked."

Examples:

- Consumer search: "Searched for `AuthStrategyRegistry`; found four usages, all in auth initialization and tests."
- Git history: "Added in commit `abc123` during initial OAuth implementation; no later commits indicate runtime
  swapping."
- Tests: "Tests assert behavior through API endpoints, not strategy substitution."
- Docs/config/runtime: "No public extension mechanism documented; no deployment config or feature flag selects custom
  strategies."

If you cannot fill this section out, downgrade confidence or classify as Uncertain.

### 7. Confidence

Use High, Medium, or Low according to the calibration rules.

State why.

### 8. Effort, Risk, and Reversibility

Estimate:

- **Effort**: Low / Medium / High.
- **Risk**: Low / Medium / High.
- **Reversibility**: Easy / Moderate / Hard.

Consider: how much code changes, whether data migrations are involved, whether public contracts or durable-state schemas
change, whether rollback is possible, and whether characterization tests can de-risk the change.

### 9. Remediation Plan

For non-trivial proposals, describe how to apply safely. Remediation here follows the research-preview clean-break
policy in `docs/developer/coding_standards.md` §5, not parallel-path rollout machinery:

1. Add characterization tests for the behavior that must survive.
2. Make the break cleanly and atomically: update code, schema, docs, tests, and examples in the same change. No default
   shims, aliases, fallback logic, or parallel old/new paths — a compatibility layer must be explicitly justified in the
   proposal, not kept by reflex.
3. Durable-state changes still need strict shape validation and a clear reset/migration message for stale files.
4. Delete tests for removed behavior; update tests for moved behavior. Never skip.
5. Name the changelog/board entry the change needs.

These rules cover research-preview surfaces. If a proposal touches a surface declared stable, §5's stable-surface policy
applies instead (deprecation period, migration path) — name which regime the proposal falls under, and let the
confidence/risk ratings reflect the contract it touches.

---

## Phase 4: The Simplification Report

Produce a structured report.

Adapt depth to scope. A focused audit of one module does not need the same ceremony as a full-codebase review.

Use this template.

```markdown
# Simplicity Audit: [Project / Area Name]

## Executive Summary

[2–4 sentences: what the codebase/area does, how complex it is relative to that functionality, and the biggest simplification opportunities.]

## Scope and Evidence

**Scope:** [Full codebase / module / feature / directory]

**Audit mode:** [Quick Scan / Focused Audit / Full Audit]

**Evidence available:**
- [Source code]
- [Tests]
- [Git history]
- [Docs]
- [Runtime config]
- [...]

**Evidence unavailable:**
- [Production metrics]
- [External consumers]
- [...]

**Prior audits checked:** [Cards/impl notes read; previously refuted findings not re-litigated.]

**Confidence caveat:** [Any limits imposed by missing evidence.]

## Functionality Inventory

| Feature Area | Behaviors | LOC | Files | Abstractions | Config Knobs | External Dependencies | Key Concepts |
|---|---:|---:|---:|---:|---:|---:|---|
| [Area] | [N] | [N] | [N] | [N] | [N] | [N] | [Concepts] |

### [Feature Area]

#### What it does

[Concrete user-facing behaviors.]

#### Dependency landscape

[External services, shared modules, configuration, state.]

#### Current complexity

[LOC, files, abstractions, concepts, call depth, operational dependencies.]

#### Assessment

[Essential, earned, accidental, legacy, and uncertain complexity. Include first-principles reasoning.]

#### Do-not-simplify findings

[Complexity that looks suspicious but is essential or earned.]

#### Proposals

##### Proposal [N]: [Name]

**Classification:** [Accidental / Legacy]

**What exists now:**
[...]

**What it could be instead:**
[...]

**Behavioral equivalence and intentional changes:**
[...]

**What you would gain:**
[...]

**What you would lose:**
[...]

**What you verified:**
[...]

**Adversarial verification:** [Survived — what the refuter checked and failed to find.]

**Confidence:** [High / Medium / Low]
[Reason.]

**Effort:** [Low / Medium / High]
**Risk:** [Low / Medium / High]
**Reversibility:** [Easy / Moderate / Hard]

**Remediation plan:**
[...]

## Summary of Proposals

| # | Proposal | Area | Classification | Complexity Reduction | Confidence | Effort | Risk | Reversibility |
|---:|---|---|---|---|---|---|---|---|
| 1 | [Proposal] | [Area] | [Accidental] | [-3 files, -2 concepts, ~200 LOC] | High | Low | Low | Easy |
| 2 | [Proposal] | [Area] | [Legacy] | [-1 mode, -4 flags] | Medium | Medium | Medium | Moderate |

## Surfaced Defects

[Bugs found while trying to justify complexity — behavior or observability defects, not simplifications. Each confirmed
defect fix needs a regression test. An empty section is fine; do not pad it.]

| # | Defect | Anchor | Status |
|---:|---|---|---|
| 1 | [What breaks, concretely] | [file:line] | [Confirmed / Needs investigation] |

## Refuted Candidates

[Findings the adversarial pass killed, with the refuting evidence. Written for the next audit as much as this one — it
prevents re-litigating the same candidates.]

| Candidate | Refuted because | Evidence |
|---|---|---|
| [Finding] | [The justification found] | [Doc/commit/test that proves it] |

## Open Questions

| Question | Area | Why it matters | Evidence checked | Who should answer |
|---|---|---|---|---|
| [Question] | [Area] | [Impact] | [Consumers/tests/docs/history] | [Team/person/role] |

## Recommendations

[Prioritized list grouped into batches by confidence and risk/effort — see Recommendation Prioritization. Lead with
high-confidence, low-risk wins. Separate proposals that can be acted on now from those requiring team input.]

## Suggested Next Steps

[Concrete sequence of safe refactors, characterization tests, or team questions. For each acted-on proposal, name the cheap local check that will confirm its predicted gain.]
```

---

## Recommendation Prioritization

Prioritize proposals by impact, confidence, risk, and reversibility.

A useful ordering:

1. **High confidence, low risk, easy reversibility** Do these first. They build trust.

2. **High confidence, medium risk** Do after adding characterization tests.

3. **Medium confidence, low risk** Good candidates for small exploratory PRs.

4. **Medium confidence, high risk** Require team discussion and stronger evidence.

5. **Low confidence** Do not present as recommendations. Present as open questions.

For roadmaps with many proposals, group them into batches by confidence and effort: a first batch of high-confidence,
low-risk, single-file changes (trust-building deletions); a second batch of medium-effort changes that want a
characterization test first; and a final batch of verified-but-low-value items listed explicitly so nobody re-flags
them.

Avoid starting with a dramatic rewrite unless the evidence is overwhelming.

The best first simplification is often small, obvious, safe, and trust-building.

---

## Style and Tone

Phrase findings as tradeoffs, not blame.

Bad:

> This abstraction is pointless.

Better:

> I could not find current evidence that this abstraction is carrying its weight. It may have been useful when the
> module supported multiple providers, but the current code has one implementation, no runtime selection, and no
> documented extension contract.

Bad:

> Whoever wrote this over-engineered it.

Better:

> This appears to be a fossil from an earlier design. The surrounding feature was removed, but the supporting registry
> and configuration remain.

Complexity is often a fossil record of real constraints: deadlines, incidents, product pivots, compliance needs, team
boundaries, and previous migrations. Treat it with respect.

Name the sunk-cost reflex directly. Engineers resist removing abstractions they invested months in, and a report that
ignores that reads as tone-deaf. Do not spin the removal as painless "cleanup," and do not reach for a euphemism. Credit
what the complexity *did*, and attribute its removal to a change in conditions rather than a verdict on its author:

> This registry absorbed real provider variation during the multi-provider period. That period ended when the team
> standardized on one provider. Removing it banks that work rather than discarding it.

A good audit should make the team feel:

- Understood.
- Safer.
- Less burdened.
- Better equipped to simplify deliberately.

---

## Practical Heuristics

Use these as prompts, not laws.

### Suspicious Complexity

Potentially accidental:

- Interface with one implementation.
- Strategy pattern with fixed strategies.
- Registry with one registered item.
- Config option always set one way.
- Middleware that only forwards.
- Service layer with no policy or orchestration.
- Adapter that only renames fields.
- Event bus used only synchronously.
- Feature flag permanently enabled.
- "Legacy" code with no callers.
- Tests that mock every layer but assert little behavior.
- Folders organized by pattern rather than feature.
- Multiple representations of the same domain object.
- Stored state that could be derived.
- Custom framework around a simple workflow.
- Generic code with no actual variation.
- Abstractions named after implementation patterns rather than domain concepts.
- Textbook-conventional abstraction (Strategy, Registry, Factory, Provider) with no motivating evidence: no requirement
  in git history, no test exercising the variation, no config that ever differs. Treat the *absence of a driving
  requirement* as the signal — not a guess about whether a human or an AI assistant wrote it, which you usually cannot
  prove.

### Potentially Earned Complexity

Be cautious around the load-bearing zones catalogued under **Special Caution Zones**, including the repo-specific ones.
Complexity there is often earned: it isolates a volatile dependency, preserves a contract, or encodes a lesson from a
real failure. Verify the specific justification, but raise the evidence bar before flagging.

---

## Example Finding

```markdown
### Proposal 1: Collapse notification provider registry

**Classification:** Accidental

**What exists now:**
Notification delivery flows through `NotificationService`, `ProviderRegistry`, `ProviderFactory`, and `EmailProvider`. The registry supports multiple providers, but only `SendGridProvider` is registered. The provider is selected from config, but every checked environment sets `NOTIFICATION_PROVIDER=sendgrid`.

**What it could be instead:**
Replace the registry and factory with direct construction of `SendGridEmailClient` in notification initialization. Keep a small `send_email()` function as the domain boundary. If another provider is needed later, introduce variation at that point.

**Behavioral equivalence and intentional changes:**
Email templates, suppression rules, retry behavior, provider error mapping, and audit logs remain unchanged. Public notification APIs remain unchanged. No behavior, mode, or compatibility path is intentionally removed.

**What you would gain:**
Removes two concepts (`ProviderRegistry`, `ProviderFactory`), three files, one config knob, and approximately 150 LOC. The common delivery path becomes easier to trace.

**What you would lose:**
Adding a second provider later would require editing initialization code rather than registering a provider. This seems acceptable unless a second provider is planned.

**What you verified:**
Searched for `ProviderRegistry`, `ProviderFactory`, and `NOTIFICATION_PROVIDER`. Found only notification initialization, unit tests, and one docs mention. Git history shows the abstraction was added during an abandoned multi-provider experiment. No current docs describe provider plugins. Tests assert notification behavior and can be rewritten against `send_email()`.

**Adversarial verification:** Survived. The refuter searched for external extension contracts, plugin docs, and deployment configs selecting another provider; found none.

**Confidence:** High
The full Justification Search was completed; no current justification was found.

**Effort:** Low
**Risk:** Low
**Reversibility:** Easy

**Remediation plan:**
Add characterization tests for provider error mapping, then remove the registry/factory and their tests in the same change, preserving `send_email()` behavior. Run the existing notification integration tests and monitor delivery errors after deployment.
```

---

## Final Principle

The goal of a Simplicity Audit is not to prove that the code is bad.

The goal is to find the smallest design that faithfully serves the real problem.

A strong audit should say both:

> "This part is more complex than it needs to be."

and:

> "This part is complex because reality is complex; leave it alone."

That balance is what makes the recommendations trustworthy.
