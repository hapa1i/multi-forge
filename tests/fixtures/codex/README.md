# Codex `exec --json` fixtures

Recorded JSONL event streams from a real `codex exec --json` run. These are **authoritative** for
`parse_codex_jsonl_stream` (`src/forge/core/invoker/codex_stream.py`): when the binary's stream shape disagrees with any
doc, the fixture wins.

One exception is **source-derived** (not a live capture) -- see
[Synthesized fixtures](#synthesized-fixtures-source-derived).

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

- `{"type": "error", "message": <error text>}`
- `{"type": "turn.failed", "error": {"message": <error text>}}`

`parse_codex_jsonl_stream` maps the presence of either `error` or `turn.failed` to `runtime_is_error=True`.

The `exec --json` error event carries **only `message`** (a string) -- the structured discriminator the internal
protocol uses (`ErrorEvent.codex_error_info`, e.g. `usage_limit_exceeded`) and the HTTP status are **dropped at the exec
boundary** (`codex-rs/exec/src/exec_events.rs`: `ThreadErrorEvent { message: String }`). So `message` is the only
observable, and it takes **two shapes** depending on whether codex recognized the error:

- **Stringified provider JSON** (raw-leak path, e.g. the `400` in `exec_json_error.jsonl`): codex did not type the
  error, so `message` is the provider envelope `{"type":"error","status":<int>,"error":{"type":<str>,"message":<str>}}`.
- **Human prose** (typed path, e.g. the quota fixture below): codex mapped the backend error to a `CodexErr` whose
  `Display` is human text (`codex-rs/protocol/src/error.rs`). A spent ChatGPT subscription
  (`CodexErr::UsageLimitReached`) reaches exec as `"You've hit your usage limit. ..."` -- **no** `status`/`error.type`
  to parse.

This two-shape split is why any exhaustion classifier must both (a) substring-match the human prose and (b) fall back to
JSON-parsing the structured shape; it cannot rely on `status`/`error.type` alone.

## Synthesized fixtures (source-derived)

`exec_json_quota_exhausted.jsonl` is **not** a live capture (a `codex exec` quota hit cannot be triggered on demand
without spending a real subscription, which this dir avoids). It is **synthesized from the codex source**, and is
authoritative for the *shape*, not the *co-occurrence*:

- **Envelope** verified from `codex-rs/exec/src/exec_events.rs` (`ThreadErrorEvent { message: String }`,
  `TurnFailedEvent { error }`) -- byte-identical event structure to the recorded error fixture.
- **Message content** verified from `codex-rs/protocol/src/error.rs` -- the `UsageLimitReachedError` `Display` for a
  `Plus` plan with no `resets_at`. The invariant across **all** plan branches (Plus/Pro/Team/Business/Free/Go/
  Enterprise/Edu/Unknown) is the substring `hit your usage limit`; sibling exhaustion variants are `out of credits`
  (credits depleted), `spend cap` (workspace usage limit), `Quota exceeded. Check your plan and billing details.`
  (`QuotaExceeded`), and `To use Codex with your ChatGPT plan, upgrade to Plus` (`UsageNotIncluded`).
- **Source pin**: `openai/codex` `main` @ `db887d03e1f907467e33271572dffb73bceecd6b` (2026-06-30); runtime is tag
  `rust-v0.137.0`. The classifier anchors on the version-stable invariant substring, not the full Plus string, to
  survive copy drift between the read SHA and the installed runtime.
- `thread_id` is a synthetic all-zero-ish UUID (signals "not a real run"); no secrets.

Used by the T7 exhaustion classifier truth table as the positive wire-shape sample. If a future `codex` major changes
the `UsageLimitReached` `Display`, re-derive from `error.rs` (no billing needed) and update the anchor set.

## Secret-free

Streams were scanned for home paths, API keys, and bearer tokens before commit (none present). `thread_id` is a per-run
UUID, kept verbatim. The error `message` only names the rejected model and "ChatGPT account" (not a secret).

## Re-recording

`codex exec` runs are **billed**. Re-record only when the stream shape changes (new Codex major). Use a trivial prompt
and a throwaway dir, then re-scan for secrets before committing.
