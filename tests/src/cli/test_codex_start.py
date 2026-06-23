"""Unit tests for `forge codex start --proxy` (Phase 4 launcher).

The orchestration is exercised end-to-end through the CLI with the proxy/runtime/invoke
seams patched: `get_runtime` (installed + version), `ensure_proxy` (resolve/start),
`assert_proxy_responses_capable` (capability gate), and `invoke_codex_bare_proxy` (exec).
Errors land on stderr (Rich `Console(stderr=True)`); status lands on stdout. Click 8.4's
default `CliRunner()` exposes `result.stdout`/`result.stderr` separately.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from forge.cli.main import main
from forge.proxy.proxies import (
    AmbiguousProxyError,
    ProxyNotFoundError,
    ProxyRegistryCorruptedError,
)
from forge.proxy.proxy_orchestrator import (
    ProxyIdentityMismatchError,
    ProxyNotResponsesCapableError,
    ProxyStartError,
    ProxyUnreachableError,
)


def _runtime(*, installed: bool = True, version: str | None = "0.141.0") -> MagicMock:
    rt = MagicMock()
    rt.is_installed.return_value = installed
    rt.detect.return_value = version
    return rt


def _entry(
    proxy_id: str = "proxy_abc",
    base_url: str = "http://127.0.0.1:8084",
    template: str = "codex-responses-local",
) -> SimpleNamespace:
    return SimpleNamespace(proxy_id=proxy_id, base_url=base_url, template=template)


def _invoke_start(
    args: list[str],
    *,
    runtime: MagicMock | None = None,
    ensure: Any = None,
    capable: Any = None,
    invoke: Any = None,
) -> tuple[Any, MagicMock, MagicMock, MagicMock]:
    runtime = runtime or _runtime()
    ensure = ensure if ensure is not None else MagicMock(return_value=(_entry(), False))
    capable = capable if capable is not None else MagicMock(return_value=("gpt-5.5", "openai_responses_passthrough"))
    invoke = invoke if invoke is not None else MagicMock(return_value=0)
    with (
        patch("forge.cli.codex.get_runtime", return_value=runtime),
        patch("forge.proxy.proxy_orchestrator.ensure_proxy", ensure),
        patch("forge.proxy.proxy_orchestrator.assert_proxy_responses_capable", capable),
        patch("forge.session.codex_invoke.invoke_codex_bare_proxy", invoke),
    ):
        result = CliRunner().invoke(main, ["codex", "start", *args])
    return result, ensure, capable, invoke


class TestHappyPath:
    def test_wires_args_and_exits_zero(self) -> None:
        result, ensure, capable, invoke = _invoke_start(["--proxy", "codex-responses-local"])
        assert result.exit_code == 0
        ensure.assert_called_once_with("codex-responses-local")
        capable.assert_called_once_with(
            "http://127.0.0.1:8084", expected_proxy_id="proxy_abc", expected_template="codex-responses-local"
        )
        kw = invoke.call_args.kwargs
        assert kw["base_url"] == "http://127.0.0.1:8084"
        assert kw["sandbox"] == "workspace-write"
        assert kw["model"] == "gpt-5.5"
        assert kw["passthrough"] == []

    def test_sandbox_and_passthrough_flow(self) -> None:
        result, _, _, invoke = _invoke_start(["--proxy", "p", "--sandbox", "read-only", "--", "--search"])
        assert result.exit_code == 0
        kw = invoke.call_args.kwargs
        assert kw["sandbox"] == "read-only"
        assert kw["passthrough"] == ["--search"]

    def test_started_proxy_notice_on_stdout(self) -> None:
        ensure = MagicMock(return_value=(_entry(), True))
        result, _, _, _ = _invoke_start(["--proxy", "codex-responses-local"], ensure=ensure)
        assert result.exit_code == 0
        assert "Started proxy" in result.stdout

    def test_no_login_env_still_launches(self) -> None:
        # The launcher never gates on native auth -- a no-login machine still reaches exec.
        result, _, _, invoke = _invoke_start(["--proxy", "p"])
        assert result.exit_code == 0
        invoke.assert_called_once()

    def test_exit_code_passthrough_from_codex(self) -> None:
        result, _, _, _ = _invoke_start(["--proxy", "p"], invoke=MagicMock(return_value=42))
        assert result.exit_code == 42


class TestPreflightGates:
    def test_codex_not_installed_exits_before_ensure(self) -> None:
        ensure = MagicMock()
        result, ensure, _, invoke = _invoke_start(["--proxy", "p"], runtime=_runtime(installed=False), ensure=ensure)
        assert result.exit_code == 1
        ensure.assert_not_called()
        invoke.assert_not_called()
        assert "codex CLI not found" in result.stderr

    def test_old_version_hard_blocks_before_ensure(self) -> None:
        ensure = MagicMock()
        result, ensure, _, invoke = _invoke_start(["--proxy", "p"], runtime=_runtime(version="0.140.0"), ensure=ensure)
        assert result.exit_code == 1
        ensure.assert_not_called()
        invoke.assert_not_called()
        assert "0.141.0" in result.stderr

    def test_unparseable_version_proceeds(self) -> None:
        result, _, _, invoke = _invoke_start(["--proxy", "p"], runtime=_runtime(version=None))
        assert result.exit_code == 0
        invoke.assert_called_once()


class TestProxyErrors:
    def test_proxy_not_found_shows_template_list_tip(self) -> None:
        ensure = MagicMock(side_effect=ProxyNotFoundError("p"))
        result, _, _, invoke = _invoke_start(["--proxy", "p"], ensure=ensure)
        assert result.exit_code == 1
        assert "forge proxy template list" in result.stderr
        invoke.assert_not_called()

    def test_ambiguous_proxy_prints_message(self) -> None:
        ensure = MagicMock(side_effect=AmbiguousProxyError("p", ["proxy_a", "proxy_b"]))
        result, _, _, _ = _invoke_start(["--proxy", "p"], ensure=ensure)
        assert result.exit_code == 1
        assert "proxy_a" in result.stderr

    def test_registry_corrupt_prints_message(self) -> None:
        ensure = MagicMock(side_effect=ProxyRegistryCorruptedError("index.json", "corrupt JSON"))
        result, _, _, _ = _invoke_start(["--proxy", "p"], ensure=ensure)
        assert result.exit_code == 1
        assert "corrupt" in result.stderr

    def test_start_failed_prints_message(self) -> None:
        ensure = MagicMock(side_effect=ProxyStartError("port 8084 in use"))
        result, _, _, _ = _invoke_start(["--proxy", "p"], ensure=ensure)
        assert result.exit_code == 1
        assert "port 8084 in use" in result.stderr


class TestCapabilityGate:
    def test_unreachable_shows_proxy_start_tip(self) -> None:
        capable = MagicMock(side_effect=ProxyUnreachableError("proxy at http://x is unreachable: boom"))
        result, _, _, invoke = _invoke_start(["--proxy", "p"], capable=capable)
        assert result.exit_code == 1
        assert "forge proxy start" in result.stderr
        invoke.assert_not_called()

    def test_not_responses_capable_required_message(self) -> None:
        capable = MagicMock(side_effect=ProxyNotResponsesCapableError("openai_translated"))
        result, _, _, invoke = _invoke_start(["--proxy", "p"], capable=capable)
        assert result.exit_code == 1
        assert "Responses-capable proxy required" in result.stderr
        assert "openai_translated" in result.stderr
        invoke.assert_not_called()

    def test_identity_mismatch_shows_stale_entry_tip(self) -> None:
        # Stale exact-proxy_id entry whose port now serves a different capable proxy.
        capable = MagicMock(
            side_effect=ProxyIdentityMismatchError(
                "http://127.0.0.1:8084",
                expected_proxy_id="proxy_abc",
                actual_proxy_id="proxy_other",
                detail="expected proxy_id 'proxy_abc', got 'proxy_other'",
            )
        )
        result, _, _, invoke = _invoke_start(["--proxy", "proxy_abc"], capable=capable)
        assert result.exit_code == 1
        assert "stale" in result.stderr.lower()
        assert "forge proxy start" in result.stderr
        invoke.assert_not_called()


class TestUsage:
    def test_proxy_is_required(self) -> None:
        result = CliRunner().invoke(main, ["codex", "start"])
        assert result.exit_code != 0
        assert "proxy" in (result.stderr + result.output).lower()
