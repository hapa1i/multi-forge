"""B5: abandoned-home cleanup could delete a fresh API reviewer home before it was leased."""

import os
from pathlib import Path

import pytest

from forge.core.reactive import codex_reviewer_home as reviewer
from tests.src.core.reactive.test_codex_reviewer_home import owned as owned
from tests.src.core.reactive.test_codex_reviewer_home import selection as selection

pytestmark = pytest.mark.regression


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setattr("forge.core.runtime.codex_preflight.codex_api_key_for_subprocess", lambda: "synthetic-key")


def test_concurrent_cleanup_before_the_first_lease_keeps_the_new_home(owned, selection, api_key, monkeypatch):
    # Run another attempt's cleanup at the worst moment: after this attempt creates
    # its home, immediately before it first takes the home's lease.
    created: list[str] = []
    racing: list[bool] = []
    original_mkdtemp = reviewer.tempfile.mkdtemp
    original_flock = reviewer.fcntl.flock

    def mkdtemp(*args, **kwargs):
        created.append(original_mkdtemp(*args, **kwargs))
        return created[-1]

    def flock(descriptor, operation):
        if created and not racing:
            racing.append(True)
            reviewer._clean_abandoned_api_homes(Path(created[0]).parent)
        return original_flock(descriptor, operation)

    monkeypatch.setattr(reviewer.tempfile, "mkdtemp", mkdtemp)
    monkeypatch.setattr(reviewer.fcntl, "flock", flock)
    with reviewer.prepare_reviewer_home(selection, auth_mode="api") as prepared:
        assert racing and prepared.home.exists() and reviewer.verify_selected_inputs(prepared.home, selection)
    assert not list(owned.parent.glob("codex-api-*"))


def test_unmarked_api_home_is_removed_when_marking_fails(owned, selection, api_key, monkeypatch):
    original_open, original_write_text = os.open, Path.write_text

    def fail_marker(name):
        if os.fspath(name).endswith(reviewer.MARKER):
            raise OSError("disk full")

    def open_(path, flags, *args, **kwargs):
        if flags & os.O_CREAT:
            fail_marker(path)
        return original_open(path, flags, *args, **kwargs)

    def write_text(self, *args, **kwargs):
        fail_marker(self)
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(reviewer.os, "open", open_)
    monkeypatch.setattr(Path, "write_text", write_text)
    with pytest.raises(OSError, match="disk full"):
        with reviewer.prepare_reviewer_home(selection, auth_mode="api"):
            pytest.fail("Setup failed before staging")
    # Cleanup claims only marked homes, so an unmarked leftover would never be collected.
    assert not list(owned.parent.glob("codex-api-*"))
