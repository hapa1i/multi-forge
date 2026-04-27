# Forge Team Orchestration — Design Sketch

**Status**: Draft (updated for Claude Code v2.1.x, 2026-03-05).

**Prerequisite**: Claude Code native [Agent Teams](https://code.claude.com/docs/en/agent-teams) (experimental). Changes
in this revision assume Claude Code v2.1.69+.

**References**: design.md §3.10 (hooks), §4.1.2 (reactive patterns), §3.1 (multi-proxy workflow)

**Tag convention**: `[VERIFY]` = upstream feature exists (per release notes) but its behavior in our specific use case
(e.g., teammate identity in PreToolUse) needs empirical testing. `[NOT IMPLEMENTED]` = upstream capability Forge doesn't
use yet.

---

### What Forge Implements Today

Before diving into upstream changes and future directions, here's what Forge has built and tested:

| Capability                            | Status            | Details                                                                      |
| ------------------------------------- | ----------------- | ---------------------------------------------------------------------------- |
| `TeammateIdle` quality gate           | Implemented       | Tagger + optional supervisor, two outcomes                                   |
| `TaskCompleted` quality gate          | Implemented       | Tagger + supervisor + escape hatch, two outcomes                             |
| Cross-team supervisor                 | Implemented       | `claude -p --resume`, structured JSON verdict                                |
| File-backed cache                     | Implemented       | `~/.forge/team-hooks/<session_id>.json`, 0.2s lock                           |
| Handler contract                      | `tuple[int, str]` | exit 0 = allow, exit 2 + stderr = block                                      |
| Teammate termination (JSON response)  | Not implemented   | Upstream supports it (v2.1.69); Forge handlers return `tuple[int, str]` only |
| Worktree lifecycle hooks              | Not implemented   | `WorktreeCreate`/`WorktreeRemove` exist upstream                             |
| HTTP hook deployment                  | Not implemented   | Upstream supports HTTP hooks (v2.1.63)                                       |
| Per-role PreToolUse enforcement       | Not implemented   | `agent_id` in hooks `[VERIFY]` — unclear if it identifies teammates          |
| `last_assistant_message` optimization | Not implemented   | Forge Stop uses transcript snapshots; field available upstream (v2.1.47)     |

---

## 1. Native Teams: What They Provide and What They Don't

Claude Code Agent Teams coordinate multiple Claude Code instances with shared tasks and inter-agent messaging. Forge
does not replace this coordination — it augments it with multi-model routing, quality gates, and cross-team supervision.

### What native teams provide

| Capability                   | Detail                                                       |
| ---------------------------- | ------------------------------------------------------------ |
| Separate Claude instances    | Each teammate has its own context window                     |
| Messaging                    | Automatic delivery, direct teammate-to-teammate, broadcast   |
| Shared task list             | File-locked claiming, dependency auto-unblock                |
| Plan approval                | Teammates can be put in plan mode; lead approves/rejects     |
| Delegate mode                | Lead restricted to coordination-only tools (Shift+Tab)       |
| Per-teammate model selection | Lead specifies tier per teammate ("Use Sonnet for this one") |
| Display modes                | In-process (Shift+Up/Down) or split-pane (tmux/iTerm2)       |

### What native teams do NOT provide

| Constraint                           | Impact                                                                                                                                                                                                                                                                       |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Shared `ANTHROPIC_BASE_URL`          | All teammates hit the same proxy — 3-model max (one per tier)                                                                                                                                                                                                                |
| Shared `FORGE_SESSION`               | Single session manifest per worktree in team mode. Hooks resolve via env var / index / scan fallback — all land at the same manifest. `agent_id`/`agent_type` (v2.1.69) may provide per-role identity in hook events `[VERIFY]`, but the shared manifest constraint remains. |
| Shared working directory             | File conflicts possible. `isolation: "worktree"` exists for Agent-tool subagents (v2.1.49); unclear if it applies to teammates `[VERIFY]`.                                                                                                                                   |
| No per-teammate permissions at spawn | All teammates inherit lead's permission mode                                                                                                                                                                                                                                 |
| No session resumption                | In-process teammates not restored on `/resume`                                                                                                                                                                                                                               |

### Team-specific hooks (identity available)

Two hooks carry teammate identity, enabling per-role checks at task/idle boundaries:

| Hook            | Payload fields                          | Outcomes (Forge)                           | Outcomes (upstream v2.1.69)                                 |
| --------------- | --------------------------------------- | ------------------------------------------ | ----------------------------------------------------------- |
| `TeammateIdle`  | `teammate_name`, `team_name`            | exit 0 (allow) / exit 2 (continue working) | + `{"continue": false, "stopReason": "..."}` stops teammate |
| `TaskCompleted` | `teammate_name`, `team_name`, `task_id` | exit 0 (allow) / exit 2 (task stays open)  | + `{"continue": false, "stopReason": "..."}` stops teammate |

Standard hooks (`PreToolUse`, `PostToolUse`, `Stop`) also fire on teammates but carry only `session_id` — no
`teammate_name`. v2.1.69 added `agent_id` and `agent_type` to hook events; whether these identify teammates in standard
hooks needs verification `[VERIFY]`.

### Other hooks relevant to teams (v2.1.47+)

| Hook                                 | Version | Relevance                                                                |
| ------------------------------------ | ------- | ------------------------------------------------------------------------ |
| `WorktreeCreate` / `WorktreeRemove`  | v2.1.50 | Auto-setup sessions in new agent worktrees. Not handled by Forge.        |
| `InstructionsLoaded`                 | v2.1.69 | Dynamic team instruction injection when CLAUDE.md loads. Not handled.    |
| `Stop` with `last_assistant_message` | v2.1.47 | Simpler verification input — no transcript parsing needed. Not used yet. |

**Concurrency constraint**: All teammates share `FORGE_SESSION`, so concurrent hook firings contend on the session
manifest file lock. Team hook handlers read the manifest for config but avoid per-event writes to `forge.session.json` —
they use a separate cache file at `~/.forge/team-hooks/` instead.

**Corrected from earlier findings**: The 2026-02-06 empirical test misinterpreted `backendType: "in-process"` as a
shared-process execution model. It's a display mode. Teammates are "separate Claude Code instances" with own context
windows.

---

## 2. Forge's Role

Forge does not manage team lifecycle. Native teams handle coordination (messaging, tasks, plan approval). Forge adds:

1. **Proxy tier mapping**: The lead's `ANTHROPIC_BASE_URL` points to a Forge proxy. Native tier selection
   (`sonnet`/`haiku`/`opus`) maps to different backend models via the proxy's template (e.g., opus → o3, sonnet → Claude
   Opus, haiku → Gemini Flash). All teammates inherit this proxy. Already built — no team-specific code needed.

2. **Quality gate hooks**: `TeammateIdle` and `TaskCompleted` handlers using the shared reactive library (design.md
   §4.1.2). Per-role checks keyed on `teammate_name`. Two outcomes today (allow / block); upstream supports a third
   (stop teammate) — see §4.

3. **Cross-team supervisor**: A `claude -p --resume` session with its own proxy, watching all teammate events for plan
   adherence. The key differentiator — see §3.

4. **CLAUDE.md generation**: Topology templates that produce team instructions (role descriptions, model-to-tier
   assignments, quality gate rules). Lightweight — template string substitution, not a framework. The
   `InstructionsLoaded` hook (v2.1.69) could make this dynamic (inject context when CLAUDE.md loads) rather than static
   — see Open Questions.

5. **Worktree lifecycle** (aspirational): `WorktreeCreate`/`WorktreeRemove` hooks could auto-initialize child sessions
   in new agent worktrees and archive artifacts on removal. Not implemented — see §5.

6. **HTTP hook deployment** (future consideration): v2.1.63 added HTTP hooks (POST JSON to URL, receive JSON response).
   Could replace shell command hooks for team scenarios where concurrent teammates cause subprocess overhead. Not a
   current direction — see Open Questions.

---

## 3. Cross-Team Supervisor

The supervisor is a Forge-managed `claude -p --resume` invocation that evaluates teammate work against the approved
plan. It runs **outside** the native team — its own proxy, its own context.

### Current implementation (two outcomes)

```
TeammateIdle / TaskCompleted hook fires
        |
        v
  forge hook teammate-idle / task-completed
        |
        v
  Tagger (cheap LLM, via core.llm — classify event)
        |  tags: needs-review | routine | trivial
        |
        +-- "needs-review" --> Supervisor session
        |       |
        |       +-- aligned   --> allow (exit 0)
        |       +-- divergent --> block + feedback (exit 2)
        |
        +-- "routine"      --> allow (exit 0)
        +-- "trivial"      --> allow (exit 0)
```

### Future: third outcome (upstream capability) `[NOT IMPLEMENTED]`

v2.1.69 supports `{"continue": false, "stopReason": "..."}` to stop a teammate entirely. Adding this to the supervisor
would require changing the handler contract from `tuple[int, str]` to a richer response type that can emit JSON output
instead of exit codes. This enables a three-way decision:

- **allow** (exit 0): Teammate goes idle / task marked complete
- **block** (exit 2): Teammate continues working / task stays open, feedback sent
- **stop** (JSON response): Teammate terminated — for severe plan divergence or safety violations

**Supervisor session**:

- Invoked via `claude -p --resume <planner_session_id>` (inherits plan context without RAG)
- Own `ANTHROPIC_BASE_URL` pointing to a cheap high-context proxy (e.g., Gemini via `litellm-gemini-local`)
- Minimal JSON verdict (`{verdict, confidence, feedback}` — parsed via `extract_json_from_response()`)
- File-backed cache + throttle window (`~/.forge/team-hooks/<session_id>.json`, timestamp-based freshness)
- Fail-open on errors (same pattern as existing supervisor)

**Per-role evaluation**: The prompt includes `teammate_name` from the hook payload:

> "The **executor** completed task 'Implement auth middleware'. Evaluate whether this work aligns with the approved
> plan. Focus on: did the executor follow the specified approach? Were the right files modified? Were tests included?"

If `agent_id`/`agent_type` become available in hook payloads `[VERIFY]`, the supervisor prompt can include richer agent
identity context beyond just the teammate name.

**Potential optimization**: The `last_assistant_message` field in Stop/SubagentStop hooks (v2.1.47) provides the
teammate's final response text directly in the hook payload. This could be injected into the supervisor prompt as
additional evidence, avoiding the need to open transcripts for context about the teammate's last action.

The tagger makes supervision cost-effective at team scale. Instead of checking every event (N teammates x M events),
only "needs-review" events escalate to the full supervisor session.

**Tag taxonomy note**: The team tagger uses event-level tags (needs-review | routine | trivial). The policy tagger
(design.md §4.1.2) uses code-change tags (bug-fix | refactor | architectural | new-pattern | test | docs). Same
`tag_action()` utility, different prompts. Tag taxonomies are per-caller, not shared.

---

## 4. Quality Gate Hooks

Two hook handlers, both plain Python functions importing from the shared reactive library. Handler contract:
`tuple[int, str]` — exit code + stderr feedback.

### `forge hook teammate-idle`

Triggered by Claude Code's `TeammateIdle` event. Receives `teammate_name`, `team_name` on stdin.

```python
def handle_teammate_idle(data, config, cache) -> tuple[int, str]:
    teammate = data.get("teammate_name") or "unknown"
    team = data.get("team_name") or "unknown"

    tag = _classify_event(config.tagger_model, IDLE_TAGGER_PROMPT, teammate, team)
    if tag != "needs-review":
        return 0, ""

    if not config.resume_id:
        return 0, ""

    exit_code, feedback = _run_supervisor(config, teammate, team, "idle", "")
    return exit_code, feedback  # 0="" or 2="feedback"
```

### `forge hook task-completed`

Triggered by Claude Code's `TaskCompleted` event. Receives `teammate_name`, `team_name`, `task_id`, `task_subject`.

```python
def handle_task_completed(data, config, cache) -> tuple[int, str]:
    teammate = data.get("teammate_name") or "unknown"
    task_id = data.get("task_id") or "unknown"

    # Escape hatch: auto-allow after max_blocks_per_task
    if cache.get(f"{teammate}:{task_id}", {}).get("block_count", 0) >= config.max_blocks_per_task:
        return 0, ""

    tag = _classify_event(...)
    if tag != "needs-review":
        return 0, ""

    exit_code, feedback = _run_supervisor(...)
    # Track block count for escape hatch
    return exit_code, feedback
```

Both handlers use shared reactive library utilities (`run_claude_session`, `extract_json_from_response`,
`lookup_proxy_base_url`) plus a local `_classify_event()` that calls `SyncAdapter(get_client(model))` for cheap tagger
LLM calls. Throttling uses a file-backed dict with timestamp freshness — not `ThrottleCache`.

**Operational constraints**:

- **Idempotency**: Cache by `teammate:task_id` to avoid re-spending tokens on re-fires
- **Timeouts**: Supervisor call must complete within hook timeout (60s); warn-only after timeout
- **Escape hatch**: Max blocks per task (default 3) — after that, allow with warning
- **Feedback channel**: Exit code 2 sends stderr text as feedback to the teammate (per Claude Code hook contract)

### Future: Three-outcome model `[NOT IMPLEMENTED]`

v2.1.69 supports `{"continue": false, "stopReason": "..."}` as a hook response to stop a teammate entirely. Adopting
this in Forge requires:

1. New response type (beyond `tuple[int, str]`) that can express allow / block / terminate
2. Updated CLI plumbing in `commands.py` to emit JSON output instead of exit codes for the terminate case
3. Policy for when termination is appropriate — it's irreversible within the current team run

### Future: Per-role PreToolUse enforcement `[VERIFY]`

v2.1.69 added `agent_id` and `agent_type` to hook events. If these fields identify teammates in `PreToolUse` events (not
just Agent-tool subagents), Forge's existing `policy-check` hook could apply role-specific policy bundles:

```python
# Sketch — depends on agent_id identifying teammates in PreToolUse
def policy_check(event: dict) -> None:
    agent_id = event.get("agent_id")
    if agent_id and is_teammate(agent_id):
        role = resolve_role(agent_id)  # executor, reviewer, etc.
        bundles = role_bundles.get(role, default_bundles)
        # Apply role-specific TDD/coding_standards enforcement
```

This requires empirical verification — see Open Questions §6 Q5.

---

## 5. Worktree Lifecycle Hooks (Aspirational)

`WorktreeCreate` and `WorktreeRemove` hooks (v2.1.50) fire when Claude Code creates or removes agent worktrees
(currently for Agent-tool subagents via `isolation: "worktree"`).

**Potential Forge integration**:

- **WorktreeCreate**: Auto-initialize a child session manifest in the new worktree, copy proxy config from parent,
  ensure hooks are installed in the new `.claude/` directory.
- **WorktreeRemove**: Archive the child session's artifacts (transcript, plan snapshots) back to the parent session
  before the worktree is deleted.

**Relationship to teams**: If teammates gain worktree isolation (currently unconfirmed `[VERIFY]`), this becomes the
session-per-teammate mechanism. Each teammate would get its own session manifest in its own worktree, resolving the
shared-manifest contention problem.

Not implemented. No hook handlers registered. No timeline.

---

## 6. Open Questions

1. **Topology as code**: Should topology definitions (role→tier mappings, CLAUDE.md templates) live in
   `.forge/topologies/` (project-local), `~/.forge/team-topologies/` (user-global), or both?

2. **Cost visibility**: Teams amplify token spend. Should Forge track per-teammate token usage? Requires proxy-level
   counting (not yet implemented). `agent_id` in hook events could help correlate proxy logs with specific teammates if
   the ID is stable.

3. **Forge-managed supervisor sessions**: Currently, `claude -p --resume` calls in the supervisor are naked subprocesses
   — no Forge session manifest is created. Should the cross-team supervisor get its own Forge session for cost
   attribution and configurability? HTTP hooks (v2.1.63) add an alternative: supervisor as a local HTTP server instead
   of a subprocess chain.

4. **`PreToolUse` per-role enforcement**: Downgraded from "blocked on upstream" to "needs verification." v2.1.69 added
   `agent_id`/`agent_type` to hook events — if these identify teammates in PreToolUse, per-role TDD enforcement is
   feasible. Previously blocked on upstream Claude Code changes; now blocked on empirical verification.

5. **`agent_id` scope and stability** `[VERIFY]`: Does `agent_id` appear in PreToolUse/PostToolUse events for
   teammate-triggered actions (not just Agent-tool subagents)? Is the ID stable across a teammate's lifetime? Does it
   correlate with `teammate_name`? **Verification procedure**: Start a team, install a PreToolUse hook that logs the
   full event payload to a file, check for `agent_id` in teammate-triggered events.

6. **HTTP hooks vs command hooks**: v2.1.63 added HTTP hooks (POST JSON to URL, receive JSON response). For team
   scenarios with many concurrent teammates, HTTP may reduce subprocess overhead and file lock contention (server
   handles state in memory). Tradeoff: requires a running server process.

7. **`InstructionsLoaded` for dynamic team context**: Should Forge use the `InstructionsLoaded` hook (v2.1.69) to inject
   team-specific instructions dynamically, replacing static CLAUDE.md generation? Tradeoff: dynamic injection is more
   flexible but adds hook latency on every CLAUDE.md load.

8. **Three-outcome implementation**: When/if to extend the handler contract from `tuple[int, str]` to support teammate
   termination via `{"continue": false, "stopReason": "..."}`. Depends on whether the use case (severe divergence,
   safety violations) justifies the additional complexity.

---

## 7. v2.1.x Changelog Impact Reference

| Version    | Change                                                                            | Team Impact                                | Status                   |
| ---------- | --------------------------------------------------------------------------------- | ------------------------------------------ | ------------------------ |
| v2.1.47    | `last_assistant_message` in Stop hooks                                            | Simpler verification / supervisor input    | Not used                 |
| v2.1.47–69 | Memory leak fixes (conversation pinning, hook event accumulation, task retention) | Long-running team stability improved       | Upstream fix             |
| v2.1.49    | `isolation: "worktree"` for subagents                                             | Potential per-teammate worktree isolation  | `[VERIFY]` for teammates |
| v2.1.50    | `WorktreeCreate`/`WorktreeRemove` hooks                                           | Session auto-setup in new worktrees        | Aspirational             |
| v2.1.63    | HTTP hooks                                                                        | Alternative to shell command hooks         | Open question            |
| v2.1.69    | `agent_id` + `agent_type` in hook events                                          | Per-role PreToolUse enforcement possible   | `[VERIFY]`               |
| v2.1.69    | TeammateIdle/TaskCompleted JSON response                                          | Three-outcome model (allow / block / stop) | Not implemented          |
| v2.1.69    | `InstructionsLoaded` hook                                                         | Dynamic team instruction injection         | Open question            |
| v2.1.69    | `${CLAUDE_SKILL_DIR}` variable                                                    | Portable resource paths in skill files     | Informational            |
