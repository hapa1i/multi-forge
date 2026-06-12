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
./reproduce.sh all          # + operator-guided 40 50 80 (needs a TTY)
./reproduce.sh 60           # one stage
./sanitize.sh               # raw captures -> sanitized fixture candidates + loud secret scan

# Round 3 (enrollment mechanics; explicit-only -- see below):
./reproduce.sh 80           # operator trust ceremony; builds the persistent enrolled fixture
./reproduce.sh 81 82 83 84  # headless probes against that fixture (refuse to run without it)
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

### Safety (round 3 additions)

The fixture's `codex-home/` is never copied by `sanitize.sh` (the existing `*/codex-home/*` exclusion covers it), and
its `auth.json` is removed on every stage exit. Stage 83's empirical test runs in a fresh `mktemp` home, removed on
exit. Trust state (`config.toml`) persists by design; delete the fixture dir when the round-3 record is written.

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

**Owed next operator round — stage 85 (enrolled `forge hook codex-policy-check` end-to-end).** Phase 3 shipped the Codex
PreToolUse policy hook (`forge hook codex-policy-check`: apply_patch -> per-file policy evaluation -> stdout deny JSON);
CI covers its stdin-JSON CLI contract (`tests/integration/docker/test_policy_hooks.py`), but the full enrolled-hook loop
— a real `codex exec` turn whose registered PreToolUse hook runs the forge command and Codex honors the deny — needs the
trust ceremony, so it is operator-gated. Sketch: register `command = "forge hook codex-policy-check"` (path-stable) as a
PreToolUse hook in the enrolled fixture, point `FORGE_SESSION` at a policy-enabled session, prompt an apply_patch into
`src/` with no tests, and assert the patch did NOT apply.

**Owed next operator round — stage 86 (enrolled SessionStart transfer delivery end-to-end).** Phase 4 shipped the
delivery loop (`forge session start --runtime codex --context-delivery hook`: staged `pending-context.md` -> registered
`forge hook codex-session-start` emits `additionalContext` -> receipt -> CLI reconciliation into
`confirmed.codex.context_delivery`); CI covers the handler's stdin-JSON contract and the staged/receipt lifecycle
(`tests/integration/docker/test_policy_hooks.py::TestCodexSessionStartDocker`) and 30e proved short-token
additionalContext lands. The operator round verifies the composed loop on real codex: register
`command = "forge hook codex-session-start"` (path-stable) as a SessionStart hook in the enrolled fixture, plant a
`MAGIC-CTX`-style token in a parent session's transfer, run the one-command bridge with `--context-delivery hook`, and
assert (a) the model echoes the token (delivery reached context), (b)
`confirmed.codex.context_delivery == "session_start_hook"` with `rollout_source = "session_start_hook"` (receipt
reconciled), and (c) a **realistic multi-KB transfer body** still lands — payload size is the one unprobed dimension
(30e used a short token). Also re-confirms the bridge-scoped env loop (`FORGE_SESSION`/`FORGE_FORGE_ROOT` visible in the
hook env; 40c2/50c pinned ambient passthrough, this pins the bridge-set values specifically).

**Owed next operator round — stage 87 (Forge-managed interactive Codex smoke).** Phase 5 shipped Forge-managed
interactive sessions (`forge session start --runtime codex` launches the TUI; bare `forge session resume` reattaches via
`codex resume <thread_id>`; thread identity reconciled post-exit from the observation receipt or filesystem discovery).
The TUI cannot run headless, so this is a manual checklist with captured evidence (`forge session show` output +
`observation-receipt.json` contents per step):

1. **Bare start**: `forge session start s87a --runtime codex` -> TUI opens with no initial prompt -> exit ->
   `session show s87a` records `thread_id` with `rollout_source = "discovered_post_exit"` (un-enrolled home) or
   `"session_start_hook"` (enrolled), and **no** `Delivery:` line (bare starts record `context_delivery = None`).
2. **Interactive bridge, positional delivery**: `forge session start s87b --runtime codex --resume-from <parent>` with a
   **multi-KB curated transfer** (size unprobed — 50c used a short token). Verify the hold instructions hold: the first
   model turn acknowledges the context in a sentence and **waits** — no file edits, no commands, no tool calls before
   the operator types. This is the load-bearing check: the positional `[PROMPT]` starts a real model turn, and the
   `compose_codex_interactive_context` framing is what keeps it passive.
3. **Interactive bridge, hook delivery** (enrolled home): `--context-delivery hook` -> context lands via
   `additionalContext` with no synthetic first turn; post-exit `context_delivery == "session_start_hook"`.
4. **Reattach**: `forge session resume s87a` -> `codex resume <thread_id>` reopens the same conversation (prior turns
   visible); a second resume while one is live is refused (active-session gate).
5. **TUI `--sandbox` behavior**: `forge session start s87c --runtime codex --sandbox read-only` -> the TUI honors the
   sandbox mode at runtime. The argv shapes are already pinned (codex 0.139.0 `--help` probes, 2026-06-11: root
   `codex [OPTIONS] [PROMPT]` and `codex resume [OPTIONS] [SESSION_ID]` both declare `-s/--sandbox`; the launcher passes
   it inside the `resume` subcommand where it is documented) — this step verifies the *behavior*, not the flag parsing.
