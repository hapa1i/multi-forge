# forge codex command group: proxy-backed sessionless Codex launcher

**Status**: Proposed implementation card. The accepted product value is `forge codex start --proxy <id-or-template>`: a
sessionless Codex TUI routed through a Forge-managed, Responses-capable proxy. Nothing in this card is shipped yet.
`docs/design.md` §3.4/§3.5/§3.9 remain normative; this card defers to them on conflict.

**Type**: Single implementation card if it owns the CLI surface plus the first Responses-proxy capability slice. Split
into an epic if the proxy transport, audit, or telemetry work grows beyond a thin vertical path.

## Summary

Add a `forge codex` command group centered on:

- `forge codex start --proxy <id-or-template>`: sessionless Codex TUI through a Forge proxy.
- `forge codex status`: read-only inspection of Forge's Codex footprint and readiness hints.

Do **not** ship a native-direct `forge codex start` or `forge codex start --no-proxy` in this card. Native-direct,
untracked Codex use already has the first-party command: `codex`.

The value proposition matches the strong half of `forge claude start --proxy`: Forge starts or adopts the proxy,
health-checks it, configures the child runtime to use the local proxy, scrubs inherited Forge session context, and gives
operators Forge telemetry/provider-trace/cost/audit control over otherwise sessionless usage. The difference is that
Codex needs an OpenAI Responses-compatible proxy path, not the Claude `ANTHROPIC_BASE_URL` path.

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
Responses proxy mode as unsupported. This card is therefore not just CLI plumbing; it must establish a first
Responses-capable proxy contract for Codex.

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

| Constraint                                                                                                      | Source                                                                                                       | Implication for `forge codex`                                                                                                                                  |
| --------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Current Codex runtime is native-direct; Forge proxy mode is marked unsupported                                  | `docs/design.md` §3.4; `src/forge/core/runtime/codex_preflight.py`                                           | This card must add or prove a Responses-capable proxy path before the launcher can be considered ready.                                                        |
| `forge claude start --proxy` already owns the comparable proxy lifecycle pattern                                | `src/forge/cli/claude.py`; `src/forge/session/claude/invoke.py`                                              | Reuse the shape: ensure/adopt proxy, health-check, configure child env, foreground TUI, pass through appropriate args, scrub inherited session context.        |
| Managed Codex sessions always write Forge session state                                                         | `docs/design.md` §3.5/§3.9; `src/forge/core/ops/codex_session.py`; `src/forge/core/ops/codex_interactive.py` | `forge codex start --proxy` is sessionless and records no `confirmed.codex`; docs must distinguish it from `forge session start/resume --runtime codex`.       |
| Codex hooks are enrollment-gated and can fire for user-scope registrations outside Forge sessions               | `docs/design.md` §3.9; `src/forge/cli/hooks/codex_transfer.py`                                               | The launcher must scrub inherited Forge session/root env so hooks resolve no managed session and stay silent.                                                  |
| Bare Claude launches mint a fresh run-tree root while scrubbing parent session identity                         | `src/forge/session/claude/invoke.py`                                                                         | Codex proxy launches may mint a fresh command/proxy attribution root if needed, but must not inherit parent run ids or set `FORGE_SESSION`/`FORGE_FORGE_ROOT`. |
| codex-cli owns `config.toml`; Forge only appends a managed block whose bytes are part of Codex's `trusted_hash` | `src/forge/install/codex_hooks.py`; `docs/design.md` §3.9                                                    | No `forge codex preset`. `forge codex status` is read-only by design.                                                                                          |
| `trusted_hash` is not computable from a config read                                                             | `src/forge/core/ops/codex_enrollment.py`                                                                     | `forge codex status` reports registration facts and verification guidance, never "enrolled: yes" from a static read.                                           |
| Registration correctness is event-aware                                                                         | `codex_registration_pairs()` vs `read_codex_registration()` in `src/forge/install/codex_hooks.py`            | Status must distinguish command strings that merely appear somewhere from expected `(event, command)` registrations that can actually fire.                    |
| `forge claude` remains the primary-runtime surface                                                              | `docs/design.md` §3.4; `src/forge/cli/claude.py`                                                             | Keep `forge claude` visible even when Claude is absent so its invocation can produce install/setup guidance. `forge codex status` should also remain visible.  |

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
- Mint a fresh command/proxy attribution root only if the proxy needs request attribution headers or env; that fresh
  root must not imply a Forge session and must not inherit the parent session tree.
- Preserve Codex's normal cwd and config search behavior (`$CODEX_HOME/config.toml`, project `.codex/config.toml`).
- Support the Codex sandbox flag shape that the live probe confirms, at least
  `--sandbox read-only|workspace-write|danger-full-access` if still accepted by the installed Codex CLI.
- Pass through remaining Codex args only after the proxy contract and sandbox handling are pinned.

First implementation should be deliberately narrow: proxy-backed TUI launch only. Do not add native-direct aliases,
resume, preset editing, or session registration.

### Responses proxy contract

This card must include an explicit discovery/probe slice before implementation locks down CLI behavior. The probe should
answer:

- Which env vars, config keys, or command-line flags make Codex use a local Responses-compatible base URL.
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

- **Proxy transport scope creep.** Responses proxy support may be larger than a command-group card. Mitigation: require
  a probe slice and split if proxy transport, audit, or telemetry work is not a thin vertical path.
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

1. **Live-probe Codex proxy contract.** Pin how the installed Codex CLI accepts a Responses-compatible base URL, local
   proxy auth, sandbox flags, and pass-through args. Document the exact env/config/argv contract in the card closeout or
   design docs.
2. **Responses-capable proxy readiness.** Add or expose a proxy capability signal for OpenAI Responses traffic; teach
   `forge runtime preflight codex --proxy <id-or-template>` to require it.
3. **`forge codex start --proxy`.** New `src/forge/cli/codex.py` group with proxy-backed TUI launch; ensure/adopt proxy,
   health-check capability, configure child, scrub inherited env, and launch foreground Codex.
4. **Proxy observability mapping.** Ensure downstream telemetry, provider trace, costs, and audit fields are populated
   for Responses requests at the minimum level needed to justify the proxy-backed value proposition.
5. **`forge codex status`.** Add read-only status with binary/version, config tracking, managed block, event-aware
   registration, static enrollment posture, and optional proxy readiness hints.
6. **Docs.** Update `cli_reference.md`, `docs/end-user/session.md`, `docs/end-user/hook.md`, and the relevant design
   docs for the sessionless proxy launch contract and the no-preset/no-static-enrollment boundary.

## Acceptance tests

| Test                                            | Fixture                                  | Assertion                                                                                                   | Test File                              |
| ----------------------------------------------- | ---------------------------------------- | ----------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| Proxy start ensures selected proxy              | proxy id/template fixture                | launcher starts or adopts the proxy before execing `codex`                                                  | `tests/src/cli/test_codex_launcher.py` |
| Proxy start rejects non-Responses proxy         | proxy advertises no Responses capability | command fails before launch with actionable "Responses-capable proxy required" guidance                     | same                                   |
| Proxy start configures Codex child              | mocked `codex` executable                | child receives the probe-pinned base URL/auth/config and routes through local proxy                         | same                                   |
| Proxy start does not leak upstream native creds | native Codex/OpenAI env set              | child env omits upstream credentials when proxy owns upstream auth, except any local proxy token required   | same                                   |
| Proxy start scrubs managed-session context      | Forge session/root/run vars set          | child env lacks inherited session/root/run/proxy vars or receives only a fresh non-session attribution root | same                                   |
| Proxy start needs no `.forge/`                  | CWD without `.forge/`                    | launcher reaches `codex` exec when runtime and proxy preflight pass                                         | same                                   |
| Proxy start preserves Codex config search       | project `.codex/config.toml` present     | launcher does not overwrite/stub config; Codex receives normal cwd/config behavior                          | same                                   |
| Proxy preflight detects unsupported mode        | Codex installed, proxy not capable       | `forge runtime preflight codex --proxy <id>` reports proxy unsupported with remediation                     | `tests/src/cli/test_runtime_codex.py`  |
| Status works when Codex absent                  | PATH excludes `codex`                    | `forge codex status` exits 0 and reports `installed: false`                                                 | `tests/src/cli/test_codex_status.py`   |
| Status reports managed block                    | config has Forge markers                 | output shows config path, `block_present: true`, and registered commands                                    | same                                   |
| Status catches wrong-event registration         | command under wrong Codex event          | output reports wrong-event/partial, not `registered: yes`                                                   | same                                   |
| Status does not claim enrollment                | managed block present                    | output says enrollment is unverified and points to `forge runtime preflight codex --verify-enrollment`      | same                                   |
| Status supports JSON                            | any                                      | stable JSON fields for binary, config path, block, expected pairs, tracking, and verification command       | same                                   |
| Top-level group remains visible for diagnostics | PATH excludes `codex`                    | `forge --help` lists `codex`; `forge codex status` explains missing runtime                                 | `tests/integration/cli/test_help.py`   |

## Open questions

- **Exact Codex proxy contract.** Which env/config/argv path does the installed Codex CLI support for a local
  Responses-compatible base URL?
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
- `src/forge/cli/claude.py` - `forge claude` group and bare proxy launcher
- `src/forge/session/claude/invoke.py` - bare Claude launch env shaping and fresh run-tree attribution
- `src/forge/cli/main.py` - root command registration and help formatting
- `src/forge/core/runtime/codex_preflight.py` - native Codex readiness and current Responses/proxy posture
- `src/forge/core/runtime/registry.py` - runtime specs and binary detection
- `src/forge/session/codex_invoke.py` - managed interactive Codex launcher, intentionally session-bound
- `src/forge/core/invoker/codex.py` - Codex child env sanitization and native-direct headless invoker
- `src/forge/install/codex_hooks.py` - managed-block read/write, `read_codex_registration`, `codex_registration_pairs`
- `src/forge/install/models.py` - `installed.json` Codex tracking (`codex_config_path`, `codex_commands`)
- `src/forge/core/ops/codex_enrollment.py` - empirical enrollment verification
- `src/forge/install/preset.py` - Claude preset ownership model
- `docs/board/done/codex_frontend/card.md` - shipped session-managed Codex runtime
