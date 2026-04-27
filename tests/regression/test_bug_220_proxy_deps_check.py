"""Regression test for proxy dependency checking.

Bug ID: 220
Date: 2026-02-03
Phase: 11 (Search Infrastructure)

Description:
    When proxy dependencies (uvicorn, fastapi, litellm) are not installed,
    proxy creation fails with a confusing ModuleNotFoundError during subprocess
    spawn. The error should be caught early with a helpful message.

Root cause:
    - Proxy dependencies were optional (pyproject.toml [proxy] extra)
    - setup.sh didn't install them
    - No early validation before spawning subprocess

Fix:
    - Added _check_proxy_dependencies() validation before spawn
    - Proxy dependencies moved to core deps (no longer optional)
    - Added helpful error message with install instructions
"""

import builtins

import pytest

from forge.proxy.proxy_orchestrator import ProxyStartError

pytestmark = pytest.mark.regression


def test_missing_proxy_dependencies_raise_helpful_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that missing proxy dependencies raise helpful error before spawn."""
    import forge.proxy.proxy_orchestrator as orchestrator

    # Mock import to simulate missing uvicorn
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "uvicorn":
            raise ImportError(f"No module named '{name}'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    # Should raise ProxyStartError with helpful message
    with pytest.raises(ProxyStartError) as exc_info:
        orchestrator._check_proxy_dependencies()

    error_msg = str(exc_info.value)

    # Error should mention the missing dependency
    assert "uvicorn" in error_msg

    # Error should provide installation instructions
    assert "uv sync" in error_msg or "proxy dependencies" in error_msg.lower()

    # Error should mention --no-start workaround
    assert "--no-start" in error_msg
