# Codex Frontend (build)

Status: doing. Spun out of `runtime_abstraction` Phase 6 (evaluation only, closed 2026-06-09).

## Summary

Phase 6 of `runtime_abstraction` evaluated Codex as a Forge frontend runtime and deliberately shipped **no product
code** -- only a probe harness (`scripts/experiments/codex-hooks/`) and a decision record (the `runtime_abstraction`
checklist Phase 6 block, codex-cli 0.138.0). This card is the build work that evaluation gated.

The Phase 6 probe's load-bearing finding was: **Codex hooks do not fire under headless `codex exec`** (0 firings across
all registration surfaces, with `--dangerously-bypass-hook-trust`, on repeated same-home runs).

**Gating probe round 2 (2026-06-10, operator-guided stages 40+50, codex-cli 0.138.0) refined that finding decisively:
hooks DO fire under headless `codex exec` once the hook is trust-enrolled — headless just cannot *self-enroll*.** One
interactive trust grant in the TUI flipped the same project hook from 0 firings (40a/40b) to firing on every subsequent
headless turn (40c2, 40d), with artifact-grade attribution (`permission_mode:"bypassPermissions"` = exec, vs the
interactive capture's `"default"`; rollout timestamps match the headless turns). Interactive firing is also confirmed
(50c). So the hook-dependent deliverables are live, gated now on *enrollment mechanics*, not on firing capability.

## Probe-established facts (do not re-derive)

From the Phase 6 decision record + `scripts/experiments/codex-hooks/`:

- **Untrusted hooks do not fire under `codex exec`** (5 clean isolated confirmations, Phase 6): neither plain, nor with
  `--dangerously-bypass-hook-trust`, nor with config `[projects."<proj>"] trust_level = "trusted"` (40b, round 2).
- **`codex exec resume <thread_id>` works and is cross-CWD** (unlike Claude's CWD-bound `--resume`); `--json` composes
  (options before the `resume` subcommand); id = stream `thread_id`; `--last` is unreliable headless.
- **Hook payload shape is snake_case as documented**:
  `{session_id, transcript_path, cwd, hook_event_name, model, permission_mode, source}`. The payload carries the
  `session_id` AND the rollout `transcript_path` directly -- ideal for `confirmed` manifest wiring.
- **Registration validation is shallow**: required inner fields are validated, but unknown fields and **bogus event
  names load silently** -- a Forge installer must validate event names itself.
- **Session/rollout files**: `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<ts>-<session_id>.jsonl` (filename embeds the
  session id -- discoverable for a `confirmed` manifest field). `FORGE_SESSION` reaches the model shell. First-run
  plugin-marketplace clone into `$CODEX_HOME/.tmp/plugins`.

Gating probe round 2 (2026-06-10, stages 40+50 run with a TTY operator; captures were at
`~/.cache/forge-codex-hooks-probe/`, evidence quoted here):

- **Trust-enrolled hooks fire headless** (THE flip): after one interactive TUI session in the project accepted trust,
  the same project-local SessionStart hook fired on both subsequent headless `codex exec` turns (40c2, 40d). Headless
  policy enforcement and SessionStart transfer injection are therefore *possible* on `codex exec` -- the gate is a
  one-time trust enrollment, not the execution mode.
- **Interactive hook firing is CONFIRMED** (50c): a user-level (`$CODEX_HOME/config.toml`) SessionStart hook fired
  during a TUI session launched with a positional initial prompt (the positional arg works), payload
  `permission_mode:"default"`.
- **Trust state lives in the user `config.toml`** as plain TOML, written by the TUI trust flow:
  `[hooks.state."<abs-path-of-registering-config>:session_start:0:0"]` with `trusted_hash = "sha256:..."`. Keyed by
  (registering config path, snake_case event, entry indices) -- NOT stored in sqlite, NOT in the project. The hash
  preimage is unknown (open question below).
- **Trust survives hook-script content change** (40d): appending to the registered wrapper script did not stop firing.
  The `trusted_hash` covers the registration *definition*, not the executable's bytes -- good for Forge upgrades (the
  `forge hook ...` command string stays stable), security-relevant for the installer story (a trusted hook's executable
  can be silently swapped). The registration-string dimension (changing `command` itself) is still unprobed.
- **`FORGE_SESSION` reaches the hook env** (50c interactive capture: `FORGE_SESSION=probe-fs-xyz` in the hook's env) --
  hooks can locate the Forge session manifest exactly as Claude hooks do. Ambient env passthrough to hooks also holds
  headless (40c2 env capture).
- **`permission_mode` discriminates execution mode** in the payload: `"bypassPermissions"` on `codex exec` turns vs
  `"default"` in the TUI (single observation each -- a lead for the adapter, not yet a pinned contract).
- **Payload fixtures are now capturable headless**: an enrolled home fires reproducibly, so the Phase 6 "fixtures need
  the interactive path" descope rationale is obsolete -- one enrollment ceremony, then headless capture.
- **`--ephemeral` negative control**: no session rollout is created (only sqlite WAL noise) -- maps cleanly to
  incognito-style sessions.

## Deliverables (verdicts carried from the decision record)

1. **One-command bridge CLI (GO -- build first).** A `forge`-surface frontend over the shipped `bridge_session_to_codex`
   core op (`core/ops/codex_bridge.py`): e.g. `forge session start --runtime codex --resume-from <claude-session>`
   (exact shape TBD). No hook dependency. Needs: a `runtime` field on the session manifest
   (`SessionIntent`/`SessionConfirmed`), a runtime-aware dispatch in the launcher (today hard-wired to `invoke_claude`),
   and hook-free recording of the Codex `thread_id` (resume id) from the `thread.started` JSONL event. Rollout path
   recording must stay honest about its source: derive it separately by discovering the matching
   `$CODEX_HOME/sessions/.../rollout-*.jsonl`, or populate it from the SessionStart hook only when the home is
   trust-enrolled. Use `codex exec resume <thread_id>` for multi-turn continuation. Also: GC the synthetic
   `<parent>-codex-<suffix>` transfer children the bridge accumulates (recorded debt from Phase 5e).

2. **Gating probe -- ANSWERED 2026-06-10 (firing), reshaped to enrollment mechanics.** The original go/no-go ("do hooks
   fire at all?") is settled: GO -- interactive fires (50c) AND trust-enrolled headless fires (40c2/40d). The remaining
   probe work, now about *enrollment*, all of it runnable headless from one enrolled fixture home:

   - **`trusted_hash` preimage**: what exactly does Codex hash -- the TOML entry bytes, the command string, a canonical
     struct? If Forge can compute it, the installer can pre-enroll its own hooks by writing both the registration and
     the `[hooks.state]` record (decide the posture deliberately: pre-enrolling programmatically bypasses Codex's review
     gate -- same trust model as Forge writing Claude's `settings.json`, but make it an explicit decision). If not
     computable/stable, the product story is a one-time guided `codex` trust ceremony per hook change.
   - **Event coverage post-enrollment**: only SessionStart has fired. Re-run stages 20/30 (payloads + response
     contracts, incl. the 30e `additionalContext` magic-token oracle and PreToolUse deny/`updatedInput`) in an enrolled
     home -- now possible headless. Policy on `codex exec` fan-out workers hangs on PreToolUse here.
   - **Registration-string trust dimension** (the 40e gap): change the registered `command` string and confirm trust
     invalidates (40d only proved script-*content* changes survive).
   - **User-level vs project-level trust**: 50c's user-level hook fired interactively but its home died with the run --
     where (and whether) its trust record lands is unobserved.
   - **Harness note**: mktemp-per-run kills enrollment with the run. The follow-up probe needs a *stable* project path
     and a persistent enrolled `CODEX_HOME` fixture (the existing 40-trust persistent-home pattern, minus the teardown)
     so one ceremony serves many headless probe turns.
   - Once enrollment semantics are pinned, encode them in `codex_preflight.py`'s `hook_seam` (today `enrollment_gated`
     -- a capability statement, not a per-home enrolled-state verdict, per the Phase 0 rename; it can now learn to read
     `[hooks.state]` and report enrolled-vs-not per hook).

3. **Codex hook adapter/responder (gated on probe 2's response-contract leg).** `CodexHookAdapter`/`CodexHookResponder`
   filling the runtime-neutral protocols in `src/forge/cli/hooks/protocols.py` (the Phase 4f seam already makes room).
   Map the snake_case payload -> `ActionContext`; serialize decisions to Codex's response wire (deny/`updatedInput`/
   PermissionRequest `decision.behavior` -- contracts to pin in probe 2, now headless-runnable). Broader coverage
   target: PreToolUse + PermissionRequest + Stop + UserPromptSubmit. Carry the **`ActionContext.runtime` -> `origin`
   rename** here (the adapter is its first real consumer; direction resolved in the `runtime_abstraction` Open Decisions
   2026-06-09 -- values `{forge_cli, claude_code, codex}`; do NOT add a `subject_runtime` axis). **Registry correction
   owed (2026-06-10):** `native_hooks="headless_inert"` is now refuted by the binary -- hooks fire headless once
   trust-enrolled. The honest encoding is enrollment-gated (e.g. a `trust_enrolled` literal or re-scoped `gated`
   semantics) and `pretool_policy` can rise from `"none"` only when PreToolUse firing + deny are pinned post-enrollment.
   Land the registry+design.md+tests correction with this card's first code commit.

4. **SessionStart curated-transfer delivery with initial-message fallback (gated on probe 2's 30e leg).** Now viable for
   BOTH the interactive frontend AND the headless bridge (enrolled homes fire headless -- the Phase 6 "headless stays
   initial-message permanently" is softened to "initial-message is the zero-setup default; hook delivery is the
   post-enrollment upgrade"). Build once the 30e `additionalContext` magic-token oracle passes in an enrolled home.

5. **Interactive Codex frontend (unblocked 2026-06-10: interactive firing confirmed).** Forge-managed interactive
   `codex` sessions: `install_scopes` for Codex config (today `()` on the RuntimeSpec), flip
   `interactive="beta" -> ...`, FORGE_SESSION wiring (verified to reach BOTH the model shell and the hook env),
   positional initial-prompt arg (verified), session-id + rollout-path capture into `confirmed` (both carried in the
   SessionStart payload).

6. **Installer Codex support (gated on 3/5).** The installer is Claude-shaped: 13 Claude hook names are hardcoded in
   `src/forge/install/preset.py` and it writes only `.claude/`. Installing Forge hooks into Codex needs a Codex preset
   (`~/.forge/codex.preset.json`?) + a Codex registration target (`$CODEX_HOME`/project `.codex/`), with installer-side
   **event-name validation** (the binary won't catch typos) and a per-hook-trust story.

7. **App-server transport (deferred, unevaluated).** `codex app-server`/`--stdio` as a long-lived RPC alternative to
   one-shot `codex exec` for resumed multi-turn sessions. Not probed in Phase 6; spike only if multi-turn `exec resume`
   proves clumsy.

## Risks / open questions

- **The `trusted_hash` preimage may be uncomputable or version-unstable.** If Forge cannot write valid `[hooks.state]`
  records, every hook install/change costs the user an interactive trust ceremony -- survivable (one-time) but a real UX
  tax; the installer story (6) hinges on this.
- **Pre-enrolling trust programmatically is a posture decision, not just a capability.** Writing another tool's trust
  store to bypass its review gate needs an explicit, documented decision (precedent: Forge already writes Claude's
  `settings.json` hooks with user consent) -- and could break if Codex hardens the store.
- **Trust keys on the registering config's absolute path** (`<path>:<event>:<idx>:<idx>`): moving/recreating a project
  (worktrees!) likely invalidates enrollment; sidecar/container paths diverge from host paths. Probe before relying on
  enrollment surviving Forge's worktree workflows.
- **Only SessionStart has been observed firing.** PreToolUse/Stop/UserPromptSubmit/PermissionRequest post-enrollment
  behavior is extrapolated, not pinned -- the policy deliverable (3) rests on the unprobed events.
- **Codex version churn**: 0.137.0 -> 0.138.0 mid-evaluation; re-run the probe on Codex bumps (the harness is the
  standing guard). Trust/enrollment semantics are exactly the kind of behavior a minor release changes.
- **`allow_managed_hooks_only`** (enterprise `requirements.toml`) can still suppress user/project hooks regardless of
  enrollment.
- **`fallbackModel`/model drift**: a Codex usage event's `model` must be the actually-routed model (already handled for
  the headless emitter; revisit for any interactive path).
