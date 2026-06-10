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
./reproduce.sh all          # + operator-guided 40 50 (needs a TTY; 2 interactive runs)
./reproduce.sh 60           # one stage
./sanitize.sh               # raw captures -> sanitized fixture candidates + loud secret scan
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

## Relationship to the decision record

Findings land as a dated Stage-A-style block + go/no-go table in `docs/board/doing/runtime_abstraction/checklist.md`
(Phase 6). Hook fixtures are **descoped to the `codex_frontend` build card**, not promoted in Phase 6 (evaluation only):
hook payload fixtures need a firing hook, which is headless-unavailable, so they must be captured on the interactive
path. `sanitize.sh` produces review-ready candidates; the build card promotes any to `tests/fixtures/codex/hooks/` with
a provenance README (cloning the `tests/fixtures/codex/README.md` structure), pinning the future adapter's parsers as
`exec_json_success.jsonl` pins `parse_codex_jsonl_stream`.
