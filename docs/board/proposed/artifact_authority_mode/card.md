# Artifact Authority Mode

**Status**: Proposed (2026-08-13; narrowed after design review). This card covers per-session artifact authority,
handler-level fail-closed decisions on declared runtime-tool surfaces, launch preflight, disclosed runtime fail-open
seams, and an honest posture read. It does not add delegation, cross-runtime context transfer, Git-range attestation,
textual-overlap analysis, or an admission gate. Forge adds no courier; the supported advisory-to-producer flow is
human-only.

**References**: [design.md §3.9](../../../design.md#39-session-resume-context-management) (Codex session lifecycle),
[design.md §3.10](../../../design.md#310-hook-handlers) (managed hook dispatch),
[design_workflows.md §1](../../../design_workflows.md#1-policy-enforcement) (policy boundaries),
[design_appendix.md §I.2](../../../design_appendix.md#i2-codex-runtimespec-declarations) (Codex hook posture),
`src/forge/cli/hooks/commands.py` and `src/forge/cli/hooks/policy.py` (current hook gates), and
`tests/src/install/test_registered_commands_contract.py` (pinned hook matchers). Runtime evidence:
[Claude Code hooks](https://code.claude.com/docs/en/hooks) (catch-all matchers, timeout posture, and `ExitPlanMode`
input) and [Claude Code tools](https://code.claude.com/docs/en/tools-reference) (current tool inventory).

## Motivation

Model selection currently bundles inspection, reasoning, project-artifact byte generation, workspace mutation, review,
and admission, even when a project wants those authorities separated. Organizations may restrict artifact production
because of
[provider content-marking practices](https://support.claude.com/en/articles/16266773-how-claude-marks-ai-generated-content),
output-licensing uncertainty, privacy or data-handling rules, or approved-model policy. Those constraints can change
without making a model unsuitable for planning or review, so Forge assigns authority to sessions rather than permanently
classifying providers. Prompt instructions and workflow convention are not an enforcement boundary: they degrade across
compaction, tool use, and runtime behavior. Forge already uses a policy engine because instructions alone do not hold at
action time; authority mode puts this rule at the same runtime action boundary while leaving final admission with the
human.

## Goal

Give the human operator an explicit, provider-neutral way to assign one of two authority roles to a managed Forge
session:

- an **advisory session** may inspect, reason, plan, and review, but its authority handler denies every runtime-tool
  request covered by its active enforcement tier;
- a **producer session** may mutate its workspace, subject to the ordinary policy and runtime permissions configured for
  that session.

The role belongs to the session, not to a vendor, model, backend, or lane. An unmarked legacy session keeps today's
behavior and carries no artifact-authority claim.

In the supported v1 flow, the human moves requirements and findings between the sessions. Forge preserves each runtime's
own conversation and workspace, but sends no transcript, transfer snapshot, generated patch, or model-curated handoff
between them.

## Definitions and scoped invariant

**Project artifacts** are files beneath the session's recorded checkout root, excluding Forge operational state under
`.forge/` and Git/runtime metadata. Authority events and session manifests are operational records, not project
artifacts.

A **managed run** is a session launched or resumed through Forge with a valid session manifest and a runtime hook seam
that passed the authority preflight for that run. A raw `claude`, `codex`, editor, shell, human process, or other
process outside the managed run is not covered.

A **covered request** is a runtime tool invocation included in the active tier's runtime-specific coverage inventory.
The inventory is code-defined, versioned, and printed by the authority read surface. It is not inferred from prompt text
or from a model's stated intent.

> During a preflighted managed advisory run, an authority handler that receives a covered request and can emit a valid
> runtime decision denies that request. Failure inside that handler to resolve or evaluate the advisory authority guard
> also denies the request. If the required hook registration or enrollment cannot be established before launch, Forge
> refuses to start the advisory run.

This invariant covers Forge's managed runtime-tool boundary only. It does not attest:

- OS-level filesystem immutability;
- semantic independence or absence of advisory influence;
- who authored a commit, file, or hunk;
- whether a human copied advisory output into an artifact;
- fail-closed behavior when the runtime does not deliver the hook, a command hook times out, the dispatcher cannot start
  or execute Forge, or the runtime discards malformed hook output;
- admission, merge, endorsement, or provider-term compliance.

## Session-owned authority state

Authority is session intent, separate from consumer lanes and ordinary policy fail mode:

```yaml
intent:
  authority:
    role: advisory        # advisory | producer
    tier: shell_closed    # advisory only
```

Absence means **unmarked**. `producer` is a positive human designation, not the inferred absence of the advisory bundle.
It authorizes workspace mutation through the managed session but does not claim that every workspace byte came from that
session.

Authority has typed session surfaces:

```bash
forge session start planner --authority advisory --authority-tier shell_closed
forge session start impl --runtime codex --worktree --authority producer

forge session authority show [session] [--json]
forge session authority set <session> --role <advisory|producer> [--tier <tier>]
forge session authority clear <session>
```

`show`, `set`, and `clear` give the subgroup enough distinct leaves to satisfy the CLI command-shape contract. `show` is
read-only and never persists a report.

An omitted tier defaults to `shell_closed` for an advisory role. Supplying a tier for `producer` is an error, and
`clear` removes the complete authority subtree so the session becomes unmarked.

`set`, `clear`, and authority-bearing session-creation flags are human control-plane operations:

- they refuse when invoked from inside a managed agent process (`FORGE_SESSION` is present);
- `set` and `clear` refuse while the target session is active;
- generic `forge session set/reset` rejects `authority` keys;
- v1 exposes no mutating `%authority` direct command.

The human escape hatch is to stop the session, change or clear its role from another terminal, and resume it. The model
cannot disable its own authority guard through an allowed Forge command.

### Derivation and inheritance

- An advisory role is inherited by fresh resumes and forks so a planner or reviewer does not silently regain mutation
  authority after a context reset.
- A producer role is never inherited. A derived session is unmarked until the human explicitly designates it.
- The authority tier is copied only with an inherited advisory role.
- A role supplied explicitly at child creation wins before the first launch and is journaled as an external
  control-plane action.

## Prevention tiers

Authority enforcement runs before ordinary action normalization and before the deterministic/semantic policy engine. It
does not use `intent.policy.fail_mode`; every covered advisory request delivered to a functioning authority handler
receives a deny decision.

| Tier                        | Covered runtime-tool surface                                                                                          |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `named_tools`               | Raw `Write`, `Edit`, `NotebookEdit`, and `apply_patch` requests, including add, update, delete, and rename envelopes  |
| `shell_closed` (v1 default) | `named_tools` plus `Bash`/shell execution and every tool not present in the runtime's explicit non-mutation allowlist |
| `os_readonly`               | Filesystem-enforced read-only advisory checkout; future hardening tier, out of scope                                  |

The v1 `shell_closed` allowlist is deliberately small and separates inspection from conversation/control state:

- Claude inspection: `Read`, `Glob`, `Grep`, `WebFetch`, and `WebSearch`;
- Claude conversation/control state: `AskUserQuestion`, `EnterPlanMode`, `ExitPlanMode`, `ReportFindings`, `TaskCreate`,
  `TaskGet`, `TaskList`, `TaskUpdate`, and legacy `TodoWrite`. These tools do not grant project-artifact mutation;
  `ExitPlanMode` may trigger Forge's existing approved-plan snapshot under `.forge/artifacts/` as operational state;
- Codex: no shell-backed repository inspection. A shell-closed advisory Codex session may reason over context already
  present in the conversation, but its `Bash` and `apply_patch` surfaces are denied;
- unknown, newly introduced, delegation-capable, skill, and MCP tools are denied until explicitly classified.

`Allowlisted` means only that the authority guard declines to deny the call. It never emits a permission-granting
`allow`; runtime permission prompts, user-interaction requirements, and other hooks still apply.

Classification is tool-scoped, not path-scoped. A denied direct-mutation tool remains denied when it targets `.forge/`,
an outside-checkout path, or an absent, malformed, or unnormalizable path; there are no path carve-outs that could
become normalization bypasses. Forge-owned control-plane and lifecycle handlers may write operational state after an
allowed control tool, but the advisory model receives no direct mutation capability for that state.

`named_tools` is a weaker compatibility tier. Its report names `Bash`, delegation tools, MCP tools, and external
processes as uncovered. A tier name never stands in for its printed coverage inventory.

### Hook and launch contract

Authority uses runtime-specific PreToolUse entry points. Claude adds a dedicated catch-all `authority-check`; Codex puts
the raw authority guard at the top of its existing no-matcher `codex-policy-check` command:

1. The launcher validates the authority role and tier, verifies the required hook seam, and stamps a run-owned authority
   marker and configuration digest into the managed runtime environment.
2. Claude's standalone dispatcher recognizes the `authority-check` hook name and tests the launch-owned advisory marker
   before Forge launcher resolution, imports, or CLI execution. Unmarked and producer runs return from that
   authority-only row; their existing `Write`/`Edit` `policy-check` rows still enforce ordinary policy.
3. An advisory handler evaluates the raw tool name and envelope before per-file parsing. A covered request is denied
   even when its payload is malformed or its target path cannot be normalized.
4. In the combined Codex handler, marker/state resolution and the authority guard run before the raw tool-name filter,
   the `policy.enabled` early exit, bundle/supervisor gates, and `CodexHookAdapter`. Claude's dedicated authority
   handler contains no ordinary-policy early exit.
5. Any authority-guard exception, manifest/marker inconsistency, or unreadable authority state denies the request when
   the handler can emit the runtime's valid blocking response.
6. Ordinary TDD, coding-standard, and supervisor policy behavior remains unchanged after the authority-only row or guard
   declines to deny an action.

The launch-owned marker is necessary because the current hooks fail open before ordinary `fail_mode` is available when
the manifest or engine cannot be read. It identifies an already validated advisory run; it is not a user-facing grant
and cannot turn an unmarked run into a producer.

Verified seam changes required by v1:

- **Claude**: installation currently registers `policy-check` only for `Write` and `Edit`, and the handler itself exits
  for every other tool. Authority mode adds the separate `authority-check` registration with an omitted matcher so it
  matches every PreToolUse event, and updates the pinned registration contract while leaving both existing
  `policy-check` rows intact. `ClaudeHookAdapter` remains responsible only for ordinary per-file policy normalization.
- **Codex**: the current PreToolUse registration already has no matcher and its command bytes are covered by Codex
  trust. V1 therefore extends that command instead of adding another registration or changing its dispatcher command.
  The command currently exits unless the tool is `apply_patch`; `CodexHookAdapter` then skips malformed and delete-only
  patches. Authority mode evaluates raw `apply_patch`, `Bash`, and unknown tool envelopes before the tool filter,
  `policy.enabled`, and adapter gates. An advisory Codex launch requires empirically verified hook enrollment; static
  registration alone is insufficient.

## Authority journal and posture read

Authority mode adds one durable record path:

```text
.forge/artifacts/<session>/authority/events.jsonl
```

Forge appends `authority_configured`, `authority_cleared`, `authority_inherited`, `launch_preflight`, `run_started`,
`run_ended`, `request_denied`, and `mutation_refused` events. `mutation_refused` covers syntactically valid,
target-resolved attempts through in-agent, active-target, and generic override surfaces; malformed or unresolved
invocations remain diagnostics rather than an unbounded journal-spam surface.

Each event contains a schema version, timestamp, session, runtime, event type, role, tier, `origin_surface`, outcome,
optional reason code, effective-config SHA-256, hook-registration SHA-256, and the covered tool name when applicable.
Outcome is one of `success`, `denied`, `refused`, `cancelled`, or `error`; the reason code is `null` when it does not
apply. `origin_surface` is a code-defined enum such as `external_cli`, `session_derivation`, `launcher`,
`claude_authority_hook`, or `codex_policy_hook`; it identifies the Forge surface that observed the event, not an
authenticated human identity. The journal stores no tool payload, candidate patch, prompt, or source bytes.

Appends are serialized under a dedicated journal lock and write one complete JSONL record per acquisition.
Configuration, inheritance, or launch-preflight append failures are command or launch errors. Failure to journal a
denied tool request never changes the deny decision and is reported as a diagnostic.

The file is append-only by Forge convention. `shell_closed` protects it from the advisory model; `named_tools` lists
shell mutation of operational state as uncovered. It is not a tamper-proof log and makes no claim against a human or
external process that rewrites local state. For a currently marked session, a missing or manifest-inconsistent journal
yields `configuration_history: unproven`. An unmarked session with no journal uses `null` and makes no claim about
whether history never existed or was removed. Malformed or unreadable journal state is a command error. Absence of
evidence is never upgraded into a continuity claim.

`forge session authority show` derives a current vector rather than an overall badge:

```yaml
authority:
  session: planner
  role: advisory
  tier: shell_closed
  runtime: claude_code
  active: true
  launch_support: verified       # verified | unverified | unsupported | not_running
  configuration_history: supported  # supported | unproven | null
  configured_epoch: {started_at: ..., ended_at: null}
  covered_tools: [Write, Edit, NotebookEdit, apply_patch, Bash, unknown_tools]
  read_only_tools: [Read, Glob, Grep, WebFetch, WebSearch]
  control_tools:
    - AskUserQuestion
    - EnterPlanMode
    - ExitPlanMode
    - ReportFindings
    - TaskCreate
    - TaskGet
    - TaskList
    - TaskUpdate
    - TodoWrite
  observed_denials: {count: 2, first_at: ..., last_at: ...}
  limitations:
    - managed runtime-tool boundary only
    - runtime hook timeout or non-delivery can fail open
    - local journal is not tamper-proof
    - authorship and admission are not attested
```

The JSON shape is stable and contains the same fields for advisory, producer, and unmarked sessions, using `null` or an
empty list where a field does not apply. Missing sessions, invalid state, unreadable manifests, and malformed journals
are command errors. A valid session with an unavailable hook seam is a successful read with
`launch_support: unsupported`; attempting to launch that session as advisory is an error.

`configuration_history: supported` means only that Forge's recorded authority configuration is continuous between its
journaled events. It does not mean that Forge observed every filesystem mutation or every process during that interval.
`launch_support: verified` likewise reports prelaunch evidence only; it does not guarantee that the runtime delivered
every later hook invocation or honored every emitted response.

## Human-courier flow

The planner remains in its original conversation. The human starts an independent producer session in a distinct
worktree and supplies the approved task directly:

```bash
forge session start planner --authority advisory --authority-tier shell_closed

# In another terminal; no --resume-from and therefore no transfer payload.
forge session start impl --runtime codex --worktree --authority producer
```

The second command opens a fresh managed Codex conversation. The human enters the requirements there. Later findings can
be carried to the same producer thread:

```bash
forge session resume impl --task "Revise the parser without adding filesystem I/O."
```

The human may inspect the producer branch from a separate checkout, relay findings to either conversation, and decide
what to commit or merge. Forge neither forwards the planner transcript nor claims to witness final admission.

## Existing foundation

Forge already has the required session composition:

- Claude and Codex managed runtimes;
- fresh interactive Codex sessions and persisted thread continuation;
- worktree-backed sessions and workspace occupancy reads;
- session-owned intent with immutable runtime identity;
- installed PreToolUse hooks and Codex enrollment preflight;
- deterministic policy evaluation and raw runtime hook payloads.

The missing pieces are the session authority state, raw authority guard with handler-level deny-on-error behavior,
launch preflight/marker, journal, and typed session authority surfaces. No producer consumer lane or proxy-level model
switch is required.

## V1 acceptance boundary

01. Advisory launch refuses an absent, unregistered, or unverified authority hook seam.
02. The launch marker is derived only from validated session intent and remains fixed for one managed run.
03. `named_tools` denies complete raw mutation envelopes, including malformed, delete, and rename patches, without
    target path carve-outs.
04. `shell_closed` denies shell, unknown, and non-allowlisted tools; its runtime-specific inventory explicitly
    classifies allowed inspection and conversation/control tools.
05. A delivered authority request is evaluated before tool filtering, `policy.enabled`, ordinary-policy gates, and
    per-file adapters; authority-guard errors deny it independently of ordinary policy fail mode when the handler can
    emit a valid blocking response.
06. Producer and unmarked sessions retain ordinary policy behavior, including the existing Claude `Write`/`Edit` policy
    rows and Codex `apply_patch` policy path.
07. Role assignment or mutation through authority commands, creation flags, active-session targets, in-agent processes,
    and generic overrides follows the human control-plane rules. Every well-formed, target-resolved refusal appends
    `mutation_refused` with its `origin_surface`.
08. The authority journal serializes one complete record per configuration, inheritance, launch-preflight,
    run-lifecycle, denial, and scoped-refusal event, including origin surface and outcome but no prompts, payloads,
    patches, or source bytes.
09. `configuration_history` is derived from the journal; missing or manifest-inconsistent history for a currently marked
    session yields `unproven`, an unmarked session with no journal uses `null` without making a history claim, and
    malformed or unreadable journal state is a command error.
10. `authority show --json` is read-only, stable, and distinguishes configuration history from launch support, including
    the residual runtime fail-open limitation.
11. The Claude `authority-check` no-op path does not resolve, import, or execute Forge for an unmarked or producer run.
    Under `scripts/experiments/hook-dispatcher/benchmark.py` with 50 runs, 40 registry entries, and depth 5, its p95 on
    the reference host remains within the existing
    [30 ms dispatcher ceiling](../../done/forge_hook_dispatcher/checklist.md); the 2026-08-13 remeasurement is 26.7 ms
    p95. Unit tests pin the structural no-resolve/no-import/no-exec behavior rather than a wall-clock ceiling.
12. The documented producer flow creates a distinct worktree and sends no automatic parent context.

## Non-goals

- No `/forge:delegate`, execution packet, automated return loop, or `producer` consumer lane.
- No use of the existing cross-runtime transfer bridge in the authority-mode user flow.
- No Git-range association, per-hunk/model authorship, textual-overlap audit, or persisted attestation report. Those are
  separate provenance questions and require a separate proposal if later needed.
- No commit, merge, or admission gate.
- No provider allow/deny judgments or legal safe-harbor claim.
- No protection from humans, editors, raw runtimes, external processes, or direct filesystem access outside a managed
  run.
- No OS-enforced read-only workspace in v1.

## Risks

- **Runtime hook drift and non-delivery.** Upstream hook firing and blocking responses can change. Validated-version
  guards and empirical Codex enrollment checks refuse known-unavailable advisory launches, but preflight cannot prevent
  a later command-hook timeout, dispatcher loss, or malformed response from following an upstream fail-open path.
- **Reduced advisory utility.** `shell_closed` deliberately removes shell-backed repository inspection, especially for
  Codex. Users who select `named_tools` receive an explicit uncovered-surface report.
- **Catch-all hook overhead.** Claude starts the standalone dispatcher for every PreToolUse event. The authority-only
  marker gate avoids the much larger Forge launcher/import/CLI path for unmarked and producer runs but cannot eliminate
  that initial process spawn. Codex already invokes its no-matcher policy hook for every PreToolUse event, so v1 adds no
  second Codex registration.
- **Operational-state trust.** The local journal records Forge observations but is not tamper-proof evidence.
- **Human carryover.** A human can paste advisory output into the producer conversation or an artifact. Authority mode
  neither detects nor prevents that.

## Resolved during proposal review (2026-08-13)

| Question            | Decision                                                                                                           |
| ------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Dispatch            | Supported flow is human-only; producer starts fresh with no `--resume-from` or automatic transfer                  |
| Authority ownership | Positive per-session `advisory`/`producer` intent, separate from lanes and ordinary policy bundles                 |
| Failure posture     | Handler errors deny; preflight refuses known-bad seams; upstream timeout/non-delivery remains a disclosed gap      |
| CLI shape           | Typed `forge session authority` subgroup (`show`/`set`/`clear`) plus `--authority`/`--authority-tier` launch flags |
| Evidence claim      | Current configuration and launch posture only; no Git-range, authorship, or admission attestation                  |
| Shell posture       | `shell_closed` is the default and denies all shell use; `named_tools` is explicitly weaker                         |
| Role inheritance    | Advisory inherits; producer never inherits                                                                         |
| Provider posture    | Provider-neutral roles; v1 coverage is reported separately for each managed runtime                                |

## Open question

Should the authority role and tier appear in the status line during an active managed session, or is
`forge session authority show` sufficient for v1?
