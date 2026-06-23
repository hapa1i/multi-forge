# Checklist: forge codex command group

**Card**: [card.md](card.md) - **Branch**: `forge_codex_command_group` - **Lane**: done

Executed the codex proposal as one card but sequenced per its **Type** note: shipped `forge codex status` first, gated
the Responses transport on the Phase 2 probe, and built `forge codex start --proxy` only after the transport existed.

## Current focus

Phase 1 shipped (commit `dff6e3a`): `forge codex status` + 14 unit tests, `make pre-commit` clean. Phase 2 live-probe
**resolved GO** -- codex accepts a custom Responses base URL via argv (`-c`) + env. Phase 3 (Slice 2) **implemented as a
Responses _passthrough_** (not the card's original translating transport -- see the revised Slice 2 rationale): 6 seams
shipped, 49 unit tests, `make pre-commit` clean, and a **live integration gate run** (real codex 0.141.0 -> the proxy).
One acceptance item remains **credential-blocked**, not code-blocked: a successful 200 reasoning round-trip needs a
working OpenAI key (this environment's `OPENAI_API_KEY` is dead). At closeout this is accepted as an operator residual,
because the routing and launcher paths have been live-verified up to upstream 401/429.

**Phase 4 shipped**: `forge codex start --proxy <id-or-template>` -- the sessionless, scrubbed Codex TUI launcher (4
seams: version gate, capability gate, bare invocation, CLI leaf; 62 new unit tests incl. the post-commit proxy-identity
fix). `make pre-commit` clean and the live argv-routing gate ran: the list-mode `-c` argv routes real codex 0.141.0 to
`POST /v1/responses` (risk #1 validated). The 200 reasoning round-trip remains credential-blocked (dead key), like Phase
3, and is recorded below as an accepted residual.

## Phase 1 - `forge codex status` (shippable now)

- [x] New `forge codex` group in `src/forge/cli/codex.py`, registered in `src/forge/cli/main.py`. Group stays visible
  when `codex` is absent (diagnostic surface). *(test_status_codex_absent_exits_zero,
  test_codex_group_registered_and_visible)*
- [x] `status` reports binary + version via `get_runtime("codex").detect()`. With `codex` absent, exits 0 and reports
  `installed: false`. *(test_status_codex_absent_exits_zero)*
- [x] Config-path inspection: default is the **detected** install scope via `find_forge_installation` (else user);
  `--scope user|project|local` and `--all` (lists local distinctly) widen it. Project/local roots resolve by walking up
  for `.git`/`.codex`, not bare cwd, so a subdir run still finds the per-project config + scope-keyed tracking.
  *(test_status_default_uses_detected_scope, test_status_default_is_user_when_no_install,
  test_status_all_includes_local_scope, test_status_project_scope_resolves_root_from_subdir)*
- [x] Tracking from `~/.forge/installed.json` (`codex_config_path`, `codex_commands`) when present.
  *(test_status_surfaces_installed_json_tracking)*
- [x] Managed-block presence via `read_codex_registration(...).block_present`. *(test_status_reports_managed_block)*
- [x] Event-aware registration pairs via `codex_registration_pairs(...)`, **filtered to Forge commands** so unrelated
  user hooks in the same config do not pollute the footprint (`SessionStart -> forge hook codex-session-start`,
  `PreToolUse -> forge hook codex-policy-check`). *(test_status_reports_managed_block, test_status_catches_wrong_event,
  test_status_filters_unrelated_hooks)*
- [x] Static enrollment posture: `registered: yes/no/partial/wrong-event`, `enrollment: unverified by static read`,
  `verify: forge runtime preflight codex --verify-enrollment`. Never claims enrollment from a static read.
  *(test_status_catches_wrong_event, test_status_does_not_claim_enrollment)*

### Style-guide compliance (new guards merged in #46)

- [x] **Single-leaf group (decision reversed).** The original plan registered a gated `start` so `forge codex` had two
  leaves. That doesn't survive review: a `start` with no `--proxy` that always errors *is* a tombstone-shaped
  placeholder, it contradicts the card (launcher = parked), and it would pin a `--proxy` contract the **Phase 2 kill
  criterion** may invalidate. Resolution: remove `start`; allowlist `forge codex` in `SINGLE_LEAF_GROUP_ALLOWLIST` as
  deliberate **phasing** debt (distinct from the flatten-style entries), to be removed when `start --proxy` ships in
  Phase 4. *(test_codex_group_registered_and_visible asserts `forge codex start` is "No such command".)* **\[Phase 4:
  reversed -- `start` shipped; the allowlist entry is removed and the test now asserts `start` exists.\]**
- [x] `status` exposes `--json` with dest `as_json` (read-leaf rule). With `start` removed, the module has no
  hand-rolled error markup and no `print_error` call; `status`'s only error is Click's `UsageError` (already stderr), so
  the stdout/stderr split holds. **Deferred to Phase 4:** when `start` returns it must use a stderr `Console`.
- _Out-of-scope finding (flag, do not fix here):_ `forge.cli.output`'s fallback `console` is stdout (`output.py:22`), so
  the guide's "errors -> stderr" rule is violated project-wide by the shared helper (~18 files). Separate cleanup.

### Acceptance tests (Phase 1)

| Test                                     | Fixture                                   | Assertion                                                                            | Test File                            |
| ---------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------------------ | ------------------------------------ |
| Status works when Codex absent           | runtime faked absent                      | exits 0, `installed: false`                                                          | `tests/src/cli/test_codex_status.py` |
| Status reports managed block             | config has Forge markers                  | shows config path, `block_present: true`, registered commands                        | same                                 |
| Status catches wrong-event registration  | command under wrong event                 | reports wrong-event/partial, not `registered: yes`                                   | same                                 |
| Status does not claim enrollment         | managed block present                     | enrollment unverified, points to `forge runtime preflight codex --verify-enrollment` | same                                 |
| Status supports JSON                     | any                                       | stable JSON fields (binary, config path, block, pairs, tracking, verify cmd)         | same                                 |
| Default uses detected scope              | `find_forge_installation` faked / raising | default shows detected scope, else falls back to user                                | same                                 |
| `--all` lists local distinctly           | any                                       | scopes == {user, project, local}                                                     | same                                 |
| Project scope resolves root from subdir  | `.git`+`.codex` at root, run from subdir  | finds root `.codex/config.toml` (`config_exists`/`block_present`)                    | same                                 |
| Registered pairs are Forge-only          | Forge block + unrelated hook              | unrelated command absent from `registered_pairs`; Forge command present              | same                                 |
| Group single-leaf; `start` not a command | runtime faked absent                      | `forge --help` lists `codex`; `forge codex start` is "No such command"               | same                                 |
| Tracking surfaced from installed.json    | seeded `installed.json`                   | `tracked_config_path` / `tracked_commands` populated in scope output                 | same                                 |

## Phase 2 - Live-probe Codex proxy contract (hard go/no-go gate) -- RESOLVED: GO

Probed `codex-cli 0.141.0` (`/opt/homebrew/bin/codex`) on 2026-06-22. **Decision: GO** -- the kill criterion is NOT
triggered. Routing to a custom Responses base URL is reachable via **argv (`-c`) + env**, not config-file-only, so the
launcher's "configure child env/argv" design is feasible. (Card Slice 1.)

### Pinned contract (no codex-owned `config.toml` write)

Inject the provider entirely through `-c` overrides (every subcommand accepts `-c key=value`, dotted, TOML-parsed):

```text
codex [exec] \
  -c model_provider=<id> \
  -c 'model_providers.<id>.name="..."' \
  -c 'model_providers.<id>.base_url="http://127.0.0.1:<port>/v1"' \
  -c 'model_providers.<id>.wire_api="responses"' \
  -c 'model_providers.<id>.env_key="<ENV_VAR>"'
```

- **Auth = env.** Codex sends the value of `<ENV_VAR>` as the provider token; the loopback proxy must accept it. With a
  custom provider active, `requires OpenAI auth: false` -- native OpenAI creds are not needed (supports the
  no-upstream-creds-leak requirement).
- **`wire_api="responses"`** is HTTP/SSE Responses (what Slice 2 must serve). The separate "Responses WebSocket" feature
  is disabled by default -- Slice 2 needs HTTP/SSE only, not WebSocket.

### Evidence

`codex doctor --json` with an **empty** `$CODEX_HOME` and argv-only `-c` flags reported: `model provider: forge_local`,
`forge_local API base URL: http://127.0.0.1:4000/v1 connect failed (required)` (read + attempted -> proves routing),
`wire API: responses`, `provider auth env var: <VAR> (present)`, `requires OpenAI auth: false`.

### Caveats for Slices 2-3

- **Never pass `--strict-config`.** `codex exec --strict-config` errors on config fields the installed version does not
  recognize; rely on version-tolerant `-c` overrides instead.
- `-p/--profile` layers a `$CODEX_HOME/<name>.config.toml` file -- a file-based alternative deliberately NOT used; `-c`
  argv is the chosen non-file channel.
- Env scrub (Slice 3): `shell_environment_policy.inherit` is a `-c`-settable key relevant to controlling child env.
- Slice 1 proves the routing channel only. A full Responses request/response round-trip is Slice 2's acceptance test
  (`tests/src/proxy/test_responses_transport.py`), not proven here.

## Phase 3 - Responses proxy transport (gated on Phase 2) -- IMPLEMENTED (passthrough); 200-completion credential-blocked

**Decision: passthrough, not translating.** Translating Responses\<->the proxy's internal layer drops reasoning-item
continuity (`converters.py`, `core/llm/types.py` has no reasoning channel). Codex is a reasoning-model client that
depends on that continuity -- the exact failure `anthropic_passthrough` exists to avoid. So Slice 2 ships an
`openai_responses_passthrough` wire shape that forwards Codex's raw Responses traffic byte-for-byte (reasoning
preserved, signature-safe). Tier re-routing + a core.llm reasoning channel are deferred. This **revises card Slice 2**.

### Seams shipped

- [x] **Seam 1 (config).** `openai_responses_passthrough` in `_VALID_WIRE_SHAPES`; `responses_ingress` capability on
  `ModelSourceCapabilities`; `codex-responses-local` source (litellm-local upstream so the cost header is present) +
  template; `source_bearer_auth_env_var()` (the single secret, non-connection-value env var; fail-closed on 0 or >1).
- [x] **Seam 2 (forwarding).** Extracted `proxy/stream_relay.py` (wire-agnostic SSE teardown shared with the Anthropic
  passthrough -- its 32 tests stay green) + new `proxy/responses_passthrough.py` (method/body/query-aware `forward`,
  Bearer-injecting header builder that strips inbound auth + `OpenAI-Organization`/`OpenAI-Project`, tolerant usage
  side-tap, USD->micros cost from `x-litellm-response-cost`, response-header allowlist that drops hop-by-hop **and the
  proxy-owned `x-request-id`**).
- [x] **Seam 3 (routes).** `POST /v1/responses` (create, stream-aware) registered before the catch-all
  `api_route("/v1/responses/{rest:path}", methods=[GET,POST,DELETE])`; body read only for POST (bodyless GET/DELETE
  never call `.json()`); gate = `wire_shape == openai_responses_passthrough` AND `source.responses_ingress` else
  **501**. Handler + registrar + GET / helpers live in the new `proxy/responses_ingress.py` (extracted from `server.py`
  to keep it under the 2.5k-line cap; reads proxy runtime state via a lazy `import forge.proxy.server`).
- [x] **Seam 4 (GET /).** `build_intercept_capability_section` + `advertise_responses_ingress` (pure helpers in
  `responses_ingress.py`): `thinking_blocks_preserved` true, `can_inspect.*` uniformly false,
  `capabilities.responses_ingress` mirrors the route gate.
- [x] **Seam 5 (preflight).** `_resolve_responses_posture` returns the previously-dead `proxy_supported` only on the
  same wire_shape AND `responses_ingress` conjunction the route enforces (fail-closed on empty/unknown source).
- [x] **Seam 6 (smoke test).** `proxy_orchestrator` smoke test POSTs a minimal Responses request to `/v1/responses` for
  this wire shape (not `/v1/messages`).

### Acceptance tests (Phase 3)

| Test                                            | Fixture                                                              | Assertion                                                                                                             | Test File                                        |
| ----------------------------------------------- | -------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| Non-stream + stream POST relayed faithfully     | mock upstream                                                        | method/url/body forwarded byte-for-byte; SSE bytes unchanged                                                          | `tests/src/proxy/test_responses_transport.py`    |
| Bodyless GET/DELETE + top-level non-`{id}` path | mock upstream                                                        | method/query preserved; no `.json()` on bodyless                                                                      | same                                             |
| Usage + cost accounting                         | `response.completed` + `x-litellm-response-cost`                     | token usage from SSE/body; `"0.000123"->123`; negative/absent->unavailable                                            | same                                             |
| Capability gate -> 501                          | wrong wire_shape / non-ingress / unknown / empty source              | route returns 501                                                                                                     | same                                             |
| GET / truth table                               | each wire shape                                                      | reasoning preserved + inspect false for responses-pt; ingress advert mirrors gate                                     | same                                             |
| Header hygiene                                  | inbound + upstream headers                                           | Bearer injected; org/project stripped; hop-by-hop + duplicate `x-request-id` dropped                                  | same                                             |
| `source_bearer_auth_env_var` fail-closed        | 0 / 2 secret env vars                                                | raises `ModelSourceCatalogError`                                                                                      | same                                             |
| Preflight conjunction                           | proxy.yaml wire_shape x source                                       | `proxy_supported` only when both; else `proxy_unsupported`                                                            | `tests/src/core/runtime/test_codex_preflight.py` |
| Accounting only on the generation endpoint      | GET retrieve / DELETE / cancel / input_tokens vs POST create         | on_complete + provider-trace + spend-cap wired only for `POST /v1/responses`; a retrieve echoing usage is not counted | `tests/src/proxy/test_responses_transport.py`    |
| Terminal status folds into failure              | streamed `response.failed`/`incomplete`; non-stream `status: failed` | failed -> `failed=True` + `error_type`; incomplete -> billed partial success; usage still captured                    | same                                             |

### Review fixes (pre-merge)

- **Accounting double-count.** The generation-accounting callback was attached to *every* `/v1/responses*` method, so a
  later `GET /v1/responses/{id}` (which echoes the original response's `usage`) would double-count tokens, and
  retrieve/cancel/delete logged zero-token "attempts". Gated to `POST /v1/responses` only — the spend cap too, so a run
  can be cancelled while over cap.
- **Terminal-status accuracy.** The streamed `failed` flag was transport-only, so a 200 stream ending in
  `response.failed` was recorded as success. The accumulator now tracks terminal status and folds `response.failed` into
  `failed=True` + `error_type="response_failed"`; `response.incomplete` stays a billed partial success.

### Live integration gate (2026-06-22)

Ran a real `codex-cli 0.141.0` against a live `codex-responses-local` proxy (forge `:8105` -> litellm `:4000` ->
OpenAI). Confirmed against the **running** system:

- `GET /` advertises `wire_shape=openai_responses_passthrough`, `capabilities.responses_ingress=true`, and the exact
  intercept truth table (`thinking_blocks_preserved=true`, all `can_inspect.*=false`).

- LiteLLM genuinely serves `/v1/responses` and routes upstream (an OpenAI-originated error relays back through forge ->
  litellm -> client), so the upstream architecture is real, not theoretical.

- Direct probes: non-stream POST, stream POST, and **bodyless GET** all forward + relay the upstream response; exactly
  **one** `X-Request-ID` row (the dedup fix); bodyless GET does not crash on `.json()`.

- **Real codex drives the route**: with the Phase 2 `-c` contract (`base_url=...:8105/v1`, `wire_api="responses"`,
  `env_key`), codex sends `POST /v1/responses` (streaming, via `_forward_streaming`); the route **opens** (not 501) and
  relays the upstream status. Codex even read the proxy's `X-Request-ID` back in its retry log.

- [x] **Accepted residual (credential-blocked, not code):** a successful **200 reasoning round-trip + interrupt** could
  not complete -- this environment's `OPENAI_API_KEY` is dead (OpenAI returns 401 directly; codex then hits a 429 retry
  storm). Re-run the gate with a working OpenAI (or LiteLLM) key and confirm a reasoning-bearing turn completes before
  treating the upstream-200 proof as covered.

### Design-doc sync (Phase 3)

- [x] `docs/design.md` §3.4: `proxy_supported` goes live; document the Responses passthrough wire shape + the wire_shape
  AND `responses_ingress` gate.
- [x] `docs/board/change_log.md`: Phase 3 entry.

## Phase 4 - `forge codex start --proxy` launcher -- IMPLEMENTED

Sessionless proxy-backed TUI launch with full child-env scrub; no `.forge/`, no `confirmed.codex`. (Card Slice 3.)

### Seams shipped

- [x] **Version gate** (`src/forge/core/runtime/codex_preflight.py`): `CODEX_PROXY_CONTRACT_VALIDATED = "0.141.0"` +
  `codex_proxy_contract_blocker(version)` (reuses `_version_lt`). Blocks only a *parsed* version strictly below the
  floor; unparseable/None is allowed (unknown != provably-old). Distinct from `CODEX_VERSION_VALIDATED` (0.139.0 probe
  ceiling) and the hook floor (0.131.0). *(TestProxyContractBlocker)*
- [x] **Capability gate** (`src/forge/proxy/proxy_orchestrator.py`):
  `assert_proxy_responses_capable(base_url) -> (default_model|None, wire_shape)` + `ProxyUnreachableError` /
  `ProxyNotResponsesCapableError`. Enforces the full runtime conjunction off `GET /` -- top-level
  `wire_shape == openai_responses_passthrough` AND `capabilities.responses_ingress is True` -- so a flag set under a
  wrong shape still fails closed. Default model from `routing.default_tier -> tiers[tier].model` (guarded).
  *(TestAssertProxyResponsesCapable)*
- [x] **Bare invocation** (`src/forge/session/codex_invoke.py`): `invoke_codex_bare_proxy` + pure
  `_build_codex_proxy_env` / `_build_codex_proxy_argv`. Env composes `_CODEX_BARE_PROXY_STRIP_VARS` (= the shared
  `_CODEX_CHILD_STRIP_VARS` + session/fork + run-tree + the 5 OpenAI account/routing vars), advances `FORGE_DEPTH`, sets
  the loopback token, and re-establishes NO native auth. Argv = list-mode
  `-c model_providers.forge_proxy.{name,base_url,wire_api=responses,env_key}`; `-m` auto-defaults from the proxy unless
  the user passed `-m`/`--model`; never `--strict-config`. *(TestBareProxyArgv, TestBareProxyEnv, TestBareProxyInvoke)*
- [x] **CLI leaf** (`src/forge/cli/codex.py`): `forge codex start --proxy <id-or-template> [--sandbox] [-- codex-args]`.
  Order: installed -> version gate -> `ensure_proxy` -> capability gate -> exec. Errors on a stderr `Console` via
  `print_error` / `print_error_with_tip` (closes the Phase 1 stderr-Console deferral). On a gate failure the started
  proxy is left running. *(tests/src/cli/test_codex_start.py)*
- [x] **Single-leaf allowlist**: removed `forge codex` from `SINGLE_LEAF_GROUP_ALLOWLIST` (now 2 leaves);
  `test_codex_group_registered_and_visible` updated to assert `start` exists and errors on missing `--proxy` (not "No
  such command"). *(test_no_single_leaf_groups)*

### Acceptance tests (Phase 4)

| Test                                     | Fixture                                       | Assertion                                                   | Test File                                    |
| ---------------------------------------- | --------------------------------------------- | ----------------------------------------------------------- | -------------------------------------------- |
| Old codex hard-blocks before proxy start | runtime version 0.140.0                       | exit 1, `ensure_proxy` not called, tip names 0.141.0        | `tests/src/cli/test_codex_start.py`          |
| Unparseable version proceeds             | runtime version None                          | reaches `invoke_codex_bare_proxy` (exit 0)                  | `tests/src/cli/test_codex_start.py`          |
| Capability conjunction fail-closed       | `responses_ingress:true` + wrong `wire_shape` | raises `ProxyNotResponsesCapableError` (wire_shape carried) | `tests/src/proxy/test_proxy_orchestrator.py` |
| No native-account leakage                | `OPENAI_*` + `CODEX_*` set in env             | all absent from bare env; loopback token set                | `tests/src/session/test_codex_invoke.py`     |
| `-c` argv exact tokens (list-mode)       | base_url with/without trailing slash          | exact provider argv, single `/v1`, no `--strict-config`     | `tests/src/session/test_codex_invoke.py`     |
| Not-capable surfaces required message    | capability gate raises                        | exit 1, "Responses-capable proxy required" on stderr        | `tests/src/cli/test_codex_start.py`          |

**Verification**: 55 new unit tests pass; full `tests/src/cli` suite (1953) green; the modified preflight / orchestrator
/ codex_invoke / codex_status / command-tree files green.

### Design-doc sync (Phase 4)

- [x] `docs/cli_reference.md`: `forge codex start` row + shipped description (dropped the "parked" note).
- [x] `docs/design.md` §3.4: "Bare launch (Codex)" subsection (sessionless launch + scrubbed child env); §3.7 wire-shape
  bullet cross-references the launcher consumer.
- [x] `docs/board/change_log.md`: Phase 4 entry (`## 2026-06-23`).

### Live integration gate (Phase 4) -- RUN (2026-06-23)

Started a real `codex-responses-local` proxy (forge `:8105` -> litellm `:4000`), ran the **real**
`assert_proxy_responses_capable('http://localhost:8105')` -> `('openai/gpt-5.5', 'openai_responses_passthrough')` (live
GET / conjunction + default-model extraction), then drove `codex-cli 0.141.0` through the **exact list-mode `-c`
tokens** from `_build_codex_proxy_argv` via `subprocess.run` (no shell -- same quoting path as
`invoke_codex_bare_proxy`). The TUI itself needs a tty, so the request-generating leg used `codex exec` with
byte-identical `-c` provider tokens.

- [x] **List-mode `-c` argv routes codex to the proxy (risk #1 validated).** codex reported `provider: forge_proxy`,
  `model: openai/gpt-5.5`, `wire_api=responses` (it accepted the literal inner-quote tokens), and the proxy access log
  shows two `POST /v1/responses` requests reaching `responses_passthrough._forward_streaming` (`req_84925e2a4325`,
  `req_72401ff602ae`). The shell-quoted Phase 2 probe and now the list-mode path both route.
- [x] **200 reasoning round-trip stays credential-blocked, not code-blocked.** The two POSTs failed upstream with 401
  then 429 (dead/rate-limited OpenAI key), past the proxy's routing -- the same deferral as Phase 3, not a launcher
  defect.
- [x] `make pre-commit` clean (ruff, black, isort, mypy, pyright, mdformat, gitleaks; under the 2.5k-line file cap).

### Review fixes (post-commit)

- [x] **Wrong-proxy identity gap (caught in review).** `ensure_proxy` resolves an exact proxy_id by registry presence,
  not liveness, and the capability gate originally passed only `entry.base_url` to `assert_proxy_responses_capable` --
  so a stale entry whose port is now held by a *different* capable Forge proxy could route Codex through the wrong
  upstream while the UI named the requested proxy. Fix: `assert_proxy_responses_capable` now takes
  `expected_proxy_id`/`expected_template` and verifies identity (`is_proxy` + `proxy_id` + `template`) from the *same*
  `GET /` body, **before** the capability conjunction, raising `ProxyIdentityMismatchError` (mirrors
  `check_proxy_health` / the Claude launcher's `_healthcheck_proxy`). The CLI passes `entry.proxy_id`/`entry.template`
  and tips the stale-entry recovery. *(TestProxyIdentityVerification + test_identity_mismatch_shows_stale_entry_tip;
  live-verified against a real proxy body: correct id passes, wrong id rejects.)*

## Blockers / deferred

- Phase 2 hard gate: **cleared GO** (argv/env routing exists; not config-file-only). Phases 3-4 shipped on top of that
  probe result.
- Live 200 reasoning round-trip: accepted residual, credential-blocked in this environment. Needs a working OpenAI or
  LiteLLM key for final operator confirmation.
- `forge codex preset` is out of scope by design (`config.toml` is codex-owned and trust-frozen). The launcher uses `-c`
  argv overrides, never a written file -- consistent with that boundary.

## Closeout

- [x] `forge codex status` documented in `docs/cli_reference.md` ("Codex management" section).
- [x] End-user guides synced for `forge codex start --proxy` (`session.md`, `proxy.md`, `authentication.md`).
- [x] Phase 1 merged.
- [x] `docs/design.md` updated for the codex CLI surface change (§3.4 "Bare launch (Codex)", §3.7 wire-shape consumer
  cross-ref).
- [x] `epic_forge_codex` not created; the Responses transport and launcher work folded back into this card, and the
  normative contract now lives in design docs + implementation notes.
- [x] `change_log.md` entry at phase closeout; move `doing/ -> done/` when the card's live scope ships.
