# Codex hook payload fixtures

Sanitized hook-payload JSON (one `*.stdin.json` per Codex lifecycle event observed firing). These pin the future
`CodexHookAdapter`'s payload parsers (`codex_frontend` Phase 3) the way `../exec_json_success.jsonl` pins
`parse_codex_jsonl_stream`. When the binary's payload shape disagrees with any doc, the fixture wins.

> **Status: captured 2026-06-10** (codex-cli 0.138.0). Five payloads promoted from the round-3 enrolled-fixture probe
> (`scripts/experiments/codex-hooks` stages 80-81). Re-record only on a Codex major (the steps below stand).

## How these are produced

1. Run the enrollment ceremony + headless coverage probe:
   ```bash
   scripts/experiments/codex-hooks/reproduce.sh 80   # operator trust ceremony (builds the fixture)
   scripts/experiments/codex-hooks/reproduce.sh 81    # fires every event; raw payloads -> capture dir
   ```
   Raw captures land at
   `${CODEX_HOOKS_CAPTURE_DIR:-~/.cache/forge-codex-hooks-probe}/81-enrolled-coverage/payloads/<Event>-<ts>.stdin.json`.
2. Sanitize and scan (replaces `$HOME`/`$USER`/probe paths, then FAILS LOUDLY on residual secrets):
   ```bash
   scripts/experiments/codex-hooks/sanitize.sh
   ```
3. Promote **one** sanitized payload per event observed firing into this directory, renaming to
   `<snake_event>.stdin.json` (e.g. `session_start.stdin.json`, `pre_tool_use.stdin.json`), and fill in the provenance
   row below. Deliberately exclude the `env/` and `streams/` captures (higher sanitization risk, lower test value — the
   exec streams are already covered by `../exec_json_*.jsonl`).
4. `make pre-commit` (gitleaks) must be clean on the promoting commit.

## Provenance

- **Binary**: codex-cli 0.138.0 (`/opt/homebrew/bin/codex`)
- **Date**: 2026-06-10
- **Auth**: ChatGPT account, isolated `CODEX_HOME` (never the real `~/.codex`)
- **Capture**: round-3 enrolled fixture; payloads via the per-label tee wrapper (`tee-hook.sh`), so attribution does not
  depend on the `hook_event_name` field. Stage 81 runs several `codex exec` turns from the one enrolled home, so these
  five payloads span three of them (distinguishable by `session_id`): the 81.0 body-swap revalidate turn (prompt "reply
  with the single word OK"), the 81.1 read-only matrix turn (`echo PROBE-RT-1`), and the 81.1 workspace-write matrix
  turn (`apply_patch` of `probe.txt`). The "Source turn" column records which. Paths sanitized to `<HOME>`;
  `session_id`/`turn_id`/`tool_use_id` are per-run identifiers kept verbatim (not secrets).

| File                            | Event              | Source turn         | codex version | Notes                                                            |
| ------------------------------- | ------------------ | ------------------- | ------------- | ---------------------------------------------------------------- |
| `session_start.stdin.json`      | `SessionStart`     | 81.0 revalidate     | 0.138.0       | carries `source: "startup"`                                      |
| `pre_tool_use.stdin.json`       | `PreToolUse`       | 81.1 matrix (r/o)   | 0.138.0       | `tool_name: "Bash"`, `tool_input.command`, `tool_use_id`         |
| `post_tool_use.stdin.json`      | `PostToolUse`      | 81.1 matrix (write) | 0.138.0       | `tool_name: "apply_patch"` (file write); carries `tool_response` |
| `user_prompt_submit.stdin.json` | `UserPromptSubmit` | 81.0 revalidate     | 0.138.0       | carries the `prompt` string                                      |
| `stop.stdin.json`               | `Stop`             | 81.0 revalidate     | 0.138.0       | carries `last_assistant_message`, `stop_hook_active`             |

## Confirmed shape (round 3, 0.138.0)

Confirmed `snake_case`: common `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `model`, `permission_mode`;
SessionStart adds `source` (observed `"startup"`); turn-scoped events add `turn_id`; PreToolUse adds
`tool_name`/`tool_use_id`/`tool_input`; PostToolUse adds `tool_response`; UserPromptSubmit adds `prompt`; Stop adds
`last_assistant_message`/`stop_hook_active`. **`permission_mode` is `"bypassPermissions"` on `codex exec`** (vs
`"default"` interactively, round 2) — the adapter's execution-mode discriminator. **`tool_name` is `"Bash"` for shell
and `"apply_patch"` for file writes** — a PreToolUse matcher must match those names (the probe's `matcher = "shell"`
never fired). The captured fixture is authoritative over this paragraph.

## Secret-free

Payloads are sanitized (`sanitize.sh`) and scanned before commit. `session_id`/`transcript_path` are per-run
identifiers, kept verbatim (not secrets). No `auth.json`, API keys, or bearer tokens.
