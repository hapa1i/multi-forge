# A3: bounded feasibility before runtime work

Status: proposed study design. Offline preparation is active; this document grants no paid-call or native-data approval.
A3 depends on A1 and B1. A2's failed wrapper study neither validates nor rules out plan/action checking.

## Decision to make

Can reviewed atomic plan questions identify useful, completely covered actions that warrant a later review-skipping
study? The first screen tests judgment under human-reviewed plan coverage. It does not validate automatic decomposition,
runtime evidence acquisition, representative false-allow rates or subscription savings.

Start with offline evidence admission and human review. Stop if that cannot establish a useful supported subset. Only
then prepare a separately approved Jev capture. Generative-checker and frontier comparison calls wait until the
candidate survives this screen; there is no reason to spend on those baselines if the candidate already fails its own
labels.

## Verified starting constraints

The current [`PlanCheckPolicy`](../../../../../src/forge/policy/semantic/plan_check.py) uses a generative checker and
can accept sufficiently informative truncated excerpts. A3 instead requires complete supported evidence. Preserve that
baseline difference in later comparisons; do not silently make the existing checker stricter.

[`ReviewSource`](../../../../../src/forge/policy/semantic/plan_source.py) shares an immutable plan snapshot between
checker and frontier. [`PolicyEngine`](../../../../../src/forge/policy/engine.py) gives denials precedence and invokes
its resolver for unresolved review. A Jev allow must not resolve unrelated findings or turn unavailable review into a
positive alignment judgment. B1's operational fail-open result remains distinct from reviewed alignment.

The [Codex adapter](../../../../../src/forge/cli/hooks/codex_policy.py) emits per-file contexts, omits deletions and
bounds displayed evidence. A full-action digest does not establish full-action coverage. The initial candidate may admit
only complete supported single-operation cases; multi-file, deletion, cross-file and truncated actions are escalation
controls until whole-action composition is proved.

[`validate_reviewer`](../../../../../src/forge/policy/semantic/identity.py) currently rejects ordinary
`auth_mode=subscription-only` with cascade enabled. Do not bypass that guard or use inherited authentication to claim
subscription savings. A future paid Jev tier with an independently guarded subscription reviewer needs an explicit auth
contract before runtime work.

The [shared deadline](../../../../../src/forge/policy/semantic/deadline.py) is 55 seconds inside the 60-second hook. The
existing checker allows up to 15 seconds and the frontier up to 45; those maxima cannot both fit. A3 must reserve the
configured frontier allowance and completion work before starting Jev, accounting for preparation and every file. A2's
five-second proposal is not an inherited A3 limit.

## Offline packet: at most 24 synthetic cases

Propose four small plan families with six action variants each. Keep every normative plan clause in a review ledger: map
it to a question, explain why it is irrelevant to that action, or mark it unsupported. Any relevant unmapped or
unsupported clause prevents an allow, regardless of model confidence. Retain exact plan/action bytes and versions.

| Family               | Example plan concern                                             |
| -------------------- | ---------------------------------------------------------------- |
| Input handling       | Validate malformed input and preserve the specified error result |
| Data transformation  | Produce the specified output without mutating the supplied input |
| Local file operation | Respect the supplied destination/overwrite contract              |
| Bounded processing   | Preserve ordering and stop at the declared work bound            |

Within each family, include an aligned action, a divergent action, an omitted relevant constraint, missing or partial
context, changed/ambiguous plan authority, and adversarial action text. Include multi-file/deletion controls among the
unsupported variants. These are construction intentions, not human labels. Use fixture state only; read no repository
history or native sessions. If a rule needs unsupplied facts, retain that limitation instead of inventing evidence.

Humans review plan authority, clause coverage, per-question evidence and answers, and the expected allow/escalate result
separately. Unknown or disputed labels stay pending. Model agreement, successful tool execution and B1 reviewer verdicts
are not ground truth. Keep labels and reviewer-only rationale out of provider payloads.

Assign two whole families to calibration and two to held-out model evaluation before any outputs. Fix semantic wording
and the finite threshold-selection procedure before calibration; freeze selected settings before held-out dispatch. If
held-out cases influence prompt design, report that exposure and do not claim unseen-scenario generalization.

Compare offline admission with two local controls: always escalate, and explicit deterministic checks supported by the
same evidence. Report whether any proposed semantic allow adds value beyond those checks. Do not add an AST framework or
infer semantic coverage from successful parsing.

## Capture proposal, only after review

The first possible model screen is Jev only, with at most 24 cases and three repetitions: no more than 72 physical
requests, often fewer because host-rejected cases dispatch nothing. This is a proposed ceiling, not an authorization. A
concrete manifest must fix each slot, exact payload, model/route, privacy settings, price snapshot, input/response caps,
per-request and whole-run deadlines, spend allowance, isolated telemetry home and retained output bounds. Use A1's typed
client, mandatory ZDR, explicit evaluation identity and zero retries. Do not reuse A2's consumed allowance.

Fix an instruction/decision formulation for this study. No adaptive prompt editing, replacement cases, refilled slots or
resumption after uncertain sends. Reserve attempts durably before dispatch. Stop on model/route drift, invalid output,
service failure, unknown required cost, exceeded limits or evidence-write failure; preserve incomplete denominators.

Proposed semantic gate for owner review: zero composed false allows on divergent or mandatory-escalation cases in any
repetition, all host coverage failures escalate, and at least one correctly allowed semantic case in each held-out
family across all repetitions that the deterministic control cannot already settle. Evaluate only the declared bands on
fixed calibration observations; stop before held-out dispatch if none meets the calibration gates. Once settings are
frozen, stop at the first held-out false allow. If all admitted cases abstain, or only deterministic checks explain the
useful allows, record no demonstrated model benefit and stop this study. These small stress-heavy cohorts cannot
estimate deployment frequency or rare error rates.

The manifest must expand those gates into exact case/question keys and freeze the calibration procedure before approval.
Do not borrow the existing supervisor's 0.8 threshold or choose a new threshold without an explicit selection rule.

## What a pass permits

A pass permits review of a separately bounded comparative/observation proposal. It does not activate A3. That next study
must distinguish full B1 supervision, the existing configured generative cascade, and the proposed Jev cascade. Fix
routes, authentication, cache assumptions and per-file invocation counts; 24 full actions need not mean 24 reviewer
calls. Include failures and escalations in observation, not only sampled candidate allows.

Report hypothetical skips separately from actual avoided Claude invocations. Subtract deterministic denials, cache hits,
existing-checker skips, escalations and audit overhead before attributing incremental benefit. Keep API cost and unknown
subscription quota measurements separate. Before runtime activation, require a reviewed auth/admission design,
independent quality evidence, whole-hook timing and native proof of an actual skipped call plus a real escalation.

A failed screen stops this candidate and returns the disposition to the owner and epic. A new formulation or product
scope needs a new bounded proposal; failure does not launch another automatic tuning cycle.
