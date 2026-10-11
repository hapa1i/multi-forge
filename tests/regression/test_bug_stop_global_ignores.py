"""Global Git excludes must not become raw snapshots or Stop reviewer input."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from forge.policy.semantic import stop_review as review
from forge.policy.semantic.supervisor import SupervisorRun
from forge.policy.types import PolicyDecision
from tests.fixtures.stop_review import changed, context, deadline, git

pytestmark = pytest.mark.regression


def test_globally_ignored_content_never_enters_stop_evidence(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    ignore = tmp_path / "global-ignore"
    ignore.write_text(".env\n")
    config = tmp_path / "gitconfig"
    config.write_text(f'[core]\nexcludesFile = "{ignore}"\n')
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    private = ctx.checkout / ".env"
    private.write_text("SYNTHETIC_IGNORED_BEFORE\n")
    assert git(ctx.checkout, "ls-files", "--others", "--exclude-standard", "-z") == b""
    review.begin_turn(ctx, deadline=deadline())
    private.write_text("SYNTHETIC_IGNORED_AFTER\n")
    changed(ctx, "visible work\n", start=False)
    call = Mock(return_value=SupervisorRun(PolicyDecision("allow", "semantic.supervisor"), run_ok=True, parsed=True))
    monkeypatch.setattr(review, "run_supervisor_check", call)
    outcome = review.review_stop(ctx, deadline=deadline(), current_config=lambda: ctx.config_digest)
    assert outcome.complete
    assert call.call_count == 1
    sent = call.call_args.args[1].raw_diff
    assert "visible work" in sent
    assert "SYNTHETIC_IGNORED" not in sent
    assert '".env"' not in sent
    for path in ctx.storage.iterdir():
        if path.suffix in {".blob", ".snapshot"}:
            assert b"SYNTHETIC_IGNORED" not in path.read_bytes()
            if path.suffix == ".snapshot":
                assert b'".env"' not in path.read_bytes()
