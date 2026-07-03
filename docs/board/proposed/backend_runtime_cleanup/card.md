# Backend runtime cleanup -- stop backend instances by id or all at once

**Lane**: `proposed/`. Focused CLI ergonomics/ops card, not an architecture rewrite.

**Scheduling status (2026-07-02)**: **Step 2** of an agreed interleave -- sequenced **after**
[`cli_style_ux_compliance`](../cli_style_ux_compliance/card.md) **A1** (now active in
`docs/board/doing/cli_error_stream_stderr/`, branch `fix/cli-error-stream-stderr`). When this card starts, **fold in
cli_style B1 backend-help** in the same PR (define source-id vs runtime-instance-id vs adapter in the `backend` group
help; fix B1's 3 verified traps; **help-only, no metavar rename**), since both edit `backend.py` help. Stays parked in
`proposed/` until Step 1 ships.

**Origin**: stale local backend/proxy debugging, 2026-07-02. The proxy incident made the operator gap visible: when a
local LiteLLM backend is suspected of carrying stale credentials or other bad process state, Forge has a clean
`forge proxy delete --all` path for proxies but no equally direct backend-runtime cleanup path. For backends, the
runtime object is a process/registry entry rather than durable config, so the cleanup verb should be `stop`, not
`delete`.

**Relationship to existing work**:

- Builds on `unified_backend`: catalog source ids and runtime instance ids are intentionally separate value-spaces.
- Distinct from, but coupled to, `proposed/cli_style_ux_compliance` B1/C2, which improves help/metavar clarity for the
  same id-space split. This card adds the missing operator behavior.
- Does not make remote backend sources lifecycle-managed. Remote sources remain built-in/static definitions with no
  local process to delete.

## Problem

`forge model backend` has two legitimate identity spaces:

| Identity                  | Example        | Meaning                                                                |
| ------------------------- | -------------- | ---------------------------------------------------------------------- |
| Catalog backend/source id | `openrouter`   | Static upstream model endpoint/capacity unit used by proxies/telemetry |
| Local runtime instance id | `litellm-4000` | Running local process registered by Forge                              |

That split is correct, but the lifecycle surface makes the runtime identity feel second-class:

- `forge model backend show litellm-4000` accepts a runtime instance id.
- `BackendInstance.backend_id` stores that id in the runtime registry.
- `BackendManager.stop_backend(backend_id)` already stops/unregisters by runtime id.
- But `forge model backend stop` only accepts a source-or-adapter operand today, not the runtime id shown by `list` /
  `show`, and it has no bulk form.
- `forge model backend delete` also has an indirect runtime spelling today (`delete litellm --port 4000`), while
  `delete litellm` means config deletion. That overload makes the cleanup path harder to reason about.
- There is no bulk cleanup equivalent to `forge proxy delete --all`.

So when an operator wants to flush suspect local backend processes after credential changes or a bad upstream state, the
current choices are either too indirect (`adapter + --port`) or too broad in the wrong dimension (delete the adapter
config).

## Grounding (verified 2026-07-02)

- `BackendInstance.backend_id` is already the runtime-instance id (`litellm-4000`) in `src/forge/backend/registry.py`.
- `BackendRegistryStore.list_backends()` prunes dead Forge-spawned PIDs, but it does not clean alive-but-unhealthy
  processes and deliberately never auto-prunes `pid is None` entries.
- The LiteLLM adapter's `stop()` is a no-op when `instance.pid is None`; `BackendManager.stop_backend()` still removes
  the registry entry after calling the adapter.
- `forge model backend show <id>` already accepts either a catalog source id or a runtime backend id.
- `forge model backend stop` currently resolves a local source id or adapter+port to a runtime id.
- `forge model backend delete` currently resolves its positional as a local adapter/source operand and uses `--port` to
  target a specific instance; without `--port`, it deletes the adapter config directory.
- `forge proxy delete` accepts one or more proxy ids and `--all`; that shape is the desired operator precedent.
- `docs/design_appendix.md` says `create` and `delete` remain local adapter/config operations because built-in remote
  sources are not user-created durable state. This card should preserve that no-lifecycle boundary while improving local
  runtime cleanup.

## Vocabulary dependency

The broader `source id` wording problem belongs to `proposed/cli_style_ux_compliance` B1/C2: `ModelSource.id` is real
internally, but `source` is not a first-class CLI noun. This card should not settle that naming decision; it should only
ensure the new stop/delete help follows it. In this card's scope, call `litellm-4000` a **runtime instance id** and
avoid adding new unexplained `SOURCE_ID` wording.

## Proposal

Make local backend runtime instances first-class stop targets:

```bash
forge model backend stop litellm-4000
forge model backend stop litellm-4000 litellm-4001
forge model backend stop --all
forge model backend stop --all --yes
```

Semantics:

- A positional matching a registry `BackendInstance.backend_id` stops and unregisters that runtime instance. Adapter
  config remains in place.
- `--all` means all registered local runtime instances, matching the proxy-instance bulk-action precedent. It does
  **not** delete backend source definitions and does **not** delete adapter config directories.
- `--all` includes `pid is None` registry entries. Those entries should be unregistered, but Forge must not try to kill
  an unknown-owner process by port in this MVP. Report them distinctly, e.g. "unregistered pidless instance; no process
  was killed."
- `--all` cannot be combined with explicit targets.
- A missing target without `--all` exits non-zero with a tip to run `forge model backend list`.
- Clean break: `stop` accepts runtime instance ids, not catalog source ids or adapter+port. This avoids the shared-local
  source trap where `stop litellm-openai-local` actually stops the shared `litellm-4000` process backing other local
  sources too.
- Remove `forge model backend stop <adapter> --port <port>`. Use the runtime id (`litellm-4000`) instead.
- Bulk stop should preview target ids and prompt by default; `--yes` skips the prompt. Single explicit stops can keep
  the existing no-confirm behavior.
- `forge model backend delete <adapter>` becomes config deletion only. It may stop matching runtime instances first, but
  the command's object is the adapter config, not a runtime process.
- Remove `forge model backend delete <adapter> --port <port>` in the clean break. A runtime-id operand to `delete`
  should fail with a tip such as `Use 'forge model backend stop litellm-4000' to stop a runtime instance.`

Do **not** make `forge model backend stop openrouter` or `forge model backend delete openrouter` delete anything. A
remote catalog source should keep returning a clear no-local-lifecycle/no-local-config message.

## Start/stop asymmetry

This intentionally breaks the current `start X` / `stop X` inverse expectation. The objects are different:

- `start` is config-oriented. It starts a local lifecycle source or adapter config and may create/reuse the runtime
  instance that implements it.
- `stop` is process-oriented. It stops a live runtime instance row, because local sources can share one process
  (`litellm-openai-local` and `litellm-gemini-local` can both map to `litellm-4000`).

Do not add `start <runtime-id>` in this card. A runtime id is an observation of a local process row, not a durable
configuration object to start from when the row is absent. Keep start on local source ids / adapter config for now, and
make the asymmetry explicit in help and docs.

## Implementation notes

- Change `stop` from a single required `source_or_adapter` argument to explicit targets plus `--all`.
- Resolve explicit `stop` targets in this order:
  1. Runtime instance id present in `BackendRegistryStore.read().backends`.
  2. Known catalog source id or adapter rejected with a runtime-id-focused tip.
  3. Unknown id rejected with a `forge model backend list` tip.
- Add a helper that stops by runtime id using the registered instance's `adapter_type`, rather than reconstructing the
  id from adapter/port.
- For `stop --all`, read the registry once for the preview target list, then stop each runtime id with per-target error
  reporting. Continue after failures when stopping multiple targets, like proxy delete.
- Do not use `BackendRegistryStore.list_backends()` to compute the `--all` target set unless the intended prune side
  effect is explicit; read the registry directly so the preview can account for live, dead-PID, and pidless entries.
- Change `delete` to a config-only command: remove `--port`, check for runtime instance ids before adapter/source
  resolution, reject those runtime ids with a stop-focused tip, and keep stopping matching instances before deleting the
  adapter config.
- Leave `start` config-oriented and do not add runtime-id parsing there in this card.
- Keep adapter config deletion out of the `stop --all` path. A future config cleanup command can be designed separately
  if needed.

## Tests

| Test                          | Fixture                                                                                   | Assertion                                                                  |
| ----------------------------- | ----------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Stop by runtime id            | Registry has `litellm-4000`                                                               | stops/unregisters that instance; config remains                            |
| Stop multiple runtime ids     | Registry has two instances                                                                | both are attempted; failures are reported per target                       |
| Stop all runtime instances    | Registry has two instances                                                                | `stop --all --yes` removes both and leaves adapter config intact           |
| Stop all includes pidless     | Registry has `pid=None` instance                                                          | unregisters it, reports no process killed, exits zero                      |
| Empty all                     | Empty registry                                                                            | `stop --all` prints a no-target message and exits zero                     |
| Conflict guard                | `stop litellm-4000 --all`                                                                 | exits non-zero                                                             |
| Missing target guard          | `stop` with no target and no `--all`                                                      | exits non-zero with a `forge model backend list` tip                       |
| Remote stop boundary          | `stop openrouter`                                                                         | exits with intentional no-local-lifecycle message; no registry edit        |
| Stop rejects local source     | `stop litellm-openai-local`                                                               | exits with tip to use the runtime instance id from `backend list`          |
| Stop port clean break         | `stop litellm --port 4000`                                                                | exits non-zero; `--port` is no longer a stop option                        |
| Start remains config-oriented | `start litellm-4000`                                                                      | still rejected; start continues to use local source ids or adapter config  |
| Delete runtime-id precedence  | `delete litellm-4000` with that id in registry                                            | exits with a `stop litellm-4000` tip, not "Unknown backend adapter/source" |
| Delete port clean break       | `delete litellm --port 4000`                                                              | exits non-zero; `--port` is no longer a delete option                      |
| Adapter config spelling       | `delete litellm --yes`                                                                    | still deletes config and stops matching instances                          |
| Remote delete boundary        | `delete openrouter`                                                                       | exits with intentional no-local-config message; no registry edit           |
| Docs sync                     | help, `docs/cli_reference.md`, `docs/end-user/proxy.md`, `docs/design_appendix.md` §A.2.1 | start/config vs stop/runtime vs delete/config semantics are documented     |
| Source vocabulary guard       | `forge model backend --help` / stop/delete help                                           | "source" is defined or avoided; no unexplained `SOURCE_ID`-style leak      |

## Open questions

- Should there eventually be an `--unhealthy` filter? The MVP uses `--all` because the operator recovery case is "flush
  local backend runtime state," not "classify faulty state perfectly."
