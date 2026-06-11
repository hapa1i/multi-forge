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
  (registering config path, snake_case event, entry indices) -- NOT stored in sqlite, NOT in the project. *(Round-2
  snapshot: the hash preimage was an open question here; round 3 (83) settled the posture -- not black-box computable,
  so guided ceremony. See Risks.)*
- **Trust survives hook-script content change** (40d): appending to the registered wrapper script did not stop firing.
  The `trusted_hash` covers the registration *definition*, not the executable's bytes -- good for Forge upgrades (the
  `forge hook ...` command string stays stable), security-relevant for the installer story (a trusted hook's executable
  can be silently swapped). *(Round-2 snapshot: the registration-string dimension was unprobed here; round 3 (40e)
  settled it -- the command string IS in the per-entry `trusted_hash`.)*
- **`FORGE_SESSION` reaches the hook env** (50c interactive capture: `FORGE_SESSION=probe-fs-xyz` in the hook's env) --
  hooks can locate the Forge session manifest exactly as Claude hooks do. Ambient env passthrough to hooks also holds
  headless (40c2 env capture).
- **`permission_mode` discriminates execution mode** in the payload: `"bypassPermissions"` on `codex exec` turns vs
  `"default"` in the TUI *(round-2: single observation each; round 3 re-observed both values across the enrolled-home
  runs -- see the round-3 payload-shape bullet)*.
- **Payload fixtures are now capturable headless**: an enrolled home fires reproducibly, so the Phase 6 "fixtures need
  the interactive path" descope rationale is obsolete -- one enrollment ceremony, then headless capture.
- **`--ephemeral` negative control**: no session rollout is created (only sqlite WAL noise) -- maps cleanly to
  incognito-style sessions.

Gating probe round 3 (2026-06-10, codex-cli **0.138.0**, headless from one enrolled fixture; harness
`scripts/experiments/codex-hooks/` stages 80-83, captures at `~/.cache/forge-codex-hooks-probe/`):

- **One "trust all" grant enrolls every entry** (operator-observed wording: *"You can trust all - no command or hash"*).
  A single ceremony wrote **13** `[hooks.state]` keys (all 10 events + a matcher'd PreToolUse + a user-level + a
  sacrificial entry) and a `[projects."<proj>"] trust_level = "trusted"` line. So enrollment is a per-config grant, not
  per-entry review, and the TUI shows neither the command string nor a hash.
- **40d holds on 0.138.0** (re-validated): a wrapper-body swap kept trust (SessionStart still fired) -- the harness's
  stable-path / swappable-body design is sound.
- **40e -- the command string IS in the per-entry `trusted_hash`**: changing one entry's registered `command` untrusted
  *that* entry (it stopped firing) while the unchanged primary kept firing. Combined with 40d (script *content*
  survives), `trusted_hash` covers the registration *definition* (command string), not the executable's bytes.
- **Response contracts headless (enrolled, no bypass)**: PreToolUse **deny** (JSON `permissionDecision:"deny"`) blocked
  the command; PreToolUse **deny via exit 2** blocked it too; PreToolUse **allow + `updatedInput`** mutation **took
  effect** (the rewritten command ran); **UserPromptSubmit block** suppressed the model turn; **Stop block-once** forced
  exactly one extra pass; **SessionStart `additionalContext` PASSED** -- the model echoed the injected token (Phase 4
  delivery viable headless). **PermissionRequest did NOT fire** under the read-only sandbox.
- **Malformed PreToolUse output FAILS OPEN, not closed** (refutes the doc-claim): a response with
  `permissionDecision:"allow"` + unknown `bogusFieldZzz` + `continue:false` ran the command -- Codex honored the allow
  and ignored the unknown/`continue` fields. The adapter must NOT rely on Codex fail-closing on bad hook output.
- **Payload shape (snake_case, confirmed; fixtures at `tests/fixtures/codex/hooks/`)**: common `session_id`,
  `transcript_path` (the rollout JSONL path -- directly usable for `confirmed`), `cwd`, `hook_event_name`, `model`,
  `permission_mode`; turn-scoped add `turn_id`; SessionStart adds `source` (`"startup"`); PreToolUse adds
  `tool_name`/`tool_input`/`tool_use_id`; PostToolUse adds `tool_response`; UserPromptSubmit adds `prompt`; Stop adds
  `last_assistant_message`/`stop_hook_active`. **`tool_name` is `"Bash"` (shell) and `"apply_patch"` (file write)** -- a
  PreToolUse matcher must match those names; the probe's `matcher="shell"` never fired. `permission_mode` is
  `"bypassPermissions"` on `codex exec` (vs `"default"` interactively, round 2) -- the execution-mode discriminator.
- **User-level AND project-level hooks fire headless** when enrolled; trust records key by the registering config's path
  (user record under `codex-home/config.toml`, project records under `proj/.codex/config.toml`).
- **Enrollment survives worktrees of the enrolled project (resolved 82w2, valid run).** The project SessionStart hook
  fired in a `git worktree` checkout (`proj-codexwt`, a sibling path) **with no folder `trust_level` and no
  `[hooks.state]` record at the worktree config path** (proj=1, user=1). Cross-checked against the captured clean base
  (`meta/user-config.no-wt-trustlevel.toml`): the worktree `[projects."<wt>"]` block was stripped, no `[hooks.state]`
  key exists at the worktree path, and all 13 enrolled records sit at `codex-home/config.toml` /
  `proj/.codex/config.toml`. Chained with **40b** (folder `trust_level` alone does NOT fire hooks), the firing can only
  be a `trusted_hash` match on the registration definition (the command string is byte-identical: `$HOOKBIN/<event>.sh`,
  an absolute path outside both trees). **Mechanism not distinguished**: trust could be matched by a path-independent
  hash value, or Codex could canonicalize the worktree back to the enrolled checkout (same git repo). This probe does
  not separate them, and proves **nothing** about an *unrelated* project reusing the same command string -- that broad
  "one ceremony trusts the command everywhere" claim is UNTESTED and needs a fresh-project probe before any installer
  story relies on it. **\[RESOLVED 2026-06-10, stage 84: the broad claim is FALSE -- a fresh unrelated repo's
  byte-identical project hook did NOT fire even with folder trust, so the worktree survival was worktree->checkout
  canonicalization (not a path-independent hash) and project-scope trust is per-repo. The path-stable user-level hook
  fired from the fresh repo, so USER-scope registration is the leading one-ceremony-covers-all candidate.\]** **Phase 6
  (holds under either mechanism): project-scope registration with a path-stable command string survives `git worktree`
  checkouts -- no per-worktree re-enrollment** (a path-varying command string would break it; one interactive ceremony
  per `CODEX_HOME` still seeds the first record). *(First 82w2 run was VOID -- the persistent fixture had retained a
  worktree `trust_level` block; stage 82 hardened with a strip-first clean base and an INVALID self-guard, then
  re-run.)*
- **`trusted_hash` preimage is NOT black-box computable**: 15 candidate canonicalizations (command, JSON struct, TOML
  block, key variants) reproduced **0/13** harvested hashes. The command string is in the hash (40e) but the algorithm
  is not a simple sha256 of obvious inputs -- recovering it needs a source-dive of the codex-cli Rust. The empirical
  pre-enrollment test was correctly skipped (can't forge without the algorithm). **-> pre-enrollment posture = guided
  one-time ceremony** (the installer ships a guided `codex` trust step; programmatic `[hooks.state]` writing stays
  blocked until/unless a source-dive makes the hash computable).

Phase 2 live verification (2026-06-10, codex-cli 0.138.0, via the standing real-codex E2E
`tests/integration/core/test_codex_session_start.py` -- 2 live turns; probe stage 61
`scripts/experiments/codex-hooks/stages/61-rollout-identity.sh` is written + wired into `reproduce.sh` for the
experiment harness but the E2E supersedes its one-shot run):

- **Stream `thread_id` == rollout filename `session_id`** (was doc-asserted only): the live run's
  `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<ts>-<id>.jsonl` ends with the `thread.started` thread_id -- hook-free
  rollout discovery by thread_id glob is sound.
- **stdin-prompt + `codex exec resume` works** (the invoker delivers prompts via stdin, which probe 60 never combined
  with `resume`): a seed token planted in turn 1 was recalled in turn 2 with the prompt on stdin, and the resumed stream
  re-announced the **same** thread_id (60b's stability holds through the invoker path; the op's drift-warning path
  stayed cold).

## Deliverables (verdicts carried from the decision record)

1. **One-command bridge CLI -- SHIPPED 2026-06-10 (Phase 2; see the checklist + change_log entry).**
   `forge session start [name] --runtime codex --resume-from <parent> --task "..."` +
   `forge session resume <name> --task "..."` over the new command-core op `core/ops/codex_session.py` (composing
   `bridge_session_to_codex`). All the needs landed: `LaunchIntent.runtime` (immutable, registry-id vocabulary) with
   runtime-aware dispatch in every entry point (plus a `_launch_claude_for_session` backstop); hook-free `thread_id`
   from `thread.started` into `confirmed.codex`; rollout path discovered by thread_id and recorded with
   `rollout_source="discovered_by_thread_id"` (None when absent -- a future hook-sourced value gets its own label);
   `codex exec resume <thread_id>` continuation (cross-CWD, prompt on stdin -- both verified live, see the "Phase 2 live
   verification" facts above). The synthetic-children debt was retired *structurally*: the CLI path keys the snapshot by
   the real session name so `Derivation.context_file` GC-protects it; existing orphan detection sweeps pre-Phase-2
   leftovers.

2. **Gating probe -- COMPLETE 2026-06-10 (Phase 0 + Phase 1).** Firing GO (interactive 50c, enrolled-headless 40c2/40d),
   and the enrollment mechanics are now pinned -- see "Gating probe round 3" above and the change_log Phase 1 entry; do
   not re-derive. In brief: one "trust all" ceremony enrolls every entry; the `trusted_hash` covers the registration
   *definition* (40e) but is NOT black-box computable (0/13) -> posture = guided ceremony; the full event matrix +
   30a-30h response contracts ran (30e PASS gates Phase 4; PreToolUse deny + `updatedInput` gate Phase 3 and the
   `pretool_policy` value); user- and project-level hooks both fire; enrollment survives worktrees of the enrolled
   project. The persistent enrolled-fixture harness (`scripts/experiments/codex-hooks/` stages 80-83) is the reproducer.
   **Closeout code unit shipped 2026-06-10:** the `codex_preflight.py` `[hooks.state]` decision is recorded in code (the
   read is deliberately not implemented -- a path-keyed read would false-negative in a worktree, and the hash is not
   computable, so preflight can never report `active`; the seam stays `enrollment_gated`) and the registry
   `pretool_policy` rose `"none"` -> `"partial"` (deny + mutation confirmed; partial because enforcement is
   enrollment-gated, malformed output fails open, and PermissionRequest is unpinned). See Risks.

3. **Codex hook adapter/responder (gated on probe 2's response-contract leg).** `CodexHookAdapter`/`CodexHookResponder`
   filling the runtime-neutral protocols in `src/forge/cli/hooks/protocols.py` (the Phase 4f seam already makes room).
   Map the snake_case payload -> `ActionContext`; serialize decisions to Codex's response wire (deny/`updatedInput`/
   PermissionRequest `decision.behavior` -- contracts to pin in probe 2, now headless-runnable). Broader coverage
   target: PreToolUse + PermissionRequest + Stop + UserPromptSubmit. Carry the **`ActionContext.runtime` -> `origin`
   rename** here (the adapter is its first real consumer; direction resolved in the `runtime_abstraction` Open Decisions
   2026-06-09 -- values `{forge_cli, claude_code, codex}`; do NOT add a `subject_runtime` axis). **Registry correction
   DONE in Phase 0 (2026-06-10):** `native_hooks="headless_inert"` was refuted and renamed to `enrollment_gated` on both
   the registry `HookSupport` and the preflight `HookSeam`. The `pretool_policy` rise shipped in the Phase 1 closeout
   unit (2026-06-10): `"none"` -> `"partial"` (see Deliverable 2).

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

- **Guided-ceremony UX tax (the resolved-posture residual).** The `trusted_hash` is not black-box computable (0/13), so
  Forge cannot forge `[hooks.state]` records; the posture is a one-time interactive `codex` trust ceremony per
  `CODEX_HOME`. Survivable but a real Day-1 setup step; re-openable only if a codex-cli source-dive recovers the hash
  (`hash-preimage.py --emit-state` is ready for that path).
- **Path-stable command-string requirement.** Worktree trust survival hinges on the registered `command` being
  byte-identical across paths (40e: the command string is in the hash). A path-varying command (one embedding the
  worktree/project dir) would diverge the hash and break trust. The installer must register a stable `forge hook`
  command, not a path-relative one.
- **Cross-project trust does NOT hold (RESOLVED -- stage 84, codex 0.139.0, 2026-06-10).** A fresh, UNRELATED git repo
  registering a byte-identical hook command string is untrusted: even with the registration present and folder
  `trust_level` added (the 40b deconfound), the fresh repo's project SessionStart did NOT fire (proj=0) while the
  path-stable user-level hook DID (user=1) -- so the turn ran and the apparatus worked, a real no-fire, not a dead turn.
  Trust is keyed by the registering config's PATH; 82w worktree survival was Codex canonicalizing the worktree back to
  the enrolled checkout (a fire with no `[hooks.state]` record at the worktree path must map back), not portable
  command-string trust. **Installer consequence:** project-scope registration needs a ceremony *per repo*; a USER-scope
  registration (`$CODEX_HOME/config.toml`) is path-stable and one ceremony covers every project (the user-level control
  fired unprompted from the fresh repo). The path-stable command-string requirement still holds within a project's
  worktrees. See the Worktree/installer-scope Open Decision (checklist).
- **Malformed hook output FAILS OPEN, not closed** (refutes the doc claim). Codex ran the command on a PreToolUse
  response carrying `allow` + an unknown field + `continue:false`. The adapter/responder must emit strictly valid output
  and must NOT rely on Codex fail-closing on bad hook output.
- **PermissionRequest behavior headless is unpinned.** It did NOT fire under the read-only sandbox probe; whether it
  fires headless under permission-eliciting conditions is unobserved. Deliverable 3's PermissionRequest path rests on an
  event that has not been seen firing on `codex exec`.
- **Codex version churn**: 0.137.0 -> 0.138.0 mid-evaluation; re-run the probe on Codex bumps (the harness is the
  standing guard). Trust/enrollment semantics are exactly the kind of behavior a minor release changes.
- **`allow_managed_hooks_only`** (enterprise `requirements.toml`) can still suppress user/project hooks regardless of
  enrollment.
- **`fallbackModel`/model drift**: a Codex usage event's `model` must be the actually-routed model (already handled for
  the headless emitter; revisit for any interactive path).
