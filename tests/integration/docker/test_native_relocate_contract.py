"""Native-relocate contract test (Phase 3 spike) -- THE DECISION GATE.

Does copying a Claude session JSONL into a different CWD's encoded project dir
make it resumable across that boundary, and does the tool-use continuation
survive signed-thinking revalidation?

Real Claude Code in Docker. Narrow assertions: exit codes + marker/JSONL
structure, never LLM prose. Three failure modes are separated so the verdict is
trustworthy: discovery failure (Claude could not find the relocated JSONL) vs
signature/content rejection (found but the continuation was refused) vs success.
A bare non-zero exit with no recognizable marker is UNCATEGORIZED -- never
silently treated as a signature failure.

The 2026-04-02 negative result (Claude Code 2.1.90, cross-CWD resume fails "No
conversation found"; docs/design.md 3.9) is the prior art this test revisits:
that test never relocated the JSONL. Host Claude is now far newer, so both the
relocation hypothesis and the version bump are reasons to re-measure.

Run:
    ./scripts/test-integration.sh tests/integration/docker/test_native_relocate_contract.py -v
"""

from __future__ import annotations

import os

import pytest

from tests.fixtures.docker import ContainerLike
from tests.integration.docker.conftest import relocate_and_resume

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_in,
    pytest.mark.slow,
]

_MIN_VERSION = (2, 1, 90)
# Tightened to the exact Claude discovery error; a bare "not found" could mislabel an
# unrelated failure (which otherwise falls through to UNCATEGORIZED and fails loudly).
_DISCOVERY_MARKERS = ("no conversation found",)
_SIGNATURE_MARKERS = ("signature", "thinking", "unmodified", "invalid_request_error")

# The child worktree path carries an UNDERSCORE on purpose: it forces real Claude to
# exercise the encode_project_path() `_`->`-` branch end-to-end, so an encoder
# regression surfaces here as DISCOVERY-FAIL instead of silently passing on a clean
# `/workspace`-style path.
_CHILD_ROOT = "/tmp/relocate_child_wt"
_CHILD_FIXTURE = f"{_CHILD_ROOT}/RELOCATE_FIXTURE_CHILD.txt"

PARENT_PROMPT = (
    "Think step by step about which tool reads a file, then use the Read tool to "
    "read /workspace/RELOCATE_FIXTURE.txt and reply with exactly ACKNOWLEDGED."
)
CHILD_PROMPT = f"Use the Read tool to read {_CHILD_FIXTURE} and reply with exactly CONTINUED."


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
    """Fail loudly (never skip) on missing key or host Claude < 2.1.90."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.fail("ANTHROPIC_API_KEY not set. Add it to your environment/.env and re-run integration tests.")

    from forge.install.version import get_claude_runtime_version

    host = get_claude_runtime_version()
    if host is None:
        pytest.fail("Claude Code not found on host; cannot run the native-relocate contract test.")
    if _version_tuple(host) < _MIN_VERSION:
        pytest.fail(f"Native-relocate contract test requires Claude Code >= 2.1.90 (host has {host}).")


class TestNativeRelocateContract:
    """The cross-CWD relocation gate (real Claude, signed-thinking continuation)."""

    def test_relocated_session_resumes_across_cwd(self, forge_workspace: ContainerLike) -> None:
        signals = relocate_and_resume(
            forge_workspace,
            parent_prompt=PARENT_PROMPT,
            child_prompt=CHILD_PROMPT,
            child_root=_CHILD_ROOT,
        )

        # The container's Claude executes the resume -- it governs the result.
        container_version = str(signals["container_claude_version"])
        assert (
            _version_tuple(container_version) >= _MIN_VERSION
        ), f"Container Claude {container_version!r} < 2.1.90; result is not valid for this gate."

        # Precondition: a SIGNED thinking block must have been exercised, else the
        # run is INCONCLUSIVE (not a negative) -- do not record an outcome.
        if not signals["parent_has_signature"]:
            pytest.fail(
                "INCONCLUSIVE: parent transcript carried no signed thinking block, so signature "
                "validation was never exercised. Adjust model / MAX_THINKING_TOKENS / prompt. "
                f"(container Claude {container_version})"
            )

        verdict = _classify(signals)
        tail = (
            "\n---- child stdout (tail) ----\n"
            + str(signals["child_stdout"])[-1500:]
            + "\n---- child stderr (tail) ----\n"
            + str(signals["child_stderr"])[-1500:]
        )

        if verdict == "discovery_fail":
            pytest.fail(
                "DISCOVERY-FAIL: relocating the JSONL did not make the session discoverable on "
                f"Claude {container_version}; native-relocate is not viable.{tail}"
            )
        if verdict == "signature_fail":
            pytest.fail(
                "SIGNATURE-FAIL: relocated session was found but the continuation was rejected "
                f"(likely signed-thinking revalidation) on Claude {container_version}.{tail}"
            )
        if verdict == "uncategorized":
            pytest.fail(
                f"UNCATEGORIZED child failure (exit={signals['child_exit']}, Claude {container_version}); "
                f"not assumed to be a signature failure -- inspect the output.{tail}"
            )

        # verdict == success: judge from Claude's project dir, not the manifest.
        assert signals[
            "new_fork_jsonls"
        ], "child exited 0 but no new fork transcript appeared in the child's encoded dir"
        tool_use_count = signals["fork_tool_use_count"]
        assert isinstance(tool_use_count, int) and tool_use_count >= 2, (
            "forked transcript should carry >= 2 tool_use blocks (parent Read + child Read); "
            f"found {tool_use_count!r}"
        )
        # --fork-session must not mutate the relocated parent copy.
        assert (
            signals["reloc_sha_before"] == signals["reloc_sha_after"]
        ), "relocated parent JSONL changed during resume (--fork-session mutated history)"
