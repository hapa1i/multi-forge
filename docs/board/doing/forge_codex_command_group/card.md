# forge codex command group: proxy-backed sessionless Codex launcher

**Status**: In progress (`doing/`). **Slice 1 (`forge codex status`) shipped**; **Slice 2 (Responses passthrough
transport) shipped** (Phase 3); **Slice 3 (`forge codex start --proxy` launcher) shipped** (Phase 4). The one open item
is a live 200 reasoning round-trip, which is **credential-blocked** (this env's `OPENAI_API_KEY` is dead), not
code-blocked. `docs/design.md` §3.4/§3.5/§3.7 are normative; this card defers to them on conflict.

**Type**: Recorded as one proposed card, but **split it before execution** — the evidence already requires it.
Verification (2026-06-22, against the codebase) confirmed Forge's proxy serves no Responses API and that pointing the
Codex CLI at a local base URL is unverified, so this is not a thin vertical path. The accepted split:

1. **`forge codex status`** ships as a standalone card now — every building block exists today.
2. **The Responses-capable proxy transport** is an epic member, gated on the Slice 1 probe. It is a from-scratch proxy
   build, not a config toggle. **Shipped as a byte-faithful _passthrough_** (new `/v1/responses*` route, raw SSE relay,
   advertised capability, and the live `proxy_supported` posture), **not** the translating transport this card
   originally sketched — translation drops Codex's reasoning-item continuity. See the revised Slice 2.
3. **`forge codex start --proxy`** — **shipped** (Phase 4) once the probe resolved and the transport landed: a
   sessionless, scrubbed Codex TUI through the Responses-capable proxy, with hard version + capability gates and no
   native-account leakage.

Do not execute all three as one vertical card.

## Summary

Add a `forge codex` command group centered on:

- `forge codex start --proxy <id-or-template>`: sessionless Codex TUI through a Forge proxy.
- `forge codex status`: read-only inspection of Forge's Codex footprint and readiness hints.

Do **not** ship a native-direct `forge codex start` or `forge codex start --no-proxy` in this card. Native-direct,
untracked Codex use already has the first-party command: `codex`.

Only the proxy *lifecycle shape* is reusable from `forge claude start --proxy`: ensure/adopt the proxy and health-check
it before launch. Everything downstream is new build, not reuse. The Claude path points the child at a proxy that
already serves the Anthropic wire via `ANTHROPIC_BASE_URL`; Codex needs an OpenAI **Responses**-compatible proxy that
does **not** exist yet (Forge's proxy serves only `/v1/messages`) and a base-URL hook into the Codex CLI that is
**unverified** (there is no `CODEX_BASE_URL` companion in the credential registry; Slice 1 probes it). The child
env-scrub is also new work, not a copy of the Claude launcher (see Design context). Treat the launcher as
build-from-zero behind an existing CLI shape.

The honest split is:

- `codex` for untracked, native-direct Codex TUI use.
- `forge codex start --proxy <id-or-template>` for untracked Codex TUI use with Forge proxy routing and observability.
- `forge session start --runtime codex` / `forge session resume` for Forge-managed Codex sessions.
- `forge codex status` for Forge's Codex registration, config footprint, and readiness hints.

## Problem

**1. No sessionless proxy-backed Codex launcher.** Codex can run inside Forge-managed sessions, and native Codex can run
directly via `codex`, but there is no command for "open Codex TUI from this directory through a Forge proxy, without
creating a Forge session." That is the gap this card fills.

**2. Current Codex proxy posture is unsupported.** `src/forge/core/runtime/codex_preflight.py` currently treats
Responses proxy mode as unsupported: `_resolve_responses_posture()` only returns `native_direct` or `proxy_unsupported`,
and the `proxy_supported` value in the `ProxyResponses` literal is never returned. This card is therefore not just CLI
plumbing; it must establish a first Responses-capable proxy contract for Codex.

**3. No Codex-namespaced status surface.** Forge appends a managed hook block to Codex's `config.toml`
(`src/forge/install/codex_hooks.py`), but answering "what did Forge register, where, and how do I verify it?" currently
means combining `forge extension status`, `forge runtime preflight codex`, and sometimes
`forge runtime preflight codex --verify-enrollment`. A `forge codex status` read surface makes that discoverable.

**4. Optional-runtime help should be honest without hiding diagnostics.** The `forge codex` group should remain visible
even when `codex` is absent, because `status` is diagnostic. Launcher invocation can fail with specific preflight
errors.

## Motivation

- **Proxy parity where it matters.** Users get the useful part of `forge claude start --proxy`: proxy lifecycle,
  routing, auth boundary, observability, and control.
- **No session overhead.** The launcher creates no Forge session manifest, no session index entry, and no
  `confirmed.codex`; it is not resumable through `forge session resume`.
- **Operator visibility.** Sessionless Codex usage can still flow through Forge provider trace, cost accounting, audit,
  and policy-capable proxy surfaces where the proxy supports them.
- **Clear product boundary.** Forge does not wrap native-direct Codex just for symmetry. The command exists because
  Forge adds proxy-backed value.
- **Safe inspect surface.** Users get a Codex-namespaced answer to "what did Forge touch?" without an editable Codex
  preset or a turn-spending enrollment probe.

## Design context (normative constraints this card must respect)

| Constraint                                                                                                                                  | Source                                                                                                                                                                                                    | Implication for `forge codex`                                                                                                                                                                                                                                                                                                     |
| ------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Current Codex runtime is native-direct; Forge proxy mode is marked unsupported                                                              | `docs/design.md` §3.4; `src/forge/core/runtime/codex_preflight.py:465-502`                                                                                                                                | This card must add or prove a Responses-capable proxy path before the launcher can be considered ready.                                                                                                                                                                                                                           |
| `forge claude start --proxy` owns only the proxy **lifecycle** (ensure/adopt + health-check); its env-scrub is **not** a reusable precedent | `src/forge/cli/claude.py:159-191` (scrubs only `FORGE_SESSION`/`FORK_NAME`/`PARENT_SESSION`); `src/forge/core/invoker/codex.py:55-65` (`_CODEX_CHILD_STRIP_VARS`); `src/forge/core/reactive/env.py:39-41` | Reuse the ensure/adopt + health-check lifecycle. Build a **new, complete** child-env scrub — no current launcher strips the full run-tree + subprocess set; the real precedent is `_CODEX_CHILD_STRIP_VARS` plus the run-tree var names. A half-copied claude scrub would leak `FORGE_RUN_ID`/`FORGE_ROOT_RUN_ID` into the child. |
| Managed Codex sessions always write Forge session state                                                                                     | `docs/design.md` §3.5/§3.9; `src/forge/core/ops/codex_session.py`; `src/forge/core/ops/codex_interactive.py`                                                                                              | `forge codex start --proxy` is sessionless and records no `confirmed.codex`; docs must distinguish it from `forge session start/resume --runtime codex`.                                                                                                                                                                          |
| Codex hooks are enrollment-gated and can fire for user-scope registrations outside Forge sessions                                           | `docs/design.md` §3.9; `src/forge/cli/hooks/codex_transfer.py`                                                                                                                                            | The launcher must scrub inherited Forge session/root env so hooks resolve no managed session and stay silent.                                                                                                                                                                                                                     |
| Bare Claude launches mint a fresh run-tree root but only `invoke.py` pops `FORGE_PARENT_RUN_ID` — not the full set                          | `src/forge/session/claude/invoke.py:194`                                                                                                                                                                  | Codex proxy launches must mint a fresh attribution root **and** scrub the full run-tree set themselves; `invoke.py` is not a complete precedent. Must not inherit parent run ids or set `FORGE_SESSION`/`FORGE_FORGE_ROOT`.                                                                                                       |
| codex-cli owns `config.toml`; Forge only appends a managed block whose bytes are part of Codex's `trusted_hash`                             | `src/forge/install/codex_hooks.py`; `docs/design.md` §3.9                                                                                                                                                 | No `forge codex preset`. `forge codex status` is read-only by design.                                                                                                                                                                                                                                                             |
| `trusted_hash` is not computable from a config read                                                                                         | `src/forge/core/ops/codex_enrollment.py`                                                                                                                                                                  | `forge codex status` reports registration facts and verification guidance, never "enrolled: yes" from a static read.                                                                                                                                                                                                              |
| Registration correctness is event-aware                                                                                                     | `codex_registration_pairs()` vs `read_codex_registration()` in `src/forge/install/codex_hooks.py`                                                                                                         | Status must distinguish command strings that merely appear somewhere from expected `(event, command)` registrations that can actually fire.                                                                                                                                                                                       |
| `forge claude` remains the primary-runtime surface                                                                                          | `docs/design.md` §3.4; `src/forge/cli/claude.py`                                                                                                                                                          | Keep `forge claude` visible even when Claude is absent so its invocation can produce install/setup guidance. `forge codex status` should also remain visible.                                                                                                                                                                     |

## Proposed surface

| Surface                                      | Status       | Notes                                                                                                                  |
| -------------------------------------------- | ------------ | ---------------------------------------------------------------------------------------------------------------------- |
| `forge codex start --proxy <id-or-template>` | **New**      | Sessionless foreground Codex TUI through a Responses-capable Forge proxy                                               |
| `forge codex status`                         | **New**      | Read-only status over binary/version, install tracking, config path, managed block, and event-aware registration pairs |
| Native-direct `forge codex start`            | Not shipped  | Use raw `codex` for native-direct sessionless use                                                                      |
| `forge codex start --no-proxy`               | Not shipped  | Avoid a thin alias with unclear value                                                                                  |
| Session-managed Codex                        | Exists       | `forge session start/resume --runtime codex`; not re-exposed                                                           |
| Empirical enrollment verification            | Exists       | `forge runtime preflight codex --verify-enrollment`; `status` links to it, does not duplicate it                       |
| Editable Codex settings                      | Out of scope | `config.toml` is codex-owned; no Forge preset                                                                          |

### `forge codex start --proxy <id-or-template>`

Launch the foreground Codex TUI from the current directory, routed through a Forge proxy.

Required behavior:

- Accept a proxy id or proxy template, matching the operator-facing shape of `forge claude start --proxy`.
- Start or adopt the proxy with the existing proxy lifecycle helper pattern where possible.
- Health-check the proxy before launch and require an advertised OpenAI Responses-compatible capability.
- Fail with an actionable "Responses-capable proxy required" error if the proxy cannot serve Codex.
- Configure the `codex` child to use the local proxy using the contract proven by the live probe slice.
- Keep upstream LLM credentials owned by the proxy when the proxy handles upstream auth.
- Avoid leaking native Codex/OpenAI credentials into the child when they are not needed for local proxy auth.
- Create no Forge session, manifest, index entry, or `.forge/` requirement.
- Set no `FORGE_SESSION` or `FORGE_FORGE_ROOT`.
- Scrub inherited managed-session identity: `FORGE_SESSION`, `FORGE_FORGE_ROOT`, `FORGE_FORK_NAME`,
  `FORGE_PARENT_SESSION`.
- Scrub inherited run-tree identity: `FORGE_RUN_ID`, `FORGE_PARENT_RUN_ID`, `FORGE_ROOT_RUN_ID`.
- Scrub inherited Claude/proxy/subprocess routing vars that could misroute the child, including `ANTHROPIC_*` and
  `FORGE_SUBPROCESS_*`.
- This full scrub is **new work**, not a copy of `forge claude start`: the only existing strip precedent is
  `_CODEX_CHILD_STRIP_VARS` (`src/forge/core/invoker/codex.py:55-65`, which already strips `ANTHROPIC_BASE_URL` +
  `FORGE_SUBPROCESS_*`); run-tree var names live in `src/forge/core/reactive/env.py:39-41`. A test must assert the child
  env carries none of the above.
- Mint a fresh command/proxy attribution root only if the proxy needs request attribution headers or env; that fresh
  root must not imply a Forge session and must not inherit the parent session tree.
- Preserve Codex's normal cwd and config search behavior (`$CODEX_HOME/config.toml`, project `.codex/config.toml`).
- Support the Codex sandbox flag shape that the live probe confirms, at least
  `--sandbox read-only|workspace-write|danger-full-access` if still accepted by the installed Codex CLI.
- Pass through remaining Codex args only after the proxy contract and sandbox handling are pinned.

First implementation should be deliberately narrow: proxy-backed TUI launch only. Do not add native-direct aliases,
resume, preset editing, or session registration. Narrow does not mean cheap: this slice is blocked on the Slice 1 probe
result and the Slice 2 transport, neither of which is "reuse `forge claude start`".

### Responses proxy contract

This card must include an explicit discovery/probe slice before implementation locks down CLI behavior. The probe should
answer:

- Which env vars, config keys, or command-line flags make Codex use a local Responses-compatible base URL.
- **The routing channel explicitly**: env/argv vs a `config.toml` `model_provider` block. This is a go/no-go input (see
  Slice 1 and Risks): an env/argv hook keeps the launcher's "configure child env" design viable; a config-only hook does
  not.
- Whether Codex requires a downstream API key for the local proxy and what token shape is safest.
- Whether Codex sends all model traffic through the configured base URL or retains any native-direct path.
- How Codex reports model, provider, request id, and streaming events through the Responses route.
- Which request and response fields the Forge proxy can record for provider trace, costs, audit, and policy hooks.
- What readiness check `forge runtime preflight codex --proxy <id-or-template>` should perform.

The implementation should not guess these details from the Claude proxy path. `ANTHROPIC_BASE_URL` is not transferable
to Codex.

### `forge codex status`

A cheap, read-only command that spends no model turn and does not edit Codex config.

It should report:

- Codex binary presence and detected version (`get_runtime("codex").detect()`).
- The relevant Codex config path(s):
  - default: detected Forge installation scope when one is known;
  - `--scope user|project|local` to inspect a specific scope;
  - `--all` to show every scope Forge can reason about.
- Tracking state from `~/.forge/installed.json`: `codex_config_path` and `codex_commands`, when present.
- Managed block presence via `read_codex_registration(...).block_present`.
- Expected event-aware registration pairs via `codex_registration_pairs(...)`:
  - `SessionStart -> forge hook codex-session-start`;
  - `PreToolUse -> forge hook codex-policy-check`.
- A static enrollment posture:
  - `registered: yes/no/partial/wrong-event`;
  - `enrollment: unverified by static read`;
  - `verify: forge runtime preflight codex --verify-enrollment`.
- Proxy readiness hints:
  - whether `forge runtime preflight codex --proxy <id-or-template>` is available;
  - whether a selected proxy advertises Responses support when `--proxy` is provided to `status`.

It must not claim enrollment from `config.toml`. The empirical answer belongs to
`forge runtime preflight codex --verify-enrollment`, which intentionally runs a real probe turn.

`--json` should expose the same fields with stable names for scripting.

### No `forge codex preset`

`forge claude preset` is editable because Forge owns `~/.forge/claude.preset.json` and merges it into Claude's
`settings.json`. Codex config is codex-owned `config.toml`, and Forge's one contribution to it is trust-frozen. An
editable Codex preset would invent ownership the design does not grant and would silently break enrollment on edit.

## Runtime visibility

Do not gate the entire `forge codex` group. The group is diagnostic and should remain reachable even when `codex` is
absent.

Recommended behavior:

| Surface                                      | Registration  | Absent-binary or unsupported-proxy behavior                                       |
| -------------------------------------------- | ------------- | --------------------------------------------------------------------------------- |
| `forge claude`                               | Unconditional | Primary runtime; invocation can print install/setup guidance                      |
| `forge codex status`                         | Unconditional | Reports `installed: false`, registration/tracking if any, and setup guidance      |
| `forge codex start --proxy <id-or-template>` | Unconditional | Runs preflight and fails with clear install or Responses-proxy readiness guidance |
| Native-direct `forge codex start`            | Not present   | Use raw `codex`; help should not imply Forge owns native-direct sessionless Codex |

This avoids import-time conditional registration complexity for the accepted surface. If later optional launcher leaves
are conditionally registered, tests should exercise them in subprocesses or with explicit module reload isolation,
because command registration happens at import time in `src/forge/cli/main.py`.

## Risks

- **Proxy transport scope creep.** Responses proxy support is larger than a command-group card — it is a from-scratch
  transport (see Slice 2). Mitigation: the Type note splits it into an epic member gated on the Slice 1 probe; do not
  carry it as one vertical with the CLI.
- **Routing may require the file Forge must not own.** Codex auth is `CODEX_API_KEY` with no base-URL companion in the
  credential registry (`src/forge/core/credential_registry.py`). If the Slice 1 probe finds Codex accepts a local base
  URL only via a `config.toml` `model_provider` block (not env/argv), then "configure the child env" — the launcher's
  whole mechanism — is the wrong tool, and routing would mean writing/merging codex-owned `config.toml`: the exact
  trust-frozen file this card forbids Forge from owning. Mitigation: the Slice 1 go/no-go gates on this; an
  env/argv-incapable result fails the launcher rather than reopening Forge ownership of `config.toml`.
- **False readiness.** A proxy may be healthy for Anthropic-compatible routes but not for Codex Responses traffic.
  Mitigation: advertise and test a specific Responses capability, and make preflight check that capability.
- **Auth mixing.** Codex native auth and Forge proxy upstream auth could conflict or leak. Mitigation: define the local
  proxy auth contract and test that native upstream credentials are not passed when proxy auth owns upstream access.
- **Thin wrapper drift.** Adding native-direct `forge codex start` would collapse the value proposition back into a thin
  alias. Mitigation: keep native-direct launch out of this card.
- **Surface confusion.** Users may confuse sessionless proxy launch with managed Codex sessions. Mitigation: help and
  docs state "no Forge session, no Forge resume, no `confirmed.codex`."
- **False enrollment claims.** Static config reads cannot prove trust enrollment. Mitigation: status reports
  registration facts and points to the empirical verifier.
- **Wrong-event false positives.** Command strings can exist under the wrong event. Mitigation: status uses
  `codex_registration_pairs()` for correctness.
- **Leaked managed-session context.** A sessionless launcher could inherit `FORGE_SESSION` or parent run ids from a
  managed shell. Mitigation: full env scrub acceptance tests plus a fresh attribution root when proxy telemetry needs
  one.

## Slices

1. **Live-probe Codex proxy contract (hard go/no-go gate).** Pin how the installed Codex CLI accepts a
   Responses-compatible base URL, local proxy auth, sandbox flags, and pass-through args. Report the routing channel
   explicitly (env/argv vs `config.toml` `model_provider`). **Kill criterion**: if Codex has no env/argv hook for a
   local base URL — i.e. routing is reachable only by writing codex-owned `config.toml` — then
   `forge codex start --proxy` is infeasible as designed (the launcher configures child *env*, and the card forbids
   Forge owning `config.toml`); stop, do not work around it. Document the exact env/config/argv contract in the card
   closeout or design docs.
2. **Build the Responses proxy transport (the largest piece — from scratch). Shipped as a passthrough (revised).** The
   proxy previously served only `/v1/messages` + `/v1/messages/count_tokens` (`src/forge/proxy/server.py`), and the
   `proxy_supported` value in the `ProxyResponses` literal was **dead code** — `_resolve_responses_posture` only ever
   returned `native_direct` or `proxy_unsupported`. The card originally scoped this as OpenAI-Responses ↔ internal
   **converters** + SSE translation. That was **reversed during execution**: translation drops Codex's signed
   reasoning-item continuity (the failure `anthropic_passthrough` exists to avoid), so the slice instead adds an
   `openai_responses_passthrough` wire shape that forwards Codex's raw Responses traffic byte-for-byte. Shipped:
   `POST /v1/responses` + a method/body/query-aware catch-all over the whole `/v1/responses*` surface
   (`src/forge/proxy/server.py`); a raw-SSE relay (`src/forge/proxy/stream_relay.py` + `responses_passthrough.py`); a
   real `responses_ingress` capability advertised on `GET /`; and the live `proxy_supported` return path gated on
   `wire_shape == openai_responses_passthrough` AND the source's `responses_ingress`, mirrored exactly in
   `forge runtime preflight codex --proxy`. Tier re-routing + a core.llm reasoning channel are deferred. Multi-file
   transport work, not a config toggle — the epic member named in the Type note.
3. **`forge codex start --proxy`.** New `src/forge/cli/codex.py` group with proxy-backed TUI launch; ensure/adopt proxy,
   health-check capability, configure child, scrub inherited env, and launch foreground Codex. Blocked on Slices 1 and
   2\.
4. **Proxy observability mapping.** Ensure downstream telemetry, provider trace, costs, and audit fields are populated
   for Responses requests at the minimum level needed to justify the proxy-backed value proposition.
5. **`forge codex status`.** Add read-only status with binary/version, config tracking, managed block, event-aware
   registration, static enrollment posture, and optional proxy readiness hints. Independent of Slices 1-4; shippable
   first as the standalone card named in the Type note.
6. **Docs.** Update `cli_reference.md`, `docs/end-user/session.md`, `docs/end-user/hook.md`, and the relevant design
   docs for the sessionless proxy launch contract and the no-preset/no-static-enrollment boundary.

## Acceptance tests

| Test                                            | Fixture                                      | Assertion                                                                                                                                              | Test File                                     |
| ----------------------------------------------- | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------- |
| Proxy serves a Responses request end-to-end     | proxy with the new Responses route (Slice 2) | proxy accepts a Responses-shaped POST and relays it byte-for-byte (passthrough, no translation); `GET /` advertises `responses_ingress`                | `tests/src/proxy/test_responses_transport.py` |
| Proxy start ensures selected proxy              | proxy id/template fixture                    | launcher starts or adopts the proxy before execing `codex`                                                                                             | `tests/src/cli/test_codex_launcher.py`        |
| Proxy start rejects non-Responses proxy         | proxy advertises no Responses capability     | command fails before launch with actionable "Responses-capable proxy required" guidance                                                                | same                                          |
| Proxy start configures Codex child              | mocked `codex` executable                    | child receives the probe-pinned base URL/auth/config and routes through local proxy                                                                    | same                                          |
| Proxy start does not leak upstream native creds | native Codex/OpenAI env set                  | child env omits upstream credentials when proxy owns upstream auth, except any local proxy token required                                              | same                                          |
| Proxy start scrubs managed-session context      | Forge session/root/run vars set              | child env lacks inherited session/root/run/proxy vars (incl. `FORGE_RUN_ID`/`FORGE_ROOT_RUN_ID`) or receives only a fresh non-session attribution root | same                                          |
| Proxy start needs no `.forge/`                  | CWD without `.forge/`                        | launcher reaches `codex` exec when runtime and proxy preflight pass                                                                                    | same                                          |
| Proxy start preserves Codex config search       | project `.codex/config.toml` present         | launcher does not overwrite/stub config; Codex receives normal cwd/config behavior                                                                     | same                                          |
| Proxy preflight detects unsupported mode        | Codex installed, proxy not capable           | `forge runtime preflight codex --proxy <id>` reports proxy unsupported with remediation                                                                | `tests/src/cli/test_runtime_codex.py`         |
| Status works when Codex absent                  | PATH excludes `codex`                        | `forge codex status` exits 0 and reports `installed: false`                                                                                            | `tests/src/cli/test_codex_status.py`          |
| Status reports managed block                    | config has Forge markers                     | output shows config path, `block_present: true`, and registered commands                                                                               | same                                          |
| Status catches wrong-event registration         | command under wrong Codex event              | output reports wrong-event/partial, not `registered: yes`                                                                                              | same                                          |
| Status does not claim enrollment                | managed block present                        | output says enrollment is unverified and points to `forge runtime preflight codex --verify-enrollment`                                                 | same                                          |
| Status supports JSON                            | any                                          | stable JSON fields for binary, config path, block, expected pairs, tracking, and verification command                                                  | same                                          |
| Top-level group remains visible for diagnostics | PATH excludes `codex`                        | `forge --help` lists `codex`; `forge codex status` explains missing runtime                                                                            | `tests/integration/cli/test_help.py`          |

## Open questions

- **Exact Codex proxy contract.** Which env/config/argv path does the installed Codex CLI support for a local
  Responses-compatible base URL? (Slice 1 go/no-go — a config-only path fails the launcher; see Risks.)
- **Local proxy auth shape.** Should the local proxy accept a generated bearer token, a Forge-owned ephemeral secret, or
  no downstream auth on loopback?
- **Responses telemetry minimum.** Which provider-trace, cost, and audit fields are required for this first vertical
  path to be considered useful?
- **Policy/audit compatibility.** Can the existing proxy audit/intercept path safely inspect and control Responses
  traffic, or does first ship only trace/cost visibility?
- **Fresh attribution root.** What exact non-session run identity should proxy telemetry use for a sessionless launch?
- **Native-direct wrapper later.** Likely no. If users want it, evaluate separately with a concrete value beyond
  `codex`.

## Out of scope

- Native-direct `forge codex start`; use raw `codex`.
- `forge codex start --no-proxy`.
- Re-implementing or aliasing the session-managed Codex path (`forge session start/resume --runtime codex`).
- Any Forge-owned Codex settings file or `forge codex preset`.
- Building a Gemini launcher.
- Changing the runtime registry schema beyond what proxy preflight requires.
- Running an empirical enrollment check inside `forge codex status`.

## References

- `docs/design.md` §3.4 (bare-launch contract), §3.5 (`confirmed.codex` CLI-owned), §3.9 (Codex session lifecycle)
- `src/forge/cli/claude.py` - `forge claude` group and bare proxy launcher (lifecycle reuse; env-scrub is only the three
  session vars)
- `src/forge/session/claude/invoke.py:194` - bare Claude launch env shaping; pops only `FORGE_PARENT_RUN_ID`
- `src/forge/core/invoker/codex.py:55-65` - `_CODEX_CHILD_STRIP_VARS`, the real child-env strip precedent (native-direct
  headless invoker)
- `src/forge/core/reactive/env.py:39-41` - run-tree env var names
  (`FORGE_RUN_ID`/`FORGE_PARENT_RUN_ID`/`FORGE_ROOT_RUN_ID`)
- `src/forge/cli/main.py` - root command registration and help formatting
- `src/forge/core/runtime/codex_preflight.py` - native Codex readiness; `ProxyResponses` literal with the dead
  `proxy_supported` value `_resolve_responses_posture` never returns
- `src/forge/proxy/server.py`, `src/forge/proxy/converters.py`, `src/forge/proxy/passthrough.py` - proxy route surface
  and wire converters the Responses transport (Slice 2) must extend; today the proxy serves only `/v1/messages` +
  `/v1/messages/count_tokens`
- `src/forge/core/runtime/registry.py` - runtime specs and binary detection
- `src/forge/session/codex_invoke.py` - managed interactive Codex launcher, intentionally session-bound
- `src/forge/install/codex_hooks.py` - managed-block read/write, `read_codex_registration`, `codex_registration_pairs`
- `src/forge/install/models.py` - `installed.json` Codex tracking (`codex_config_path`, `codex_commands`)
- `src/forge/core/ops/codex_enrollment.py` - empirical enrollment verification
- `src/forge/install/preset.py` - Claude preset ownership model
- `docs/board/done/codex_frontend/card.md` - shipped session-managed Codex runtime
