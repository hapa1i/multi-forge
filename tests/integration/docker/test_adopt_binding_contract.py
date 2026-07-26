"""Adoption binding contract: a plain ``--resume`` keeps the same session id.

`forge session adopt` (docs/board/doing/native_session_adoption) binds a Forge
manifest to an existing native conversation by writing
``confirmed.claude_session_id``. The first Forge-managed Stop then rewrites that
field **unconditionally** from the Stop payload
(``src/forge/cli/hooks/commands.py:179``), so an adopted binding survives only if
a plain ``claude --resume <uuid>`` reattach reports the original id. If Claude
ever reported a fresh id on reattach, an adopted session would silently unbind
after one turn and point at a conversation the user never adopted.

Local transcript evidence cannot answer this: Forge does not record reconnects
distinguishably, so no on-disk sample observes the reattach leg. This gate is the
only place the invariant is actually seen.

Observable: the Stop handler writes the payload's ``session_id`` verbatim into
each artifact entry (``commands.py:169``) and ``_append_artifact_entry`` appends
without dedup, so ``confirmed.artifacts.transcripts`` is an append-only log of
every Stop payload. Claude invokes Stop repeatedly as a transcript grows
(``commands.py:541-544``), so the assertion is that *every* recorded payload
carries the original id -- not that exactly two entries exist.

Run:
    ./scripts/test-integration.sh tests/integration/docker/test_adopt_binding_contract.py -v
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from tests.fixtures.docker import ContainerLike
from tests.integration.docker.conftest import run_claude_print, setup_real_claude

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_in,
    pytest.mark.slow,
]

# The Claude Code version this reattach-identity guard was last confirmed against.
# Reported (not hard-asserted) so a routine CLI bump does not red the suite, while a
# real identity REGRESSION still fails on the payload assertions below. Bump after a
# green run and record the date in the card's checklist.
CLAUDE_VERSION_VALIDATED = "2.1.220"

_SESSION = "adopt-binding-gate"
_MANIFEST = f"/workspace/.forge/sessions/{_SESSION}/forge.session.json"
# Artifacts live under .forge/artifacts/<session>/, NOT beside the manifest
# under .forge/sessions/<session>/ (session/artifacts.py:89-96).
_TRANSCRIPT_ARTIFACTS = f"/workspace/.forge/artifacts/{_SESSION}/transcripts"

FIRST_PROMPT = "Say just the word one"
RESUME_PROMPT = "Say just the word two"

# Artifact reasons written by _capture_transcript_artifact (commands.py:550, :755) --
# the two paths that also rewrite confirmed.claude_session_id from the payload.
_BINDING_REASONS = frozenset({"stop", "stop-failure"})


@pytest.fixture(scope="module", autouse=True)
def _require_anthropic_api_key() -> None:
    """Fail loudly if the API key is missing (never-skip policy)."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.fail("ANTHROPIC_API_KEY not set. Add it to your environment/.env and re-run integration tests.")


def _container_claude_version(workspace: ContainerLike) -> str:
    result = workspace.exec("claude --version")
    if result.returncode != 0:
        pytest.fail(f"`claude --version` failed in container (rc={result.returncode}): {result.stderr[:200]!r}")
    return result.stdout.strip()


def _read_manifest(workspace: ContainerLike) -> dict[str, Any]:
    result = workspace.exec(f"cat {_MANIFEST}")
    if result.returncode != 0:
        pytest.fail(f"Could not read manifest {_MANIFEST}: {result.stderr[:200]!r}")
    payload: dict[str, Any] = json.loads(result.stdout)
    return payload


def _stop_payload_ids(manifest: dict[str, Any]) -> list[str | None]:
    """Session ids recorded by each binding-rewriting Stop payload, oldest first.

    Filtered to the reasons written by ``_capture_transcript_artifact`` -- exactly
    the entries that also rewrite ``confirmed.claude_session_id``
    (``cli/hooks/commands.py:179``), so the list matches the contract under test.
    ``reason="pre-compact"`` (``commands.py:875``) shares this artifact list but
    OMITS ``session_id`` entirely, and would otherwise read as a ``None`` drift.
    """
    entries = manifest.get("confirmed", {}).get("artifacts", {}).get("transcripts", [])
    if not isinstance(entries, list):
        pytest.fail(f"confirmed.artifacts.transcripts is not a list: {entries!r}")
    return [entry.get("session_id") for entry in entries if entry.get("reason") in _BINDING_REASONS]


class TestAdoptBindingContract:
    """The reattach-identity gate adoption's binding rests on (real Claude)."""

    def test_plain_resume_reports_the_original_session_id(self, forge_workspace: ContainerLike) -> None:
        setup_real_claude(forge_workspace, session_name=_SESSION)
        version = _container_claude_version(forge_workspace)

        first_exit, first_stdout, first_stderr = run_claude_print(
            forge_workspace,
            prompt=FIRST_PROMPT,
            session_name=_SESSION,
            timeout=60,
        )
        first_tail = (
            f"\n---- turn 1 stdout (tail) ----\n{first_stdout[-1000:]}"
            f"\n---- turn 1 stderr (tail) ----\n{first_stderr[-1000:]}"
        )
        # Unlike the best-effort hook smoke tests, this gate needs a real conversation
        # to exist before it can mean anything -- a degraded turn 1 would make every
        # downstream identity assertion untrustworthy rather than merely noisy.
        assert first_exit == 0, f"turn 1 `claude --print` failed on {version} (exit={first_exit}).{first_tail}"

        original_uuid = _read_manifest(forge_workspace).get("confirmed", {}).get("claude_session_id")
        assert original_uuid, (
            f"SessionStart/Stop did not record a claude_session_id on claude {version}; "
            f"the gate cannot run.{first_tail}"
        )

        ids_after_first = _stop_payload_ids(_read_manifest(forge_workspace))
        assert ids_after_first, (
            f"no {sorted(_BINDING_REASONS)} transcript artifact after turn 1 on claude {version}, so no payload "
            f"session_id is observable and the gate would pass vacuously.{first_tail}"
        )

        # Plain reattach: --resume without --fork-session, the exact dispatch a
        # bare `forge session resume <adopted>` produces.
        resume_exit, resume_stdout, resume_stderr = run_claude_print(
            forge_workspace,
            prompt=RESUME_PROMPT,
            session_name=_SESSION,
            resume_id=original_uuid,
            timeout=60,
        )
        tail = (
            f"\n---- resume stdout (tail) ----\n{resume_stdout[-1000:]}"
            f"\n---- resume stderr (tail) ----\n{resume_stderr[-1000:]}"
        )
        assert resume_exit == 0, f"plain `claude --resume` failed on {version} (exit={resume_exit}).{tail}"

        manifest_after = _read_manifest(forge_workspace)
        ids_after_resume = _stop_payload_ids(manifest_after)
        assert len(ids_after_resume) > len(ids_after_first), (
            f"the reattach turn produced no new Stop artifact entry on claude {version}, so the reattach "
            f"payload was never observed (before={len(ids_after_first)}, after={len(ids_after_resume)}).{tail}"
        )

        # THE contract: every Stop payload across both turns reported the same id.
        drifted = [recorded for recorded in ids_after_resume if recorded != original_uuid]
        assert not drifted, (
            f"REATTACH-DRIFT on claude {version} (validated {CLAUDE_VERSION_VALIDATED}): a plain "
            f"`--resume {original_uuid}` reported a different session_id in a Stop payload -- recorded ids "
            f"{ids_after_resume!r}. commands.py:179 rewrites confirmed.claude_session_id from that payload "
            f"unconditionally, so an adopted binding would silently drift after one turn. Adoption cannot "
            f"rely on Stop idempotency; Slice 2 needs an explicit guard.{tail}"
        )

        assert manifest_after.get("confirmed", {}).get("claude_session_id") == original_uuid, (
            f"confirmed.claude_session_id changed across a plain reattach on claude {version} even though "
            f"every Stop payload matched -- another writer moved the binding."
        )

        # Corroboration: one conversation means one UUID-named artifact file.
        listing = forge_workspace.exec(f"ls {_TRANSCRIPT_ARTIFACTS}/*.jsonl 2>/dev/null | wc -l")
        assert listing.stdout.strip() == "1", (
            f"expected exactly one UUID-named transcript artifact after a reattach on claude {version}; "
            f"found {listing.stdout.strip()!r}, which means a second session id reached the artifact path."
        )

        # The identity result only means something if the reattach actually continued the
        # conversation. A --resume that silently started fresh under the same id would pass
        # every assertion above, so require both turns in the one captured transcript.
        captured = forge_workspace.exec(f"cat {_TRANSCRIPT_ARTIFACTS}/{original_uuid}.jsonl")
        assert captured.returncode == 0, f"could not read the captured transcript: {captured.stderr[:200]!r}"
        for prompt in (FIRST_PROMPT, RESUME_PROMPT):
            assert prompt in captured.stdout, (
                f"captured transcript for {original_uuid} is missing {prompt!r} on claude {version}: the "
                f"reattach did not continue the original conversation, so the matching session_id does not "
                f"establish the binding contract."
            )
