"""Tests proving routing invariants (B2.1).

These integration tests validate that:
- Proxy `GET /` returns **runtime truth** only (proxy identity + routing defaults + tier mappings).
- Session state is **not** returned by the proxy (session is local-only).
- Routing precedence is:
  1. Request explicit tier (haiku/sonnet/opus in model name)
  2. Proxy-owned default tier (config.proxy.default_tier)

Session config/overrides are owned by Forge Session + hooks and must be read locally.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]


class TestSessionConfigRouting:
    """Prove routing behavior does not depend on session state."""

    def test_proxy_runtime_truth_has_no_session_key(self, proxy_server: str, temp_session: dict[str, Any]) -> None:
        """GET / must not return session state (session is local-only)."""
        with httpx.Client() as client:
            resp = client.get(f"{proxy_server}/")
            data = resp.json()

            assert "session" not in data
            assert data["is_proxy"] is True
            assert "proxy" in data
            assert "routing" in data
            assert "runtime" in data

    def test_routing_note_mentions_session_non_authoritative(self, proxy_server: str) -> None:
        """Routing section should explicitly document session non-authoritative rule."""
        with httpx.Client() as client:
            resp = client.get(f"{proxy_server}/")
            data = resp.json()

            note = data["routing"]["note"]
            assert "proxy-owned" in note
            assert "Session state" in note
            assert "not" in note

    def test_ambiguous_model_uses_lease_default_tier(self, proxy_server: str, temp_session: dict[str, Any]) -> None:
        """Ambiguous model should use proxy-owned default tier (not session tier).

        Session may be active, but it must be non-authoritative for routing.
        """
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{proxy_server}/v1/messages",
                json={
                    "model": "claude-3",  # No tier substring → ambiguous
                    "max_tokens": 10,
                    "messages": [{"role": "user", "content": "test"}],
                },
                headers={"x-api-key": "test"},
            )
            assert resp.status_code == 200
            # X-Resolved-Tier should match proxy default (proxy.default_tier)
            assert resp.headers.get("X-Resolved-Tier") == "sonnet"
            assert resp.headers.get("X-Resolved-Model") == "gemini/gemini-3.1-pro-preview"

    def test_explicit_request_tier_overrides_lease_default(
        self, proxy_server: str, temp_session: dict[str, Any]
    ) -> None:
        """Explicit request tier (haiku) should override proxy default tier.

        Session may be active, but it is non-authoritative for routing.
        Request tier should win, and the backend model should match haiku's config.
        """
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{proxy_server}/v1/messages",
                json={
                    "model": "claude-3-5-haiku-20241022",  # Explicit haiku
                    "max_tokens": 10,
                    "messages": [{"role": "user", "content": "test"}],
                },
                headers={"x-api-key": "test"},
            )
            assert resp.status_code == 200
            # X-Resolved-Tier header confirms haiku was used (not opus from session)
            assert resp.headers.get("X-Resolved-Tier") == "haiku"
            # X-Resolved-Model confirms haiku's backend model was used
            # (litellm-gemini-test family: haiku → gemini/gemini-3-flash-preview)
            assert resp.headers.get("X-Resolved-Model") == "gemini/gemini-3-flash-preview"

    def test_no_session_uses_family_default(self, proxy_server: str, no_active_session: None) -> None:
        """With no active session and ambiguous model, use template default.

        No session active, ambiguous model → template default tier (sonnet for litellm-gemini-test).
        The backend model should match sonnet's configured model.
        """
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{proxy_server}/v1/messages",
                json={
                    "model": "claude-3",  # No tier substring
                    "max_tokens": 10,
                    "messages": [{"role": "user", "content": "test"}],
                },
                headers={"x-api-key": "test"},
            )
            assert resp.status_code == 200
            # X-Resolved-Tier header confirms template default (sonnet) was used
            assert resp.headers.get("X-Resolved-Tier") == "sonnet"
            # X-Resolved-Model confirms sonnet's backend model was used
            # (litellm-gemini-test family: sonnet → gemini/gemini-3.1-pro-preview)
            assert resp.headers.get("X-Resolved-Model") == "gemini/gemini-3.1-pro-preview"
