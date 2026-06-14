# Codex hooks/frontend probe (runtime_abstraction Phase 6, evaluation only)

**Question:** which Codex facts that the Codex-frontend deliverables rest on are actually true on the installed binary?
Docs go stale (this repo has caught two stale Codex doc claims already); the binary is authoritative — every doc-lead
below is a *claim to confirm or refute*, never an assumption to build on.

Research pin: codex-cli **0.137.0** (Phase 5, 2026-06-08). Stage 00 stamps the actual installed version into
`meta/version.txt` and warns on drift (0.138.0 observed 2026-06-09; changelog claims 0.138/0.139 are hook-neutral —
itself a doc-claim).

## Facts under test

| #   | Fact                                                                                                                                                                         | Stage      |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| 1   | Hook payload JSON shapes per event (field names, `tool_input` per tool, session/turn/cwd fields)                                                                             | 20         |
| 2   | Response wire contracts (deny JSON + exit-2, `updatedInput`, UserPromptSubmit block, SessionStart `additionalContext`, PermissionRequest, Stop block, malformed fail-closed) | 30         |
| 3   | Registration mechanics (user/proj x toml/json surfaces; matcher support; validation depth -- bogus event names load silently)                                                | 05, 10, 20 |
| 4   | Trust mechanics (untrusted-skip, project `trust_level` vs per-hook-hash, where trust state lives, hash-keying)                                                               | 40         |
| 5   | Do hooks fire under `codex exec` at all? (THE GATE)                                                                                                                          | 10         |
| 6   | Interactive management facts (initial-prompt arg, env passthrough to hooks, session-file location + id discoverability)                                                      | 50         |
| 7   | `codex exec resume` semantics (id, `--json` composition + argv form, cross-cwd, `--last`)                                                                                    | 60         |
| 8   | PreToolUse bypass paths (simple/compound shell, apply_patch, MCP)                                                                                                            | 70 (+20)   |

**Excluded by scope decision (2026-06-09):** the `codex app-server` transport — deferred, unevaluated.

## Doc-leads (every row: doc-claim, needs binary confirmation)

Fetched 2026-06-09 from developers.openai.com/codex (hooks, config-reference, noninteractive, changelog):

- Payload fields are `snake_case`: common `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `model`,
  `permission_mode`; turn-scoped events add `turn_id`; PreToolUse adds `tool_name`/`tool_use_id`/`tool_input`;
  PostToolUse adds `tool_response`; SessionStart adds `source` (`startup|resume|clear|compact`).
- Responses are `camelCase`: PreToolUse deny = `hookSpecificOutput.permissionDecision: "deny"` (+ reason) or exit 2 +
  stderr; mutation = `permissionDecision: "allow"` + `updatedInput`; unsupported PreToolUse output fields fail closed.
  PermissionRequest uses nested `decision.behavior` (a different shape). UserPromptSubmit block = top-level
  `{"decision": "block", "reason": ...}`. SessionStart/SubagentStart = `hookSpecificOutput.additionalContext`.
  Stop/SubagentStop block = `{"decision": "block", "reason": ...}` forcing another pass.
- Registration surfaces searched: `$CODEX_HOME/hooks.json`, `$CODEX_HOME/config.toml` `[hooks]`, project
  `.codex/hooks.json`, `.codex/config.toml`. Matchers are regex; UserPromptSubmit/Stop accept no matcher. Only
  `type: "command"` executes.
- Trust: non-managed hooks need review before first run; trust keyed to the hook-definition hash; untrusted projects
  skip project-local `.codex/` hooks; `--dangerously-bypass-hook-trust` (binary-confirmed flag) skips for one run;
  `codex doctor` exposes NO per-hook trust signal (binary-confirmed, Phase 5a).
- Whether hooks fire under `codex exec` is **doc-silent** — the gating unknown.
- `codex exec resume <id>` / `--last`; the id is the stream's `thread_id`; cwd-aware since 0.135.0.

## Running

```bash
./reproduce.sh              # headless set: 00 05 10 20 30 60 70 (~16-18 short turns)
./reproduce.sh all          # + operator-guided 40 50 80 85 86 87 (needs a TTY)
./reproduce.sh 60           # one stage
./sanitize.sh               # raw captures -> sanitized fixture candidates + loud secret scan

# Round 3 (enrollment mechanics; explicit-only -- see below):
./reproduce.sh 80           # operator trust ceremony; builds the persistent enrolled fixture
./reproduce.sh 81 82 83 84  # headless probes against that fixture (refuse to run without it)
./reproduce.sh 85           # product codex-policy-check E2E (operator trust + 1 headless turn)
./reproduce.sh 86           # product codex-session-start E2E (operator trust + 1 headless turn)
./reproduce.sh 87           # foreground TUI behavioral smoke (operator-guided)
```

Captures land **outside the repo** at `${CODEX_HOOKS_CAPTURE_DIR:-~/.cache/forge-codex-hooks-probe}/<stage>/`
(`payloads/`, `streams/`, `results/`, `trees/`, `meta/`). Stage state is otherwise disposable (mktemp + EXIT trap).
Delete the capture root when the decision record is written.

Stage 10's verdict re-routes (not blocks) the other hook stages: on `[FIRES-HEADLESS-TRUST-GATED]` they add
`--dangerously-bypass-hook-trust` automatically (`need_trust_bypass`, override with `PROBE_BYPASS_TRUST=0/1`). On either
no-fire verdict, the hook-dependent stages (20/30/70) capture nothing and their artifacts are **not** hook evidence -- a
hook that never fires cannot demonstrate a payload or response contract. Whether no-fire means interactive-only or
misregistration is a cross-stage call (it needs stage 50's interactive evidence), not a stage-10 verdict.

### Verdict vocabulary

- Stage 10: `[FIRES-HEADLESS]` | `[FIRES-HEADLESS-TRUST-GATED]` | `[NO-FIRE-UNCATEGORIZED]` | `[NO-FIRE-INCONCLUSIVE]`
  (the last when every relied-on turn errored/timed out -- 0 firings from an incomplete turn is not evidence, and the
  stage exits nonzero). `[INTERACTIVE-ONLY]` is a decision-record classification (needs stage 50), not a stage-10
  output.
- Stage 70 per tool path: `intercepted` | `bypassed` | `not-probed` (absence of a probe is never reported as a result)
- 30e oracle: PASS only when the model **echoes** the injected `MAGIC-CTX-7F3A9` token (injection verifiably landed in
  model context); anything else is a recorded miss, not a soft pass.

## Safety

1. **Never touches the real `~/.codex`**: every stage runs under an isolated `CODEX_HOME` inside a mktemp tree (stage 40
   keeps a persistent home under the capture root because trust state must survive its sub-steps; its `auth.json` copy
   is removed on exit). Escape hatch `PROBE_USE_REAL_CODEX_HOME=1` is operator-consent-only and mutates real trust
   state.
2. **Auth**: `~/.codex/auth.json` is copied 0600 into the disposable home and dies with it. Hook env captures elide the
   values of anything matching `KEY|TOKEN|SECRET|AUTH|PASSWORD` at capture time — before sanitization ever runs.
3. **No writes outside the probe trees**: hooks write only via `PROBE_CAPTURE_DIR`; workspace-write turns are confined
   to the mktemp project.
4. **Sanitize-then-scan**: `sanitize.sh` replaces `$HOME`/`$USER`/probe paths and then FAILS LOUDLY on residual
   secret-shaped content (scan-and-fail, never silent scrub). `codex-home` dirs are never copied; a stray `auth.json`
   anywhere fails the run.

## Cost

Every model turn is a one-sentence prompt demanding a one-word reply (`--sandbox read-only` unless the probe needs
writes, `-o` last-message oracle). Full headless set ≈ 16–18 short turns; `all` adds ~5 turns + 2 interactive runs — in
total roughly one trivial conversation of ChatGPT-subscription quota. Re-run individual stages, not the world.

## Round 3 — enrollment mechanics (codex_frontend Phase 1)

Rounds 1-2 settled the firing question: Codex hooks **do** fire under headless `codex exec` once trust-enrolled
(40c2/40d) and interactively (50c); headless cannot *self-enroll*. Round 3 pins the *enrollment mechanics* that gate the
build deliverables — what `trusted_hash` covers, whether Forge can pre-enroll programmatically, which events actually
fire post-enrollment, whether enrollment survives worktrees, and where user-level trust lands. **No
`--dangerously-bypass-hook-trust` anywhere in 80-83**: enrollment is the variable under test, not something to bypass.

### The fixture model

One operator trust ceremony (stage 80) builds a **persistent** enrolled home that serves every later headless probe. It
lives OUTSIDE the per-stage capture dirs and survives across runs:

```
${CODEX_HOOKS_CAPTURE_DIR}/fixture/
├── codex-home/     # persistent CODEX_HOME (trust state in config.toml; auth.json copied per run, removed on exit)
├── proj/           # stable git-inited project; proj/.codex/config.toml registers all hooks
├── hookbin/        # STABLE wrapper paths (the registered command strings -> the trust key never changes)
└── ENROLLED        # sentinel written after stage 80 verifies SessionStart fires headless
```

**Why stable paths + rewritten bodies.** Trust keys embed the registering config's *absolute path* and a hash of the
hook *definition* (which includes the command string = the wrapper path). 40d proved trust survives a wrapper-*content*
change. So the harness keeps each wrapper PATH fixed (trust holds) but rewrites its BODY every stage (`make_hook_cmd`
bakes the stage's `PROBE_CAPTURE_DIR`; a stale body would silently misattribute captures). `fixture_tee`/`fixture_arm`
(in `lib.sh`) own that swap; stage 81 re-validates the 40d assumption as its first step.

### Ceremony (one required, ~3 min)

`./reproduce.sh 80` registers everything, then prints an OPERATOR block: in a second terminal,
`cd <fixture>/proj && CODEX_HOME=<fixture>/codex-home codex`, accept the project + hook trust prompts (noting the exact
wording), `/quit`, then press ENTER. Stage 80 snapshots the trust delta, harvests the `[hooks.state]` keys + hashes, and
runs two headless verification turns. Re-running 80 rebuilds the home and needs a fresh ceremony (never idempotent);
81-83 are the repeatable headless consumers.

### Stage map

| Stage | Mode             | Pins                                                                                                                                                                |
| ----- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 80    | guided (TTY)     | builds + enrolls the fixture; SessionStart fires headless on two fresh runs                                                                                         |
| 81    | headless+fixture | 40d body-swap re-validation; per-event fired matrix; 30a-30h response contracts (30e gates Phase 4; PreToolUse deny/`updatedInput` gate Phase 3 + `pretool_policy`) |
| 82    | headless+fixture | 40e command-string mutation; user-vs-project trust location; worktree path-sensitivity (-> Phase 6 installer scope)                                                 |
| 83    | offline (+1-2)   | `hash-preimage.py` reverse-engineers `trusted_hash`; if computable, forges a `[hooks.state]` record and proves programmatic pre-enrollment end-to-end               |
| 84    | headless+fixture | cross-project trust: does a fresh UNRELATED repo reusing the enrolled command string fire? H1 definition-match vs H2/H3 path-scoping (-> Phase 6 installer scope)   |
| 85    | guided+headless  | product `forge hook codex-policy-check` E2E: trusted PreToolUse hook denies an apply_patch and the blocked file does not land                                       |
| 86    | guided+headless  | product `forge hook codex-session-start` E2E: hook-delivered multi-KB transfer reaches `additionalContext` and reconciles into `confirmed.codex`                    |
| 87    | guided TUI       | Forge-managed interactive Codex smoke: bare start, reattach, active gate, positional hold behavior, hook delivery, and read-only sandbox behavior                   |

### Verdict vocabulary (round 3)

- Stage 80: `FIXTURE-ENROLLED` | `ENROLLMENT-UNCONFIRMED` (SessionStart did not fire on both verification turns —
  inspect `results/enrollment-matrix.txt`, re-ceremony).
- Stage 81 `81-revalidate`: `PASS` (body swap kept trust) | `FAIL (MAJOR)` (40d does not hold here — fall back to
  per-change ceremonies; 81/82 results become suspect).
- Stage 83: `PREIMAGE-COMPUTABLE` (+ empirical `PROVEN`/`UNCONFIRMED`) | `PREIMAGE-NOT-COMPUTABLE` (posture = guided
  ceremony; not a failure). `hash-preimage.py` reports `PREIMAGE FOUND: '<candidate>'` only when one canonicalization
  reproduces **every** harvested hash.
- Stage 84 (writes `results/verdict.txt`; **HOLDS/SCOPED exit 0, the others exit nonzero**):
  `[CROSS-PROJECT-TRUST-HOLDS]` (a fresh UNRELATED repo's project hook fired -- itself proof the turn ran, so HOLDS does
  NOT need the positive control -> one ceremony per `CODEX_HOME` trusts the command everywhere; a user=0 HOLDS is
  flagged but stands) | `[CROSS-PROJECT-TRUST-SCOPED]` (the turn ran -- user-level positive control fired -- but the
  project hook did NOT -> per-project enrollment or user-scope registration) | `[CROSS-PROJECT-SELF-ENROLLED]` (MAJOR --
  a `[hooks.state]` record appeared headless, refuting "headless cannot self-enroll"; 84a short-circuits before 84b) |
  `[CROSS-PROJECT-INVALID]` (setup confound -- the fixture was not in the expected clean state; inspect + re-run) |
  `[CROSS-PROJECT-INCONCLUSIVE]` (not even the positive control fired; the turn did not run -- mirrors stage 10).
- Stage 85: `[POLICY-CHECK-E2E-PASS]` when a trusted product `codex-policy-check` hook records a TDD deny and the
  requested `src/` file is absent; `[POLICY-CHECK-E2E-INCONCLUSIVE]` when no matching decision lands;
  `[POLICY-CHECK-E2E-FAIL]` when the blocked file exists.
- Stage 86: `[SESSIONSTART-DELIVERY-E2E-PASS]` when a trusted product `codex-session-start` hook delivers a >=4 KiB
  transfer, the model echoes the oracle token, and `confirmed.codex` records `context_delivery="session_start_hook"` +
  `rollout_source="session_start_hook"`; `FAIL` means `hook_undelivered`; `INCONCLUSIVE` means the echo/manifest/size
  facts did not all line up.
- Stage 87: `[INTERACTIVE-SMOKE-PASS]` when operator confirmations and manifest facts all pass;
  `[INTERACTIVE-SMOKE-SANDBOX-FAIL]` when the main interactive facts pass but the read-only sandbox still allows a file
  write; `[INTERACTIVE-SMOKE-SANDBOX-INCONCLUSIVE]` when the sandbox refusal was not operator-confirmed;
  `[INTERACTIVE-SMOKE-INCOMPLETE]` records other missing answers/facts in `results/verdict.txt`.

### Safety (round 3 additions)

The fixture's `codex-home/` is never copied by `sanitize.sh` (the existing `*/codex-home/*` exclusion covers it), and
its `auth.json` is removed on every stage exit. Stage 83's empirical test runs in a fresh `mktemp` home, removed on
exit. Trust state (`config.toml`) persists by design; delete the fixture dir when the round-3 record is written. Stages
85-87 additionally create isolated Forge state under each stage capture dir (`FORGE_HOME=$CAPTURE/stage/forge-home`) and
stable product projects under the stage capture dir. They register the **real product command strings**
(`forge hook codex-policy-check` / `forge hook codex-session-start`), so `forge` must be on PATH for the Codex hook
subprocess. Use `./scripts/setup.sh --local` or another local install before running those stages.

## Relationship to the decision record

Rounds 1-2 fed the `runtime_abstraction` Phase 6 decision record (a dated Stage-A-style block + go/no-go table, now in
`docs/board/done/runtime_abstraction/checklist.md`, evaluation-only). Round 3+ is this harness's standing role as the
`codex_frontend` build card's Codex-fact guard — re-run it on Codex version bumps.

Hook payload fixtures are **capturable headless** from the enrolled fixture: rounds 2-3 settled that hooks fire under
headless `codex exec` once trust-enrolled, so the Phase-6 "fixtures need the interactive path" descope is obsolete (one
ceremony, then headless capture). Phase 1 already promoted five sanitized payloads to `tests/fixtures/codex/hooks/`.
`sanitize.sh` produces review-ready candidates; the build card promotes any with a provenance README (cloning the
`tests/fixtures/codex/README.md` structure), pinning the future adapter's parsers as `exec_json_success.jsonl` pins
`parse_codex_jsonl_stream`.

**Operator-gated product stages (85-87).** These are now runnable scripts rather than checklist sketches:

- `./reproduce.sh 85`: registers `forge hook codex-policy-check` as a product PreToolUse hook in a stable stage project,
  asks the operator to trust it, creates a no-launch Forge session with TDD policy enabled, prompts a real Codex turn to
  `apply_patch` an implementation file without tests, and passes only if the product hook records a deny and the file
  does not land.
- `./reproduce.sh 86`: registers `forge hook codex-session-start`, asks the operator to trust it, creates a parent
  session with a multi-KB synthetic transcript, runs
  `forge session start s86-child --runtime codex --resume-from s86-parent --strategy full --context-delivery hook`, and
  passes only if the model echoes the oracle token and `confirmed.codex` records the hook-sourced delivery/rollout.
- `./reproduce.sh 87`: launches the foreground TUI paths and records operator confirmations plus manifest facts: bare
  start, live reattach, active-session refusal from a second terminal, positional bridge hold behavior, hook-delivered
  interactive bridge, and read-only sandbox behavior. The hook-delivered bridge also records the Codex CLI display
  observation that `SessionStart` `additionalContext` may be visibly rendered in the transcript even though it was not a
  positional synthetic prompt. The stage prints the exact second-terminal command for the active-gate check (using the
  absolute `forge` path from the launching shell), writes answers to `results/operator-answers.txt`, and writes
  non-gating observations to `results/observations.txt`.
