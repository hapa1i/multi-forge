"""Tests for the run-id format leaf module (mint + validate).

The proxy validates inbound ``X-Forge-Run-ID``/``X-Forge-Root-Run-ID`` headers with
``is_valid_run_id`` before logging them (Slice 4g), so the format guard must reject
malformed, spoofed, and header-injection values -- not just accept well-formed ones.
"""

from __future__ import annotations

import pytest

from forge.core.run_id import (
    RUN_ID_RE,
    derive_provider_session_id,
    is_valid_label,
    is_valid_provider_session_id,
    is_valid_run_id,
    mint_run_id,
    sanitize_label,
)


def test_mint_is_valid_and_shaped() -> None:
    rid = mint_run_id()
    assert rid.startswith("run_")
    assert len(rid) == len("run_") + 12
    assert is_valid_run_id(rid)
    assert RUN_ID_RE.match(rid)


def test_mint_is_unique() -> None:
    assert mint_run_id() != mint_run_id()


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "run_",  # no hex
        "run_short",  # not 12 hex
        "run_7e81a1bb765",  # 11 hex
        "run_7e81a1bb765d0",  # 13 hex
        "run_7E81A1BB765D",  # uppercase (mint is lowercase)
        "req_7e81a1bb765d",  # wrong prefix (proxy request id, not a run id)
        "run_7e81a1bb765g",  # non-hex char
        " run_7e81a1bb765d",  # leading space
        "run_7e81a1bb765d ",  # trailing space
        "run_7e81a1bb765d\nX-Evil: injected",  # header injection
        "x: y\nX-Forge-Run-ID: run_7e81a1bb765d",  # spoof attempt
    ],
)
def test_rejects_malformed_and_injection(value: str | None) -> None:
    assert not is_valid_run_id(value)


# --- Provider session/command labels ---


@pytest.mark.parametrize(
    "raw",
    ["memory_writer", "memory-writer", "memory writer", "Memory  Writer", " memory.writer "],
)
def test_sanitize_label_canonicalizes_separators(raw: str) -> None:
    # One role string must normalize one way regardless of separator/casing, so the
    # id suffix and the X-Forge-Command header can never drift apart.
    assert sanitize_label(raw) == "memory_writer"


@pytest.mark.parametrize("value", [None, "", "   ", "!!!", "---", "\n", ":"])
def test_sanitize_label_empty_or_pure_separator_is_none(value: str | None) -> None:
    assert sanitize_label(value) is None


def test_sanitize_label_strips_injection_to_single_token() -> None:
    out = sanitize_label("supervisor\nX-Evil: injected")
    assert out is not None
    assert "\n" not in out and ":" not in out and " " not in out
    assert is_valid_label(out)  # the normalized result is itself a clean label


def test_sanitize_label_caps_length() -> None:
    out = sanitize_label("a" * 200)
    assert out is not None
    assert len(out) <= 64


@pytest.mark.parametrize("value", ["supervisor", "memory_writer", "review", "a", "x9_y"])
def test_is_valid_label_accepts_clean(value: str) -> None:
    assert is_valid_label(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "Supervisor",  # uppercase (stamped values are lowercased)
        "memory writer",  # space
        "memory-writer",  # hyphen (canonical form uses underscore)
        "a" * 65,  # over the length cap
        "role\nX-Evil: y",  # header injection
        "x: y",  # colon
    ],
)
def test_is_valid_label_rejects_spoofed(value: str | None) -> None:
    assert not is_valid_label(value)


def test_derive_with_label_is_opaque_and_shaped() -> None:
    sess = derive_provider_session_id("My Feature/Branch", "run_7e81a1bb765d", role="supervisor")
    assert sess.startswith("forge_sess_")
    assert sess.endswith("_supervisor")
    assert "/" not in sess
    # The raw human name (and its slug) never appears — only a hash does.
    assert "feature" not in sess.lower()
    assert "branch" not in sess.lower()
    assert is_valid_provider_session_id(sess)


def test_derive_without_label_falls_back_to_run_id() -> None:
    root = "run_7e81a1bb765d"
    sess = derive_provider_session_id(None, root, role="review")
    assert sess.startswith("forge_run_")
    assert sess.endswith("_review")
    assert root not in sess  # the run id is hashed too, not embedded raw
    assert is_valid_provider_session_id(sess)


def test_derive_blank_label_uses_fallback() -> None:
    # A whitespace-only FORGE_SESSION must not produce forge_sess_<hash("")>.
    assert derive_provider_session_id("   ", "run_7e81a1bb765d").startswith("forge_run_")


def test_derive_is_deterministic_for_grouping() -> None:
    a = derive_provider_session_id("session-alpha", "run_aaaaaaaaaaaa", role="supervisor")
    b = derive_provider_session_id("session-alpha", "run_bbbbbbbbbbbb", role="supervisor")
    # Same session label + role => same grouping id, independent of the run tree.
    assert a == b


def test_derive_role_is_sanitized_in_suffix() -> None:
    # The role rides through the same sanitizer as the X-Forge-Command header.
    sess = derive_provider_session_id("s", "run_7e81a1bb765d", role="memory writer")
    assert sess.endswith("_memory_writer")


def test_derive_without_role_has_no_suffix() -> None:
    sess = derive_provider_session_id("s", "run_7e81a1bb765d")
    assert is_valid_provider_session_id(sess)
    assert sess.count("_") == 2  # forge _ sess _ <hash>, no trailing role


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "forge_sess_",  # no hash
        "forge_sess_SHORT",  # not 12 hex
        "forge_sess_7e81a1bb765",  # 11 hex
        "forge_sess_7E81A1BB765D",  # uppercase hex
        "run_7e81a1bb765d",  # a run id, not a provider session id
        "forge_xxx_7e81a1bb765d",  # wrong discriminator
        "forge_sess_7e81a1bb765d\nX-Evil: y",  # header injection
        "forge_sess_7e81a1bb765d_" + "a" * 65,  # role over cap
    ],
)
def test_is_valid_provider_session_id_rejects_spoofed(value: str | None) -> None:
    assert not is_valid_provider_session_id(value)
