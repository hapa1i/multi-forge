# Ambient policy scope -- global default-on policies with session opt-out

**Epic**: [epic_budgeted_review_guards](../epic_budgeted_review_guards/card.md) (M0 -- shared substrate).

**Lane**: `proposed/`.

## Goal

Add a second **activation scope** to the policy engine. Today every policy activates session-scoped and opt-in
(`intent.policy.enabled` + bundles); an **ambient** policy activates from global runtime config, applies by default to
every hook-visible session, and is opted out of per session. The policy *type* taxonomy (deterministic / semantic /
verification) is unchanged -- scope answers "who turned it on and who may turn it off", not "what does it check".

Epic decisions D1 (engine integration, not a dedicated handler) and D2 (config home + override precedence) are recorded
in the epic card and are this card's requirements, not open questions.

## Design

- **Config source**: a typed `policy.guards:` section in `~/.forge/config.yaml`. Missing means built-in defaults; a
  present malformed guard section is tracked as invalid and disables ambient guards for that load rather than falling
  back to a potentially blocking built-in default. `forge config set`/`edit` reject unknown keys and bad enums.
- **All-sidecar delivery**: move the existing read-only `config.yaml` bind out of proxy-only audit plumbing and into the
  common sidecar mount path. Proxied and direct-subscription sidecars must resolve the same ambient configuration.
- **Two-source engine construction**: the policy hook builds the engine from ambient guards (runtime config) plus
  session bundles (manifest). `policy.enabled` gates session bundles; ambient guards evaluate unless the explicit
  `ambient_guards_disabled` override is set.
- **Opt-out = session override**: add `policy.disabled_guards: list[str]` and `policy.ambient_guards_disabled: bool`.
  `%policy guard disable|enable <guard>` changes the list. `%policy disable` disables session bundles and sets the
  all-ambient switch; `%policy enable` clears the switch. The global default is global-owned; opt-out is session-owned,
  discoverable, and auditable. Precedence: session override > global config > built-in default.
- **One ambient-mutation op seam**: add UI-agnostic command-core operations for per-guard disable/enable and the
  all-ambient switch. Both `forge policy ...` and `%policy ...` call them. Preserve the existing intentional distinction
  that the terminal enable surface authors bundle intent while the direct command toggles bundle overrides; only the new
  ambient fields are single-sourced here.
- **No-session tolerance**: `ActionContext` construction and the hook must tolerate a missing manifest (bare `claude` in
  an enrolled repo). Ambient guards still evaluate from global config; decision logging degrades -- no `confirmed` to
  write, so stderr plus best-effort telemetry only.
- **Claude fan-out lifecycle hooks**: probe and register the policy-check handler for the actual Skill/Agent PreToolUse
  names. Use the already-registered observe-only `SubagentStop` as the primary completion candidate; probe whether its
  `agent_id` correlates to the launch and whether it fires after failure/cancellation before considering any new
  PostToolUse matcher. PreToolUse admits work; correlated `SubagentStop` lets M2 release an active slot. This is
  Claude-specific; Codex keeps its existing apply-patch vocabulary until a Codex fan-out tool is observed.
- **Persistent invalid-config visibility**: a hook warning is best effort, not the recovery surface.
  `forge extension doctor [--json]` reports the guard section as `missing/defaulted`, `valid`, or `invalid/fail-open`,
  and `forge policy status` reports the same effective/degraded state. A status-line marker is optional follow-up.
- **Fail posture**: config, state, or manifest read errors fail open with a stderr warning (system-boundary rule,
  design_workflows.md section 1.2). A malformed present guard section is not equivalent to a missing section.

## Constraints (verified against current code)

- `policy-check` registers only `Write` and `Edit` PreToolUse matchers today (`src/forge/install/preset.py`); the events
  for Skill/Agent invocations exist but nothing routes them to the engine.
- New matcher rows change the registered-command contract golden
  (`tests/src/install/test_registered_commands_contract.py`, keyed on `(event, matcher, command, timeout)`) and reach
  existing installs only via `forge extension sync`.
- `ClaudeHookAdapter` requires a manifest and only extracts Write/Edit content today; it must accept an optional
  manifest and normalize Claude Skill/Agent payloads. `CodexHookAdapter` remains apply-patch-specific; M0 does not
  invent Codex Skill/Agent vocabulary.
- The current sidecar config mount is inside proxy-id audit plumbing. Direct-subscription sidecars do not receive
  `~/.forge/config.yaml` until M0 moves that bind into the common mount path.
- `SubagentStop` is already registered and its current observe-only handler reads `session_id`, `agent_id`, agent type,
  transcript path, and last message. Correlation to PreToolUse Agent and failure/cancellation delivery are unproven.
- Terminal policy enable/disable mutates intent directly, while `%policy` mutates overrides directly; despite the prior
  supervisor op extraction, these activation leaves do not currently share a command-core op.
- The ownership table in `design_workflows.md` section 1.6 says "policy enabled/disabled is session-owned"; that
  sentence must become scope-aware in the same change.

## Open Questions

- **Actual tool names**: pin the PreToolUse tool-name strings for skill and subagent invocations by probe (they must
  match the runtime's vocabulary across Claude versions) before registering matchers.
- **Operation and `SubagentStop` correlation**: identify the guarded Skill invocation id and Agent parent-operation id;
  prove whether SubagentStop `agent_id` matches the launch and whether it fires for unrelated Agent work, concurrent
  agents, failure/cancellation, Skill completion, and a `/compact` rollover.
- **Ambient-session observability**: what exactly is recorded for a guard decision with no manifest and no run identity
  -- stderr only, or an unattributed upstream outcome?

## Acceptance Criteria

- An ambient guard defined only in `~/.forge/config.yaml` evaluates in a managed session that never enabled any policy
  bundle.
- The same guard evaluates in a hook-dispatched session with no `FORGE_SESSION` (no manifest), from global config alone.
- `%policy guard disable <guard>` suppresses one guard for that session; `%policy guard enable <guard>` restores it.
  `%policy disable` suppresses both ambient and session-bundle policy until `%policy enable`. All states are visible in
  effective session output.
- Terminal `forge policy guard disable|enable`, `forge policy disable`, and `forge policy enable` set/clear the same
  ambient override fields through shared command-core ops as their `%policy` equivalents; existing bundle
  intent-versus-override semantics remain unchanged.
- Session-bundle behavior is byte-identical when no ambient guards are configured (empty `policy.guards` is the golden).
- A missing `policy.guards` section uses defaults; a malformed present section evaluates no ambient guards and warns;
  `forge config set` rejects the same malformed input loudly. This remains true after the built-in default becomes
  blocking.
- `forge extension doctor --json` and `forge policy status` both distinguish missing/defaulted, valid, and
  invalid/fail-open guard configuration with an actionable repair path.
- Direct and proxied sidecars read the same host guard configuration.
- Deny output reuses the engine's three-tier message on Claude and, for ambient policies applicable to `apply_patch`,
  the existing Codex responder. No Codex Skill/Agent support is claimed.
