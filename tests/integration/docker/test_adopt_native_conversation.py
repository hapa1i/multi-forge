"""End-to-end adoption of a conversation Forge never launched (real Claude).

The Slice 0 gate (``test_adopt_binding_contract.py``) proved the *identity*
premise adoption rests on: a plain ``--resume`` reports the original session id.
This gate proves the flow that premise was for -- discover, bind, continue --
against files Forge did not write.

Everything adoption depends on here is real and unmockable at the unit layer: the
lossy launch-directory encoding Claude files transcripts under, the transcript
shape ``summarize_transcript`` parses, and ``_has_resumable_transcript``'s
``get_transcript_path(...).is_file()`` check against a JSONL no Forge code
produced. Unit tests write their own fixtures, so they can only prove Forge
agrees with itself.

The conversation is created with ``FORGE_SESSION`` unset, so no hook fires and no
manifest exists when ``forge session adopt`` first sees it -- the actual "I ran
bare ``claude`` and now it matters" case.

Run:
    ./scripts/test-integration.sh tests/integration/docker/test_adopt_native_conversation.py -v
"""

from __future__ import annotations

import json
import os
import shlex
from typing import Any

import pytest

from forge.core.ops.session_adopt import SOURCE_RUNTIME_CLAUDE
from tests.fixtures.docker import ContainerLike
from tests.integration.docker.conftest import run_claude_print, setup_real_claude

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_in,
    pytest.mark.slow,
]

# A Forge session that exists before the native conversation does. It is never
# launched, so it has a pre-seeded UUID but no transcript -- which makes it a
# control for the preview (it must not appear) rather than scenery.
_DECOY = "pre-existing-forge-session"
_ADOPTED = "adopted-native"

NATIVE_PROMPT = "Remember this number: 8317. Reply with just the word noted"
CONTINUE_PROMPT = "What number did I ask you to remember? Reply with just the digits"
_NUMBER = "8317"

_CONTAINER_PY = "/forge/.venv/bin/python"
_RESUMABLE_PROBE = """\
import json
import sys

from forge.cli.session_lifecycle import _is_resumable_session
from forge.session import SessionStore

state = SessionStore(sys.argv[1], sys.argv[2]).read()
print(json.dumps({
    "resumable": _is_resumable_session(state),
    "claude_session_id": state.confirmed.claude_session_id,
}))
"""


@pytest.fixture(scope="module", autouse=True)
def _require_anthropic_api_key() -> None:
    """Fail loudly if the API key is missing (never-skip policy)."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.fail("ANTHROPIC_API_KEY not set. Add it to your environment/.env and re-run integration tests.")


def _adopt_preview(workspace: ContainerLike) -> dict[str, Any]:
    result = workspace.exec("cd /workspace && forge session adopt --json")
    if result.returncode != 0:
        pytest.fail(f"`forge session adopt --json` failed (rc={result.returncode}): {result.stderr[:400]!r}")
    try:
        payload: dict[str, Any] = json.loads(result.stdout)
    except ValueError:
        pytest.fail(f"preview did not emit JSON: {result.stdout[:400]!r}")
    return payload


def _read_manifest(workspace: ContainerLike, name: str) -> dict[str, Any]:
    path = f"/workspace/.forge/sessions/{name}/forge.session.json"
    result = workspace.exec(f"cat {path}")
    if result.returncode != 0:
        pytest.fail(f"Could not read manifest {path}: {result.stderr[:200]!r}")
    payload: dict[str, Any] = json.loads(result.stdout)
    return payload


class TestAdoptNativeConversation:
    def test_a_bare_claude_conversation_is_discovered_bound_and_continued(self, forge_workspace: ContainerLike) -> None:
        setup_real_claude(forge_workspace, session_name=_DECOY)

        # 1. A conversation Forge has nothing to do with: no FORGE_SESSION, so the
        #    installed hooks have no session to resolve and write nothing.
        native_exit, native_stdout, native_stderr = run_claude_print(
            forge_workspace,
            prompt=NATIVE_PROMPT,
            session_name=None,
            timeout=90,
        )
        native_tail = (
            f"\n---- native stdout (tail) ----\n{native_stdout[-1000:]}"
            f"\n---- native stderr (tail) ----\n{native_stderr[-1000:]}"
        )
        assert native_exit == 0, f"the bare `claude --print` turn failed (exit={native_exit}).{native_tail}"

        # 2. Discovery: the preview is how a user finds an id they never recorded.
        preview = _adopt_preview(forge_workspace)
        candidates = preview.get("candidates", [])
        assert len(candidates) == 1, (
            f"expected exactly one adoptable conversation in /workspace, got {len(candidates)}: "
            f"{[c.get('conversation_id') for c in candidates]}. The decoy session '{_DECOY}' was never "
            f"launched, so it has no transcript and must not appear.{native_tail}"
        )
        candidate = candidates[0]
        native_uuid = candidate["conversation_id"]
        assert candidate["user_turns"] >= 1, f"the real transcript parsed as {candidate['user_turns']} user turns"
        assert NATIVE_PROMPT[:20] in candidate["preview"], (
            f"preview text {candidate['preview']!r} does not come from the prompt actually sent -- "
            f"summarize_transcript is not reading real Claude output correctly"
        )

        # 3a. The double-attach guard, against the case it was written for: a real
        #     conversation that ended seconds ago. With no stdin the confirm aborts.
        unconfirmed = forge_workspace.exec(
            f"cd /workspace && forge session adopt {shlex.quote(native_uuid)} --name {_ADOPTED} < /dev/null"
        )
        assert unconfirmed.returncode != 0, (
            "a conversation that was active seconds ago was adopted without confirmation; "
            "the 30-minute double-attach guard did not fire"
        )
        assert not forge_workspace.file_exists(
            f"/workspace/.forge/sessions/{_ADOPTED}"
        ), "the declined adopt left session state behind"

        # 3b. Bind it. --yes is the documented way past 3a, and the only way here:
        #     the transcript is minutes old by construction.
        adopt = forge_workspace.exec(
            f"cd /workspace && forge session adopt {shlex.quote(native_uuid)} --name {_ADOPTED} --yes"
        )
        assert adopt.returncode == 0, f"`forge session adopt` failed: {adopt.stdout[-600:]!r} {adopt.stderr[-600:]!r}"

        manifest = _read_manifest(forge_workspace, _ADOPTED)
        confirmed = manifest.get("confirmed", {})
        assert confirmed.get("claude_session_id") == native_uuid
        adoption = confirmed.get("adoption")
        assert adoption is not None, "confirmed.adoption is unset, so the session does not record where it came from"
        assert adoption.get("source_runtime") == SOURCE_RUNTIME_CLAUDE

        decoy_uuid = _read_manifest(forge_workspace, _DECOY).get("confirmed", {}).get("claude_session_id")
        assert native_uuid != decoy_uuid, "the adopted id collided with the pre-existing session's pre-seeded id"

        # 4. Forge's own predicate must accept a transcript it never wrote. This is
        #    the check that unit fixtures cannot stand in for.
        probe = forge_workspace.exec(
            f"cat > /tmp/_resumable.py << 'PROBE_EOF'\n{_RESUMABLE_PROBE}\nPROBE_EOF\n"
            f"{_CONTAINER_PY} /tmp/_resumable.py /workspace {_ADOPTED}"
        )
        assert probe.returncode == 0, f"resumability probe failed: {probe.stderr[-400:]!r}"
        verdict = json.loads(probe.stdout.strip().splitlines()[-1])
        assert verdict["resumable"] is True, (
            f"Forge does not consider the adopted session resumable ({verdict!r}); "
            f"`forge session resume {_ADOPTED}` would launch fresh instead of reattaching"
        )

        # 5. Continue it the way a bare `forge session resume` dispatches: plain
        #    --resume, no --fork-session.
        cont_exit, cont_stdout, cont_stderr = run_claude_print(
            forge_workspace,
            prompt=CONTINUE_PROMPT,
            session_name=_ADOPTED,
            resume_id=native_uuid,
            timeout=90,
        )
        cont_tail = (
            f"\n---- continue stdout (tail) ----\n{cont_stdout[-1000:]}"
            f"\n---- continue stderr (tail) ----\n{cont_stderr[-1000:]}"
        )
        assert cont_exit == 0, f"resuming the adopted conversation failed (exit={cont_exit}).{cont_tail}"

        # Continuity, not just a successful call: the model can only answer from the
        # pre-adoption turn. A --resume that silently started fresh would exit 0.
        assert _NUMBER in cont_stdout, (
            f"the resumed turn did not recall {_NUMBER!r} from the pre-adoption conversation, so adoption "
            f"bound an id without carrying the history it points at.{cont_tail}"
        )

        # 6. The user's transcript is still theirs.
        encoded = forge_workspace.exec(
            f'{_CONTAINER_PY} -c "from forge.session.claude.paths import get_transcript_path; '
            f"print(get_transcript_path('/workspace', '{native_uuid}'))\""
        )
        assert encoded.returncode == 0, f"could not resolve the native transcript path: {encoded.stderr[:200]!r}"
        native_path = encoded.stdout.strip()
        assert forge_workspace.file_exists(
            native_path
        ), f"adoption removed or moved the user's native transcript at {native_path}"
