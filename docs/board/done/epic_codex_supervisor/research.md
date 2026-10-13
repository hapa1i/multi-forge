# Codex supervisor research

Verified 2026-10-06 against Forge `c2638510`. This supports the [Codex supervisor epic](card.md) and its five cards. No
model turns, paid probes, or routing smoke runs were performed during this research.

## Planning verification, 2026-10-07

Rechecked source at B1's base `6e0d1f4c` and local Claude 2.1.291 help/version output. No auth-status or inference calls
were made during this follow-up. The [B1 checklist](../../done/plan_file_supervision/checklist.md) records decisions and
uncompleted probes; the observations below do not establish runtime isolation or billing guarantees.

- Existing `claude-max` is billing metadata: a resolvable key still selects API billing for all four consumers. B1 now
  preserves that compatibility and introduces a separate supervisor-local subscription-only opt-in.
- Both hook commands have conversation-ID presence checks and call shared supervisor registration. Plan-only admission
  therefore needs explicit host Claude coverage and sidecar refusal, not just Codex executor fixtures.
- Claude Write/Edit policy hooks also have a 60-second preset. The Claude runner supplies no read-only tool restriction,
  and its JSON negotiation retry receives a second full timeout. Neither the runtime's signals/kill scope nor reviewer
  cleanup after hook-only death has been measured. B1's probes cover both executors and macOS child-process lifetime.
- Shadow v4 already records the plan snapshot/hash and `lane.model`. Its missing/malformed lane fallback can select the
  default Claude route. The new version must additionally establish source/auth policy and effective model/effort, and
  refuse reconstruction that cannot prove the dispatch contract.

Forge currently resumes Claude from the planner's checkout, but that is not proof that the runtime requires it. Current
[CLI documentation](https://code.claude.com/docs/en/cli-reference) says UUID resume can search across projects since
2.1.223. B1 keeps its existing history lookup until tested; `--add-dir` grants access without choosing which checkout
the reviewer reads. [Permissions documentation](https://code.claude.com/docs/en/permissions) applies permissions to
added directories and describes their customization loading, so both directories need read-selection and write-refusal
evidence.

Current [authentication documentation](https://code.claude.com/docs/en/authentication) describes `CLAUDE_CONFIG_DIR`
namespacing for claude.ai Keychain credentials, but keyless Console profiles use storage outside that directory. That
qualifies the blanket isolation concern; it does not prove the installed binary or every credential source is isolated.
Negative identity/managed-policy cases stay in disposable environments, Keychain tests use a separate macOS user/VM, and
the positive real-host scenario requires unchanged login/settings assertions.

## Current Forge support and the missing path

[Codex policy hooks](../../../../src/forge/cli/hooks/codex_policy.py) normalize `apply_patch` file operations into the
shared policy engine. The [hook command](../../../../src/forge/cli/hooks/commands.py) registers semantic supervision
through the same [helper](../../../../src/forge/cli/hooks/policy.py) as Claude. The existing
[probe harness](../../../../scripts/experiments/codex-hooks/README.md) records a product deny test that checks the file
was not written. Codex hooks are already implemented; trusted registration is required.

The setup path in [policy operations](../../../../src/forge/core/ops/policy.py) requires a target and calls
`validate_supervisor_target`, which requires a confirmed Claude conversation. The
[supervisor](../../../../src/forge/policy/semantic/supervisor.py), plan checker, hook registration, CLI state surfaces,
and lifecycle helpers repeatedly use `resume_id` as the configured predicate. Some uses genuinely resolve a conversation
and must remain source-specific; replacing every occurrence mechanically would be incorrect.

The Claude dispatch resumes its target and uses the planner's working directory. The existing Codex dispatch runs fresh
with a plan in the prompt and the action's checkout, but still sits behind the shared target requirement. B1 adds a
plan-file configuration and fresh Claude dispatch, and explicitly tests plan-only use of the existing fresh Codex
reviewer. B5 separately adds native Codex conversation forks. Supervisor model choice must be made effective in dispatch
as well as the consumer-lane record; merely changing a nominal lane field is insufficient. The proposed 150–250
product-line estimate is not validated and is not a scope limit.

The Codex launch code still rejects `--supervise` and related launch options. Its "no hooks" comment is stale. B1 uses
`forge policy supervisor set --plan <file>` and does not require launch-flag parity. The supervisor's "no --resume"
comments describe an old runtime limitation; the current implementation is deliberately fresh even though the installed
CLI has native resume/fork commands. Correct comments where the relevant cards touch them, preserving historical board
records as evidence of their original runtime version.

## Claude read-only enforcement is missing

The [Claude runner](../../../../src/forge/core/reactive/session_runner.py) supplies no tool or permission restriction.
The supervisor prompt also does not forbid edits. The existing Codex reviewer supplies a read-only sandbox, but the
Claude reviewer's read-only description is intent rather than enforced capability. B1 moving fresh review into the
executor checkout makes this gap consequential; its scope now adds restrictions to both fresh and resumed Claude review.

Forge does have an [artifact-authority guard](../../../../src/forge/cli/hooks/authority.py), but it requires a launch
marker and matching managed authority state. Supervisor dispatch does not establish that contract. An ordinary
supervisor cannot rely on it to prevent writes.

Installed `claude --version` reports **2.1.291**. Its help exposes `--tools` for a positive built-in tool list, and
`--restricted` for reduced capabilities and settings isolation. The latter leaves file-edit tools available and retains
managed/explicit settings; MCP needs separate restriction. Therefore B1 requires an inspection-only tool set and
disables executable customizations, MCP and delegation as alternate write paths. The exact combined invocation needs
tests under permissive user/project settings, for fresh and resumed review. `--bare` skips OAuth login, so it cannot
supply the subscription-only isolation mode. [Claude CLI reference](https://code.claude.com/docs/en/cli-reference)

No adversarial write test or real supervisor turn was run during this research. CLI help establishes available controls,
not proof that their composition enforces the proposed boundary.

Resumed history introduces a separate compatibility question: a planning conversation may already contain `Edit` and
`Bash` calls whose definitions disappear under an inspection-only `--tools` list. No result is established for that
combination. After the auth preflight, B1's first inference probe must test such a disposable conversation, preserving
its source while proving new writes remain blocked. If it fails, compare supported deny/permission mechanisms before
choosing the resumed-run design; flag availability alone does not establish equivalent enforcement.

## Measured local usage

A read-only scan of this checkout's `.forge/sessions/*/forge.session.json` found 78 manifests. All 78 parsed through
`SessionStore.read()` and `compute_effective_intent()` without error. Counts:

| Observation                                        | Count |
| -------------------------------------------------- | ----- |
| Effective policy enforcement enabled               | 0     |
| Effective supervisor with a configured `resume_id` | 0     |
| Confirmed supervisor consumer-lane binding         | 0     |

The underlying JSON also has no supervisor objects in intent, no supervisor overrides, and no policy-state entries.
Intent launch runtimes are 67 Claude and 11 Codex. These are current stored-state measurements for this repository, not
a historical usage ledger or a survey of other workspaces/deleted sessions. They support a local adoption problem; they
do not establish previously incurred supervisor costs or savings.

## Installed Codex versus verified Forge contracts

Local `codex --version` reports **0.160.1**. `codex exec fork --help` exposes a required source session ID and options
including `--ephemeral`, `--output-schema`, `--thread-source`, and `--json`. Help output verifies parser availability,
not their joint behavior, read-only enforcement, hook recursion, or context fidelity. There is no earlier-turn selector
in that help. B5 supports the executor thread as a source only with an explicit approved plan file and a recorded
reduction in independence; a fork can inherit the executor's later implementation reasoning.

Forge's [preflight](../../../../src/forge/core/runtime/codex_preflight.py) sets `CODEX_VERSION_VALIDATED = "0.149.1"`.
The proxy contract has a separate validation version; raising the general ceiling must not imply new proxy evidence. The
[QA runtime matrix](../../../../src/skills/qa/resources/runtime-matrix.json) also records the general ceiling. OpenAI's
[changelog](https://learn.chatgpt.com/docs/changelog) dates 0.160.1 to 2026-10-05. The minor-version gap is eleven; it
is not an audited count of intervening releases.

Current [hook documentation](https://learn.chatgpt.com/docs/hooks) describes `additionalContext` for model-visible
PreToolUse feedback and `systemMessage` for operator warnings in the UI/event stream. These are separate delivery
channels; stderr visibility also needs a direct probe. Background hooks deliver information later and cannot enforce the
triggering action. A Stop block requests continuation; it does not undo the completed turn. B2 must test these claims,
the existing Forge allow shape, turn identity across continuations, `update_plan` payloads, and native forks on the
installed binary. An `update_plan` event alone does not establish user approval of a plan.

Forge currently keeps Codex allow stdout empty and emits warnings to stderr because model-visible allow feedback was
unprobed. B3 therefore has a real dependency on B2. Stop review needs an evidence snapshot and duplicate/recursion
guards: a hook can fire repeatedly, and a continuation may alter the work being reviewed. B4 must keep its one-review
budget while identifying any later changes as unreviewed.

The [catch-all PreToolUse registration](../../../../src/forge/install/codex_hooks.py) now needs measured coverage and
overhead for plan updates, MCP, subagents and long-running shell sessions as well as patches. This is not only a policy
filter: [Codex hook dispatch](../../../../src/forge/cli/hooks/commands.py) runs the authority guard before skipping
non-`apply_patch` tools. Narrowing the registration without retaining that guard's coverage would weaken enforcement. B2
measures actual deliveries, per-tool latency and reviewer-call counts before recommending any matcher change.

## Hook deadlines and observable review failures

The Codex registration fixes PreToolUse at **60 seconds**, and its exact trusted definition includes the timeout. The
[supervisor config](../../../../src/forge/session/models.py) defaults to 45 seconds to reserve a margin, but the CLI
accepts larger values. Checking a single subprocess timeout is insufficient: a multi-file patch can invoke multiple
checks, a cascade can escalate, and the Claude runner can retry output-format negotiation with another full timeout.

B1 must bound the whole hook invocation and validate the configured reviewer limit against that budget, leaving time for
cancellation and durable recording. A runtime kill can prevent the final decision and usage emission, even if earlier
attempts or provider telemetry survive. Record an attempt before inference and expose unfinished attempts as incomplete;
never infer success or zero usage from a missing terminal event. B2 probes actual timeout behavior, and B4 selects and
documents its Stop timeout. A changed timeout or matcher requires enrollment of the changed hook definition.

Before B3, allowed Codex actions have no established in-session warning delivery. The current
[supervisor status](../../../../src/forge/cli/policy.py) primarily shows configuration and routing/degrade state;
[activity](../../../../src/forge/core/ops/usage_summary.py) can report recorded failure counts. Neither is evidence that
a killed hook's missing result is already visible. B1 must expose latest state/reason/time in
`forge policy supervisor status [--json]` and unavailable/incomplete attempts in `forge telemetry activity [session]`.
B3 owns tested model and operator feedback, with model injection following `policy_summary_feedback`.

## Subscription use, credentials, and spending

The user constraint is no API spend on everyday supervision, with paid routes acceptable for complex projects. Choosing
`claude-max` alone does not enforce this: Forge's [billing resolver](../../../../src/forge/core/usage/billing.py) treats
a resolvable API key as API usage even on that lane. The API-key check in
[reactive environment construction](../../../../src/forge/core/reactive/env.py) determines bare-mode eligibility; it
does not audit every Claude authentication source. Child environments currently inherit additional auth variables and
hydrate Forge credentials. A provider-reported cost figure is not a subscription invoice or measured quota decrement.

Claude's documented precedence includes gateway sign-in, cloud flags, bearer/API credentials, key helpers, OAuth tokens
and profiles. `CLAUDE_CODE_OAUTH_TOKEN` can represent subscription auth; it is not inherently an API-paid credential.
Workload identity federation and active/default profiles also matter when `ANTHROPIC_PROFILE` is unset.
[Authentication precedence](https://code.claude.com/docs/en/authentication)

B1's selected design sanitizes the child environment, skips user/project/local settings, and accepts only verified
CLI-managed subscription login. Its test matrix includes `CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX`,
`CLAUDE_CODE_USE_FOUNDRY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_API_KEY`, `apiKeyHelper`, `CLAUDE_CODE_OAUTH_TOKEN`,
`ANTHROPIC_PROFILE`, `ANTHROPIC_FEDERATION_RULE_ID`, `ANTHROPIC_ORGANIZATION_ID`, profile defaults and stored paid
credentials. Account/config-directory selection and missing/expired login must not create an unchecked fallback. Check
only non-secret metadata through supported interfaces; refuse ambiguous sources, managed settings and gateways before
inference. Settings can supply auth environment variables, so clearing only the parent environment is insufficient.
[Settings precedence](https://code.claude.com/docs/en/settings)

The candidate interface is **`claude auth status --json`**. The installed command exposes `loggedIn`, `authMethod`,
`apiProvider`, and conditional `apiKeySource` without a model turn. It must run with the same final child environment,
binary, working/config directories and auth-relevant settings flags as supervision. A plain-shell check before Forge
loads configuration is insufficient. Full equivalence to headless dispatch across auth/settings sources remains an
implementation gate; refuse an unverifiable route rather than read login tokens. The official
[CLI reference](https://code.claude.com/docs/en/cli-reference) documents the command and its logged-in exit status.

The local API-key response omitted `subscriptionType`, but the cleaned login response included
`subscriptionType: "max"`. Thus the API-key observation does **not** establish that the interface never reports a plan.
Treat that field as optional, reported metadata: it does not establish credits settings, credential validity or the bill
for a future call. An isolated synthetic, invalid key also yielded `loggedIn: true`, confirming that this status is not
a paid-auth test. Keep the explicit `claude-max` lane selection and user-side account condition.

Anthropic's [Claude Code terms guidance](https://code.claude.com/docs/en/legal-and-compliance) permits users to sign
into the unmodified binary with their own subscriptions, including in a hosted product, subject to the applicable terms.
It forbids collecting or intermediating Claude login credentials. Products must preserve the binary's supported
authentication and must not resell or intermediate users' Claude usage. Selecting credentials/settings for one child
process does not remove authentication methods from the unmodified binary; the earlier wording should not be read as
banning per-run route isolation.

The
[Agent SDK subscription notice](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
says the proposed June billing change was paused and `claude -p` continues to draw on subscription limits; it promises
an update before that billing change takes effect. This supports the current intended use, not a permanent zero-charge
guarantee. The broader [login guidance](https://support.claude.com/en/articles/13189465-log-in-to-your-claude-account),
updated May 19, also reserves charging third-party-tool use to usage credits for subscribers who enabled them. This
qualification was missing from the earlier research. **Keeping account usage credits disabled is a user-side condition
of everyday no-spend use**, not something Forge's subprocess checks can establish. The article also prefers API auth for
third-party products. Forge's contract is invoking the user's own published CLI without token handling or subscription
resale; preflight must report the limits of its evidence rather than promise account-level billing.

### Local auth-status probes and the actual Forge child

Read-only probes on 2026-10-06 used Claude 2.1.291. Only selected auth metadata, field presence and credential-source
booleans were retained; no token/key values or account identifiers were printed. No `claude -p` invocation was made.

The tool shell initially lacked `ANTHROPIC_API_KEY`. The approved host status check selected the saved Claude login; the
sandboxed check could not see that login. Importing [Forge's CLI](../../../../src/forge/cli/main.py), which calls
`load_dotenv()`, introduced the key. The discovered dotenv file contained that variable; no Forge credential profile
contained it, and the inspected user/local Claude settings had no such `env` entry (project settings were absent). This
independently reproduces the maintainer's reported paid-key risk in Forge's actual child, while locating the current
injection at CLI dotenv loading rather than the initial tool environment.

| Probe                                                                                     | Result                                                                                                                     |
| ----------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Plain host `claude auth status --json`                                                    | `claude.ai`, `firstParty`, no API-key source; `subscriptionType: max`                                                      |
| After Forge CLI loading and `build_claude_env(direct=True)`                               | Key present; `can_use_bare(child)` true; status with `--bare` reports `api_key`, source `ANTHROPIC_API_KEY`, no plan field |
| Same child with competing auth selectors removed, plus `--restricted --strict-mcp-config` | `claude.ai`, `firstParty`, no API-key source; `subscriptionType: max`                                                      |

The existing runner would therefore choose `--bare` and API-key auth for this **direct** child. This is a concrete local
requirement for B1, not only a hypothetical conflict. It does not prove all Forge subprocesses bill that key: explicit
proxy routes and caller overrides can change selection. The documented non-interactive precedence supports the direct
case; no inference was made to demonstrate a charge.
[Headless authentication precedence](https://code.claude.com/docs/en/authentication)

Isolated probes used a temporary `CLAUDE_CONFIG_DIR`, an untrusted temporary Git project and a synthetic invalid key.
Competing auth selectors were removed from the child environment, then one settings source was populated per case.
Global flags preceded `auth status --json`. This tested status selection without inference:

| Credential source            | Ordinary status | With `--restricted --strict-mcp-config` | With `--setting-sources ''` |
| ---------------------------- | --------------- | --------------------------------------- | --------------------------- |
| No credential                | `none`          | Not tested                              | Not tested                  |
| User settings `env`          | `api_key`       | `none`                                  | `none`                      |
| Explicit `--settings` `env`  | `api_key`       | `api_key`                               | Not tested                  |
| Project/local settings `env` | `none`          | `none`                                  | `none`                      |

User-settings isolation has a positive control; explicit settings still apply under restricted mode. Project/local
results are inconclusive because the ordinary command did not load those sources in the untrusted fixture. B1 must add
trusted positive controls and verify the actual supervisor invocation, managed policy, profiles and gateways. These
probes establish a useful candidate interface, not completion of the auth guard.

### What the cost check establishes

`forge telemetry costs show --period all --json` reported $34.379168 across 597 proxy requests: 572 had reported cost
and 25 had unavailable cost. Its verb summary contained panel work and no supervisor entry. This is retained proxy
telemetry, not proof of historical direct Anthropic charges or their absence. The
[command](../../../../src/forge/cli/proxy_costs.py) reads proxy request records; a direct headless call bypasses that
plane. Per-session `forge telemetry activity <session> --period all` can expose recorded direct automation and billing
classification, but its cost attribution is best-effort. An actual account charge needs provider billing evidence; no
such account history was inspected here.

Jev requests are separately API-billed. Its [epic](../../proposed/epic_jev_support/card.md) is opt-in on projects where
that spend is accepted. The cascade can preserve Claude quota only when it actually avoids a Claude call; warning-only
rule packs do not establish that saving. Measure avoided calls, model/tokens, review quality and latency. Record quota
usage only where the provider exposes usable evidence, alongside Jev's reported cost.

## Existing paid route to smoke-test separately

The bundled [openrouter-openai template](../../../../src/forge/config/defaults/templates/openrouter-openai.yaml) maps
Sonnet and Opus tiers to GPT-6 Astra. The semantic supervisor pins Opus on a proxy route. A Claude Code executor and
supervisor can therefore use that route when configured consistently. Existing saved proxy snapshots can differ from the
packaged template; inspect the realized route before a smoke run. This is existing routing, not a new ticket.

A future opt-in smoke should verify actual executor and supervisor model IDs, ZDR, cited verdict delivery, and provider
usage. It is API-billed. This research does not establish a watermark property for either the models or CLI. The user's
preference to keep Claude-generated wording out of Codex is addressed by the optional source-only feedback design.
