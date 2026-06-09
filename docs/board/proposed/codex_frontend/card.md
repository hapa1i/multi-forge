# Codex Frontend (build)

Status: proposed. Spun out of `runtime_abstraction` Phase 6 (evaluation only, closed 2026-06-09).

## Summary

Phase 6 of `runtime_abstraction` evaluated Codex as a Forge frontend runtime and deliberately shipped **no product
code** -- only a probe harness (`scripts/experiments/codex-hooks/`) and a decision record (the `runtime_abstraction`
checklist Phase 6 block, codex-cli 0.138.0). This card is the build work that evaluation gated.

The probe's load-bearing finding reshapes the build: **Codex hooks do not fire under headless `codex exec`** (0 firings
across all registration surfaces, with `--dangerously-bypass-hook-trust`, on repeated same-home runs). So every
hook-dependent deliverable is either headless-impossible or gated on an unverified interactive-firing capability. The
one clearly-shippable piece is the bridge CLI, which needs no hooks.

## Probe-established facts (do not re-derive)

From the Phase 6 decision record + `scripts/experiments/codex-hooks/`:

- **Headless `codex exec` delivers no hooks** (5 clean isolated confirmations). Headless policy enforcement and
  SessionStart transfer injection are therefore not available on `codex exec`.
- **`codex exec resume <thread_id>` works and is cross-CWD** (unlike Claude's CWD-bound `--resume`); `--json` composes
  (options before the `resume` subcommand); id = stream `thread_id`; `--last` is unreliable headless.
- **Hook payload shape is snake_case as documented**:
  `{session_id, transcript_path, cwd, hook_event_name, model, permission_mode, source}`. Capturing payloads reliably
  needs the interactive path.
- **Registration validation is shallow**: required inner fields are validated, but unknown fields and **bogus event
  names load silently** -- a Forge installer must validate event names itself.
- **Session/rollout files**: `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<ts>-<session_id>.jsonl` (filename embeds the
  session id -- discoverable for a `confirmed` manifest field). `FORGE_SESSION` reaches the model shell. First-run
  plugin-marketplace clone into `$CODEX_HOME/.tmp/plugins`.
- **Interactive hook firing is UNVERIFIED** -- requires a TTY operator session (`codex` refuses non-TTY stdin; a pty via
  `script` starts the TUI but it needs real terminal interaction). This is this card's first gating probe.

## Deliverables (verdicts carried from the decision record)

1. **One-command bridge CLI (GO -- build first).** A `forge`-surface frontend over the shipped `bridge_session_to_codex`
   core op (`core/ops/codex_bridge.py`): e.g. `forge session start --runtime codex --resume-from <claude-session>`
   (exact shape TBD). No hook dependency. Needs: a `runtime` field on the session manifest
   (`SessionIntent`/`SessionConfirmed`), a runtime-aware dispatch in the launcher (today hard-wired to `invoke_claude`),
   and recording the Codex `thread_id` (resume id) + rollout path into `confirmed`. Use `codex exec resume <thread_id>`
   for multi-turn continuation. Also: GC the synthetic `<parent>-codex-<suffix>` transfer children the bridge
   accumulates (recorded debt from Phase 5e).

2. **First gating probe: interactive hook firing.** Run `scripts/experiments/codex-hooks/` stages 40 + 50 from a real
   terminal (the operator-guided steps) to settle: do hooks fire in interactive `codex`? where does trust state live?
   what is the initial-prompt arg? Capture real payloads per event for fixtures. **All of (i)/(ii)/(iv) depend on a GO
   here.** If interactive also does not fire, Codex-frontend policy + hook-based transfer are dead on this Codex line
   and this card reduces to the bridge CLI (1) alone.

3. **Codex hook adapter/responder (gated on probe 2).** `CodexHookAdapter`/`CodexHookResponder` filling the
   runtime-neutral protocols in `src/forge/cli/hooks/protocols.py` (the Phase 4f seam already makes room). Map the
   snake_case payload -> `ActionContext`; serialize decisions to Codex's response wire (deny/`updatedInput`/
   PermissionRequest `decision.behavior` -- contracts to pin in probe 2). Broader coverage target: PreToolUse +
   PermissionRequest + Stop + UserPromptSubmit. Carry the **`ActionContext.runtime` -> `origin` rename** here (the
   adapter is its first real consumer; direction resolved in the `runtime_abstraction` Open Decisions 2026-06-09 --
   values `{forge_cli, claude_code, codex}`; do NOT add a `subject_runtime` axis). Honest capability ceiling:
   `pretool_policy="partial"`; headless `codex exec` workers get **no** policy (registry note).

4. **SessionStart curated-transfer delivery with initial-message fallback (gated on probe 2).** Only meaningful for an
   interactive frontend -- the headless bridge stays initial-message permanently. Build only if (2) confirms
   SessionStart `additionalContext` fires + lands in model context (the harness's 30e magic-token oracle, re-run
   interactively).

5. **Interactive Codex frontend (gated on probe 2).** Forge-managed interactive `codex` sessions: `install_scopes` for
   Codex config (today `()` on the RuntimeSpec), flip `interactive="beta" -> ...`, FORGE_SESSION wiring (reaches the
   model shell; hook env unverified), session-id capture into `confirmed`.

6. **Installer Codex support (gated on 3/5).** The installer is Claude-shaped: 13 Claude hook names are hardcoded in
   `src/forge/install/preset.py` and it writes only `.claude/`. Installing Forge hooks into Codex needs a Codex preset
   (`~/.forge/codex.preset.json`?) + a Codex registration target (`$CODEX_HOME`/project `.codex/`), with installer-side
   **event-name validation** (the binary won't catch typos) and a per-hook-trust story.

7. **App-server transport (deferred, unevaluated).** `codex app-server`/`--stdio` as a long-lived RPC alternative to
   one-shot `codex exec` for resumed multi-turn sessions. Not probed in Phase 6; spike only if multi-turn `exec resume`
   proves clumsy.

## Risks / open questions

- **Interactive firing may also be absent or trust-gated** in a way Forge can't pre-grant non-interactively -- (2) is a
  real go/no-go, not a formality. If it fails, descope to the bridge CLI.
- **Codex version churn**: 0.137.0 -> 0.138.0 mid-evaluation; re-run the probe on Codex bumps (the harness is the
  standing guard).
- **Per-hook-hash trust** + `allow_managed_hooks_only` could make Forge-installed Codex hooks unusable without manual
  user trust; the installer story (6) depends on what (2) finds about the trust store.
- **`fallbackModel`/model drift**: a Codex usage event's `model` must be the actually-routed model (already handled for
  the headless emitter; revisit for any interactive path).
