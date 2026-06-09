# Codex `exec --json` fixtures

Recorded JSONL event streams from a real `codex exec --json` run. These are **authoritative** for
`parse_codex_jsonl_stream` (`src/forge/core/invoker/codex_stream.py`): when the binary's stream shape disagrees with any
doc, the fixture wins.

## Provenance

- **Binary**: `codex-cli 0.137.0` (`/opt/homebrew/bin/codex`)
- **Date**: 2026-06-08
- **Auth**: ChatGPT account (`auth_method=chatgpt_tokens`, `billing_mode=subscription_quota`)
- **Capture dir**: throwaway temp dir (not a git repo), hence `--skip-git-repo-check`
- Prompt is piped via **stdin** (mirrors the invoker's `input=request.prompt`), not passed positionally.

| File                            | Command                                                                                                                                                      | Exit |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---- |
| `exec_json_success.jsonl`       | `printf 'reply with the single word OK' \| codex exec --json --sandbox read-only --skip-git-repo-check -o last_message.txt`                                  | 0    |
| `exec_last_message_success.txt` | `-o last_message.txt` from the run above (the correctness oracle; content is exactly `OK` — a text-normalizer may add a trailing newline the test `rstrip`s) | 0    |
| `exec_json_error.jsonl`         | `printf 'reply with the single word OK' \| codex exec --json --sandbox read-only --skip-git-repo-check -m totally-invalid-model-zzz-999`                     | 1    |

## Pinned stream shape (what the parser reduces)

Each line is one event: `{"type": <event>, ...}`.

- `thread.started` -> `{thread_id}` (the resume/session id; not a secret).
- `turn.started` -> no payload.
- `item.completed` -> `{item: {id, type, text}}`. The assistant text is `item.text` where
  `item.type == "agent_message"`. Concatenate these in order to get `final_text`.
- `turn.completed` -> `{usage: {input_tokens, cached_input_tokens, output_tokens, reasoning_output_tokens}}`. Map:
  `input_tokens` -> input, `output_tokens` -> output, `cached_input_tokens` -> cached. `reasoning_output_tokens` is a
  **subset** of `output_tokens` (Responses usage is inclusive) — **do not sum** it into output, and it is not lifted (no
  `HeadlessResult` field). One terminal `turn.completed` per `codex exec`, so the parser's last-wins assignment == the
  only value.

### Error shape

A failed turn emits **two** terminal events and exits non-zero, with **no** `turn.completed` (so no usage):

- `{"type": "error", "message": <stringified provider error>}`
- `{"type": "turn.failed", "error": {"message": <stringified provider error>}}`

`parse_codex_jsonl_stream` maps the presence of either `error` or `turn.failed` to `runtime_is_error=True`.

## Secret-free

Streams were scanned for home paths, API keys, and bearer tokens before commit (none present). `thread_id` is a per-run
UUID, kept verbatim. The error `message` only names the rejected model and "ChatGPT account" (not a secret).

## Re-recording

`codex exec` runs are **billed**. Re-record only when the stream shape changes (new Codex major). Use a trivial prompt
and a throwaway dir, then re-scan for secrets before committing.
