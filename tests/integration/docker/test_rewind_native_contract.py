"""Rewind clean-prefix contract test.

This extends the native-relocate real-Claude gate to the rewind-specific shape:
the child resumes from a fresh UUID whose JSONL is a truncated clean prefix of
the parent transcript, while the embedded transcript session id remains the
parent's. Unit tests cover the prefix writer; this test verifies Claude Code can
actually discover and continue that truncated fresh-stem transcript.

Run:
    ./scripts/test-integration.sh tests/integration/docker/test_rewind_native_contract.py -v
"""

from __future__ import annotations

import os

import pytest

from tests.fixtures.docker import ContainerLike
from tests.integration.docker.conftest import rewind_prefix_and_resume

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_in,
    pytest.mark.slow,
]

_MIN_VERSION = (2, 1, 197)
_DISCOVERY_MARKERS = ("no conversation found",)
_SIGNATURE_MARKERS = ("signature", "thinking", "unmodified", "invalid_request_error")

_CHILD_ROOT = "/tmp/rewind_child_wt"
_HEAD_FIXTURE = "/workspace/REWIND_FIXTURE_HEAD.txt"
_TAIL_FIXTURE = "/workspace/REWIND_FIXTURE_TAIL.txt"
_CHILD_FIXTURE = f"{_CHILD_ROOT}/REWIND_FIXTURE_CHILD.txt"

PARENT_HEAD_PROMPT = (
    "Think step by step about which tool reads a file, then use the Read tool to "
    f"read {_HEAD_FIXTURE} and reply with exactly REWIND_HEAD_ACK."
)
PARENT_TAIL_PROMPT = f"Use the Read tool to read {_TAIL_FIXTURE} and reply with exactly REWIND_TAIL_ACK."
CHILD_PROMPT = f"Use the Read tool to read {_CHILD_FIXTURE} and reply with exactly REWIND_CONTINUED."


def _version_tuple(raw: str) -> tuple[int, ...]:
    """Parse a `claude --version` string ('X.Y.Z (Claude Code)') to a tuple."""
    head = raw.strip().split()[0] if raw.strip() else ""
    parts: list[int] = []
    for token in head.split(".")[:3]:
        try:
            parts.append(int(token))
        except ValueError:
            break
    return tuple(parts)


def _classify(signals: dict[str, object]) -> str:
    """Map raw child-resume signals to success / discovery / signature / uncategorized."""
    if signals["child_exit"] == 0:
        return "success"
    out = (str(signals["child_stdout"]) + "\n" + str(signals["child_stderr"])).lower()
    if any(marker in out for marker in _DISCOVERY_MARKERS):
        return "discovery_fail"
    if any(marker in out for marker in _SIGNATURE_MARKERS):
        return "signature_fail"
    return "uncategorized"


@pytest.fixture(scope="module", autouse=True)
def _require_api_key_and_host_version() -> None:
    """Fail loudly (never skip) on missing key or host Claude < 2.1.197."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.fail("ANTHROPIC_API_KEY not set. Add it to your environment/.env and re-run integration tests.")

    from forge.install.version import get_claude_runtime_version

    host = get_claude_runtime_version()
    if host is None:
        pytest.fail("Claude Code not found on host; cannot run the rewind clean-prefix contract test.")
    if _version_tuple(host) < _MIN_VERSION:
        pytest.fail(f"Rewind clean-prefix contract test requires Claude Code >= 2.1.197 (host has {host}).")


class TestRewindNativeContract:
    """The fresh-UUID truncated-prefix resume gate (real Claude)."""

    def test_truncated_fresh_uuid_prefix_resumes_across_cwd(self, forge_workspace: ContainerLike) -> None:
        signals = rewind_prefix_and_resume(
            forge_workspace,
            parent_head_prompt=PARENT_HEAD_PROMPT,
            parent_tail_prompt=PARENT_TAIL_PROMPT,
            child_prompt=CHILD_PROMPT,
            child_root=_CHILD_ROOT,
        )

        container_version = str(signals["container_claude_version"])
        assert (
            _version_tuple(container_version) >= _MIN_VERSION
        ), f"Container Claude {container_version!r} < 2.1.197; result is not valid for this gate."

        prefix = signals["prefix"]
        assert isinstance(prefix, dict)
        assert prefix["total_turns"] >= 2
        assert prefix["kept_turns"] >= 1
        assert prefix["actual_dropped_turns"] >= 2
        assert prefix["contains_head_fixture"] is True
        assert signals["parent_uuid"] != signals["rewind_uuid"]

        verdict = _classify(signals)
        tail = (
            "\n---- child stdout (tail) ----\n"
            + str(signals["child_stdout"])[-1500:]
            + "\n---- child stderr (tail) ----\n"
            + str(signals["child_stderr"])[-1500:]
        )

        if verdict == "discovery_fail":
            pytest.fail(
                "DISCOVERY-FAIL: Claude did not discover the truncated fresh-UUID rewind prefix "
                f"on Claude {container_version}.{tail}"
            )
        if verdict == "signature_fail":
            pytest.fail(
                "SIGNATURE-FAIL: truncated rewind prefix was found but continuation was rejected "
                f"(likely signed-thinking revalidation) on Claude {container_version}.{tail}"
            )
        if verdict == "uncategorized":
            pytest.fail(
                f"UNCATEGORIZED child failure (exit={signals['child_exit']}, Claude {container_version}); "
                f"not assumed to be a signature failure -- inspect the output.{tail}"
            )

        assert signals["new_fork_jsonls"], "child exited 0 but no new fork transcript appeared in the child's encoded dir"
        tool_use_count = signals["fork_tool_use_count"]
        assert isinstance(tool_use_count, int) and tool_use_count >= 2, (
            "forked transcript should carry >= 2 tool_use blocks (kept parent Read + child Read); "
            f"found {tool_use_count!r}"
        )
        assert (
            signals["rewind_sha_before"] == signals["rewind_sha_after"]
        ), "rewind prefix JSONL changed during resume (--fork-session mutated history)"
