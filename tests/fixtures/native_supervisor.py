"""Small synthetic histories for native-selector tests; these are not runtime evidence."""

import hashlib
import json

THREAD = "01a12b5c-ce1a-72c2-ad3f-05d75f3fba00"
TURN = "01a12b76-ad83-7083-aebf-1dc70fddbbc0"
CHILD = "01a12b73-202d-7dd0-a058-f74ec9375dd2"


def synthetic_rows(thread=THREAD, *, complete=True):
    def event(kind, **fields):
        return {"type": "event_msg", "payload": {"type": kind, **fields}}

    rows = [
        {
            "type": "session_meta",
            "payload": {
                "id": thread,
                "session_id": thread,
                "cli_version": "0.162.1",
                "history_mode": "paginated",
                "creator_account_id": "synthetic-account",
                "source": "exec",
                "originator": "codex_exec",
                "model_provider": "openai",
                "cwd": "/synthetic-source",
                "base_instructions": {"text": "fixture"},
            },
        },
        event("task_started", turn_id=TURN),
        {"type": "turn_context", "payload": {"model": "gpt-6.1-sol", "effort": "low"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
                "content": [{"type": "output_text", "text": "BOUNDARY_DONE"}],
            },
        },
        event(
            "token_count",
            info={
                "total_token_usage": {"input_tokens": 812603, "cached_input_tokens": 523392, "output_tokens": 298},
                "last_token_usage": {"input_tokens": 81466},
            },
        ),
        {"type": "token_usage_record", "payload": {"thread_token_usage": {"input_tokens": 1056476}}},
    ]
    if complete:
        rows.append(event("task_complete", turn_id=TURN))
    return rows


def write_rollout(home, rows):
    path = home / "sessions/2026/10/11" / f"rollout-2026-10-11T01-02-03-{rows[0]['payload']['id']}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(json.dumps(row).encode() + b"\n" for row in rows))
    return path


def allow_synthetic_instructions(monkeypatch):
    from forge.core.runtime import codex_review_source

    digest = hashlib.sha256(json.dumps({"text": "fixture"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    monkeypatch.setattr(codex_review_source, "BASE_INSTRUCTIONS", {digest})
