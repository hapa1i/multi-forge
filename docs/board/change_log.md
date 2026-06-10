# Change Log

Completed-work record for Forge implementation sessions.

## Maintenance

- Updated by the memory writer with `strategy=changelog`, and by humans when closing a phase.
- Add compact entries for completed work only. Pending tasks belong in card checklists.
- Follow `docs/developer/board-contract.md` "Change Log Policy": each entry needs Goal, Key changes, and Verification.
- Keep entries short. Do not list every file unless the file list is the point of the work.
- Use newest-first order so active work stays near the top.
- When this file approaches the documentation size limits, compact the oldest entries at the bottom into a dated summary
  that preserves decisions, verification, and deferred items. Archive detailed old entries only if the summary is still
  too large.
- Check size before long sessions or when the file feels slow to scan:

```bash
wc -l docs/board/change_log.md
./scripts/count-tokens.py --model <agent-model> docs/board/change_log.md
```

## Entries

> Format: `## YYYY-MM-DD`, then `### Phase X.Y: Short Title`, with `**Goal**:`, `**Key changes**:` as bullets, and
> `**Verification**:`. Use newest-first order. See `docs/developer/board-contract.md` "Change Log Policy" for the full
> spec.

## 2026-06-10

### codex_frontend Phase 0: Registry correction -- `headless_inert` -> `enrollment_gated`

**Goal**: Correct the Codex hooks capability encoding refuted by gating-probe round 2: trust-enrolled hooks DO fire
under headless `codex exec` (40c2/40d) and interactively (50c) -- the gate is a one-time trust enrollment, not the
execution mode. First code commit of the `codex_frontend` card.

**Key changes**:

- `HookSupport` (registry) and `HookSeam` (preflight) renamed `headless_inert` -> `enrollment_gated` **together**, so
  neither half of the capability model retains the refuted value. Resolves the card's literal-name Open Decision.
- The preflight verdict is pinned as capability-not-state: "hooks can fire, but this preflight has not checked the
  `[hooks.state]` record" -- never treat it as `active`. The per-hook enrollment read is Phase 1.
- Codex `RuntimeSpec` note rewritten to the round-2 facts (trust lives in user `config.toml` `[hooks.state]` keyed by
  the registering config's absolute path; survives script-*content* changes; only SessionStart observed firing).
  `pretool_policy` stays `"none"` (post-enrollment PreToolUse unprobed). `design.md` §5.5.5 synced; card.md stale
  "hook_seam is today honestly `unknown`" line fixed.

**Verification**: 63 runtime/CLI/preflight unit tests green (incl. renamed
`test_enabled_is_enrollment_gated_never_active`); mypy clean; `rg headless_inert docs/design.md src/ tests/` empty; live
`forge runtime list` renders `enrollment_gated` and `forge runtime preflight codex` renders
`Hook seam: enrollment_gated` (render asserted, exit code orthogonal); `make pre-commit` clean.

## 2026-06-09

### Phase 6: Codex frontend evaluation (probe-only; runtime_abstraction complete)

**Goal**: Evaluate Codex as a Forge frontend runtime -- a reproducible probe + a go/no-go decision record + a follow-up
build card -- without shipping product code. Closes the last open phase of `runtime_abstraction`.

**Key changes**:

- **Probe harness** `scripts/experiments/codex-hooks/` (mirrors the native-resume precedent): staged `reproduce.sh`,
  isolated `CODEX_HOME` (auth copied 0600 into a disposable tree), per-label tee/respond hooks, JSON/TOML registration
  generator, scan-and-fail `sanitize.sh`. Stages 00/05 (preflight + schema, 0 turns), 10 (headless-fire gate), 20
  (payloads), 30 (responses, moot-headless), 40/50 (trust/interactive -- headless parts + operator-gated TTY steps), 60
  (exec-resume), 70 (bypass, moot-headless). A capture-dir false-positive bug was found and fixed (probe_init clears the
  per-stage dir).
- **Gate finding (codex-cli 0.138.0):** Codex hooks do **NOT** fire under headless `codex exec` -- 0 firings across all
  4 registration surfaces, with `--dangerously-bypass-hook-trust`, on repeated same-home runs, confirmed by 5
  independent clean isolated tests. So headless policy enforcement and SessionStart transfer injection are unavailable
  on `codex exec`; interactive firing is UNVERIFIED (needs a TTY operator session).
- **Other pinned facts:** `codex exec resume <thread_id>` works and is **cross-CWD** (`--json` composes; `--last`
  unreliable); payload shape is snake_case as documented; registration validation is shallow (bogus event names load
  silently); session files at `$CODEX_HOME/sessions/.../rollout-<ts>-<session_id>.jsonl`; `FORGE_SESSION` reaches the
  model shell.
- **Go/no-go:** bridge CLI = **GO** (no hook dep; resume verified); SessionStart delivery = **NO-GO headless ->
  initial-message stays primary** (vindicates the Phase 5 deferral); hook adapter + interactive frontend = **gated on an
  interactive-firing probe**; app-server = deferred. Build work seeded in `docs/board/proposed/codex_frontend/`.
- **Registry correction** (`src/forge/core/runtime/registry.py`): the Codex `RuntimeSpec` read as "hooks work once
  version-gated" (`native_hooks="gated"`, `pretool_policy="partial"`), but hooks are enabled + version-OK yet do not
  fire headless. Corrected the **machine-readable fields**, not just the note: `native_hooks="headless_inert"` (new
  `HookSupport` value) + `pretool_policy="none"`, so a consumer reading the field -- not just the prose -- sees the
  limit. `codex_preflight.py` aligned: `hook_seam` now returns `headless_inert` (new `HookSeam` literal) for the normal
  enabled+version-OK headless case instead of `unknown`, so `forge runtime preflight codex` reports a known negative,
  not "trust unproven" (still never `active`).
- **Checklist compaction:** Phase 6 planning pushed the checklist over the 30k-token board hook; Phases 2/3-hardening/4
  (4a-4f) slice bodies compacted (state + decisions + debt preserved; verification bodies in git history + these
  entries). 31.2k -> ~25k tokens.

**Verification**: `bash -n` + shellcheck clean on the harness; stages 00/05/10/20/60 + headless 40/50 run green with
captures; the runtime/preflight/CLI suites (`test_registry.py`/`test_runtime.py`/`test_codex_preflight.py`) pass + mypy
clean after the field/seam/note edits. Probe spent ~10 short ChatGPT-quota turns. No runtime/execution behavior changed
(nothing branches on these capability values); only `forge runtime list`/`preflight codex` now render the corrected
`native_hooks`/`pretool_policy`/`hook_seam`. **`runtime_abstraction` is fully executed (Phases 0-6)**; the
`doing/ -> done/` lane move is gated on the merge to `main`.

### Phase 5f: Phase 5 doc sync + `forge transfer` end-user guide (docs-only closeout)

**Goal**: Sync the normative + end-user docs to shipped Phase 5 (Codex headless runtime) behavior and close out Phase 5.

**Key changes**:

- `design.md` §3.9 rewritten from pre-5e future tense to shipped: the `bridge_session_to_codex` cross-runtime hop
  (parent -> ai-curated Codex-targeted transfer -> body prepended to the `codex exec` prompt -> `CodexHeadlessInvoker`,
  one run tree), initial-message delivery as the Phase 5 mechanism (SessionStart-hook delivery deferred to Phase 6), and
  the honest CLI status (no `--runtime codex` frontend yet; user surface = `regenerate --target-runtime codex` + manual
  `codex exec`). §3.14 gained a "Transfer curation usage (Phase 5e)" paragraph. The bridge is documented in §3.9 (a
  cross-runtime resume-delivery op), not §5.5.5, which was already correct.
- `design_appendix.md` §A.13: `codex_exec` (route) + `codex_jsonl` (reporter) flipped reserved -> emitted; the
  per-emitter table gained the `transfer-curate` row; §M.1 `target_runtime` comment de-staled.
- New end-user guide `docs/end-user/transfer.md` (the chosen home): documents the previously-undocumented
  `forge transfer show|regenerate|edit|diff` group + the three-file model + the cross-runtime "plan in Claude, implement
  in Codex" workflow (honest that the one-command bridge is Phase 6). Registered in `README.md`; `session.md` repointed.
- `card.md` Phase 6 note corrected ("Phase 5 uses only `SessionStart`" was wrong -> initial-message delivery). The dated
  5a change_log "provisional" line is left as a historical snapshot.

**Verification**: `make pre-commit` clean (mdformat + the new guide); design docs under the tiktoken size hook; grep
gates clean (`SessionStart` outside `done/` names initial-message delivery; `codex_exec`/`codex_jsonl` shown as
emitted); `forge transfer --help`/`regenerate --help` confirm the guide matches the shipped CLI; the documented
`regenerate -> show -> codex exec` path is covered end-to-end by the 5e real-codex E2E
(`tests/integration/core/test_claude_to_codex_resume.py`). **Phase 5 is complete** (5.0/5a-5f shipped).

### Phase 5e: Claude->Codex resume bridge (the payoff)

**Goal**: Compose the Phase 5 build-group parts into the "plan in Claude -> implement in Codex via curated transfer"
hop, attributed across one run tree.

**Key changes**:

- New `core/ops/codex_bridge.py::bridge_session_to_codex` (UI-agnostic core op; no CLI -- the `--runtime codex` frontend
  is Phase 6): parent session -> ai-curated transfer (`target_runtime=codex`) -> body **prepended to the `codex exec`
  prompt** (initial-message delivery, not a `SessionStart` hook -- per-hook trust is unconfirmable, 5a) ->
  `CodexHeadlessInvoker().run`. Returns `CodexBridgeResult`; raises `ForgeOpError` for bad strategy / missing parent /
  non-ready Codex (Codex's own success/failure rides on `.codex`, not raised).
- "One run tree" is an `os.environ` contract: the bridge mints a fresh root (`new_root_run_identity()`) into env via a
  tested `_temporary_run_env` context manager, so both the curation `core.llm` call and the `codex exec` run derive
  under it -- no API change to the 5b/5c emitters. Per-run child key (`<parent>-codex-<run-suffix>`) avoids re-feeding a
  stale frozen snapshot.
- Part A: instrumented the ai-curated transfer curation (a previously-unattributed `core.llm` call) to emit a usage
  event (`.ask`->`.complete` to capture in-band tokens; `route=core_llm` / `runtime=forge_cli` /
  `command=transfer-curate`). General gap-fix: no-ops without an ambient run identity.
- `compose_codex_initial_message` is the named prompt-composition seam (pure, unit-tested).

**Verification**: hermetic bridge + transfer + codex-emit unit/CIT suites pass (99); real-codex E2E
(`tests/integration/core/test_claude_to_codex_resume.py`, `@slow`) green against real `codex 0.137.0` (~8s; curation
mocked so codex auth is the only hard dep); 5b real-codex smoke regression green; `mypy` clean; `make pre-commit` clean.

**Deferred to 5f**: `design.md` §3.9/§3.14/§5.5.5 sync (initial-message delivery; curation usage event; bridge composes
preflight + invoker) + the end-user cross-runtime workflow doc. No CLI command and no `SessionStart`-hook delivery (both
Phase 6).

## 2026-06-08

### Phase 5b-5d: Codex headless runtime (invoker + usage + transfer relabel)

**Goal**: Ship the Codex build group -- a `CodexHeadlessInvoker` reusing the hardened lifecycle, a native usage emitter,
and a `target_runtime`-aware transfer relabel -- so the Phase 5e plan-in-Claude/implement-in-Codex bridge has its parts.

**Key changes**:

- **Probe-first (B0)**: captured a real `codex exec --json` run (codex-cli 0.137.0) verbatim into
  `tests/fixtures/codex/` (success + error streams + `-o` oracle + provenance README). The fixture is authoritative over
  docs; it confirmed the doc-sourced token field names (`input_tokens`/`cached_input_tokens`/`output_tokens`).
- **Parser (B1)**: `core/invoker/codex_stream.py` reduces the JSONL event stream -> `(final_text, tokens, is_error)`; a
  failed turn (`error`+`turn.failed`) maps to `runtime_is_error`.
- **Shared lifecycle (B2)**: extracted the hardened `run`/`run_parallel` lifecycle into `_HeadlessLifecycleBase`
  (`core/invoker/_lifecycle.py`) with six template hooks; `ClaudeHeadlessInvoker` subclasses it ("moved, not changed").
  Migrated ~30 test patch-strings `claude.<sym>` -> `_lifecycle.<sym>` across the invoker test + 3 review drivers + the
  json-flag regression; both retry-race canaries stayed green.
- **Invoker + builder (B3/B4)**: `core/invoker/codex.py` -- `CodexHeadlessInvoker` (format-retry predicate always
  `False`) + `prepare_codex_request` (argv `codex exec --json --sandbox`, key injected only for env/credential_file
  auth, no proxy, run-tree triple stamped via the neutral `stamp_run_identity` factored out of `build_claude_env`).
- **Usage (5c)**: `emit_codex_usage` -- `route=codex_exec`/`reporter=codex_jsonl`/`runtime_native`,
  `confidence=unavailable` + `cost=None`/`source_refs=None` (direct to OpenAI; honest cost absence), `billing_mode` from
  `CodexPreflight` via a new optional `Attribution.billing_mode`.
- **Transfer (5d)**: `target_runtime` threads through `assemble_transfer_context` (default `claude`, byte-identical to
  pre-5d) -> frontmatter + `## Runtime Hints`; `forge transfer regenerate --target-runtime {claude|codex}` defaults from
  the cache (no silent flip). Delivery is initial-message (no SessionStart hook -> Phase 6).
- **Design sync**: `design.md` §5.5.5 (shared `_lifecycle` base + two invokers), §3.14 (native Codex emitter), §3.9
  (`target_runtime` + initial-message delivery).

**Decisions**: 5c `confidence=unavailable` (ledger confidence is cost-only; Codex reports no $); 5d minimal relabel
(body stays Claude-worded; curation tuning deferred); SessionStart-hook delivery deferred to Phase 6 (`hook_seam` can't
confirm per-hook trust).

**Verification**: 430 hermetic unit tests (invoker/usage/transfer/CLI + migrated review/regression); real-codex `@slow`
smoke green (8s, full stack: builder -> invoker -> real `codex exec` -> parser -> emitter); `mypy` clean (15 files);
`make pre-commit` clean.

### Phase 5a: Codex auth/runtime preflight (probe-first)

**Goal**: Ship a read-only native-Codex preflight -- run before any `codex exec` -- that resolves a non-interactive
credential, fails closed with setup guidance, and exposes a stable `CodexPreflight` contract for slices 5b/5c/5d, after
a live probe of the installed `codex` binary to correct doc-implied assumptions.

**Key changes**:

- **Stage-A probe (codex-cli 0.137.0, binary-authoritative)**: `codex doctor --json` is `schemaVersion: 1` with
  **string-boolean** auth details (`stored API key`/`stored ChatGPT tokens`/`stored agent identity` =
  `"true"`/`"false"`), parses a valid report **even on non-zero exit**, and reports `overallStatus="warning"` while auth
  is fine (so it must NOT gate readiness). It exposes **no per-hook trust** check -- so 5a never claims a trusted hook.
  Sanitized note in the 5a checklist.
- **`src/forge/core/runtime/codex_preflight.py`** (render-free core): frozen `CodexPreflight` + `preflight_codex` /
  `assert_codex_ready` (typed `CodexPreflightError`, mirroring `validate_proxy_startup`). Auth resolution is
  binary-authoritative: Forge `CODEX_API_KEY` (env/file) -> `CODEX_ACCESS_TOKEN` (env) -> `codex doctor` stored auth ->
  fail closed. `ready = installed AND auth resolved AND not responses-blocked` -- never `overallStatus`. `hook_seam`
  never returns `active` (trust is a 5d per-hook-hash check); managed suppression is claimed only on explicit
  `requirements.toml` evidence. The resolved key value is **never** a result field (would leak via `asdict()`/`--json`);
  5b reads it via the non-rendered `codex_api_key_for_subprocess()`.
- **Responses as a report, not a route**: `--proxy <id>` reads an existing proxy's `wire_shape` via
  `config.loader.load_proxy_instance_config` (lazy import; no `forge.proxy` dependency, no `/v1/responses` route);
  neither wire shape serves Codex Responses, so a proxied route is `proxy_unsupported` and direct `codex exec` is
  preferred.
- **`codex-api` (`CODEX_API_KEY`) credential** added to `CREDENTIALS`; note clarifies it is not OPENAI_API_KEY and not
  the ChatGPT login (Codex owns its own store).
- **CLI** `forge runtime preflight codex [--proxy] [--json]`: Rich report; `--json` dumps the secret-free dataclass;
  exit 1 when not ready.
- **Review hardening (2026-06-08)**: `_resolve_responses_posture` catches the config loader's `ValueError`/`TypeError`
  (invalid id / corrupt `proxy.yaml`) -> `proxy_unsupported`, not a traceback (preserves the never-raise contract);
  version comparison pads components (`0.131` meets the `0.131.0` floor); stored-auth resolution documented as
  PRESENCE-based (a non-"ok" `auth.credentials.status` does not fail-close -- validity is proven at 5b). Stale
  credential docs updated (`authentication.md` + `design_appendix.md`: six credentials, `codex-api` row,
  `not_needed_for` note); managed-suppression tests made fully hermetic + the nested-TOML parser branch covered.

**Verification**: 85 focused tests (`test_codex_preflight.py`, `test_runtime.py` preflight, `test_capabilities.py`
codex-api) + 244 broader (auth/runtime/CLI) green; mypy + pyright 0/0/0 on changed src. Live
`forge runtime preflight codex` on 0.137.0: `chatgpt_tokens`/`subscription_quota`, `hook_seam=unknown`,
`doctor=warning`, **Ready YES**, exit 0 (unknown `--proxy` -> exit 1; non-codex runtime -> exit 2). No
Docker/integration tier (5a spawns nothing). 5b-5f remain provisional pending a re-plan from the Stage-A findings.

### Phase 5 planning + Slice 5.0: Codex/Claude runtime-fact corrections

**Goal**: Scope Phase 5 (cross-runtime resume) and, before planning, re-verify the `runtime_abstraction` card's
external-tool assumptions against current Claude Code + Codex CLI — the card pinned Codex 0.124.0, now 0.137.0 stable
(~13 minors stale).

**Key changes**:

- **Research**: three adversarially-verified web sweeps (every claim grounded in fetched official docs or the installed
  `codex` binary) produced a per-assumption diff. Corrected stale Codex facts: hooks are **default-on**
  (`[features] hooks`; `codex_hooks` is a **deprecated alias**, not "required" and not "removed"); **10** lifecycle
  events (was 5); `SessionStart` additionalContext is the transfer-injection seam but **conditional** on hook
  enablement+trust (keep an initial-message fallback); `PreToolUse` can mutate via `updatedInput`; first-party
  non-interactive auth (`CODEX_API_KEY` / `codex login --device-auth` / enterprise tokens) + `codex doctor`; Codex emits
  `wire_api="responses"` only, so a proxy must serve Responses on its **Codex-facing** surface (a translated
  chat-completions backend does not block); `codex app-server --stdio` is a real alias for `--listen stdio://` (verified
  against the 0.137.0 binary — the rendered docs table omitted it).
- **Slice 5.0 (registry, shipped)**: `core/runtime/registry.py` Codex `RuntimeSpec` → `hook_feature_flag=None`,
  `hook_min_version="0.131.0"`, default-on note (10 events, `updatedInput`, `allow_managed_hooks_only`, Responses,
  SessionStart-trust caveat); `HookSupport` comment generalized to version-gated. `card.md` hooks paragraph + capability
  matrix + posture bullets + Phase 5/6 notes and `design.md` §5.5.5 corrected.
- **Plan**: `checklist.md` Phase 5 expanded from a 4-task stub to slices 5.0 (done) → 5a auth/runtime preflight → 5b
  `CodexHeadlessInvoker` (one-shot `codex exec`) → 5c usage attribution → 5d target-runtime curator (SessionStart +
  fallback) → 5e Claude→Codex demo → 5f doc sync, with fixture-grounded acceptance tables, a research verdict, and an
  Open Risks list. Transport decision recorded: one-shot `codex exec` (app-server a deferred follow-up).

**Verification**: `tests/src/core/runtime/test_registry.py` + `tests/src/cli/test_runtime.py` → 17 passed; mypy clean on
changed src. Otherwise docs/planning (no runtime behavior change beyond registry data). `make pre-commit` clean.

### Phase 4g: Exact cost attribution for proxied `claude -p` (run-tree correlation)

**Goal**: Replace the concurrency-fragile before/after proxy snapshot delta for proxied `claude -p` cost
(`verb_snapshot_estimated`, polluted when a session shares the proxy) with an **exact** join that correlates each cost
record to the Forge run that incurred it. ToS-clean: Forge's own headless subprocesses through Forge's own proxy, opaque
non-secret run ids; no credential extraction; the interactive OAuth session is untouched. Resolves the last Phase 4 open
decision.

**Key changes**:

- **Join key is the run tree, not `source_refs`.** One `claude -p` run makes many requests, so the single-valued
  `source_refs.cost_request_id` is the wrong shape — `source_refs` stays null on `claude -p`
  (`test_bug_usage_claude_p_null_source_refs.py` holds, no `UsageEvent` schema change). Cost records gain additive
  `forge_run_id`/`forge_root_run_id` (`schema_version` 1, no bump; reader uses `.get()`).
- **Env injection (gated, Forge-owned).** `build_claude_env` stamps `X-Forge-Run-ID`/`X-Forge-Root-Run-ID` via
  `ANTHROPIC_CUSTOM_HEADERS` only for a headless child (`derive_run_identity`) targeting a **proven Forge proxy**
  (`target_is_forge_proxy` OR marker present **and** `base_url == FORGE_SUBPROCESS_BASE_URL`) — an opaque/third-party
  base_url, including an inherited marker + explicit opaque override, never leaks the header. Strips inherited
  `X-Forge-*` lines, preserves user lines.
- **Proxy validate + stamp.** Middleware validates each inbound id (`^run_[0-9a-f]{12}$`, shared with `mint_run_id` via
  the new dependency-free `forge.core.run_id` leaf) and stores `None` on a spoof/malformed value; threads the ids
  through `_calc_and_log_cost` -> `log_request_cost`. One site covers both wire shapes.
- **Read-time root join + suppression.** `sum_reported_cost_by_root` returns `has_records`/`runs_with_records`
  (presence, incl. dollar-less records) and `has_cost`/`per_run` (dollars) separately;
  `usage_summary._join_session_cost` sums by `forge_root_run_id` and suppresses a `verb_snapshot_estimated` event
  **per-run-subtree** — only when its OWN run produced records, or it is a verb whose DIRECT children did (fan-out, via
  worker `parent_run_id`). Whole-root suppression was wrong: it dropped a correctly-unstamped sibling's snapshot
  whenever any run under the shared session root was stamped (silent undercount). A no-dollars route renders
  **unavailable**, never `$0`; root-summing still captures orphan cancelled leaves. The event stays
  `verb_snapshot_estimated`; the read surface recomputes the exact figure (`proxy_request_exact`) and renders it
  **without the `~` estimate marker** (`cost_estimated=False` on the summary/command DTOs drives `forge activity` and
  the session-end line).

**Verification**: Unit + regression suites green — `test_run_id.py`, `test_cost_logger.py::TestForgeRunCorrelation`
(+`runs_with_records` presence), `test_env.py::TestCorrelationHeaders`, `test_usage_summary.py::TestRootJoin4g`
(+exactness flags), `test_activity.py` (exact renders without `~`), and
`tests/regression/test_bug_4g_mixed_stamped_unstamped_undercount.py` (the shared-root undercount guard); mypy clean.
Docs synced (design.md §3.14, design_appendix.md §A.9/§A.13, card + checklist). **4g.0 feasibility canary PASSED**
(`tests/integration/proxy/test_forge_run_id_correlation.py`, all 6 cases, 28.6s) against a live OpenRouter-backed Forge
proxy on **Claude Code 2.1.168** — proving the load-bearing external dependency on the real wire: plain `claude -p`,
`claude -p --bare`, and a multi-request tool loop where the tool loop forced >= 2 requests and **every** record carried
the run ids. The standing version-regression guard records the validated version (`CLAUDE_VERSION_VALIDATED`).

## 2026-06-07

### Docs: correct the `claude_session_id` pre-seed lifecycle (design.md §3.3/§3.5 + session.md)

**Goal**: design.md §3.3/§3.5 and the end-user session guide said `claude_session_id` is "not pre-seeded by the CLI" /
"`None` until Claude starts" / "a non-null value means it has been used" — true only for the native `--fork-session`
path. The `forge session start` path (and transfer/fresh children) actually **pre-seed** it (the CLI generates the UUID,
writes it at creation, imposes it via `--session-id`) and the SessionStart hook **validates** it. Align the normative
and user docs to the shipped code (documentation-guidelines Rule 2: design docs describe shipped behavior).

**Key changes**:

- **design.md §3.3** (1:1 invariant): every launch that starts a **new** Claude conversation pre-seeds —
  `forge session start` and transfer/fresh children (`fork`, `resume --fresh`) generate a UUID and impose it via
  `--session-id`, which the hook validates; only **native** `--fork-session` forks do not pre-seed (Claude mints, hook
  records; `native-relocate` reuses the parent UUID). A non-null UUID alone is **not** "used" (a `--no-launch` start
  session already carries a pre-seeded UUID) — "used"/resumable requires hook confirmation or transcript-backed
  evidence, matching `_is_resumable_session` ("Pre-seeded UUIDs without other evidence are still rejected").
- **design.md §3.5**: the CLI-writes note now states the CLI pre-seeds for start + transfer/fresh children; the
  Hooks-write note says SessionStart validates (those paths) or records (native `--fork-session`).
- **end-user/session.md**: same corrections, and fixed a self-contradictory resume section — the stale "never-launched →
  launch in-place / previously-used → fork" bullets now describe reattach-by-default vs `--fresh`-derives-a-child,
  matching the adjacent intro/Gates text and `_reconnect_in_place` (`--resume`, no `--fork-session`).

**Verification**: Docs-only — no code change (the code was already self-consistent: `models.py:400` comment, the
start/fork launch paths, and `_is_resumable_session` all agree). Grep confirms no stale "not pre-seeded" / "None until
Claude starts" / "non-null means used" claims remain outside `done/`. `make pre-commit` clean.

### Fix: `project_root` consistently git-common-dir-derived (workspace_scope Slice 1)

**Goal**: Sessions started in a **manually**-created linked worktree (`git worktree add`, then `forge session start` —
not `--worktree`) did not group under `--scope workspace`, defeating the core motivation of the `workspace_scope`
proposal. Fix the latent `project_root` derivation bug rather than layer a new scope concept over it.

**Key changes**:

- `SessionManager.start_session` and the same-directory `fork` path derived `project_root` via
  `find_project_root(worktree_path)`, which returns the *worktree's own* root for a linked worktree (its `.git` is a
  file). Both now route through the existing canonical `resolve_project_root()` (`get_main_repo_root` + graceful non-git
  fallback), so `project_root` is the shared git-common-dir root for every worktree of a repo — aligning the code with
  design.md §3, which already names `get_main_repo_root()` as the `project_root` identity source. Removed the now-unused
  `find_project_root` import.
- Minor improvement: a `.forge/`-enabled non-git directory no longer raises mid-`start_session`; `project_root` degrades
  to the directory itself, consistent with how `checkout_root` already falls back.

**Verification**: New regression `tests/regression/test_bug_workspace_scope_manual_worktree.py` (confirmed failing on
the old derivation — `wt-sess` missing from `--scope workspace` — and passing after the fix). 1031 session+ops unit
tests pass; `make pre-commit` clean. No design-doc change (the fix makes code match the existing §3 contract).

### Rename `--scope repo` → `--scope workspace` (workspace_scope precursor, clean break)

**Goal**: Resolve concern #1 from the `workspace_scope` proposal review — the proposed `--scope workspace` would have
been a synonym of the existing `--scope repo` (the logical-repo / worktree-family grouping). Rename the flag value
instead of adding a second name, so the CLI keeps one scope vocabulary.

**Key changes**:

- **Flag value renamed across all four command families** that share the `repo|project|all` scope: `forge session list`,
  `forge clean`, `forge memory status|shadows *`, and the `%session list` / `%clean` direct commands. `VALID_SCOPES`
  (`core/ops/session.py`, `core/ops/gc.py`), Click `Choice`/`default`/help, error messages, and the `%`-dispatcher
  defaults all use `workspace`. `session list` + `%session list` defaults flip `repo` → `workspace` (identical
  filtering, new name); `clean`/`memory`/`%clean` keep their existing `project` defaults.
- **Clean break (research-preview)**: `--scope repo` now fails with Click's native "invalid choice" — no alias or
  tombstone (coding-standards §5). This is a pure CLI-surface + `--json` `"scope"` output rename; the durable session
  index is untouched (the `project_root` field is kept — workspace membership is still derived from it, not stored).
- **Vocabulary swept** in prose/docstrings: "repo-scoped"/"repo-wide" → "workspace-scoped"/"workspace-wide" across
  design.md §3/§3.2/§4.0, design_appendix §B, end-user `session.md`, `diagrams.md`, and internal resolution docstrings.
  **Preserved deliberately** (workspace_scope card Open Q1, deferred): the `resolve_session_repo_wide` function symbol,
  the `project_root` field name, and the git-identity term "logical repo". `done/` board cards left as historical
  snapshots (board contract).

**Breaking change / reset**: `forge session list --scope repo`, `forge clean --scope repo`,
`forge memory ... --scope repo`, and `%clean --scope repo` are removed — use `--scope workspace` (same behavior). Update
any scripts/aliases.

**Verification**: 438 unit+regression tests pass across the affected suites (session ops, gc, resolution, clean CLI,
session/memory CLI, `%`-dispatcher, shadow curation, cross-project regression). Final grep confirms no `--scope repo` /
"repo-scoped" / "repo-wide" prose remains outside `done/`. `make pre-commit` clean.

## 2026-06-06

### Remove CLI rename-migration tombstones (clean break at `0.4.0`)

**Goal**: Strip the hidden, error-only rename/migration tombstone commands, flags, and stale-state guards from the CLI
so the surface stays pristine. Solo research-preview fork; no external users to shield from the breaks.

**Key changes**:

- **Bucket 2 — command/flag tombstones removed**: `forge usage`, `forge handoff run`, `forge session handoff`,
  `forge session memory` (two whole modules deleted: `session_handoff.py`, `session_memory.py`); `search -q`/`--limit`/
  `--scope`; `memory track --as`/`--session`; `--resume-mode handoff`; and the `--force` "deprecated alias for --yes" on
  `auth`, `backend`, `config`, `claude preset`, `extensions disable`, `proxy delete`, `proxy template reset`. Functional
  `--force` kept where it does real work (`proxy stop`, `extensions enable/sync`, `session delete`/`resume`,
  `hooks enable`).
- **Bucket 3a — stale-state migration guards removed**: `_RENAMED_KEYS`/`_REMOVED_KEYS` + `_prune_renamed_keys`
  (config), `_REMOVED_STRATEGIES` + `scan_stale_passports` + `memory list` stale-warnings (memory/passport). Both
  degrade cleanly to the pre-existing generic paths ("Unknown keys (ignored)" warning; `VALID_STRATEGY_NAMES` rejection)
  — no silent loss.
- **Bucket 3b — schema_version validators KEPT**: `cost_logger`/`audit_logger` forward-compat checks are not tombstones
  (they guard newer-than-current data, mandated by the durable-state contract).
- **`forge session context` excluded**: verified functional (`--field`/`--json` extraction), not an error-only stub.
- **Policy realigned to the implementation**: `coding-standards.md` §5/§6 and `design.md` §4.0 now say command/option
  removals are clean breaks (rely on the framework's native "no such command/option"); durable-state rejection with an
  actionable reset/migration message is preserved separately.
- **Tests + QA updated**: deleted the tombstone-specific tests; migrated `proxy delete`/`template reset` `--force` →
  `--yes` (and `--yes --kill-adopted` where the adopted-kill path is asserted); QA `7-costs.md` §7.14 probe removed +
  reset section renumbered; `11-config.md` and `4-proxy.md` `--force` → `--yes`.

**Verification**: `uv run pytest -m "not integration" tests/src tests/regression` → 5681 passed, 0 failed.
`make pre-commit` clean. CLI smoke: removed names now return Click "No such command/option"; all command groups still
load.

### Closeout: metric-evidence card → `done/`, version `0.4.0` (PR #18)

**Goal**: Close out the metric-evidence card and cut the release version for the PR #18 line.

**Key changes**:

- **Version `0.3.0` → `0.4.0`** (`pyproject.toml` + `src/forge/__init__.py`). Minor bump (0.x convention for breaking
  changes): PR #18 carries breaking CLI changes (`forge proxy costs` → `costs show`, `forge usage` → `forge activity`)
  plus the cost-honesty overhaul, `costs reset`, and the weekly-quota status line.
- **Card moved `doing/ → done/`** via `git mv` (history preserved), as a commit on PR #18 so it lands in `done/` on
  `main` at merge. Until then `main` still shows it under `doing/`.
- **Durable lessons NOT auto-promoted**: they stay drafted under impl_notes' "Proposed Promotions" subsection awaiting
  human review (closeout step 3 is a human gate).

**Verification**: `import forge` → `0.4.0`; no test hardcodes the version (consistency tests compare against
`forge.__version__` at runtime); `make pre-commit` clean.

### Added: weekly quota + heat-mapped rate-limit display in the status line (metric-evidence, PR #18)

**Goal**: Surface the **weekly** quota (the limit that actually bites Max/Pro users) in the status line, which
previously showed only the 5h window.

**Key changes**:

- **Both windows now shown**: Claude Code already sends `rate_limits` as `{five_hour, seven_day}`, but
  `_extract_short_window` returned only the 5h window and discarded `seven_day`. Replaced it with `_extract_windows`
  (clean break) and `format_rate_limits` now renders `5h:N% · 7d:M%`.
- **Heat-mapped**: each window's % is colored by its own usage on the **shared context gradient** (`CTX_*`, soft green →
  hot coral) via a new `_heat_color`, so the binding window stands out — same color scheme as the context bar, but with
  quota-appropriate bands (\<25/25-49/50-74/75-89/90-100), not the context bar's auto-compact-skewed thresholds.
- **`RL` prefix dropped** (the `5h`/`7d` labels are self-evident) and the **reset countdown binds inline** to the hotter
  window with a `↻` glyph (`7d:52%↻1d`) so it can't be misread as the trailing session duration.
  `_format_reset_countdown` gained day formatting (`Nd`) for weekly resets.
- **Docs/QA synced**: `config.md`, `design_appendix.md`, `auth_cost_metric.md`, QA `8-status-line.md`; `RL:` assertions
  across `test_statusline_billing.py` + `test_status_line_integration.py` updated to `5h:`.

**Verification**: 164 status-line unit tests pass (incl. `TestHeatColor`, both-window/inline-`↻`/day-countdown cases);
live render `5h:8% · 7d:52%↻1d` confirmed; `make pre-commit` clean.

### Added: `forge proxy costs reset` + `costs` → `costs show` group split (metric-evidence, PR #18)

**Goal**: Give users a one-command "reset all recorded costs to zero" path (requested while manually testing the
branch), covering every telemetry plane Forge writes — without touching the separate audit plane.

**Key changes**:

- **New `forge proxy costs reset`**: wipes the three telemetry planes — request cost logs (`~/.forge/costs/requests/`),
  verb cost logs (`~/.forge/costs/verbs/`), and the usage-attribution ledger (`~/.forge/usage/events/`) — **plus** the
  derived status-line cost cache (`~/.forge/cache/statusline/fcost-*.json`) so `forge +$Y` recomputes from the empty
  ledger instead of replaying a cached value within its TTL. Audit (`~/.forge/audit/`) and the unrelated transcript
  cache-hit entries are deliberately spared. `--dry-run` lists without deleting; `--yes` skips the confirm prompt.
- **Honest restart caveat**: prints a `Tip:` naming `forge proxy stop/start <id>` because a live proxy holds its cost
  totals (`ProxyMetrics` — cumulative-cost header, snapshot, `forge proxy costs show`) **and** cap counters in a
  separate process the CLI cannot reach — file deletion alone does not zero a running proxy's reported cost or caps.
- **CLI shape (research-preview clean break)**: `costs` had to become a group (Click consumes the first positional as a
  subcommand, colliding with the optional `proxy_id`). `forge proxy costs [id]` → `forge proxy costs show [id]`; bare
  `forge proxy costs` now prints group help ("groups orient, leaves act"; precedent `forge config` →
  `forge config show`).
- **Docs/QA synced**: design.md/appendix, end-user `proxy.md`/`session.md`/`config.md`, `auth_cost_metric.md`, and
  source/test comments naming the runnable view all moved to `show`; QA `7-costs.md` invocations → `show` + new §7.15
  reset section (index test-count 532 → 537). Board change_log/card *history* left intact (not rewritten).

**Verification**: `test_proxy_costs.py` 25 passed (incl. `TestCostsReset`: dry-run-lists, wipe-3-planes,
clears-fcost-cache/spares-cache-hit, audit-spared, confirm-abort, empty-noop); manual smoke in `/tmp/forge-reset-test`
(dry-run listed, `--yes` wiped shards + printed the restart tip, post-reset `show` read zero). `make pre-commit` clean.

### Phase 6 follow-up: deferred cleanups folded in before closeout (metric-evidence)

**Goal**: Close the three verified-but-narrow / cleanup follow-ups from the PR #18 review on the branch (rather than
deferring to separate `todo/` cards), so the `doing/ → done/` move carries no known debt. No behavior change to the
shipped cost-honesty model — these are a perf bound, a dead-branch removal, and three DRY extractions.

**Key changes**:

- **Bound the `forge_cost` scan**: `sum_forge_added_cost` gained `since: datetime | None`, threaded to
  `read_usage_events(period_start=…)`; the status producer derives it from the manifest `created_at` (defensive
  `parse_iso`, unbounded fallback). The opt-in `forge +$Y` poll no longer re-parses the whole uncapped ledger; the bound
  is loss-free (an event can't predate its session).
- **Removed the dormant `stream-json` parse branch** (chose remove over thread-through — Forge reads headless output in
  batch, where `json` is equivalent; streaming stays a proxy concern). Dropped the `output_format` param from
  `_find_result_object`/`parse_headless_envelope` and left a seam note at both halves so a future streaming mode wires
  parser **and** request side together. Closes the asymmetry where the request side could emit `stream-json` the parser
  silently dropped.
- **DRY extractions**: the `isinstance(record, dict)` JSONL guard now lives once as `core.state.decode_json_object` (5
  readers routed through it); `proxy_costs.py` verb/model/total aggregation shared via `_aggregate_by_verb` /
  `_aggregate_by_model` / `_request_cost_totals` (table + JSON can't drift); `emit.py`'s **direct-path** one-reporter
  precedence shared via `_direct_cost_provenance` — the **proxied** path stays per-caller (verb attributes the snapshot,
  a worker stays unattributed to avoid double-counting the verb aggregate).

**Verification**: 2608 unit tests pass across the affected packages (`core/{reactive,invoker,usage,state,ops}`, `proxy`,
`cli`); new tests pin each invariant — `decode_json_object` guard (`test_io.py`), `since` bound
(`test_usage_summary.py`), NDJSON→raw-text fallback (`test_bug_headless_envelope_parse.py`), and the shared-direct /
divergent-proxied emitter rule (`test_emit.py::TestDirectCostProvenance` + `TestVerbWorkerPrecedenceInvariant`).
`make pre-commit` clean (ruff/black/isort/mypy/pyright/mdformat/gitleaks). Internal cleanup — no design-doc change.

### Phase 6 review fixes: PR #18 adversarial review — headless retry/latch + cost-honesty edges

**Goal**: A max-effort adversarial review of PR #18 (9 finder angles, each finding independently verified) surfaced one
real correctness cluster plus several narrow honesty/robustness edges; fix the merge-gating ones on the branch before
the `doing/ → done/` lane move.

**Key changes**:

- **Headless `--output-format json` retry/latch (the merge gate)**: tightened `_REJECTION_RE`
  (`core/reactive/headless_json.py`) — dropped the bare `--output-format` alternative so a transient error echoing the
  command line (e.g. a 529 printing the argv) no longer misfires the retry, which latched the JSON capability off
  **process-wide** AND **double-billed** a proxied retry (no `request_id` dedupe on the cost log). `run_parallel`
  (`core/invoker/claude.py`) retry spawn now mirrors the primary spawn's post-register `cleanup_started` re-check +
  self-reap, closing a cancellation-hang gap (`shutdown(wait=True)` could otherwise block `timeout_seconds`).
- **Launch resurrection guard**: `record_launch_confirmed` (`cli/launch_confirmation.py`) gained the `exists()`
  preflight its sibling `_infer_launch_confirmation` documents — a session deleted mid-launch is no longer resurrected
  as a lock-only directory.
- **Negative-delta clamp**: `_compute_delta` (`core/reactive/cost_tracking.py`) clamps every delta `>= 0`, so a proxy
  restart mid-verb can't log a negative cost that inflates the "Interactive" residual.
- **`forge +$Y` predicate pinned**: `sum_forge_added_cost` now counts `{reported, gateway_calculated}` (not
  reported-only) and excludes `inferred`/`unknown`/`unavailable` + the harness route via a typed
  `ROUTE_CLAUDE_INTERACTIVE` constant (no bare string compare on a load-bearing exclusion).
- **Legacy verb fallback removed**: `_verb_cost_reported` (`cli/proxy_costs.py`) trusts `cost_measured` only; a pre-PR
  record (its total was a deleted-catalog estimate) reads as unavailable, never resurrected as reported.

**Verification**: 5294 unit pass; blast-radius 1041 green; the new deterministic retry-cancellation race test 10/10;
`make pre-commit` clean (mypy/pyright incl. the new `frozenset[Confidence]`); `test_status_line_integration.py` (13)
green on the real wheel CLI. Fixes committed as `97b2098`.

**Deferred (recorded as checklist debt, non-blocking)**: (1) `sum_forge_added_cost` reads the whole uncapped ledger per
poll — add a session-start lower bound; (2) dormant `stream-json` parse branch — thread `output_format` through
`parse_headless_envelope` or remove the advertised support; (3) duplication cleanup (verb/model aggregation in
`proxy_costs.py`, direct-cost precedence in `emit.py`, the ×4 `isinstance(dict)` JSONL guard).

### Phase 6 follow-up: QA checklist metric-evidence coverage (audit-driven)

**Goal**: After the Phase 6 docs/CLI cleanup, an adversarially-verified audit of `src/skills/qa/` + `docs/end-user/`
found the end-user docs clean but six QA-checklist gaps (3 confirmed + 3 completeness-critic) where a regression in this
card's headline cost-honesty behavior would pass the release-validation QA gate. Closed them on the branch.

**Key changes** (all in `src/skills/qa/resources/checklist/`):

- **§3.4 masking misfire (real defect)**: "values are masked (never shown in full)" contradicted the non-secret
  `OPENROUTER_BASE_URL`/`LITELLM_BASE_URL` (shown in full) — a correct system would have *failed* it. Scoped masking to
  secret values; added a `(default)` non-secret render assertion.
- **§7.12 `forge activity` cost honesty**: the fixture already triggers `cost_partial`/`~`/footnotes but asserted none —
  added `cost_partial=True total_cost_micro_usd=2050` (JSON) + a `~`-marker / footnote human-render check.
- **§7.13 (new) cost provenance**: isolated `qa-prov` fixture proving a null-cost request lands in
  `unavailable_requests` and is excluded from the dollar total (never priced from a local table); isolated so the shared
  `qa-fixture` 3-request invariant (7.5/7.6) is untouched.
- **§7.14 (new) rename tombstone**: bare + stale-args `forge usage` exits non-zero naming `forge activity` (no "No such
  option").
- **§8.5 (new) `forge_cost`/`forge +$Y` segment**: opt-in segment exercised end-to-end — seeded reported events render
  `forge +$0.25`, a `$9.00 claude_interactive` event is **excluded** (the load-bearing harness exclusion), and a
  no-reported-cost session renders **no** segment.
- **§5.21**: session-end one-liner cost names the `~` best-effort shape (no ` est`). Index `test-count` 512 → **532**
  (recounted actual `- [ ]`, clearing prior drift); version 1.0.21 → 1.0.22.

**Verification**: every new `<!-- auto -->` fixture validated against real code on the host — `sum_forge_added_cost` =
250000 (harness + unavailable excluded) and `format_forge_cost` → `+$0.25` / `None` (8.5);
`build_session_activity_summary` → 2050 / `cost_partial=True` (7.12); `forge proxy costs qa-prov` → reported=1,
unavailable=1, total=2500 (7.13); `forge usage` → exit 1 "has been renamed" (7.14). QA state parser re-parses to exactly
532 assertions; 206 skills/skill-content unit tests pass; `make pre-commit` clean. `docs/end-user/` needed no change
(audit confirmed cross-links + per-surface labels already correct).

### Phase 6: Docs & CLI cleanup + rename `forge usage` → `forge activity` (metric-evidence-simplification)

**Goal**: Fold the card's remaining bugs (#5–#8) and make the per-session command's name honest — it reports Forge
*automation* activity (supervisor, memory writer, workflow verbs + policy decisions), not total interactive usage. Final
docs/CLI pass before closeout; complete on branch (PR/merge/lane-move owned by the human).

**Key changes**:

- **Bug #7 / G2 (flipped to clean break)**: renamed `forge usage` → `forge activity` (`cli/usage.py` →
  `cli/activity.py`, `activity_cmd`; registered in `main.py`). Hidden, **flag-tolerant** `usage` tombstone
  (`ignore_unknown_options` + `UNPROCESSED`, the `memory_writer.py` pattern) so `forge usage <s> --all --json --days 7`
  reaches the rename message, not Click's "No such option". Help/output state the scope honestly and the blanket
  "Estimated spend only" label is corrected to "reported-or-estimated, best-effort" (Phase 5 made direct-run cost
  reported). The "usage" **ledger** plane name is unchanged — only the command moved (it now matches the internal
  `build_session_activity_summary`).
- **Bug #8**: verified **clean, not swept** — a scoped grep found every "exact"/"authoritative" hit applied to tokens,
  `request_id` joins, enum names, or `forge proxy costs` authority; no unsafe dollar prose survived Phases 2–5.
- **Bug #5**: `OPENROUTER_BASE_URL` (non-secret connection value) added to both credential tables;
  `anthropic-passthrough` added to `anthropic-api.unlocks_features` (`capabilities.py` + test) and a "which auth?" row.
- **Bug #6**: `auth_ignore_env` docs reworded — it changes the key **source** (file vs env) for both interactive and
  headless; the interactive/headless separation is `interactive_anthropic_api_key` (Phase 4). Cross-referenced.
- **Surface table**: new user-facing "which surface answers which question?" table in `proxy.md` (`forge proxy costs` vs
  `forge activity` vs status-line `cost` vs `forge +$Y`), cross-linked from `session.md` + `config.md`.
- **`auth_cost_metric.md` folded** to an internal map: banner + links to design.md §3.14 / appendix §A.8/§A.9/§A.13;
  durable reference kept (three planes, resolution chain, file index); the Phase-4-falsified findings **rewritten as
  resolved** (F1/F2, `has_api_key` deletion, billing-mode-as-declaration); superseded operator playbook + proposals
  (P1/P2 shipped in Phase 4) deleted.

**Breaking change / reset**: `forge usage` is removed — use `forge activity` (same args/flags). The old command is a
hidden tombstone that exits non-zero naming the replacement; update any scripts/aliases. Research-preview clean break,
no migration.

**Verification**: 1582 `tests/src/cli` unit tests pass (incl. 9 `test_activity.py` + 2 flag-tolerant tombstone tests) +
34 `test_capabilities.py` (incl. the `anthropic-passthrough` assertion); guard greps clean (`forge usage` → only the
tombstone + rename notes; no unsafe dollar "exact"/"authoritative"); `forge activity --help` + both `forge usage`
tombstone forms smoke-tested; `make pre-commit` clean. Integration: the renamed-command test
`test_session_commands_integration.py::TestActivityCommand` ran green (`-k Activity` → 1 passed, 5.8s, real wheel CLI in
Docker); `test_audit_plumbing.py` is comment-only (optional re-run before merge). Card stays in `doing/` — awaiting
merge to `main` for the `doing/ → done/` lane move.

## 2026-06-05

### Phase 5: Headless runtime reporters (metric-evidence-simplification)

**Goal**: Close the cost-honesty gap on the headless `claude -p` path — let the Claude runtime self-report cost/usage
(closing today's `unavailable` on direct verbs) without ever estimating, while a proxied run keeps the proxy figure
authoritative; surface Forge's additional headless spend as the opt-in `forge +$Y` status-line segment. Claude-only
(Codex deferred to `runtime_abstraction`).

**Key changes**:

- **5a spike (hard gate)** settled an undocumented contract: `claude -p --output-format json` (2.1.165) emits a JSON
  **array** with cost/usage in the terminal `result` element, not the documented single object. DECISION: GO (broad,
  direct). Capability guard = **retry-once-and-latch** (no version probe). Verdicts encoded as named constants.
- **Envelope unwrap (5b)**: shared `core/reactive/headless_json.py` (latch, `prepare_json_argv`, `usd_to_micros`) +
  `parse_headless_envelope` (never raises; array/object/stream-json/raw-text). Both runners (`run_claude_session` +
  `ClaudeHeadlessInvoker`) inject the flag through the shared helper, retry once on rejection, and unwrap `.result` into
  `.stdout` so every text consumer (supervisor/memory-writer/curation) is byte-for-byte unchanged.
- **Cost precedence (5c)**: exactly **one** reporter per run — proxied → `forge_proxy`/`verb_snapshot_estimated`
  (snapshot tokens; Anthropic-priced self-cost ignored, no double-count); direct → `claude_code`/`runtime_native`
  (self-cost) or `provider_usage_exact`/`unavailable` (tokens-only). Tokens follow the cost source (no mixed
  provenance). First emission of `claude_code` + `runtime_native`. Same precedence per-worker.
- **`forge +$Y` (5d)**: opt-in `forge_cost` segment; `sum_forge_added_cost` sums reported cost **excluding
  `route=claude_interactive`** (the card's no-blend rule); time-only `read_or_compute_session_cost` throttle (keyed on
  Forge identity not the Claude UUID, caches a legit 0, fail-open uncached); `forge_cost_ttl` config (default 10).
- **Docs (5f)**: `design.md` §3.14, `design_appendix.md` §A.13 + §A.8, `vocabulary.py`/`ledger.py` comments synced;
  corrected a stale `inferred`→`reported` left from Phase 2.
- **Review follow-ups**: (1) proxied token-only snapshots now read `verb_snapshot_estimated`, not `unattributed` (a
  token-carrying event must not claim "no figure"); (2) the `run_parallel` JSON-flag retry is now a tracked `Popen` (own
  process group, registered in `children`) so it stays terminable under cancellation; (3) the **team supervisor**
  (`policy/team/handlers.py`) is now instrumented (mirrors the semantic supervisor; emits before the success gate so
  failures are attributed); (4) `docs/end-user/config.md` gains `forge_cost`/`forge_cost_ttl`; (5) the spike's
  `reproduce.sh` detects `timeout`/`gtimeout` (macOS portability); (6) name-scoped ledger aggregation documented as a
  known limitation.

**Verification**: 5287 unit tests pass (13 new/extended files: envelope parse, unwrap, token-only, json-flag-compat on
**both** runners, is_error→status, `usd_to_micros` parity, verb+worker precedence (incl. proxied token-only),
`sum_forge_added_cost`, statusline + session-cost throttle, team-supervisor attribution). **6 real-Claude Docker tests
pass on 2.1.165** (98s) — the 5a verdict and the full self-report pipeline (run → envelope → emit → ledger) confirmed
end-to-end; updated memory/workers assertions (direct verb/worker now `runtime_native`). `make pre-commit` clean
(ruff/black/isort/mypy/pyright/mdformat/gitleaks). Follow-up (non-blocking): `usd_to_micros` vs the proxy `round()`
diverge ≤1 micro at half-micro fractions only (separate planes), pinned by test.

### Phase 4: Status-line honesty (metric-evidence-simplification)

**Goal**: Make the status line honest about billing and add the user control the auth/cost audit demands — never infer
an API payer from key presence, record + show how a session reached the model, and let users keep a key out of
interactive sessions.

**Key changes**:

- **Bug #1 (billing honesty)**: `RenderContext.billing_mode` `auto` returns `ambiguous` instead of inferring `api` from
  `ANTHROPIC_API_KEY`; `format_billing_cost` already shows quota-if-`rate_limits`-else-`≈$`. Golden `$0.42`→`≈$0.42`;
  the old divergence test became a key-invariance test. Removed the now-dead `RenderContext.has_api_key`.
- **G4 (env omit)**: flat `interactive_anthropic_api_key: inherit|omit` on `RuntimeConfig`; one source-aware
  `apply_interactive_api_key`/`compute_interactive_api_key_decision` (env.py) over new
  `resolve_env_or_credential_with_source` (template_secrets.py). Applied LAST via the interactive wrapper in `invoke.py`
  (after extra_vars/unset), so it's authoritative and the recorded `source` matches the child. Headless callers
  untouched.
- **Sidecar omit**: `session_lifecycle` sets `FORGE_OMIT_INTERACTIVE_KEY=1`; `docker/entrypoint.sh` unsets the key for
  Claude *after* the in-container proxy captured its upstream credential (works for anthropic-upstream templates).
- **G3 (launch metadata)**: additive `LaunchConfirmed` under `confirmed.launch` (models.py); centralized best-effort
  `record_launch_confirmed` called from start/resume + host fork closures (session_fork.py) + sidecar.
- **Visible `launch` segment**: opt-in (off by default) `format_launch`/`_produce_launch` renders
  `<route>·key:<posture>`.
- **Deferred**: `forge +$Y` Forge-additional-cost segment → Phase 5 (sparse until headless reporters report cost).
- **Docs**: design_appendix §A.7/§A.8 + end-user config.md/authentication.md (new key, corrected `cost_mode=auto`).

**Verification**: Focused unit suites + full blast-radius sweep (2991 passed); `make pre-commit` clean
(ruff/black/isort/mypy/pyright/mdformat/gitleaks); integration `test_status_line_integration.py` (13, incl. real-CLI
launch-metadata + omit recording) and `test_sidecar_omit.py` (1, `/proc` proof Claude lacks the key while the proxy
keeps it) green.

### Phase 2 follow-up: Fix panel cost-visibility canary (wrong monkeypatch target)

**Goal**: Make the panel integration test previously filed as a "pre-existing" failure
(`test_panel_with_subprocess_proxy_records_verb_cost`) pass, so the panel verb-cost path is actually real-wire verified
rather than left red.

**Key changes**:

- Root cause was a **test bug**, not a product bug. The test registered its canary model via
  `monkeypatch.setitem(DEFAULT_MODELS, …)`, but `forge workflow panel --models <name>` resolves through
  `resolve_model_specs`, which validates an explicit `--models` against `AVAILABLE_MODELS` (the full registry).
  `DEFAULT_MODELS` is only the no-args fallback quorum, so the canary read as `Unknown models`. Patched it into
  `AVAILABLE_MODELS` — the registry the resolver actually reads.

**Verification**: `test_cost_visibility_e2e.py::test_panel_with_subprocess_proxy_records_verb_cost` passes on real
OpenRouter (4.2s); cost-visibility matrix now 5/5. Diagnosis confirmed with an isolated `resolve_model_specs` repro
(DEFAULT_MODELS patch → `Unknown models`; AVAILABLE_MODELS patch → resolves).

### Phase 2 follow-up: Verb cost-evidence in `forge proxy costs` + docs sync (review fixes)

**Goal**: Close two review findings on the shipped Phase 2 work — the verb display ignored the cost-evidence flag
(reintroducing unknown-as-zero), and several proxy/request dollar-cost references still said "estimated."

**Key changes**:

- **Verb display now reads evidence, not a number.** `_display_by_verb` / `_output_json` gated cost-evidence on a
  numeric `total_cost_micros` (always int, `0` for a passthrough window), so a `cost_measured=False` verb rendered
  `reported: true, cost_micros: 0`. Added `_verb_cost_reported` (trusts `cost_measured`; legacy records fall back to
  `total > 0`); `_scope_verb_records_to_proxy` re-derives `cost_measured` for the scoped subset from per-proxy
  `reported_request_count`. The request display was already correct via nullable `_reported_micros`.
- **Docs sync.** Aligned remaining "estimated" proxy/request dollar-cost language to reported-or-unavailable across
  `auth_cost_metric.md`, the normative `design.md` / `design_appendix.md` (they contradicted the synced authority
  table), and end-user/{proxy,config,session}.md. Preserved the attribution-snapshot sense (`estimated:true` verb field,
  `verb_snapshot_estimated` enum, concurrency caveat) as accurate.

**Verification**: `test_proxy_costs.py` +5 (reproduces `cost_measured=False` + total 0 → `reported:false`; reported-$0;
legacy fallback; scoped recompute); 23 focused tests pass; `make pre-commit` clean (commit `b95500d`).

### Phase 2: Cost source replacement — Forge is not a cost oracle (metric-evidence Slice 2)

**Goal**: Stop inventing dollars from a local price table. Proxy cost is now **reported-or-unavailable**: Forge records
the cost a route actually reported and says `unavailable` otherwise, then deletes the price catalog so it cannot
re-enter the accounting path. Landed in three tree-green steps (1: nullable+provenance plumbing → 2: reported-cost
capture → 3: de-catalog), Step 2 integration-verified before Step 3 removed the catalog safety net.

**Key changes**:

- **Reported-cost capture, full matrix.** Added a `cost_usd` carrier on `CompletionResponse` **and** `StreamEvent`
  (review-found: streaming had no carrier). OpenRouter cost comes from the response body (`usage.cost`), extracted in
  the shared `openai_compat` converter (covers both clients, stream + non-stream). LiteLLM-gateway cost comes from the
  `x-litellm-response-cost` **header**, recovered by switching non-streaming chat **and** the Responses-API branch to
  `with_raw_response.create().parse()` + `_merge_header_cost`. The proxy threads cost as an internal
  `_reported_cost_micros` key (non-stream) / usage-chunk field (stream, parked in the SSE converter's `final_usage` like
  `cached_tokens`), never leaked to the client.
- **Provenance at the proxy.** `_calc_and_log_cost` stamps `reporter` + `confidence` from
  `config.proxy.preferred_provider` (openrouter→`reported`, litellm→`gateway_calculated`); unreported →
  `cost_micros=None` / `confidence="unavailable"`, tokens still logged, `cost_tracker.record` + metrics cost
  accumulation skipped.
- **Verb cost-evidence (review-found conflation fix).** `ProxyCostDelta.reported_request_count` +
  `VerbCostResult.cost_measured` (derived from that delta, not `bool(deltas)`); `emit.py` logs `cost_micro_usd=None` /
  `confidence="unavailable"` for a passthrough verb that moved tokens but reported no cost — never a fabricated measured
  $0.
- **Catalog deleted** (zero surviving callers): `core/models/pricing.py`, `core/data/pricing.yaml`, the `core/models`
  re-exports, and `test_pricing.py` + `test_bug_pricing_fallback_logs.py`.
- **Header evidence gate** (Step 1): `X-Request-Cost` omitted when this request's cost is null (fixes a `None/1_000_000`
  crash); `X-Cumulative-Cost` omitted until a reported-cost event exists
  (`reported_request_count`/`unavailable_request_count` on `ProxyMetrics`).

**Breaking change / reset**: Plane-1 cost record fields `estimated:true` and `pricing_source` are **removed**, replaced
by `reporter` + `confidence` (research-preview clean break; `COST_SCHEMA_VERSION` stays `1` — new records omit the old
keys, legacy records read with defaults). **Spend caps now fire only for routes that report cost**:
Anthropic-passthrough and LiteLLM-**streaming** dollar caps become no-ops (tokens still tracked). No user action
required; existing logs read fine.

**Verification**: 5531 unit+regression pass; mypy/pyright clean; `make pre-commit` clean. Real-wire integration
(`test_cost_visibility_e2e.py`) confirmed the matrix with the catalog removed — OpenRouter `reported`
(stream+non-stream), LiteLLM `gateway_calculated` (non-stream), LiteLLM **streaming**
`cost_micros=None`/`confidence="unavailable"` (the documented gap: the header predates the cost and the gateway puts
none in the final usage chunk). Design docs (§3.14, §A.9, §A.13), `auth_cost_metric.md`, and the QA `7-costs.md`
fixtures updated to the reported/unavailable model.

### Phase 3: Remove `cap_mode` & strict pre-flight (metric-evidence Slice 3)

**Goal**: Collapse the proxy's two cap behaviors (`post` / `strict`) into one — post-event enforcement — by removing
`cap_mode` and the strict pre-flight cost estimate. Strict was the cost-oracle pattern in the cap path: it priced an
unsent request from the local catalog and blocked on that guess.

**Key changes**:

- **`cap_mode` removed entirely** from `CostConfig` (field + `valid_modes` validation + load). The `costs` block is
  leniently parsed, so a stale `cap_mode:` key is rejected with an explicit tombstone in `_coerce_cost_config` rather
  than silently ignored — verified at both config-parse and the `forge proxy set` validate-before-write path.
- **Both strict pre-flight callsites deleted** (`server.py` passthrough + translated). With strict gone the whole
  estimation apparatus is orphaned and removed: the `_textish_chars` / `_estimate_input_tokens` helpers, the cap-path
  `calculate_cost` imports, `check_cap`'s `projected_cost_micros` parameter, and the always-False `CapResult.projected`
  field + "Projected " message prefix. The local price catalog no longer touches cap enforcement (the post-flight
  logging catalog call is separate — Phase 2). `on_cap_hit` (reject/warn) is unchanged.
- Tests: deleted the strict-only regression file + strict unit tests; swept the removed `cap_mode=`/`projected`/old
  `check_cap` signature out of every surviving test (the type-checker, not a hand list, was the change-detector); added
  `tests/regression/test_bug_cap_mode_removed_key_rejected.py` (config-parse + CLI surfaces).
- Docs (evidence-neutral — shipped, not aspirational): `design.md` §3.7, `design_appendix.md` §A.9,
  `auth_cost_metric.md` §6, `end-user/proxy.md` (+ upgrade reset note), QA `7-costs.md`.

**Breaking change + reset**: `costs.cap_mode` is removed. An existing `proxy.yaml` carrying any `cap_mode:` line
(including the old default `post`) now refuses to load with an actionable message; remove the line. Research-preview
clean break — no migration. **Standalone decision** (recorded once so a future session doesn't pre-date it): docs say
caps are "enforced after each completed request, from accumulated recorded spend"; Phase 2 upgrades the wording to
"reported route cost" and makes cost nullable.

**Verification**: 924 proxy/config/regression unit tests pass + the new removed-key regression (4 cases);
`make pre-commit` clean. Proxy integration: 3/4 cost-visibility e2e pass (request path intact after the strict removal);
the 4th (`test_panel_with_subprocess_proxy_records_verb_cost`) is a pre-existing, unrelated failure (confirmed identical
on clean HEAD `c7402c3` — `monkeypatch.setitem(DEFAULT_MODELS, …)` not reaching the workflow model resolver).

### Phase 1: Metric-evidence schema & vocabulary pass (metric-evidence Slice 1)

**Goal**: Add the card's metric-evidence vocabulary (`route`/`reporter`/`confidence`) to the usage ledger **without
changing any accounting behavior** — the schema foundation every later phase builds on (Phase 2 reuses `Confidence` for
cost-log provenance; Phase 4/5 reuse `route`/`reporter`).

**Key changes**:

- New thin `core/usage/vocabulary.py` holds three `Literal` aliases (`Route`, `Reporter`, `Confidence`) with no I/O, so
  Phase 2's cost plane (`proxy/cost_logger.py`) can import `Confidence` without dragging in the ledger's dacite/lock
  machinery (`proxy → core` is the clean import direction).
- `UsageEvent` gains `route`/`reporter`/`confidence` — additive, defaulted (`confidence="unknown"`), re-exported from
  `core/usage/__init__`. **`USAGE_SCHEMA_VERSION` stays `1` — no bump, by decision**: additive defaulted fields change
  no meaning, require nothing, remove nothing, so a current reader loads pre- and post-change v1 records identically.
- The 4 emitters (`emit.py`) stamp **today's** provenance honestly — catalog-derived verb cost → `inferred`;
  structurally-no-cost routes (tagger via dummy-key LiteLLM, null-cost worker) → `unavailable`; `route` = how work
  reached the model; `reporter` = source of the *metric* evidence (tokens and/or cost). No dollar/token/`billing_mode`
  value changed. Phase 2 flips the `inferred` verb cost to `reported`/`gateway_calculated`; `route`/`reporter` are
  stable across that flip.
- **`confidence` is scoped to the event's own `cost_micro_usd`** only — orthogonal to `measurement_source` (token
  provenance). The tagger shape `measurement_source="provider_usage_exact"` + `confidence="unavailable"` is therefore
  not a contradiction: tokens were reported, dollars were not. A `source_refs`-joined cost record never upgrades
  event-local `confidence`. `unavailable` (route structurally reports no cost) is distinct from `unknown` (provenance
  never recorded; the pre-Phase-1 default), pre-declared so Phase 2 adds no enum value.
- Docs synced for shipped fields only: `design.md` §3.14, `design_appendix.md` §A.13 (Provenance row + 3 `Literal`
  definitions), `auth_cost_metric.md` §1 plane-3 row.

**Keep-at-1 tradeoff (documented once — do NOT "fix" it with a migration)**: a concurrently-running *pre-Phase-1* reader
hits `dacite(strict=True)` on the unknown `route` key and **drops** new records as `"malformed"` — it discards keys it
cannot model, it does not understand them. This is expected for additive fields under strict reads and acceptable
precisely because the usage ledger is best-effort, PID-sharded, pruned **local telemetry, not durable truth**. No reset,
no migration path is owed.

**Verification**: 58 targeted tests pass (`tests/src/core/usage/test_ledger.py` + `test_emit.py` + dependent read
surfaces `test_usage_summary.py`/`test_usage.py` + `test_bug_usage_workflow_double_count.py`); `make pre-commit` clean.
No integration run — pure host-side dataclass + JSONL round-trip (no Docker/`claude -p`/proxy path; contrast Phase 2/4).

## 2026-06-04

### Fix: cost/audit JSONL readers crash on valid-but-non-object lines (metric-evidence Phase 0)

**Goal**: A valid-but-non-object JSONL line (`[]`/`1`/`"x"`/`null`/`true`) must not abort cost/audit-plane log reads —
the metric-evidence card's self-contained, ship-first slice (Bug #4).

**Key changes**:

- Added the canonical `isinstance(record, dict)` guard (mirrors `core/usage/ledger.py:215-218`) to the four unguarded
  `.get`-after-`json.loads` readers: `read_cost_logs` (`proxy/cost_logger.py`), `read_verb_logs`
  (`core/reactive/cost_tracking.py`), `read_audit_logs` (`proxy/audit_logger.py`), and `CostTracker._parse_record`
  (`proxy/cost_tracker.py`). `read_audit_logs` (audit plane) was folded in by scope decision so no JSONL reader stays
  unguarded across cost/audit/usage.
- The three readers were genuine crashers (`AttributeError` is not caught by their `except OSError`, so one bad line
  aborted the whole read and crashed `forge proxy costs` / `forge proxy audit show`); `_parse_record` was an honesty fix
  — its caller already broad-excepts, so its test calls it directly.

**Verification**: new `tests/regression/test_bug_cost_log_non_dict_line.py` (3 readers × 5 values) +
`TestParseRecordGuard` (5) — all 20 verified to fail with the guards stashed, pass with them; 92 targeted tests green;
`make pre-commit` clean.

### Fix: status-line enhancement post-PR review — 5 findings (PR #16)

**Goal**: A second self-review pass after opening PR #16 surfaced five issues across the proxy GET / path, status-line
fail-open contract, a duplicated tier scanner, and two documentation claims; each fixed (two with regression tests).

**Key changes**:

- **F1 (proxy)**: `root()` now calls the idempotent `_ensure_runtime_state()` so a freshly-imported proxy GET / reports
  real config and exposes `metrics.costs.caps` before any POST warms the module (caps were load-order dependent; the
  `spend_cap` segment showed nothing on a fresh proxy).
- **F3 (fail-open)**: `render_segments` wraps each producer in `try/except` (one bad segment degrades to absent, never
  crashes the line); `_produce_cache_hit` guards the proxy metrics shape with `isinstance` like `_produce_spend_cap`.
- **F4 (parity)**: test asserting `explicit_tier_from_model` agrees with the proxy's `_tier_from_model_name` (its 1:1
  mirror) over a model corpus; shared-helper extraction deferred to keep `proxy.server` off the status-line hot path.
- **F2 / F5 (docs)**: qualified the "byte-identical default output" claim to the API billing path (the golden guard pins
  `ANTHROPIC_API_KEY`) + added a golden-scope test pinning the sole no-key divergence (`$`→`≈$`); generated
  `statusline.segments` config comment now lists all shipped names (`supervisor`/`policy`/`audit`/`drift`/`spend_cap`).

**Verification**: 5136 unit tests pass (`make test-unit`); 15 proxy metrics-integration (incl. the import-split cap
test); 2 new regression tests (`test_bug_proxy_root_caps_uninitialized.py`, `test_bug_statusline_producer_failopen.py`);
`make pre-commit` clean; PR #16 CI green (Tests, Pre-commit, CodeQL).

## 2026-06-03 (compacted)

Condensed per the board-contract size policy (decisions/breaking changes/deferred preserved; play-by-play dropped).

### runtime_abstraction Phase 4 follow-up: per-session usage visibility + fixes

- **`forge usage [session]` + session-end summary**: `read_usage_events(session=)` filter + pure
  `build_session_activity_summary` (design §3.12; ledger for run/error/token/cost, `confirmed.policy.decisions` for
  supervisor allow/warn/deny). Host/sidecar/fork converge on one `_post_exit_render`. Workflow verbs tagged
  `session=$FORGE_SESSION`; action tagger left untagged (documented). design §3.14/§4.0, appendix §A.13.
- **Sidecar usage-ledger mount**: `usage/` mounted rw (symmetric with audit/costs, proxy-id gated) so in-container
  supervisor/verb events survive `--rm`; integration-verified host-side after teardown.
- **Review fixes**: workflow double-count (an N-worker panel read as N+1 workflows) fixed by splitting worker events
  into `CommandUsage.workers`; supervisor-warning misattribution fixed (warnings now from the `semantic.supervisor`
  sub-decision only). Regressions for both.
- **QA-surfaced proxy bugs**: proxy accepts Claude mid-conversation `{"role":"system"}` messages (was a local 422);
  passthrough streaming errors surface their real status + malformed/non-object JSON -> 400/422; `smoke_test_proxy`
  resolves the passthrough client model instead of hardcoding `sonnet`; QA `start-container.sh` refuses a stale-revision
  running container (exit 3). Regressions + real-wire validated.

### Statusline Enhancement (Phases 1-5)

Config-driven status line shipped in five phases: (1) segment registry + lazy `RenderContext` + earthy palette/glyphs as
an output-level ANSI remap -- **break**: the flat `show_rate_limits` key removed -> opt-in `rate_limits` segment
(actionable reset message on load/set/reset); (2) billing-aware cost (`api`->$ / `subscription`->quota /
`ambiguous`->`≈$`)

- `rate_limits` object-shape fix + a sanity-capped reset countdown; (3) throttled file-backed `cache_hit` (a
  deduped-by-`requestId` transcript primitive matching the proxy's cache-read formula; hashed session-id key,
  runtime-only -- never raises); (4) four Forge-unique opt-in segments -- `supervisor`/`policy` over effective session
  state, `audit`/`drift` over proxy `GET /` truth, real-route drift; (5) spend-cap proximity (`_attach_cap_summary` ->
  `metrics.costs.caps`; a binding-window `cap:…` segment; sub-cent `_fmt_cap_money` precision). A golden no-op guard
  freezes byte-identical default output (API billing path); each phase shipped `make pre-commit` clean with
  `test_status_line_integration.py` green.

## 2026-06-02

### Phase 4: Review-pass hardening (4a / 4c / 4d)

**Goal**: Fix issues found reviewing the shipped Phase 4 slices before merge -- one concurrency race plus three
correctness/clarity gaps, each with a test.

**Key changes**:

- **4d cancellation race (spawn/register TOCTOU)**: `ClaudeHeadlessInvoker.run_parallel` could spawn a child between
  `Popen` returning and registering it in `children`; a `_cleanup` snapshot in that window left the child un-SIGTERMed,
  so `executor.shutdown(wait=True)` blocked on its `communicate(timeout)` (Ctrl+C hang + transient orphan). Fixed with a
  lock-guarded `cleanup_started` flag: a worker self-reaps a child registered after cleanup began, skips spawning once
  cancellation starts, and `shutdown(cancel_futures=True)` drops unstarted workers -- append and flag-read are atomic
  under `children_lock`, so each child is reaped exactly once.
- **4d cancelled workers no longer emit usage**: a cancelled job fell through to `_emit_worker` and was logged
  `status="error"`. Added a typed `HeadlessResult.cancelled` (keeps `error="cancelled"` for the review layer);
  `_emit_worker` skips cancelled -- one policy point.
- **4c direct-LLM `cached_tokens`**: `emit_direct_llm_usage` dropped `cached_tokens`; now copied from provider usage.
- **4a partial-origin marker**: pinned the both-or-neither `origin_run_id`/`origin_root_run_id` contract on
  `_memory_writer_env` with a comment + test, so the defensive fallback isn't mistaken for a parent/root bug.

**Verification**: `test_claude_invoker.py` + `test_emit.py` 24 passed (incl. new race + cancelled-emit + cached_tokens
tests) + `test_startup_queue.py` partial-marker test; mypy + pyright + `pre-commit` clean on changed files.

### Phase 4: Deferred integration validation (4a / 4c / 4d / 4f)

**Goal**: Run the CLAUDE.md-mandated Docker / real-`claude -p` integration deferred across the Phase 4 slices, now that
4a-4f have shipped, so every shipped slice has real-subprocess coverage (not just mocked unit tests).

**Key changes**: None -- validation-only run.

**Verification** (`./scripts/test-integration.sh <file> -v`):

- `test_policy_hooks.py` (4f, deterministic): 10/10 -- real `forge hook policy-check` (adapter->engine->responder, exit
  codes, manifest).
- `test_supervisor_e2e.py` (4a/4c/4f, deterministic harness): 4/4 (8.2s) -- `forge policy supervisor`
  aligned/divergent/infra-error + session-set wiring (covers 4a env stamping, 4c supervisor emission, the 4f
  `cli/policy.py:692` site).
- `test_real_claude_memory.py::test_real_handoff_review_only_smoke` (4a/4c, real Claude): PASSED -- real
  `forge memory-writer run` end-to-end (4a origin-identity marker plumbing + 4c emission).
- `test_real_claude_workers.py` (4d, real Claude): 2/2 (34.4s) -- real `claude -p --bare` fan-out via
  `ClaudeHeadlessInvoker.run_parallel` (the process-group spawn/cleanup/ordering the mocked unit tests can't reach).

**Pre-existing finding (NOT runtime-abstraction; surfaced by this run)**:
`test_real_claude_memory.py::test_real_shadow_curation_smoke` FAILS because it passes `--session` to
`forge memory track`, which PR #6 (`13f57db`, 2026-05-28, project-scoped memory passports) made invalid ("track ... does
not take a session"). Stale test from the #6 memory change -- `13f57db` is a pre-branch ancestor and this branch touches
neither `cli/memory.py` nor the test. Latent because `slow` real-Claude tests are rarely run. Needs a separate test-only
fix to the post-#6 shadow-curation invocation; tracked for whoever owns #6's surface.

## 2026-06-01 (compacted)

Condensed per the board-contract size policy (dates, decisions, breaking changes, deferred items, and design.md pointers
preserved; per-file play-by-play dropped -- full detail in git history).

### runtime_abstraction Phase 4 (Slices 4a-4f): runtime-abstraction core

- **4a run-tree env contract**: `RunIdentity` + `FORGE_RUN_ID`/`FORGE_PARENT_RUN_ID`/`FORGE_ROOT_RUN_ID`, orthogonal to
  the `FORGE_DEPTH` recursion guard; interactive launches mint a fresh root (centralized in
  `invoke._build_environment`); the memory writer re-roots under the session's snapshotted origin identity and scrubs
  the drainer's run-tree/session vars. design_appendix §F.5/§C.1.
- **4b usage-attribution ledger**: durable versioned `~/.forge/usage/events/` -- the third plane, joined to cost/audit
  by `request_id`. `UsageEvent` (schema v1, strict typed reads where an unknown field == corruption), PID-sharded
  shards, a best-effort never-raising writer (modeled on `audit_logger`, not the unversioned `cost_logger`). design
  §3.14, appendix §A.13.
- **4c instrument native+direct paths**: `track_verb_cost` yields a cost holder; emitters wired for the 4 workflow verbs
  \+ memory-writer/supervisor/shadow + the action tagger (`ask`->`complete` to capture exact provider tokens + forward
  `X-Request-ID`); conservative `billing_mode` (no key-presence inference); `measurement_source=provider_usage_exact`
  added. Review fixes: the direct-path `request_id` join actually records its ref; `latency_ms` populated on every path.
- **4d HeadlessInvoker + review fan-out migration**: new `core/invoker/` (`HeadlessRequest`/`Result`/`Attribution` + the
  `HeadlessInvoker` protocol + `ClaudeHeadlessInvoker`); the review engine's parallel `claude -p` lifecycle moved
  **verbatim** behind `run_parallel` (the seam is the lifecycle, not the routing); per-worker usage events (worker
  granularity, cost null -- the verb aggregate holds the estimate). `_cleanup` SIGTERMs children before the blocking
  join; per-worker events record the actually-routed model/provider/proxy. design §5.5.5, appendix §A.13.
- **4e runtime registry**: a frozen `RuntimeSpec` per runtime in a module-level `RUNTIMES` table (the capability source
  Phase 5 reads); tri-state capability literals (Codex `pretool_policy="partial"`/`native_hooks="gated"` with
  machine-readable version gates -- limits declared as values, never parity-implying omissions); `forge runtime list`.
  Nothing branches on it yet. design §5.5.5.
- **4f runtime-tagged ActionContext + named Claude hook adapter/responder**: `ActionContext.runtime` is **required**
  attribution metadata (the policy engine never branches on it, stays runtime-agnostic); the two Claude-specific halves
  named behind runtime-neutral `HookAdapter`/`HookResponder` protocols (the Codex adapter/responder is the Phase 6
  stub). Output bytes + exit codes unchanged (77 hook-command snapshot tests untouched). design §4.1.4/§4.1.5.
  Integration: `test_policy_hooks.py` 10/10 through the real wheel CLI.

### Phase 3: native-relocate cross-CWD resume (spike PASS + Stage C v1 opt-in)

- **Outcome: PASS on Claude Code 2.1.158.** Relocating a parent session JSONL into the destination CWD's encoded project
  dir then `--resume --fork-session` completes a signed-thinking tool-use continuation with the parent JSONL unmodified;
  the control (resume without relocating) still reproduces the 2026-04-02 "No conversation found" discovery failure.
- **Shipped opt-in** `forge session fork --resume-mode native-relocate` (host mode only; transfer stays default) with
  pre-`fork_session` preflights (reject sidecar/`--no-launch`/missing transcript), post-create rollback, and dir-scoped
  cleanup of the relocated copy. Contract test `test_native_relocate_contract.py` PASSED (23.6s).
- **Bug fixed (surfaced by the spike)**: `encode_project_path` now maps `_`->`-` alongside `/`/`.` (Claude 2.1.158
  hyphenates underscores; Forge didn't -- broke transcript discovery/cleanup/relocation for any underscore path).
  Regression `test_bug_encode_project_path_underscore.py`. design §3.9.
- **Deferred**: `--rewrite-paths`, sidecar native-relocate, `resume --resume-mode native-relocate`, the gated default
  flip. **Candidate impl_note**: the Claude project-dir encoding maps `/` `.` `_` -> `-` (case/`-`/digits preserved).

### Phase 2: optional audit proxy

Opt-in, user-controlled wire chokepoint that can observe and (optionally) control the Claude\<->provider wire with
redacted audit logs -- all new config inert by default. Two orthogonal axes kept distinct: `wire_shape`
(`openai_translated`|`anthropic_passthrough`) and `intercept.mode`. Shipped: a thinking-preserving
`anthropic_passthrough` wire (preserves `thinking`/`redacted_thinking` byte-for-byte); redact-before-persist audit JSONL

- `forge proxy audit show|diff`; override-mode system-prompt augment/guards + reasoning-effort pin with a
  mutation-safety fingerprint tripwire (never rewrites history, fails closed); sidecar host-persistent audit/costs
  mounts + arbitrary-uid support (fixed two latent entrypoint bugs that meant the sidecar proxy could never start).
  design §7.x/§3.4/§3.7/§4.0, appendix §A.11/§A.12, end-user/proxy.md. **Deferred debt**: real-upstream `@slow`
  passthrough signature-replay e2e; streamed full-body capture.

**Verification (range)**: every slice shipped tree-green, `make pre-commit` clean; unit suites 4866->5531 passed across
the slices; integration/real-wire as noted (policy hooks 10/10, native-relocate contract 23.6s, cost-visibility matrix).

## 2026-05-31

### Phase 1: Schema-backed curated transfer + `forge transfer` CLI (Runtime Abstraction)

**Goal**: Make curated transfer a schema-backed, user-reviewable substrate and reposition `ai-curated` as the primary
cross-boundary transfer path, with a top-level `forge transfer` CLI to inspect and reshape it.

**Key changes**:

- **Transfer schema** (`src/forge/session/transfer.py`): `_build_ai_curated_output()` emits canonical sections 1-7
  (Lineage, Goal/Current Task, Decisions, Current State, Relevant Files, Open Questions, Runtime Hints); section 8 (User
  Notes) is the overlay merged at launch. `_build_frontmatter()` stamps `schema_version: 1`, reserves `target_runtime`
  for Phase 5, and marks `schema: "full"` only for a successful ai-curated body (`minimal|structured|full` →
  `compatibility-fallback`). `_validate_decision_citations()` drops citations outside the turn range the model saw, so
  `schema: full` never overstates evidence.
- **Three-file artifact model**: `generated.md` (regeneratable parent cache), `children/<child>.md` (frozen AI
  snapshot), `children/<child>.notes.md` (user overlay). `ensure_child` never overwrites an existing child; GC ties a
  notes file's liveness to its snapshot.
- **CLI** (`cli/transfer.py`, `core/ops/transfer.py`): new top-level `forge transfer show|regenerate|edit|diff`, pairing
  with `forge memory`. `regenerate` rewrites only the parent cache; `edit` targets the notes overlay; `show`/`diff` take
  `--child`.
- **Docs**: design.md §3.9 reframes curated transfer as the primary cross-boundary substrate (not a lossy fallback);
  appendix §M documents the frontmatter + 8-section contract + overlay; end-user/session.md updated.

**Verification**: 113 transfer tests pass (`test_transfer.py`, `test_transfer_cli.py`, `test_prev_sessions.py`,
regression `test_bug_transfer_notes_not_gc_orphaned.py`); shipped as commit `2b70c29`.

**Phase 1 closeout (2026-05-31, docs-only)**: `ctx` posture recorded in `design_appendix.md` §M.4 -- the transfer schema
is Forge-owned and canonical; `ctx` is prior art and inspiration only, never a dependency, and no interop is planned.
Both default-behavior decisions resolved as keep-current: `--review` stays opt-in (a plain `--fresh` resume never blocks
on `$EDITOR`) and `structured` stays the CLI default (`ai-curated` opt-in via `--strategy`, keeping the resume hot path
deterministic and LLM-free). Schema confirmed stable for Phase 5 (`target_runtime` reserved). All Phase 1 boxes ticked;
card stays in `doing/` for Phases 2-6. No code or tests changed.

## 2026-05-28 — 2026-05-29 (compacted)

Older entries condensed per the board-contract size policy. Dates, decisions, and verification highlights preserved;
per-file play-by-play dropped. Full detail in git history.

### memory_substrate: "handoff" → memory writer + transfer (2026-05-29, PR #8)

**Goal**: Split the overloaded "handoff" term into two concepts: **memory writer** (Stop-time project-doc curation) and
**transfer** (resume/fork context assembly), across code/CLI/config/durable state/docs/skills.

**Key changes**: `handoff_agent.py → memory_writer.py`, `handoff.py → transfer.py` (`HandoffConfig→MemoryWriterConfig`,
`process_handoff→assemble_transfer_context`); CLI `forge handoff run → forge memory-writer run`,
`forge session handoff show → forge memory report show` (old paths tombstoned, error with the replacement). Durable
state accept-and-tolerate: `--resume-mode handoff → transfer` (legacy read as transfer),
`handoff_timeout → memory_writer_timeout` (warn-and-ignore). Internal sweep drove residual `handoff` 207 → 39, all
intentional KEEPs (work-queue `kind="handoff"`, `enqueue_handoff_marker`, the `.forge/artifacts/<session>/handoff/`
path, the `queued_handoff` Stop field — recorded in `impl_notes.md`).

**Verification**: full unit+regression green (4902); `test_handoff_integration.py` (10) green; `make pre-commit` clean.
Shipped as PR #8 (gemini-3.5-flash catalog work split to PR #9).

### Add Claude Opus 4.8 (2026-05-28, retain 4.6 + 4.7)

**Goal**: Add Opus 4.8 as the opt-in Anthropic alternative without shrinking the registry.

**Key changes**: added `claude-opus-4-8` (5 aliases; $5/$25/$0.50, 1M context, 128K output, adaptive-only, `xhigh`)
alongside the retained 4.7 and 4.6 — three distinct registry models (`intelligence_score` 98/99/100). The
`opus`/`claude-opus` defaults + proxy tier mappings stay on **4.6**; 4.8 is opt-in (`--model claude-opus-4-8`), taking
over 4.7's *role* in review/templates/docs. Review guide `claude-4.7.md → claude-4.8.md`. (Additive correction
2026-05-29: an initial pass dropped 4.7 from the registry; re-added so catalog/pricing stay additive.)

**Verification**: catalog/pricing + full unit suite green; built-wheel smoke confirms `opus` still resolves to 4.6.

### Simplify memory strategies 7 → 4 (2026-05-28)

**Goal**: Reduce the strategy enum from 7 to 4, make shadow mode orthogonal, rename `--as → --strategy`.

**Key changes**: removed `debugging`/`patterns` (topic scoping moves to passport `intent`/`captures`) and `suggested`
(shadow mode is now orthogonal — `--propose` works with any strategy; path prefix `suggested_* → shadow_*`). Renamed
`--as → --strategy` (`--as` a hidden tombstone). Stale removed-strategy passports rejected with actionable hints.

**Verification**: full unit suite + `make pre-commit` clean.

## 2026-05-22 — 2026-05-26 (compacted)

Older entries condensed per the board-contract size policy. Dates, decisions, and verification highlights preserved;
per-file play-by-play dropped. Full detail in git history.

### Memory Enhancement project (PR #1, Phases 0-5)

**Goal**: Replace the manifest `designated_docs[]` model with passport-authoritative doc ownership, then reduce the
memory system to two primitives — passports select docs, session activation decides whether the memory writer runs.

**Key decisions & changes**:

- **Passport model** (`session/passport.py`, 2026-05-22): `MemoryStrategy` enum, YAML-frontmatter parse/serialize,
  `synthesize_passport`, writer-authorization, flag-vs-passport conflict resolution;
  `PassportError(field_path, reason, hint)`. Passports are authoritative for doc ownership.
- **Top-level `forge memory` CLI** (2026-05-23): `enable/track/untrack/list/status` (replacing `forge session memory`,
  which became a tombstone — since removed). Phase 5 added `forge memory shadows review` (LLM shadow curation,
  source-cited reports, `shadow_curation.py`).
- **Two-primitive simplification** (Slices 1-7, 2026-05-24→26): removed `.forge/memory.yaml` checkout activation,
  `MemoryIntent.designated_docs` (manifest field), the three-tier `memory_activation()` resolver, `ProjectMemoryConfig`,
  and `--inherit-memory`/extras tombstones. `forge memory enable/disable` are session-scoped; `list` is a sessionless
  passport scan; Stop hook + writer read `effective.memory.auto_update.enabled` directly. `--memory on|off` added to
  `fork`/`resume --fresh`/`start`. Strategy enum cut 7→4 (`debugging`/`patterns`/`suggested` removed; shadow mode
  orthogonal via `--propose`); `--as` renamed `--strategy`.
- **Design sync**: `design.md §5.6` (passport ownership, frontmatter, shadow, inheritance), `design_appendix.md §G`;
  memory-enhancement card archived to `docs/board/done/memory_enhancement/`.

**Verification**: unit suites green throughout (4441 → 4645 passed across slices); `make pre-commit` clean.

### CLI hardening (2026-05-24 → 2026-05-26)

- **Command-shape invariant** (documented in `coding-standards.md`/`design.md`): groups orient (print help), leaves act
  (sensible default). `forge config show` is the explicit leaf; `forge search query <terms>` replaced the `-q` action;
  `forge proxy metrics` shows all proxies when several are registered.
- **Shared recovery-tip helpers** (`cli/output.py`): `print_tip`/`print_error`/`print_error_with_tip`/
  `handle_session_error`; equivalent failures now tip identically; an invariant test allows `[dim]Tip:` only in
  `output.py`. **Break**: `forge backend create <existing>` now errors + exits 1 (was yellow + exit 0).
- **Auto-start proxies from templates** (`ensure_proxy`): naming a template with no live proxy starts one instead of
  erroring; covers all five `--proxy`/`--supervisor-proxy` paths. Liveness-aware (stale-healthy entries marked unhealthy
  before replacement). Regressions `test_bug_supervisor_proxy_autostart.py`,
  `test_bug_stale_healthy_proxy_not_restarted.py`.
- **Protect live sessions from deletion**: `forge session delete` refuses a session with a live launch unless `--force`
  (`--yes` no longer overrides); `--all` skips live sessions. Launcher tolerates a manifest deleted mid-run (no
  traceback). Regression `test_bug_delete_live_session.py`.
