"""Pytest configuration for core.llm tests."""

from dotenv import load_dotenv

# Import _repo_root from root conftest for consistent .env loading
from tests.conftest import _repo_root

# Ensure .env is loaded (idempotent with root conftest)
# See tests/conftest.py for details
load_dotenv(_repo_root / ".env", override=False)

# ruff: noqa: E402 — Imports below MUST come after load_dotenv() to ensure env vars are available
import pytest

# Mark all tests in this directory as asyncio
pytestmark = pytest.mark.asyncio
