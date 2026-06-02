"""Unit tests for the override-mode mutation pipeline (Phase 2 audit proxy, MUTATE)."""

from __future__ import annotations

import pytest

from forge.proxy import intercept


class TestFingerprint:
    def test_stable_and_sensitive(self):
        msgs = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
        fp = intercept.messages_fingerprint(msgs)
        assert fp == intercept.messages_fingerprint(msgs)  # stable
        changed = [{"role": "user", "content": [{"type": "text", "text": "bye"}]}]
        assert fp != intercept.messages_fingerprint(changed)


class TestAugmentCacheAware:
    def test_inserts_after_last_cache_marker(self):
        system = [
            {"type": "text", "text": "A", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "B"},
        ]
        new, invalidation = intercept.insert_augment_cache_aware(system, "AUG")
        assert [b["text"] for b in new] == ["A", "AUG", "B"]  # right after the marker
        assert invalidation is False  # cached prefix preserved

    def test_markerless_appends_and_flags_invalidation(self):
        new, invalidation = intercept.insert_augment_cache_aware("plain system", "AUG")
        assert [b["text"] for b in new] == ["plain system", "AUG"]
        assert invalidation is True  # no post-cache anchor

    def test_empty_augment_is_noop(self):
        system = [{"type": "text", "text": "A"}]
        new, invalidation = intercept.insert_augment_cache_aware(system, "")
        assert new is system and invalidation is False  # byte-identical, untouched


class TestGuards:
    def test_block_short_circuits(self):
        system = [{"type": "text", "text": "contains FORBIDDEN token"}]
        _, outcome = intercept.apply_guards(system, [{"pattern": "FORBIDDEN", "action": "block"}])
        assert outcome.blocked and outcome.blocked_pattern == "FORBIDDEN"

    def test_strip_removes_matches_per_block(self):
        system = [{"type": "text", "text": "a BAD b BAD c"}]
        new, outcome = intercept.apply_guards(system, [{"pattern": "BAD", "action": "strip"}])
        assert outcome.stripped_count == 2
        assert new[0]["text"] == "a  b  c"

    def test_warn_records_without_mutation(self):
        system = [{"type": "text", "text": "noisy WARNME prompt"}]
        new, outcome = intercept.apply_guards(system, [{"pattern": "WARNME", "action": "warn"}])
        assert outcome.warned_patterns == ["WARNME"]
        assert new is system  # warn does not mutate

    def test_invalid_regex_skipped(self):
        system = [{"type": "text", "text": "text"}]
        _, outcome = intercept.apply_guards(system, [{"pattern": "[unclosed", "action": "block"}])
        assert outcome.blocked is False  # bad regex skipped, not a crash


class TestReasoningPin:
    def test_floor_consistent_with_server_thresholds(self):
        """Each effort floor must round-trip back to the same effort via the server's mapping."""
        from forge.proxy import server

        for effort in ("minimal", "low", "medium", "high", "xhigh"):
            floor = intercept.effort_to_budget_floor(effort)
            assert server._derive_reasoning_effort({"budget_tokens": floor}) == effort

    def test_raises_low_budget_to_floor(self):
        thinking, changed, before, after = intercept.pin_reasoning(
            {"type": "enabled", "budget_tokens": 100}, "high", 64000
        )
        assert changed and before == 100 and after == 10000
        assert thinking == {"type": "enabled", "budget_tokens": 10000}

    def test_noop_when_already_above_floor(self):
        thinking, changed, before, after = intercept.pin_reasoning(
            {"type": "enabled", "budget_tokens": 20000}, "high", 64000
        )
        assert changed is False and before == after == 20000

    def test_clamps_under_max_tokens(self):
        _, changed, _, after = intercept.pin_reasoning({"budget_tokens": 1}, "high", 8000)
        assert changed and after == 7999  # 10000 floor clamped to max_tokens-1

    def test_skips_when_max_tokens_too_small(self):
        thinking, changed, _, _ = intercept.pin_reasoning(None, "high", 512)
        assert changed is False and thinking is None  # can't host any thinking budget

    def test_enables_thinking_when_absent(self):
        thinking, changed, before, after = intercept.pin_reasoning(None, "medium", 64000)
        assert changed and before is None and thinking["budget_tokens"] == 2000

    def test_no_floor_is_noop(self):
        thinking, changed, _, _ = intercept.pin_reasoning({"budget_tokens": 5}, None, 64000)
        assert changed is False and thinking == {"budget_tokens": 5}

    def test_preserves_unknown_thinking_siblings(self):
        """Forward-safety: unknown keys on the inbound thinking dict survive the pin."""
        thinking, changed, _, after = intercept.pin_reasoning(
            {"type": "enabled", "budget_tokens": 1, "future_key": "keep"}, "high", 64000
        )
        assert changed and after == 10000
        assert thinking["future_key"] == "keep" and thinking["budget_tokens"] == 10000


class TestApplyOverride:
    def _body(self, **over):
        base = {
            "model": "claude-opus-4-6",
            "max_tokens": 64000,
            "system": [{"type": "text", "text": "base system"}],
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
        }
        base.update(over)
        return base

    def test_augment_and_pin_together(self):
        body = self._body()
        result = intercept.apply_override(body, system_prompt_augment="EXTRA", reasoning_floor_effort="high")
        assert not result.blocked
        assert body["system"][-1]["text"] == "EXTRA"  # augment applied
        assert body["thinking"]["budget_tokens"] == 10000  # pin applied
        actions = {m["action"] for m in result.mutation_record["mutations"]}
        assert actions == {"augment", "reasoning_pin"}
        assert result.mutation_record["system_prompt_hash_before"] != result.mutation_record["system_prompt_hash_after"]

    def test_block_leaves_body_unmutated(self):
        body = self._body()
        original_system = body["system"]
        result = intercept.apply_override(
            body, system_prompt_guards=[{"pattern": "base", "action": "block"}], system_prompt_augment="EXTRA"
        )
        assert result.blocked and "blocked" in (result.blocked_reason or "")
        assert body["system"] is original_system  # not mutated when blocked
        assert "thinking" not in body

    def test_noop_when_no_directives(self):
        body = self._body()
        result = intercept.apply_override(body)
        assert result.mutation_record is None and not result.blocked

    def test_strip_then_block_does_not_mutate(self):
        """A strip guard listed before a block guard must not half-strip a blocked body."""
        body = self._body(system=[{"type": "text", "text": "drop SECRET keep FORBIDDEN"}])
        result = intercept.apply_override(
            body,
            system_prompt_guards=[
                {"pattern": "SECRET", "action": "strip"},
                {"pattern": "FORBIDDEN", "action": "block"},
            ],
        )
        assert result.blocked
        assert body["system"][0]["text"] == "drop SECRET keep FORBIDDEN"  # untouched: blocks evaluated first

    def test_mutation_record_carries_no_plaintext(self):
        body = self._body(system=[{"type": "text", "text": "SECRET-SYS"}])
        result = intercept.apply_override(
            body, system_prompt_augment="SECRET-AUG", system_prompt_guards=[{"pattern": "SECRET-SYS", "action": "warn"}]
        )
        import json

        blob = json.dumps(result.mutation_record)
        assert "SECRET-AUG" not in blob and "SECRET-SYS" not in blob  # only hashes/lengths

    def test_historical_messages_preserved(self):
        """Override never rewrites messages — esp. signed thinking blocks."""
        history = [
            {"role": "user", "content": [{"type": "text", "text": "q"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "secret reasoning", "signature": "SIG123"},
                    {"type": "redacted_thinking", "data": "OPAQUE"},
                    {"type": "text", "text": "a"},
                ],
            },
            {"role": "user", "content": [{"type": "text", "text": "followup"}]},
        ]
        body = self._body(messages=history)
        import copy

        before = copy.deepcopy(history)
        intercept.apply_override(body, system_prompt_augment="EXTRA", reasoning_floor_effort="high")
        assert body["messages"] == before  # byte-identical, signature intact


def test_apply_override_raises_on_message_mutation(monkeypatch):
    """If apply ever altered messages, the fingerprint tripwire must raise."""
    body = {
        "model": "m",
        "max_tokens": 64000,
        "system": "s",
        "messages": [{"role": "user", "content": "hi"}],
    }
    # Force a message mutation between the before/after fingerprints.
    calls = {"n": 0}
    real_fp = intercept.messages_fingerprint

    def _fp(messages):
        calls["n"] += 1
        if calls["n"] == 2:
            return "sha256:tampered"
        return real_fp(messages)

    monkeypatch.setattr(intercept, "messages_fingerprint", _fp)
    with pytest.raises(RuntimeError, match="mutation-safety invariant"):
        intercept.apply_override(body, system_prompt_augment="X")
