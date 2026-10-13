"""Owned-store isolation, refusal and fresh native-index behavior without inference."""

import json
import os

import pytest

from forge.core.reactive import codex_reviewer_home as reviewer
from forge.core.runtime.codex_review_source import bind_source, select_source
from tests.fixtures.native_supervisor import (
    THREAD,
    allow_synthetic_instructions,
    synthetic_rows,
    write_rollout,
)


@pytest.fixture
def owned(tmp_path, monkeypatch):
    monkeypatch.setattr(reviewer, "get_forge_home", lambda: tmp_path / "forge")
    monkeypatch.setattr(reviewer, "require_codex_fork_binary", lambda: "/tested/codex")
    home = reviewer.initialize_home(extra_usage_off=True)
    (home / "auth.json").write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "account_id": "synthetic-account",
                    "access_token": "synthetic-access",
                    "refresh_token": "synthetic-refresh",
                },
            }
        )
    )
    return home


@pytest.fixture
def selection(tmp_path, monkeypatch):
    home = tmp_path / "source"
    monkeypatch.setenv("CODEX_HOME", str(home))
    allow_synthetic_instructions(monkeypatch)
    write_rollout(home, synthetic_rows())
    return select_source(
        bind_source(THREAD, forge_root=None),
        model="gpt-6.1-sol",
        auth_mode="subscription-only",
        plan="",
        trigger="pre-tool-use",
        executor_origin="claude_code",
        boundary=None,
    )


def test_copies_are_immutable_and_every_attempt_has_a_fresh_index(owned, selection):
    source = selection.prefixes[0].path.read_bytes()
    with reviewer.prepare_reviewer_home(selection, auth_mode="subscription-only") as first:
        (first.sqlite_home / "state.sqlite").write_text("previous native projection")
        assert reviewer.verify_selected_inputs(first.home, selection)
        with pytest.raises(ValueError, match="owns the reviewer"):
            with reviewer.reviewer_lease(owned):
                pytest.fail("Leased input cannot be replaced")
    with reviewer.prepare_reviewer_home(selection, auth_mode="subscription-only") as second:
        assert not (second.sqlite_home / "state.sqlite").exists()
        assert reviewer.verify_selected_inputs(second.home, selection)
        assert len(list((second.home / "sessions").glob("**/*.jsonl"))) == 1
    assert selection.prefixes[0].path.read_bytes() == source


def test_unmarked_input_tree_is_never_deleted(owned, selection):
    (owned / "sessions").mkdir()
    unrelated = owned / "sessions/keep.txt"
    unrelated.write_text("unrelated")
    with pytest.raises(OSError):
        with reviewer.prepare_reviewer_home(selection, auth_mode="subscription-only"):
            pytest.fail("Unmarked tree was admitted")
    assert unrelated.read_text() == "unrelated"


def test_wrong_account_and_unverified_auth_refuse_without_touching_sources(owned, selection):
    before = selection.prefixes[0].path.read_bytes()
    auth = json.loads((owned / "auth.json").read_text())
    auth["tokens"]["account_id"] = "other-account"
    (owned / "auth.json").write_text(json.dumps(auth))
    with pytest.raises(ValueError, match="account"):
        with reviewer.prepare_reviewer_home(selection, auth_mode="subscription-only"):
            pytest.fail("Cross-account review admitted")
    auth["auth_mode"] = "apikey"
    (owned / "auth.json").write_text(json.dumps(auth))
    status = reviewer.auth_status()
    assert not status["ready"] and "synthetic" not in json.dumps(status)
    assert selection.prefixes[0].path.read_bytes() == before


def test_existing_or_symlinked_home_is_not_claimed(tmp_path, monkeypatch):
    monkeypatch.setattr(reviewer, "get_forge_home", lambda: tmp_path / "forge")
    home = reviewer.reviewer_home()
    home.mkdir(parents=True, mode=0o700)
    secret = home / "auth.json"
    secret.write_text("unrelated login")
    with pytest.raises(OSError):
        reviewer.initialize_home(extra_usage_off=True)
    assert secret.read_text() == "unrelated login"
    moved = home.with_name("other")
    home.rename(moved)
    home.symlink_to(moved, target_is_directory=True)
    with pytest.raises(OSError):
        reviewer.initialize_home(extra_usage_off=True)
    assert (moved / "auth.json").read_text() == "unrelated login"


def test_subscription_child_has_no_executor_or_provider_routing(owned, monkeypatch):
    values = {
        "FORGE_SESSION": "executor",
        "FORGE_FORGE_ROOT": "/executor",
        "FORGE_RUN_ID": "parent",
        "FORGE_DEV": "/code",
        "FORGE_CODEX_EXECUTOR_IDENTITY": "trusted-parent",
        "CODEX_THREAD_ID": THREAD,
        "OPENAI_API_KEY": "synthetic-openai",
        "CODEX_API_KEY": "synthetic-codex",
        "CODEX_ACCESS_TOKEN": "synthetic-token",
        "ANTHROPIC_BASE_URL": "https://example.invalid",
        "HTTPS_PROXY": "https://example.invalid",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    env = reviewer.reviewer_environment(owned)
    assert not values.keys() & env.keys()
    assert env["CODEX_HOME"] == str(owned) and env["FORGE_DEPTH"] == "2"
    assert os.environ["FORGE_SESSION"] == "executor"


def test_api_attempt_uses_only_explicit_key_and_does_not_open_subscription_auth(owned, selection, monkeypatch):
    monkeypatch.setattr("forge.core.runtime.codex_preflight.codex_api_key_for_subprocess", lambda: "synthetic-key")
    monkeypatch.setattr(reviewer, "_account", lambda _: pytest.fail("API must not inspect subscription login"))
    original = (owned / "auth.json").read_bytes()
    with reviewer.prepare_reviewer_home(selection, auth_mode="api") as prepared:
        assert prepared.home != owned and not (prepared.home / "auth.json").exists()
        assert prepared.env["CODEX_API_KEY"] == "synthetic-key"
    assert not prepared.home.exists()
    assert (owned / "auth.json").read_bytes() == original


def test_logout_refuses_an_active_lease_without_invoking_native_login(owned, monkeypatch):
    monkeypatch.setattr(reviewer.subprocess, "run", lambda *a, **kw: pytest.fail("Must not log out an active reviewer"))
    with reviewer.reviewer_lease(owned):
        with pytest.raises(ValueError, match="owns the reviewer"):
            reviewer.auth_logout()


def test_abandoned_api_inputs_recover_only_after_lease_release(owned, selection, monkeypatch):
    monkeypatch.setattr("forge.core.runtime.codex_preflight.codex_api_key_for_subprocess", lambda: "synthetic-key")
    abandoned = owned.with_name("codex-api-abandoned")
    abandoned.mkdir(mode=0o700)
    (abandoned / reviewer.MARKER).write_text(json.dumps({"version": 1, "extra_usage_off_asserted": False}))
    (abandoned / "review.lock").touch(mode=0o600)
    unmarked = owned.with_name("codex-api-unmarked")
    unmarked.mkdir()
    with reviewer.reviewer_lease(abandoned):
        with reviewer.prepare_reviewer_home(selection, auth_mode="api"):
            assert abandoned.exists() and unmarked.exists()
    with reviewer.prepare_reviewer_home(selection, auth_mode="api"):
        assert not abandoned.exists() and unmarked.exists()


def test_binary_replacement_invalidates_admission(tmp_path, monkeypatch):
    import hashlib

    executable = tmp_path / "codex"
    executable.write_bytes(b"verified fixture executable")
    monkeypatch.setattr(reviewer.sys, "platform", "darwin")
    monkeypatch.setattr(reviewer.shutil, "which", lambda _: str(executable))
    monkeypatch.setattr(reviewer, "_BINARY_SHA256", hashlib.sha256(executable.read_bytes()).hexdigest())
    assert reviewer.require_codex_fork_binary() == str(executable)
    executable.write_bytes(b"changed fixture executable!")
    with pytest.raises(ValueError, match="untested"):
        reviewer.require_codex_fork_binary()
    monkeypatch.setattr(reviewer.sys, "platform", "linux")
    with pytest.raises(ValueError, match="macOS"):
        reviewer.require_codex_fork_binary()


def test_admitted_digest_is_reused_across_processes_until_the_inode_changes(tmp_path, monkeypatch):
    import hashlib

    executable = tmp_path / "codex"
    executable.write_bytes(b"verified fixture executable")
    monkeypatch.setattr(reviewer.sys, "platform", "darwin")
    monkeypatch.setattr(reviewer.shutil, "which", lambda _: str(executable))
    monkeypatch.setattr(reviewer, "_BINARY_SHA256", hashlib.sha256(executable.read_bytes()).hexdigest())
    reviewer._binary_cache.clear()
    assert reviewer.require_codex_fork_binary() == str(executable)

    reviewer._binary_cache.clear()  # A later one-shot hook process.
    original = reviewer.hashlib.file_digest
    monkeypatch.setattr(reviewer.hashlib, "file_digest", lambda *a, **kw: pytest.fail("Unchanged binary rehashed"))
    assert reviewer.require_codex_fork_binary() == str(executable)

    monkeypatch.setattr(reviewer.hashlib, "file_digest", original)
    executable.write_bytes(b"changed fixture executable!")  # Same size; ctime and mtime move.
    reviewer._binary_cache.clear()
    with pytest.raises(ValueError, match="untested"):
        reviewer.require_codex_fork_binary()


def test_malformed_digest_cache_is_recomputed(tmp_path, monkeypatch):
    import hashlib

    executable = tmp_path / "codex"
    executable.write_bytes(b"verified fixture executable")
    monkeypatch.setattr(reviewer.sys, "platform", "darwin")
    monkeypatch.setattr(reviewer.shutil, "which", lambda _: str(executable))
    monkeypatch.setattr(reviewer, "_BINARY_SHA256", hashlib.sha256(executable.read_bytes()).hexdigest())
    cache = reviewer.get_forge_home() / "runtime" / "codex-fork-binary.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("{not json")
    reviewer._binary_cache.clear()
    assert reviewer.require_codex_fork_binary() == str(executable)
