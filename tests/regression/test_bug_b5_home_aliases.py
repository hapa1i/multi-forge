"""B5 accepts configured root aliases, but never aliases within owned stores."""

from dataclasses import replace
from pathlib import Path

import pytest

from forge.core.reactive import codex_reviewer_home as reviewer
from forge.core.runtime.codex_review_source import bind_source
from tests.fixtures.native_supervisor import THREAD, synthetic_rows, write_rollout
from tests.src.core.reactive.test_codex_reviewer_home import owned as owned
from tests.src.core.runtime.test_codex_review_source import select
from tests.src.core.runtime.test_codex_review_source import source_home as source_home

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("default_home", [False, True])
def test_codex_home_alias_and_previously_saved_alias_binding(source_home, monkeypatch, default_home):
    path = write_rollout(source_home, synthetic_rows())
    alias = Path.home() / ".codex" if default_home else source_home.parent / "codex-alias"
    alias.symlink_to(source_home, target_is_directory=True)
    if default_home:
        monkeypatch.delenv("CODEX_HOME")
    else:
        monkeypatch.setenv("CODEX_HOME", str(alias))
    bound = bind_source(THREAD, forge_root=None)
    assert Path(bound.home) == source_home.resolve()
    legacy = replace(bound, home=str(alias), rollout_path=str(alias / path.relative_to(source_home)))
    assert select(legacy).prefixes[0].path == path.resolve()
    sessions = source_home / "sessions"
    sessions.rename(source_home / "linked-sessions")
    sessions.symlink_to(source_home / "linked-sessions", target_is_directory=True)
    with pytest.raises(OSError):
        select(bound)


def test_forge_home_alias_allows_auth_but_reviewer_subdirectory_alias_is_refused(owned, monkeypatch):
    root = owned.parent.parent
    alias = root.with_name("forge-alias")
    alias.symlink_to(root, target_is_directory=True)
    monkeypatch.setattr(reviewer, "get_forge_home", lambda: alias)
    assert reviewer.reviewer_home() == owned
    assert reviewer.auth_status()["ready"]
    with reviewer.reviewer_lease(reviewer.initialize_home(extra_usage_off=True)):
        reviewer.require_reviewer_auth("subscription-only")
    moved = owned.with_name("moved")
    owned.rename(moved)
    owned.symlink_to(moved, target_is_directory=True)
    assert not reviewer.auth_status()["ready"]
